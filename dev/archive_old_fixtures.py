"""Archive pre-refresh ebook fixtures after a format-breaking refresh.

Called from the validate-fixtures CI workflow when the Pass 1 test run (with
AO3_FIXTURE_MODE=current_only) fails: this means the newly-downloaded ebook in
test/fixtures/ebook/<work_id>/current/ is no longer parseable by update.py, so
we preserve the previous (working) version under the sibling archive/ folder
for regression testing against future parser fixes.

For each ebook file that is modified relative to HEAD, this script:
  1. Retrieves the pre-refresh bytes via `git show HEAD:<path>`.
  2. Computes a short sha256 hash of those bytes.
  3. Copies them to ebook/<work_id>/archive/<base>-<hash>.<ext>.
  4. Skips if the destination file already exists (identical content already
     archived on a prior run).

Only touches files under test/fixtures/ebook/*/current/ so that snapshot
regenerations or other diffs do not accidentally get archived.
"""

import hashlib
import os
import subprocess
import sys


FIXTURES_ROOT = os.path.join('test', 'fixtures', 'ebook')


def modified_current_files() -> list[str]:
    """Return ebook current/ paths modified vs HEAD (relative to repo root)."""

    result = subprocess.run(
        ['git', 'diff', '--name-only', 'HEAD', '--', FIXTURES_ROOT],
        check=True, capture_output=True, text=True,
    )
    # git reports paths with forward slashes on all platforms
    paths = result.stdout.strip().splitlines()
    return [p for p in paths if '/current/' in p]


def pre_refresh_bytes(path: str) -> bytes:
    """Retrieve the HEAD version of `path` as bytes."""

    result = subprocess.run(
        ['git', 'show', f'HEAD:{path}'],
        check=True, capture_output=True,
    )
    return result.stdout


def archive_path(current_path: str, content_hash: str) -> str:
    """Compute the archive destination path for a given current/ file + hash.

    current_path: e.g. test/fixtures/ebook/218676/current/incompleteWork.epub
    → test/fixtures/ebook/218676/archive/incompleteWork-<hash>.epub
    """
    work_dir = os.path.dirname(os.path.dirname(current_path))
    base = os.path.basename(current_path)
    name, ext = os.path.splitext(base)
    return os.path.join(work_dir, 'archive', f'{name}-{content_hash}{ext}')


def short_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def main() -> int:
    archived = []
    skipped = []
    for path in modified_current_files():
        try:
            old_bytes = pre_refresh_bytes(path)
        except subprocess.CalledProcessError:
            # path was newly added in this refresh, not pre-existing — nothing to archive
            print(f'skipping {path}: no HEAD version')
            continue

        content_hash = short_hash(old_bytes)
        dest = archive_path(path, content_hash)

        if os.path.exists(dest):
            skipped.append(dest)
            print(f'skipping {dest}: already archived')
            continue

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(old_bytes)
        archived.append(dest)
        print(f'archived {path} -> {dest}')

    print()
    print(f'{len(archived)} archived, {len(skipped)} skipped')
    return 0


if __name__ == '__main__':
    sys.exit(main())
