import itertools
import traceback

from ao3downloader import fileio, parse_text, strings, update
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.repo import Repository
from tqdm import tqdm


def action():
    with Repository() as repo:

        folder = shared.get_update_folder()
        update_filetypes = shared.get_update_types()
        download_filetypes = shared.get_download_types()

        print(strings.AO3_PROMPT_IMAGES)
        images = True if input() == strings.PROMPT_YES else False

        shared.ao3_login(repo)    

        print(strings.UPDATE_INFO_FILES)

        fics = shared.get_files_of_type(folder, update_filetypes)
        
        print(strings.UPDATE_INFO_NUM_RETURNED.format(len(fics)))

        print(strings.UPDATE_INFO_URLS)

        logfile = shared.get_logfile()

        works = []
        for fic in tqdm(fics):
            try:
                work = update.process_file(fic['path'], fic['filetype'])
                if work:
                    works.append(work)
                    fileio.write_log(logfile, {'message': strings.MESSAGE_INCOMPLETE_FIC, 'path': fic['path'], 'link': work['link']})
            except Exception as e:
                fileio.write_log(logfile, {'message': strings.ERROR_INCOMPLETE_FIC, 'path': fic['path'], 'error': str(e), 'stacktrace': traceback.format_exc()})    

        # remove duplicate work links. take lowest number of chapters.
        works_cleaned = []
        works_sorted = sorted(works, key=lambda x: x['link'])
        for link, group in itertools.groupby(works_sorted, lambda x: x['link']):
            chapters = min(group, key=lambda x: x['chapters'])['chapters']
            works_cleaned.append({'link': link, 'chapters': chapters})

        print(strings.UPDATE_INFO_URLS_DONE)

        logs = fileio.load_logfile(logfile)
        if logs:
            unsuccessful = parse_text.get_unsuccessful_downloads(logs)
            if any('/works/' in x for x in unsuccessful):
                print(strings.UPDATE_INFO_FILTER)
                works_cleaned = list(filter(lambda x: x['link'] not in unsuccessful, works_cleaned))

        print(strings.UPDATE_INFO_DOWNLOADING)

        fileio.make_dir(strings.DOWNLOAD_FOLDER_NAME)

        ao3 = Ao3(repo, download_filetypes, strings.DOWNLOAD_FOLDER_NAME, logfile, None, False, images)

        for work in tqdm(works_cleaned):
            ao3.update(work['link'], work['chapters'])
