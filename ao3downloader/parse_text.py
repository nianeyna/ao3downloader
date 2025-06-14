import datetime
import os

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


def get_valid_filename(filename: list[str], maximum: int) -> str:
    valid_path = list(filter(lambda x: x, [get_valid_filepath(segment, maximum) for segment in filename]))
    if len(valid_path) == 0: return ''
    if len(valid_path) == 1: return valid_path[0]
    return os.path.join(*valid_path)


def get_valid_filepath(filename: str, maximum: int) -> str:
    valid_name = filename.translate({ord(i):None for i in strings.INVALID_FILENAME_CHARACTERS})
    if maximum == 0: return valid_name.strip()
    return valid_name[:maximum].strip()


def get_file_type(filetype: str) -> str:
    return '.' + filetype.lower()


def get_work_number(link: str) -> str:
    return get_digits_after('/works/', link)


def get_series_number(link: str) -> str:
    return get_digits_after('/series/', link)


def is_work(link: str) -> bool:
    return get_work_number(link) != None


def is_series(link: str) -> bool:
    return get_series_number(link) != None


def get_digits_after(test: str, url: str) -> str:
    index = str.find(url, test)
    if index == -1: return None
    digits = get_num_from_link(url, index + len(test))
    if not digits or len(digits) == 0: return None
    return digits


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
    end = start
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
        'authenticity_token': token
    }
    return payload


def get_title_dict(logs: list[dict]) -> dict[str, list[str]]:
    dictionary = {}
    titles = filter(lambda x: 'title' in x and 'link' in x, logs)
    for obj in list(titles):
        link = obj['link']
        if link not in dictionary:
            title = obj['title']
            if not isinstance(title, list): title = [title]
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
