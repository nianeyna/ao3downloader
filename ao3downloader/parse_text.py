import datetime
import os

from ao3downloader import strings


def get_pinboard_url(api_token: str, date: datetime.datetime) -> str:
    """
    correctly formats a pinboard url to include an api token and (optionally) a timestamp, then returns it as a string
    """

    if date == None:
        return strings.ALL_POSTS_URL.format(api_token)
    else:
        year = str(date.year)
        month = str(date.month).zfill(2)
        day = str(date.day).zfill(2)
        timestamp = strings.TIMESTAMP_URL.format(year, month, day)
        return strings.POSTS_FROM_DATE_URL.format(api_token, timestamp)


def get_valid_filename(filename: list[str], maximum: int) -> str:
    """
    creates a valid filename path from a list of strings
    """

    valid_path = list(filter(lambda x: x, [get_valid_filepath(segment, maximum) for segment in filename]))
    if len(valid_path) == 0: return ''
    if len(valid_path) == 1: return valid_path[0]
    return os.path.join(*valid_path)


def get_valid_filepath(filename: str, maximum: int) -> str:
    """
    removes any invalid filename characters and leading/trailing whitespace from an input string
    the output will also be trimmed to the provided maximum amount of characters if maximum is greater than 0
    """

    valid_name = filename.translate({ord(i):None for i in strings.INVALID_FILENAME_CHARACTERS})
    if maximum == 0: return valid_name.strip()
    return valid_name[:maximum].strip()


def get_file_type(filetype: str) -> str:
    """
    creates a filename suffix string for an input (uppercase) filetype and returns it
    """

    return '.' + filetype.lower()


def get_work_number(link: str) -> str:
    """
    gets the work number from an ao3 work link
    """

    return get_digits_after('/works/', link)


def get_series_number(link: str) -> str:
    """
    gets the series number from an ao3 series link
    """

    return get_digits_after('/series/', link)


def is_work(link: str) -> bool:
    """
    checks if a link is for an ao3 work
    """

    return get_work_number(link) != None


def is_series(link: str) -> bool:
    """
    checks if a link is for an ao3 series
    """

    return get_series_number(link) != None


def get_digits_after(test: str, url: str) -> str:
    """
    retrieves all consecutive numerical digits in a url after a given test string.
    if the test string doesn't exist or there are no numbers found, the function returns None
    """

    index = str.find(url, test)
    #make sure that the test string is actually in our url
    if index == -1: return None
    digits = get_num_from_link(url, index + len(test))
    #check if we have a number to return
    if not digits or len(digits) == 0: return None
    return digits


def get_next_page(link: str) -> str:
    """
    increment the page number in an ao3 link, and return the updated url
    """

    index = str.find(link, 'page=')

    # if 'page=' isn't already in the link, we need to add it
    # we can assume that this means we're on the first page, and so we always add 'page=2'
    if index == -1:
        # if there's no querystring, add one with 'page=' as the first element
        if str.find(link, '?') == -1:
            newlink = link + '?page=2'
        # if the querystring already exists, add the 'page=' element at the end
        else:
            newlink = link + '&page=2'
    else:
        # we already have a 'page=' element, so we need to increment it by one
        i = index + 5
        page = get_num_from_link(link, i)
        nextpage = int(page) + 1
        newlink = link.replace('page=' + page, 'page=' + str(nextpage))
    return newlink


def get_page_number(link: str) -> int:
    """
    gets the page number from an ao3 link and returns it as an int
    """

    index = str.find(link, 'page=')
    # there's no 'page=' element in the link, so we have to be on the first page
    if index == -1:
        return 1
    else:
        # our index starts after 'page=' so increment by five
        i = index + 5
        page = get_num_from_link(link, i)
        return int(page)


def get_num_from_link(link: str, start: int) -> str:
    """
    used to extract a number in a string that occurs after a specific start point
    """

    end = start
    #iterate through the string until we hit a non-digit character
    while end < len(link) and str.isdigit(link[start:end+1]):
        end = end + 1
    return link[start:end]


def get_total_chapters(text: str, index: int) -> str:
    """
    read characters after index until encountering a space.
    """

    totalchap = ''
    for c in text[index+1:]:
        if c.isspace():
            break
        else:
            totalchap += c
    return totalchap


def get_current_chapters(text: str, index: int) -> str:
    """
    reverse text before index, then read characters from beginning of reversed text
    until encountering a space, then un-reverse the value you got.
    we assume here that the text does not include unicode values.
    this should be safe because ao3 doesn't have localization... I think.
    """

    currentchap = ''
    for c in reversed(text[:index]):
        if c.isspace():
            break
        else:
            currentchap += c
    currentchap = currentchap[::-1]
    return currentchap


def get_payload(username: str, password: str, token: str) -> dict[str, str]:
    """
    constructs a payload for ao3 login.
    """

    payload = {
        'user[login]': username,
        'user[password]': password,
        'user[remember_me]': '1',
        'authenticity_token': token
    }
    return payload


def get_title_dict(logs: list[dict]) -> dict[str, list[str]]:
    """
    creates a dict of form [work link, [work title]] from the logfile
    this dict contains every unique work listed in the logs
    """

    dictionary = {}
    titles = filter(lambda x: 'title' in x and 'link' in x, logs)
    for obj in list(titles):
        link = obj['link']
        # make sure we don't include duplicates in our dict
        if link not in dictionary:
            title = obj['title']
            if not isinstance(title, list): title = [title]
            dictionary[link] = title
    return dictionary


def get_unsuccessful_downloads(logs: list[dict]) -> list[str]:
    """
    checks the logs for any unsuccessful downloads
    if these exist, the function returns a list of links to those works (otherwise it returns an empty list)
    """

    links = []
    errors = filter(lambda x:'link' in x and 'success' in x and x['success'] == False, logs)
    for error in errors:
        link = error['link']
        # check if the work link is already in the list
        if link not in links: 
            links.append(link)
    return links
