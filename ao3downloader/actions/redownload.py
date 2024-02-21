import traceback

from ao3downloader import parse_text, strings, update
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository
from tqdm import tqdm


def action():
    fileops = FileOps()
    with Repository(fileops) as repo:
        
        folder = shared.redownload_folder()
        oldtypes = shared.redownload_oldtypes()
        newtypes = shared.redownload_newtypes()
        images = shared.images()

        shared.ao3_login(repo, fileops)

        fics = shared.get_files_of_type(folder, oldtypes)

        print(strings.REDOWNLOAD_INFO_URLS)

        works = []
        for fic in tqdm(fics):
            try:
                work = update.process_file(fic['path'], fic['filetype'], False)
                if work: 
                    works.append(work)
                    fileops.write_log({'message': strings.MESSAGE_FIC_FILE, 'path': fic['path'], 'link': work['link']})
            except Exception as e:
                fileops.write_log({'message': strings.ERROR_REDOWNLOAD, 'path': fic['path'], 'error': str(e), 'stacktrace': traceback.format_exc()})

        urls = list(set(map(lambda x: x['link'], works)))

        print(strings.REDOWNLOAD_INFO_DONE.format(len(urls)))

        logs = fileops.load_logfile()
        if logs:
            print(strings.INFO_EXCLUDING_WORKS)
            titles = parse_text.get_title_dict(logs)
            unsuccessful = parse_text.get_unsuccessful_downloads(logs)
            maximum = fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
            urls = list(filter(lambda x: 
                not fileops.file_exists(x, titles, newtypes, maximum)
                and x not in unsuccessful,
                urls))

        print(strings.AO3_INFO_DOWNLOADING)

        ao3 = Ao3(repo, fileops, newtypes, None, False, images)

        for url in tqdm(urls):
            ao3.download(url)
