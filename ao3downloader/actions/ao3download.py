from ao3downloader import strings
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


def action():
    fileops = FileOps()
    with Repository(fileops) as repo:

        filetypes = shared.download_types(fileops)
        series = shared.series()
        link = shared.link(fileops)
        pages = shared.pages()
        images = shared.images()

        shared.ao3_login(repo, fileops)

        visited = shared.visited(fileops, filetypes)

        print(strings.AO3_INFO_DOWNLOADING)

        ao3 = Ao3(repo, fileops, filetypes, pages, series, images)
        ao3.download(link, visited)
