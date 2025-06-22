import os

import ao3downloader.strings as strings
from ao3downloader.fileio import FileOps

from ao3downloader.actions import ao3download
from ao3downloader.actions import pinboarddownload
from ao3downloader.actions import updatefics
from ao3downloader.actions import redownload
from ao3downloader.actions import logvisualization
from ao3downloader.actions import updateseries
from ao3downloader.actions import getlinks
from ao3downloader.actions import markedforlater
from ao3downloader.actions import enterlinks
from ao3downloader.actions import ignorelist


def ao3_download_action():
    ao3download.action()


def links_only_action():
    getlinks.action()


def file_input_action():
    enterlinks.action()


def update_epubs_action():
    updatefics.action()


def update_series_action():
    updateseries.action()
    

def re_download_action():
    redownload.action()


def marked_for_later_action():
    markedforlater.action()


def pinboard_download_action():
    pinboarddownload.action()


def log_visualization_action():
    logvisualization.action()


def ignorelist_action():
    ignorelist.action()


def display_menu():
    print(strings.PROMPT_OPTIONS)
    for key, value in actions.items():
        try:
            desc = value.description
        except AttributeError:
            desc = value.__name__
        print(' {}: {}'.format(key, desc))


def choose(choice):
    try:
        function = actions[choice]
        try:
            function()
        except Exception as e:
            print(str(e))
    except KeyError as e:
        print(strings.PROMPT_INVALID_ACTION)


display_menu.description = strings.ACTION_DESCRIPTION_DISPLAY_MENU
ao3_download_action.description = strings.ACTION_DESCRIPTION_AO3
update_epubs_action.description = strings.ACTION_DESCRIPTION_UPDATE
pinboard_download_action.description = strings.ACTION_DESCRIPTION_PINBOARD
log_visualization_action.description = strings.ACTION_DESCRIPTION_VISUALIZATION
re_download_action.description = strings.ACTION_DESCRIPTION_REDOWNLOAD
update_series_action.description = strings.ACTION_DESCRIPTION_UPDATE_SERIES
links_only_action.description = strings.ACTION_DESCRIPTION_LINKS_ONLY
marked_for_later_action.description = strings.ACTION_DESCRIPTION_MARKED_FOR_LATER
file_input_action.description = strings.ACTION_DESCRIPTION_FILE_INPUT
ignorelist_action.description = strings.ACTION_DESCRIPTION_CONFIGURE_IGNORELIST

QUIT_ACTION = 'q'
MENU_ACTION = 'd'

actions = {
    MENU_ACTION: display_menu,
    'a': ao3_download_action,
    'l': links_only_action,
    'f': file_input_action,
    'u': update_epubs_action,
    's': update_series_action,
    'r': re_download_action,
    'm': marked_for_later_action,
    'p': pinboard_download_action,
    'v': log_visualization_action,
    'i': ignorelist_action
    }

def ao3downloader():
    try:
        os.system('clear||cls')
        fileOps = FileOps()
        fileOps.initialize()
        print(strings.MESSAGE_WELCOME.format(os.getcwd(), QUIT_ACTION, strings.INI_FILE_NAME))
        fileOps.update_ini()
        display_menu()
        while True:
            print(strings.PROMPT_MENU.format(MENU_ACTION))
            print(strings.PROMPT_CHOOSE.format(QUIT_ACTION))
            choice = input()
            if choice == QUIT_ACTION: break
            choose(choice)
    except KeyboardInterrupt:
        print(strings.MESSAGE_EXIT)

if __name__ == '__main__':
    ao3downloader()
