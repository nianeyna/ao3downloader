from ao3downloader import parse_text, parse_xml, strings
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository
from tqdm import tqdm


def action():
    fileops = FileOps()
    with Repository(fileops) as repo:

        filetypes = shared.download_types(fileops)
        date = shared.pinboard_date()
        exclude_toread = shared.pinboard_exclude()
        images = shared.images()
        api_token = shared.api_token(fileops)
        
        shared.ao3_login(repo, fileops)
        
        print(strings.PINBOARD_INFO_GETTING_BOOKMARKS)

        url = parse_text.get_pinboard_url(api_token, date)
        bookmark_xml = repo.get_xml(url)
        bookmarks = parse_xml.get_bookmark_list(bookmark_xml, exclude_toread)

        print(strings.PINBOARD_INFO_NUM_RETURNED.format(len(bookmarks)))

        logs = fileops.load_logfile()
        if logs:
            print(strings.INFO_EXCLUDING_WORKS)
            titles = parse_text.get_title_dict(logs)
            unsuccessful = parse_text.get_unsuccessful_downloads(logs)
            maximum = fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
            bookmarks = list(filter(lambda x: 
                not fileops.file_exists(x['href'], titles, filetypes, maximum) 
                and x['href'] not in unsuccessful, 
                bookmarks))

        print(strings.AO3_INFO_DOWNLOADING)

        ao3 = Ao3(repo, fileops, filetypes, None, True, images)

        for item in tqdm(bookmarks):
            ao3.download(item['href'])
