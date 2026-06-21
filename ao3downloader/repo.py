"""Web requests go here."""

import datetime
import traceback
import xml.etree.ElementTree as ET
from time import sleep

import requests
from bs4 import BeautifulSoup
from requests import codes

from ao3downloader import exceptions, parse_soup, parse_text, strings
from ao3downloader.fileio import FileOps


class Repository:

    headers = {'user-agent': 'ao3downloader +nianeyna@gmail.com'}
    timeout = 60

    retry_statuses = frozenset([500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530])
    retry_initial_delay = 0.1
    retry_max_delay = 30


    def __init__(self, fileops: FileOps) -> None:
        self.fileops = fileops
        self.session = requests.Session()
        self.debug = fileops.get_ini_value_boolean(strings.INI_DEBUG_LOGGING, False)
        self.extra_wait = fileops.get_ini_value_integer(strings.INI_WAIT_TIME, 0)
        self.max_retries = fileops.get_ini_value_integer(strings.INI_MAX_RETRIES, 0)
        self.max_timeouts = fileops.get_ini_value_integer(strings.INI_MAX_TIMEOUTS, 3)


    def __enter__(self):
        return self


    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.session.close()


    def get_xml(self, url: str) -> ET.Element:
        """Get XML object from a url."""

        content = self.my_request('GET', url).content
        xml = ET.XML(content)
        return xml


    def get_soup(self, url: str) -> BeautifulSoup:
        """Get BeautifulSoup object from a url."""

        html = self.my_request('GET', url).text
        soup = BeautifulSoup(html, 'html.parser')
        return soup


    def get_book(self, url: str) -> bytes:
        """Get content from url. Intended for downloading works from ao3."""

        response = self.my_request('GET', url).content
        return response


    def my_request(self, method: str, url: str, data: dict[str, str] | None = None) -> requests.Response:
        """Get response from a url."""

        # normalize http -> https for ao3 links. older downloaded works may contain http
        # links in their embedded metadata, and the resulting redirect trips cloudflare.
        if strings.AO3_DOMAIN in url.lower() and url.lower().startswith('http://'):
            url = 'https://' + url[len('http://'):]

        attempt = 0
        timeouts = 0

        while True:
            should_retry = strings.AO3_DOMAIN in url.lower() and (self.max_retries == 0 or attempt < self.max_retries)
            retry_delay = self.get_delay(attempt)

            try:
                try:
                    response = self.session.request(method, url, data, headers=self.headers, timeout=self.timeout)
                except requests.exceptions.Timeout as e: # raw timeout exceptions are way too verbose
                    raise exceptions.TimeoutException(strings.ERROR_TIMEOUT.format(self.timeout)) from e
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
                    sleep(retry_delay)
                    continue
                else:
                    self.log_error(url, strings.ERROR_HTTP_REQUEST, e)
                    raise

            timeouts = 0

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
                now = datetime.datetime.now()
                later = now + datetime.timedelta(0, pause_time)
                print(strings.MESSAGE_TOO_MANY_REQUESTS.format(pause_time, now.strftime('%H:%M:%S'), later.strftime('%H:%M:%S')))
                sleep(pause_time)
                print(strings.MESSAGE_RESUMING)
                continue

            # this check follows the retry-after check because a cloudflare response that is also 
            # a 429 can happen, and should be handled with pause logic rather than retry logic
            if self.is_cloudflare_response(response):
                if self.retry_or_raise(should_retry, attempt, method, url, retry_delay,
                        strings.ERROR_CLOUDFLARE,
                        exceptions.CloudflareException(strings.ERROR_CLOUDFLARE)):
                    attempt += 1
                    continue

            if self.extra_wait > 0: sleep(self.extra_wait)

            if self.debug:
                self.fileops.write_log(
                    {'link': url, 'message': strings.MESSAGE_SUCCESS.format(method, response.status_code),
                     'level': 'debug'})

            return response


    def login(self, username: str, password: str):
        """Login to ao3."""

        soup = self.get_soup(strings.AO3_LOGIN_URL)
        if not soup: raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NOT_FOUND))
        token = parse_soup.get_login_token(soup)
        payload = parse_text.get_payload(username, password, token)
        response = self.my_request('POST', strings.AO3_LOGIN_URL, payload)
        soup = BeautifulSoup(response.text, 'html.parser')
        if not soup: raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NO_RESPONSE))
        if not parse_soup.is_logged_in(soup): # raise exception type that indicates we should clear username and password data
            raise exceptions.LoginException(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_INVALID_CREDENTIALS))
        

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
        Returns True if the caller should continue the retry loop."""
        if should_retry:
            if self.debug:
                self.fileops.write_log(
                    {'link': url, 'message': strings.MESSAGE_RETRY.format(method, attempt + 1, retry_delay),
                     'error': error, 'level': 'debug'})
            sleep(retry_delay)
            return True
        raise exc


    @staticmethod
    def is_cloudflare_response(response: requests.Response) -> bool:
        server = response.headers.get('Server', '').lower()
        if 'cloudflare' not in server:
            return False
        content_type = response.headers.get('Content-Type', '').lower()
        if content_type.startswith('text/html'):
            cloudflare_markers = [
                # common generic cloudflare page titles. unlikely, since ao3 uses their own branding, 
                # but worth checking for. shouldn't false positive on works with titles that happen 
                # to match the strings - a legitimate ao3 title will include "| Archive of Our Own"
                '<title>just a moment...</title>',
                '<title>attention required!</title>',
                '<title>access denied</title>',
                # checking for suspicious javascript variables. these *will* false positive if a user
                # includes them in the title, but the chances of that are very very low, I hope. 
                'cf-browser-verification',
                'id="cf-wrapper"',
                '_cf_chl_opt',
            ]
            return any(marker in response.text.lower() for marker in cloudflare_markers)
        return False


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
