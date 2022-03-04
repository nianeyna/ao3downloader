import os
import requests

import ao3downloader.exceptions as exceptions
import ao3downloader.fileio as fileio
import ao3downloader.repo as repo
import ao3downloader.strings as strings


def get_logfile() -> str:
    if not os.path.exists(strings.LOG_FOLDER_NAME):
        os.mkdir(strings.LOG_FOLDER_NAME)
    return os.path.join(strings.LOG_FOLDER_NAME, strings.LOG_FILE_NAME)


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
