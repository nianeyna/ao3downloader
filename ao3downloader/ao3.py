"""Download works from ao3."""

import os
import traceback

from bs4 import BeautifulSoup

from ao3downloader import exceptions, fileio, parse_soup, parse_text, strings
from ao3downloader.repo import Repository


class Ao3:
    def __init__(self, repo: Repository, filetypes: list[str], folder: str, logfile: str, pages: int, series: bool, images: bool) -> None:
        self.repo = repo
        self.filetypes = filetypes
        self.folder = folder
        self.logfile = logfile
        self.pages = pages
        self.series = series
        self.images = images


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


    def get_work_links(self, link: str) -> list[str]:
        
        links_list = []
        visited_series = []

        try:
            self.get_work_links_recursive(links_list, link, visited_series)
        except Exception as e:
            print(strings.ERROR_LINKS_LIST)
            self.log_error({'message': strings.ERROR_LINKS_LIST}, e)

        return links_list


    def get_work_links_recursive(self, links_list: list[str], link: str, visited_series: list[str]) -> None:

        if parse_text.is_work(link):
            if link not in links_list:
                links_list.append(link)
        elif parse_text.is_series(link):
            if self.series and link not in visited_series:
                visited_series.append(link)
                series_soup = self.repo.get_soup(link)
                series_soup = self.proceed(series_soup)
                work_urls = parse_soup.get_work_urls(series_soup)
                for work_url in work_urls:
                    if work_url not in links_list:
                        links_list.append(work_url)
        elif strings.AO3_BASE_URL in link:
            while True:
                thesoup = self.repo.get_soup(link)
                urls = parse_soup.get_work_and_series_urls(thesoup)
                if len(urls) == 0: break
                for url in urls:
                    self.get_work_links_recursive(links_list, url, visited_series)
                link = parse_text.get_next_page(link)
                pagenum = parse_text.get_page_number(link)
                if self.pages and pagenum == self.pages + 1: break
                print(strings.INFO_FINISHED_PAGE.format(str(pagenum - 1), str(pagenum)))
                fileio.write_log(self.logfile, {'starting': link})
        else:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)


    def download_recursive(self, link: str, log: dict, visited: list[str]) -> None:

        if link in visited: return
        visited.append(link)

        if parse_text.is_series(link):
            if self.series:
                log = {}
                self.download_series(link, log, visited)
        elif parse_text.is_work(link):
            log = {}
            self.download_work(link, log, None)
        elif strings.AO3_BASE_URL in link:
            while True:
                thesoup = self.repo.get_soup(link)
                urls = parse_soup.get_work_and_series_urls(thesoup)
                if len(urls) == 0: break
                for url in urls:
                    self.download_recursive(url, log, visited)
                link = parse_text.get_next_page(link)
                pagenum = parse_text.get_page_number(link)
                if self.pages and pagenum == self.pages + 1: break
                print(strings.INFO_FINISHED_PAGE.format(str(pagenum - 1), str(pagenum)))
                fileio.write_log(self.logfile, {'starting': link})
        else:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)


    def download_series(self, link: str, log: dict, visited: list[str]) -> None:
        """"Download all works in a series"""

        try:
            series_soup = self.repo.get_soup(link)
            series_soup = self.proceed(series_soup)
            series_info = parse_soup.get_series_info(series_soup)
            series_title = series_info['title']
            log['series'] = series_title
            for work_url in series_info['work_urls']:
                if work_url not in visited:
                    self.download_work(work_url, log, None)
        except Exception as e:
            log['link'] = link
            self.log_error(log, e)


    def download_work(self, link: str, log: dict, chapters: str) -> None:
        """Download a single work"""

        try:
            log['link'] = link
            title = self.try_download(link, chapters)
            if title == False: return
            log['title'] = title
        except Exception as e:
            self.log_error(log, e)
        else:
            log['success'] = True
            fileio.write_log(self.logfile, log)


    def try_download(self, work_url: str, chapters: str) -> str:
        """Main download logic"""

        thesoup = self.repo.get_soup(work_url)
        thesoup = self.proceed(thesoup)

        if chapters is not None: # TODO this is a super awkward place for this logic to be and I don't like it.
            currentchapters = parse_soup.get_current_chapters(thesoup)
            if currentchapters <= chapters:
                return False
        
        title = parse_soup.get_title(thesoup)
        filename = parse_text.get_valid_filename(title)

        for filetype in self.filetypes:
            link = parse_soup.get_download_link(thesoup, filetype)
            response = self.repo.get_book(link)
            filetype = parse_text.get_file_type(filetype)
            fileio.save_bytes(self.folder, filename + filetype, response)

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
                    imagefolder = os.path.join(self.folder, strings.IMAGE_FOLDER_NAME)
                    fileio.make_dir(imagefolder)
                    fileio.save_bytes(imagefolder, imagefile, response)
                    counter += 1
                except Exception as e:
                    fileio.write_log(self.logfile, {
                        'message': strings.ERROR_IMAGE, 'link': work_url, 'title': title, 
                        'img': img, 'error': str(e), 'stacktrace': traceback.format_exc()})

        return title


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
        fileio.write_log(self.logfile, log)
