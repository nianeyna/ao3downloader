import datetime
import json
import os
import traceback

import requests
from ao3downloader import exceptions, fileio, repo, strings


def get_logfile() -> str:
    if not os.path.exists(strings.LOG_FOLDER_NAME):
        os.mkdir(strings.LOG_FOLDER_NAME)
    return os.path.join(strings.LOG_FOLDER_NAME, strings.LOG_FILE_NAME)


def get_folder(prompt: str) -> str:
    while True:
        print(prompt)
        folder = input()
        if os.path.exists(folder): 
            break
        else:
            print(strings.INFO_NO_FOLDER)
    return folder


def ao3_login(session: requests.sessions.Session) -> None:

    print(strings.AO3_PROMPT_LOGIN)
    login = False if input() == strings.PROMPT_NO else True

    if login:
        username = fileio.setting(
            strings.AO3_PROMPT_USERNAME, 
            strings.SETTINGS_FILE_NAME, 
            strings.SETTING_USERNAME)
        password = fileio.setting(
            strings.AO3_PROMPT_PASSWORD, 
            strings.SETTINGS_FILE_NAME, 
            strings.SETTING_PASSWORD)

        print(strings.AO3_INFO_LOGIN)
        try:
            repo.login(username, password, session)
        except exceptions.LoginException:
            fileio.save_setting(strings.SETTINGS_FILE_NAME, strings.SETTING_USERNAME, None)
            fileio.save_setting(strings.SETTINGS_FILE_NAME, strings.SETTING_PASSWORD, None)
            raise


def get_download_types() -> list[str]:
    filetypes = fileio.get_setting(strings.SETTINGS_FILE_NAME, strings.SETTING_FILETYPES)
    if isinstance(filetypes, list):
        print(strings.AO3_PROMPT_USE_SAVED_DOWNLOAD_TYPES)
        if input() == strings.PROMPT_YES: return filetypes
    filetypes = []
    while(True):
        filetype = ''
        while filetype not in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES:
            print(strings.AO3_PROMPT_DOWNLOAD_TYPE)
            filetype = input()
        filetypes.append(filetype)
        print(strings.AO3_INFO_FILE_TYPE.format(filetype))
        print(strings.AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE)
        if input() == strings.PROMPT_YES:
            filetypes = list(set(filetypes))
            fileio.save_setting(strings.SETTINGS_FILE_NAME, strings.SETTING_FILETYPES, filetypes)
            return filetypes


def get_update_types() -> list[str]:
    filetypes = fileio.get_setting(strings.SETTINGS_FILE_NAME, strings.SETTING_UPDATE_FILETYPES)
    if isinstance(filetypes, list):
        print(strings.UPDATE_PROMPT_USE_SAVED_FILE_TYPES)
        if input() == strings.PROMPT_YES: return filetypes
    filetypes = []
    while(True):
        filetype = ''
        while filetype not in strings.UPDATE_ACCEPTABLE_FILE_TYPES:
            print(strings.UPDATE_PROMPT_FILE_TYPE)
            filetype = input()
        filetypes.append(filetype)
        print(strings.UPDATE_INFO_FILE_TYPE.format(filetype))
        print(strings.AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE)
        if input() == strings.PROMPT_YES:
            filetypes = list(set(filetypes))
            fileio.save_setting(strings.SETTINGS_FILE_NAME, strings.SETTING_UPDATE_FILETYPES, filetypes)
            return filetypes


def get_update_folder() -> str:
    folder = fileio.get_setting(strings.SETTINGS_FILE_NAME, strings.SETTING_UPDATE_FOLDER)
    if folder:
        print(strings.UPDATE_PROMPT_USE_SAVED_FOLDER)
        if input() == strings.PROMPT_YES: return folder
    folder = fileio.setting(
        strings.UPDATE_PROMPT_INPUT, 
        strings.SETTINGS_FILE_NAME, 
        strings.SETTING_UPDATE_FOLDER)
    return folder


def get_files_of_type(folder: str, filetypes: list[str]) -> list[dict[str, str]]:
    results = []
    for subdir, dirs, files in os.walk(folder):
        for file in files:
            filetype = os.path.splitext(file)[1].upper()[1:]
            if filetype in filetypes:
                path = os.path.join(subdir, file)
                results.append({'path': path, 'filetype': filetype})
    return results


def get_last_page_downloaded(logfile: str) -> str:
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
        fileio.write_log(logfile, {'error': str(e), 'message': strings.ERROR_LOG_FILE, 'stacktrace': traceback.format_exc()})

    link = None
    if latest:
        print(strings.AO3_PROMPT_LAST_PAGE)
        if input() == strings.PROMPT_YES:
            link = latest['starting']

    return link
