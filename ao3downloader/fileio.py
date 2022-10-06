"""File operations go here."""

import datetime
import json
import os

from ao3downloader import parse_text, strings


class FileOps:
    def __init__(self):
        if not os.path.exists(strings.LOG_FOLDER_NAME): os.mkdir(strings.LOG_FOLDER_NAME)
        if not os.path.exists(strings.DOWNLOAD_FOLDER_NAME): os.mkdir(strings.DOWNLOAD_FOLDER_NAME)
        self.logfile = os.path.join(strings.LOG_FOLDER_NAME, strings.LOG_FILE_NAME)
        self.settingsfile = strings.SETTINGS_FILE_NAME
        self.downloadfolder = strings.DOWNLOAD_FOLDER_NAME


    def write_log(self, log: dict) -> None:
        log['timestamp'] = datetime.datetime.now().strftime('%m/%d/%Y, %H:%M:%S')
        with open(self.logfile, 'a', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False)
            f.write('\n')


    def save_bytes(self, filename: str, content: bytes) -> None:
        file = os.path.join(self.downloadfolder, filename)
        os.makedirs(os.path.dirname(file), exist_ok=True)
        with open(file, 'wb') as f:
            f.write(content)

    def save_setting(self, setting: str, value) -> None:
        js = self.get_settings_json()
        if value is None:
            js.pop(setting, None)
        else:
            js[setting] = value
        with open(self.settingsfile, 'w') as f:
            f.write(json.dumps(js))


    def get_setting(self, setting: str):
        js = self.get_settings_json()
        try:
            return js[setting]
        except:
            return ''


    def get_settings_json(self) -> dict:
        with open(self.settingsfile, 'a', encoding='utf-8'):
            pass
        with open(self.settingsfile, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except:
                return {}


    def setting(self, prompt: str, setting: str):
        value = self.get_setting(setting)
        if value == '':
            print(prompt)
            value = input()
            self.save_setting(setting, value)
        return value


    def load_logfile(self) -> list[dict]:
        logs = []
        try:
            with open(self.logfile, 'r', encoding='utf-8') as f:
                objects = map(lambda x: json.loads(x), f.readlines())
                logs.extend(list(objects))
        except FileNotFoundError:
            pass
        return logs


    def file_exists(self, id: str, titles: dict[str, str], filetypes: list[str]) -> bool:
        if id not in titles: return False
        filename = parse_text.get_valid_filename(titles[id])
        files = list(map(lambda x: os.path.join(self.downloadfolder, filename + '.' + x.lower()), filetypes))
        for file in files:
            if not os.path.exists(file):
                return False
        return True
