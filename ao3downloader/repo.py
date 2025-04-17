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

    retry_statuses = frozenset([500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530])
    retry_initial_delay = 0.1
    retry_max_delay = 30


    def __init__(self, fileops: FileOps) -> None:
        self.fileops = fileops
        self.session = requests.Session()
        self.debug = fileops.get_ini_value_boolean(strings.INI_DEBUG_LOGGING, False)
        self.extra_wait = fileops.get_ini_value_integer(strings.INI_WAIT_TIME, 0)
        self.max_retries = fileops.get_ini_value_integer(strings.INI_MAX_RETRIES, 0)


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


    def my_request(self, method: str, url: str, data: dict[str, str] = None) -> requests.Response:
        """Get response from a url."""

        try:
            response = self.my_request_inner(method, url, data=data)
            if self.debug:
                self.fileops.write_log(
                    {'link': url, 'message': strings.MESSAGE_SUCCESS.format(method, response.status_code), 
                     'level': 'debug'})
            return response
        except Exception as e:
            if self.debug:
                self.fileops.write_log(
                    {'link': url, 'message': strings.ERROR_HTTP_REQUEST, 'error': str(e),
                     'stacktrace': ''.join(traceback.TracebackException.from_exception(e).format()), 
                     'level': 'debug'})
            raise


    def my_request_inner(self, method: str, url: str, attempt: int = 0, data: dict[str, str] = None) -> requests.Response:

        should_retry = strings.AO3_DOMAIN in url.lower() and (self.max_retries == 0 or attempt < self.max_retries)
        retry_delay = self.get_delay(attempt)
        attempt += 1

        try:
            response = self.session.request(method, url, data, headers=self.headers)
        except Exception as e:
            if should_retry:
                if self.debug:
                    self.fileops.write_log(
                        {'link': url, 'message': strings.MESSAGE_RETRY.format(method, attempt, retry_delay),
                         'error': str(e), 'stacktrace': ''.join(traceback.TracebackException.from_exception(e).format()),
                         'level': 'debug'})
                sleep(retry_delay)
                return self.my_request_inner(method, url, attempt, data)
            else:
                raise

        if response.status_code in self.retry_statuses:
            if should_retry:
                if self.debug:
                    self.fileops.write_log(
                        {'link': url, 'message': strings.MESSAGE_RETRY.format(method, attempt, retry_delay),
                         'error': str(response.status_code), 'level': 'debug'})
                sleep(retry_delay)
                return self.my_request_inner(method, url, attempt, data)
            else:
                raise exceptions.InvalidStatusCodeException(strings.ERROR_INVALID_STATUS_CODE.format(response.status_code))

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
            attempt -= 1 # kind of messy, but we don't want to count this against the retry limit
            return self.my_request_inner(method, url, attempt, data)

        if self.extra_wait > 0: sleep(self.extra_wait)

        return response


    def login(self, username: str, password: str):
        """Login to ao3."""

        soup = self.get_soup(strings.AO3_LOGIN_URL)
        token = parse_soup.get_token(soup)
        payload = parse_text.get_payload(username, password, token)
        response = self.my_request('POST', strings.AO3_LOGIN_URL, payload)
        soup = BeautifulSoup(response.text, 'html.parser')
        if not soup: raise Exception(strings.ERROR_FAILED_LOGIN) # raise normal exception type
        if parse_soup.is_failed_login(soup): # raise exception type that indicates we should clear username and password data
            raise exceptions.LoginException(strings.ERROR_FAILED_LOGIN)


    def get_delay(self, attempt: int) -> float:
        delay = self.retry_initial_delay * (2 ** attempt)
        if delay > self.retry_max_delay:
            return self.retry_max_delay
        return delay
