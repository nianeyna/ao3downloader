import itertools
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

        folder = shared.update_folder(fileops)
        update_filetypes = shared.update_types(fileops)
        download_filetypes = shared.download_types(fileops)
        images = shared.images()

        shared.ao3_login(repo, fileops)    

        fics = shared.get_files_of_type(folder, update_filetypes)

        print(strings.UPDATE_INFO_URLS)

        works = []
        for fic in tqdm(fics):
            try:
                work = update.process_file(fic['path'], fic['filetype'])
                if work:
                    works.append(work)
                    fileops.write_log({'message': strings.MESSAGE_INCOMPLETE_FIC, 'path': fic['path'], 'link': work['link']})
            except Exception as e:
                fileops.write_log({'message': strings.ERROR_INCOMPLETE_FIC, 'path': fic['path'], 'error': str(e), 'stacktrace': traceback.format_exc()})    

        # remove duplicate work links. take lowest number of chapters.
        works_cleaned = []
        works_sorted = sorted(works, key=lambda x: x['link'])
        for link, group in itertools.groupby(works_sorted, lambda x: x['link']):
            chapters = min(group, key=lambda x: x['chapters'])['chapters']
            works_cleaned.append({'link': link, 'chapters': chapters})

        print(strings.UPDATE_INFO_URLS_DONE)

        logs = fileops.load_logfile()
        if logs:
            unsuccessful = parse_text.get_unsuccessful_downloads(logs)
            if any('/works/' in x for x in unsuccessful):
                print(strings.UPDATE_INFO_FILTER)
                works_cleaned = list(filter(lambda x: x['link'] not in unsuccessful, works_cleaned))

        print(strings.UPDATE_INFO_DOWNLOADING)

        ao3 = Ao3(repo, fileops, download_filetypes, None, False, images)

        for work in tqdm(works_cleaned):
            ao3.update(work['link'], work['chapters'])
