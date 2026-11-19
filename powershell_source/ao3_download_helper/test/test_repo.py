"""Tests for ao3downloader.repo — cloudflare detection, retry logic, login, marking."""

import io
import json
import os
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest
import requests
import urllib3
from bs4 import BeautifulSoup

from source_code import exceptions, progress, strings
from source_code.repo import Repository

from test.conftest import ebook_fixtures


AO3_URL = 'https://archiveofourown.org/works/123'
NON_AO3_URL = 'https://example.com/whatever'

# work id of the markedForLater fixture, used to derive the mark-as-read URL
MARKED_FOR_LATER_WORK_ID = '66326125'
MARKED_FOR_LATER_URL = strings.AO3_BASE_URL + '/works/' + MARKED_FOR_LATER_WORK_ID

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name + '.html'), encoding='utf-8') as f:
        return f.read()


# region is_cloudflare_response

def make_response(server='', content_type='text/html',
                  url='https://archiveofourown.org/works/123',
                  text='', status_code=200, headers=None):
    response = MagicMock()
    hdrs = {'Server': server, 'Content-Type': content_type}
    if headers:
        hdrs.update(headers)
    response.headers = hdrs
    response.url = url
    response.text = text
    response.status_code = status_code
    response.content = text.encode('utf-8') if isinstance(text, str) else text
    return response


def test_cloudflare_challenge_page():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>Just a moment...</title></head></html>')
    assert Repository.is_cloudflare_response(response) is True


def test_cloudflare_attention_required():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>Attention Required!</title></head></html>')
    assert Repository.is_cloudflare_response(response) is True


def test_cloudflare_access_denied():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>Access denied</title></head></html>')
    assert Repository.is_cloudflare_response(response) is True


def test_cloudflare_wrapper_div():
    response = make_response(
        server='cloudflare',
        text='<html><body><div id="cf-wrapper">challenge</div></body></html>')
    assert Repository.is_cloudflare_response(response) is True


def test_normal_ao3_page():
    response = make_response(
        server='Apache',
        text='<html><head><title>A Work - Chapter 1</title></head></html>')
    assert Repository.is_cloudflare_response(response) is False


def test_ao3_behind_cloudflare_but_normal_page():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>A Work - Chapter 1</title></head><body><div id="main"></div></body></html>')
    assert Repository.is_cloudflare_response(response) is False


def test_normal_download():
    response = make_response(
        server='cloudflare',
        content_type='application/epub+zip',
        url='https://archiveofourown.org/downloads/123/work.epub',
        text='')
    assert Repository.is_cloudflare_response(response) is False


def test_detected_without_server_header():
    response = make_response(
        server='',
        text='<html><head><title>Just a moment...</title></head></html>')
    assert Repository.is_cloudflare_response(response) is True


def test_cloudflare_challenge_script():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>Unknown Title</title></head>'
             '<body><script>window._cf_chl_opt = {cvId: "3"};</script></body></html>')
    assert Repository.is_cloudflare_response(response) is True


def test_cloudflare_challenge_error_text_marker():
    response = make_response(
        server='',
        text='<html><body><span id="challenge-error-text">'
             'Enable JavaScript and cookies to continue</span></body></html>')
    assert Repository.is_cloudflare_response(response) is True


def test_cloudflare_marker_found_beyond_2048_bytes():
    # ao3's interstitial buries its markers ~5 KB in, after a large inline svg logo and <style>
    # block, so detection must scan the whole body. this guards against reintroducing a
    # response.text[:N] truncation.
    padding = '<!-- ' + 'x' * 5000 + ' -->'
    response = make_response(
        server='',
        text='<html><head>' + padding + '<script>window._cf_chl_opt = {};</script></head></html>')
    assert Repository.is_cloudflare_response(response) is True


def test_binary_content_type_not_scanned():
    # a real work file (epub/pdf/mobi/azw3) is never served as text/html; its bytes must not be
    # scanned as text, even if a marker string happens to appear in them.
    response = make_response(
        server='cloudflare',
        content_type='application/epub+zip',
        text='PK\x03\x04 ... _cf_chl_opt ... binary noise')
    assert Repository.is_cloudflare_response(response) is False


_HTML_DOWNLOAD_FIXTURES = (
    ebook_fixtures('23009290', '.html')
    + ebook_fixtures('218676', '.html')
    + ebook_fixtures('334557', '.html'))


@pytest.mark.parametrize('path', _HTML_DOWNLOAD_FIXTURES,
                         ids=[os.path.relpath(p, FIXTURES_DIR) for p in _HTML_DOWNLOAD_FIXTURES])
def test_real_html_download_not_flagged(path):
    # real AO3 HTML work downloads are text/html; now that detection no longer gates on the Server
    # header, make sure a genuine download is never mistaken for a challenge page.
    with open(path, encoding='utf-8') as f:
        html = f.read()
    response = make_response(server='', text=html)
    assert Repository.is_cloudflare_response(response) is False

# endregion


# region my_request — retry statuses

@pytest.mark.parametrize('status', sorted(Repository.retry_statuses))
def test_my_request_retries_on_retry_status_then_succeeds(mock_repo, status):
    failing = make_response(status_code=status)
    succeeding = make_response(status_code=200, text='ok')
    mock_repo.session.request.side_effect = [failing, succeeding]

    result = mock_repo.my_request('GET', AO3_URL)

    assert result is succeeding
    assert mock_repo.session.request.call_count == 2


def test_my_request_exhausts_max_retries_and_raises_invalid_status(mock_repo):
    mock_repo.max_retries = 2
    mock_repo.session.request.return_value = make_response(status_code=502)

    with pytest.raises(exceptions.InvalidStatusCodeException):
        mock_repo.my_request('GET', AO3_URL)

    # attempts 0, 1, 2 → 3 calls before raising
    assert mock_repo.session.request.call_count == 3


MAINTENANCE = ('<html><head><title>Archive of Our Own</title></head><body><h2>The archive is '
               'down for maintenance.</h2><p>Check our status page.</p></body></html>')


def test_a_retry_is_said_in_the_run_rather_than_waited_out_silently(mock_repo, capsys):
    mock_repo.max_retries = 5
    mock_repo.session.request.side_effect = [make_response(status_code=503),
                                             make_response(status_code=200, text='ok')]

    mock_repo.my_request('GET', AO3_URL)

    said = capsys.readouterr().out
    assert 'AO3 answered 503' in said
    assert 'attempt 1 of 5' in said


def test_a_stop_lands_during_a_retry_wait_instead_of_after_it(mock_repo):
    # this was a plain sleep: a run retrying ao3's error pages could not be stopped for
    # a quarter of an hour, and sat saying 'stopping' the whole time
    stopped = {'yes': False}
    mock_repo.cancelled = lambda: stopped['yes']
    mock_repo.max_retries = 30

    def answer(*args, **kwargs):
        stopped['yes'] = True  # the stop arrives while ao3 is failing
        return make_response(status_code=503)

    mock_repo.session.request.side_effect = answer

    with pytest.raises(exceptions.CancelledException):
        mock_repo.my_request('GET', AO3_URL)
    assert mock_repo.session.request.call_count == 1


def test_the_maintenance_page_is_asked_about_twice_then_given_up_on(mock_repo, capsys):
    mock_repo.session.request.return_value = make_response(status_code=503, text=MAINTENANCE)

    with pytest.raises(exceptions.Ao3DownException):
        mock_repo.my_request('GET', AO3_URL)

    # the first answer and two more, not MaxRetries' thirty
    assert mock_repo.session.request.call_count == 1 + Repository.maintenance_retries
    assert 'down for maintenance' in capsys.readouterr().out
    assert mock_repo.ao3_down is True


def test_the_maintenance_page_counts_even_when_ao3_says_200(mock_repo):
    mock_repo.session.request.return_value = make_response(status_code=200, text=MAINTENANCE)
    with pytest.raises(exceptions.Ao3DownException):
        mock_repo.my_request('GET', AO3_URL)


def test_once_ao3_is_down_every_later_request_to_it_fails_at_once(mock_repo):
    mock_repo.ao3_down = True

    with pytest.raises(exceptions.Ao3DownException):
        mock_repo.my_request('GET', AO3_URL)
    mock_repo.session.request.assert_not_called()

    # anywhere else - FicHub - is still asked
    mock_repo.session.request.return_value = make_response(status_code=200, text='ok')
    assert mock_repo.my_request('GET', 'https://fichub.net/api/v0/epub?q=x').status_code == 200


def test_fichub_is_still_asked_about_an_ao3_link_once_ao3_is_down(mock_repo):
    # FicHub's lookup carries the ao3 link in its query - which, matched as text, used to
    # read as a request to ao3 and was refused, so the one place left was never asked
    import urllib.parse
    mock_repo.ao3_down = True
    mock_repo.session.request.return_value = make_response(status_code=200, text='{}')
    url = strings.FICHUB_API_URL + '?q=' + urllib.parse.quote(
        'https://archiveofourown.org/works/75354806', safe='')

    assert mock_repo.my_request('GET', url).status_code == 200


@pytest.mark.parametrize('url, ao3', [
    ('https://archiveofourown.org/works/1', True),
    ('http://archiveofourown.org/works/1', True),
    ('https://download.archiveofourown.org/downloads/1/fic.epub', True),
    ('https://fichub.net/api/v0/epub?q=https://archiveofourown.org/works/1', False),
    ('https://example.com/archiveofourown.org', False),
    ('https://notarchiveofourown.org/', False),
])
def test_a_request_is_to_ao3_by_the_host_it_goes_to(url, ao3):
    from source_code import repo
    assert repo.goes_to_ao3(url) is ao3


def test_ao3_coming_back_mid_retry_carries_on(mock_repo):
    mock_repo.session.request.side_effect = [make_response(status_code=503, text=MAINTENANCE),
                                             make_response(status_code=200, text='ok')]
    assert mock_repo.my_request('GET', AO3_URL).text == 'ok'
    assert mock_repo.ao3_down is False


def test_a_work_quoting_the_maintenance_sentence_is_not_mistaken_for_it():
    work = make_response(text='<div id="workskin"><p>The archive is down for maintenance.</p></div>')
    epub = make_response(content_type='application/epub+zip', text='the archive is down for maintenance')
    assert Repository.is_maintenance_response(work) is False
    assert Repository.is_maintenance_response(epub) is False
    assert Repository.is_maintenance_response(make_response(text=MAINTENANCE)) is True


def test_a_stop_walks_away_from_a_request_ao3_has_not_answered_yet(mock_repo):
    import threading, time
    never = threading.Event()
    mock_repo.pause_slice = 0.01
    pressed = time.monotonic() + 0.05
    mock_repo.cancelled = lambda: time.monotonic() > pressed

    def hang(*args, **kwargs):
        never.wait(5)  # ao3 taking its time - up to the whole timeout
        return make_response(status_code=200, text='late')

    mock_repo.session.request.side_effect = hang
    began = time.monotonic()
    with pytest.raises(exceptions.CancelledException):
        mock_repo.my_request('GET', AO3_URL)
    assert time.monotonic() - began < 1
    never.set()


def test_a_pause_walks_away_from_a_slow_request_and_asks_again_on_resume(mock_repo, capsys):
    import threading, time
    first = threading.Event()
    mock_repo.pause_slice = 0.01
    state = {'held': False, 'calls': 0}
    mock_repo.held = lambda: state['held']
    mock_repo.cancelled = lambda: False

    def answer(*args, **kwargs):
        state['calls'] += 1
        if state['calls'] == 1:
            state['held'] = True     # paused while ao3 is still thinking
            threading.Timer(0.1, lambda: state.update(held=False)).start()  # resumed
            first.wait(5)
            return make_response(status_code=200, text='abandoned')
        return make_response(status_code=200, text='the same page, asked again')

    mock_repo.session.request.side_effect = answer
    result = mock_repo.my_request('GET', AO3_URL)

    assert result.text == 'the same page, asked again'
    assert state['calls'] == 2
    said = capsys.readouterr().out
    assert strings.MESSAGE_HELD in said and strings.MESSAGE_RELEASED in said
    first.set()


def test_a_request_ao3_holds_open_gives_up_at_the_timeout_saying_it_is_waiting(mock_repo, capsys):
    # requests' own timeout fires only on silence; a connection held open got past it
    import threading
    never = threading.Event()
    mock_repo.pause_slice = 0.01
    mock_repo.waiting_note = 0.05
    mock_repo.timeout = 0.2
    mock_repo.max_timeouts = 2
    mock_repo.cancelled = lambda: False

    def held_open(*args, **kwargs):
        never.wait(5)
        return make_response(status_code=200, text='too late')

    mock_repo.session.request.side_effect = held_open
    with pytest.raises(exceptions.TimeoutException):
        mock_repo.my_request('GET', AO3_URL)

    said = capsys.readouterr().out
    assert f'still waiting for AO3 to answer {AO3_URL}' in said
    assert 'did not answer' in said          # the retry after the first timeout, said
    assert mock_repo.session.request.call_count == 2
    never.set()


def test_my_request_unlimited_retries_when_max_retries_zero(mock_repo):
    mock_repo.max_retries = 0
    responses = [make_response(status_code=502)] * 5 + [make_response(status_code=200, text='ok')]
    mock_repo.session.request.side_effect = responses

    result = mock_repo.my_request('GET', AO3_URL)

    assert result.status_code == 200
    assert mock_repo.session.request.call_count == 6


def test_my_request_non_ao3_url_does_not_retry_on_5xx(mock_repo):
    mock_repo.session.request.return_value = make_response(status_code=502)

    with pytest.raises(exceptions.InvalidStatusCodeException):
        mock_repo.my_request('GET', NON_AO3_URL)

    assert mock_repo.session.request.call_count == 1

# endregion


# region my_request — 429 handling

def test_my_request_429_pauses_for_retry_after_header(mock_repo, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleep_calls.append(s))

    first = make_response(status_code=429, headers={'retry-after': '7'})
    second = make_response(status_code=200, text='ok')
    mock_repo.session.request.side_effect = [first, second]

    result = mock_repo.my_request('GET', AO3_URL)

    assert result.status_code == 200
    assert 7 in sleep_calls


def test_my_request_429_defaults_to_300_when_header_missing(mock_repo, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleep_calls.append(s))

    first = make_response(status_code=429)  # no retry-after header
    second = make_response(status_code=200)
    mock_repo.session.request.side_effect = [first, second]

    mock_repo.my_request('GET', AO3_URL)

    assert 300 in sleep_calls


def test_my_request_429_defaults_to_300_when_header_nonnumeric(mock_repo, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleep_calls.append(s))

    first = make_response(status_code=429, headers={'retry-after': 'soon'})
    second = make_response(status_code=200)
    mock_repo.session.request.side_effect = [first, second]

    mock_repo.my_request('GET', AO3_URL)

    assert 300 in sleep_calls


def test_my_request_429_defaults_to_300_when_header_nonpositive(mock_repo, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleep_calls.append(s))

    first = make_response(status_code=429, headers={'retry-after': '0'})
    second = make_response(status_code=200)
    mock_repo.session.request.side_effect = [first, second]

    mock_repo.my_request('GET', AO3_URL)

    assert 300 in sleep_calls


def test_my_request_429_with_cloudflare_body_takes_pause_path_not_retry(mock_repo, monkeypatch):
    """A 429 response that also has a cloudflare-looking body should pause (via retry-after),
    not go down the cloudflare retry/raise branch. Verifies the ordering in my_request."""
    sleep_calls = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleep_calls.append(s))

    first = make_response(
        server='cloudflare',
        status_code=429,
        headers={'retry-after': '42'},
        text='<html><head><title>Just a moment...</title></head></html>')
    second = make_response(status_code=200)
    mock_repo.session.request.side_effect = [first, second]

    result = mock_repo.my_request('GET', AO3_URL)

    assert result.status_code == 200
    # 42 was used as the pause value — so we took the retry-after branch
    assert 42 in sleep_calls

# endregion


# region my_request — cloudflare

def test_my_request_cloudflare_retries_then_raises(mock_repo):
    mock_repo.max_retries = 1
    cf = make_response(
        server='cloudflare', status_code=200,
        text='<html><head><title>Just a moment...</title></head></html>')
    mock_repo.session.request.return_value = cf

    with pytest.raises(exceptions.CloudflareException):
        mock_repo.my_request('GET', AO3_URL)

    assert mock_repo.session.request.call_count == 2


def test_my_request_cloudflare_retries_then_succeeds(mock_repo):
    cf = make_response(
        server='cloudflare', status_code=200,
        text='<html><head><title>Just a moment...</title></head></html>')
    ok = make_response(status_code=200, text='<html><head><title>A Work</title></head></html>')
    mock_repo.session.request.side_effect = [cf, ok]

    result = mock_repo.my_request('GET', AO3_URL)

    assert result is ok

# endregion


# region my_request — exceptions and normalization

def test_my_request_timeout_wraps_as_timeoutexception(mock_repo):
    mock_repo.max_retries = 1
    mock_repo.session.request.side_effect = requests.exceptions.Timeout('boom')

    with pytest.raises(exceptions.TimeoutException) as excinfo:
        mock_repo.my_request('GET', AO3_URL)

    # original Timeout is chained via `raise ... from e`
    assert isinstance(excinfo.value.__cause__, requests.exceptions.Timeout)


def test_my_request_timeout_cuts_off_before_max_retries(mock_repo):
    mock_repo.max_retries = 30
    mock_repo.max_timeouts = 3
    mock_repo.session.request.side_effect = requests.exceptions.Timeout('boom')

    with pytest.raises(exceptions.TimeoutException):
        mock_repo.my_request('GET', AO3_URL)

    # gives up after 3 consecutive timeouts instead of grinding through all 30 retries
    assert mock_repo.session.request.call_count == 3


def test_my_request_timeout_cutoff_applies_with_unlimited_retries(mock_repo):
    mock_repo.max_retries = 0  # unlimited — without the timeout cap this would hang forever
    mock_repo.max_timeouts = 3
    mock_repo.session.request.side_effect = requests.exceptions.Timeout('boom')

    with pytest.raises(exceptions.TimeoutException):
        mock_repo.my_request('GET', AO3_URL)

    assert mock_repo.session.request.call_count == 3


def test_my_request_timeout_streak_resets_on_response(mock_repo):
    mock_repo.max_retries = 30
    mock_repo.max_timeouts = 3
    timeout = requests.exceptions.Timeout('boom')
    interrupting = make_response(status_code=502)
    succeeding = make_response(status_code=200, text='ok')
    # 4 timeouts total, but the 502 response in the middle breaks the streak,
    # so the consecutive-timeout cap of 3 is never reached
    mock_repo.session.request.side_effect = [
        timeout, timeout, interrupting, timeout, timeout, succeeding]

    result = mock_repo.my_request('GET', AO3_URL)

    assert result is succeeding
    assert mock_repo.session.request.call_count == 6


def test_a_rate_limit_break_does_not_reset_the_timeout_count(mock_repo, monkeypatch):
    monkeypatch.setattr('source_code.repo.sleep', lambda s: None)
    mock_repo.max_retries = 30
    mock_repo.max_timeouts = 3
    timeout = requests.exceptions.Timeout('boom')
    slow_down = make_response(status_code=429, headers={'retry-after': '1'})
    # two timeouts, ao3 asks for a break, then one more timeout: that is the third, so it gives up
    mock_repo.session.request.side_effect = [timeout, timeout, slow_down, timeout, make_response(status_code=200)]

    with pytest.raises(exceptions.TimeoutException):
        mock_repo.my_request('GET', AO3_URL)

    assert mock_repo.session.request.call_count == 4


def test_a_rate_limit_break_says_the_timeout_count_it_carries_on_from(mock_repo, monkeypatch, capsys):
    monkeypatch.setattr('source_code.repo.sleep', lambda s: None)
    mock_repo.max_retries = 30
    mock_repo.max_timeouts = 4
    timeout = requests.exceptions.Timeout('boom')
    slow_down = make_response(status_code=429, headers={'retry-after': '1'})
    succeeding = make_response(status_code=200, text='ok')
    mock_repo.session.request.side_effect = [timeout, timeout, slow_down, timeout, succeeding]

    assert mock_repo.my_request('GET', AO3_URL) is succeeding
    said = capsys.readouterr().out
    assert '(timeout 3 of 4)' in said
    assert said.count('(timeout 1 of 4)') == 1


@pytest.mark.parametrize('method, url', [
    ('POST', 'https://archiveofourown.org/users/login'),
    ('GET', 'https://archiveofourown.org/users/Example_Reader/bookmarks?page=2'),
    ('GET', 'https://archiveofourown.org/works/123'),
    ('GET', 'https://download.archiveofourown.org/downloads/123/fic.epub'),
])
def test_every_request_keeps_its_timeout_count_through_a_rate_limit_break(mock_repo, monkeypatch, method, url):
    monkeypatch.setattr('source_code.repo.sleep', lambda s: None)
    mock_repo.max_retries = 30
    mock_repo.max_timeouts = 3
    timeout = requests.exceptions.Timeout('boom')
    slow_down = make_response(status_code=429, headers={'retry-after': '1'})
    mock_repo.session.request.side_effect = [timeout, timeout, slow_down, timeout, make_response(status_code=200)]

    with pytest.raises(exceptions.TimeoutException):
        mock_repo.my_request(method, url)

    assert mock_repo.session.request.call_count == 4


def test_a_rate_limit_break_does_not_reset_the_attempt_count(mock_repo, monkeypatch, capsys):
    monkeypatch.setattr('source_code.repo.sleep', lambda s: None)
    mock_repo.max_retries = 5
    failing = make_response(status_code=502)
    slow_down = make_response(status_code=429, headers={'retry-after': '1'})
    mock_repo.session.request.side_effect = [failing, failing, slow_down, failing, make_response(status_code=200)]

    mock_repo.my_request('GET', AO3_URL)

    said = capsys.readouterr().out
    assert '(attempt 3 of 5)' in said
    assert said.count('(attempt 1 of 5)') == 1


def test_a_rate_limit_break_does_not_reset_the_maintenance_count(mock_repo, monkeypatch):
    monkeypatch.setattr('source_code.repo.sleep', lambda s: None)
    down = make_response(status_code=503, text=MAINTENANCE)
    slow_down = make_response(status_code=429, headers={'retry-after': '1'})
    mock_repo.session.request.side_effect = (
        [down] * Repository.maintenance_retries + [slow_down, down, make_response(status_code=200)])

    with pytest.raises(exceptions.Ao3DownException):
        mock_repo.my_request('GET', AO3_URL)

    assert mock_repo.session.request.call_count == Repository.maintenance_retries + 2


def test_my_request_max_timeouts_zero_disables_cutoff(mock_repo):
    mock_repo.max_retries = 2
    mock_repo.max_timeouts = 0  # early cutoff disabled — behavior governed by max_retries
    mock_repo.session.request.side_effect = requests.exceptions.Timeout('boom')

    with pytest.raises(exceptions.TimeoutException):
        mock_repo.my_request('GET', AO3_URL)

    # attempts 0, 1, 2 → 3 calls before max_retries is exhausted
    assert mock_repo.session.request.call_count == 3


def test_my_request_normalizes_http_to_https_for_ao3(mock_repo):
    mock_repo.session.request.return_value = make_response(status_code=200)

    mock_repo.my_request('GET', 'http://archiveofourown.org/works/123')

    called_url = mock_repo.session.request.call_args[0][1]
    assert called_url == 'https://archiveofourown.org/works/123'


def test_my_request_does_not_normalize_http_for_non_ao3_url(mock_repo):
    mock_repo.session.request.return_value = make_response(status_code=200)

    mock_repo.my_request('GET', 'http://example.com/foo')

    called_url = mock_repo.session.request.call_args[0][1]
    assert called_url == 'http://example.com/foo'

# endregion


# region my_request — side effects

def test_my_request_debug_log_written_on_success(mock_repo, fake_fileops):
    mock_repo.debug = True
    mock_repo.session.request.return_value = make_response(status_code=200)

    mock_repo.my_request('GET', AO3_URL)

    with open(fake_fileops.logfile, encoding='utf-8') as f:
        entry = json.loads(f.readline())
    assert entry['link'] == AO3_URL
    assert entry['level'] == 'debug'
    assert '200' in entry['message']


def test_my_request_extra_wait_sleeps_once_after_success(mock_repo, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleep_calls.append(s))

    mock_repo.extra_wait = 3
    mock_repo.session.request.return_value = make_response(status_code=200)

    mock_repo.my_request('GET', AO3_URL)

    assert sleep_calls == [3]

# endregion


# region get_delay

@pytest.mark.parametrize('attempt', range(11))
def test_get_delay_is_bounded_by_retry_max_delay(mock_repo, attempt):
    delay = mock_repo.get_delay(attempt)
    assert delay <= Repository.retry_max_delay


def test_get_delay_grows_exponentially_until_cap(mock_repo):
    delays = [mock_repo.get_delay(i) for i in range(20)]
    # monotonic non-decreasing
    for earlier, later in zip(delays, delays[1:]):
        assert later >= earlier
    # eventually clamped at retry_max_delay
    assert delays[-1] == Repository.retry_max_delay

# endregion


# region wrapper smoke tests

def test_get_soup_returns_beautifulsoup(mock_repo):
    mock_repo.session.request.return_value = make_response(
        status_code=200, text='<html><body><p>hello</p></body></html>')

    soup = mock_repo.get_soup(AO3_URL)

    assert isinstance(soup, BeautifulSoup)
    assert soup.find('p').text == 'hello'


def test_get_xml_returns_element(mock_repo):
    mock_repo.session.request.return_value = make_response(
        status_code=200, text='<root><child/></root>')

    xml = mock_repo.get_xml(AO3_URL)

    assert isinstance(xml, ET.Element)
    assert xml.tag == 'root'


def test_get_book_returns_bytes(mock_repo):
    mock_repo.session.request.return_value = make_response(
        status_code=200, text='fake-epub-bytes')

    result = mock_repo.get_book(AO3_URL)

    assert result == b'fake-epub-bytes'

# endregion


# region login

def test_login_raises_login_exception_on_invalid_credentials(mock_repo):
    # first GET -> real login page HTML; POST -> response without logged-in body class
    mock_repo.session.request.side_effect = [
        make_response(status_code=200, text=_load_fixture('lockedWorkLoggedOut')),
        make_response(status_code=200, text='<html><body class="logged-out"></body></html>'),
    ]

    with pytest.raises(exceptions.LoginException):
        mock_repo.login('alice', 'bad-password')


def test_login_succeeds_when_logged_in_body_class_present(mock_repo):
    # GET login page uses real AO3 HTML; token is extracted from the real form
    from source_code import parse_soup
    login_html = _load_fixture('lockedWorkLoggedOut')
    expected_token = parse_soup.get_login_token(BeautifulSoup(login_html, 'html.parser'))

    mock_repo.session.request.side_effect = [
        make_response(status_code=200, text=login_html),
        make_response(status_code=200, text='<html><body class="logged-in"></body></html>'),
    ]

    # no exception
    mock_repo.login('alice', 'hunter2')

    post_call = mock_repo.session.request.call_args_list[1]
    method, url = post_call.args[0], post_call.args[1]
    payload = post_call.args[2]
    assert method == 'POST'
    assert url == strings.AO3_LOGIN_URL
    assert payload['authenticity_token'] == expected_token
    assert payload['user[login]'] == 'alice'

# endregion


# region mark_work_as_read

def test_mark_work_as_read_skips_when_token_missing(mock_repo, fake_fileops):
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')

    mock_repo.mark_work_as_read(soup, AO3_URL)

    # no PATCH issued
    mock_repo.session.request.assert_not_called()
    # log entry written
    with open(fake_fileops.logfile, encoding='utf-8') as f:
        entry = json.loads(f.readline())
    assert entry['success'] is False
    assert '123' in entry['link']


def test_mark_work_as_read_posts_patch_with_token(mock_repo):
    # use the real marked-for-later page as the source of the mark-read form
    from source_code import parse_soup
    soup = BeautifulSoup(_load_fixture('markedForLater'), 'html.parser')
    expected_token = parse_soup.get_mark_read_token(soup)
    mock_repo.session.request.return_value = make_response(status_code=200)

    mock_repo.mark_work_as_read(soup, MARKED_FOR_LATER_URL)

    call = mock_repo.session.request.call_args
    method, url, data = call.args[0], call.args[1], call.args[2]
    assert method == 'PATCH'
    assert url == strings.AO3_MARK_READ_URL.format(MARKED_FOR_LATER_WORK_ID)
    assert data == {'authenticity_token': expected_token}


def test_mark_work_as_read_logs_non_200_response(mock_repo, fake_fileops):
    soup = BeautifulSoup(_load_fixture('markedForLater'), 'html.parser')
    mock_repo.session.request.return_value = make_response(status_code=403)

    mock_repo.mark_work_as_read(soup, MARKED_FOR_LATER_URL)

    with open(fake_fileops.logfile, encoding='utf-8') as f:
        entry = json.loads(f.readline())
    assert entry['success'] is False
    assert '403' in entry['error']

# endregion


# region log_error

def test_log_error_no_op_when_debug_false(mock_repo, fake_fileops):
    mock_repo.debug = False

    mock_repo.log_error(AO3_URL, 'test', RuntimeError('boom'))

    assert not __import__('os').path.exists(fake_fileops.logfile)


def test_log_error_includes_stacktrace_for_non_ao3_exception(mock_repo, fake_fileops):
    mock_repo.debug = True

    try:
        raise RuntimeError('boom')
    except RuntimeError as e:
        mock_repo.log_error(AO3_URL, 'test', e)

    with open(fake_fileops.logfile, encoding='utf-8') as f:
        entry = json.loads(f.readline())
    assert 'stacktrace' in entry
    assert 'RuntimeError' in entry['stacktrace']


def test_log_error_omits_stacktrace_for_ao3_exception(mock_repo, fake_fileops):
    mock_repo.debug = True

    mock_repo.log_error(AO3_URL, 'test', exceptions.LockedException('locked'))

    with open(fake_fileops.logfile, encoding='utf-8') as f:
        entry = json.loads(f.readline())
    assert 'stacktrace' not in entry

# endregion


# region download_file — a built link can point at something that is not a file

def test_a_work_file_comes_back_as_its_bytes(mock_repo):
    mock_repo.session.request.return_value = make_response(
        status_code=200, content_type='application/epub+zip', text='epub bytes')

    assert mock_repo.download_file(AO3_URL, 'EPUB') == b'epub bytes'


def test_a_missing_work_is_refused_rather_than_saved(mock_repo):
    # the link is built from the work number, so it can point at a work that is gone.
    # saving ao3's 404 page under an .epub name would look downloaded and be unreadable
    mock_repo.session.request.return_value = make_response(
        status_code=404, content_type='text/html', text='<html>not found</html>')

    with pytest.raises(exceptions.DownloadException) as raised:
        mock_repo.download_file(AO3_URL, 'EPUB')

    # which format, and what ao3 said - a work is reported once, on the first format that
    # fails, so the message is the only place that says which one it was
    assert 'EPUB file' in str(raised.value)
    assert 'status 404' in str(raised.value)


def test_a_page_returned_instead_of_an_ebook_is_refused(mock_repo):
    # 200, but html - a login or error page standing in for the file
    mock_repo.session.request.return_value = make_response(
        status_code=200, content_type='text/html; charset=utf-8', text='<html>sign in</html>')

    with pytest.raises(exceptions.DownloadException) as raised:
        mock_repo.download_file(AO3_URL, 'pdf')

    assert 'PDF file' in str(raised.value)
    assert 'content was a web page' in str(raised.value)


def test_html_really_is_html_so_it_is_judged_on_the_status_alone(mock_repo):
    # the one format where the file and an error page look the same
    mock_repo.session.request.return_value = make_response(
        status_code=200, content_type='text/html; charset=utf-8', text='<html>the fic</html>')

    assert mock_repo.download_file(AO3_URL, 'HTML') == b'<html>the fic</html>'


# endregion


# region stopping a run

def stoppable(fake_fileops, monkeypatch, stop_on_sleep: bool):
    """A repository that can be stopped, and optionally is - while it is waiting."""

    stopped = {'value': False}

    def fake_sleep(_seconds):
        if stop_on_sleep: stopped['value'] = True

    monkeypatch.setattr('source_code.repo.sleep', fake_sleep)
    repo = Repository(fake_fileops, cancelled=lambda: stopped['value'])
    repo.session = MagicMock()
    return repo, stopped


def test_a_stop_during_a_rate_limit_break_unwinds_instead_of_asking_again(
        fake_fileops, monkeypatch):
    # the bug this covers: the wait used to end quietly when stopped, and the loop went
    # straight back to the same request - which simply earned another break the same
    # length, over and over, so the run never actually stopped
    repo, _ = stoppable(fake_fileops, monkeypatch, stop_on_sleep=True)
    repo.session.request.return_value = make_response(
        status_code=429, headers={'retry-after': '600'})

    with pytest.raises(exceptions.CancelledException):
        repo.my_request('GET', AO3_URL)

    assert repo.session.request.call_count == 1


def test_a_stop_is_noticed_during_the_wait_between_requests(fake_fileops, monkeypatch):
    # at 15 or 30 seconds a plain sleep makes a stop look like a hang
    repo, _ = stoppable(fake_fileops, monkeypatch, stop_on_sleep=True)
    repo.extra_wait = 30
    repo.session.request.return_value = make_response(status_code=200, text='ok')

    with pytest.raises(exceptions.CancelledException):
        repo.my_request('GET', AO3_URL)


def test_a_stop_is_noticed_before_a_retry_is_sent(fake_fileops, monkeypatch):
    repo, _ = stoppable(fake_fileops, monkeypatch, stop_on_sleep=True)
    repo.session.request.side_effect = [
        make_response(status_code=500), make_response(status_code=200, text='ok')]

    with pytest.raises(exceptions.CancelledException):
        repo.my_request('GET', AO3_URL)

    assert repo.session.request.call_count == 1


def test_a_stop_already_asked_for_never_reaches_ao3(fake_fileops):
    repo = Repository(fake_fileops, cancelled=lambda: True)
    repo.session = MagicMock()

    with pytest.raises(exceptions.CancelledException):
        repo.my_request('GET', AO3_URL)

    assert repo.session.request.call_count == 0


def test_a_break_is_waited_in_slices_so_a_stop_is_seen_within_a_second(
        fake_fileops, monkeypatch):
    repo, _ = stoppable(fake_fileops, monkeypatch, stop_on_sleep=False)
    sleeps = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleeps.append(s))

    repo.pause(5)

    assert sleeps == [1, 1, 1, 1, 1]


def test_a_break_is_one_sleep_when_there_is_nothing_that_could_stop_it(
        fake_fileops, monkeypatch):
    # the console has no stop button, so slicing the wait would only add wake-ups
    sleeps = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleeps.append(s))
    repo = Repository(fake_fileops)

    repo.pause(600)

    assert sleeps == [600]

# endregion


# region pausing a run

def pausable(fake_fileops, monkeypatch, release_after: int):
    """A repository the user has paused, released after that many checks of the pause."""

    state = {'held': True, 'sleeps': 0, 'stopped': False}

    def fake_sleep(_seconds):
        state['sleeps'] += 1
        if state['sleeps'] >= release_after: state['held'] = False

    monkeypatch.setattr('source_code.repo.sleep', fake_sleep)
    repo = Repository(fake_fileops, cancelled=lambda: state['stopped'],
                      held=lambda: state['held'])
    repo.session = MagicMock()
    return repo, state


def test_a_run_nobody_paused_waits_for_nothing(fake_fileops, monkeypatch):
    # the gate is on the path every single request takes, so it has to cost nothing at all
    # when it is not in use
    sleeps = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleeps.append(s))
    events: list[dict] = []
    repo = Repository(fake_fileops, progress=events.append, held=lambda: False)
    repo.session = MagicMock()
    repo.session.request.return_value = make_response(status_code=200, text='ok')

    repo.my_request('GET', AO3_URL)

    assert sleeps == []
    assert not [e for e in events if e['type'] == progress.HELD]


def test_a_paused_run_asks_ao3_for_nothing_until_it_is_resumed(fake_fileops, monkeypatch):
    repo, state = pausable(fake_fileops, monkeypatch, release_after=3)
    repo.session.request.return_value = make_response(status_code=200, text='ok')

    repo.my_request('GET', AO3_URL)

    # it waited instead of asking, and went exactly once, after being let go
    assert state['sleeps'] == 3
    assert repo.session.request.call_count == 1


def test_a_pause_arriving_mid_request_lets_that_request_finish(fake_fileops, monkeypatch):
    # the safety property the whole design rests on. the gate sits *before* a request, so a
    # pause pressed while one is in flight cannot cut it short - which is what would leave
    # a part-written file carrying a name that says it is complete
    state = {'held': False}
    monkeypatch.setattr('source_code.repo.sleep', lambda s: None)
    repo = Repository(fake_fileops, held=lambda: state['held'])
    repo.session = MagicMock()

    def respond(*args, **kwargs):
        state['held'] = True  # the user hits pause while this one is being fetched
        return make_response(status_code=200, text='ok')

    repo.session.request.side_effect = respond

    response = repo.my_request('GET', AO3_URL)

    assert response.text == 'ok'  # finished and handed back, not abandoned partway


def test_a_stop_while_paused_unwinds_rather_than_waiting_to_be_resumed(
        fake_fileops, monkeypatch):
    # a pause must never be able to trap a run. nobody is coming to resume it, and the
    # stop button has to work straight through a pause
    repo, state = pausable(fake_fileops, monkeypatch, release_after=999)
    monkeypatch.setattr('source_code.repo.sleep',
                        lambda _s: state.__setitem__('stopped', True))
    repo.session.request.return_value = make_response(status_code=200, text='ok')

    with pytest.raises(exceptions.CancelledException):
        repo.my_request('GET', AO3_URL)

    repo.session.request.assert_not_called()


def test_a_stop_while_paused_never_claims_the_run_resumed(fake_fileops, monkeypatch):
    events: list[dict] = []
    repo, state = pausable(fake_fileops, monkeypatch, release_after=999)
    repo.progress = events.append
    monkeypatch.setattr('source_code.repo.sleep',
                        lambda _s: state.__setitem__('stopped', True))
    repo.session.request.return_value = make_response(status_code=200, text='ok')

    with pytest.raises(exceptions.CancelledException):
        repo.my_request('GET', AO3_URL)

    assert [e['type'] for e in events if e['type'] in (progress.HELD, progress.RELEASED)] \
        == [progress.HELD]


def test_a_pause_says_so_once_and_says_when_it_is_over(fake_fileops, monkeypatch):
    events: list[dict] = []
    repo, _ = pausable(fake_fileops, monkeypatch, release_after=2)
    repo.progress = events.append
    repo.session.request.return_value = make_response(status_code=200, text='ok')

    repo.my_request('GET', AO3_URL)

    assert [e['type'] for e in events if e['type'] in (progress.HELD, progress.RELEASED)] \
        == [progress.HELD, progress.RELEASED]


def real_response(body: bytes, status_code: int = 200, content_type: str = 'text/html'):
    """A genuine requests.Response over a real stream.

    The MagicMock responses used elsewhere in this file cannot exercise `read_body` at all:
    iter_content on a mock yields nothing and .text keeps whatever it was handed, so the
    streaming would look right while doing nothing whatsoever. These tests build the real
    object because what is being checked is that a body arrives complete through it.
    """

    raw = urllib3.HTTPResponse(body=io.BytesIO(body), status=status_code,
                               headers={'Content-Type': content_type},
                               preload_content=False)
    response = requests.Response()
    response.raw = raw
    response.status_code = status_code
    response.headers.update({'Content-Type': content_type})
    response.url = AO3_URL
    return response


def test_a_streamed_body_arrives_whole(fake_fileops):
    # the body comes down in pieces now so a pause can land between them; everything
    # downstream still has to see one complete response
    repo = Repository(fake_fileops)
    repo.chunk_size = 4
    repo.session = MagicMock()
    repo.session.request.return_value = real_response(b'a page of html, in pieces')

    response = repo.my_request('GET', AO3_URL)

    assert response.content == b'a page of html, in pieces'
    assert response.text == 'a page of html, in pieces'


def test_a_pause_partway_through_a_body_fetches_the_whole_thing_again(fake_fileops,
                                                                     monkeypatch):
    # what the pause button is for during a large download: drop what has arrived, wait,
    # then ask for the file again from the beginning rather than finishing it first
    state = {'held': False}
    monkeypatch.setattr('source_code.repo.sleep', lambda _s: state.__setitem__('held', False))
    repo = Repository(fake_fileops, held=lambda: state['held'])
    repo.chunk_size = 4
    repo.session = MagicMock()

    def respond(*args, **kwargs):
        # the user hits pause while the first copy is coming down
        if repo.session.request.call_count == 1: state['held'] = True
        return real_response(b'the whole pdf, eventually')

    repo.session.request.side_effect = respond

    response = repo.my_request('GET', AO3_URL)

    assert repo.session.request.call_count == 2   # asked again, from the start
    assert response.content == b'the whole pdf, eventually'   # and got all of it


def test_a_pause_partway_through_a_body_does_not_count_as_a_failed_attempt(fake_fileops,
                                                                          monkeypatch):
    # pausing is not the server failing, so it must not eat into the retry budget
    state = {'held': False}
    monkeypatch.setattr('source_code.repo.sleep', lambda _s: state.__setitem__('held', False))
    repo = Repository(fake_fileops, held=lambda: state['held'])
    repo.chunk_size = 4
    repo.max_retries = 1
    repo.session = MagicMock()

    def respond(*args, **kwargs):
        if repo.session.request.call_count == 1: state['held'] = True
        return real_response(b'still comes down in the end')

    repo.session.request.side_effect = respond

    assert repo.my_request('GET', AO3_URL).content == b'still comes down in the end'


def test_a_post_paused_partway_is_handed_back_to_be_started_again(fake_fileops, monkeypatch):
    # a login form ao3 may already have taken is not one to send twice: the caller holds,
    # then starts the whole login again with a fresh token
    state = {'held': False}
    monkeypatch.setattr('source_code.repo.sleep', lambda _s: None)
    repo = Repository(fake_fileops, held=lambda: state['held'])
    repo.chunk_size = 4
    repo.session = MagicMock()

    def respond(*args, **kwargs):
        state['held'] = True  # the user hits pause while the form is going up
        return real_response(b'the form went through')

    repo.session.request.side_effect = respond

    with pytest.raises(exceptions.PausedException):
        repo.my_request('POST', AO3_URL, {'user': 'someone'})
    assert repo.session.request.call_count == 1


def test_a_login_paused_partway_holds_then_logs_in_again_from_a_fresh_page(
        fake_fileops, monkeypatch):
    repo = Repository(fake_fileops)
    pages = iter(['<form>token</form>', '<form>token</form>'])
    monkeypatch.setattr(repo, 'get_soup', lambda url: BeautifulSoup(next(pages), 'html.parser'))
    monkeypatch.setattr('source_code.repo.parse_soup.get_login_token', lambda soup: 't')
    held = []
    monkeypatch.setattr(repo, 'hold_if_asked', lambda: held.append(1))
    posts = []

    def post(method, url, data=None):
        posts.append(method)
        if len(posts) == 1: raise exceptions.PausedException()
        return real_response(b'<body class="logged-in"></body>')
    monkeypatch.setattr(repo, 'my_request', post)
    monkeypatch.setattr('source_code.repo.parse_soup.is_logged_in',
                        lambda soup: 'logged-in' in str(soup))

    repo.login('someone', 'secret')

    assert held == [1] and posts == ['POST', 'POST']


def test_a_login_paused_after_ao3_took_the_form_is_already_done(fake_fileops, monkeypatch):
    repo = Repository(fake_fileops)
    pages = iter(['<form>token</form>', '<body class="logged-in"></body>'])
    monkeypatch.setattr(repo, 'get_soup', lambda url: BeautifulSoup(next(pages), 'html.parser'))
    monkeypatch.setattr('source_code.repo.parse_soup.get_login_token', lambda soup: 't')
    monkeypatch.setattr(repo, 'hold_if_asked', lambda: None)
    posts = []

    def post(method, url, data=None):
        posts.append(method)
        raise exceptions.PausedException()
    monkeypatch.setattr(repo, 'my_request', post)
    monkeypatch.setattr('source_code.repo.parse_soup.is_logged_in',
                        lambda soup: 'logged-in' in str(soup))

    repo.login('someone', 'secret')

    assert posts == ['POST']


def test_a_pause_lands_during_a_break_and_the_time_held_counts_toward_it(
        fake_fileops, monkeypatch):
    state = {'held': True}
    sleeps = []
    monkeypatch.setattr('source_code.repo.sleep', lambda s: sleeps.append(s))
    clock = iter([100.0, 103.0])
    monkeypatch.setattr('source_code.repo.monotonic', lambda: next(clock))
    repo = Repository(fake_fileops, cancelled=lambda: False, held=lambda: state['held'])
    holds = []

    def hold():
        holds.append(1)
        state['held'] = False   # resumed after three seconds
    monkeypatch.setattr(repo, 'hold_if_asked', hold)

    repo.pause(5)

    # held at once, and only the two seconds left of the break waited out after
    assert holds == [1] and sleeps == [1, 1]


def test_a_stop_partway_through_a_body_unwinds(fake_fileops):
    repo = Repository(fake_fileops, cancelled=lambda: True)
    repo.chunk_size = 4
    repo.session = MagicMock()
    repo.session.request.return_value = real_response(b'abandoned halfway down')

    with pytest.raises(exceptions.CancelledException):
        repo.my_request('GET', AO3_URL)


def test_a_pause_is_kept_apart_from_a_break_ao3_demanded(fake_fileops, monkeypatch):
    # they look alike on screen and are nothing alike underneath: one ends by itself, the
    # other ends only when the user says so. sharing an event would make them
    # indistinguishable to the ui
    events: list[dict] = []
    repo, _ = pausable(fake_fileops, monkeypatch, release_after=1)
    repo.progress = events.append
    repo.session.request.return_value = make_response(status_code=200, text='ok')

    repo.my_request('GET', AO3_URL)

    assert not [e for e in events if e['type'] == progress.PAUSED]

# endregion
