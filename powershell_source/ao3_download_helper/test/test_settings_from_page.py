"""settings.ini edited from the page's User settings tab - in place, and only on this computer."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from source_code import access, server, settings_file, strings


TEMPLATE = """[settings]

# seconds to wait after every request
# (more is gentler on ao3)
ExtraWaitTime=15

# set this to 'true' to save your password
SavePassword=false

# a switch
EnableDebugLogging=false

# where the page finds the helper
HelperUrl=http://127.0.0.1:4400
"""


# region what the page is shown

def test_every_setting_but_the_password_and_the_hosting_ones_is_offered_with_its_explanation():
    offered = settings_file.editable_settings('[settings]\nExtraWaitTime=3\n', TEMPLATE)

    assert [s['key'] for s in offered] == ['ExtraWaitTime', 'EnableDebugLogging']
    wait, tools = offered
    assert wait == {'key': 'ExtraWaitTime', 'value': '3', 'default': '15', 'kind': 'integer',
                    'about': 'seconds to wait after every request (more is gentler on ao3)'}
    # missing from the file: the default the helper would use
    assert tools['value'] == 'false' and tools['kind'] == 'boolean'


def test_the_real_template_offers_none_of_the_settings_that_say_where_the_helper_is():
    keys = {s['key'] for s in settings_file.editable_settings('')}

    assert keys and not keys & set(settings_file.NOT_EDITABLE)


def test_an_explanation_reads_as_paragraphs_keeping_its_indented_example():
    block = '# one line\n# carried on\n#\n# named:\n#   {worknum} {title}\n# after\nX=1'

    assert settings_file.about(block) == 'one line carried on\n\nnamed:\n  {worknum} {title}\nafter'


def test_the_defaults_are_those_this_copy_was_built_with_where_it_has_them():
    built = '[settings]\nExtraWaitTime=40\n'

    offered = settings_file.editable_settings('[settings]\n', TEMPLATE, defaults=built)

    # the packaged app's deployment set 40; the template's 15 is not what it was downloaded with
    assert offered[0]['default'] == '40' and offered[0]['value'] == '40'
    # a setting the built file lacks still has one: the template's
    assert offered[1]['default'] == 'false'


def test_a_commented_out_value_is_not_read_as_the_setting():
    offered = settings_file.editable_settings('# ExtraWaitTime=99\nExtraWaitTime=4\n', TEMPLATE)

    assert offered[0]['value'] == '4'

# endregion


# region writing it

def test_only_the_value_changes_and_everything_around_it_stays_as_written():
    text = '[settings]\n# mine\nExtraWaitTime = 15   \n# ExtraWaitTime=1\nEnableDebugLogging=false\n'

    written = settings_file.set_values(text, {'ExtraWaitTime': '20'})

    assert written == '[settings]\n# mine\nExtraWaitTime = 20   \n# ExtraWaitTime=1\nEnableDebugLogging=false\n'


@pytest.mark.parametrize('kind, given, wanted', [
    ('boolean', True, 'true'), ('boolean', 'FALSE', 'false'),
    ('integer', 0, '0'), ('integer', '007', '7'), ('integer', ' 12 ', '12'),
])
def test_a_value_is_written_the_way_the_helper_reads_it(kind, given, wanted):
    assert settings_file.checked_value({'key': 'X', 'kind': kind}, given) == wanted


@pytest.mark.parametrize('kind, given', [
    ('boolean', 'yes'), ('boolean', 1), ('integer', -1), ('integer', '1.5'), ('integer', 'ten'),
    ('integer', True), ('text', 'two\nlines'),
])
def test_a_value_the_helper_would_misread_is_refused(kind, given):
    with pytest.raises(ValueError):
        settings_file.checked_value({'key': 'X', 'kind': kind}, given)


def test_a_refused_value_writes_nothing_at_all(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nExtraWaitTime=15\nMaxRetries=30\n', encoding='utf-8')

    with pytest.raises(ValueError):
        settings_file.update_settings_file(str(path), {'ExtraWaitTime': '20', 'MaxRetries': 'lots'})

    assert path.read_text(encoding='utf-8') == '[settings]\nExtraWaitTime=15\nMaxRetries=30\n'


@pytest.mark.parametrize('key', ['SavePassword', 'HelperUrl', 'RequirePasscode', 'PageOrigin', 'Nonsense'])
def test_a_setting_the_page_may_not_edit_is_refused(tmp_path, key):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nExtraWaitTime=15\n', encoding='utf-8')

    with pytest.raises(ValueError, match=key):
        settings_file.update_settings_file(str(path), {key: 'true'})


def test_reset_puts_back_every_default_in_place_and_leaves_the_hosting_settings(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\n# mine\nExtraWaitTime=99\nEnableDebugLogging=true\n'
                    'HelperUrl=http://127.0.0.1:5000\n', encoding='utf-8')

    settings = settings_file.update_settings_file(str(path), {}, '[settings]\nExtraWaitTime=40\n',
                                                  reset=True)

    text = path.read_text(encoding='utf-8')
    assert '# mine\nExtraWaitTime=40\n' in text
    assert 'EnableDebugLogging=false' in text
    assert 'HelperUrl=http://127.0.0.1:5000' in text
    assert {s['key']: s['value'] for s in settings}['ExtraWaitTime'] == '40'


def test_a_notepad_file_keeps_its_line_endings(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_bytes(b'[settings]\r\n# mine\r\nExtraWaitTime=15\r\n')

    settings_file.update_settings_file(str(path), {'ExtraWaitTime': 9})

    assert path.read_bytes() == b'[settings]\r\n# mine\r\nExtraWaitTime=9\r\n'


def test_a_setting_the_file_lacks_is_added_with_its_explanation_then_set(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nExtraWaitTime=15\n', encoding='utf-8')

    settings_file.update_settings_file(str(path), {'EnableConsoleLogging': True})

    text = path.read_text(encoding='utf-8')
    assert text.startswith('[settings]\nExtraWaitTime=15\n')
    assert 'EnableConsoleLogging=true' in text
    assert '# setting this to true makes the helper print to its own window' in text

# endregion


# region through the helper

@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, str(tmp_path))
    monkeypatch.delenv(access.ENV_PASSCODE, raising=False)
    path = tmp_path / strings.INI_FILE_NAME
    path.write_text('[settings]\n# mine\nExtraWaitTime=15\n', encoding='utf-8')
    return path


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(server.Handler, 'host', server.HOST)
    httpd = ThreadingHTTPServer((server.HOST, 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f'http://{server.HOST}:{httpd.server_address[1]}'
    finally:
        httpd.shutdown()
        httpd.server_close()


def ask(base, method='GET', body=None):
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = urllib.request.Request(base + '/api/settings-file', data=data, method=method,
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_a_helper_on_this_computer_shows_its_settings_and_where_the_file_is(live, config):
    status, body = ask(live)

    assert status == 200 and body['editable'] is True
    assert body['file'] == str(config)
    assert {'key': 'ExtraWaitTime', 'value': '15'}.items() <= body['settings'][0].items()


def test_a_helper_on_this_computer_writes_the_change_into_its_settings_ini(live, config):
    status, body = ask(live, 'POST', {'values': {'ExtraWaitTime': 30}})

    assert status == 200
    assert body['settings'][0]['value'] == '30'
    assert config.read_text(encoding='utf-8').startswith('[settings]\n# mine\nExtraWaitTime=30\n')


def test_reset_through_the_helper_uses_the_settings_the_app_was_built_with(live, config, tmp_path, monkeypatch):
    built = tmp_path / 'defaults.ini'
    built.write_text('[settings]\nExtraWaitTime=40\n', encoding='utf-8')
    monkeypatch.setattr(server.Handler, 'settings_defaults', str(built))
    ask(live, 'POST', {'values': {'ExtraWaitTime': 7}})

    status, body = ask(live, 'POST', {'reset': True})

    assert status == 200
    assert body['settings'][0] == {**body['settings'][0], 'value': '40', 'default': '40'}
    assert config.read_text(encoding='utf-8').startswith('[settings]\n# mine\nExtraWaitTime=40\n')


def test_a_bad_value_is_a_400_naming_it(live, config):
    status, body = ask(live, 'POST', {'values': {'ExtraWaitTime': 'soon'}})

    assert status == 400 and 'ExtraWaitTime' in body['error']
    assert 'ExtraWaitTime=15' in config.read_text(encoding='utf-8')


def test_a_hosted_helper_neither_shows_nor_writes_its_settings_ini(live, config, monkeypatch):
    monkeypatch.setattr(server.Handler, 'host', '0.0.0.0')

    status, body = ask(live)
    assert status == 200 and body == {'editable': False, 'settings': []}

    status, body = ask(live, 'POST', {'values': {'ExtraWaitTime': 30}})
    assert status == 403
    assert 'ExtraWaitTime=15' in config.read_text(encoding='utf-8')


def test_a_helper_behind_a_passcode_does_not_let_the_page_edit_it(config, monkeypatch):
    config.write_text('[settings]\nRequirePasscode=true\nExtraWaitTime=15\n', encoding='utf-8')
    monkeypatch.setattr(server.Handler, 'host', server.HOST)

    assert server.settings_file_editable() is False

# endregion
