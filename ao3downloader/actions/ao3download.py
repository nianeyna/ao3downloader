import requests

import ao3downloader.actions.globals as globals
import ao3downloader.ao3 as ao3
import ao3downloader.fileio as fileio
import ao3downloader.strings as strings


def action():
    
    filetype = ''
    while filetype not in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES:
        filetype = fileio.setting(
            strings.AO3_PROMPT_DOWNLOAD_TYPE, 
            strings.SETTINGS_FILE_NAME, 
            strings.SETTING_FILETYPE)

    print(strings.AO3_PROMPT_SUBFOLDERS)
    subfolders = True if input() == strings.PROMPT_YES else False

    print(strings.AO3_PROMPT_LINK)
    link = input()

    print(strings.AO3_PROMPT_PAGES)
    pages = input()

    try:
        pages = int(pages)
        if pages <= 0:
            pages = None
    except:
        pages = None

    session = requests.sessions.Session()
    
    globals.ao3_login(session)    
    
    folder = strings.DOWNLOAD_FOLDER_NAME
    logfile = globals.get_logfile(folder)

    print(strings.AO3_INFO_DOWNLOADING)
    
    fileio.write_log(logfile, {'starting': link})
    
    ao3.download(link, filetype, folder, logfile, session, subfolders, pages)

    session.close()
