"""Download works from ao3."""

import os
import requests
import traceback

import ao3downloader.exceptions as exceptions
import ao3downloader.fileio as fileio
import ao3downloader.repo as repo
import ao3downloader.soup as soup
import ao3downloader.strings as strings

from bs4 import BeautifulSoup


def download(link: str, filetypes: list[str], folder: str, logfile: str, session: requests.sessions.Session, subfolders: bool, pages: int, series: bool, images: bool) -> None:

    log = {}
    visited = []

    try:
        download_recursive(link, filetypes, folder, log, logfile, session, subfolders, pages, visited, series, images)
    except Exception as e:
        log_error(log, logfile, e)


def update(link: str, filetypes: list[str], folder: str, logfile: str, session: requests.sessions.Session, chapters: str, images: bool) -> None:
    
    log = {}
    
    try:
        download_work(link, filetypes, folder, log, logfile, session, chapters, images)
    except Exception as e:
        log_error(log, logfile, e)


def update_series(link: str, filetypes: list[str], folder: str, logfile: str, session: requests.sessions.Session, subfolders: bool, visited: list[str], images: bool) -> None:

    log = {}

    try:
        download_series(link, filetypes, folder, log, logfile, session, subfolders, images, visited)
    except Exception as e:
        log_error(log, logfile, e)


def get_work_links(link: str, session: requests.sessions.Session, pages: int, series: bool) -> list[str]:
    links_list = []
    visited_series = []
    get_work_links_recursive(links_list, link, session, pages, series, visited_series)
    return links_list


def get_work_links_recursive(links_list: list[str], link: str, session: requests.sessions.Session, pages: int, series: bool, visited_series: list[str]) -> None:

    if '/works/' in link:
        if link not in links_list:
            links_list.append(link)
    elif '/series/' in link:
        if series and link not in visited_series:
            visited_series.append(link)
            series_soup = repo.get_soup(link, session)
            series_soup = proceed(series_soup, session)
            work_urls = soup.get_work_urls(series_soup)
            for work_url in work_urls:
                if work_url not in links_list:
                    links_list.append(work_url)
    elif strings.AO3_BASE_URL in link:
        while True:
            thesoup = repo.get_soup(link, session)
            urls = soup.get_work_and_series_urls(thesoup)
            if len(urls) == 0: break
            for url in urls:
                get_work_links_recursive(links_list, url, session, pages, series, visited_series)
            link = soup.get_next_page(link)
            if pages and soup.get_page_number(link) == pages + 1: break


def download_recursive(link: str, filetypes: list[str], folder: str, log: dict, logfile: str, session: requests.sessions.Session, subfolders: bool, pages: int, visited: list[str], series: bool, images: bool) -> None:

    if link in visited: return
    visited.append(link)

    if '/series/' in link:
        if series:
            log = {}
            download_series(link, filetypes, folder, log, logfile, session, subfolders, images)
    elif '/works/' in link:
        log = {}
        download_work(link, filetypes, folder, log, logfile, session, None, images)
    elif strings.AO3_BASE_URL in link:
        while True:
            thesoup = repo.get_soup(link, session)
            urls = soup.get_work_and_series_urls(thesoup)
            if len(urls) == 0: break
            for url in urls:
                download_recursive(url, filetypes, folder, log, logfile, session, subfolders, pages, visited, series, images)
            link = soup.get_next_page(link)
            if pages and soup.get_page_number(link) == pages + 1: break
            fileio.write_log(logfile, {'starting': link})
    else:
        raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)


def download_series(link: str, filetypes: list[str], folder: str, log: dict, logfile: str, session: requests.sessions.Session, subfolders: bool, images: bool, visited: list[str]=None) -> None:
    """"Download all works in a series into a subfolder"""

    try:
        series_soup = repo.get_soup(link, session)
        series_soup = proceed(series_soup, session)
        series_info = soup.get_series_info(series_soup)
        series_title = series_info['title']
        log['series'] = series_title
        if subfolders:
            valid_title = fileio.get_valid_filename(series_title)
            folder = os.path.join(folder, valid_title)
            fileio.make_dir(folder)
        for work_url in series_info['work_urls']:
            if not visited or work_url not in visited:
                download_work(work_url, filetypes, folder, log, logfile, session, None, images)
    except Exception as e:
        log['link'] = link
        log_error(log, logfile, e)


def download_work(link: str, filetypes: list[str], folder: str, log: dict, logfile: str, session: requests.sessions.Session, chapters: str, images: bool) -> None:
    """Download a single work"""

    try:
        log['link'] = link
        title = try_download(link, filetypes, folder, logfile, session, chapters, images)
        if title == False: return
        log['title'] = title
    except Exception as e:
        log_error(log, logfile, e)
    else:
        log['success'] = True
        fileio.write_log(logfile, log)


def try_download(work_url: str, filetypes: list[str], folder: str, logfile: str, session: requests.sessions.Session, chapters: str, images: bool) -> str:
    """Main download logic"""

    thesoup = repo.get_soup(work_url, session)
    thesoup = proceed(thesoup, session)

    if chapters is not None: # TODO this is a super awkward place for this logic to be and I don't like it.
        currentchapters = soup.get_current_chapters(thesoup)
        if currentchapters <= chapters:
            return False
    
    title = soup.get_title(thesoup)
    filename = fileio.get_valid_filename(title)

    for filetype in filetypes:
        link = soup.get_download_link(thesoup, filetype)
        response = repo.get_book(link, session)
        filetype = get_file_type(filetype)
        fileio.save_bytes(folder, filename + filetype, response)

    if images:
        counter = 0
        imagelinks = soup.get_image_links(thesoup)
        for img in imagelinks:
            if str.startswith(img, '/'): break
            try:
                ext = os.path.splitext(img)[1]
                if '?' in ext: ext = ext[:ext.index('?')]
                response = repo.get_book(img, session)
                imagefile = filename + ' img' + str(counter).zfill(3) + ext
                imagefolder = os.path.join(folder, strings.IMAGE_FOLDER_NAME)
                fileio.make_dir(imagefolder)
                fileio.save_bytes(imagefolder, imagefile, response)
                counter += 1
            except Exception as e:
                fileio.write_log(logfile, {
                    'message': strings.ERROR_IMAGE, 'link': work_url, 'title': title, 
                    'img': img, 'error': str(e), 'stacktrace': traceback.format_exc()})

    return title


def proceed(thesoup: BeautifulSoup, session: requests.sessions.Session) -> BeautifulSoup:
    """Check locked/deleted and proceed through explicit agreement if needed"""

    if soup.is_locked(thesoup):
        raise exceptions.LockedException(strings.ERROR_LOCKED)
    if soup.is_deleted(thesoup):
        raise exceptions.DeletedException(strings.ERROR_DELETED)
    if soup.is_explicit(thesoup):
        proceed_url = soup.get_proceed_link(thesoup)
        thesoup = repo.get_soup(proceed_url, session)
    return thesoup


def get_file_type(filetype: str) -> str:
    return '.' + filetype.lower()


def log_error(log: dict, logfile: str, exception: Exception):
    log['error'] = str(exception)
    log['success'] = False
    if not isinstance(exception, exceptions.Ao3DownloaderException):
        log['stacktrace'] = ''.join(traceback.TracebackException.from_exception(exception).format())
    fileio.write_log(logfile, log)
