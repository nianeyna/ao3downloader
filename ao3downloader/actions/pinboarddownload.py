import requests

import ao3downloader.actions.globals as globals
import ao3downloader.ao3 as ao3
import ao3downloader.fileio as fileio
import ao3downloader.pinboard as pinboard
import ao3downloader.strings as strings

from tqdm import tqdm


def action():
    
    print(strings.PINBOARD_PROMPT_INCLUDE_UNREAD)
    exclude_toread = False if input() == strings.PROMPT_YES else True

    bookmarks = pinboard.get_bookmarks(strings.PINBOARD_FILE_NAME, exclude_toread)
    print(strings.PINBOARD_INFO_NUM_RETURNED.format(len(bookmarks)))

    print(strings.AO3_PROMPT_SUBFOLDERS)
    subfolders = True if input() == strings.PROMPT_YES else False
    
    session = requests.sessions.Session()

    globals.ao3_login(session)
    
    filetype = ''
    while filetype not in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES:
        filetype = fileio.setting(
            strings.AO3_PROMPT_DOWNLOAD_TYPE, 
            strings.SETTINGS_FILE_NAME, 
            strings.SETTING_FILETYPE)

    folder = strings.DOWNLOAD_FOLDER_NAME
    logfile = globals.get_logfile(folder)

    print(strings.AO3_INFO_DOWNLOADING)

    for item in tqdm(bookmarks):
        link = item['href']
        ao3.download(link, filetype, folder, logfile, session, subfolders)
    
    session.close()
