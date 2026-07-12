"""Tests for ao3downloader.actions.shared — folder input and file discovery."""

import os
from unittest.mock import MagicMock

import pytest

from ao3downloader import strings
from ao3downloader.actions import shared
from ao3downloader.fileio import FileOps


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


# region yes/no prompts

@pytest.mark.parametrize('answer, expected', [
    (strings.PROMPT_YES, True),
    (strings.PROMPT_NO, False),
    ('', False),
])
def test_series_returns_expected_bool(answer, expected, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.series() is expected


@pytest.mark.parametrize('answer, expected', [
    (strings.PROMPT_YES, True),
    (strings.PROMPT_NO, False),
])
def test_images_returns_expected_bool(answer, expected, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.images() is expected


@pytest.mark.parametrize('answer, expected', [
    (strings.PROMPT_YES, True),
    (strings.PROMPT_NO, False),
])
def test_metadata_returns_expected_bool(answer, expected, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.metadata() is expected


@pytest.mark.parametrize('answer, expected_exclude', [
    # pinboard_exclude has inverted logic — 'yes include unread' means don't exclude
    (strings.PROMPT_YES, False),
    (strings.PROMPT_NO, True),
])
def test_pinboard_exclude_inverts_input(answer, expected_exclude, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.pinboard_exclude() is expected_exclude

# endregion


# region pages

@pytest.mark.parametrize('answer, expected', [
    ('5', 5),
    ('0', None),
    ('-1', None),
    ('abc', None),
    ('', None),
])
def test_pages_parses_int_with_fallback(answer, expected, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.pages() == expected

# endregion


# region pinboard_date

def test_pinboard_date_returns_none_when_no(monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: strings.PROMPT_NO)
    assert shared.pinboard_date() is None


def test_pinboard_date_parses_entered_date(monkeypatch, capsys) -> None:
    import datetime
    inputs = iter([strings.PROMPT_YES, '03/15/2024'])
    monkeypatch.setattr('builtins.input', lambda: next(inputs))

    result = shared.pinboard_date()

    assert result == datetime.datetime(2024, 3, 15)

# endregion


# region visited

def _prepare_fileops(tmp_path):
    from ao3downloader.fileio import FileOps

    fo = FileOps()
    fo.logfile = str(tmp_path / 'log.jsonl')
    fo.inifile = str(tmp_path / 'settings.ini')
    fo.settingsfile = str(tmp_path / 'data.json')
    fo.downloadfolder = str(tmp_path / 'downloads')
    os.makedirs(fo.downloadfolder, exist_ok=True)
    return fo


def test_visited_returns_files_from_log_that_exist_on_disk(tmp_path, monkeypatch) -> None:
    """visited should return only work ids whose files exist on disk."""
    fo = _prepare_fileops(tmp_path)

    # write two works to the log
    fo.write_log({'link': 'https://a/works/1', 'title': 'one'})
    fo.write_log({'link': 'https://a/works/2', 'title': 'two'})

    # only create the file for work 1
    with open(os.path.join(fo.downloadfolder, 'one.epub'), 'wb') as f:
        f.write(b'')

    monkeypatch.chdir(tmp_path)  # IGNORELIST_FILE_NAME uses relative path

    result = shared.visited(fo, ['EPUB'])

    assert 'https://a/works/1' in result
    assert 'https://a/works/2' not in result


def test_visited_returns_empty_when_no_log_and_no_ignorelist(tmp_path, monkeypatch) -> None:
    fo = _prepare_fileops(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert shared.visited(fo, ['EPUB']) == []

# endregion
