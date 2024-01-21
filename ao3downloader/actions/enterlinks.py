from ao3downloader import strings
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository

from tqdm import tqdm

def action():
    fileops = FileOps()
    with Repository(fileops) as repo:

        filetypes = shared.download_types(fileops)
        images = shared.images()

        print(strings.AO3_PROMPT_FILE_INPUT)
        path = input()
        with open(path) as f:
            links = f.readlines()

        shared.ao3_login(repo, fileops)

        visited = shared.visited(fileops, filetypes)

        print(strings.AO3_INFO_DOWNLOADING)

        ao3 = Ao3(repo, fileops, filetypes, 0, True, images)
        for link in tqdm(links):
            ao3.download(link.strip(), visited)
