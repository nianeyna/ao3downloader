import requests

import ao3downloader.actions.shared as shared
import ao3downloader.ao3 as ao3
import ao3downloader.fileio as fileio
import ao3downloader.strings as strings


def action():

    filetypes = shared.get_download_types()

    print(strings.AO3_PROMPT_SERIES)
    series = True if input() == strings.PROMPT_YES else False

    if series:
        print(strings.AO3_PROMPT_SUBFOLDERS)
        subfolders = True if input() == strings.PROMPT_YES else False
    else:
        subfolders = False

    logfile = shared.get_logfile()
    
    link = shared.get_last_page_downloaded(logfile)

    if not link: 
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

    print(strings.AO3_PROMPT_IMAGES)
    images = True if input() == strings.PROMPT_YES else False

    session = requests.sessions.Session()

    shared.ao3_login(session)

    print(strings.AO3_INFO_DOWNLOADING)

    fileio.write_log(logfile, {'starting': link})
    fileio.make_dir(strings.DOWNLOAD_FOLDER_NAME)
    
    ao3.download(link, filetypes, strings.DOWNLOAD_FOLDER_NAME, logfile, session, subfolders, pages, series, images)

    session.close()
