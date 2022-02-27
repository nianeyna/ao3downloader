import datetime
import json
import traceback
import requests

import ao3downloader.actions.globals as globals
import ao3downloader.ao3 as ao3
import ao3downloader.fileio as fileio
import ao3downloader.strings as strings


def action():

    folder = strings.DOWNLOAD_FOLDER_NAME
    logfile = globals.get_logfile(folder)

    filetypes = globals.get_download_types()

    print(strings.AO3_PROMPT_SUBFOLDERS)
    subfolders = True if input() == strings.PROMPT_YES else False

    latest = None
    try:
        with open(logfile, 'r', encoding='utf-8') as f:
            objects = map(lambda x: json.loads(x), f.readlines())
            starts = filter(lambda x: 'starting' in x, objects)
            bydate = sorted(starts, key=lambda x: datetime.datetime.strptime(x['timestamp'], '%m/%d/%Y, %H:%M:%S'), reverse=True)
            if bydate: latest = bydate[0]
    except FileNotFoundError:
        pass
    except Exception as e:
        fileio.write_log(logfile, {'error': str(e), 'errordesc': strings.ERROR_LOG_FILE, 'stacktrace': traceback.format_exc()})

    link = None
    if latest:
        print(strings.AO3_PROMPT_LAST_PAGE)
        if input() == strings.PROMPT_YES:
            link = latest['starting']

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

    session = requests.sessions.Session()

    globals.ao3_login(session)

    print(strings.AO3_INFO_DOWNLOADING)

    fileio.write_log(logfile, {'starting': link})

    ao3.download(link, filetypes, folder, logfile, session, subfolders, pages)

    session.close()
