"""Web requests go here."""

import datetime
import xml.etree.ElementTree as ET
from time import sleep

import requests
from bs4 import BeautifulSoup
from requests import codes

from ao3downloader import exceptions, parse_soup, parse_text, strings


class Repository:

    # for reasons I don't fully understand, specifying the user agent makes requests faster
    headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit'
            '/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36 +nianeyna@gmail.com'}


    def __init__(self) -> None:
        self.session = requests.Session()


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
    
        return response


    def login(self, username: str, password: str):
        """Login to ao3."""

        soup = self.get_soup(strings.AO3_LOGIN_URL)
        token = parse_soup.get_token(soup)
        payload = parse_text.get_payload(username, password, token)
        response = self.session.post(strings.AO3_LOGIN_URL, data=payload)
        soup = BeautifulSoup(response.text, 'html.parser')
        if parse_soup.is_failed_login(soup):
            raise exceptions.LoginException(strings.ERROR_FAILED_LOGIN)
