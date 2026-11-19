"""Updating the Windows, Mac or Linux app from inside itself: the page's **Update now**.

Only the packaged app can do this (`desktop.py` sets `Handler.updater`) - it is the one copy
that is a folder of files on someone's computer, installed from a GitHub release. A helper run
any other way answers the update endpoints 404, and its page never shows the button.

What happens, in order:

1. `latest` asks GitHub for the repository's latest release and finds this app's zip -
   `ficfairy-ao3downloader-windows.zip`, on a Mac the one for its chip, or on Linux the one for its machine. It has to be newer than this
   app, or nothing happens.
2. `install` downloads it into `update/` beside the program and checks it: against the SHA-256
   GitHub publishes for the file, and entry by entry - every file has to land inside the
   app's own folder (a symlink too, wherever it points), and the zip has to hold the program
   and its `_internal/`. Anything wrong and nothing is touched.
3. It unpacks it into `update/new/` - keeping each file's permissions and each symlink, which
   the Mac and Linux apps need - writes the swap script, starts it detached, and closes the app.
4. The script waits for the app to be gone, moves each top-level item of the old app into
   `update/previous/` and the new one in its place, and starts the app again. If a move fails
   it puts every old item back first, so the app that starts is always a whole one - the new
   version, or the old one it was. It writes what it did to `update/update.log`, which the
   restarted app reads (`last_result`) so the page can say an update failed.

The swap is PowerShell on Windows (`SWAP_SCRIPT`) and bash on a Mac (`MAC_SWAP_SCRIPT`), and
the two write the same log lines. On a Mac the app lives in a Terminal window, so the script
starts it again by opening `Start FicFairy.command` in a new one.

`config/` and `logs/` are never moved: they are not in the zip, and the script skips them by
name as well. So an update never touches the user's settings.ini - the restarted app adds any
new setting to it, and comments out any the new version dropped (`desktop.settings_up_to_date`).
"""

import hashlib
from urllib.parse import urlsplit
import os
import re
import stat
import subprocess
import sys
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from source_code.fileio import trim_file

import requests

ASSET_NAME = 'ficfairy-ao3downloader-windows.zip'
# the folder the zip unpacks into: every entry has to be inside it
ZIP_ROOT = 'ficfairy'
# what each release zip's name starts with (package_app.ZIP_PREFIX); the folder inside is ZIP_ROOT
ASSET_PREFIX = 'ficfairy-ao3downloader'
EXE_NAME = 'ficfairy.exe'
MAC_PROGRAM = 'ficfairy'
# what a Mac is started by - the script the swap reopens in Terminal (package_app.MAC_LAUNCHER)
MAC_LAUNCHER = 'Start FicFairy.command'
# which Mac zip is this Mac's: the same names package_app builds them under
MAC_CHIPS = {'arm64': 'apple-silicon', 'x86_64': 'intel'}
# what starts the app on Linux, which the swap runs again (package_app.LINUX_LAUNCHER)
LINUX_LAUNCHER = 'Start FicFairy.sh'
# Linux builds, named by machine; anything else has no published build to update from
LINUX_MACHINES = {'x86_64': 'x86_64', 'amd64': 'x86_64'}
# left by the Mac swap for the app it starts: a Terminal window opened by `open` gets none of
# the script's environment, so this says what AO3DOWNLOADER_NO_BROWSER says on Windows - the
# page is still open, and reloads itself
RESTARTED_MARKER = 'restarted'
UPDATE_FOLDER = 'update'
# never moved or replaced: the user's, not the app's
KEPT = ('config', 'logs', UPDATE_FOLDER)
GITHUB_API = 'https://api.github.com'
# where a real release's zip may come from: the link GitHub's answer gives is on github.com, and
# GitHub sends the download itself from one of its own githubusercontent.com hosts
RELEASE_LINK_HOST = 'github.com'
DOWNLOAD_HOST_SUFFIX = '.githubusercontent.com'
# a stand-in for GitHub's api, so an update can be tried end to end without a real release -
# the Windows build does exactly that. only ever set by whoever starts the app
ENV_UPDATE_SOURCE = 'AO3DOWNLOADER_UPDATE_SOURCE'
SCRIPT_NAME = 'apply-update.ps1'
MAC_SCRIPT_NAME = 'apply-update.sh'
LOG_NAME = 'update.log'
# what the swap script itself printed, errors included
OUTPUT_NAME = 'swap-output.txt'
PYINSTALLER_RESET = 'PYINSTALLER_RESET_ENVIRONMENT'
DOWNLOAD_NAME = 'download.zip'
TIMEOUT_SECONDS = 60
# the response to the page has to get out before the app closes
EXIT_DELAY_SECONDS = 1.5

# while any of these, a run may not start - the app is about to close
BUSY = ('checking', 'downloading', 'restarting')

VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')


class UpdateError(Exception):
    """An update that cannot go ahead, and why - said to the page as it is."""


@dataclass
class Release:
    version: str
    download: str
    # sha256 of the zip, as GitHub publishes it for each file of a release; '' if it did not
    digest: str
    size: int


def version_parts(text: str) -> tuple[int, int, int] | None:
    match = VERSION.match(str(text or '').strip())
    return tuple(int(x) for x in match.groups()) if match else None


def is_newer(candidate: str, current: str) -> bool:
    a, b = version_parts(candidate), version_parts(current)
    return bool(a and b and a > b)


@dataclass
class Kind:
    """What an update looks like on one system: which zip, which program must be in it, and
    how the swap script is written and started."""

    asset: str
    program: str
    script_name: str
    script: str
    encoding: str
    # macos or linux for the bash swap, which starts the app again differently on each
    system: str = ''

    def command(self, script: Path, app_dir: Path, pid: int) -> list[str]:
        if self.script_name == SCRIPT_NAME:
            return ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                    '-WindowStyle', 'Hidden', '-File', str(script),
                    '-AppDir', str(app_dir), '-ProcessId', str(pid)]
        # the same bash script on a Mac and on Linux, told which, since each restarts the app
        # its own way
        return ['/bin/bash', str(script), str(app_dir), str(pid), self.system]


def kind_for(platform: str | None = None, machine: str | None = None) -> Kind | None:
    """This system's update, or None where the app has none."""

    platform = platform or sys.platform
    if platform == 'win32':
        return Kind(ASSET_NAME, EXE_NAME, SCRIPT_NAME, SWAP_SCRIPT, 'utf-8-sig')
    if platform == 'darwin':
        import platform as machines
        chip = MAC_CHIPS.get(machine or machines.machine())
        if not chip: return None
        return Kind(f'{ASSET_PREFIX}-macos-{chip}.zip', MAC_PROGRAM, MAC_SCRIPT_NAME, MAC_SWAP_SCRIPT, 'utf-8',
                    'macos')
    if platform.startswith('linux'):
        import platform as machines
        arch = LINUX_MACHINES.get((machine or machines.machine()).lower())
        if not arch: return None
        return Kind(f'{ASSET_PREFIX}-linux-{arch}.zip', MAC_PROGRAM, MAC_SCRIPT_NAME, MAC_SWAP_SCRIPT, 'utf-8',
                    'linux')
    return None


def entry_parts(name: str) -> tuple[str, ...]:
    return PurePosixPath(name.replace('\\', '/')).parts


def is_link(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def check_zip(archive: zipfile.ZipFile, program: str = EXE_NAME) -> None:
    """Refuse a zip that is not this app, or that would write anywhere but the app's folder -
    through a symlink as much as through a name."""

    names = archive.namelist()
    for info in archive.infolist():
        name = info.filename
        path = PurePosixPath(name.replace('\\', '/'))
        # a ':' anywhere is refused too: on Windows a part like 'C:' jumps to another drive
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != ZIP_ROOT \
                or any(':' in part for part in path.parts):
            raise UpdateError(f'the download has a file where it should not be ({name}) - '
                              'not installing it')
        if is_link(info):
            # a link is only ever to a sibling inside the app: never absolute, never climbing
            # out of the folder it sits in
            target = archive.read(info).decode('utf-8', errors='replace')
            depth = len(path.parts) - 2
            climbs = 0
            for part in PurePosixPath(target).parts:
                climbs = climbs + 1 if part == '..' else climbs - (part not in ('.', ''))
                if climbs > depth: break
            if PurePosixPath(target).is_absolute() or climbs > depth or ':' in target:
                raise UpdateError(f'the download has a link pointing out of the app ({name}) - '
                                  'not installing it')
    if f'{ZIP_ROOT}/{program}' not in names:
        raise UpdateError(f'the download has no {program} - not installing it')
    if not any(name.startswith(f'{ZIP_ROOT}/_internal/') for name in names):
        raise UpdateError('the download has no _internal folder - not installing it')


def unpack(archive: zipfile.ZipFile, destination: Path) -> None:
    """Everything under the zip's top folder into `destination`, except anything under a
    folder that is the user's - a zip that carried one would otherwise replace it.

    Each file keeps the permissions it was zipped with, and a symlink is made as a symlink:
    `ZipFile.extract` does neither, and the Mac and Linux apps need both - its program must stay
    executable, and PyInstaller's Mac build links parts of its folder to each other.
    `check_zip` has already refused a link pointing anywhere else."""

    for info in archive.infolist():
        parts = entry_parts(info.filename)[1:]
        if not parts or parts[0] in KEPT: continue
        target = destination.joinpath(*parts)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if is_link(info):
            os.symlink(archive.read(info).decode('utf-8'), target)
            continue
        with archive.open(info) as source, open(target, 'wb') as out:
            while chunk := source.read(1024 * 1024):
                out.write(chunk)
        mode = (info.external_attr >> 16) & 0o777
        if mode and sys.platform != 'win32':
            target.chmod(mode)


def system_environment(environment: dict | None = None) -> dict:
    """The environment for a program of the system's own - a browser, a terminal - started
    from the frozen app.

    On Linux PyInstaller points LD_LIBRARY_PATH at the app's own libraries, keeping what it was
    in LD_LIBRARY_PATH_ORIG, and a system program handed that loads the app's copies of
    libraries in place of its own - a browser or terminal built against newer ones then fails
    to start. Put back as it was; nothing else is touched."""

    environment = dict(os.environ if environment is None else environment)
    if not getattr(sys, 'frozen', False) or sys.platform == 'win32': return environment
    for name in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
        original = environment.pop(f'{name}_ORIG', None)
        if original: environment[name] = original
        else: environment.pop(name, None)
    return environment


def launch_environment() -> dict:
    """What the swap script, and the app it starts again, run with.

    A frozen app hands its children PyInstaller's own variables (`_PYI_*`), and PyInstaller
    says to reset them when starting another frozen program - the relaunched exe would
    otherwise take them as its own. The script sets the flag again before it starts the app.
    The library path is the system's, since the script runs system programs (`system_environment`)."""

    environment = system_environment()
    environment[PYINSTALLER_RESET] = '1'
    return environment


def update_log_limit() -> int:
    """`UpdateLogMaxMB` from settings.ini, in bytes (0: no limit)."""

    from source_code.fileio import FileOps, megabytes
    from source_code import strings
    return megabytes(FileOps().get_ini_value_integer(strings.INI_UPDATE_LOG_MAX_MB,
                                                     strings.INI_DEFAULT_UPDATE_LOG_MAX_MB))


def launch_detached(command: list[str], output: Path | None = None) -> None:
    """Start the swap script so it outlives this process, with no window of its own.

    What it prints goes to `output`: a script that will not even start - refused by policy,
    or failing to parse - never reaches its own log, and would otherwise leave no trace."""

    flags = 0
    detach = {}
    if sys.platform == 'win32':
        # a hidden console of its own rather than none: Windows PowerShell started with no
        # console at all (DETACHED_PROCESS) was seen to end before running a single line
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        # a session of its own, so closing the app's Terminal window does not take it along
        detach = {'start_new_session': True}
    sink = open(output, 'ab') if output else subprocess.DEVNULL
    try:
        subprocess.Popen(command, creationflags=flags, close_fds=True, env=launch_environment(),
                         stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT, **detach)
    finally:
        if output: sink.close()


class Updater:
    """Everything the update endpoints need, for one running app."""

    def __init__(self, app_dir: str, version: str, repository: str,
                 get: Callable = requests.get,
                 launch: Callable[..., None] = launch_detached,
                 leave: Callable[[], None] = lambda: os._exit(0),
                 kind: Kind | None = None,
                 log_limit: Callable[[], int] | None = None):
        self.app_dir = Path(app_dir)
        # how large update.log and swap-output.txt may grow (`UpdateLogMaxMB`), in bytes
        self.log_limit = log_limit or update_log_limit
        # Windows, unless told otherwise: desktop.make_updater passes this system's
        self.kind = kind or kind_for('win32')
        self.version = version
        self.repository = repository
        self.get = get
        self.launch = launch
        self.leave = leave
        self.lock = threading.Lock()
        self.source = (os.environ.get(ENV_UPDATE_SOURCE) or GITHUB_API).rstrip('/')
        # what the page is told: idle, downloading, restarting, or failed with why
        self.state: dict = {'state': 'idle'}
        self.trim_logs()
        failure = self.last_result()
        if failure: self.state = {'state': 'failed', 'error': failure}

    @property
    def update_dir(self) -> Path:
        return self.app_dir / UPDATE_FOLDER

    def busy(self) -> bool:
        """Whether an update is under way - asked before a run may start."""

        with self.lock:
            return self.state.get('state') in BUSY

    def claim(self) -> bool:
        """Mark an update as under way, unless one already is. The helper calls this under the
        same lock it starts runs under, so a run and an update can never both begin."""

        with self.lock:
            if self.state.get('state') in BUSY: return False
            self.state = {'state': 'checking'}
            return True

    def status(self) -> dict:
        with self.lock:
            return {'version': self.version, 'updatable': True, 'update': dict(self.state)}

    def trim_logs(self) -> None:
        """Drop the oldest lines of the update logs once they pass `UpdateLogMaxMB` - as the
        app starts and before each update, since the swap scripts only ever add to them."""

        try:
            limit = self.log_limit()
        except Exception:
            return
        for name in (LOG_NAME, OUTPUT_NAME):
            try:
                trim_file(self.update_dir / name, limit)
            except Exception:
                pass

    def last_result(self) -> str:
        """Why the last update failed, if the swap script said it did - read as the app
        starts again, so the page can say so rather than wait for a version that never came."""

        log = self.update_dir / LOG_NAME
        try:
            lines = [x for x in log.read_text(encoding='utf-8', errors='replace').splitlines() if x.strip()]
        except OSError:
            return ''
        # the log keeps every update's lines; only the latest outcome counts
        outcome = next((x for x in reversed(lines) if 'update failed' in x or 'swapped' in x), '')
        if 'update failed' not in outcome: return ''
        return outcome.split('update failed', 1)[1].strip(' :-') or 'the update did not complete'

    def latest(self) -> Release:
        url = f'{self.source}/repos/{self.repository}/releases/latest'
        try:
            response = self.get(url, headers={'Accept': 'application/vnd.github+json'},
                                timeout=TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise UpdateError(f'could not reach GitHub to find the latest version ({e})') from e
        if response.status_code != 200:
            raise UpdateError(f'GitHub did not say what the latest version is ({response.status_code})')
        release = response.json()
        version = str(release.get('tag_name') or '').removeprefix('v')
        if not version_parts(version):
            raise UpdateError(f"the latest release is not a version this app understands ({version or 'none'})")
        asset = next((a for a in release.get('assets') or [] if a.get('name') == self.kind.asset), None)
        if not asset or not asset.get('browser_download_url'):
            raise UpdateError(f'the latest release, {version}, has no {self.kind.asset}')
        download = str(asset['browser_download_url'])
        digest = str(asset.get('digest') or '')
        # a stand-in source is on this computer, set up by whoever started the app; the real
        # thing is held to GitHub's own https hosts and to the checksum GitHub publishes
        if self.source == GITHUB_API:
            if not download.startswith('https://'):
                raise UpdateError('the download is not over https - not fetching it')
            if host_of(download) != RELEASE_LINK_HOST:
                raise UpdateError(f'the download is not on {RELEASE_LINK_HOST} - not fetching it')
            owner = owner_of(self.repository)
            if not released_by(download, owner):
                raise UpdateError(f"the download is not one of {owner}'s releases on GitHub - not fetching it")
            if not digest.startswith('sha256:'):
                raise UpdateError(f'GitHub published no checksum for {self.kind.asset} - not installing it')
        return Release(version=version, download=download,
                       digest=digest.removeprefix('sha256:') if digest.startswith('sha256:') else '',
                       size=int(asset.get('size') or 0))

    def begin(self) -> Release:
        """Check there is a newer version and start installing it in the background, once
        `claim`ed. Returns the release; raises UpdateError - and stands down - when there is
        nothing to do or it cannot."""

        try:
            return self.start_install()
        except Exception as e:
            # whatever went wrong - an answer from GitHub that is not what it should be, say -
            # the updater stands down, or it would refuse every run until the app restarted
            with self.lock:
                self.state = {'state': 'idle'}
            if isinstance(e, UpdateError): raise
            raise UpdateError(f'could not start the update ({e})') from e

    def start_install(self) -> Release:
        release = self.latest()
        if not is_newer(release.version, self.version):
            raise UpdateError(f'this is already the latest version ({self.version})')
        try:
            self.update_dir.mkdir(exist_ok=True)
            probe = self.update_dir / '.writable'
            probe.write_text('', encoding='utf-8')
            probe.unlink()
        except OSError as e:
            raise UpdateError(f'the app cannot write to its own folder ({self.app_dir}) - if it '
                              'is somewhere protected, like Program Files or Applications, move '
                              'it to your own folders and start it from there') from e
        with self.lock:
            self.state = {'state': 'downloading', 'version': release.version}
        threading.Thread(target=self.install, args=(release,), daemon=True).start()
        return release

    def install(self, release: Release) -> None:
        try:
            archive_path = self.download(release)
            new = self.update_dir / 'new'
            if new.exists(): remove_tree(new)
            with zipfile.ZipFile(archive_path) as archive:
                check_zip(archive, self.kind.program)
                unpack(archive, new)
            script = self.update_dir / self.kind.script_name
            script.write_text(self.kind.script, encoding=self.kind.encoding, newline='\n'
                              if self.kind.script_name == MAC_SCRIPT_NAME else None)
            with self.lock:
                self.state = {'state': 'restarting', 'version': release.version}
            print(f'updating to {release.version}: the app will close and start again in a moment')
            if self.kind.script_name == MAC_SCRIPT_NAME:
                print('it opens in a new window - this one can be closed once it has')
            self.trim_logs()
            self.launch(self.kind.command(script, self.app_dir, os.getpid()),
                        self.update_dir / OUTPUT_NAME)
            threading.Timer(EXIT_DELAY_SECONDS, self.leave).start()
        except Exception as e:
            message = str(e) if isinstance(e, UpdateError) else f'the update failed ({e})'
            print(f'update: {message}')
            with self.lock:
                self.state = {'state': 'failed', 'version': release.version, 'error': message}

    def download(self, release: Release) -> Path:
        target = self.update_dir / DOWNLOAD_NAME
        digest = hashlib.sha256()
        size = 0
        try:
            with self.get(release.download, stream=True, timeout=TIMEOUT_SECONDS) as response:
                if response.status_code != 200:
                    raise UpdateError(f'the download failed ({response.status_code})')
                # GitHub redirects the link to where the file is kept; it has to end up on
                # GitHub's own hosts, never somewhere a redirect was talked into
                landed = getattr(response, 'url', None)
                if self.source == GITHUB_API and isinstance(landed, str) and not github_host(host_of(landed)):
                    raise UpdateError('the download was sent somewhere other than GitHub - not installing it')
                with open(target, 'wb') as out:
                    for chunk in response.iter_content(1024 * 1024):
                        if not chunk: continue
                        out.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
        except requests.RequestException as e:
            raise UpdateError(f'the download failed ({e})') from e
        if release.size and size != release.size:
            raise UpdateError(f'the download came out {size} bytes, not {release.size} - not installing it')
        if release.digest and digest.hexdigest().lower() != release.digest.lower():
            raise UpdateError('the download does not match the checksum GitHub published for it '
                              '- not installing it')
        return target


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or '').lower()


def owner_of(repository: str) -> str:
    """The account a repository belongs to: `alexandria-p` of `alexandria-p/FicFairy`."""

    return repository.split('/')[0].strip().lower()


def released_by(url: str, owner: str) -> bool:
    """Whether a link is a release file of one of `owner`'s own repositories -
    `https://github.com/<owner>/<repo>/releases/download/<tag>/<file>` and nothing else. The
    repository's name is not held to the one this app was built with, so a renamed repository
    (GitHub answers for the old name) still updates; the account is."""

    parts = urlsplit(url).path.split('/')
    return (bool(owner) and len(parts) >= 7 and parts[0] == '' and parts[1].lower() == owner
            and bool(parts[2]) and parts[3] == 'releases' and parts[4] == 'download')


def github_host(host: str) -> bool:
    return host == RELEASE_LINK_HOST or host.endswith(DOWNLOAD_HOST_SUFFIX)


def remove_tree(path: Path) -> None:
    for child in sorted(path.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        child.rmdir() if child.is_dir() and not child.is_symlink() else child.unlink()
    path.rmdir()


# Written into update/ and run by powershell once the app has closed. Windows PowerShell 5.1
# is on every Windows 10 and 11, so it is the one thing this can rely on being there. It never
# touches config/, logs/ or update/, and puts every old item back if any move fails, so the app
# it starts again is always a whole one.
SWAP_SCRIPT = r'''param(
    [Parameter(Mandatory = $true)] [string] $AppDir,
    [Parameter(Mandatory = $true)] [int] $ProcessId
)

$ErrorActionPreference = 'Stop'
$update = Join-Path $AppDir 'update'
$new = Join-Path $update 'new'
$previous = Join-Path $update 'previous'
$log = Join-Path $update 'update.log'
$kept = @('config', 'logs', 'update')

function Say([string] $message) {
    Add-Content -LiteralPath $log -Value ((Get-Date).ToString('u') + ' ' + $message)
}

# a file can stay locked for a moment after its process has gone - an antivirus scan, say -
# so a move is tried again for a while. whatever a failed attempt left at the destination is
# cleared first: where a rename is refused, a move can fall back to copying, and a half-made
# copy would otherwise make every later attempt fail on it
function Move-Carefully([string] $from, [string] $to) {
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        try {
            if (Test-Path -LiteralPath $to) { Remove-Item -LiteralPath $to -Recurse -Force }
            Move-Item -LiteralPath $from -Destination $to
            return
        }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if (Test-Path -LiteralPath $to) { Remove-Item -LiteralPath $to -Recurse -Force }
    Move-Item -LiteralPath $from -Destination $to
}

try {
    Say "waiting for the app (process $ProcessId) to close"
    try { Wait-Process -Id $ProcessId -Timeout 60 -ErrorAction Stop } catch { }

    if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Recurse -Force }
    New-Item -ItemType Directory -Path $previous | Out-Null

    $names = @(Get-ChildItem -LiteralPath $new -Force | ForEach-Object { $_.Name } |
        Where-Object { $kept -notcontains $_ })
    $moved = @()
    $placed = @()
    try {
        foreach ($name in $names) {
            $target = Join-Path $AppDir $name
            if (Test-Path -LiteralPath $target) {
                Move-Carefully $target (Join-Path $previous $name)
                $moved += $name
            }
            Move-Carefully (Join-Path $new $name) $target
            $placed += $name
        }
    }
    catch {
        Say "could not swap the files ($_) - putting the old ones back"
        foreach ($name in $placed) {
            Remove-Item -LiteralPath (Join-Path $AppDir $name) -Recurse -Force -ErrorAction SilentlyContinue
        }
        foreach ($name in $moved) {
            Move-Item -LiteralPath (Join-Path $previous $name) -Destination (Join-Path $AppDir $name) -ErrorAction SilentlyContinue
        }
        throw
    }

    Say "swapped $($names -join ', ')"
    Remove-Item -LiteralPath $previous -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $new -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $update 'download.zip') -Force -ErrorAction SilentlyContinue
}
catch {
    Say "update failed: $_"
}
finally {
    # started again whether the swap worked or not - the new version, or the whole old one.
    # the page is still open in the browser and reloads itself, so no second tab
    $env:AO3DOWNLOADER_NO_BROWSER = '1'
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    Start-Process -FilePath (Join-Path $AppDir 'ficfairy.exe') -WorkingDirectory $AppDir
    Say 'started the app again'
}
'''


# Written into update/ and run by bash once the app has closed - the Mac's and Linux's
# SWAP_SCRIPT, doing
# the same things in the same order and writing the same log lines, so `last_result` reads
# either. A rename on the same disk cannot be half-done, so it needs none of the retrying the
# Windows one does for locked files; it still puts every old item back if any move fails.
# The app runs in Terminal on a Mac, so it is started again by opening its launcher, in a new
# window - which gets none of this script's environment, hence the marker file. On Linux the
# launcher itself finds a terminal to open, or runs the app straight where there is no desktop.
MAC_SWAP_SCRIPT = r'''#!/bin/bash
APP_DIR="$1"
APP_PID="$2"
# macos or linux: each starts the app again its own way
SYSTEM="${3:-macos}"
UPDATE="$APP_DIR/update"
NEW="$UPDATE/new"
PREVIOUS="$UPDATE/previous"
LOG="$UPDATE/update.log"

say() { printf '%s %s\n' "$(date -u '+%Y-%m-%d %H:%M:%SZ')" "$1" >> "$LOG"; }

start_again() {
    # the page is still open and reloads itself, so the app must not open a second tab
    touch "$UPDATE/restarted"
    if [ "$SYSTEM" = linux ]; then
        # the launcher opens a terminal of its own where there is a desktop, and runs the app
        # straight where there is none; a session of its own so nothing here takes it along.
        # the old app's window set AO3DOWNLOADER_IN_TERMINAL, and this script has it - left
        # set, the launcher would run the app with no window to show it in
        unset AO3DOWNLOADER_IN_TERMINAL
        if setsid -f "$APP_DIR/Start FicFairy.sh" > /dev/null 2>&1 < /dev/null; then
            say 'started the app again'
        else
            say 'could not start the app again - run Start FicFairy.sh'
        fi
    elif open -a Terminal "$APP_DIR/Start FicFairy.command"; then
        say 'started the app again'
    else
        say 'could not start the app again - double-click Start FicFairy.command'
    fi
}

say "waiting for the app (process $APP_PID) to close"
for _ in $(seq 1 120); do
    kill -0 "$APP_PID" 2>/dev/null || break
    sleep 0.5
done

rm -rf "$PREVIOUS"
if ! mkdir -p "$PREVIOUS"; then
    say "update failed: could not make $PREVIOUS"
    start_again
    exit 0
fi

moved=()
placed=()
failure=''
while IFS= read -r -d '' item; do
    name="$(basename "$item")"
    case "$name" in config|logs|update) continue ;; esac
    if [ -e "$APP_DIR/$name" ] || [ -L "$APP_DIR/$name" ]; then
        if ! mv "$APP_DIR/$name" "$PREVIOUS/$name"; then failure="could not move $name aside"; break; fi
        moved+=("$name")
    fi
    if ! mv "$NEW/$name" "$APP_DIR/$name"; then failure="could not move the new $name in"; break; fi
    placed+=("$name")
done < <(find "$NEW" -mindepth 1 -maxdepth 1 -print0)

if [ -n "$failure" ]; then
    say "could not swap the files ($failure) - putting the old ones back"
    for name in "${placed[@]}"; do rm -rf "${APP_DIR:?}/$name"; done
    for name in "${moved[@]}"; do mv "$PREVIOUS/$name" "$APP_DIR/$name"; done
    say "update failed: $failure"
else
    names="$(IFS=,; echo "${placed[*]}")"
    say "swapped ${names//,/, }"
    rm -rf "$PREVIOUS" "$NEW" "$UPDATE/download.zip"
fi
start_again
'''
