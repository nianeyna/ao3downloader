"""Web requests go here."""

import datetime
import xml.etree.ElementTree as ET
from time import sleep

from bs4 import BeautifulSoup
from requests import codes, get

from ao3downloader import parse_soup, parse_text, strings
from ao3downloader.exceptions import LoginException


# for reasons I don't fully understand, specifying the user agent makes requests faster
headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit'
           '/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36 +nianeyna@gmail.com'}


def get_xml(url, session):
    """Get XML object from a url."""

    content = my_get(url, session).content
    xml = ET.XML(content)
    return xml


def get_soup(url, session):
    """Get BeautifulSoup object from a url."""

    html = my_get(url, session).text
    soup = BeautifulSoup(html, 'html.parser')
    return soup


def get_book(url, session):
    """Get content from url. Intended for downloading works from ao3."""

    response = my_get(url, session).content
    return response


def my_get(url, session):
    """Get response from a url."""

    if session == None:
        response = get(url, headers=headers)
    else:
        response = session.get(url, headers=headers)

    if response.status_code == codes['too_many_requests']:
        try:
            pause_time = int(response.headers['retry-after'])
        except:
            pause_time = 300 # default to 5 minutes in case there was a problem getting retry-after
        now = datetime.datetime.now()
        later = now + datetime.timedelta(0, pause_time)
        print(strings.MESSAGE_TOO_MANY_REQUESTS.format(pause_time, now.strftime('%H:%M:%S'), later.strftime('%H:%M:%S')))
        sleep(pause_time)
        print(strings.MESSAGE_RESUMING)
        return my_get(url, session)
 
    return response


def login(username, password, session):
    """Login to ao3."""

    soup = get_soup(strings.AO3_LOGIN_URL, session)
    token = parse_soup.get_token(soup)
    payload = parse_text.get_payload(username, password, token)
    response = session.post(strings.AO3_LOGIN_URL, data=payload)
    soup = BeautifulSoup(response.text, 'html.parser')
    if parse_soup.is_failed_login(soup):
        raise LoginException(strings.ERROR_FAILED_LOGIN)
