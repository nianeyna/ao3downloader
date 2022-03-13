"""Logic for navigating BeautifulSoup output"""

import re

import ao3downloader.strings as strings

from ao3downloader.exceptions import DownloadException
from ao3downloader.exceptions import ProceedException


def get_token(soup):
    """Get authentication token for logging in to ao3."""

    token = (soup.find('form', class_='new_user')
                 .find('input', attrs={'name': 'authenticity_token'})
                 .get('value'))
    return token


def get_image_links(soup):
    links = []
    work = soup.find('div', id='workskin')
    if not work: return links
    images = work.find_all('img')
    for img in images:
        href = img.get('src')
        if href:
            links.append(href)
    return links


def get_series_info(soup):
    """Get series title and list of work urls."""

    work_urls = get_work_urls(soup)

    # create dictionary for series info
    series_info = {'work_urls': work_urls}

    # add series title to dictionary
    series_info['title'] = get_title(soup)

    return series_info


def get_work_urls(soup):
    """Get all links to ao3 works on a page"""

    # work urls can be identified by the prefix /works/ followed by only digits
    pattern = r'\/works\/\d+$'
    expression = re.compile(pattern)

    work_urls = []

    # get links to all works on the page
    all_links = soup.find_all('a')
    for link in all_links:
        href = link.get('href')
        if href and expression.match(href):
            url = strings.AO3_BASE_URL + href
            work_urls.append(url)

    return work_urls


def get_work_and_series_urls(soup):
    """Get all links to ao3 works or series on a page"""

    # work urls can be identified by the prefix /works/ followed by only digits
    workpattern = r'\/works\/\d+$'
    workexpression = re.compile(workpattern)

    # series urls can be identified in the same manner
    seriespattern = r'\/series\/\d+$'
    seriesexpression = re.compile(seriespattern)

    urls = []

    # get links to all works on the page
    all_links = soup.find_all('a')
    for link in all_links:
        href = link.get('href')
        if href and (workexpression.match(href) or seriesexpression.match(href)):
            url = strings.AO3_BASE_URL + href
            urls.append(url)

    return urls


def get_proceed_link(soup):
    """Get link to proceed through explict work agreement."""

    try:
        link = (soup.find('div', class_='works-show region')
                    .find('ul', class_='actions')
                    .find('li')
                    .find('a', text=strings.AO3_PROCEED)
                    .get('href'))
    except AttributeError as e:
        raise ProceedException(strings.ERROR_PROCEED_LINK) from e
    return strings.AO3_BASE_URL + link


def get_download_link(soup, download_type):
    """Get download link from ao3 work page."""

    try:
        link = (soup.find('li', class_='download')
                    .find('a', text=download_type)
                    .get('href'))
    except AttributeError as e:
        raise DownloadException(strings.ERROR_DOWNLOAD_LINK) from e
    return strings.AO3_BASE_URL + link


def get_title(soup):
    """Get title of ao3 work, stripping out extraneous information."""

    return (soup.title.get_text().strip()
            .replace(strings.AO3_TITLE, '')
            .replace(strings.AO3_CHAPTER_TITLE, ''))


def get_current_chapters(soup):
    text = (soup.find('dl', class_='stats')
                .find('dd', class_='chapters')
                .get_text().strip())

    index = text.find('/')
    if index == -1: return -1
    
    currentchap = ''
    for c in reversed(text[:index]):
        if c.isspace():
            break
        else:
            currentchap += c
    currentchap = currentchap[::-1]
    return currentchap


def is_locked(soup):
    return string_exists(soup, strings.AO3_LOCKED)


def is_deleted(soup):
    return string_exists(soup, strings.AO3_DELETED)


def is_explicit(soup):
    return string_exists(soup, strings.AO3_EXPLICIT)


def is_failed_login(soup):
    return string_exists(soup, strings.AO3_FAILED_LOGIN)


def string_exists(soup, string):
    pattern = string
    expression = re.compile(pattern)
    match = soup.find_all(text=expression)
    return len(match) > 0


def get_next_page(link):
    index = str.find(link, 'page=')
    if index == -1:
        if str.find(link, '?') == -1:
            newlink = link + '?page=2'
        else:
            newlink = link + '&page=2'
        print('finished downloading page 1. getting page 2')
    else:
        i = index + 5
        page = get_num_from_link(link, i)
        nextpage = int(page) + 1
        newlink = link.replace('page=' + page, 'page=' + str(nextpage))
        print('finished downloading page ' + page + '. getting page ' + str(nextpage))
    return newlink


def get_page_number(link):
    index = str.find(link, 'page=')
    if index == -1:
        return 1
    else:
        i = index + 5
        page = get_num_from_link(link, i)
        return int(page)


def get_num_from_link(link, start):
    end = start + 1
    while end < len(link) and str.isdigit(link[start:end+1]):
        end = end + 1
    return link[start:end]
