"""Web requests go here."""

import datetime

import ao3downloader.strings as strings

from bs4 import BeautifulSoup
from time import sleep
from requests import codes
from requests import get

from ao3downloader.soup import get_token
from ao3downloader.soup import is_failed_login

from ao3downloader.exceptions import LoginException

# for reasons I don't fully understand, specifying the user agent makes requests faster
headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit'
           '/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36 +nianeyna@gmail.com'}

# login form for ao3
ao3_login_url = 'https://archiveofourown.org/users/login'

# sleep time between requests so we don't make ao3 sad
sleep_time = 1

# extra time between requests in case ao3 gets sad anyway
pause_time = 300


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
        print(strings.MESSAGE_TOO_MANY_REQUESTS.format(datetime.datetime.now().strftime('%H:%M:%S')))
        sleep(pause_time)
        print(strings.MESSAGE_RESUMING)
        return my_get(url, session)

    if(strings.AO3_BASE_URL in url):
        sleep(sleep_time)
        
    return response


def login(username, password, session):
    """Login to ao3."""

    soup = get_soup(ao3_login_url, session)
    token = get_token(soup)
    payload = get_payload(username, password, token)
    response = session.post(ao3_login_url, data=payload)
    soup = BeautifulSoup(response.text, 'html.parser')
    if is_failed_login(soup):
        raise LoginException(strings.ERROR_FAILED_LOGIN)


def get_payload(username, password, token):
    """Get payload for ao3 login."""

    payload = {
        'user[login]': username,
        'user[password]': password,
        'user[remember_me]': '1',
        'utf8': '&#x2713;',
        'authenticity_token': token
    }
    return payload
