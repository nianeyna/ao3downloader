# region file ops

DOWNLOAD_FOLDER_NAME = 'downloads'
LOG_FOLDER_NAME = 'logs'
HTML_FOLDER_NAME = 'html'
LOG_FILE_NAME = 'log.jsonl'
TEMPLATE_FILE_NAME = 'template.html'
VISUALIZATION_FILE_NAME = 'logvisualization.html'
SETTINGS_FILE_NAME = 'settings.json'

SETTING_USERNAME = 'username'
SETTING_PASSWORD = 'password'
SETTING_FILETYPES = 'filetypes'
SETTING_API_TOKEN = 'api_token'
SETTING_UPDATE_FOLDER = 'update_folder'
SETTING_UPDATE_FILETYPES = 'update_filetypes'

# endregion

# region ui

PROMPT_YES = 'y'
PROMPT_NO = 'n'

PROMPT_OPTIONS = 'options'
PROMPT_INVALID_ACTION = 'please choose a valid action'

# for action description changes be sure to update readme
ACTION_DESCRIPTION_DISPLAY_MENU = 'display menu'
ACTION_DESCRIPTION_AO3 = 'download from ao3 link'
ACTION_DESCRIPTION_UPDATE = 'download latest version of incomplete fics'
ACTION_DESCRIPTION_PINBOARD = 'download bookmarks from pinboard'
ACTION_DESCRIPTION_VISUALIZATION = 'convert logfile into interactable html'

PINBOARD_PROMPT_API_TOKEN = 'please enter api token'
PINBOARD_PROMPT_INCLUDE_UNREAD = 'do you want to include unread bookmarks? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
PINBOARD_PROMPT_DATE = 'do you want to get bookmarks only after a specific date? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
PINBOARD_PROMPT_ENTER_DATE = 'please enter the date formatted {}:'
PINBOARD_INFO_GETTING_BOOKMARKS = 'getting bookmark urls from pinboard'
PINBOARD_INFO_NUM_RETURNED = '{} bookmarks returned'

AO3_PROMPT_LOGIN = 'do you want to log in to ao3? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_USERNAME = 'please enter username'
AO3_PROMPT_PASSWORD = 'please enter password'
AO3_PROMPT_USE_SAVED_DOWNLOAD_TYPES = 'use saved download type list? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_ACCEPTABLE_DOWNLOAD_TYPES = ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML']
AO3_PROMPT_DOWNLOAD_TYPE = 'please enter download type. choose from the following (case-sensitive):\n' + '\n'.join(AO3_ACCEPTABLE_DOWNLOAD_TYPES)
AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE = 'done entering file types? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_LINK = 'please enter link to ao3'
AO3_PROMPT_LAST_PAGE = 'do you want to start downloading from the page you stopped on last time? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_PAGES = 'please enter page number to stop on. enter 0 to download all pages.'
AO3_PROMPT_SUBFOLDERS = 'do you want to create series subfolders? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_INFO_LOGIN = 'logging in'
AO3_INFO_DOWNLOADING = 'downloading works'
AO3_INFO_FILE_TYPE = 'added {} to list of download types'

UPDATE_PROMPT_INPUT = 'input path to folder containing files you want to check for updates (also checks subfolders)'
UPDATE_INFO_FILES = 'getting list of files to update'
UPDATE_INFO_NUM_RETURNED = '{} files found'
UPDATE_INFO_URLS = 'getting urls of incomplete fics'
UPDATE_INFO_URLS_DONE = 'finished getting urls of incomplete fics'
UPDATE_INFO_DOWNLOADING = 're-downloading incomplete works'
UPDATE_ACCEPTABLE_FILE_TYPES = ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML']
UPDATE_PROMPT_USE_SAVED_FILE_TYPES = 'use saved list of file types to check for updates? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
UPDATE_PROMPT_FILE_TYPE = 'please enter the file type of the files you would like to check for updates. choose from the following (case-sensitive):\n' + '\n'.join(UPDATE_ACCEPTABLE_FILE_TYPES)
UPDATE_INFO_FILE_TYPE = 'added {} to list of file types to check for updates'

INFO_NO_LOG_FILE = 'no log file'

MESSAGE_TOO_MANY_REQUESTS = 'too many requests to server. resuming in 5 minutes. paused at: {}'
MESSAGE_RESUMING = 'resuming execution'
MESSAGE_INCOMPLETE_FIC = 'found incomplete fic'

# endregion

# region ao3 scraping

AO3_BASE_URL = 'https://archiveofourown.org'

AO3_LOCKED = 'This work is only available to registered users of the Archive'
AO3_DELETED = 'Error 404'
AO3_EXPLICIT = 'This work could have adult content.'
AO3_FAILED_LOGIN = 'The password or user name you entered doesn\'t match our records.'
AO3_PROCEED = 'Proceed'

AO3_TITLE = '[Archive of Our Own]'
AO3_CHAPTER_TITLE = 'Chapter 1 - '

# endregion

# region error messages

ERROR_INVALID_LINK = 'Not a series or work'
ERROR_LOCKED = 'Locked'
ERROR_DELETED = 'Deleted'
ERROR_UNKNOWN = 'Unspecified error'
ERROR_ATTRIBUTE = 'Unrecognized'
ERROR_FAILED_LOGIN = 'Failed login'
ERROR_PROCEED_LINK = 'Problem getting proceed link'
ERROR_DOWNLOAD_LINK = 'Problem getting download link'
ERROR_SERIES = 'Problem getting series'
ERROR_LOG_FILE = 'Problem parsing log file during initial setup'
ERROR_INCOMPLETE_FIC = 'Problem parsing file while checking for incomplete fics'

# endregion
