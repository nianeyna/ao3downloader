# region file ops

# based on https://docs.microsoft.com/en-us/windows/win32/fileio/naming-a-file#naming-conventions
INVALID_FILENAME_CHARACTERS = r'<>:"/\|?*.' + ''.join(chr(i) for i in range(32))
TIMESTAMP_FORMAT = '%m/%d/%Y, %H:%M:%S'

DOWNLOAD_FOLDER_NAME = 'downloads'
IMAGE_FOLDER_NAME = 'images'
HTML_FOLDER_NAME = 'ao3downloader.html'
SETTINGS_FOLDER_NAME = 'ao3downloader.settings'
LOG_FOLDER_NAME = 'logs'
LOG_FILE_NAME = 'log.jsonl'
SETTINGS_FILE_NAME = 'data.json'
TEMPLATE_FILE_NAME = 'template.html'
VISUALIZATION_FILE_NAME = 'logvisualization{}.html'
IGNORELIST_FILE_NAME = 'ignorelist.txt'
INI_FILE_NAME = 'settings.ini'
INI_SECTION_NAME = 'settings'

INI_WAIT_TIME = 'ExtraWaitTime'
INI_PASSWORD_SAVE = 'SavePassword'
INI_NAME_LENGTH = 'FileNameLength'
INI_NAME_PATTERN = 'FileNamePattern'
INI_DEBUG_LOGGING = 'EnableDebugLogging'
INI_MAX_RETRIES = 'MaxRetries'

INI_DEFAULT_NAME_LENGTH = '50'
INI_DEFAULT_NAME_PATTERN = '{worknum} {title} - {author}'

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

PROMPT_MENU = '\'{}\' to display the menu again'
PROMPT_CHOOSE = 'please enter your choice, or \'{}\' to quit:'
PROMPT_OPTIONS = 'options'
PROMPT_INVALID_ACTION = 'please choose a valid action'

# for action description changes be sure to update readme
ACTION_DESCRIPTION_DISPLAY_MENU = 'display menu'
ACTION_DESCRIPTION_AO3 = 'download from ao3 link'
ACTION_DESCRIPTION_UPDATE = 'download latest version of incomplete fics'
ACTION_DESCRIPTION_PINBOARD = 'download bookmarks from pinboard'
ACTION_DESCRIPTION_VISUALIZATION = 'convert logfile into interactable html'
ACTION_DESCRIPTION_REDOWNLOAD = 're-download fics saved in one format in a different format'
ACTION_DESCRIPTION_UPDATE_SERIES = 'download missing fics from series'
ACTION_DESCRIPTION_LINKS_ONLY = 'get all work links from an ao3 listing (saves links only)'
ACTION_DESCRIPTION_MARKED_FOR_LATER = 'download marked for later list and mark all as read (requires login)'
ACTION_DESCRIPTION_FILE_INPUT = 'download links from file'
ACTION_DESCRIPTION_CONFIGURE_IGNORELIST = 'configure ignore list (list of links to never try to download)'

PINBOARD_PROMPT_API_TOKEN = 'please enter api token'
PINBOARD_PROMPT_INCLUDE_UNREAD = 'do you want to include unread bookmarks? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
PINBOARD_PROMPT_DATE = 'do you want to get bookmarks only after a specific date? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
PINBOARD_PROMPT_ENTER_DATE = 'please enter the date formatted {}:'
PINBOARD_INFO_GETTING_BOOKMARKS = 'getting bookmark urls from pinboard'
PINBOARD_INFO_NUM_RETURNED = '{} bookmarks returned'

AO3_PROMPT_LOGIN = 'do you want to log in to ao3? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_USERNAME = 'please enter username:'
AO3_PROMPT_PASSWORD = 'please enter password:\nNOTE: password {} be saved. to change this behavior,\nquit the script (using ctrl+c or by closing the window)\nand edit the \'' + INI_PASSWORD_SAVE + '\' setting in the ' + INI_FILE_NAME + '\nfile before running the script again\nNOTE: password input will not be displayed in this window'
AO3_PROMPT_PASSWORD_SAVE_TRUE = 'will'
AO3_PROMPT_PASSWORD_SAVE_FALSE = 'will not'
AO3_PROMPT_USE_SAVED_DOWNLOAD_TYPES = 'use saved download type list? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_ACCEPTABLE_DOWNLOAD_TYPES = ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML']
AO3_PROMPT_DOWNLOAD_TYPE = 'please enter download type. choose from the following (case-sensitive):\n' + '\n'.join(AO3_ACCEPTABLE_DOWNLOAD_TYPES)
AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE = 'done entering file types? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_LINK = 'please enter link to ao3'
AO3_PROMPT_LAST_PAGE = 'do you want to start downloading from the page you stopped on last time? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_PAGES = 'please enter page number to stop on. enter 0 to download all pages.'
AO3_PROMPT_IMAGES = 'do you want to download embedded images? (will be saved separately) ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_SERIES = 'do you want to get works from all encountered series links? (bookmarked series will always be downloaded, regardless of this option) ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_METADATA = 'do you want to include work metadata? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_FILE_INPUT = 'please enter complete file path (including file extension) to file containing links to download (must be a text file with one link on each line)'
AO3_INFO_LOGIN = 'logging in'
AO3_INFO_DOWNLOADING = 'downloading works'
AO3_INFO_FILE_TYPE = 'added {} to list of download types'
AO3_INFO_VISITED = 'generating list of work links that are already in the downloads folder (will be skipped)'

UPDATE_PROMPT_INPUT = 'input path to folder containing files you want to check for updates (also checks subfolders)'
UPDATE_INFO_FILES = 'getting list of files'
UPDATE_INFO_NUM_RETURNED = '{} files found'
UPDATE_INFO_URLS = 'getting urls of incomplete fics'
UPDATE_INFO_URLS_DONE = 'finished getting urls of incomplete fics'
UPDATE_INFO_DOWNLOADING = 're-downloading incomplete works'
UPDATE_ACCEPTABLE_FILE_TYPES = ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML']
UPDATE_PROMPT_USE_SAVED_FILE_TYPES = 'use saved list of file types to check for updates? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
UPDATE_PROMPT_USE_SAVED_FOLDER = 'check same folder as last time? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
UPDATE_PROMPT_FILE_TYPE = 'please enter the file type of the files you would like to check for updates. choose from the following (case-sensitive):\n' + '\n'.join(UPDATE_ACCEPTABLE_FILE_TYPES)
UPDATE_INFO_FILE_TYPE = 'added {} to list of file types to check for updates'
UPDATE_INFO_FILTER = 'filtering out works that could not be downloaded on previous runs'

SERIES_INFO_FILES = 'getting list of works belonging to series'
SERIES_INFO_URLS = 'finding all series urls'
SERIES_INFO_NUM = '{} series found'
SERIES_INFO_DOWNLOADING = 'downloading works missing from series'
SERIES_INFO_FILTER = 'filtering out series that could not be downloaded on previous runs'

REDOWNLOAD_PROMPT_FOLDER = 'please enter the folder containing the files you want to re-download (also checks subfolders):'
REDOWNLOAD_PROMPT_FILE_TYPE = 'please enter file type you want to convert from. choose from the following (case sensitive):\n' + '\n'.join(UPDATE_ACCEPTABLE_FILE_TYPES)
REDOWNLOAD_INFO_FILE_TYPE = 'added {} to list of file types to convert from'
REDOWNLOAD_INFO_URLS = 'getting work urls'
REDOWNLOAD_INFO_DONE = 'done getting work urls. {} urls found'

IGNORELIST_INFO_INITIALIZED = f'{IGNORELIST_FILE_NAME} has been added to the main script folder. you can use this file to perma-skip downloading works or series that you know you don\'t want to download. to use this file open it in a text editor (the default text editor for Windows is called Notepad. on Mac, you can use TextEdit) and add the links you want to ignore, one on each line. these should be links to ao3 works or series. other links will be ignored. each link MUST begin with https://archiveofourown.org and be placed at the start of a new line. you may also *optionally* add a comment after each link. comments must begin with a SEMICOLON followed by a SPACE: `; ` and must not contain any newline characters (the entire comment must be on the same line as the link). otherwise, you can write anything you want in the comment. comments are for your personal reference only and are not used by the script.'
IGNORELIST_PROMPT_CHECK_DELETED = 'do you want to check the log file for deleted links and add them to the ignore list automatically?'

INFO_NO_LOG_FILE = 'no log file'
INFO_NO_FOLDER = 'folder does not exist'
INFO_EXCLUDING_WORKS = 'filtering out works that are already in the downloads folder'
INFO_STARTING_PAGE = 'starting page'
INFO_FINISHED_PAGE = 'finished getting page {}. starting page {}'
INFO_PARSING_LOGS = 'parsing data from log entries with timestamps starting at {} and ending at {}'
INFO_LINKS_LIST_CANCELED = '\nlink list generation manually canceled. list may not be complete.'
INFO_NO_WORKS_ON_PAGE = 'ending scrape because no work or series urls were found on page'
INFO_PAGE_LIMIT_REACHED = 'ending scrape because page limit was reached'

MESSAGE_TOO_MANY_REQUESTS = 'ao3 has requested a {} second break\npaused at: {}\nresuming at: {}'
MESSAGE_RESUMING = 'resuming execution'
MESSAGE_INCOMPLETE_FIC = 'found incomplete fic'
MESSAGE_FIC_FILE = 'found fic file'
MESSAGE_SERIES_FILE = 'found work in series'
MESSAGE_RETRY = 'Retrying {} request. Attempt {}. {} seconds until next attempt.'
MESSAGE_SUCCESS = 'Successful {} request with status code {}'
MESSAGE_WELCOME = 'welcome to ao3downloader!\nthe script has been initialized in the following directory:\n\t{}\nif you would like to change any settings, you may do so by entering\n\'{}\' to quit this menu and then editing the file \'{}\'\n(located at the above folder path) before running the script again.\n'
MESSAGE_EXIT = '\nexiting'
MESSAGE_INI_FILE_CHANGED = 'the options available in ' + INI_FILE_NAME + ' have changed. a copy of the new default settings file has been saved as {}. please review the changes and update ' + INI_FILE_NAME + ' accordingly.'
MESSAGE_INI_DIFFERENCES = 'the following differences were found:\n'
MESSAGE_INI_ADDED_KEY = 'added \'{}\' to \'{}\' section.\n'
MESSAGE_INI_REMOVED_KEY = 'removed \'{}\' from \'{}\' section.\n'
MESSAGE_INI_ADDED_SECTION = '\'{}\' section has been added.\n'
MESSAGE_INI_REMOVED_SECTION = '\'{}\' section has been removed.\n'

# endregion

# region ao3 scraping

AO3_DOMAIN = 'archiveofourown.org'
AO3_BASE_URL = 'https://archiveofourown.org'
AO3_LOGIN_URL = 'https://archiveofourown.org/users/login'

AO3_FAILED_LOGIN = 'The password or user name you entered doesn\'t match our records.'
AO3_PROCEED = 'Yes, Continue'
AO3_MARK_READ = 'Mark as Read'

# endregion

# region pinboard scraping

POSTS_FROM_DATE_URL = 'https://api.pinboard.in/v1/posts/all?auth_token={}&fromdt={}'
ALL_POSTS_URL = 'https://api.pinboard.in/v1/posts/all?auth_token={}'
TIMESTAMP_URL = '{}-{}-{}T00:00:00Z'

# endregion

# region error messages

ERROR_INVALID_LINK = 'Not an ao3 link'
ERROR_LOCKED = 'Locked'
ERROR_DELETED = 'Deleted'
ERROR_FAILED_LOGIN = 'Failed login'
ERROR_PROCEED_LINK = 'Problem getting proceed link'
ERROR_DOWNLOAD_LINK = 'Problem getting download link'
ERROR_LOG_FILE = 'Problem parsing log file during initial setup'
ERROR_INCOMPLETE_FIC = 'Problem parsing file while checking for incomplete fics'
ERROR_FIC_IN_SERIES = 'Problem parsing file while checking for fics in series'
ERROR_REDOWNLOAD = 'Error processing file for re-download'
ERROR_IMAGE = 'Problem getting image'
ERROR_LINKS_LIST = 'Error encountered while getting links list. List may not be complete.'
ERROR_HTTP_REQUEST = 'Unrecoverable error encountered while making web request'
ERROR_INVALID_STATUS_CODE = 'Request failed with status code {}'
ERROR_TIMEOUT = 'Request exceeded the timeout limit of {} seconds'

# endregion
