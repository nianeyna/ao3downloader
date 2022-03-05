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
    
    folder = globals.get_folder(strings.REDOWNLOAD_PROMPT_FOLDER)

    oldtypes = []
    while True:
        filetype = ''
        while filetype not in strings.UPDATE_ACCEPTABLE_FILE_TYPES:
            print(strings.REDOWNLOAD_PROMPT_FILE_TYPE)
            filetype = input()
        oldtypes.append(filetype)
        print(strings.REDOWNLOAD_INFO_FILE_TYPE.format(filetype))
        print(strings.AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE)
        if input() == strings.PROMPT_YES:
            oldtypes = list(set(oldtypes))
            break

    newtypes = globals.get_download_types()

    session = requests.sessions.Session()
    globals.ao3_login(session)

    fics = globals.get_files_of_type(folder, oldtypes)
    
    print(strings.UPDATE_INFO_NUM_RETURNED.format(len(fics)))

    print(strings.REDOWNLOAD_INFO_URLS)

    logfile = globals.get_logfile()

    works = []
    for fic in tqdm(fics):
        try:
            work = update.process_file(fic['path'], fic['filetype'], False)
            if work: 
                works.append(work)
                fileio.write_log(logfile, {'message': strings.MESSAGE_FIC_FILE, 'path': fic['path'], 'link': work['link']})
        except Exception as e:
            fileio.write_log(logfile, {'message': strings.ERROR_REDOWNLOAD, 'path': fic['path'], 'error': str(e), 'stacktrace': traceback.format_exc()})

    urls = list(set(map(lambda x: x['link'], works)))

    print(strings.REDOWNLOAD_INFO_DONE.format(len(urls)))

    fileio.make_dir(strings.DOWNLOAD_FOLDER_NAME)

    for url in tqdm(urls):
        ao3.download(url, newtypes, strings.DOWNLOAD_FOLDER_NAME, logfile, session, False)

    session.close()
