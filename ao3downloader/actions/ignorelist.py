from ao3downloader import strings
from ao3downloader.actions import shared
from ao3downloader.fileio import FileOps

def action():
    fileops = FileOps()
    with open('ignorelist.txt', 'a', encoding='utf-8'): pass
    entries = list(map(lambda x: x[:x.find('; ')]))
    print(strings.IGNORELIST_INFO_INITIALIZED)
    if shared.ignorelist_check_deleted():
        with open('ignorelist.txt', 'r', encoding='utf-8') as f: 
            ignorelist = f.readlines()
        logfile = fileops.load_logfile()
        deleted = list(map(lambda y: y['link'], filter(lambda x: x.get('error') == strings.ERROR_DELETED)))
        for d in deleted: 
            paths = [x['path'] for x in logfile if 'path' in x and x.get('link') == d]
        newlinks = list(filter(lambda x: x not in ignorelist, deleted))
        with open('ignorelist.txt', 'a', encoding='utf-8') as f:
            for link in newlinks:
                f.write(f'{link}; Deleted\n')
