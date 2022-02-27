import requests

import ao3downloader.actions.globals as globals
import ao3downloader.ao3 as ao3
import ao3downloader.pinboard as pinboard
import ao3downloader.strings as strings

from tqdm import tqdm


def action():
    
    print(strings.PINBOARD_PROMPT_INCLUDE_UNREAD)
    exclude_toread = False if input() == strings.PROMPT_YES else True

    filetypes = globals.get_download_types()

    print(strings.AO3_PROMPT_SUBFOLDERS)
    subfolders = True if input() == strings.PROMPT_YES else False    

    bookmarks = pinboard.get_bookmarks(strings.PINBOARD_FILE_NAME, exclude_toread)
    print(strings.PINBOARD_INFO_NUM_RETURNED.format(len(bookmarks)))

    session = requests.sessions.Session()

    globals.ao3_login(session)
    
    folder = strings.DOWNLOAD_FOLDER_NAME
    logfile = globals.get_logfile(folder)

    print(strings.AO3_INFO_DOWNLOADING)

    for item in tqdm(bookmarks):
        link = item['href']
        ao3.download(link, filetypes, folder, logfile, session, subfolders)
    
    session.close()
