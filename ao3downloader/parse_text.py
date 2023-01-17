import datetime
import re

from ao3downloader import strings


def get_pinboard_url(api_token: str, date: datetime.datetime) -> str:
    if date == None:
        return strings.ALL_POSTS_URL.format(api_token)
    else:
        year = str(date.year)
        month = str(date.month).zfill(2)
        day = str(date.day).zfill(2)
        timestamp = strings.TIMESTAMP_URL.format(year, month, day)
        return strings.POSTS_FROM_DATE_URL.format(api_token, timestamp)


def get_valid_filename(filename: str) -> str:
    valid_name = filename.translate({ord(i):None for i in strings.INVALID_FILENAME_CHARACTERS})
    return valid_name[:50].strip()


def get_file_type(filetype: str) -> str:
    return '.' + filetype.lower()


def get_work_number(link: str) -> str:
    return link[link.find('/works/'):][7:]


def is_work(link: str, internal: bool=True) -> bool:
    return (link.startswith('/') or not internal) and re.compile(strings.AO3_WORK).match(link)


def is_series(link: str, internal: bool=True) -> bool:
    return (link.startswith('/') or not internal) and re.compile(strings.AO3_SERIES).match(link)


def get_next_page(link: str) -> str:
    index = str.find(link, 'page=')
    if index == -1:
        if str.find(link, '?') == -1:
            newlink = link + '?page=2'
        else:
            newlink = link + '&page=2'
    else:
        i = index + 5
        page = get_num_from_link(link, i)
        nextpage = int(page) + 1
        newlink = link.replace('page=' + page, 'page=' + str(nextpage))
    return newlink


def get_page_number(link: str) -> int:
    index = str.find(link, 'page=')
    if index == -1:
        return 1
    else:
        i = index + 5
        page = get_num_from_link(link, i)
        return int(page)


def get_num_from_link(link: str, start: int) -> str:
    end = start + 1
    while end < len(link) and str.isdigit(link[start:end+1]):
        end = end + 1
    return link[start:end]


def get_total_chapters(text: str, index: int) -> str:
    '''read characters after index until encountering a space.'''
    totalchap = ''
    for c in text[index+1:]:
        if c.isspace():
            break
        else:
            totalchap += c
    return totalchap


def get_current_chapters(text: str, index: int) -> str:
    ''' 
    reverse text before index, then read characters from beginning of reversed text 
    until encountering a space, then un-reverse the value you got. 
    we assume here that the text does not include unicode values.
    this should be safe because ao3 doesn't have localization... I think.
    '''
    currentchap = ''
    for c in reversed(text[:index]):
        if c.isspace():
            break
        else:
            currentchap += c
    currentchap = currentchap[::-1]
    return currentchap


def get_payload(username: str, password: str, token: str) -> dict[str, str]:
    """Get payload for ao3 login."""

    payload = {
        'user[login]': username,
        'user[password]': password,
        'user[remember_me]': '1',
        'utf8': '&#x2713;',
        'authenticity_token': token
    }
    return payload


def get_title_dict(logs: list[dict]) -> dict[str, str]:
    dictionary = {}
    titles = filter(lambda x: 'title' in x and 'link' in x, logs)
    for obj in list(titles):
        link = obj['link']
        if link not in dictionary:
            title = obj['title']
            dictionary[link] = title
    return dictionary


def get_unsuccessful_downloads(logs: list[dict]) -> list[str]:
    links = []
    errors = filter(lambda x:'link' in x and 'success' in x and x['success'] == False, logs)
    for error in errors:
        link = error['link']
        if link not in links: 
            links.append(link)
    return links
