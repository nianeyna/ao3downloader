from ao3downloader import fileio, parse_text, strings
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.repo import Repository


def action():
    with Repository() as repo:

        filetypes = shared.get_download_types()

        print(strings.AO3_PROMPT_SERIES)
        series = True if input() == strings.PROMPT_YES else False

        logfile = shared.get_logfile()

        link = shared.get_last_page_downloaded(logfile)

        if not link: 
            print(strings.AO3_PROMPT_LINK)
            link = input()

        print(strings.AO3_PROMPT_PAGES)
        pages = input()

        try:
            pages = int(pages)
            if pages <= 0:
                pages = None
        except:
            pages = None

        print(strings.AO3_PROMPT_IMAGES)
        images = True if input() == strings.PROMPT_YES else False

        shared.ao3_login(repo)

        visited = []
        logs = fileio.load_logfile(logfile)
        if logs:
            titles = parse_text.get_title_dict(logs)
            visited = list({x for x in titles if 
                fileio.file_exists(x, titles, filetypes, strings.DOWNLOAD_FOLDER_NAME)})

        print(strings.AO3_INFO_DOWNLOADING)

        fileio.write_log(logfile, {'starting': link})
        fileio.make_dir(strings.DOWNLOAD_FOLDER_NAME)

        ao3 = Ao3(repo, filetypes, strings.DOWNLOAD_FOLDER_NAME, logfile, pages, series, images)
        ao3.download(link, visited)
