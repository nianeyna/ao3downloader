from ao3downloader import strings
from ao3downloader.actions import shared
from ao3downloader.fileio import FileOps

def action():
    fileops = FileOps()
    with open(strings.IGNORELIST_FILE_NAME, 'a', encoding='utf-8'): pass
    print(strings.IGNORELIST_INFO_INITIALIZED)
    if shared.ignorelist_check_deleted():
        with open(strings.IGNORELIST_FILE_NAME, 'r', encoding='utf-8') as f: 
            ignorelist = [x[:x.find('; ')] for x in f.readlines()]
        logfile = fileops.load_logfile()
        deleted = [x['link'] for x in logfile if x.get('error') == strings.ERROR_DELETED]
        pathdict = {}
        for d in deleted:
            paths = [x['path'] for x in logfile if 'path' in x and x.get('link') == d or ('series' in x and d in x['series'])]
            if paths: pathdict[d] = list(set(paths))
        newlinks = list(filter(lambda x: x not in ignorelist, deleted))
        with open(strings.IGNORELIST_FILE_NAME, 'a', encoding='utf-8') as f:
            for link in newlinks:
                f.write(f'{link}; Deleted')
                if pathdict[link]: f.write(f': associated filepaths - {pathdict[link]}')
                f.write('\n')
