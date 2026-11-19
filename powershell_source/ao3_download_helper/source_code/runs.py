"""One json file per run: what it set out to do, and what became of it.

Separate from `logs/log.jsonl`, which records individual requests and is written for
debugging. This is the run as a whole - which button, which settings, which fics it touched
and how it ended - and is what the history page reads.

**The file is written when the run starts, not when it ends.** A record still saying
`running` after the helper has gone is how an interrupted run is recognised: a run killed
mid-flight cannot write its own epitaph, so the absence of an ending is the evidence.
"""

import datetime
import json
import time
import os

from source_code import strings
from source_code.ao3 import index_gaps


# how a run ended. 'running' is also the state a run is left in when it never got to
# finish - see the module docstring.
STATUS_RUNNING = 'running'
STATUS_SUCCESS = 'success'
STATUS_FAILED = 'failed'
# ended as it should, but some of its indexing broke off - a listing that stopped on an
# error, a collection listing, a fic whose page would not read. what it did is kept and
# counted; it is never a floor for a quick scan, and Retry can carry on from the gap
STATUS_PARTIAL = 'partial'
STATUS_STOPPED = 'stopped'
# a background run the helper ended because it was left paused too long. ended the same way a
# stop ends one - everything saved is kept - and, like a stopped run, it can be resumed
STATUS_ABANDONED = 'abandoned'
# a run that never wrote its ending - the page left, or the helper stopped - once the page
# has checked the helper is not still working on it. the helper never writes this itself
STATUS_INTERRUPTED = 'interrupted'

# How often a line of console output takes the record to disk.
#
# The whole file is rewritten on every save, and for a library in Dropbox that is an upload of
# a file that grows to hundreds of kilobytes - so a line saves the record only once this long
# has passed since the last save. Time alone decides, not a count of lines: a slow step (an
# index walk held up by ao3's rate limit prints a few lines an hour) must still reach disk, and
# a fast one must not upload the file every few seconds. Checkpoints, answered questions and
# the run ending save at once whatever this says.
#
# The trigger is a line arriving: nothing saves on a timer, so a run killed outright loses the
# lines of its last stretch this long, however quiet it was afterwards.
LOG_FLUSH_SECONDS = 120

# A run over a large library prints a line per fic per format, so this is a ceiling rather
# than an expectation; most runs never approach it. The **last** lines are kept when it is
# reached, because whatever went wrong is at the end.
LOG_MAX_LINES = 5000
# the range `RunLogMaxLines` is kept to: a log much shorter says too little, and a much longer
# one is rewritten whole on every save (an upload of it, in Dropbox)
LOG_MIN_LINES = 500
LOG_MOST_LINES = 50000
# with `KeepLogsOfRecentRunsOnly`, how many of the newest records keep their logs
RECENT_RUN_LOGS = 100


def log_max_lines(value) -> int:
    """A run log's length, kept in range; anything unreadable is the default."""

    try:
        n = int(value)
    except (TypeError, ValueError):
        return LOG_MAX_LINES
    if n <= 0: return LOG_MAX_LINES
    return min(LOG_MOST_LINES, max(LOG_MIN_LINES, n))


def now() -> str:
    """The moment, to the second, **in UTC and marked so** (`+00:00`), in a form that sorts and
    survives a file name. Every time the app writes is UTC - the hosted helper's clock and the
    reader's need not share a zone, and a run's `started`/`finished` are read by a page that
    shows them in the reader's own. Records written before this carry naive local times,
    which the page reads as local, as it always did."""

    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def file_stamp(stamp: str) -> str:
    """A UTC time as a run file's name starts with it: `20261103T101542Z`, ISO 8601's basic
    form. It sorts by time, carries its zone as the standard `Z`, has nothing a file system or
    Dropbox could object to, and sorts after every older name (`2026-11-03T...`, local time),
    since a digit sorts after `-` - so the newest run is the last name, whichever wrote it."""

    at = datetime.datetime.fromisoformat(stamp).astimezone(datetime.timezone.utc)
    return at.strftime('%Y%m%dT%H%M%SZ')


def shown(stamp: str, zone=None) -> str:
    """A recorded (UTC) time as a run's own lines say it: in the person's AO3 zone when the run
    was given one, named - `2026-11-03 21:15 Australia/Sydney` - else `YYYY-MM-DD HH:MM UTC`. An
    older record's naive local time is said as it was written."""

    text = str(stamp or '')
    try:
        at = datetime.datetime.fromisoformat(text)
    except ValueError:
        return text[:16].replace('T', ' ')
    if at.tzinfo is None: return text[:16].replace('T', ' ')
    if zone is not None:
        return f"{at.astimezone(zone).strftime('%Y-%m-%d %H:%M')} {zone_name(zone)}"
    return at.astimezone(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def zone_name(zone) -> str:
    """A zone as a line names it: its IANA name (`Australia/Sydney`)."""

    return str(getattr(zone, 'key', None) or zone)


def snapshot(record: 'RunRecord') -> dict:
    """A copy of a record's data as it stands, safe to send while its run goes on.

    The run's thread appends to the log as this copies it, so the log is copied first, in
    one step, and the rest after; a copy that meets a dict changing under it tries again.
    """

    for _ in range(3):
        try:
            data = dict(record.data)
            data['log'] = list(data.get('log') or [])
            return json.loads(json.dumps(data))
        except RuntimeError:
            # a dict in it (the progress, say) changed size mid-copy; the next try sees it whole
            continue
    return json.loads(json.dumps(dict(record.data)))


def stamped(text: str) -> str:
    """One line of a run's log as it is kept: the moment it was said, then what was said.

    Stamped when the line is said, not when it is saved - a log is saved in batches, and a
    line held until the record exists would otherwise carry the record's time. In UTC, and
    marked so: a log is read alongside other people's, and the hosted helper's clock is not
    the reader's - a local time with no zone cannot be lined up with anything.
    """

    return f'[{utc_now()} UTC] {text}'


def utc_now() -> str:
    """The moment in UTC, to the second, as a log line writes it."""

    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


class RunRecord:
    """What one run did, written as it happens.

    Every method swallows its own errors. A history file is a convenience, and a run that
    downloaded a library successfully must not be reported as failed because a note about
    it could not be written.
    """

    def __init__(self, fileops, job_id: str, action: str, action_name: str,
                 filetypes: list[str], options: dict,
                 printed: list[str] | None = None,
                 settings: dict | None = None, background: bool = False,
                 helper: str = '', url: str = '', username: str = '') -> None:
        self.fileops = fileops
        # where the run keeps its issues and fic lists as it goes - the downloader, handed
        # over once the run has one (`run_job`). read on every save, so an interrupted run's
        # record is as current as its log rather than empty until an ending it never reaches
        self.source = None
        # lines counted since the last write, not since the run began, and when that was
        self.unsaved = 0
        self.last_saved = float('-inf')
        # set once the run is force stopped: the page writes the record's ending itself, and
        # a run thread still stuck somewhere must not wake later and write over it
        self.frozen = False
        self.path = os.path.join(
            fileops.runsfolder, f'{file_stamp(now())}-{job_id[:8]}.json')
        self.data: dict = {
            'id': job_id,
            'action': action,
            'actionName': action_name,
            'started': now(),
            'finished': None,
            'status': STATUS_RUNNING,
            'filetypes': list(filetypes),
            'options': dict(options or {}),
            # the link the run was pointed at - a collection, or a fic - so History can start
            # the same run again without it being typed in. empty for the runs that work
            # their link out from the username
            'url': url or '',
            # the ao3 account the run logged in as - which library was read, whose bookmarks,
            # and whose session lapsed when one did. the username alone: the password is never
            # handed to the record, so it cannot end up in a history file
            'username': username or '',
            # a run the helper carried on with after the page closed, reaching Dropbox itself
            'background': bool(background),
            # the helper the page started it on, as the page names it (its address). a page
            # talking to another helper - the one on this computer, say, while the hosted one
            # runs this - must not take this run for an interrupted one of its own
            'helper': helper,
            # what settings.ini said at the time. it decides pacing, file naming and
            # retries, so a run cannot be explained afterwards without it - and which
            # settings.ini was in force depends on where the helper was started from,
            # which is why the path it was read from is part of this
            'settings': dict(settings or {}),
            # the fics this run touched, and in which way. kept apart because they answer
            # different questions: what got a fresh index entry, what arrived as a file,
            # and what replaced a copy that was already there.
            'reindexed': [],
            'downloaded': [],
            'updated': [],
            # anything the run stopped to ask, and what was answered
            'choices': [],
            'failures': [],
            'skipped': [],
            # new copies downloaded while the older copy could not be safely deleted
            'keptCopies': [],
            # formats taken from FicHub that may be older cached copies (`Ao3.fichub_older`)
            'fichubOlder': [],
            # Resolve issues' repairs not done because the name they would give was taken
            'repairClashes': [],
            # older copies of a work the run decided to remove, and what became of each:
            # `pending` until the cleanup step, then `removed`, or `kept` with the reason.
            # written the moment they are marked, so a run that dies first still says which
            'removals': [],
            # everything the run printed, in order - the same account the modal shows,
            # kept because the modal is gone once the tab is closed. every line starts with
            # when it was said (`stamped`); `printed` arrives stamped already, by `run_job`
            'log': list(printed or []),
            # how many lines had to be dropped to stay under the ceiling, so a trimmed log
            # says so rather than silently beginning in the middle
            'logTrimmed': 0,
            'error': '',
            # the moment the login succeeded - what a later quick scan measures back to. a
            # resumed run carries the first attempt's, since it is finishing that run's work
            'baseline': None,
            # the run this one picks up from, and the first attempt of the chain it belongs to
            'resumes': None,
            'resumesFirst': None,
            # how far the run got, written as it goes, so it can be resumed - see helper_files/RESUMING.md
            'progress': {},
        }
        self.save()

    def logged_in(self, baseline: str, resumes: str | None = None,
                  first: str | None = None) -> None:
        self.data['baseline'] = baseline
        if resumes:
            self.data['resumes'] = resumes
            self.data['resumesFirst'] = first or resumes
        self.save()

    def checkpoint(self, **fields) -> None:
        """Record how far the run has got. Written straight away: a checkpoint that waits
        for a batch is one an interrupted run never gets to write."""

        try:
            self.data['progress'].update(fields)
        except Exception:
            return
        self.save()

    def save(self) -> None:
        if self.frozen: return
        try:
            if self.source is not None: self.collect(self.source())
        except Exception:
            pass
        try:
            # through the library's own storage, so a run writing to Dropbox keeps its
            # history there too, beside the works it describes
            self.fileops.write_text(self.path, json.dumps(self.data, indent=2))
            self.unsaved = 0
            self.last_saved = time.monotonic()
        except Exception:
            # a note about the run is not worth taking the run down for
            pass

    def line(self, text: str) -> None:
        """Keep one line of console output, writing to disk in batches.

        Not saved per line on purpose: `save` rewrites the whole file, so a run printing a
        line per fic per format would rewrite a growing file thousands of times. A line
        saves the record once `LOG_FLUSH_SECONDS` have passed since the last save; a run killed
        outright loses what it said since then, and everything else - a stop, a failure, a
        finish - goes through `save` anyway.
        """

        try:
            log = self.data['log']
            log.append(stamped(text))
            most = getattr(self, 'max_lines', LOG_MAX_LINES)
            if len(log) > most:
                # the end is where whatever went wrong is, so the start is what gives way
                dropped = len(log) - most
                del log[:dropped]
                self.data['logTrimmed'] += dropped
            self.unsaved += 1
            if time.monotonic() - self.last_saved >= LOG_FLUSH_SECONDS:
                self.save()
        except Exception:
            pass

    def choice(self, entry: dict) -> None:
        """Record something the run stopped to ask, and what came back."""

        how = getattr(self, 'pending_how', None)
        self.pending_how = None
        # how it was answered - by you, or a default and why - unless the caller says itself
        self.data['choices'].append({'at': now(), **({'how': how} if how else {}), **entry})
        self.save()

    def amend_choice(self, fields: dict) -> None:
        """Add what came of the last answer to it, once the run has acted on it.

        The choice itself is written the moment it is answered, so a run that dies while
        acting on it still shows what was decided; this fills in the outcome afterwards.
        """

        try:
            if not self.data['choices']: return
            self.data['choices'][-1].update(fields)
            self.save()
        except Exception:
            pass

    def removals(self, items: list[dict]) -> None:
        """Record the older copies marked for removal, or what has since become of them."""

        try:
            self.data['removals'] = [{k: v for k, v in x.items() if k != 'path'} for x in items]
            self.save()
        except Exception:
            pass

    def collect(self, ao3) -> None:
        """Take the fic lists off the downloader that has been gathering them."""

        if ao3 is None: return
        self.data['reindexed'] = sorted(ao3.reindexed)
        self.data['downloaded'] = sorted(ao3.downloaded)
        self.data['updated'] = sorted(ao3.updated)
        self.data['failures'] = list(ao3.failures)
        rescued = getattr(ao3, 'rescued', None)
        self.data['rescued'] = list(rescued) if isinstance(rescued, list) else []
        self.data['skipped'] = list(ao3.skipped_works)
        kept = getattr(ao3, 'kept_copies', None)
        self.data['keptCopies'] = list(kept) if isinstance(kept, list) else []
        older = getattr(ao3, 'fichub_older', None)
        self.data['fichubOlder'] = list(older) if isinstance(older, list) else []
        clashes = getattr(ao3, 'repair_clashes', None)
        self.data['repairClashes'] = list(clashes) if isinstance(clashes, list) else []
        # where indexing broke off - which listing or collection, which pages were read,
        # which failed, how far back in date it got
        self.data['indexFailures'] = index_gaps(ao3)
        # every format of every work saved whole, this attempt and any it carries on from - so
        # a retry carrying on from this one fetches only what is still missing
        saved = getattr(ao3, 'saved_formats', None)
        if isinstance(saved, dict) and saved:
            done = self.data['progress'].setdefault('formatsDone', {})
            for work, formats in saved.items():
                done[work] = sorted(set(done.get(work) or []) | {str(x) for x in formats})

    def finish(self, status: str, error: str = '') -> None:
        self.data['status'] = status
        self.data['error'] = error
        self.data['finished'] = now()
        self.save()


def read_runs(fileops, limit: int = 100, with_log: bool = False) -> list[dict]:
    """Every run on record, newest first - `iter_runs`, read to the end."""

    return list(iter_runs(fileops, limit, with_log))


def iter_runs(fileops, limit: int = 100, with_log: bool = False, names=None):
    """The runs on record, newest first, read one at a time as they are asked for.

    A caller that stops early - `last_successful` at the first floor, usually the newest
    record - reads only that far. In Dropbox every record is a download through the page, so
    reading all `limit` of them first cost a quick scan most of a minute before it began.
    `names` narrows it to those file names (`find_run`).

    A file that cannot be read is skipped rather than ending the listing - one damaged
    record should not hide the history around it.

    **The console log is left out by default.** A record can hold thousands of lines, and a
    hundred of them in one response would be tens of megabytes to build a page that does not
    show them. `logLines` says how many the file holds, so the listing can still mention it;
    the lines themselves are in the file.
    """

    folder = fileops.runsfolder
    if names is None:
        try:
            names = fileops.list_files(folder)
        except Exception:
            return

    found = 0
    for name in sorted(names, reverse=True):
        if not name.lower().endswith('.json'): continue
        try:
            record = json.loads(fileops.read_text(os.path.join(folder, name)))
        except Exception:
            continue
        if not isinstance(record, dict): continue
        record['file'] = name
        if not with_log:
            record['logLines'] = len(record.get('log') or [])
            record.pop('log', None)
        yield record
        found += 1
        if found >= limit: break


def prune_old_logs(fileops, keep: int = RECENT_RUN_LOGS) -> int:
    """Take the log out of every run record older than the `keep` newest, and say how many.

    The record stays - History lists it, a retry and a quick scan's floor read it - only its
    `log` goes, with `logPruned` saying how many lines it had. Newest first, and it stops at
    the first record already pruned: everything older was pruned by an earlier run, so a run
    usually reads one record here, not hundreds (in Dropbox each read is a download). The
    first time, it walks every older record once. Swallows its own errors.
    """

    pruned = 0
    try:
        names = sorted((name for name in fileops.list_files(fileops.runsfolder)
                        if name.lower().endswith('.json')), reverse=True)
    except Exception:
        return 0
    for name in names[keep:]:
        path = os.path.join(fileops.runsfolder, name)
        try:
            record = json.loads(fileops.read_text(path))
        except Exception:
            continue
        if not isinstance(record, dict): continue
        if 'logPruned' in record: break
        if record.get('status') == STATUS_RUNNING: continue
        record['logPruned'] = len(record.get('log') or [])
        record['log'] = []
        try:
            fileops.write_text(path, json.dumps(record, indent=2))
            pruned += 1
        except Exception:
            continue
    return pruned


def baseline_of(record: dict) -> str:
    """When a run's reach begins: the moment its login succeeded, or - for a resumed run -
    the first attempt's. Older records have no baseline, and their start is the nearest."""

    return str(record.get('baseline') or record.get('started') or '')


def find_run(fileops, run_id: str) -> dict | None:
    """One run's record by its id, with the name of the file it is in."""

    if not run_id: return None
    # every run file's name ends with the first 8 of its id, so only those are read - not the
    # whole folder, which in Dropbox is a download per record. a name that does not follow it
    # (none has, but a hand-renamed file might) is still found by reading the rest
    try:
        names = fileops.list_files(fileops.runsfolder)
    except Exception:
        return None
    suffix = f'-{run_id[:8]}.json'.lower()
    named = [name for name in names if name.lower().endswith(suffix)]
    for candidates in (named, [name for name in names if name not in named]):
        for record in iter_runs(fileops, limit=100000, names=candidates):
            if str(record.get('id') or '') == run_id: return record
    return None


def amend_run(fileops, name: str, fields: dict) -> None:
    """Add fields to another run's record - how a run it resumed is told so."""

    try:
        path = os.path.join(fileops.runsfolder, name)
        record = json.loads(fileops.read_text(path))
        record.update(fields)
        fileops.write_text(path, json.dumps(record, indent=2))
    except Exception:
        pass


def last_successful(fileops, match=None, statuses=(STATUS_SUCCESS,)) -> dict | None:
    """The most recent run that actually finished, or None if there has never been one.

    What 'up to the last run' means for a quick scan. A run that failed, was stopped, or
    was interrupted is **not** a floor to index down to: it may have stopped before
    reaching fics that were updated before it started, and trusting it would leave exactly
    those unseen.

    `match` narrows it to the runs that are a floor at all. Finishing is not enough on its
    own: most runs cover only part of the listing, so a successful one says nothing about
    works it was never looking at. It takes a record and answers whether that run qualifies,
    rather than a list of action names, because whether a run covered everything can depend
    on the options it ran with and not only on which button it was. The caller decides -
    this module deliberately knows nothing about what any of that means. `statuses` widens
    which endings count - a quick scan's floor also takes a partly finished run, by rules
    `match` holds.
    """

    # read newest first, stopping at the first that qualifies - usually the newest record
    for record in iter_runs(fileops):
        if record.get('status') not in statuses: continue
        if match is not None and not match(record): continue
        return record
    return None
