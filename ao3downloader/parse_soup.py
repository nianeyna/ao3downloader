import re

from bs4 import BeautifulSoup

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


def get_series_info(soup: BeautifulSoup) -> dict:
    """Get series title and list of work urls."""

    work_urls = get_work_urls(soup)

    # create dictionary for series info
    series_info = {'work_urls': work_urls}

    # add series title to dictionary
    series_info['title'] = soup.select('.series-show h2')[0].get_text().strip()

    return series_info


def get_work_urls(soup: BeautifulSoup) -> list[str]:
    """Get all links to ao3 works on a page"""

    work_urls = []

    # get links to all works on the page
    all_links = soup.find_all('a')
    for link in all_links:
        href = link.get('href')
        if href and parse_text.is_work(href):
            url = strings.AO3_BASE_URL + href
            work_urls.append(url)

    return work_urls


def get_work_and_series_urls(soup: BeautifulSoup) -> list[str]:
    """Get all links to ao3 works or series on a page"""

    urls = []

    # get links to all works on the page
    all_links = soup.find_all('a')
    for link in all_links:
        href = link.get('href')
        if href and (parse_text.is_work(href) or parse_text.is_series(href)):
            url = strings.AO3_BASE_URL + href
            urls.append(url)

    return urls


def get_proceed_link(soup: BeautifulSoup) -> str:
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


def get_title(soup: BeautifulSoup, link: str) -> str:
    """Get work title, author, and id as a string"""

    worknum = parse_text.get_work_number(link)
    title = soup.select('.preface .title')[0].get_text().strip()
    author = soup.select('.preface .byline')[0].get_text().strip()

    return f'{worknum} {title} - {author}'


def get_work_metadata(soup: BeautifulSoup, link: str) -> dict:
    worknum = parse_text.get_work_number(link)
    blurb = soup.find('li', class_=f'work-{worknum}')
    tags = blurb.find('ul', class_='tags')
    metadata = {}
    metadata['title'] = blurb.find('a', href=f'/works/{worknum}').get_text()
    try:
        metadata['author'] = blurb.find('a', rel='author').get_text()
    except:
        metadata['author'] = 'Anonymous'
    metadata['fandoms'] = list(x.get_text() for x in blurb.find('h5', class_='fandoms').find_all('a'))
    metadata['summary'] = blurb.find('blockquote', class_='summary').decode_contents()
    metadata['warnings'] = list(x.find('a').get_text() for x in tags.find_all('li', class_='warnings'))
    metadata['characters'] = list(x.find('a').get_text() for x in tags.find_all('li', class_='characters'))
    metadata['relationships'] = list(x.find('a').get_text() for x in tags.find_all('li', class_='relationships'))
    metadata['tags'] = list(x.find('a').get_text() for x in tags.find_all('li', class_='freeforms'))
    metadata['words'] = blurb.find('dd', class_='words').get_text()
    metadata['rating'] = blurb.find('span', class_='rating').get_text()
    metadata['chapters'] = blurb.find('dd', class_='chapters').get_text()
    metadata['categories'] = blurb.find('span', class_='category').get_text()
    metadata['complete'] = True if blurb.find('span', class_='iswip').get_text() == 'Complete Work' else False
    return metadata


def get_current_chapters(soup: BeautifulSoup) -> str:
    text = (soup.find('dl', class_='stats')
                .find('dd', class_='chapters')
                .get_text().strip())

    index = text.find('/')
    if index == -1: return -1
    
    return parse_text.get_current_chapters(text, index)


def is_locked(soup: BeautifulSoup) -> bool:
    return string_exists(soup, strings.AO3_LOCKED)


def is_deleted(soup: BeautifulSoup) -> bool:
    return string_exists(soup, strings.AO3_DELETED)


def is_explicit(soup: BeautifulSoup) -> bool:
    return string_exists(soup, strings.AO3_EXPLICIT)


def is_failed_login(soup: BeautifulSoup) -> bool:
    return string_exists(soup, strings.AO3_FAILED_LOGIN)


def string_exists(soup: BeautifulSoup, string: str) -> bool:
    pattern = string
    expression = re.compile(pattern)
    match = soup.find_all(text=expression)
    return len(match) > 0
