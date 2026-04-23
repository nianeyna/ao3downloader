import os
from collections.abc import Callable
from typing import NamedTuple

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


class MenuAction(NamedTuple):
    description: str
    run: Callable[[], None]


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
    for key, action in actions.items():
        print(' {}: {}'.format(key, action.description))


def choose(choice):
    try:
        action = actions[choice]
    except KeyError:
        print(strings.PROMPT_INVALID_ACTION)
        return
    try:
        action.run()
    except Exception as e:
        print(str(e))


QUIT_ACTION = 'q'
MENU_ACTION = 'd'

actions: dict[str, MenuAction] = {
    MENU_ACTION: MenuAction(strings.ACTION_DESCRIPTION_DISPLAY_MENU, display_menu),
    'a': MenuAction(strings.ACTION_DESCRIPTION_AO3, ao3_download_action),
    'l': MenuAction(strings.ACTION_DESCRIPTION_LINKS_ONLY, links_only_action),
    'f': MenuAction(strings.ACTION_DESCRIPTION_FILE_INPUT, file_input_action),
    'u': MenuAction(strings.ACTION_DESCRIPTION_UPDATE, update_epubs_action),
    's': MenuAction(strings.ACTION_DESCRIPTION_UPDATE_SERIES, update_series_action),
    'r': MenuAction(strings.ACTION_DESCRIPTION_REDOWNLOAD, re_download_action),
    'm': MenuAction(strings.ACTION_DESCRIPTION_MARKED_FOR_LATER, marked_for_later_action),
    'p': MenuAction(strings.ACTION_DESCRIPTION_PINBOARD, pinboard_download_action),
    'v': MenuAction(strings.ACTION_DESCRIPTION_VISUALIZATION, log_visualization_action),
    'i': MenuAction(strings.ACTION_DESCRIPTION_CONFIGURE_IGNORELIST, ignorelist_action),
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
