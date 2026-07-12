"""Tests for ao3downloader.fileio — log writing, byte saving, settings persistence, download folder resolution."""

import datetime
import json
import os

import pytest

from ao3downloader import strings
from ao3downloader.fileio import FileOps


# region write_log

def test_write_log_appends_two_json_lines_with_timestamp(fake_fileops):
    fake_fileops.write_log({'message': 'first'})
    fake_fileops.write_log({'message': 'second'})

    with open(fake_fileops.logfile, encoding='utf-8') as f:
        lines = f.readlines()

    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first['message'] == 'first'
    assert second['message'] == 'second'
    # timestamp matches the expected format
    datetime.datetime.strptime(first['timestamp'], strings.TIMESTAMP_FORMAT)
    datetime.datetime.strptime(second['timestamp'], strings.TIMESTAMP_FORMAT)


def test_write_log_preserves_non_ascii(fake_fileops):
    fake_fileops.write_log({'title': 'これはテスト'})

    with open(fake_fileops.logfile, encoding='utf-8') as f:
        content = f.read()

    # ensure_ascii=False keeps the literal characters
    assert 'これはテスト' in content
    assert json.loads(content.strip())['title'] == 'これはテスト'

# endregion


# region save_bytes

def test_save_bytes_writes_content_and_creates_parent_dirs(fake_fileops):
    fake_fileops.save_bytes(os.path.join('sub', 'dir', 'work.epub'), b'epub-bytes')

    path = os.path.join(fake_fileops.downloadfolder, 'sub', 'dir', 'work.epub')
    assert os.path.exists(path)
    with open(path, 'rb') as f:
        assert f.read() == b'epub-bytes'


def test_save_bytes_overwrites_existing_file(fake_fileops):
    fake_fileops.save_bytes('work.epub', b'first')
    fake_fileops.save_bytes('work.epub', b'second')

    path = os.path.join(fake_fileops.downloadfolder, 'work.epub')
    with open(path, 'rb') as f:
        assert f.read() == b'second'

# endregion


# region save_setting / get_setting

def test_save_setting_roundtrips_through_get_setting(fake_fileops):
    fake_fileops.save_setting('username', 'alice')
    assert fake_fileops.get_setting('username') == 'alice'


def test_save_setting_none_removes_key(fake_fileops):
    fake_fileops.save_setting('username', 'alice')
    fake_fileops.save_setting('username', None)
    assert fake_fileops.get_setting('username') == ''


def test_get_setting_returns_empty_string_when_missing(fake_fileops):
    assert fake_fileops.get_setting('nope') == ''

# endregion


# region get_settings_json

def test_get_settings_json_returns_empty_dict_when_file_missing(fake_fileops):
    assert not os.path.exists(fake_fileops.settingsfile)

    result = fake_fileops.get_settings_json()

    assert result == {}
    # 'a' mode should have created the file
    assert os.path.exists(fake_fileops.settingsfile)


def test_get_settings_json_returns_empty_dict_when_file_malformed(fake_fileops):
    with open(fake_fileops.settingsfile, 'w', encoding='utf-8') as f:
        f.write('not json')

    assert fake_fileops.get_settings_json() == {}

# endregion


# region load_logfile

def test_load_logfile_returns_empty_list_when_file_missing(fake_fileops):
    assert not os.path.exists(fake_fileops.logfile)
    assert fake_fileops.load_logfile() == []


def test_load_logfile_parses_each_line_as_json_object(fake_fileops):
    fake_fileops.write_log({'message': 'one'})
    fake_fileops.write_log({'message': 'two'})

    logs = fake_fileops.load_logfile()

    assert len(logs) == 2
    assert logs[0]['message'] == 'one'
    assert logs[1]['message'] == 'two'


def test_load_logfile_loads_unicode_correctly(fake_fileops):
    fake_fileops.write_log({'title': 'これはテスト'})

    logs = fake_fileops.load_logfile()

    assert logs[0]['title'] == 'これはテスト'

# endregion


# region file_exists

def test_file_exists_false_when_id_not_in_titles(fake_fileops):
    assert fake_fileops.file_exists('99', {}, ['EPUB'], 50) is False


def test_file_exists_true_when_all_filetypes_present(fake_fileops):
    titles = {'1': ['work title']}
    for ext in ['epub', 'html']:
        path = os.path.join(fake_fileops.downloadfolder, 'work title.' + ext)
        with open(path, 'wb') as f:
            f.write(b'')

    assert fake_fileops.file_exists('1', titles, ['EPUB', 'HTML'], 50) is True


def test_file_exists_false_when_one_filetype_missing(fake_fileops):
    titles = {'1': ['work title']}
    # only create the epub, not the html
    path = os.path.join(fake_fileops.downloadfolder, 'work title.epub')
    with open(path, 'wb') as f:
        f.write(b'')

    assert fake_fileops.file_exists('1', titles, ['EPUB', 'HTML'], 50) is False

# endregion


# region ini_differences_str

def test_ini_differences_str_returns_none_when_equal(fake_fileops):
    local = {'settings': {'a', 'b'}}
    remote = {'settings': {'a', 'b'}}

    assert fake_fileops.ini_differences_str(local, remote) is None


def test_ini_differences_str_reports_added_section(fake_fileops):
    local = {'settings': {'a'}}
    remote = {'settings': {'a'}, 'new_section': {'x'}}

    msg = fake_fileops.ini_differences_str(local, remote)

    assert msg is not None
    assert strings.MESSAGE_INI_ADDED_SECTION.format('new_section') in msg


def test_ini_differences_str_reports_removed_section(fake_fileops):
    local = {'settings': {'a'}, 'gone': {'x'}}
    remote = {'settings': {'a'}}

    msg = fake_fileops.ini_differences_str(local, remote)

    assert msg is not None
    assert strings.MESSAGE_INI_REMOVED_SECTION.format('gone') in msg


def test_ini_differences_str_reports_added_and_removed_keys_in_same_section(fake_fileops):
    local = {'settings': {'old_key', 'shared'}}
    remote = {'settings': {'new_key', 'shared'}}

    msg = fake_fileops.ini_differences_str(local, remote)

    assert msg is not None
    assert strings.MESSAGE_INI_ADDED_KEY.format('new_key', 'settings') in msg
    assert strings.MESSAGE_INI_REMOVED_KEY.format('old_key', 'settings') in msg


def test_ini_differences_str_handles_multiple_sections(fake_fileops):
    local = {'a': {'k1'}, 'b': {'k2'}}
    remote = {'a': {'k1', 'k3'}, 'b': {'k2'}}

    msg = fake_fileops.ini_differences_str(local, remote)

    assert strings.MESSAGE_INI_ADDED_KEY.format('k3', 'a') in msg

# endregion


# region ini_differences

def test_ini_differences_parses_real_ini_strings(fake_fileops):
    local = '[settings]\na=1\nb=2\n'
    remote = '[settings]\na=1\nb=2\nc=3\n'

    msg = fake_fileops.ini_differences(local, remote)

    assert msg is not None
    assert strings.MESSAGE_INI_ADDED_KEY.format('c', 'settings') in msg


def test_ini_differences_returns_none_when_identical(fake_fileops):
    content = '[settings]\na=1\nb=2\n'

    assert fake_fileops.ini_differences(content, content) is None

# endregion


# region get_ini_value*

def _write_ini(fake_fileops, body: str) -> None:
    with open(fake_fileops.inifile, 'w', encoding='utf-8') as f:
        f.write(body)


def test_get_ini_value_reads_string(fake_fileops):
    _write_ini(fake_fileops, '[settings]\nFileNamePattern=custom\n')

    assert fake_fileops.get_ini_value('FileNamePattern', 'fallback') == 'custom'


def test_get_ini_value_returns_fallback_when_missing(fake_fileops):
    _write_ini(fake_fileops, '[settings]\n')

    assert fake_fileops.get_ini_value('Missing', 'default') == 'default'


def test_get_ini_value_boolean_reads_true_and_false(fake_fileops):
    _write_ini(fake_fileops,
               '[settings]\nFlagTrue=true\nFlagFalse=false\n')

    assert fake_fileops.get_ini_value_boolean('FlagTrue', False) is True
    assert fake_fileops.get_ini_value_boolean('FlagFalse', True) is False


def test_get_ini_value_boolean_returns_fallback_when_missing(fake_fileops):
    _write_ini(fake_fileops, '[settings]\n')

    assert fake_fileops.get_ini_value_boolean('Absent', True) is True
    assert fake_fileops.get_ini_value_boolean('Absent', False) is False


def test_get_ini_value_integer_reads_and_fallbacks(fake_fileops):
    _write_ini(fake_fileops, '[settings]\nMaxRetries=42\n')

    assert fake_fileops.get_ini_value_integer('MaxRetries', 0) == 42
    assert fake_fileops.get_ini_value_integer('Missing', 99) == 99


def test_get_ini_value_raw_tolerates_percent_signs(fake_fileops):
    _write_ini(fake_fileops, '[settings]\nSomeKey=%USERPROFILE%\\fics\n')

    assert fake_fileops.get_ini_value('SomeKey', 'fallback', raw=True) == '%USERPROFILE%\\fics'

# endregion


# region get_download_folder

def _write_download_folder(fake_fileops, value: str) -> None:
    _write_ini(fake_fileops, f'[settings]\n{strings.INI_DOWNLOAD_FOLDER}={value}\n')


def test_get_download_folder_returns_default_when_key_missing(fake_fileops):
    _write_ini(fake_fileops, '[settings]\n')

    assert fake_fileops.get_download_folder() == strings.DOWNLOAD_FOLDER_NAME


def test_get_download_folder_returns_default_when_value_blank(fake_fileops):
    _write_download_folder(fake_fileops, '')

    assert fake_fileops.get_download_folder() == strings.DOWNLOAD_FOLDER_NAME


def test_get_download_folder_returns_default_when_value_is_quotes_only(fake_fileops):
    _write_download_folder(fake_fileops, '""')

    assert fake_fileops.get_download_folder() == strings.DOWNLOAD_FOLDER_NAME


def test_get_download_folder_keeps_relative_path_relative(fake_fileops):
    _write_download_folder(fake_fileops, os.path.join('my fics', 'ao3'))

    assert fake_fileops.get_download_folder() == os.path.join('my fics', 'ao3')


def test_get_download_folder_returns_absolute_path_verbatim(fake_fileops, tmp_path):
    _write_download_folder(fake_fileops, str(tmp_path / 'elsewhere'))

    assert fake_fileops.get_download_folder() == str(tmp_path / 'elsewhere')


def test_get_download_folder_strips_enclosing_quotes(fake_fileops):
    _write_download_folder(fake_fileops, '"my fics"')

    assert fake_fileops.get_download_folder() == 'my fics'


def test_get_download_folder_tolerates_percent_signs(fake_fileops):
    _write_download_folder(fake_fileops, '50% fics')

    assert fake_fileops.get_download_folder() == '50% fics'


def test_get_download_folder_expands_home_directory(fake_fileops, tmp_path, monkeypatch):
    # cover both the posix (HOME) and windows (USERPROFILE) lookups
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    _write_download_folder(fake_fileops, '~/fics')

    assert fake_fileops.get_download_folder() == str(tmp_path) + '/fics'


def test_get_download_folder_expands_environment_variables(fake_fileops, tmp_path, monkeypatch):
    monkeypatch.setenv('AO3DL_TEST_FOLDER', str(tmp_path))
    _write_download_folder(fake_fileops, '$AO3DL_TEST_FOLDER/fics')

    assert fake_fileops.get_download_folder() == str(tmp_path) + '/fics'


def test_fileops_reads_download_folder_from_ini_on_construction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with open(strings.INI_FILE_NAME, 'w', encoding='utf-8') as f:
        f.write(f'[settings]\n{strings.INI_DOWNLOAD_FOLDER}=custom folder\n')

    assert FileOps().downloadfolder == 'custom folder'


def test_fileops_uses_default_download_folder_when_no_ini(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert FileOps().downloadfolder == strings.DOWNLOAD_FOLDER_NAME

# endregion


# region initialize

def test_initialize_creates_nested_download_folder(fake_fileops, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_ini(fake_fileops, '[settings]\n')
    fake_fileops.downloadfolder = str(tmp_path / 'a' / 'b' / 'c')

    fake_fileops.initialize()

    assert os.path.isdir(fake_fileops.downloadfolder)


def test_initialize_succeeds_when_download_folder_already_exists(fake_fileops, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_ini(fake_fileops, '[settings]\n')
    assert os.path.isdir(fake_fileops.downloadfolder)

    fake_fileops.initialize()

    assert os.path.isdir(fake_fileops.downloadfolder)


def test_initialize_fails_with_message_when_download_folder_uncreatable(fake_fileops, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _write_ini(fake_fileops, '[settings]\n')
    blocker = tmp_path / 'blocker'
    blocker.write_bytes(b'')
    fake_fileops.downloadfolder = str(blocker / 'fics')

    with pytest.raises(OSError):
        fake_fileops.initialize()

    assert strings.MESSAGE_DOWNLOAD_FOLDER_ERROR.format(fake_fileops.downloadfolder) in capsys.readouterr().out

# endregion
