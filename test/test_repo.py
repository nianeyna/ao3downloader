"""Tests for ao3downloader.repo — cloudflare detection, retry logic, login, marking."""

import json
import os
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

import pytest
import requests
from bs4 import BeautifulSoup

from ao3downloader import exceptions, strings
from ao3downloader.repo import Repository

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
    monkeypatch.setattr('ao3downloader.repo.sleep', lambda s: sleep_calls.append(s))

    first = make_response(status_code=429, headers={'retry-after': '7'})
    second = make_response(status_code=200, text='ok')
    mock_repo.session.request.side_effect = [first, second]

    result = mock_repo.my_request('GET', AO3_URL)

    assert result.status_code == 200
    assert 7 in sleep_calls


def test_my_request_429_defaults_to_300_when_header_missing(mock_repo, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr('ao3downloader.repo.sleep', lambda s: sleep_calls.append(s))

    first = make_response(status_code=429)  # no retry-after header
    second = make_response(status_code=200)
    mock_repo.session.request.side_effect = [first, second]

    mock_repo.my_request('GET', AO3_URL)

    assert 300 in sleep_calls


def test_my_request_429_defaults_to_300_when_header_nonnumeric(mock_repo, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr('ao3downloader.repo.sleep', lambda s: sleep_calls.append(s))

    first = make_response(status_code=429, headers={'retry-after': 'soon'})
    second = make_response(status_code=200)
    mock_repo.session.request.side_effect = [first, second]

    mock_repo.my_request('GET', AO3_URL)

    assert 300 in sleep_calls


def test_my_request_429_defaults_to_300_when_header_nonpositive(mock_repo, monkeypatch):
    sleep_calls = []
    monkeypatch.setattr('ao3downloader.repo.sleep', lambda s: sleep_calls.append(s))

    first = make_response(status_code=429, headers={'retry-after': '0'})
    second = make_response(status_code=200)
    mock_repo.session.request.side_effect = [first, second]

    mock_repo.my_request('GET', AO3_URL)

    assert 300 in sleep_calls


def test_my_request_429_with_cloudflare_body_takes_pause_path_not_retry(mock_repo, monkeypatch):
    """A 429 response that also has a cloudflare-looking body should pause (via retry-after),
    not go down the cloudflare retry/raise branch. Verifies the ordering in my_request."""
    sleep_calls = []
    monkeypatch.setattr('ao3downloader.repo.sleep', lambda s: sleep_calls.append(s))

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
    monkeypatch.setattr('ao3downloader.repo.sleep', lambda s: sleep_calls.append(s))

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
    from ao3downloader import parse_soup
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
    from ao3downloader import parse_soup
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
