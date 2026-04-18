"""Tests for ao3downloader.actions.shared — folder input and file discovery."""

import os
from unittest.mock import MagicMock

import pytest

from ao3downloader import strings
from ao3downloader.actions import shared
from ao3downloader.fileio import FileOps


# region normalize_path_input

@pytest.mark.parametrize('raw, expected', [
    ('/tmp/fics', '/tmp/fics'),
    ('  /tmp/fics  ', '/tmp/fics'),
    ('"/tmp/fics"', '/tmp/fics'),
    ("'/tmp/fics'", '/tmp/fics'),
    ('"C:\\Users\\foo\\fics"', 'C:\\Users\\foo\\fics'),
    ('  "/tmp/fics"  ', '/tmp/fics'),
    ('"/tmp/fics\'', '"/tmp/fics\''),
    ('"/tmp/fics', '"/tmp/fics'),
    ('/tmp/fics"', '/tmp/fics"'),
    ('', ''),
    ('"', '"'),
])
def testnormalize_path_input(raw: str, expected: str) -> None:
    assert shared.normalize_path_input(raw) == expected

# endregion


# region get_files_of_type

def test_get_files_of_type_returns_matching_files(tmp_path, capsys) -> None:
    (tmp_path / 'work1.epub').write_bytes(b'')
    (tmp_path / 'work2.EPUB').write_bytes(b'')
    (tmp_path / 'work3.mobi').write_bytes(b'')
    (tmp_path / 'readme.txt').write_bytes(b'')
    sub = tmp_path / 'nested'
    sub.mkdir()
    (sub / 'work4.epub').write_bytes(b'')

    results = shared.get_files_of_type(str(tmp_path), ['EPUB'])

    paths = sorted(os.path.basename(r['path']) for r in results)
    assert paths == ['work1.epub', 'work2.EPUB', 'work4.epub']
    assert all(r['filetype'] == 'EPUB' for r in results)


def test_get_files_of_type_nonexistent_folder_returns_empty(capsys) -> None:
    bogus = '/definitely/does/not/exist/anywhere'
    results = shared.get_files_of_type(bogus, ['EPUB'])

    assert results == []
    out = capsys.readouterr().out
    assert bogus in out


def test_get_files_of_type_quoted_path_returns_empty(capsys) -> None:
    results = shared.get_files_of_type('"/tmp"', ['EPUB'])

    assert results == []
    out = capsys.readouterr().out
    assert strings.INFO_NO_FOLDER.split('{')[0] in out

# endregion


# region update_folder

def _fake_fileops() -> MagicMock:
    fo = MagicMock(spec=FileOps)
    fo._settings = {}
    fo.get_setting.side_effect = lambda key: fo._settings.get(key, '')
    def _save(key: str, value) -> None:
        if value is None:
            fo._settings.pop(key, None)
        else:
            fo._settings[key] = value
    fo.save_setting.side_effect = _save
    return fo


def test_update_folder_accepts_quoted_paste(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    quoted = f'"{tmp_path}"'
    monkeypatch.setattr('builtins.input', lambda: quoted)

    result = shared.update_folder(fo)

    assert result == str(tmp_path)
    # normalized value is saved
    assert fo._settings[strings.SETTING_UPDATE_FOLDER] == str(tmp_path)


def test_update_folder_reprompts_on_invalid_then_accepts(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    inputs = iter(['/nope/not/a/real/path', str(tmp_path)])
    monkeypatch.setattr('builtins.input', lambda: next(inputs))

    result = shared.update_folder(fo)

    assert result == str(tmp_path)


def test_update_folder_detects_stale_saved_path(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    fo._settings[strings.SETTING_UPDATE_FOLDER] = '/stale/path/gone'
    monkeypatch.setattr('builtins.input', lambda: str(tmp_path))

    result = shared.update_folder(fo)

    # stale path was cleared, user was reprompted, new path saved
    assert result == str(tmp_path)
    assert fo._settings[strings.SETTING_UPDATE_FOLDER] == str(tmp_path)


def test_update_folder_normalizes_quoted_saved_path(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    fo._settings[strings.SETTING_UPDATE_FOLDER] = f'"{tmp_path}"'
    monkeypatch.setattr('builtins.input', lambda: strings.PROMPT_YES)

    result = shared.update_folder(fo)

    assert result == str(tmp_path)
    assert fo._settings[strings.SETTING_UPDATE_FOLDER] == str(f'"{tmp_path}"')


def test_update_folder_reuses_valid_saved_path(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    fo._settings[strings.SETTING_UPDATE_FOLDER] = str(tmp_path)
    monkeypatch.setattr('builtins.input', lambda: strings.PROMPT_YES)

    result = shared.update_folder(fo)

    assert result == str(tmp_path)


def test_update_folder_says_no_to_saved_then_prompts(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    other = tmp_path / 'other'
    other.mkdir()
    fo._settings[strings.SETTING_UPDATE_FOLDER] = str(tmp_path)
    inputs = iter([strings.PROMPT_NO, str(other)])
    monkeypatch.setattr('builtins.input', lambda: next(inputs))

    result = shared.update_folder(fo)

    assert result == str(other)
    assert fo._settings[strings.SETTING_UPDATE_FOLDER] == str(other)

# endregion


# region redownload_folder

def test_redownload_folder_accepts_quoted_paste(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('builtins.input', lambda: f'"{tmp_path}"')
    assert shared.redownload_folder() == str(tmp_path)


def test_redownload_folder_reprompts_on_invalid(tmp_path, monkeypatch) -> None:
    inputs = iter(['/nope/not/a/real/path', str(tmp_path)])
    monkeypatch.setattr('builtins.input', lambda: next(inputs))
    assert shared.redownload_folder() == str(tmp_path)

# endregion
