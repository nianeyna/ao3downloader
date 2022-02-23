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

    filetype = ''
    while filetype not in strings.UPDATE_ACCEPTABLE_DOWNLOAD_TYPES:
        filetype = fileio.setting(
            strings.UPDATE_PROMPT_DOWNLOAD_TYPE, 
            strings.SETTINGS_FILE_NAME, 
            strings.SETTING_UPDATE_FILETYPE)

    session = requests.sessions.Session()
    globals.ao3_login(session)    

    print(strings.UPDATE_INFO_FILES.format(filetype))

    fics = []
    for subdir, dirs, files in os.walk(folder):
        for file in files:
            if os.path.splitext(file)[1].upper() == '.' + filetype:
                fics.append(os.path.join(subdir, file))

    print(strings.UPDATE_INFO_NUM_RETURNED.format(len(fics), filetype))

    print(strings.UPDATE_INFO_URLS)

    works = []
    for fic in tqdm(fics):
        try:
            update.process_file(fic, works, filetype)
        except Exception as e:
            fileio.write_log(logfile, {'item': fic, 'error': str(e), 'stacktrace': traceback.format_exc()})    

    print(strings.UPDATE_INFO_URLS_DONE)

    print(strings.UPDATE_INFO_DOWNLOADING)

    for work in tqdm(works):
        ao3.update(work['link'], filetype, strings.DOWNLOAD_FOLDER_NAME, logfile, session, work['chapters'])
