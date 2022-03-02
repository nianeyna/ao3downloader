import itertools
import os
import requests
import traceback

import ao3downloader.actions.globals as globals
import ao3downloader.ao3 as ao3
import ao3downloader.fileio as fileio
import ao3downloader.strings as strings
import ao3downloader.update as update

from tqdm import tqdm


def action():
    logfile = strings.LOG_FILE_NAME

    folder = fileio.setting(
        strings.UPDATE_PROMPT_INPUT, 
        strings.SETTINGS_FILE_NAME, 
        strings.SETTING_UPDATE_FOLDER)

    update_filetypes = globals.get_update_types()
    download_filetypes = globals.get_download_types()

    session = requests.sessions.Session()
    globals.ao3_login(session)    

    print(strings.UPDATE_INFO_FILES)

    fics = []
    for subdir, dirs, files in os.walk(folder):
        for file in files:
            filetype = os.path.splitext(file)[1].upper()[1:]
            if filetype in update_filetypes:
                path = os.path.join(subdir, file)
                fics.append({'path': path, 'filetype': filetype})

    print(strings.UPDATE_INFO_NUM_RETURNED.format(len(fics)))

    print(strings.UPDATE_INFO_URLS)

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

    print(strings.UPDATE_INFO_DOWNLOADING)

    fileio.make_dir(strings.DOWNLOAD_FOLDER_NAME)

    for work in tqdm(works_cleaned):
        ao3.update(work['link'], download_filetypes, strings.DOWNLOAD_FOLDER_NAME, logfile, session, work['chapters'])
