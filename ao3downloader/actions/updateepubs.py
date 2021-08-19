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
    logfile = globals.get_logfile(strings.DOWNLOAD_FOLDER_NAME)

    folder = fileio.setting(
        strings.UPDATE_PROMPT_INPUT, 
        strings.SETTINGS_FILE_NAME, 
        strings.SETTING_UPDATE_FOLDER)

    session = requests.sessions.Session()
    globals.ao3_login(session)    

    print(strings.UPDATE_INFO_FILES)

    epubs = []
    for subdir, dirs, files in os.walk(folder):
        for file in files:
            if os.path.splitext(file)[1].lower() == '.epub':
                epubs.append(os.path.join(subdir, file))

    print(strings.UPDATE_INFO_NUM_RETURNED.format(len(epubs)))

    print(strings.UPDATE_INFO_URLS)

    works = []
    for epub in tqdm(epubs):
        try:
            update.process_epub(epub, works)
        except Exception as e:
            fileio.write_log(logfile, {'item': epub, 'error': str(e), 'stacktrace': traceback.format_exc()})    

    print(strings.UPDATE_INFO_URLS_DONE)

    print(strings.UPDATE_INFO_DOWNLOADING)

    for work in tqdm(works):
        ao3.update(work['link'], 'EPUB', strings.DOWNLOAD_FOLDER_NAME, logfile, session, work['chapters'])
