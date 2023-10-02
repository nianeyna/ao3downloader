import traceback

from ao3downloader import parse_text, strings, update
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository
from tqdm import tqdm


def action():
    fileops = FileOps()
    with Repository(fileops) as repo:

        folder = shared.update_folder(fileops)
        update_filetypes = shared.update_types(fileops)
        download_filetypes = shared.download_types(fileops)
        images = shared.images()

        shared.ao3_login(repo, fileops)

        files = shared.get_files_of_type(folder, update_filetypes)

        print(strings.SERIES_INFO_FILES)

        works = []
        for file in tqdm(files):
            try:
                work = update.process_file(file['path'], file['filetype'], True, True)
                if work:
                    works.append(work)
                    fileops.write_log({'message': strings.MESSAGE_SERIES_FILE, 'path': file['path'], 'link': work['link'], 'series': work['series']})
            except Exception as e:
                fileops.write_log({'message': strings.ERROR_FIC_IN_SERIES, 'path': file['path'], 'error': str(e), 'stacktrace': traceback.format_exc()})    

        print(strings.SERIES_INFO_URLS)

        series = dict[str, list[str]]()
        for work in works:
            for s in work['series']:
                if s not in series:
                    series[s] = []
                link = work['link'].replace('http://', 'https://')
                if link not in series[s]:
                    series[s].append(link)

        logs = fileops.load_logfile()
        if logs:
            unsuccessful = parse_text.get_unsuccessful_downloads(logs)
            if any('/series/' in x for x in unsuccessful):
                print(strings.SERIES_INFO_FILTER)
                series = {k: v for k, v in series.items() if k not in unsuccessful}

        print(strings.SERIES_INFO_NUM.format(len(series)))

        print(strings.SERIES_INFO_DOWNLOADING)

        ao3 = Ao3(repo, fileops, download_filetypes, None, True, images)

        for key, value in tqdm(series.items()):
            ao3.update_series(key, value)
