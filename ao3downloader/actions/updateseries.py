import traceback

import requests
from ao3downloader import ao3, fileio, parse_text, strings, update
from ao3downloader.actions import shared
from tqdm import tqdm


def action():

    folder = shared.get_update_folder()
    update_filetypes = shared.get_update_types()
    download_filetypes = shared.get_download_types()

    print(strings.AO3_PROMPT_SUBFOLDERS)
    subfolders = True if input() == strings.PROMPT_YES else False

    print(strings.AO3_PROMPT_IMAGES)
    images = True if input() == strings.PROMPT_YES else False

    session = requests.sessions.Session()
    shared.ao3_login(session)

    print(strings.UPDATE_INFO_FILES)

    files = shared.get_files_of_type(folder, update_filetypes)
    
    print(strings.UPDATE_INFO_NUM_RETURNED.format(len(files)))

    print(strings.SERIES_INFO_FILES)

    logfile = shared.get_logfile()

    works = []
    for file in tqdm(files):
        try:
            work = update.process_file(file['path'], file['filetype'], True, True)
            if work:
                works.append(work)
                fileio.write_log(logfile, {'message': strings.MESSAGE_SERIES_FILE, 'path': file['path'], 'link': work['link'], 'series': work['series']})
        except Exception as e:
            fileio.write_log(logfile, {'message': strings.ERROR_FIC_IN_SERIES, 'path': file['path'], 'error': str(e), 'stacktrace': traceback.format_exc()})    

    print(strings.SERIES_INFO_URLS)

    series = dict[str, list[str]]()
    for work in works:
        for s in work['series']:
            if s not in series:
                series[s] = []
            link = work['link'].replace('http://', 'https://')
            if link not in series[s]:
                series[s].append(link)

    logs = fileio.load_logfile(logfile)
    if logs:
        unsuccessful = parse_text.get_unsuccessful_downloads(logs)
        if any('/series/' in x for x in unsuccessful):
            print(strings.SERIES_INFO_FILTER)
            series = {k: v for k, v in series.items() if k not in unsuccessful}

    print(strings.SERIES_INFO_NUM.format(len(series)))

    print(strings.SERIES_INFO_DOWNLOADING)

    fileio.make_dir(strings.DOWNLOAD_FOLDER_NAME)

    for key, value in tqdm(series.items()):
        ao3.update_series(key, download_filetypes, strings.DOWNLOAD_FOLDER_NAME, logfile, session, subfolders, value, images)
