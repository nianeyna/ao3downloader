import requests
import traceback

import ao3downloader.actions.shared as shared
import ao3downloader.ao3 as ao3
import ao3downloader.fileio as fileio
import ao3downloader.strings as strings
import ao3downloader.update as update

from tqdm import tqdm

def action():
    
    folder = shared.get_folder(strings.REDOWNLOAD_PROMPT_FOLDER)

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

    newtypes = []
    while True:
        filetype = ''
        while filetype not in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES:
            print(strings.AO3_PROMPT_DOWNLOAD_TYPE)
            filetype = input()
        newtypes.append(filetype)
        print(strings.AO3_INFO_FILE_TYPE.format(filetype))
        print(strings.AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE)
        if input() == strings.PROMPT_YES:
            newtypes = list(set(newtypes))
            break

    print(strings.AO3_PROMPT_IMAGES)
    images = True if input() == strings.PROMPT_YES else False

    session = requests.sessions.Session()
    shared.ao3_login(session)

    fics = shared.get_files_of_type(folder, oldtypes)
    
    print(strings.UPDATE_INFO_NUM_RETURNED.format(len(fics)))

    print(strings.REDOWNLOAD_INFO_URLS)

    logfile = shared.get_logfile()

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

    print(strings.INFO_EXCLUDING_WORKS)
    logs = fileio.load_logfile(logfile)
    titles = shared.get_title_dict(logs)
    unsuccessful = shared.get_unsuccessful_downloads(logs)
    urls = list(filter(lambda x: fileio.file_exists(x, titles, newtypes, strings.DOWNLOAD_FOLDER_NAME), urls))
    urls = list(filter(lambda x: x not in unsuccessful, urls))

    fileio.make_dir(strings.DOWNLOAD_FOLDER_NAME)

    for url in tqdm(urls):
        ao3.download(url, newtypes, strings.DOWNLOAD_FOLDER_NAME, logfile, session, False, None, False, images)

    session.close()
