"""Web requests go here."""

import urllib.parse
import datetime
import threading
import traceback
import xml.etree.ElementTree as ET
from collections.abc import Callable
from time import monotonic, sleep

import requests
from bs4 import BeautifulSoup
from requests import codes

from source_code import exceptions, parse_soup, parse_text, progress, strings
from source_code.fileio import FileOps
from source_code.progress import ProgressCallback


def seconds(value: float) -> str:
    """A wait as a person reads it: whole seconds, or one decimal under one."""

    return f'{value:.1f}' if value < 1 else f'{value:.0f}'



def goes_to_ao3(url: str) -> bool:
    """Whether a request is to ao3 itself, judged by the host it goes to.

    Not by the url containing ao3's name: FicHub is asked about a work by its ao3 link, so
    its url carries `archiveofourown.org` in the query. Judged that way, a run that found ao3
    down refused FicHub too - the one place left to get the work from.
    """

    try:
        host = (urllib.parse.urlsplit(url).hostname or '').lower()
    except ValueError:
        return False
    return host == strings.AO3_DOMAIN or host.endswith('.' + strings.AO3_DOMAIN)

class Repository:

    headers = {'user-agent': 'ao3downloader +nianeyna@gmail.com'}
    timeout = 60

    retry_statuses = frozenset([500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530])
    # how long a cancellable pause waits before checking whether it has been stopped
    pause_slice = 1
    # how often a run says it is still waiting on a request ao3 has not answered
    waiting_note = 15
    # how much of a response body to take at a time. small enough that a pause is noticed
    # promptly on a slow line, large enough not to spin through a fast one.
    chunk_size = 64 * 1024
    retry_initial_delay = 0.1
    retry_max_delay = 30
    # how many times a request is asked again once ao3 says it is down for maintenance, and
    # how long apart. maintenance is usually minutes or hours, not seconds, so the full
    # MaxRetries would only spend a quarter of an hour per request learning nothing new
    maintenance_retries = 2
    # the status of the last page `get_soup` fetched
    last_status: int | None = None
    # the zone a run's lines say a time in (the person's AO3 zone); None is UTC
    zone = None
    maintenance_delay = 30


    def __init__(self, fileops: FileOps, progress: ProgressCallback | None = None,
                 cancelled: Callable[[], bool] | None = None,
                 held: Callable[[], bool] | None = None) -> None:
        self.fileops = fileops
        self.progress = progress
        self.cancelled = cancelled
        self.held = held
        self.session = requests.Session()
        self.debug = fileops.get_ini_value_boolean(strings.INI_DEBUG_LOGGING, False)
        self.extra_wait = fileops.get_ini_value_integer(strings.INI_WAIT_TIME, 0)
        self.max_retries = fileops.get_ini_value_integer(strings.INI_MAX_RETRIES, 0)
        self.max_timeouts = fileops.get_ini_value_integer(strings.INI_MAX_TIMEOUTS, 3)
        # the time limits below are settings; the class's values are the defaults, and what a
        # settings.ini that cannot be read (or a test's stand-in) leaves in force
        self.timeout = self.setting(strings.INI_REQUEST_TIMEOUT, type(self).timeout, 1)
        self.waiting_note = self.setting(strings.INI_STILL_WAITING, type(self).waiting_note, 1)
        self.maintenance_retries = self.setting(strings.INI_MAINTENANCE_RETRIES,
                                                type(self).maintenance_retries)
        self.maintenance_delay = self.setting(strings.INI_MAINTENANCE_DELAY,
                                              type(self).maintenance_delay)
        self.retry_max_delay = self.setting(strings.INI_RETRY_MAX_DELAY,
                                            type(self).retry_max_delay)
        # True once logged in, False for a run told not to, None until either is known
        self.logged_in: bool | None = None
        # set once a request has given up on ao3's maintenance page: every later request to
        # ao3 fails at once with the same answer, rather than retrying its way to it again
        self.ao3_down = False


    def __enter__(self):
        return self


    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.session.close()


    def check_cancelled(self) -> None:
        """Raise if a stop has been asked for, so the caller unwinds rather than carries on."""

        if self.cancelled is not None and self.cancelled():
            raise exceptions.CancelledException()


    def wait(self, seconds: float) -> None:
        """Sleep, in slices, so that a stop is noticed instead of waited out.

        Raises CancelledException rather than returning quietly. A stop has to unwind the
        request, not just cut the wait short: ao3 asks for several minutes at a time, and
        going straight back to the same request only earns another break of the same length.
        """

        if seconds <= 0: return

        # nothing can interrupt a caller that cannot cancel, so it just waits
        if self.cancelled is None:
            sleep(seconds)
            return

        # a pause lands here too, at once - and the time it is held counts toward the wait,
        # since ao3's clock keeps running whether or not the run is paused. resumed, the run
        # waits out only what is left of it, then carries on with the request it was waiting
        # to make
        remaining = seconds
        while remaining > 0:
            self.check_cancelled()
            if self.held is not None and self.held():
                began = monotonic()
                self.hold_if_asked()
                remaining -= monotonic() - began
                continue
            slice_length = min(self.pause_slice, remaining)
            sleep(slice_length)
            remaining -= slice_length
        self.check_cancelled()


    def pause(self, seconds: int) -> None:
        """Wait out an ao3 rate limit break. Raises if stopped partway through."""

        self.wait(seconds)


    def fetch(self, method: str, url: str, data) -> requests.Response:
        """One request, body and all."""

        response = self.session.request(method, url, data, headers=self.headers,
                                        timeout=self.timeout, stream=True)
        self.read_body(response, method)
        return response


    def abandonable(self, method: str, call: Callable[[], requests.Response],
                    url: str = '') -> requests.Response:
        """Make one request in a way that a stop or a pause can walk away from at once.

        Stop and pause used to be noticed only between a body's chunks and before a request
        went out. Waiting for ao3 to start answering - up to `timeout` seconds, again on every
        retry - noticed neither, and a run pressed to stop sat saying 'stopping' while it
        waited. So the request runs on a thread of its own and this one watches, a slice at a
        time: a stop raises `CancelledException`, a pause on a GET raises `PausedException`
        (the caller holds, then asks for the same thing again from the start).

        Nothing is lost by walking away: the bytes are in memory until the whole body has
        arrived and been judged, so nothing has been written. The abandoned thread is left to
        finish or time out on its own; it reads no further than its next chunk, because
        `read_body` checks the same stop and pause. **Every method is abandoned for a pause**,
        a POST included: a PATCH (mark as read) is asked again as it was, while a POST -
        the login - is handed back to its caller (`my_request` re-raises `PausedException`),
        which holds and then starts the whole login again with a fresh token, since a login
        form ao3 may already have taken is not one to send twice.

        **`timeout` is a limit on the whole request here**, not only on silence: requests'
        own timeout fires only when the connection says nothing for that long, so a server
        that holds it open, or trickles a byte at a time, kept a request going for many
        minutes while the run said nothing. Past `timeout` this raises `TimeoutException`,
        which `my_request` retries and counts toward `MaxTimeouts` like any other. Every
        `waiting_note` seconds until then the run says it is still waiting, and on what.
        """

        if self.cancelled is None and self.held is None: return call()

        result: dict = {}
        finished = threading.Event()

        def run() -> None:
            try:
                result['response'] = call()
            except BaseException as e:
                result['error'] = e
            finally:
                finished.set()

        threading.Thread(target=run, daemon=True).start()
        began = monotonic()
        said = 0
        while not finished.wait(self.pause_slice):
            self.check_cancelled()
            if self.held is not None and self.held():
                raise exceptions.PausedException()
            waited = monotonic() - began
            if waited >= self.timeout:
                raise exceptions.TimeoutException(strings.ERROR_TIMEOUT.format(self.timeout))
            if waited >= (said + 1) * self.waiting_note:
                said += 1
                print(strings.MESSAGE_STILL_WAITING.format(url, said * self.waiting_note))
        if 'error' in result: raise result['error']
        return result['response']


    def read_body(self, response, method: str) -> None:
        """Pull a response body down in pieces, so a pause or a stop lands during it.

        Without this the whole body arrives inside one call and nothing can interrupt it -
        a large pdf on a slow line would leave the pause button looking broken for as long
        as the transfer took.

        Abandoning a body costs nothing. The bytes are held in memory and are only written
        once the caller has them all and has judged them, so there is no part-written file
        to clean up and the retry starts from nothing.

        Every method is abandoned for a pause - see `abandonable` for what then happens to a
        POST.
        """

        chunks = []
        try:
            for chunk in response.iter_content(self.chunk_size):
                chunks.append(chunk)
                self.check_cancelled()
                if self.held is not None and self.held():
                    raise exceptions.PausedException()
        except BaseException:
            # the connection is no use half-read, and leaving it open holds a pool slot
            response.close()
            raise

        # requests sets these itself for a body it read in one go. filling them in here is
        # what lets everything downstream - .content, .text, .json() - carry on unchanged,
        # so streaming stays an implementation detail of this method.
        response._content = b''.join(chunks)
        response._content_consumed = True


    def hold_if_asked(self) -> None:
        """Wait here for as long as the user has the run paused.

        Called wherever a pause lands - before a request, after one abandoned for a pause,
        inside `wait` (whose caller counts the time held toward the wait), and before every
        request to the library (`PageStorage.gate`). Never inside a write: bytes are held in
        memory until a body is whole and judged, and a library write is one request, so at
        every one of these points nothing on disk is open, part-written or renamed. Do not add
        a gate inside a download or a save loop - see CLAUDE.md.

        A stop still works while held - the wait is in slices and each one checks - so a
        paused run is never a stuck one. A stop taken here unwinds without ever claiming
        to have resumed.
        """

        if self.held is None or not self.held(): return

        print(strings.MESSAGE_HELD)
        progress.report(self.progress, progress.HELD)

        while self.held():
            self.check_cancelled()
            sleep(self.pause_slice)
        self.check_cancelled()

        print(strings.MESSAGE_RELEASED)
        progress.report(self.progress, progress.RELEASED)


    def get_xml(self, url: str) -> ET.Element:
        """Get XML object from a url."""

        content = self.my_request('GET', url).content
        xml = ET.XML(content)
        return xml


    def get_soup(self, url: str) -> BeautifulSoup:
        """Get BeautifulSoup object from a url."""

        response = self.my_request('GET', url)
        # kept for whoever asked, so a page ao3 answered with 401, 403 or 404 - served like
        # any other - can be told from the page that was wanted (`Ao3.fetch_page`)
        self.last_status = response.status_code
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup


    def get_book(self, url: str) -> bytes:
        """Get content from url. Intended for downloading works from ao3."""

        response = self.my_request('GET', url).content
        return response


    def download_file(self, url: str, filetype: str) -> bytes:
        """Fetch a work file from a link built rather than read off the work page.

        Because the link is constructed from the work number, it can point at a work that
        has been deleted, made restricted, or was never available in that format. Ao3
        answers those with a page, and saving that page under an .epub name would be worse
        than failing outright - the file would look downloaded and be unreadable.
        """

        response = self.my_request('GET', url)

        # the format is named in the error: a work is recorded as a failure once, on the
        # first format that fails, so without it nobody could tell whether it was the epub
        # that ao3 lacks or every format at once
        shown = filetype.upper()
        if response.status_code != codes['ok']:
            raise exceptions.DownloadException(strings.ERROR_NOT_A_WORK_FILE.format(
                shown, strings.ERROR_NOT_A_WORK_FILE_STATUS.format(response.status_code)))

        # html is the one format where a page and a file look alike, so it is judged on the
        # status alone; for the rest, html coming back means something went wrong
        if shown != 'HTML':
            content_type = (response.headers.get('Content-Type') or '').lower()
            if 'text/html' in content_type:
                raise exceptions.DownloadException(strings.ERROR_NOT_A_WORK_FILE.format(
                    shown, strings.ERROR_NOT_A_WORK_FILE_TYPE.format(response.status_code)))

        return response.content


    def my_request(self, method: str, url: str, data: dict[str, str] | None = None) -> requests.Response:
        """Get response from a url."""

        # normalize http -> https for ao3 links. older downloaded works may contain http
        # links in their embedded metadata, and the resulting redirect trips cloudflare.
        to_ao3 = goes_to_ao3(url)
        if to_ao3 and url.lower().startswith('http://'):
            url = 'https://' + url[len('http://'):]

        attempt = 0
        timeouts = 0
        maintenance = 0

        while True:
            # a stop asked for while this was retrying or waiting must not start it again
            self.check_cancelled()
            # ao3 already said it is down on this run: nothing to gain by asking again
            if to_ao3 and self.ao3_down:
                raise exceptions.Ao3DownException(strings.ERROR_AO3_DOWN)
            # and a pause holds here, before the request, rather than anywhere it could
            # catch a transfer in progress
            self.hold_if_asked()
            should_retry = to_ao3 and (self.max_retries == 0 or attempt < self.max_retries)
            retry_delay = self.get_delay(attempt)

            try:
                try:
                    response = self.abandonable(method, lambda: self.fetch(method, url, data), url)
                except requests.exceptions.Timeout as e: # raw timeout exceptions are way too verbose
                    raise exceptions.TimeoutException(strings.ERROR_TIMEOUT.format(self.timeout)) from e
            except exceptions.PausedException:
                # a login form ao3 may already have taken is not one to send again: its
                # caller holds, then starts the login over with a fresh token
                if method.upper() == 'POST': raise
                # the body was abandoned partway through. wait for the resume, then ask for
                # the whole thing again - nothing was kept, so this starts clean. it does
                # not count as an attempt: the user pausing is not the server failing
                self.hold_if_asked()
                continue
            except Exception as e:
                # a page that times out repeatedly is unlikely to recover, so give up after (consecutive) 
                # timeouts reach the configured limit to avoid wasting a lot of time on a dead page.
                if isinstance(e, exceptions.TimeoutException):
                    timeouts += 1
                else:
                    timeouts = 0
                timeout_capped = self.max_timeouts != 0 and timeouts >= self.max_timeouts
                if should_retry and not timeout_capped:
                    attempt += 1
                    self.log_error(url, strings.MESSAGE_RETRY.format(method, attempt, retry_delay), e)
                    if isinstance(e, exceptions.TimeoutException):
                        print(strings.MESSAGE_TIMED_OUT_RETRYING.format(
                            url, seconds(retry_delay), timeouts, self.max_timeouts or 'no limit'))
                    self.wait(retry_delay)
                    continue
                else:
                    self.log_error(url, strings.ERROR_HTTP_REQUEST, e)
                    raise

            # an answer ends a run of timeouts - all but ao3 asking us to slow down, which says
            # nothing about whether the page loads: after the break the count carries on from
            # where it was, so a third timeout is still the third, not the first again
            if response.status_code != codes['too_many_requests']:
                timeouts = 0

            # ao3's maintenance page comes back in place of whatever was asked for, whatever
            # its status. asked about a couple of times, out loud, then given up on for the run
            if to_ao3 and self.is_maintenance_response(response):
                maintenance += 1
                if maintenance > self.maintenance_retries:
                    self.ao3_down = True
                    raise exceptions.Ao3DownException(strings.ERROR_AO3_DOWN)
                print(strings.MESSAGE_AO3_DOWN_RETRY.format(
                    self.maintenance_delay, maintenance, self.maintenance_retries))
                self.wait(self.maintenance_delay)
                continue

            if response.status_code in self.retry_statuses:
                if self.retry_or_raise(should_retry, attempt, method, url, retry_delay,
                        str(response.status_code),
                        exceptions.InvalidStatusCodeException(strings.ERROR_INVALID_STATUS_CODE.format(response.status_code))):
                    attempt += 1
                    continue

            if response.status_code == codes['too_many_requests']:
                try:
                    pause_time = int(response.headers['retry-after'])
                except:
                    pause_time = 300  # default to 5 minutes in case there was a problem getting retry-after
                if pause_time <= 0:
                    pause_time = 300  # default to 5 minutes if retry-after is an invalid value
                # said in the person's AO3 zone when the run has one, else UTC - named either way
                zone = self.zone or datetime.timezone.utc
                label = str(getattr(self.zone, 'key', None) or 'UTC') if self.zone else 'UTC'
                now = datetime.datetime.now(zone)
                later = now + datetime.timedelta(0, pause_time)
                print(strings.MESSAGE_TOO_MANY_REQUESTS.format(pause_time, now.strftime('%H:%M:%S ') + label, later.strftime('%H:%M:%S ') + label))
                progress.report(self.progress, progress.PAUSED, seconds=pause_time,
                                until=later.strftime('%H:%M:%S ') + label)
                self.pause(pause_time)
                print(strings.MESSAGE_RESUMING)
                progress.report(self.progress, progress.RESUMED)
                continue

            # this check follows the retry-after check because a cloudflare response that is also 
            # a 429 can happen, and should be handled with pause logic rather than retry logic
            if self.is_cloudflare_response(response):
                if self.retry_or_raise(should_retry, attempt, method, url, retry_delay,
                        strings.ERROR_CLOUDFLARE,
                        exceptions.CloudflareException(strings.ERROR_CLOUDFLARE)):
                    attempt += 1
                    continue

            # cancellable: at 15 or 30 seconds a plain sleep makes a stop look like a hang
            if self.extra_wait > 0: self.wait(self.extra_wait)

            if self.debug:
                self.fileops.write_log(
                    {'link': url, 'message': strings.MESSAGE_SUCCESS.format(method, response.status_code),
                     'level': 'debug'})

            return response


    def login(self, username: str, password: str):
        """Login to ao3."""

        # a run told not to log in never gets here, and `Ao3.check_session` reads this to
        # know there is no session to have lapsed
        self.logged_in = True

        while True:
            soup = self.get_soup(strings.AO3_LOGIN_URL)
            if not soup: raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NOT_FOUND))
            # a login paused after ao3 had taken the form: the session is already logged in
            if parse_soup.is_logged_in(soup): return
            token = parse_soup.get_login_token(soup)
            payload = parse_text.get_payload(username, password, token)
            try:
                response = self.my_request('POST', strings.AO3_LOGIN_URL, payload)
                break
            except exceptions.PausedException:
                # paused mid-login: hold, then log in again from a fresh login page - the
                # interrupted line, asked again
                self.hold_if_asked()
        soup = BeautifulSoup(response.text, 'html.parser')
        if not soup: raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NO_RESPONSE))
        if not parse_soup.is_logged_in(soup): # raise exception type that indicates we should clear username and password data
            raise exceptions.LoginException(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_INVALID_CREDENTIALS))
        

    def still_logged_in(self) -> bool:
        """Whether ao3 still recognises this session.

        Every ao3 page carries `<body class="logged-in">` while a session is alive, so any
        page will answer it - the front page is the cheapest.

        **A check that cannot be made answers True.** This exists to end a run early when
        the login has lapsed; ending one because the check itself timed out would be worse
        than the problem, so anything going wrong here means carry on as before.
        """

        try:
            return parse_soup.is_logged_in(self.get_soup(strings.AO3_BASE_URL))
        except Exception:
            return True


    def mark_work_as_read(self, soup: BeautifulSoup, work_url: str):
        """Mark a work as read on ao3."""

        work_id = parse_text.get_work_number(work_url)
        link = strings.AO3_MARK_READ_URL.format(work_id)
        token = parse_soup.get_mark_read_token(soup)
        if not token:
            self.fileops.write_log({'link': link, 'message': strings.ERROR_MARK_READ_SKIP, 'success': False})
            return
        payload = {'authenticity_token': token}
        try:
            response = self.my_request('PATCH', link, payload)
            if response.status_code != codes['ok']:
                log = {'link': link, 'message': strings.ERROR_MARK_READ, 'error': 
                       strings.ERROR_INVALID_STATUS_CODE.format(response.status_code), 'success': False}
                self.fileops.write_log(log)
        except Exception as e:
            log = {'link': link, 'message': strings.ERROR_MARK_READ, 'error': str(e), 'success': False}
            if not isinstance(e, exceptions.Ao3DownloaderException):
                log['stacktrace'] = ''.join(traceback.TracebackException.from_exception(e).format())
            self.fileops.write_log(log)


    def retry_or_raise(self, should_retry: bool, attempt: int, method: str, url: str,
                       retry_delay: float, error: str, exc: Exception) -> bool:
        """Retry the request if possible, otherwise raise the given exception.
        Returns True if the caller should continue the retry loop.

        The wait goes through `wait`, so a stop lands during it - this was a plain sleep, and
        a run retrying ao3's error pages could not be stopped for a quarter of an hour. Each
        retry is said in the run, or a run doing nothing but retrying looks hung.
        """
        if should_retry:
            if self.debug:
                self.fileops.write_log(
                    {'link': url, 'message': strings.MESSAGE_RETRY.format(method, attempt + 1, retry_delay),
                     'error': error, 'level': 'debug'})
            if self.max_retries:
                print(strings.MESSAGE_RETRYING.format(error, url, seconds(retry_delay),
                                                      attempt + 1, self.max_retries))
            else:
                print(strings.MESSAGE_RETRYING_UNLIMITED.format(error, url, seconds(retry_delay),
                                                                attempt + 1))
            self.wait(retry_delay)
            return True
        raise exc


    @staticmethod
    def is_maintenance_response(response: requests.Response) -> bool:
        """Whether this is ao3's 'The archive is down for maintenance' page.

        A small html page carrying that sentence. A work's own text could quote it, so a page
        with a work on it (`workskin`) never counts, and nor does anything that is not html -
        a downloaded epub or pdf is never mistaken for it.
        """

        content_type = (response.headers.get('Content-Type') or '').lower()
        if not content_type.startswith('text/html'): return False
        try:
            text = response.text.lower()
        except Exception:
            return False
        return strings.AO3_DOWN_MARKER in text and 'id="workskin"' not in text


    @staticmethod
    def is_cloudflare_response(response: requests.Response) -> bool:
        content_type = response.headers.get('Content-Type', '').lower()
        if not content_type.startswith('text/html'):
            return False
        cloudflare_markers = [
            # common generic cloudflare page titles. unlikely, since ao3 uses their own branding, 
            # but worth checking for. shouldn't false positive on works with titles that happen 
            # to match the strings - a legitimate ao3 title will include "| Archive of Our Own"
            '<title>just a moment...</title>',
            '<title>attention required!</title>',
            '<title>access denied</title>',
            # checking for suspicious javascript variables. these *will* false positive if a user
            # includes them in the work, but the chances of that are very very low, I hope. 
            'cf-browser-verification',
            'id="challenge-error-text"',
            'id="cf-wrapper"',
            '_cf_chl_opt',
        ]
        return any(marker in response.text.lower() for marker in cloudflare_markers)


    def setting(self, key: str, fallback, minimum: int = 0):
        """A whole-number setting, or `fallback` when settings.ini has none or cannot say."""

        try:
            value = self.fileops.get_ini_value_integer(key, fallback)
        except Exception:
            return fallback
        if not isinstance(value, int) or isinstance(value, bool): return fallback
        return max(minimum, value)


    def get_delay(self, attempt: int) -> float:
        delay = self.retry_initial_delay * (2 ** attempt)
        if delay > self.retry_max_delay:
            return self.retry_max_delay
        return delay


    def log_error(self, url: str, message: str, error: Exception):
        if not self.debug: return
        log = {'link': url, 'message': message, 'error': str(error), 'level': 'debug'}
        if not isinstance(error, exceptions.Ao3DownloaderException):
            log['stacktrace'] = ''.join(traceback.TracebackException.from_exception(error).format())
        self.fileops.write_log(log)
