"""File operations go here."""

import configparser
import datetime
import getpass
import importlib
import importlib.metadata
import json
import os

from ao3downloader import parse_text, strings


class FileOps:
    def __init__(self):
        self.logfile = os.path.join(strings.LOG_FOLDER_NAME, strings.LOG_FILE_NAME)
        self.inifile = strings.INI_FILE_NAME
        self.settingsfile = strings.SETTINGS_FILE_NAME
        self.downloadfolder = strings.DOWNLOAD_FOLDER_NAME


    def initialize(self) -> None:
        if not os.path.exists(strings.LOG_FOLDER_NAME): os.mkdir(strings.LOG_FOLDER_NAME)
        if not os.path.exists(self.downloadfolder): os.mkdir(self.downloadfolder)
        if not os.path.exists(self.inifile):
            with importlib.resources.open_text(strings.SETTINGS_FOLDER_NAME, self.inifile) as f:
                with open(self.inifile, 'w', encoding='utf-8') as ini_file:
                    ini_file.write(f.read())
        if (self.get_ini_value_boolean(strings.INI_PASSWORD_SAVE, False) == False):
            self.save_setting(strings.SETTING_PASSWORD, None)


    def update_ini(self) -> None:
        with open(self.inifile, 'r', encoding='utf-8') as l: 
            local = l.read()
        with importlib.resources.open_text(strings.SETTINGS_FOLDER_NAME, self.inifile) as r: 
            remote = r.read()
        ini_differences = self.ini_differences(local, remote)
        if ini_differences: self.save_new_ini(ini_differences)


    def ini_differences(self, local: str, remote: str) -> str:
        local_config = configparser.ConfigParser()
        local_config.read_string(local)
        remote_config = configparser.ConfigParser()
        remote_config.read_string(remote)
        local_config_structure = {section: set(local_config.options(section)) for section in local_config.sections()}
        remote_config_structure = {section: set(remote_config.options(section)) for section in remote_config.sections()}
        return self.ini_differences_str(local_config_structure, remote_config_structure)


    def ini_differences_str(self, local: dict[str, set[str]], remote: dict[str, set[str]]) -> str:
        if local == remote: return None
        message = strings.MESSAGE_INI_DIFFERENCES
        for section in local:
            if section not in remote:
                message += strings.MESSAGE_INI_REMOVED_SECTION.format(section)
                local.pop(section, None)
        for section in remote:
            if section not in local:
                message += strings.MESSAGE_INI_ADDED_SECTION.format(section)
                remote.pop(section, None)
        if local or remote:
            all_sections = set(local.keys()).union(remote.keys())
            for section in all_sections:
                local_keys = local.get(section, set())
                remote_keys = remote.get(section, set())
                added_keys = remote_keys - local_keys
                removed_keys = local_keys - remote_keys
                for key in added_keys:
                    message += strings.MESSAGE_INI_ADDED_KEY.format(key, section)
                for key in removed_keys:
                    message += strings.MESSAGE_INI_REMOVED_KEY.format(key, section)
        return message


    def save_new_ini(self, ini_differences: str) -> None:
        package_version = importlib.metadata.version('ao3downloader')
        new_inifile = f'settings-v{package_version}.ini'
        if not os.path.exists(new_inifile):
            with importlib.resources.open_text(strings.SETTINGS_FOLDER_NAME, self.inifile) as f:
                with open(new_inifile, 'w', encoding='utf-8') as ini_file:
                    ini_file.write(f.read())
            print(strings.MESSAGE_INI_FILE_CHANGED.format(new_inifile))
            print(ini_differences)


    def write_log(self, log: dict) -> None:
        log['timestamp'] = datetime.datetime.now().strftime(strings.TIMESTAMP_FORMAT)
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


    def setting(self, prompt: str, setting: str, save: bool = True, sensitive: bool = False) -> str:
        value = self.get_setting(setting)
        if value == '':
            print(prompt)
            if sensitive:
                value = getpass.getpass()
            else:
                value = input()
            if save:
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


    def file_exists(self, id: str, titles: dict[str, list[str]], filetypes: list[str], maximum: int) -> bool:
        if id not in titles: return False
        filename = parse_text.get_valid_filename(titles[id], maximum)
        files = list(map(lambda x: os.path.join(self.downloadfolder, filename + parse_text.get_file_type(x)), filetypes))
        for file in files:
            if not os.path.exists(file):
                return False
        return True


    def get_ini_value(self, key: str, fallback: str = None) -> str:
        config = configparser.ConfigParser()
        config.read(self.inifile)
        return config.get(strings.INI_SECTION_NAME, key, fallback=fallback)


    def get_ini_value_boolean(self, key: str, fallback: bool) -> bool:
        config = configparser.ConfigParser()
        config.read(self.inifile)
        return config.getboolean(strings.INI_SECTION_NAME, key, fallback=fallback)


    def get_ini_value_integer(self, key: str, fallback: int) -> int:
        config = configparser.ConfigParser()
        config.read(self.inifile)
        return config.getint(strings.INI_SECTION_NAME, key, fallback=fallback)
