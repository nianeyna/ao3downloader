"""A settings.ini kept in step with the settings the helper knows about - only ever added to."""

import os
from unittest.mock import patch

import pytest

from source_code import server, settings_file, strings


TEMPLATE = """[settings]

# seconds to wait after every request
ExtraWaitTime=15

# set this to 'true' to save your password
SavePassword=false

# a setting added in a later version
# over two lines of explanation
NewSetting=7
"""


# region completing one

def test_a_setting_the_file_lacks_is_added_with_its_explanation_and_default():
    existing = '[settings]\nExtraWaitTime=30\n'

    completed, added = settings_file.complete_settings(existing, TEMPLATE)

    assert added == ['NewSetting']
    assert completed.endswith('# a setting added in a later version\n'
                              '# over two lines of explanation\nNewSetting=7\n')


def test_what_the_user_wrote_is_left_exactly_as_it_was():
    existing = '[settings]\n# my own note\nExtraWaitTime=30\n'

    completed, _ = settings_file.complete_settings(existing, TEMPLATE)

    # only added to the end - nothing already there is rewritten or moved
    assert completed.startswith(existing.rstrip('\n'))
    assert 'ExtraWaitTime=30' in completed and 'ExtraWaitTime=15' not in completed


def test_a_setting_written_in_another_case_counts_as_there():
    # configparser reads names without case, so this one is already set
    completed, added = settings_file.complete_settings(
        '[settings]\nextrawaittime=30\nnewsetting=1\n', TEMPLATE)
    assert added == []


def test_the_password_setting_is_never_added():
    # the web page never stores a password
    _, added = settings_file.complete_settings('[settings]\n', TEMPLATE)
    assert strings.INI_PASSWORD_SAVE not in added


def test_a_file_with_nothing_in_it_gets_a_section_to_put_things_in():
    completed, added = settings_file.complete_settings('', TEMPLATE)
    assert completed.startswith('[settings]')
    assert added == ['ExtraWaitTime', 'NewSetting']


def test_the_real_template_has_every_setting_the_helper_reads():
    # the settings added since the web ui took over are all in it, so they reach old files
    names = [key for key, _ in settings_file.blocks_of(settings_file.template_text())]
    for key in (strings.INI_HELPER_URL, strings.INI_REQUIRE_PASSCODE, strings.INI_PAGE_ORIGIN,
                strings.INI_CONSOLE_LOGGING, strings.INI_PAUSED_RUN_TIMEOUT,
                strings.INI_WAIT_TIME):
        assert key in names, key

# endregion


# region the file on disk

def test_a_missing_file_is_written_from_the_template_without_the_password_setting(tmp_path):
    path = tmp_path / 'config' / 'settings.ini'

    assert settings_file.ensure_settings_file(str(path), TEMPLATE) == (True, [], [])
    text = path.read_text(encoding='utf-8')
    assert 'ExtraWaitTime=15' in text and 'NewSetting=7' in text
    assert 'SavePassword' not in text


def test_an_old_file_gets_what_it_lacks(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nExtraWaitTime=30\n', encoding='utf-8')

    assert settings_file.ensure_settings_file(str(path), TEMPLATE) == (False, ['NewSetting'], [])
    assert 'NewSetting=7' in path.read_text(encoding='utf-8')


def test_a_complete_file_is_not_written_at_all(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nExtraWaitTime=30\nNewSetting=1\n', encoding='utf-8')
    os.utime(path, (1, 1))

    assert settings_file.ensure_settings_file(str(path), TEMPLATE) == (False, [], [])
    assert os.path.getmtime(path) == 1


def test_a_setting_this_version_no_longer_reads_is_commented_out_and_marked(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\n# how many pages at most\nOldLimit=40\nExtraWaitTime=30\n'
                    'NewSetting=1\n', encoding='utf-8')

    assert settings_file.ensure_settings_file(str(path), TEMPLATE) == (False, [], ['OldLimit'])

    text = path.read_text(encoding='utf-8')
    # the value is still there to read, the comment above it untouched - it just sets nothing
    assert '# how many pages at most\n# DEPRECATED: OldLimit is no longer used' in text
    assert '\n# OldLimit=40\n' in text
    assert '\nOldLimit=' not in text
    # everything else exactly as it was
    assert 'ExtraWaitTime=30\nNewSetting=1\n' in text


def test_marking_a_setting_deprecated_twice_changes_nothing(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nOldLimit=40\nExtraWaitTime=30\nNewSetting=1\n', encoding='utf-8')
    settings_file.ensure_settings_file(str(path), TEMPLATE)
    once = path.read_text(encoding='utf-8')

    assert settings_file.ensure_settings_file(str(path), TEMPLATE) == (False, [], [])
    assert path.read_text(encoding='utf-8') == once


def test_a_setting_that_is_only_left_out_of_page_builds_is_never_deprecated(tmp_path):
    # SavePassword still exists - a page build only leaves it out of the files it writes
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nSavePassword=false\nExtraWaitTime=30\nNewSetting=1\n',
                    encoding='utf-8')

    assert settings_file.ensure_settings_file(str(path), settings_file.fresh_settings(TEMPLATE)) \
        == (False, [], [])
    assert 'SavePassword=false' in path.read_text(encoding='utf-8')


def test_a_setting_is_added_and_another_deprecated_in_one_go(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nOldLimit=40\nExtraWaitTime=30\n', encoding='utf-8')

    assert settings_file.ensure_settings_file(str(path), TEMPLATE) == (False, ['NewSetting'], ['OldLimit'])


def test_a_file_edited_in_notepad_keeps_its_line_endings(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_bytes(b'[settings]\r\nOldLimit=40\r\nExtraWaitTime=30\r\n')

    settings_file.ensure_settings_file(str(path), TEMPLATE)

    data = path.read_bytes()
    assert b'\r\n# OldLimit=40\r\n' in data
    assert b'NewSetting=7' in data
    assert b'\n' not in data.replace(b'\r\n', b'')


def test_every_setting_the_helper_reads_is_in_the_template():
    # anything read but missing from the template would be commented out as deprecated in
    # every settings.ini the next time the helper starts
    from source_code import strings
    read = {value for name, value in vars(strings).items()
            if name.startswith('INI_') and isinstance(value, str)
            and name not in ('INI_FILE_NAME', 'INI_SECTION_NAME', 'INI_DEFAULT_HELPER_URL')}
    assert {key.lower() for key in read} <= settings_file.keys_in(settings_file.template_text())

# endregion


# region when the helper starts

def test_the_helper_writes_a_missing_settings_file_as_it_starts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, str(tmp_path))
    with patch.object(server, 'already_listening', return_value=False), \
         patch.object(server, 'ThreadingHTTPServer'):
        server.serve(port=4400)

    text = (tmp_path / strings.INI_FILE_NAME).read_text(encoding='utf-8')
    assert f'{strings.INI_PAUSED_RUN_TIMEOUT}=10' in text
    assert 'settings.ini: created' in capsys.readouterr().out


def test_the_helper_adds_what_an_older_settings_file_lacks_and_says_so(tmp_path, monkeypatch,
                                                                        capsys):
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, str(tmp_path))
    ini = tmp_path / strings.INI_FILE_NAME
    ini.write_text('[settings]\nExtraWaitTime=42\n', encoding='utf-8')

    with patch.object(server, 'already_listening', return_value=False), \
         patch.object(server, 'ThreadingHTTPServer'):
        server.serve(port=4400)

    text = ini.read_text(encoding='utf-8')
    assert 'ExtraWaitTime=42' in text
    assert f'{strings.INI_HELPER_URL}=http://127.0.0.1:4400' in text
    said = capsys.readouterr().out
    assert 'settings.ini: added' in said and strings.INI_PAUSED_RUN_TIMEOUT in said


def test_a_settings_file_that_cannot_be_written_does_not_stop_the_helper(tmp_path, capsys):
    with patch.object(settings_file, 'ensure_settings_file', side_effect=PermissionError('no')):
        server.bring_settings_up_to_date(str(tmp_path / 'settings.ini'))
    assert 'using the defaults' in capsys.readouterr().out

# endregion
