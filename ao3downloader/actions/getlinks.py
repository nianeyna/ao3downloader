import csv
import datetime
import os

from ao3downloader import strings
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


OPTIONAL_COLUMNS = ['date_bookmarked', 'bookmarker_tags', 'bookmarker_notes', 'last_visited', 'times_visited']

def action():
    fileops = FileOps()
    with Repository(fileops) as repo:

        link = shared.link(fileops)
        series = shared.series()
        pages = shared.pages()
        metatdata = shared.metadata()

        shared.ao3_login(repo, fileops)

        ao3 = Ao3(repo, fileops, [], pages, series, False)
        links = ao3.get_work_links(link, metatdata)

        if metatdata:
            flattened = [flatten_dict(k, v) for k, v in links.items()]
            remove_empty_optional_columns(flattened)
            filename = f'links_{datetime.datetime.now().strftime("%m%d%Y%H%M%S")}.csv'
            with open(os.path.join(fileops.downloadfolder, filename), 'w', newline='', encoding='utf-8') as f:
                keys = []
                sample = flattened[0]
                for key in sample: keys.append(key)
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                for item in flattened:
                    try:
                        writer.writerow(item)
                    except ValueError:
                        fileops.write_log(item)
        else:
            filename = f'links_{datetime.datetime.now().strftime("%m%d%Y%H%M%S")}.txt'
            with open(os.path.join(fileops.downloadfolder, filename), 'w') as f:
                for l in links:
                    f.write(l + '\n')


def flatten_dict(k: str, v: dict) -> dict:
    v['link'] = k
    return v


def remove_empty_optional_columns(flattened: list[dict]) -> None:
    """remove optional columns from the csv output if they are empty for every work in the download"""

    empty = [c for c in OPTIONAL_COLUMNS if not any(item.get(c) for item in flattened)]
    for item in flattened:
        for c in empty:
            item.pop(c, None)
