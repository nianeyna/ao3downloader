"""Shared pytest fixtures for ao3downloader tests."""

import glob
import os
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
EBOOK_DIR = os.path.join(FIXTURES_DIR, 'ebook')


def ebook_fixtures(work_id: str, ext: str) -> list[str]:
    """Return sorted paths to ebook fixtures for a given work + extension.

    Always includes files under `ebook/<work_id>/current/`. Additionally
    includes `archive/` unless AO3_FIXTURE_MODE=current_only is set in the
    environment (used by the CI two-pass check to verify a newly-refreshed
    live fixture still parses correctly without help from archived versions).
    """
    root = os.path.join(EBOOK_DIR, work_id)
    paths = sorted(glob.glob(os.path.join(root, 'current', '*' + ext)))
    if os.environ.get('AO3_FIXTURE_MODE') != 'current_only':
        paths += sorted(glob.glob(os.path.join(root, 'archive', '*' + ext)))
    return paths


# region shared loaders

@pytest.fixture
def fixture_soup():
    """Factory: load test/fixtures/<name>.html as a BeautifulSoup."""

    def _load(name: str) -> BeautifulSoup:
        path = os.path.join(FIXTURES_DIR, name + '.html')
        with open(path, encoding='utf-8') as f:
            return BeautifulSoup(f.read(), 'html.parser')

    return _load

# endregion


# region fileops / repo

@pytest.fixture
def fake_fileops(tmp_path) -> FileOps:
    """Real FileOps whose paths are redirected under tmp_path."""

    fileops = FileOps()
    fileops.logfile = str(tmp_path / 'log.jsonl')
    fileops.inifile = str(tmp_path / 'settings.ini')
    fileops.settingsfile = str(tmp_path / 'data.json')
    fileops.downloadfolder = str(tmp_path / 'downloads')
    os.makedirs(fileops.downloadfolder, exist_ok=True)
    return fileops


@pytest.fixture
def mock_repo(fake_fileops, monkeypatch) -> Repository:
    """Repository with a mocked session and no-op sleep, for retry-logic tests."""

    monkeypatch.setattr('ao3downloader.repo.sleep', lambda _: None)
    repo = Repository(fake_fileops)
    repo.session = MagicMock()
    return repo

# endregion
