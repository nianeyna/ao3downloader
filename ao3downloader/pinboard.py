"""Logic to get bookmarks from pinboard."""

import xml.etree.ElementTree as ET

from ao3downloader.repo import my_get
from datetime import datetime


POSTS_FROM_DATE_URL = 'https://api.pinboard.in/v1/posts/all?auth_token={}&fromdt={}'
ALL_POSTS_URL = 'https://api.pinboard.in/v1/posts/all?auth_token={}'
TIMESTAMP_URL = '{}-{}-{}T00:00:00Z'


def get_bookmarks(api_token: str, date: datetime, exclude_toread: bool) -> list[dict[str, str]]:
    url = get_pinboard_url(api_token, date)
    content = my_get(url, None).content
    bookmark_xml = ET.XML(content)
    return get_bookmark_list(bookmark_xml, exclude_toread)


def get_pinboard_url(api_token: str, date: datetime) -> str:
    if date == None:
        return ALL_POSTS_URL.format(api_token)
    else:
        year = str(date.year)
        month = str(date.month).zfill(2)
        day = str(date.day).zfill(2)
        timestamp = TIMESTAMP_URL.format(year, month, day)
        return POSTS_FROM_DATE_URL.format(api_token, timestamp)


def get_bookmark_list(bookmark_xml: ET.Element, exclude_toread: bool) -> list[dict[str, str]]:
    bookmark_list = []
    for child in bookmark_xml:
        attributes = child.attrib
        # only include valid ao3 links
        if is_work_or_series(attributes):
            # if exclude_toread is true, only include read bookmarks
            if exclude_toread:
                if have_read(attributes):
                    bookmark_list.append(attributes)          
            # otherwise include all valid bookmarks
            else:
                bookmark_list.append(attributes)
    return bookmark_list


def have_read(bookmark_attributes):
    return not 'toread' in bookmark_attributes


def is_work_or_series(bookmark_attributes):
    return is_work(bookmark_attributes) or is_series(bookmark_attributes)


def is_work(bookmark_attributes):
    return 'archiveofourown.org/works/' in bookmark_attributes['href']


def is_series(bookmark_attributes):
    return 'archiveofourown.org/series/' in bookmark_attributes['href']
