import requests

import ao3downloader.actions.globals as globals
import ao3downloader.ao3 as ao3
import ao3downloader.fileio as fileio
import ao3downloader.pinboard as pinboard
import ao3downloader.strings as strings

from datetime import datetime
from tqdm import tqdm


def action():

    filetypes = globals.get_download_types()

    print(strings.AO3_PROMPT_SUBFOLDERS)
    subfolders = True if input() == strings.PROMPT_YES else False

    print(strings.PINBOARD_PROMPT_DATE)
    getdate = True if input() == strings.PROMPT_YES else False
    if getdate:
        date_format = 'mm/dd/yyyy'
        print(strings.PINBOARD_PROMPT_ENTER_DATE.format(date_format))
        inputdate = input()
        date = datetime.strptime(inputdate, '%m/%d/%Y')
    else:
        date = None

    print(strings.PINBOARD_PROMPT_INCLUDE_UNREAD)
    exclude_toread = False if input() == strings.PROMPT_YES else True

    print(strings.AO3_PROMPT_IMAGES)
    images = True if input() == strings.PROMPT_YES else False

    api_token = fileio.setting(
        strings.PINBOARD_PROMPT_API_TOKEN, 
        strings.SETTINGS_FILE_NAME, 
        strings.SETTING_API_TOKEN)

    session = requests.sessions.Session()

    globals.ao3_login(session)
    
    print(strings.PINBOARD_INFO_GETTING_BOOKMARKS)
    bookmarks = pinboard.get_bookmarks(api_token, date, exclude_toread)
    print(strings.PINBOARD_INFO_NUM_RETURNED.format(len(bookmarks)))

    folder = strings.DOWNLOAD_FOLDER_NAME
    logfile = globals.get_logfile()

    print(strings.AO3_INFO_DOWNLOADING)

    fileio.make_dir(folder)

    for item in tqdm(bookmarks):
        link = item['href']
        ao3.download(link, filetypes, folder, logfile, session, subfolders, None, True, images)
    
    session.close()
