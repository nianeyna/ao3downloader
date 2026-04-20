"""Shared pytest fixtures for ao3downloader tests."""

import os
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


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
