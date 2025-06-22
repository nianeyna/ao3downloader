import datetime
import os
import traceback

from ao3downloader import exceptions, parse_text, strings
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


def series() -> bool:
    print(strings.AO3_PROMPT_SERIES)
    series = True if input() == strings.PROMPT_YES else False
    return series


def link(fileops: FileOps) -> str:
    link = get_last_page_downloaded(fileops)
    if not link: 
        print(strings.AO3_PROMPT_LINK)
        link = input()
    return link


def pages() -> int:
    print(strings.AO3_PROMPT_PAGES)
    pages = input()

    try:
        pages = int(pages)
        if pages <= 0:
            pages = None
    except:
        pages = None

    return pages


def images() -> bool:
    print(strings.AO3_PROMPT_IMAGES)
    images = True if input() == strings.PROMPT_YES else False
    return images


def metadata() -> bool:
    print(strings.AO3_PROMPT_METADATA)
    return True if input() == strings.PROMPT_YES else False


def ignorelist_check_deleted() -> bool:
    print(strings.IGNORELIST_PROMPT_CHECK_DELETED)
    return True if input() == strings.PROMPT_YES else False


def visited(fileops: FileOps, filetypes: list[str]) -> list[str]:
    visited = []
    logs = fileops.load_logfile()
    if logs:
        print(strings.AO3_INFO_VISITED)
        titles = parse_text.get_title_dict(logs)
        maximum = fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        visited = list({x for x in titles if 
            fileops.file_exists(x, titles, filetypes, maximum)})
    if os.path.exists(strings.IGNORELIST_FILE_NAME):
        with open(strings.IGNORELIST_FILE_NAME, 'r', encoding='utf-8') as f: 
                visited.extend([x[:x.find('; ')] for x in f.readlines()])
    return visited


def pinboard_date() -> datetime.datetime:
    print(strings.PINBOARD_PROMPT_DATE)
    getdate = True if input() == strings.PROMPT_YES else False
    if getdate:
        date_format = 'mm/dd/yyyy'
        print(strings.PINBOARD_PROMPT_ENTER_DATE.format(date_format))
        inputdate = input()
        date = datetime.datetime.strptime(inputdate, '%m/%d/%Y')
    else:
        date = None
    return date


def pinboard_exclude() -> bool:
    print(strings.PINBOARD_PROMPT_INCLUDE_UNREAD)
    exclude_toread = False if input() == strings.PROMPT_YES else True
    return exclude_toread


def api_token(fileops: FileOps) -> str:
    return fileops.setting(
            strings.PINBOARD_PROMPT_API_TOKEN, 
            strings.SETTING_API_TOKEN)


def redownload_folder() -> str:
    while True:
        print(strings.REDOWNLOAD_PROMPT_FOLDER)
        folder = input()
        if os.path.exists(folder): 
            break
        else:
            print(strings.INFO_NO_FOLDER)
    return folder


def redownload_oldtypes() -> list[str]:
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
    return oldtypes


def redownload_newtypes() -> list[str]:
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
    return newtypes


def marked_for_later_link(fileops: FileOps) -> str:
    username = fileops.get_setting(strings.SETTING_USERNAME)
    return f'{strings.AO3_BASE_URL}/users/{username}/readings?show=to-read'


def ao3_login(repo: Repository, fileops: FileOps, force: bool=False) -> None:

    if force:
        login = True
    else:
        print(strings.AO3_PROMPT_LOGIN)
        login = False if input() == strings.PROMPT_NO else True

    if login:
        savepassword = fileops.get_ini_value_boolean(strings.INI_PASSWORD_SAVE, False)
        passwordprompt = strings.AO3_PROMPT_PASSWORD_SAVE_TRUE if savepassword else strings.AO3_PROMPT_PASSWORD_SAVE_FALSE

        username = fileops.setting(
            strings.AO3_PROMPT_USERNAME,
            strings.SETTING_USERNAME)
        password = fileops.setting(
            strings.AO3_PROMPT_PASSWORD.format(passwordprompt),
            strings.SETTING_PASSWORD,
            savepassword, True)

        print(strings.AO3_INFO_LOGIN)
        try:
            repo.login(username, password)
        except exceptions.LoginException:
            fileops.save_setting(strings.SETTING_USERNAME, None)
            fileops.save_setting(strings.SETTING_PASSWORD, None)
            raise


def download_types(fileops: FileOps) -> list[str]:
    filetypes = fileops.get_setting(strings.SETTING_FILETYPES)
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
            fileops.save_setting(strings.SETTING_FILETYPES, filetypes)
            return filetypes


def update_types(fileops: FileOps) -> list[str]:
    filetypes = fileops.get_setting(strings.SETTING_UPDATE_FILETYPES)
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
            fileops.save_setting(strings.SETTING_UPDATE_FILETYPES, filetypes)
            return filetypes


def update_folder(fileops: FileOps) -> str:
    folder = fileops.get_setting(strings.SETTING_UPDATE_FOLDER)
    if folder:
        print(strings.UPDATE_PROMPT_USE_SAVED_FOLDER)
        if input() == strings.PROMPT_YES: 
            return folder
        else:
            fileops.save_setting(
                strings.SETTING_UPDATE_FOLDER, 
                None)
    folder = fileops.setting(
        strings.UPDATE_PROMPT_INPUT,
        strings.SETTING_UPDATE_FOLDER)
    return folder


def get_files_of_type(folder: str, filetypes: list[str]) -> list[dict[str, str]]:
    print(strings.UPDATE_INFO_FILES)
    results = []
    for subdir, dirs, files in os.walk(folder):
        for file in files:
            filetype = os.path.splitext(file)[1].upper()[1:]
            if filetype in filetypes:
                path = os.path.join(subdir, file)
                results.append({'path': path, 'filetype': filetype})
    print(strings.UPDATE_INFO_NUM_RETURNED.format(len(results)))
    return results


def get_last_page_downloaded(fileops: FileOps) -> str:
    latest = None
    try:
        logs = fileops.load_logfile()
        starts = filter(lambda x: x and 'message' in x and x['message'] == strings.INFO_STARTING_PAGE, logs)
        if not starts: starts = filter(lambda x: 'starting' in x, logs) # backwards compatibility
        bydate = sorted(starts, key=lambda x: datetime.datetime.strptime(x['timestamp'], '%m/%d/%Y, %H:%M:%S'), reverse=True)
        if bydate: latest = bydate[0]
    except Exception as e:
        fileops.write_log({'error': str(e), 'message': strings.ERROR_LOG_FILE, 'stacktrace': traceback.format_exc()})

    link = None
    if latest:
        print(strings.AO3_PROMPT_LAST_PAGE)
        if input() == strings.PROMPT_YES:
            link = latest['link'] if 'link' in latest else latest['starting']

    return link
