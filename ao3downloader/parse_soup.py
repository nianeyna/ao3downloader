import re
import traceback
from typing import Any

from bs4 import BeautifulSoup, ResultSet, Tag

from ao3downloader import parse_text, strings
from ao3downloader.exceptions import DownloadException, ProceedException, SeriesLinkException


def get_work_link_html(soup: BeautifulSoup) -> str | None:
    msg = soup.select('#preface .message a')
    if msg and len(msg) == 2: # there should be exactly two links in here
        return str(msg[1].get('href')) # we want the second one
    return None


def get_stats_html(soup: BeautifulSoup) -> str | None:
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


def get_work_link_mobi(soup: BeautifulSoup) -> str | None:
    # it's ok if there are other work links in the file, because the relevant one will always be the first to appear
    # can't use a more specific selector because the html that comes out of the mobi parser is poorly formatted rip me
    link = soup.find('a', href=lambda x: bool(x and 'archiveofourown.org/works/' in x))
    if link and isinstance(link, Tag): return str(link.get('href'))
    return None


def get_stats_mobi(soup: BeautifulSoup) -> str | None:
    stats = soup.find('blockquote', string=lambda x: bool(x and 'Chapters: ' in x))
    if stats: return stats.text
    return None


def get_series_mobi(soup: BeautifulSoup) -> list[str]:
    series = []
    tag = soup.find('p', string=lambda x: bool(x and x == 'Series:'))
    if tag:
        block = tag.find_next_sibling('blockquote')
        if block and isinstance(block, Tag):
            links = block.find_all('a', href=lambda x: bool(x and 'archiveofourown.org/series/' in x))
            for link in links:
                if isinstance(link, Tag):
                    href = link.get('href')
                    if href: series.append(str(href))
    return series


def get_login_token(soup: BeautifulSoup) -> str:
    """Get authentication token for logging in to ao3."""

    form = soup.find('form', id='new_user')
    if not form or not isinstance(form, Tag):
        title = soup.title.string if soup.title else 'undefined'
        raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NO_FORM.format(title)))
    
    field = form.find('input', attrs={'name': 'authenticity_token'})
    if not field or not isinstance(field, Tag):
        raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NO_TOKEN))
    
    token = field.get('value')

    if not token:
        raise Exception(strings.ERROR_FAILED_LOGIN.format(strings.FAILED_LOGIN_NO_TOKEN_VALUE))

    return str(token)


def get_mark_read_token(soup: BeautifulSoup) -> str | None:
    """Get token for marking a work as read."""

    actions = soup.find('ul', class_='work navigation actions')
    if not actions or not isinstance(actions, Tag): return None

    mark_read = actions.find('li', class_='mark')
    if not mark_read or not isinstance(mark_read, Tag): return None

    form = mark_read.find('form')
    if not form or not isinstance(form, Tag): return None

    field = form.find('input', attrs={'name': 'authenticity_token'})
    if not field or not isinstance(field, Tag): return None

    token = field.get('value')
    return str(token)


def get_image_links(soup: BeautifulSoup) -> list[str]:
    links = []
    work = soup.find('div', id='workskin')
    if not work or not isinstance(work, Tag): return links
    images = work.find_all('img')
    for img in images:
        if isinstance(img, Tag):
            href = img.get('src')
            if href:
                links.append(href)
    return links


def get_work_urls(soup: BeautifulSoup) -> list[str]:
    """Get all links to ao3 works on a page"""

    work_urls: list[str] = []
    for anchor in soup.select('.index.group a'):
        href = anchor.get('href')
        if not href:
            continue
        href_text = str(href)
        if not parse_text.is_work(href_text):
            continue
        full_url = get_full_work_url(href_text)
        if full_url:
            work_urls.append(full_url)

    return list(dict.fromkeys(work_urls))


def get_full_work_url(url: str) -> str | None:
    """Get full ao3 work url from partial url"""

    work_number = parse_text.get_work_number(url)
    return strings.AO3_BASE_URL + '/works/' + work_number if work_number else None


def get_series_urls(soup: BeautifulSoup, get_all: bool) -> list[str]:
    """Get all links to ao3 series on a page"""

    bookmarks = None if get_all else soup.find_all('li', class_='bookmark')

    series_urls: list[str] = []
    for anchor in soup.select('.index.group a'):
        href = anchor.get('href')
        if not href:
            continue
        href_text = str(href)
        if not is_series(href_text, get_all, bookmarks):
            continue
        full_url = get_full_series_url(href_text)
        if full_url:
            series_urls.append(full_url)

    return list(dict.fromkeys(series_urls))


def is_series(element: str, get_all: bool, bookmarks: ResultSet[Any] | None) -> bool:

    series_number = parse_text.get_series_number(element)

    # it's not a series at all, so return false
    if not series_number: return False

    # it is a series and we want all of them, so return true
    if get_all: return True

    # check the bookmarks list to see if this is a series, and return true if it is
    if not bookmarks:
        return False

    return any(
        f'series-{series_number}' in (bookmark.get('class') or [])
        for bookmark in bookmarks
    )


def get_full_series_url(url: str) -> str | None:
    """Get full ao3 series url from partial url"""

    series_number = parse_text.get_series_number(url)
    return strings.AO3_BASE_URL + '/series/' + series_number if series_number else None


def get_work_and_series_urls(soup: BeautifulSoup, get_all: bool=False) -> list[str]:
    """Get all links to ao3 works or series on a page"""

    work_urls = get_work_urls(soup)
    series_urls = get_series_urls(soup, get_all)
    return work_urls + series_urls


def get_total_pages(soup: BeautifulSoup) -> int | None:
    """Get total page count from pagination element, or None if no pagination exists."""

    pagination = soup.select_one('ol.pagination')
    if not pagination:
        return None
    page_numbers = []
    for li in pagination.find_all('li'):
        digits = re.sub(r'\D', '', li.get_text())
        if not digits:
            continue # ignore non-numeric ('previous' and 'next')
        page_numbers.append(int(digits))
    return max(page_numbers) if page_numbers else None


def get_proceed_link(soup: BeautifulSoup) -> str:
    """Get link to proceed through explicit work agreement."""

    link = None
    for anchor in soup.select('div.works-show.region ul.actions li a'):
        if anchor.get_text(strip=True) == strings.AO3_PROCEED:
            link = anchor.get('href')
            break
    if not link: raise ProceedException(strings.ERROR_PROCEED_LINK)
    return strings.AO3_BASE_URL + str(link)


def get_download_link(soup: BeautifulSoup, download_type: str) -> str:
    """Get download link from ao3 work page."""

    link = None
    for anchor in soup.select('li.download a'):
        if anchor.get_text(strip=True) == download_type:
            link = anchor.get('href')
            break
    if not link: raise DownloadException(strings.ERROR_DOWNLOAD_LINK)
    return strings.AO3_BASE_URL + str(link)


def has_custom_skin(soup: BeautifulSoup) -> bool:
    """Check if a work has custom creator styles"""

    return bool(soup.select('ul.work.navigation.actions li.style'))


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


def get_text_or_empty(soup: BeautifulSoup | Tag, selector: str) -> str:
    """Get text from a selector, or return an empty string if it doesn't exist"""

    try:
        return soup.select(selector)[0].get_text().strip()
    except:
        return ''


def get_series_from_span(tag: Tag) -> tuple[str, str]:
    """Get series title and index from span element"""

    series_link = tag.find('a')
    if not series_link: raise SeriesLinkException(strings.ERROR_SERIES_LINK)
    series_title = series_link.get_text().strip()
    work_index = re.sub(r'\D', '', tag.decode_contents().replace(str(series_link), '')).strip()
    return series_title, work_index


def get_work_metadata_from_list(soup: BeautifulSoup, link: str) -> dict:
    metadata = {}
    try:
        worknum = parse_text.get_work_number(link)
        blurb = soup.find('li', class_=f'work-{worknum}')
        if not isinstance(blurb, Tag):
            metadata['error'] = strings.ERROR_WORK_BLURB
            return metadata
        metadata['title'] = blurb.select('h4.heading a')[0].get_text()
        metadata['author'] = str.join(', ', list(x.get_text() for x in blurb.find_all('a', rel='author')))
        if not metadata['author']: metadata['author'] = 'Anonymous'
        summary = blurb.find('blockquote', class_='summary')
        if isinstance(summary, Tag):
            metadata['summary'] = summary.decode_contents()
        else:
            metadata['summary'] = '' # some works don't have a summary
        metadata['fandoms'] = [x.get_text() for x in blurb.select('h5.fandoms a')]
        metadata['warnings'] = [x.get_text() for x in blurb.select('li.warnings a')]
        metadata['characters'] = [x.get_text() for x in blurb.select('li.characters a')]
        metadata['relationships'] = [x.get_text() for x in blurb.select('li.relationships a')]
        metadata['tags'] = [x.get_text() for x in blurb.select('li.freeforms a')]
        metadata['words'] = get_text_or_empty(blurb, 'dd.words')
        metadata['rating'] = get_text_or_empty(blurb, 'span.rating')
        metadata['chapters'] = get_text_or_empty(blurb, 'dd.chapters')
        metadata['categories'] = get_text_or_empty(blurb, 'span.category')
        metadata['complete'] = get_text_or_empty(blurb, 'span.iswip') == 'Complete Work'
        metadata['series'] = [' '.join(x.get_text().split()) for x in blurb.select('ul[class="series"] li')]
        metadata['updated'] = get_text_or_empty(blurb, 'div.header p.datetime')
        metadata['date_bookmarked'] = get_text_or_empty(blurb, 'div.user p.datetime')
        metadata['bookmarker_tags'] = [x.get_text() for x in blurb.select('div.user ul.meta.tags a.tag')]
        notes = blurb.select_one('div.user blockquote.notes')
        metadata['bookmarker_notes'] = notes.decode_contents() if notes else ''
        viewed = get_text_or_empty(blurb, 'div.user h4.viewed')
        metadata['last_visited'] = parse_text.get_last_visited(viewed)
        metadata['times_visited'] = parse_text.get_times_visited(viewed)
    except Exception as e: # don't crash the entire download if there is an unhandled exception
        metadata['error'] = ''.join(traceback.TracebackException.from_exception(e).format())
    return metadata


def get_current_chapters(soup: BeautifulSoup) -> str:
    chapters = list(soup.select('dl.stats dd.chapters'))
    if not chapters: return '-1'
    text = chapters[0].get_text().strip()
    index = text.find('/')
    if index == -1: return '-1'
    return parse_text.get_current_chapters(text, index)


def is_locked(soup: BeautifulSoup) -> bool:
    return soup.find('div', id='main', class_='sessions-new') is not None


def is_deleted(soup: BeautifulSoup) -> bool:
    return soup.find('div', id='main', class_='error-404') is not None


def is_hidden(soup: BeautifulSoup) -> bool:
    notice = soup.find('p', class_='notice')
    if not notice or not isinstance(notice, Tag):
        return False
    return notice.find('a', href=lambda x: bool(x and x.startswith('/collections/'))) is not None


def is_explicit(soup: BeautifulSoup) -> bool:
    return soup.find('p', class_='caution') is not None


def is_logged_in(soup: BeautifulSoup) -> bool:
    return soup.find('body', class_='logged-in') is not None
