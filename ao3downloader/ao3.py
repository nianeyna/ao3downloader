"""Download works from ao3."""

import os
import traceback

from bs4 import BeautifulSoup

from ao3downloader import exceptions, parse_soup, parse_text, strings
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


class Ao3:
    def __init__(self, repo: Repository, fileops: FileOps, filetypes: list[str], pages: int, series: bool, images: bool, mark: bool=False) -> None:
        self.repo = repo
        self.fileops = fileops
        self.filetypes = filetypes
        self.pages = pages
        self.series = series
        self.images = images
        self.mark = mark
        self.debug = fileops.get_ini_value_boolean(strings.INI_DEBUG_LOGGING, False)


    def download(self, link: str, visited: list[str]=None) -> None:

        log = {}
        if not visited: visited = []

        try:
            self.download_recursive(link, log, visited)
        except Exception as e:
            self.log_error(log, e)


    def update(self, link: str, chapters: str) -> None:
        
        log = {}
        
        try:
            self.download_work(link, log, chapters)
        except Exception as e:
            self.log_error(log, e)


    def update_series(self, link: str, visited: list[str]) -> None:

        log = {}

        try:
            self.download_series(link, log, visited)
        except Exception as e:
            self.log_error(log, e)


    def get_work_links(self, link: str, metadata: bool) -> dict[str, dict]:
        
        links_list = {}
        visited_series = []

        try:
            self.get_work_links_recursive(links_list, link, visited_series, metadata)
        except Exception as e:
            print(strings.ERROR_LINKS_LIST)
            self.log_error({'message': strings.ERROR_LINKS_LIST}, e)
        except KeyboardInterrupt:
            print(strings.INFO_LINKS_LIST_CANCELED)

        return links_list


    def get_work_links_recursive(self, links_list: dict[str, dict], link: str, visited_series: list[str], metadata: bool, soup: BeautifulSoup=None) -> None:

        if parse_text.is_work(link):
            if link not in links_list:
                if metadata:
                    metadata = parse_soup.get_work_metadata_from_list(soup, link)
                    links_list[link] = metadata
                else:
                    links_list[link] = None
        elif parse_text.is_series(link):
            if link not in visited_series:
                visited_series.append(link)
                while True:
                    series_soup = self.repo.get_soup(link)
                    series_soup = self.proceed(series_soup)
                    work_urls = parse_soup.get_work_urls(series_soup)
                    if len(work_urls) == 0: break
                    for work_url in work_urls:
                        self.get_work_links_recursive(links_list, work_url, visited_series, metadata, series_soup)
                    link = parse_text.get_next_page(link)
        elif strings.AO3_BASE_URL in link:
            while True:
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                urls = parse_soup.get_work_and_series_urls(thesoup, self.series)
                if len(urls) == 0:
                    if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_NO_WORKS_ON_PAGE, 'level': 'debug'})
                    break
                for url in urls:
                    self.get_work_links_recursive(links_list, url, visited_series, metadata, thesoup)
                link = parse_text.get_next_page(link)
                pagenum = parse_text.get_page_number(link)
                if self.pages and pagenum == self.pages + 1:
                    if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                    break
                print(strings.INFO_FINISHED_PAGE.format(str(pagenum - 1), str(pagenum)))
        else:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)


    def download_recursive(self, link: str, log: dict, visited: list[str]) -> None:

        if link in visited: return
        visited.append(link)

        if parse_text.is_work(link):
            log = {}
            self.download_work(link, log, None)
        elif parse_text.is_series(link):
            log = {}
            self.download_series(link, log, visited)        
        elif strings.AO3_BASE_URL in link:
            while True:
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                urls = parse_soup.get_work_and_series_urls(thesoup, self.series)
                if len(urls) == 0: 
                    if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_NO_WORKS_ON_PAGE, 'level': 'debug'})
                    break
                for url in urls:
                    self.download_recursive(url, log, visited)
                if not self.mark:
                    link = parse_text.get_next_page(link)
                    pagenum = parse_text.get_page_number(link)
                    if self.pages and pagenum == self.pages + 1:
                        if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                        break
                    print(strings.INFO_FINISHED_PAGE.format(str(pagenum - 1), str(pagenum)))
        else:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)


    def download_series(self, link: str, log: dict, visited: list[str]) -> None:
        """"Download all works in a series"""

        try:
            while True:
                series_soup = self.repo.get_soup(link)
                series_soup = self.proceed(series_soup)
                work_urls = parse_soup.get_work_urls(series_soup)
                if len(work_urls) == 0: break
                if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                for work_url in work_urls:
                    self.download_recursive(work_url, log, visited)
                link = parse_text.get_next_page(link)
        except Exception as e:
            log['link'] = link
            self.log_error(log, e)


    def download_work(self, link: str, log: dict, chapters: str) -> None:
        """Download a single work"""

        try:
            log['link'] = link
            downloaded = self.try_download(link, log, chapters)
            if downloaded == False: return
        except Exception as e:
            self.log_error(log, e)
        else:
            log['success'] = True
            self.fileops.write_log(log)


    def try_download(self, work_url: str, log: dict, chapters: str) -> bool:
        """Main download logic"""

        thesoup = self.repo.get_soup(work_url)
        thesoup = self.proceed(thesoup)

        if chapters is not None: # TODO this is a super awkward place for this logic to be and I don't like it.
            currentchapters = parse_soup.get_current_chapters(thesoup)
            if int(currentchapters) <= int(chapters):
                return False
        
        pattern = self.fileops.get_ini_value(strings.INI_NAME_PATTERN, strings.INI_DEFAULT_NAME_PATTERN)
        maximum = self.fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        title = parse_soup.get_title(thesoup, work_url, pattern)
        filename = parse_text.get_valid_filename(title, maximum)
        log['title'] = title
        log['workskin'] = parse_soup.has_custom_skin(thesoup)

        for filetype in self.filetypes:
            link = parse_soup.get_download_link(thesoup, filetype)
            response = self.repo.get_book(link)
            filetype = parse_text.get_file_type(filetype)
            self.fileops.save_bytes(filename + filetype, response)

        if self.images:
            counter = 0
            imagelinks = parse_soup.get_image_links(thesoup)
            for img in imagelinks:
                if str.startswith(img, '/'): break
                try:
                    ext = os.path.splitext(img)[1]
                    if '?' in ext: ext = ext[:ext.index('?')]
                    response = self.repo.get_book(img)
                    imagefile = filename + ' img' + str(counter).zfill(3) + ext
                    self.fileops.save_bytes(os.path.join(strings.IMAGE_FOLDER_NAME, imagefile), response)
                    counter += 1
                except Exception as e:
                    self.fileops.write_log({
                        'message': strings.ERROR_IMAGE, 'link': work_url, 'title': title, 
                        'img': img, 'error': str(e), 'stacktrace': traceback.format_exc()})

        if self.mark:
            marklink = parse_soup.get_mark_as_read_link(thesoup)
            if marklink: self.repo.my_request('GET', marklink)

        return True


    def proceed(self, thesoup: BeautifulSoup) -> BeautifulSoup:
        """Check locked/deleted and proceed through explicit agreement if needed"""

        if parse_soup.is_locked(thesoup):
            raise exceptions.LockedException(strings.ERROR_LOCKED)
        if parse_soup.is_deleted(thesoup):
            raise exceptions.DeletedException(strings.ERROR_DELETED)
        if parse_soup.is_explicit(thesoup):
            proceed_url = parse_soup.get_proceed_link(thesoup)
            thesoup = self.repo.get_soup(proceed_url)
        return thesoup


    def log_error(self, log: dict, exception: Exception):
        log['error'] = str(exception)
        log['success'] = False
        if not isinstance(exception, exceptions.Ao3DownloaderException):
            log['stacktrace'] = ''.join(traceback.TracebackException.from_exception(exception).format())
        self.fileops.write_log(log)
