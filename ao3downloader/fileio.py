"""File operations go here."""

import datetime
import json
import os
import string


def write_log(filename, log):
    log['timestamp'] = datetime.datetime.now().strftime('%m/%d/%Y, %H:%M:%S')
    with open(filename, 'a', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False)
        f.write('\n')


def make_dir(folder):
    if not os.path.exists(folder):
        os.mkdir(folder)


def save_bytes(folder, filename, content):
    file = os.path.join(folder, filename)
    with open(file, 'wb') as f:
        f.write(content)


def get_valid_filename(filename):
    valid_chars = '-_.() {}{}'.format(string.ascii_letters, string.digits)
    valid_name = ''
    for c in filename:
        if c in valid_chars:
            valid_name = valid_name + c
    return valid_name[:100].strip()


def save_setting(filename, setting, value):
    js = get_json(filename)
    if value is None:
        js.pop(setting, None)
    else:
        js[setting] = value
    with open(filename, 'w') as f:
        f.write(json.dumps(js))


def get_setting(filename, setting):
    js = get_json(filename)
    try:
        return js[setting]
    except:
        return ''


def get_json(filename):
    with open(filename, 'a', encoding='utf-8'):
        pass
    with open(filename, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except:
            return {}


def setting(prompt, filename, setting):
    value = get_setting(filename, setting)
    if value == '':
        print(prompt)
        value = input()
        save_setting(filename, setting, value)
    return value
