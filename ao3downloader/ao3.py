"""Download works from ao3."""

import os
import traceback

import ao3downloader.fileio as fileio
import ao3downloader.repo as repo
import ao3downloader.soup as soup
import ao3downloader.strings as strings

from ao3downloader.exceptions import LockedException
from ao3downloader.exceptions import DeletedException
from ao3downloader.exceptions import ProceedException
from ao3downloader.exceptions import DownloadException


def download(link, filetype, folder, logfile, session, subfolders, pages = None):

    log = {}
    visited = []

    try:
        download_recursive(link, filetype, folder, log, logfile, session, subfolders, pages, visited)
    except Exception as e:
        log_error(log, logfile, e, strings.ERROR_UNKNOWN)


def update(link, filetype, folder, logfile, session, chapters):
    
    log = {}
    
    try:
        download_work(link, filetype, folder, log, logfile, session, chapters)
    except Exception as e:
        log_error(log, logfile, e, strings.ERROR_UNKNOWN)


def download_recursive(link, filetype, folder, log, logfile, session, subfolders, pages, visited):

    if link in visited: return
    visited.append(link)

    if '/series/' in link:
        log = {}
        download_series(link, filetype, folder, log, logfile, session, subfolders)
    elif '/works/' in link:
        log = {}
        download_work(link, filetype, folder, log, logfile, session)
    elif strings.AO3_BASE_URL in link:
        while True:
            thesoup = repo.get_soup(link, session)
            urls = soup.get_work_and_series_urls(thesoup)
            if len(urls) == 0: break
            for url in urls:
                download_recursive(url, filetype, folder, log, logfile, session, subfolders, pages, visited)
            link = soup.get_next_page(link)
            if pages and soup.get_page_number(link) == pages + 1: break
            fileio.write_log(logfile, {'starting': link})
    else:
        log_error(log, logfile, None, strings.ERROR_INVALID_LINK)


def download_series(link, filetype, folder, log, logfile, session, subfolders):
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
            download_work(work_url, filetype, folder, log, logfile, session)
    except Exception as e:
        log['link'] = link
        log_error(log, logfile, e, strings.ERROR_SERIES)


def download_work(link, filetype, folder, log, logfile, session, chapters = None):
    """Download a single work"""

    try:
        log['link'] = link
        title = try_download(link, filetype, folder, session, chapters)
        if title == False: return
        log['title'] = title
    except LockedException as e:
        log_error(log, logfile, e, strings.ERROR_LOCKED)
    except DeletedException as e:
        log_error(log, logfile, e, strings.ERROR_DELETED)
    except ProceedException as e:
        log_error(log, logfile, e, strings.ERROR_PROCEED_LINK)
    except DownloadException as e:
        log_error(log, logfile, e, strings.ERROR_DOWNLOAD_LINK)
    except AttributeError as e:
        log_error(log, logfile, e, strings.ERROR_ATTRIBUTE)
    except Exception as e:
        log_error(log, logfile, e, strings.ERROR_UNKNOWN)
    else:
        log['success'] = True
        fileio.write_log(logfile, log)


def try_download(work_url, download_type, folder, session, chapters):
    """Main download logic"""

    thesoup = repo.get_soup(work_url, session)
    thesoup = proceed(thesoup, session)
    link = soup.get_download_link(thesoup, download_type)
    title = soup.get_title(thesoup)
    response = repo.get_book(link, session)
    filename = fileio.get_valid_filename(title)
    filetype = get_file_type(download_type)

    if chapters is not None:
        currentchapters = soup.get_current_chapters(thesoup)
        if currentchapters <= chapters:
            return False

    fileio.save_bytes(folder, filename + filetype, response)
    return title


def proceed(thesoup, session):
    """Check locked/deleted and proceed through explicit agreement if needed"""

    if soup.is_locked(thesoup):
        raise LockedException
    if soup.is_deleted(thesoup):
        raise DeletedException
    if soup.is_explicit(thesoup):
        proceed_url = soup.get_proceed_link(thesoup)
        thesoup = repo.get_soup(proceed_url, session)
    return thesoup


def get_file_type(download_type):
    return '.' + download_type.lower()


def log_error(log, logfile, exception, errordesc):
    log['error'] = str(exception)
    log['errordesc'] = errordesc
    log['success'] = False
    log['stacktrace'] = ''.join(traceback.TracebackException.from_exception(exception).format())
    fileio.write_log(logfile, log)
