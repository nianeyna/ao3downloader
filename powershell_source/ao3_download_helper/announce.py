"""Say a new release is out: on Bluesky by the deploy, on X by its owner, by hand.

The post is the same on both sites but for its last line:

    v1.2.3 is live 🪄
    <the release note>
    ↪ https://github.com/alexandria-p/FicFairy/releases/latest     (X: it counts any link as 23)
    ↪ Get it here✨                                                (Bluesky: the words are the link)

**Bluesky** is posted to by the deploy (`deploy-hosted.yml`'s `announce` job) once the release's
three app zips are published, when `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` are set. Nothing
secret is printed. **X is never posted to by anything here** - its API now costs money, and a
script signing in with a password breaks its rules - so `preview` prints a link to X's own
compose page with the post written in (`x_intent_link`), for its owner to open and post once the
release is out. It is shown when they are asked to approve a merge's release note.

The release note is `.github/release-note.txt`, written for every pull request (see CLAUDE.md's
conventions). It is never cut short: `check` refuses a note that would not fit either site, and a
test runs it on the committed note, so one too long cannot be merged. A release whose note is the
same as the release before it - a push straight to main that did not write one - says
`FALLBACK_NOTE` instead on Bluesky, rather than announcing the last change twice.

**A release can go out unannounced**: a pull request whose release note is `SKIP_NOTE`
(`no-post`) and nothing else is not posted to Bluesky, and `preview` offers no X link for it.

    python announce.py check                      # does the committed note fit?
    python announce.py preview [--version 1.2.3]  # both posts, and the link to post on X
    python announce.py post --version 1.2.3 [--previous-note-file path]
    python announce.py release-notes --version 1.2.3  # the GitHub release's description

**The GitHub release's description** (`release_body`) opens with the note Bluesky was given,
under a "What's new" heading and a line, then how to install the app on each system, under an
"Installation instructions" heading of the same size. A release that is not announced
(`SKIP_NOTE`) has no "What's new". The three app builds
write it with `release-notes`, whichever of them makes the release first.
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTE_FILE = ROOT / '.github' / 'release-note.txt'
RELEASE_LINK = 'https://github.com/alexandria-p/FicFairy/releases/latest'
FALLBACK_NOTE = 'Small fixes and improvements.'
# a release note that is only this posts nothing: the release goes out unannounced
SKIP_NOTE = 'no-post'
# what Bluesky shows, linked to RELEASE_LINK: there a link's text counts in full, so the words
# stand in for the address
LINK_LABEL = 'Get it here'
# after the linked words, not part of them
LINK_SPARKLE = '\u2728'
ARROW = '\u21aa'

X_LIMIT = 280
# X counts every link as this long, whatever its length (its t.co wrapping)
X_LINK_LENGTH = 23
BLUESKY_LIMIT = 300

# X's own compose page: opens with the text given, for its owner to post
X_INTENT_URL = 'https://x.com/intent/post'
BLUESKY_SERVICE = 'https://bsky.social'
TIMEOUT_SECONDS = 30


# region what is posted

def headline(version: str) -> str:
    return f'v{version} is live 🪄'


def compose_x(version: str, note: str) -> str:
    """The post on X: the address itself, which X shows shortened and counts as 23."""

    return f'{headline(version)}\n{note.strip()}\n{ARROW} {RELEASE_LINK}'


def compose_bluesky(version: str, note: str) -> str:
    """The post on Bluesky: `LINK_LABEL` in place of the address, made a link (`link_facets`)."""

    return f'{headline(version)}\n{note.strip()}\n{ARROW} {LINK_LABEL}{LINK_SPARKLE}'


def read_note(path: Path = NOTE_FILE) -> str:
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def skipped(note: str) -> bool:
    """Whether this release is not to be announced at all (its note is `SKIP_NOTE`)."""

    return note.strip().lower() == SKIP_NOTE


def note_for(note: str, previous: str) -> str:
    """The note to post: the committed one, unless it is the last release's again (or empty).
    `SKIP_NOTE` is kept whatever the last release said, so it is never posted as the fallback."""

    note = note.strip()
    if skipped(note):
        return note
    return note if note and note != previous.strip() else FALLBACK_NOTE


def _x_weight(char: str) -> int:
    # X's own rule (twitter-text): most Latin, Greek and Cyrillic text, and general punctuation,
    # counts 1; anything else - emoji, CJK - counts 2. The joiner, selector and skin tones inside
    # an emoji count nothing here; an emoji made of several joined together, 2 to X, is counted
    # per part - over, never under, so a note that passes always fits
    code = ord(char)
    if code in (0x200D, 0xFE0F) or 0x1F3FB <= code <= 0x1F3FF:
        return 0
    if code <= 4351 or 8192 <= code <= 8205 or 8208 <= code <= 8223 or 8242 <= code <= 8247:
        return 1
    return 2


def x_length(text: str) -> int:
    """How long X counts `text`: the release link as `X_LINK_LENGTH`, the rest by weight."""

    parts = text.split(RELEASE_LINK)
    return sum(sum(_x_weight(c) for c in part) for part in parts) + X_LINK_LENGTH * (len(parts) - 1)


def bluesky_length(text: str) -> int:
    """How long Bluesky counts `text` - at most this: it counts graphemes, and a character is
    never fewer than one. Counting code points can only overcount, so a post that passes fits."""

    return len(text)


def problems(version: str, note: str) -> list[str]:
    """Why a post with `note` could not go out whole, or [] when it can (or is not to go out)."""

    if skipped(note):
        return []
    found = []
    if not note.strip():
        found.append('the release note is empty')
    if RELEASE_LINK in note or 'http://' in note or 'https://' in note:
        found.append('the release note has a link in it - the post adds the release link itself')
    on_x, on_bluesky = x_length(compose_x(version, note)), bluesky_length(compose_bluesky(version, note))
    if on_x > X_LIMIT:
        found.append(f'too long for X by {on_x - X_LIMIT} (counted as {on_x} of {X_LIMIT})')
    if on_bluesky > BLUESKY_LIMIT:
        found.append(f'too long for Bluesky by {on_bluesky - BLUESKY_LIMIT} '
                     f'(counted as {on_bluesky} of {BLUESKY_LIMIT})')
    return found


# the longest version a note has to leave room for: three numbers of four digits each
LONGEST_VERSION = '9999.9999.9999'

# endregion

# region the github release

NEW_HEADING = "## What's new"
INSTALL_HEADING = '## Installation instructions'

INSTALL_NOTES = '''\
**Windows:**

* Download the zip, extract the files, and double-click ficfairy.exe.
* Windows may warn that the app is not signed: choose More info, then Run anyway.

**Mac (M1 or later):**

* Download ficfairy-ao3downloader-macos-apple-silicon.zip

**Mac (Intel):**

* Download ficfairy-ao3downloader-macos-intel.zip

* Open the zip, and double-click Start FicFairy.command.
* The first time, macOS may say it cannot check the app. Click Done, then System Settings > Privacy & Security > Open Anyway.

**Linux (64-bit Intel or AMD):**

* Download the zip, extract the files, and run Start FicFairy.sh.

**Remember: If you wish to read & write files to your local filesystem, you must use a Chromium browser.** (Chrome, Opera, Edge, Brave, Arc) Disregard if you plan to use Dropbox instead as your file-management solution.

If you are stuck, a README inside each zip has more details.'''


def release_body(note: str) -> str:
    """The GitHub release's description: the note Bluesky is given (as `note_for` chose it)
    under a "What's new" heading, a line under it, then `INSTALL_NOTES` under an "Installation
    instructions" heading of the same size - or only the instructions for a release not
    announced."""

    install = f"{INSTALL_HEADING}\n\n{INSTALL_NOTES}\n"
    if skipped(note) or not note.strip():
        return install
    return f"{NEW_HEADING}\n\n{note.strip()}\n\n---\n\n{install}"


def previous_note(version: str, root: Path = ROOT) -> str:
    """The release note as the release before `version` had it, or '' when there is none - read
    from the tags, as the deploy's `announce` job does."""

    try:
        subprocess.run(['git', 'fetch', '--tags', '--force', '--quiet'], cwd=root, capture_output=True, timeout=120)
        tags = subprocess.run(['git', 'tag', '-l', 'v*', '--sort=-v:refname'], cwd=root,
                              capture_output=True, text=True, timeout=60).stdout.split()
        if f'v{version}' not in tags:
            return ''
        older = tags[tags.index(f'v{version}') + 1:]
        if not older:
            return ''
        shown = subprocess.run(['git', 'show', f'{older[0]}:.github/release-note.txt'], cwd=root,
                               capture_output=True, text=True, timeout=60)
        return shown.stdout if shown.returncode == 0 else ''
    except Exception:
        return ''

# endregion

# region posting

def post_bluesky(session, text: str, handle: str, password: str, service: str = BLUESKY_SERVICE) -> str:
    """Post `text` to Bluesky, its release link made a link. Answers the post's address."""

    login = session.post(f'{service}/xrpc/com.atproto.server.createSession',
                         json={'identifier': handle, 'password': password}, timeout=TIMEOUT_SECONDS)
    if login.status_code != 200:
        raise RuntimeError(f'Bluesky refused the sign-in ({login.status_code})')
    account = login.json()
    record = {
        '$type': 'app.bsky.feed.post',
        'text': text,
        'createdAt': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'langs': ['en'],
        'facets': link_facets(text),
    }
    made = session.post(f'{service}/xrpc/com.atproto.repo.createRecord',
                        headers={'Authorization': f'Bearer {account["accessJwt"]}'},
                        json={'repo': account['did'], 'collection': 'app.bsky.feed.post', 'record': record},
                        timeout=TIMEOUT_SECONDS)
    if made.status_code != 200:
        raise RuntimeError(f'Bluesky refused the post ({made.status_code}): {made.text[:200]}')
    return made.json().get('uri', '')


def link_facets(text: str) -> list[dict]:
    """Bluesky shows a link only where a facet says so, placed by UTF-8 byte offsets: the last
    `LINK_LABEL` in the post, opening `RELEASE_LINK`."""

    at = text.rfind(LINK_LABEL)
    if at < 0:
        return []
    start = len(text[:at].encode('utf-8'))
    return [{
        'index': {'byteStart': start, 'byteEnd': start + len(LINK_LABEL.encode('utf-8'))},
        'features': [{'$type': 'app.bsky.richtext.facet#link', 'uri': RELEASE_LINK}],
    }]


def announce(version: str, note: str, environ, session) -> bool:
    """Post to Bluesky, when its secrets are set. True when nothing that was tried failed."""

    if skipped(note):
        print(f'::notice::not posted to Bluesky - the release note is "{SKIP_NOTE}"')
        return True
    found = problems(version, note)
    if found:
        print('not posted: ' + '; '.join(found))
        return False
    text = compose_bluesky(version, note)
    handle, password = environ.get('BLUESKY_HANDLE', ''), environ.get('BLUESKY_APP_PASSWORD', '')
    if not (handle and password):
        print('::notice::not posted to Bluesky - set BLUESKY_HANDLE and BLUESKY_APP_PASSWORD')
        return True
    print('posting to Bluesky:\n' + text)
    try:
        print('bluesky: posted ' + post_bluesky(session, text, handle, password))
        return True
    except Exception as error:
        print(f'bluesky: not posted - {error}')
        return False


def x_intent_link(version: str, note: str) -> str:
    """X's compose page with the post written in - opened by hand, so X's API is never used."""

    return f'{X_INTENT_URL}?{urllib.parse.urlencode({"text": compose_x(version, note)}, quote_via=urllib.parse.quote)}'


def coming_version(root: Path = ROOT) -> str:
    """The version the next deploy will give main - worked out as the deploy does
    (`deploy_config.next_version`) from the `v*` tags and `VERSION` - or 'X.Y.Z' when it cannot
    be told. Only a guess until the deploy runs: another release first takes this number."""

    try:
        subprocess.run(['git', 'fetch', '--tags', '--quiet'], cwd=root, capture_output=True, timeout=60)
        tags = subprocess.run(['git', 'tag', '-l', 'v*'], cwd=root, capture_output=True,
                              text=True, timeout=60).stdout.split()
        from deploy_config import next_version
        return next_version(tags, (root / 'VERSION').read_text(encoding='utf-8'))
    except Exception:
        return 'X.Y.Z'


def preview_text(version: str, note: str) -> str:
    """Both posts as they would go out, each with how its site counts it, and the link that
    posts X's - shown before a merge."""

    if skipped(note):
        return (f'No posts for this release: the release note is "{SKIP_NOTE}".\n'
                'Bluesky will not be posted to, and there is no link to post on X.')
    on_x, on_bluesky = compose_x(version, note), compose_bluesky(version, note)
    lines = [f'X ({x_length(on_x)} of {X_LIMIT}) - posted by you, from the link below:', on_x, '',
             f'Bluesky ({bluesky_length(on_bluesky)} of {BLUESKY_LIMIT}, "{LINK_LABEL}" links to {RELEASE_LINK})'
             ' - posted by the deploy:', on_bluesky]
    found = problems(version, note)
    if found:
        lines += ['', 'will not post: ' + '; '.join(found)]
    else:
        lines += ['', 'Post on X (once the release is out):', x_intent_link(version, note)]
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='does the committed release note fit both sites?')
    preview = commands.add_parser('preview', help='both posts as they would go out, with how each site counts them')
    preview.add_argument('--version', default='',
                         help="the version to show - the next deploy's, worked out from the tags, if not given")
    post = commands.add_parser('post', help='post the release to Bluesky')
    post.add_argument('--version', required=True)
    post.add_argument('--previous-note-file', default='',
                      help="the release note as the release before this one had it, if any")
    notes = commands.add_parser('release-notes', help="the GitHub release's description, written to a file")
    notes.add_argument('--version', required=True)
    notes.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    if args.command == 'release-notes':
        note = note_for(read_note(), previous_note(args.version))
        Path(args.out).write_text(release_body(note), encoding='utf-8')
        print(release_body(note))
        return 0

    if args.command == 'check':
        found = problems(LONGEST_VERSION, read_note())
        for problem in found:
            print(problem)
        return 1 if found else 0

    if args.command == 'preview':
        version = args.version or coming_version()
        print(preview_text(version, read_note()))
        return 1 if problems(version, read_note()) else 0

    previous = read_note(Path(args.previous_note_file)) if args.previous_note_file else ''
    import requests
    with requests.Session() as session:
        return 0 if announce(args.version, note_for(read_note(), previous), os.environ, session) else 1


if __name__ == '__main__':
    sys.exit(main())
