import datetime
import os

from ao3downloader import strings
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


def action():
    with Repository() as repo:
        fileops = FileOps()

        link = shared.link(fileops)
        series = shared.series()
        pages = shared.pages()

        shared.ao3_login(repo, fileops)

        ao3 = Ao3(repo, fileops, None, pages, series, False)
        links = ao3.get_work_links(link)

        filename = f'links_{datetime.datetime.now().strftime("%m%d%Y%H%M%S")}.txt'

        with open(os.path.join(strings.DOWNLOAD_FOLDER_NAME, filename), 'w') as f:
            for l in links:
                f.write(l + '\n')
