"""Web requests go here."""

import datetime
import traceback
import xml.etree.ElementTree as ET
from time import sleep

import requests
from bs4 import BeautifulSoup
from requests import codes
import requests.adapters
from urllib3 import Retry

from ao3downloader import exceptions, parse_soup, parse_text, strings
from ao3downloader.fileio import FileOps


class Repository:

    headers = {'user-agent': 'ao3downloader +nianeyna@gmail.com'}


    def __init__(self, fileops: FileOps) -> None:
        self.fileops = fileops
        self.session = requests.Session()
        self.extra_wait = int(fileops.get_ini_value(strings.INI_WAIT_TIME, '0'))
        retries = Retry(total=None, backoff_factor=0.1, backoff_max=30, allowed_methods=frozenset(['GET', 'POST']))
        adapter = requests.adapters.HTTPAdapter(max_retries=retries)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)


    def __enter__(self):
        return self


    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.session.close()


    def get_xml(self, url: str) -> ET.Element:
        """Get XML object from a url."""

        content = self.my_get(url).content
        xml = ET.XML(content)
        return xml


    def get_soup(self, url: str) -> BeautifulSoup:
        """Get BeautifulSoup object from a url."""

        html = self.my_get(url).text
        soup = BeautifulSoup(html, 'html.parser')
        return soup


    def get_book(self, url: str) -> bytes:
        """Get content from url. Intended for downloading works from ao3."""

        response = self.my_get(url).content
        return response


    def my_get(self, url: str) -> requests.Response:
        """Get response from a url."""

        try:
            response = self.session.get(url, headers=self.headers, timeout=(30, 30))

            if response.status_code == codes['too_many_requests']:
                try:
                    pause_time = int(response.headers['retry-after'])
                except:
                    pause_time = 300 # default to 5 minutes in case there was a problem getting retry-after
                if pause_time <= 0: pause_time = 300 # default to 5 minutes if retry-after is an invalid value
                now = datetime.datetime.now()
                later = now + datetime.timedelta(0, pause_time)
                print(strings.MESSAGE_TOO_MANY_REQUESTS.format(pause_time, now.strftime('%H:%M:%S'), later.strftime('%H:%M:%S')))
                sleep(pause_time)
                print(strings.MESSAGE_RESUMING)
                return self.my_get(url)
        
            if self.extra_wait > 0: sleep(self.extra_wait)

            return response
        except Exception as e:
            self.fileops.write_log({'link': url, 'message': strings.ERROR_HTTP_GET, 'error': str(e), 
                                    'stacktrace': ''.join(traceback.TracebackException.from_exception(e).format())})
            raise


    def login(self, username: str, password: str):
        """Login to ao3."""

        soup = self.get_soup(strings.AO3_LOGIN_URL)
        token = parse_soup.get_token(soup)
        payload = parse_text.get_payload(username, password, token)
        response = self.session.post(strings.AO3_LOGIN_URL, data=payload, headers=self.headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        if not soup or parse_soup.is_failed_login(soup):
            raise exceptions.LoginException(strings.ERROR_FAILED_LOGIN)
