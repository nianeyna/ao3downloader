"""File operations go here."""

import datetime
import json
import os

from ao3downloader import parse_text


def write_log(filename: str, log: dict) -> None:
    log['timestamp'] = datetime.datetime.now().strftime('%m/%d/%Y, %H:%M:%S')
    with open(filename, 'a', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False)
        f.write('\n')


def make_dir(folder: str) -> None:
    if not os.path.exists(folder):
        os.mkdir(folder)


def save_bytes(folder: str, filename: str, content: bytes) -> None:
    file = os.path.join(folder, filename)
    with open(file, 'wb') as f:
        f.write(content)


def save_setting(filename: str, setting: str, value) -> None:
    js = get_json(filename)
    if value is None:
        js.pop(setting, None)
    else:
        js[setting] = value
    with open(filename, 'w') as f:
        f.write(json.dumps(js))


def get_setting(filename: str, setting: str):
    js = get_json(filename)
    try:
        return js[setting]
    except:
        return ''


def get_json(filename: str) -> dict:
    with open(filename, 'a', encoding='utf-8'):
        pass
    with open(filename, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except:
            return {}


def setting(prompt: str, filename: str, setting: str):
    value = get_setting(filename, setting)
    if value == '':
        print(prompt)
        value = input()
        save_setting(filename, setting, value)
    return value


def load_logfile(logfile: str) -> list[dict]:
    logs = []
    try:
        with open(logfile, 'r', encoding='utf-8') as f:
            objects = map(lambda x: json.loads(x), f.readlines())
            logs.extend(list(objects))
    except FileNotFoundError:
        pass
    return logs


def file_exists(id: str, titles: dict[str, str], filetypes: list[str], folder: str) -> bool:
    if id not in titles: return False
    filename = parse_text.get_valid_filename(titles[id])
    files = list(map(lambda x: os.path.join(folder, filename + '.' + x.lower()), filetypes))
    for file in files:
        if not os.path.exists(file):
            return False
    return True
