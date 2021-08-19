import os

import ao3downloader.fileio as fileio
import ao3downloader.repo as repo
import ao3downloader.strings as strings

from ao3downloader.exceptions import LoginException

def ao3_login(session):

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
        except LoginException:
            fileio.save_setting(strings.SETTINGS_FILE_NAME, strings.SETTING_USERNAME, None)
            fileio.save_setting(strings.SETTINGS_FILE_NAME, strings.SETTING_PASSWORD, None)
            raise


def get_logfile(folder):
    fileio.make_dir(folder)
    logfile = os.path.join(folder, strings.LOG_FILE_NAME)
    return logfile
