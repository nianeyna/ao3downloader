import re
import traceback
from typing import Any

from bs4 import BeautifulSoup, ResultSet

from ao3downloader import parse_text, strings
from ao3downloader.exceptions import DownloadException, ProceedException


def get_work_link_html(soup: BeautifulSoup) -> str:
    msg = soup.select('#preface .message a')
    if msg and len(msg) == 2: # there should be exactly two links in here
        return msg[1].get('href') # we want the second one
    return None


def get_stats_html(soup: BeautifulSoup) -> str:
    stats = soup.select('#preface .meta .tags dd')
    for dd in stats:
        if 'Chapters: ' in dd.text:
            return dd.text
    return None


def get_series_html(soup: BeautifulSoup) -> list[str]:
    series = []
    links = soup.select('#preface .meta .tags dd a')
    for link in links:
        href = link.get('href')
        if href and 'archiveofourown.org/series/' in href:
            series.append(href)
    return series


def get_work_link_mobi(soup: BeautifulSoup) -> str:
    # it's ok if there are other work links in the file, because the relevant one will always be the first to appear
    # can't use a more specific selector because the html that comes out of the mobi parser is poorly formatted rip me
    link = soup.find('a', href=lambda x: x and 'archiveofourown.org/works/' in x)
    if link: return link.get('href')
    return None


def get_stats_mobi(soup: BeautifulSoup) -> str:
    stats = soup.find('blockquote', string=lambda x: x and 'Chapters: ' in x)
    if stats: return stats.text
    return None


def get_series_mobi(soup: BeautifulSoup) -> list[str]:
    series = []
    tag = soup.find('p', string=lambda x: x and x == 'Series:')
    if tag:
        block = tag.find_next_sibling('blockquote')
        if block:
            links = block.find_all('a', href=lambda x: x and 'archiveofourown.org/series/' in x)
            for link in links:
                series.append(link.get('href'))
    return series


def get_token(soup: BeautifulSoup) -> str:
    """Get authentication token for logging in to ao3."""

    token = (soup.find('form', class_='new_user')
                 .find('input', attrs={'name': 'authenticity_token'})
                 .get('value'))
    return token


def get_image_links(soup: BeautifulSoup) -> list[str]:
    links = []
    work = soup.find('div', id='workskin')
    if not work: return links
    images = work.find_all('img')
    for img in images:
        href = img.get('src')
        if href:
            links.append(href)
    return links


def get_work_urls(soup: BeautifulSoup) -> list[str]:
    """Get all links to ao3 works on a page"""

    return list(dict.fromkeys(list(
        map(lambda w: get_full_work_url(w.get('href')), 
            filter(lambda a : a.get('href') and parse_text.is_work(a.get('href')), 
                   soup.select('.index.group a'))))))


def get_full_work_url(url: str) -> str:
    """Get full ao3 work url from partial url"""

    work_number = parse_text.get_work_number(url)
    return strings.AO3_BASE_URL + '/works/' + work_number


def get_series_urls(soup: BeautifulSoup, get_all: bool) -> list[str]:
    """Get all links to ao3 series on a page"""

    bookmarks = None if get_all else soup.find_all('li', class_='bookmark')

    return list(dict.fromkeys(list(
        map(lambda w: get_full_series_url(w.get('href')), 
            filter(lambda a : a.get('href') and is_series(a, get_all, bookmarks),
                   soup.select('.index.group a'))))))


def is_series(element: Any, get_all: bool, bookmarks: ResultSet[Any]) -> bool:

    series_number = parse_text.get_series_number(element.get('href'))

    # it's not a series at all, so return false
    if not series_number: return False

    # it is a series and we want all of them, so return true
    if get_all: return True

    # check the bookmarks list to see if this is a series, and return true if it is
    return len(list(filter(lambda x: f'series-{series_number}' in x.get('class'), bookmarks))) > 0


def get_full_series_url(url: str) -> str:
    """Get full ao3 series url from partial url"""

    series_number = parse_text.get_series_number(url)
    return strings.AO3_BASE_URL + '/series/' + series_number


def get_work_and_series_urls(soup: BeautifulSoup, get_all: bool=False) -> list[str]:
    """Get all links to ao3 works or series on a page"""

    work_urls = get_work_urls(soup)
    series_urls = get_series_urls(soup, get_all)
    return work_urls + series_urls


def get_proceed_link(soup: BeautifulSoup) -> str:
    """Get link to proceed through explicit work agreement."""

    try:
        link = (soup.find('div', class_='works-show region')
                    .find('ul', class_='actions')
                    .find('li')
                    .find('a', text=strings.AO3_PROCEED)
                    .get('href'))
    except AttributeError as e:
        raise ProceedException(strings.ERROR_PROCEED_LINK) from e
    return strings.AO3_BASE_URL + link


def get_download_link(soup: BeautifulSoup, download_type: str) -> str:
    """Get download link from ao3 work page."""

    try:
        link = (soup.find('li', class_='download')
                    .find('a', text=download_type)
                    .get('href'))
    except AttributeError as e:
        raise DownloadException(strings.ERROR_DOWNLOAD_LINK) from e
    return strings.AO3_BASE_URL + link


def get_mark_as_read_link(soup: BeautifulSoup) -> str:
    """Get link to mark work as read, if it exists."""

    try:
        link = (soup.find('li', class_='mark')
                    .find('a', text=strings.AO3_MARK_READ)
                    .get('href'))
    except:
        return None
    
    if not link:
        return None

    return strings.AO3_BASE_URL + link


def has_custom_skin(soup: BeautifulSoup) -> bool:
    """Check if a work has custom creator styles"""

    return soup.find('ul', class_='work navigation actions').find('li', class_='style') is not None


def get_title(soup: BeautifulSoup, link: str, pattern: str) -> list[str]:
    """Get (non-truncated) filename for the work"""

    result = []
    metadata = get_work_metadata_from_work(soup, link)
    split_pattern = pattern.split('/')
    
    for part in split_pattern:
        part_result = part
        for key, value in metadata.items():
            part_result = part_result.replace(f'{{{key}}}', value)
        result.append(part_result)

    return result


def get_work_metadata_from_work(soup: BeautifulSoup, link: str) -> dict:
    metadata = {}
    metadata['worknum'] = parse_text.get_work_number(link)
    metadata['title'] = get_text_or_empty(soup, '.preface .title')
    metadata['author'] = get_text_or_empty(soup, '.preface .byline')
    metadata['fandom'] = str.join(', ', list(map(lambda x: x.get_text(), soup.select('dd.fandom a'))))
    metadata['pairing'] = str.join(', ', list(map(lambda x: x.get_text(), soup.select('dd.relationship a'))))
    metadata['rating'] = get_text_or_empty(soup, 'dd.rating')
    metadata['warning'] = str.join(', ', list(map(lambda x: x.get_text(), soup.select('dd.warning a'))))
    metadata['category'] = str.join(', ', list(map(lambda x: x.get_text(), soup.select('dd.category a'))))
    metadata['words'] = get_text_or_empty(soup, 'dd.words').replace(',', '').strip()
    metadata['chapters'] = get_current_chapters(soup)
    metadata['language'] = get_text_or_empty(soup, 'dd.language')
    metadata['published'] = get_text_or_empty(soup, 'dd.published')
    metadata['updated'] = get_text_or_empty(soup, 'dd.status')
    series_list = list(map(lambda x: get_series_from_span(x), soup.select('dd.series span.series span.position')))
    metadata['series_title'] = str.join(', ', list(map(lambda x: x[0], series_list)))
    metadata['series_index'] = str.join(', ', list(map(lambda x: x[1], series_list)))
    return metadata


def get_text_or_empty(soup: BeautifulSoup, selector: str) -> str:
    """Get text from a selector, or return an empty string if it doesn't exist"""

    try:
        return soup.select(selector)[0].get_text().strip()
    except:
        return ''


def get_series_from_span(soup: BeautifulSoup) -> tuple[str, str]:
    """Get series title and index from span element"""

    series_link = soup.find('a')
    series_title = series_link.get_text().strip()
    work_index = re.sub(r'\D', '', soup.decode_contents().replace(str(series_link), '')).strip()
    return series_title, work_index


def get_work_metadata_from_list(soup: BeautifulSoup, link: str) -> dict:
    metadata = {}
    try:
        worknum = parse_text.get_work_number(link)
        blurb = soup.find('li', class_=f'work-{worknum}')
        tags = blurb.find('ul', class_='tags')
        metadata['title'] = blurb.select('h4.heading a')[0].get_text()
        metadata['author'] = str.join(', ', list(x.get_text() for x in blurb.find_all('a', rel='author')))
        if not metadata['author']: metadata['author'] = 'Anonymous'
        try:
            metadata['summary'] = blurb.find('blockquote', class_='summary').decode_contents()
        except:
            metadata['summary'] = '' # some works don't have a summary
        metadata['fandoms'] = list(x.get_text() for x in blurb.find('h5', class_='fandoms').find_all('a'))
        metadata['warnings'] = list(x.find('a').get_text() for x in tags.find_all('li', class_='warnings'))
        metadata['characters'] = list(x.find('a').get_text() for x in tags.find_all('li', class_='characters'))
        metadata['relationships'] = list(x.find('a').get_text() for x in tags.find_all('li', class_='relationships'))
        metadata['tags'] = list(x.find('a').get_text() for x in tags.find_all('li', class_='freeforms'))
        metadata['words'] = blurb.find('dd', class_='words').get_text()
        metadata['rating'] = blurb.find('span', class_='rating').get_text()
        metadata['chapters'] = blurb.find('dd', class_='chapters').get_text()
        metadata['categories'] = blurb.find('span', class_='category').get_text()
        metadata['complete'] = True if blurb.find('span', class_='iswip').get_text() == 'Complete Work' else False
    except Exception as e: # don't crash the entire download if there is an unhandled exception
        metadata['error'] = ''.join(traceback.TracebackException.from_exception(e).format())
    return metadata


def get_current_chapters(soup: BeautifulSoup) -> str:
    text = (soup.find('dl', class_='stats')
                .find('dd', class_='chapters')
                .get_text().strip())

    index = text.find('/')
    if index == -1: return -1
    
    return parse_text.get_current_chapters(text, index)


def is_locked(soup: BeautifulSoup) -> bool:
    return soup.find('div', id='main', class_='sessions-new') is not None


def is_deleted(soup: BeautifulSoup) -> bool:
    return soup.find('div', id='main', class_='error-404') is not None


def is_explicit(soup: BeautifulSoup) -> bool:
    return soup.find('p', class_='caution') is not None


def is_failed_login(soup: BeautifulSoup) -> bool:
    return string_exists(soup, strings.AO3_FAILED_LOGIN)


def string_exists(soup: BeautifulSoup, string: str) -> bool:
    pattern = string
    expression = re.compile(pattern)
    match = soup.find_all(text=expression)
    return len(match) > 0
