'''Create an html document for the purpose of visualizing the logfile. Not the most optimized thing ever but it does the job.'''

import datetime
import importlib
import importlib.resources
import json
import os

import ao3downloader.strings as strings

SIZE_HINT = 5000000 # 5 mb, firefox max filesize is 10 mb

def action():

    logfile = os.path.join(strings.LOG_FOLDER_NAME, strings.LOG_FILE_NAME)
    visfile = os.path.join(strings.LOG_FOLDER_NAME, strings.VISUALIZATION_FILE_NAME)

    if not os.path.exists(logfile):
        print(strings.INFO_NO_LOG_FILE)
        return
    
    with importlib.resources.open_text(strings.HTML_FOLDER_NAME, strings.TEMPLATE_FILE_NAME) as tmpl:
        template = tmpl.read()

    filenumber = 0 # fallback identifier in case timestamps can't be extracted

    with open(logfile, 'r', encoding='utf-8') as f:
        while True:
            buf = f.readlines(SIZE_HINT)

            if not buf:
                break

            start = get_timestamp(buf[0], filenumber)
            end = get_timestamp(buf[-1], filenumber)
            filename = visfile.format(f'{start}-{end}')

            if os.path.exists(filename):
                continue # we already have this chunk

            print(strings.INFO_PARSING_LOGS.format(start, end))

            keys = ['timestamp'] # always put timestamp first
            data = []

            for line in buf:
                js = json.loads(line)
                if 'level' in js and js['level'] == 'debug': continue
                if 'starting' in js: continue # backwards compatibility
                for key in js:
                    if key not in keys:
                        keys.append(key)
                data.append(js)

            for item in data:
                for key in keys:
                    if key not in item:
                        item[key] = ''

            thead = '<thead><tr>'
            for key in keys:
                thead += '<th>' + key + '</th>'
            thead += '</tr></thead>'

            tbody = '<tbody>'
            for item in data:
                tr = '<tr>'
                for key in keys:
                    key_item = str(item[key])
                    tr += '<td>' + key_item + '</td>'
                tr += '</tr>'
                tbody += tr
            tbody += '</tbody>'

            table = thead + tbody

            logvisualization = template.replace('%TABLE%', table)

            with open (filename, 'w', encoding='utf-8') as vis:
                vis.write(logvisualization)

            filenumber += 1


def get_timestamp(line: str, filenumber: int) -> str:
    try:
        js = json.loads(line)
        ts = js['timestamp']
        dt = datetime.datetime.strptime(ts, strings.TIMESTAMP_FORMAT)
        return dt.strftime('%Y%m%d_%H%M%S')
    except:
        return f'timestamp_error_{filenumber}'
