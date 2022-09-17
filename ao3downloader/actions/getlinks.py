import datetime
import os

from ao3downloader import fileio, strings
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.repo import Repository


def action():
    with Repository() as repo:

        logfile = shared.get_logfile()

        link = shared.get_last_page_downloaded(logfile)

        if not link: 
            print(strings.AO3_PROMPT_LINK)
            link = input()

        print(strings.AO3_PROMPT_SERIES)
        series = True if input() == strings.PROMPT_YES else False

        print(strings.AO3_PROMPT_PAGES)
        pages = input()

        try:
            pages = int(pages)
            if pages <= 0:
                pages = None
        except:
            pages = None

        shared.ao3_login(repo)

        fileio.write_log(logfile, {'starting': link})
        
        ao3 = Ao3(repo, [], strings.DOWNLOAD_FOLDER_NAME, logfile, pages, series, False)
        links = ao3.get_work_links(link)

        fileio.make_dir(strings.DOWNLOAD_FOLDER_NAME)
        filename = f'links_{datetime.datetime.now().strftime("%m%d%Y%H%M%S")}.txt'

        with open(os.path.join(strings.DOWNLOAD_FOLDER_NAME, filename), 'w') as f:
            for l in links:
                f.write(l + '\n')
