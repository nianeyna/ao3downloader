"""A local helper that lets the web ui run downloads.

A browser cannot reach ao3 (no CORS headers), cannot hold an ao3 login session, and cannot
read the ebook files on disk that the update scan needs. So the page asks this instead, and
this calls the same code the console menu calls.

By default it listens on the loopback interface only, so nothing outside this machine can
reach it, and it holds the ao3 password just long enough to log in - it is never written
anywhere. It can also be hosted on a server for one person's own use, and then it answers
nobody without a passcode and takes the login only encrypted - see `access.py`.
"""

import contextlib
import datetime
import io
import json
import math
import os
import queue
import re
import socket
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from source_code import access, dropbox_library, exceptions, fichub, settings_file, indexing, naming, parse_soup, parse_text, progress, runs, strings, updater as updates
from source_code.actions import shared
from source_code.ao3 import REASON_MAINTENANCE, SORT_DATE_SELECTORS, failure_reason, Ao3, index_gaps, was_bookmark
from source_code.fileio import FileOps
from source_code.repo import Repository
from source_code.storage import PageStorage


HOST = '127.0.0.1'
DEFAULT_PORT = 4400
# a hosted helper listens on all interfaces, on the port its host names. `PORT` is the name
# most hosts use
ENV_HOST = 'AO3DOWNLOADER_HOST'
ENV_PORT = 'PORT'
# the helper's own public address, which the host sets. see `keep_awake`
ENV_EXTERNAL_URL = 'RENDER_EXTERNAL_URL'
# a free hosted service may be stopped after about 15 minutes without a request from outside
KEEP_AWAKE_SECONDS = 10 * 60
# how often the helper looks at its background runs - for one paused too long, and for
# whether it is time to keep itself awake
WATCH_SECONDS = 30

# a full walk of the whole bookmarks listing. thorough and slow.
ACTION_BOOKMARKS = 'bookmarks'
ACTION_UPDATE = 'update'
ACTION_COLLECTIONS = 'collections'

ACTION_COLLECTION = 'collection'

# stops indexing at the first bookmark it already holds, so a routine run costs a request
# or two rather than a walk of the whole library
ACTION_NEW = 'new'
# the one to reach for: new bookmarks, then the unfinished ones, then the formats missing
# from everything else
ACTION_SYNC = 'sync'
# one fic, by link or work number
ACTION_WORK = 'work'
# several fics, pasted as links or work numbers - the single-fic run over a list
ACTION_WORKS = 'works'
# works whose files were found in your library with no index entry: the several-fics run over
# them, marking each `from_import`, fetching only what is missing unless told to replace what
# is outdated, and never overwriting a copy that is current
ACTION_IMPORT = 'import'
# the full scan with its parts made optional
ACTION_CUSTOM = 'custom'
# a full scan's shape, but stopping at the works ao3 has not touched since the last run
# that actually finished
ACTION_QUICK = 'quick'

# how long a run waits between checks for an answer to a question it has asked. short
# enough that a stop is noticed quickly, long enough not to spin.
ANSWER_POLL_SECONDS = 0.25

# how often the event stream says something even when the run has not, so a page that has
# gone away is noticed - a write to a closed connection is the only way to find out
STREAM_HEARTBEAT_SECONDS = 10

# how long a run waits for the page to answer a request about the library. long, because a
# large file on its way to Dropbox can take minutes; a page that has gone is caught sooner
# by PAGE_GRACE_SECONDS
STORAGE_TIMEOUT_SECONDS = 15 * 60

# how long a run carries on waiting with no page connected at all. a page reconnecting after
# a blip is given this long to come back before the run gives up on it
PAGE_GRACE_SECONDS = 30

# how long a question waits altogether before giving up and taking its default. a browser
# tab closed without stopping the run would otherwise leave this thread waiting for an
# answer that can never arrive. Long enough that nobody who stepped away loses their place.
ANSWER_TIMEOUT_SECONDS = 30 * 60

# What a quick scan should measure back to when no run qualifies as a floor but the index
# already holds something. Asked rather than decided: reading the whole listing is hours on
# a large library, and going by when the index was last written is a guess only the person
# who built that index can judge.
QUICK_QUESTION = 'quick-floor'
QUICK_SINCE_INDEX = 'since'
QUICK_FULL = 'full'
QUICK_CHOICES = (QUICK_SINCE_INDEX, QUICK_FULL)

# What to do about older copies of a work sitting beside the newest one used to be asked here
# ('duplicates': leave them, or keep only the newest). It is retired: a run never deletes a copy
# it did not replace - one with only a guessed date, or none, was called 'older' and could go on
# a guess - and says at its end how many works still have more than one copy of a format, for
# Resolve issues to sort (`note_duplicate_copies`). See `RETIRED_QUESTIONS`.
DUPLICATES_QUESTION = 'duplicates'

# Whether to ask FicHub for the works ao3 would not give us. Asked once the run has tried
# everything on ao3, before the cleanup. **The one question whose default does something**:
# the person who set this up asked for yes, because the works in question are already
# missing and FicHub only adds - nothing on disk is lost by trying, and a run nobody is
# watching (a background run, a closed tab) should still come back with what it can get.
FICHUB_QUESTION = 'fichub'
FICHUB_YES = 'yes'
FICHUB_NO = 'no'
FICHUB_CHOICES = (FICHUB_YES, FICHUB_NO)

# questions no longer asked. a page from before still sends answers, defaults and waits for
# them, and they are passed over rather than refusing the run: 'fichub-outdated' asked whether
# to take a format FicHub only had an older copy of - it is now taken unasked, and warned about
RETIRED_QUESTIONS = frozenset({'fichub-outdated', DUPLICATES_QUESTION})

# Whether an overwriting run should replace a copy on disk with a version **older** than it
# (the date in the file's name is later than the version about to be written). Asked per
# work, naming the formats. Defaults to **no**: replacing a newer copy with an older one
# loses something, and a run nobody answers must not do that on its own.
OVERWRITE_OLDER_QUESTION = 'overwrite-older'
OVERWRITE_OLDER_YES = 'yes'
OVERWRITE_OLDER_NO = 'no'
OVERWRITE_OLDER_CHOICES = (OVERWRITE_OLDER_YES, OVERWRITE_OLDER_NO)

# Whether a file already in the library replaces a copy of a work **the index had no entry
# for when the run began** - so nothing but the copy's own name says which version it holds.
# Asked per work, naming the formats, whether or not the run overwrites, for a file from AO3
# or from FicHub alike (`ask_about_unindexed_copies`). The run *recommends* an answer from the
# date it reads in each copy's name, and says why, but the default is always **no**: on a
# timeout, a background run, a stop, or no answer, what you have is kept. Never answered up
# front, never from settings.ini, and never reused from an earlier attempt - each work is its own.
UNINDEXED_COPY_QUESTION = 'unindexed-copy'
UNINDEXED_COPY_YES = 'yes'
UNINDEXED_COPY_NO = 'no'
# only some of a work's copies recommended for replacing: replace just those
UNINDEXED_COPY_RECOMMENDED = 'recommended'
# keep every copy, and save the incoming version beside them as a new file - offered when a copy
# has no date written the app's way and the incoming version has a date (see `KEEP_BOTH`)
UNINDEXED_COPY_BOTH = 'both'
UNINDEXED_COPY_CHOICES = (UNINDEXED_COPY_RECOMMENDED, UNINDEXED_COPY_YES, UNINDEXED_COPY_NO,
                          UNINDEXED_COPY_BOTH)
# Whether a file whose name carries **no date in the app's own form** - a date only guessed
# from its name the way *Infer date* reads one, or none at all - is replaced by an incoming
# version, from AO3 or FicHub, overwriting or not. Only a date in the app's own form is ever
# trusted to replace a file unasked. Asked per work and **scenario** (`SCENARIOS`), each with
# its own default (keep, unless changed in settings.ini or the page) and, when you ticked
# *always* on one, a standing answer the page sends with every run (`alwaysAnswers`).
INFERRED_DATE_QUESTION = 'inferred-date'
INFERRED_DATE_YES = 'yes'
INFERRED_DATE_NO = 'no'
# **Keep both**: keep the file, and save the incoming version beside it as a new file. Offered
# only when the incoming version has a date: its file is then named with it, so it can never
# land on a file whose name has no date written the app's way
INFERRED_DATE_BOTH = 'both'
INFERRED_DATE_CHOICES = (INFERRED_DATE_YES, INFERRED_DATE_NO, INFERRED_DATE_BOTH)
# a format to fetch beside its copy rather than in place of it: `superseded` names it with no
# path, so the download is saved and `replace_superseded` has nothing to remove
KEEP_BOTH = ''
SCENARIO_OLDER = 'older'
SCENARIO_NEWER = 'newer'
SCENARIO_UNKNOWN = 'unknown'
# where the incoming version comes from, and what the guessed date says of the file
SCENARIOS = tuple(f'{side}-{case}' for side in ('ao3', 'fichub')
                  for case in (SCENARIO_OLDER, SCENARIO_NEWER, SCENARIO_UNKNOWN))
SCENARIO_SETTINGS = dict(zip(SCENARIOS, (
    strings.INI_AO3_GUESSED_OLDER_ANSWER, strings.INI_AO3_GUESSED_NEWER_ANSWER,
    strings.INI_AO3_UNKNOWN_DATE_ANSWER, strings.INI_FICHUB_GUESSED_OLDER_ANSWER,
    strings.INI_FICHUB_GUESSED_NEWER_ANSWER, strings.INI_FICHUB_UNKNOWN_DATE_ANSWER)))

# Whether a retry that carries on downloading (`resumed_scope`: the earlier attempt had got as far
# as checking its files) reads each of those works again from AO3 first. Asked once per run, never
# per file. The entries are the earlier attempt's, so a work AO3 updated in between would be
# downloaded and named with the older date the index holds; re-reading costs one request a work.
# Defaults to no, and can be answered for good (`ALWAYS_KINDS`).
RETRY_REREAD_QUESTION = 'retry-reread'
RETRY_REREAD_NO = 'no'
RETRY_REREAD_YES = 'yes'
RETRY_REREAD_CHOICES = (RETRY_REREAD_NO, RETRY_REREAD_YES)
# the questions an answer can be kept for, to be taken without asking (`Job.always_answers`)
ALWAYS_KINDS = frozenset(SCENARIOS) | {RETRY_REREAD_QUESTION}

# questions asked about one work at a time: an earlier attempt's answer was about another work
ASKED_PER_WORK = {UNINDEXED_COPY_QUESTION, INFERRED_DATE_QUESTION} | set(SCENARIOS)

# how each question was answered, kept with the answer in the run's history (`how`)
ANSWERED_BY_YOU = 'answered'
ANSWERED_TIMED_OUT = 'timed-out'
ANSWERED_NOT_ASKED = 'not-asked'
ANSWERED_BACKGROUND_DEFAULT = 'background-default'
ANSWERED_UP_FRONT = 'up-front'
ANSWERED_EARLIER = 'earlier'
ANSWERED_STOPPED = 'stopped'
# an answer you chose to always use for that scenario (`Job.always_answers`)
ANSWERED_ALWAYS = 'always'
# a per-work question: an earlier one went unanswered, so this one took its default at once
ANSWERED_NOBODY = 'nobody-answering'

# every choice any question may be answered with. the run reads only the answer to the
# question it actually asked, so one list is enough to keep nonsense out at the door
ANSWER_CHOICES = QUICK_CHOICES + FICHUB_CHOICES + \
    (UNINDEXED_COPY_RECOMMENDED,)
# which choices belong to which question - a background run is answered up front, by name
CHOICES_FOR = {QUICK_QUESTION: QUICK_CHOICES,
               FICHUB_QUESTION: FICHUB_CHOICES,
               OVERWRITE_OLDER_QUESTION: OVERWRITE_OLDER_CHOICES,
               UNINDEXED_COPY_QUESTION: UNINDEXED_COPY_CHOICES,
               INFERRED_DATE_QUESTION: INFERRED_DATE_CHOICES,
               RETRY_REREAD_QUESTION: RETRY_REREAD_CHOICES}

# which settings.ini key holds each question's default answer
ANSWER_SETTING_FOR = {QUICK_QUESTION: strings.INI_QUICK_FLOOR_ANSWER,
                      FICHUB_QUESTION: strings.INI_FICHUB_ANSWER,
                      OVERWRITE_OLDER_QUESTION: strings.INI_OVERWRITE_OLDER_ANSWER,
                      RETRY_REREAD_QUESTION: strings.INI_RETRY_REREAD_ANSWER,
                      **SCENARIO_SETTINGS}


def setting_integer(key: str, fallback: int, minimum: int = 0) -> int:
    """A whole-number setting from settings.ini, or `fallback` when it cannot be read.
    Never below `minimum`: a time limit of 0 would give up before anything was tried."""

    try:
        value = FileOps().get_ini_value_integer(key, fallback)
    except Exception:
        return fallback
    return max(minimum, value) if isinstance(value, int) else fallback


def question_timeout_seconds() -> float:
    """How long a question waits for its answer (`QuestionTimeoutMinutes`); 0 is at once."""

    return setting_integer(strings.INI_QUESTION_TIMEOUT, ANSWER_TIMEOUT_SECONDS // 60) * 60


def unsure_question_timeout_seconds() -> float:
    """How long a question about a file without the app's own date waits
    (`GuessedDateQuestionTimeoutMinutes`, 1 by default); 0 is at once."""

    return setting_integer(strings.INI_UNSURE_QUESTION_TIMEOUT,
                           strings.INI_DEFAULT_UNSURE_QUESTION_TIMEOUT) * 60


# the questions with a wait of their own (`timeout_minutes_for`); every other waits
# `QuestionTimeoutMinutes`
TIMEOUT_SETTING_FOR = {
    'inferred-date': (strings.INI_UNSURE_QUESTION_TIMEOUT, strings.INI_DEFAULT_UNSURE_QUESTION_TIMEOUT),
    'overwrite-older': (strings.INI_OVERWRITE_OLDER_TIMEOUT, ANSWER_TIMEOUT_SECONDS // 60),
    'unindexed-copy': (strings.INI_UNINDEXED_COPY_TIMEOUT, ANSWER_TIMEOUT_SECONDS // 60),
}


def timeout_minutes_for(name: str) -> int:
    """How many minutes the question `name` waits, as settings.ini says: its own setting where
    it has one (`TIMEOUT_SETTING_FOR`), else `QuestionTimeoutMinutes`."""

    key, fallback = TIMEOUT_SETTING_FOR.get(name, (strings.INI_QUESTION_TIMEOUT, ANSWER_TIMEOUT_SECONDS // 60))
    return setting_integer(key, fallback)


def nobody_here_setting() -> bool:
    """`NobodyHereTakeDefaults` (on unless settings.ini says false): once a question goes
    unanswered, the rest of its kind in the run take their default without waiting."""

    try:
        return bool(FileOps().get_ini_value_boolean(strings.INI_NOBODY_HERE, True))
    except Exception:
        return True


def run_log_lines(job) -> int:
    """How many lines this run's log keeps: the hosted page's own choice sent with the run,
    else settings.ini's `RunLogMaxLines`, kept to `runs.LOG_MIN_LINES`..`LOG_MOST_LINES`."""

    chosen = getattr(job, 'run_log_max_lines', None)
    if chosen is None:
        chosen = setting_integer(strings.INI_RUN_LOG_MAX_LINES, runs.LOG_MAX_LINES)
    return runs.log_max_lines(chosen)


def keeps_recent_logs_only(job) -> bool:
    """Whether only the most recent runs keep their logs (`KeepLogsOfRecentRunsOnly`, on
    unless settings.ini says false, or the hosted page's own choice sent with the run)."""

    chosen = getattr(job, 'trim_old_run_logs', None)
    if chosen is not None: return bool(chosen)
    try:
        return bool(FileOps().get_ini_value_boolean(strings.INI_TRIM_OLD_RUN_LOGS, True))
    except Exception:
        return True


def run_log_settings(lines, trim) -> tuple[int | None, bool | None]:
    """The run-log choices a hosted page's User settings sent with a run, checked before it
    starts. Neither sent leaves settings.ini's."""

    if lines is not None and (isinstance(lines, bool) or not isinstance(lines, int)
                              or not runs.LOG_MIN_LINES <= lines <= runs.LOG_MOST_LINES):
        raise ValueError(f'a run log keeps a whole number of lines, '
                         f'{runs.LOG_MIN_LINES} to {runs.LOG_MOST_LINES}')
    if trim is not None and not isinstance(trim, bool):
        raise ValueError('keeping only the most recent runs\' logs is true or false')
    return lines, trim


def configured_answer(name: str, builtin: dict, chosen: str | None = None) -> dict:
    """The default a question takes when nobody answers it, as settings.ini says.

    Only the choice changes; anything else the built-in default carries (the undated
    question's empty date) is kept. A value the question does not offer is ignored, so a
    typo in settings.ini leaves the built-in default - the one that was chosen on purpose.
    """

    key = ANSWER_SETTING_FOR.get(name)
    if not key: return dict(builtin)
    if chosen in strings.INI_ANSWER_CHOICES.get(key, ()):
        # the run's own, from the page's User settings, comes before settings.ini's
        return {**builtin, 'choice': chosen}
    try:
        choice = FileOps().get_ini_value(key, '').strip().lower()
    except Exception:
        return dict(builtin)
    if choice not in strings.INI_ANSWER_CHOICES.get(key, ()): return dict(builtin)
    return {**builtin, 'choice': choice}

# a background run keeps every event for a page that reattaches, but not every line it
# printed: hours of 'new download:' would be megabytes replayed to a page that shows the
# last few hundred. the older lines are dropped from what is replayed, never from the run
BACKGROUND_KEPT_MESSAGES = 1000

ACTIONS = (ACTION_BOOKMARKS, ACTION_UPDATE, ACTION_COLLECTIONS, ACTION_COLLECTION,
           ACTION_NEW, ACTION_SYNC, ACTION_WORK, ACTION_WORKS, ACTION_CUSTOM, ACTION_QUICK,
           ACTION_IMPORT)

# actions that need a link from the caller rather than working it out from the username
ACTIONS_NEEDING_URL = (ACTION_COLLECTION, ACTION_WORK, ACTION_WORKS, ACTION_IMPORT)

# the runs pointed at fics by hand. a fic they index that is not your bookmark is marked
# as having come in by its link (`from_link`)
FIC_ACTIONS = (ACTION_WORK, ACTION_WORKS, ACTION_IMPORT)

# every run may be told not to log in (`skipLogin`). these still need a username without
# one, because they read your own bookmarks or collections listing, found by your name -
# logged out, ao3 shows only what anyone may see there, so private works and bookmarks are
# missed. the rest need nothing: an update run works from the index, a collection run from
# its link, a fic run from its fics
USERNAME_ACTIONS = (ACTION_BOOKMARKS, ACTION_NEW, ACTION_SYNC, ACTION_CUSTOM, ACTION_QUICK,
                    ACTION_COLLECTIONS)

# the most fics one 'several fics' run takes. a paste of a whole library belongs to a scan
MAX_WORK_LINKS = 500
# an import has no limit, at the owner's request: it names every unindexed work found in a
# library, which can be a great many - one request each, so a long run, but one run
# the fic runs that look up a list of fics and can carry on fic by fic
LIST_ACTIONS = (ACTION_WORKS, ACTION_IMPORT)

# the two collection runs. On their own they write only the collections' files; asked to
# (`collectionWorks`) they index every work they meet as well, and download those
COLLECTION_ACTIONS = (ACTION_COLLECTIONS, ACTION_COLLECTION)

# The runs whose overwrite choice is the caller's to make. Refetching a copy nothing says is
# out of date is the answer to a damaged file, and it costs a request per format per work -
# so it belongs to the two runs that are pointed at a library and told to spend more on it,
# and nowhere else. ACTION_WORK is absent on purpose: it always overwrites, and `run_work`
# sets that itself rather than taking it from the request.
OVERWRITE_ACTIONS = (ACTION_BOOKMARKS, ACTION_CUSTOM)

# The runs that may also check every non-bookmark in the index for updates - the works it
# holds only because they were found through something else, such as another work's series.
# The three scans, and only while they index: re-reading a work writes its index entry, which
# a custom run told to skip indexing has ruled out.
NON_BOOKMARK_ACTIONS = (ACTION_BOOKMARKS, ACTION_QUICK, ACTION_CUSTOM)

# The runs that can be picked up where an earlier attempt left off - see helper_files/RESUMING.md. The
# three scans and the two collection runs; the rest are short enough that starting again is
# the resume.
RESUME_ACTIONS = (ACTION_BOOKMARKS, ACTION_QUICK, ACTION_CUSTOM,
                  ACTION_COLLECTIONS, ACTION_COLLECTION)

# how an earlier run can be retried - see helper_files/RESUMING.md:
# - TOP: the same run again from its first step, answering its questions afresh - a quick scan
#   over the same window it had (its floor, up to when it first started)
# - REINDEX: its indexing again from the first page of every listing - nothing taken from the
#   earlier attempt but its window and the answers it was given
# - INDEX: carrying on with its indexing - walks it finished taken from the index, one that
#   broke off going on from where it stopped - then checking and downloading, passing over the
#   formats it already saved
# - REDOWNLOAD: its downloads again from the first work it had settled on, every format
# - DOWNLOADS: carrying on with its downloads - the works it had settled on, fetching only the
#   formats it had not yet saved whole: none of a work it finished, the rest of one it was
#   partway through, all of one it never reached
# - FAILED: only the works it could not get, and only their formats still missing
RETRY_TOP = 'top'
RETRY_REINDEX = 'reindex'
RETRY_INDEX = 'index'
RETRY_REDOWNLOAD = 'redownload'
RETRY_DOWNLOADS = 'downloads'
RETRY_FAILED = 'failed'
RETRY_MODES = (RETRY_TOP, RETRY_REINDEX, RETRY_INDEX, RETRY_REDOWNLOAD, RETRY_DOWNLOADS,
               RETRY_FAILED)
# the fic runs: retried by the fics they name, not by a listing
FIC_ACTIONS = (ACTION_WORK, ACTION_WORKS, ACTION_IMPORT)

# json is always produced, so the ui shows it ticked and locked. it is what the web page
# reads, and it costs nothing extra: the metadata comes off the listing page that has to be
# fetched anyway, rather than one request per work.
FORCED_FILETYPES = [strings.AO3_DOWNLOAD_TYPE_METADATA]

# ticked when the dialog opens, but free to untick. html is here rather than above because
# it costs a request per work on top of the indexing, so a metadata-only refresh - which is
# a great deal lighter on the rate limit - has to be possible.
DEFAULT_FILETYPES = [strings.AO3_DOWNLOAD_TYPE_METADATA, 'HTML']


def resolve_filetypes(requested, force: bool = True) -> list[str]:
    """Keep the recognised types the caller asked for, and add the ones we always produce.

    The ui shows the forced types ticked and locked, but a request is not to be trusted to
    have honoured that, so they are re-added here.

    `force` is the one exception: a run that is not going to index cannot produce json,
    because json *is* the index. Adding it back there would report a file type the run
    never writes, which is worse than not offering it.
    """

    filetypes: list[str] = []
    for filetype in (requested or []):
        # a repeat would download the same work twice, for nothing but rate limit
        if filetype in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA \
                and filetype not in filetypes:
            filetypes.append(filetype)
    if force:
        for forced in FORCED_FILETYPES:
            if forced not in filetypes: filetypes.append(forced)
    return filetypes


def resolve_options(requested) -> dict:
    """The questions the console menu asks after the file types, with the same defaults.

    'pages' is the page to stop on, where 0 means all of them - the wording the console
    uses. Ao3 wants None for that, which is done at the point of use.
    """

    given = requested or {}

    try:
        pages = int(given.get('pages') or 0)
    except (TypeError, ValueError):
        pages = 0
    if pages < 0: pages = 0

    try:
        start = int(given.get('start') or 1)
    except (TypeError, ValueError):
        start = 1
    if start < 1: start = 1
    # a stop before the start would fetch nothing at all; treat it as no stop instead
    if pages and pages < start: pages = 0

    return {
        'start': start,
        'pages': pages,
        'series': bool(given.get('series')),
        # a collections run also indexing, and downloading, every work in the collections
        'collectionWorks': bool(given.get('collectionWorks')),
        # a collections run also reading each collection's subcollections, and its parent -
        # any number of steps away, each collection at most once
        'subcollections': bool(given.get('subcollections')),
        'parentCollections': bool(given.get('parentCollections')),
        'images': bool(given.get('images')),
        'workdates': bool(given.get('workdates')),
        # fetch every requested format again, however current the copy on disk looks. the
        # answer to a damaged or truncated file, which no version check can see: the name
        # and the date are both right and only the bytes are wrong.
        'overwrite': bool(given.get('overwrite')),
        # an import: replace a copy you have when ao3 has a newer version. off, an import
        # fetches only the formats you do not have and leaves every copy you have alone
        'replaceOutdated': bool(given.get('replaceOutdated')),
        # an import: the works among its links to index only, with no format fetched - looked
        # up for their missing index entry, and not among the works chosen to update
        'indexOnly': work_numbers(given.get('indexOnly')),
        # check every non-bookmark in the index for updates too. a listing of your bookmarks
        # never shows them, so without this they are only read again when something else
        # brings the run to them. not narrowed by a date range or a floor: see
        # `update_non_bookmarks`
        'nonBookmarks': bool(given.get('nonBookmarks')),
        # a custom run can work from what is already indexed rather than reading ao3's
        # listing again. it defaults to indexing, because a run that quietly skipped it
        # would judge everything against however stale the index happened to be.
        'reindex': given.get('reindex') is not False,
        # a custom run covers *either* a slice of the listing or a window of time, never
        # both: one picks works by where they sit in the listing and the other by when ao3
        # last touched them, and a run cannot be walking a listing and not walking it.
        'dates': bool(given.get('dates')),
        # the order a custom run reads your bookmarks listing in, for a slice of pages or a
        # date range: by when you bookmarked each work, or by when ao3 last updated it. '' is
        # each shape's own order as it always was - see `listing_order`
        'order': given.get('order') if given.get('order') in LISTING_ORDERS else '',
        # a custom run skipping the indexing may still look every indexed work up on AO3, one
        # at a time, and judge its files against what AO3 says now (`rechecks`) rather than
        # against the index as it stands
        'recheck': bool(given.get('recheck')),
        # any run may go without logging in - see USERNAME_ACTIONS for what it still needs
        'skipLogin': bool(given.get('skipLogin')),
        # a typed range: the page sends each end as the UTC moment it begins (from) or ends
        # (to) in the person's AO3 zone, and it is kept so. `range_day` dates it in that zone
        # again before AO3's dates are compared. a bare date (an older page) is kept as one
        'dateFrom': range_moment(given.get('dateFrom')),
        'dateTo': range_moment(given.get('dateTo')),
        # a quick scan told which earlier scan to measure back to, by that run's id. only the
        # id travels: the date is read off the run's own record, so a request cannot invent one
        'floorRun': str(given.get('floorRun') or '').strip(),
        # the earlier run to pick up from, by id. like the floor, only the id travels: what
        # the run does is read off that run's own record, and its settings replace these
        'resume': str(given.get('resume') or '').strip(),
        # how that run is retried: from the top, carrying on from its indexing, from its
        # downloads, or only the works it could not get. '' is the older resume, which
        # takes everything the earlier attempt recorded as it stands
        'retryMode': str(given.get('retryMode') or '').strip()
        if str(given.get('retryMode') or '').strip() in RETRY_MODES else '',
    }


# the formats a downloaded work is saved in, by extension - a file named for a work in one of
# these is that work's copy
WORK_FILE_EXTENSIONS = ('.html', '.htm', '.epub', '.pdf', '.mobi', '.azw3')


def indexed_file_name(record: dict, date: str, extension: str, maximum: int) -> str:
    """The name a work's file has when it is named from its index entry, as a download names
    it - by `FileNamePattern`, cut to `maximum` - but carrying `date` rather than the entry's
    own `date_updated`. That date is the version the file holds, which is not necessarily the
    one AO3 has now."""

    stem = naming.file_stem(parse_soup.get_name_metadata_from_blurb(record),
                            parse_text.get_date_stamp(date), maximum)
    return (stem or str(record.get('id') or '')) + extension


def dated_file_name(name: str, date: str, maximum: int, parts: dict | None = None) -> str:
    """A file with no index entry, given a date, named by `FileNamePattern`: from `parts`
    (`worknum`, `title`, `author` - what the page read out of the name) where it has them, else
    from the name itself when it is already in the pattern, else with the whole name standing
    in for the title. The same trimming a download's name has."""

    base, extension = os.path.splitext(name)
    if not parts:
        parts = naming.read(name) or {
            'worknum': parse_text.get_work_file_number(name) or '',
            'title': base, 'author': ''}
        if not naming.read(name) and parts['worknum']:
            # the number is a part of its own: the rest of the name stands in for the title
            span = naming.number_span(name)
            if span: parts['title'] = (base[:span[0]] + ' ' + base[span[1]:]).strip(' -_.')
    return naming.file_stem(parts, date, maximum) + extension


def file_names_for(files, maximum: int) -> list[str]:
    """What the page's dating should rename each file to (`POST /api/file-names`): from its
    index entry where it has one, or by adding the date to the name it has. A request that does
    not make sense answers '' for that file, and the page leaves the file alone."""

    names = []
    for item in files if isinstance(files, list) else []:
        item = item if isinstance(item, dict) else {}
        name = str(item.get('name') or '').replace('\\', '/').split('/')[-1]
        date = parse_text.get_date_stamp(item.get('date') or '')
        record = item.get('record')
        parts = item.get('parts') if isinstance(item.get('parts'), dict) else None
        extension = os.path.splitext(name)[1]
        # a file is renamed with no date only from the parts the page read out of its name (the
        # rename step): dating always has one
        if not name or (not date and not parts) or extension.lower() not in WORK_FILE_EXTENSIONS:
            names.append('')
        elif isinstance(record, dict) and record.get('id'):
            names.append(indexed_file_name(record, date, extension, maximum))
        else:
            names.append(dated_file_name(name, date, maximum, {
                key: str(parts.get(key) or '') for key in ('worknum', 'title', 'author')
            } if parts else None))
    return names


def example_file_name(maximum: int) -> str:
    """The naming rule shown as an actual name.

    Built through the same truncation a real download goes through, so the example shows
    what the configured length really does rather than claiming something tidier.
    """

    return naming.example(maximum)


def use_name_pattern(fileops: FileOps) -> naming.Pattern:
    """Name and read works' files by settings.ini's `FileNamePattern` from now on - the
    default when it is missing or not a pattern. Read raw: a separator may hold a %."""

    try:
        text = fileops.get_ini_value(strings.INI_NAME_PATTERN, naming.DEFAULT, raw=True)
    except Exception:
        text = naming.DEFAULT
    return naming.use(text)


def read_settings(fileops: FileOps) -> dict:
    """The settings.ini values a run will actually use, for the ui to show back.

    The path is included on purpose. Which settings.ini is in force is not obvious - it
    depends on where the helper was started from - and a helper left running from an
    earlier session is the usual explanation for settings that appear to be ignored.
    """

    pattern = use_name_pattern(fileops)
    return {
        'file': os.path.abspath(fileops.inifile),
        'extraWaitTime': fileops.get_ini_value_integer(strings.INI_WAIT_TIME, 0),
        # how every work's file is named, and so where its number and its date are read from -
        # the page reads names by the same pattern (`naming.ts`)
        'fileNamePattern': pattern.text,
        'fileNameLength': fileops.get_ini_value_integer(
            strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH),
        'fileNameExample': example_file_name(
            fileops.get_ini_value_integer(strings.INI_NAME_LENGTH,
                                          strings.INI_DEFAULT_NAME_LENGTH)),
        'maxRetries': fileops.get_ini_value_integer(strings.INI_MAX_RETRIES, 0),
        'maxTimeouts': fileops.get_ini_value_integer(strings.INI_MAX_TIMEOUTS, 3),
        'debugLogging': fileops.get_ini_value_boolean(strings.INI_DEBUG_LOGGING, False),
        'debugTools': fileops.get_ini_value_boolean(strings.INI_DEBUG_TOOLS, False),
        'consoleLogging': fileops.get_ini_value_boolean(strings.INI_CONSOLE_LOGGING, False),
        # how long a paused background run is kept before it is abandoned - the page warns
        # with this number before a background run is paused
        'pausedRunTimeoutMinutes': paused_run_timeout(),
        'questionTimeoutMinutes': question_timeout_seconds() // 60,
        'guessedDateTimeoutMinutes': unsure_question_timeout_seconds() // 60,
        # each question's own wait, and whether 'nobody's here' is on - the hosted copy's User
        # settings start from these
        'questionTimeouts': {name: timeout_minutes_for(name) for name in TIMEOUT_SETTING_FOR},
        'nobodyHere': nobody_here_setting(),
        # what each question answers itself with - the page starts a background run's
        # up-front answers from these
        'answerDefaults': {
            name: configured_answer(name, {'choice': strings.INI_ANSWER_CHOICES[key][0]})['choice']
            for name, key in ANSWER_SETTING_FOR.items()},
    }


def settings_for_record(fileops: FileOps) -> dict:
    """settings.ini as the history file should record it, or nothing if it cannot be read.

    Everything in `runs.py` swallows its own errors for one reason: a history file is a
    convenience, and a run that downloaded a library must not be reported as failed because
    a note about it could not be filled in. This is the same rule applied one step earlier -
    the values are gathered out here, so they have to be gathered safely too.
    """

    try:
        return read_settings(fileops)
    except Exception:
        return {}


class Job:
    """One download run, executing on its own thread and publishing progress events."""

    def __init__(self, action: str, filetypes: list[str], username: str,
                 options: dict | None = None, url: str = '', background: bool = False,
                 library=None, answers: dict | None = None) -> None:
        self.id = uuid.uuid4().hex
        # a run the page is not there for - see `dropbox_library`. it reaches the library
        # itself (`library`), and every question it could ask was answered before it started
        self.background = background
        self.library = library
        # the collections a collection run read - its cleanup notes them on the works they hold
        self.collections_read: list[str] = []
        self.started = runs.now()
        # when the user paused it, by the helper's own clock, or None while it is not paused.
        # a background run paused longer than `PausedRunTimeoutMinutes` is abandoned
        self.held_since: float | None = None
        self.held_at = ''
        # set when the helper ends it for that reason, rather than the user stopping it
        self.abandoned = False
        # when it ended, by the helper's clock - a finished run is forgotten after a while
        self.finished_at: float | None = None
        # the helper the page was talking to when it started this, as the page names it - so
        # a page talking to a different helper does not mistake this run for an interrupted
        # one of its own. see `Jobs.settleInterrupted`
        self.helper = ''
        # requests to the page about the library that have not been answered yet, by id, and
        # the bytes waiting for the page to collect for each write. see `storage_call`
        self.storage_pending: dict[str, dict] = {}
        # older copies marked for removal, removed in the cleanup step - see
        # `settle_duplicates`. each carries a `status` the history file follows
        self.removals: list[dict] = []
        # the run's works with more than one file of a format, by 'work:FORMAT', with how many
        # other copies each has - every one kept (`note_duplicate_copies`)
        self.duplicate_copies: dict[str, int] = {}
        self.blobs: dict[str, bytes] = {}
        # event streams open to a page right now, and when the last one closed
        self.listeners = 0
        self.last_listener = time.monotonic()
        self.action = action
        self.filetypes = filetypes
        self.username = username
        # only the actions in ACTIONS_NEEDING_URL use this; the rest build their own link
        self.url = url
        self.options = options or resolve_options(None)
        self.events: queue.Queue = queue.Queue()
        self.done = threading.Event()
        self.cancel = threading.Event()
        # set while the user has the run paused. it is only ever read at the one safe
        # point in the request loop, so setting it here cannot interrupt anything.
        self.held = threading.Event()
        # a debug tool: abandon the step in progress and go on to the next one. read at the
        # same loop boundaries a stop is read at, and cleared by whichever pass consumes it,
        # so one press skips one step rather than every step after it.
        self.skip = threading.Event()
        # the checklist this run is working through. starts as one with nothing in it and
        # nowhere to report to, so every run function can mark its steps without first
        # checking whether anyone is listening - `run_job` swaps in the real one.
        self.steps: 'Steps' = Steps(None, [])
        # the downloader doing the work, once a runner has built one, and the history file
        # being written about this run. both are set as the run gets going.
        self._ao3 = None
        self.record = None
        # a run can stop and put a question to the ui; these carry the reply back
        self.answered = threading.Event()
        self.answer: dict = {}
        self.history: list[dict] = []
        self.lock = threading.Lock()
        # the run this one picks up from - see `prepare_resume` - and the answers it gave to
        # the questions it asked, by question name, which are used rather than asked again
        self.resume: dict | None = None
        # a background run's up-front answers are the same thing, given before it started
        self.prior_answers: dict[str, dict] = dict(answers or {})
        # per-work questions (`ASKED_PER_WORK`) can come one after another for every work in a
        # library. an answer you chose to always use for a scenario is taken without asking -
        # sent with the run from the page's User settings, or ticked during this run - and once
        # one goes unanswered nobody is there, so the rest of that kind are not waited on
        self.always_answers: dict[str, dict] = {}
        self.went_unanswered: set[str] = set()
        # a page's own User settings, sent with the run (the hosted copy's): 'nobody's here' on
        # or off, and a wait per question by name. None / missing leaves settings.ini's
        self.nobody_here: bool | None = None
        self.question_timeouts: dict[str, int] = {}
        # every file the run judged without the app's own date in its name (`ask_about_unsure_copies`):
        # told to the page at the end, which suggests dating them in Resolve issues
        self.unsure_files: set[str] = set()
        # what the page's own User settings say unanswered questions take, and how long they
        # wait - sent by a page whose helper's settings.ini it cannot edit (a hosted copy).
        # None leaves settings.ini in force. see `run_question_settings`
        self.answer_defaults: dict[str, str] = {}
        self.question_timeout_minutes: int | None = None
        # a hosted page's own run-log choices (`run_log_settings`); None leaves settings.ini's
        self.run_log_max_lines: int | None = None
        self.trim_old_run_logs: bool | None = None
        # the page's own for a file without the app's own date (a hosted copy's User settings)
        self.unsure_timeout_minutes: int | None = None
        # the zone AO3 shows this person's dates in, from the page (`ao3_zone`); None is UTC.
        # every floor and ceiling is turned into a date in it before AO3's dates are compared
        self.ao3_zone = None
        self.ao3_zone_name = ''
        self.ao3_zone_missing = ''
        # the moment the login succeeded, or the first attempt's when resuming
        self.baseline = ''

    def emit(self, event: dict) -> None:
        if event.get('type') == progress.MESSAGE and 'at' not in event:
            # when it was said, in UTC: the window shows it in the reader's own zone, and a
            # page reattaching to a background run replays lines said hours before
            event = {**event, 'at': runs.now()}
        with self.lock:
            self.history.append(event)
            if self.background and event.get('type') == progress.MESSAGE:
                self.trim_history()
            # a background run with no page attached keeps its events in `history` alone: a
            # queue nobody reads would hold every one of them for hours. a page that attaches
            # replays `history` first, and only then starts reading the queue
            if self.listeners or not self.background: self.events.put(event)

    def trim_history(self) -> None:
        """Drop the oldest printed lines from a background run's replay, keeping the rest.

        Called with the lock held. Trimmed in a batch rather than per line, so a long run
        does not rebuild the list on every line it prints.
        """

        messages = sum(1 for e in self.history if e.get('type') == progress.MESSAGE)
        excess = messages - BACKGROUND_KEPT_MESSAGES
        if excess < BACKGROUND_KEPT_MESSAGES // 10: return
        kept = []
        for event in self.history:
            if excess and event.get('type') == progress.MESSAGE:
                excess -= 1
                continue
            kept.append(event)
        self.history = kept

    def ask(self, question: dict, default: dict) -> dict:
        """Put a question to the ui and wait for the answer.

        The wait is in slices rather than one long block so that a stop releases it: a run
        paused on a question the user has walked away from must still be stoppable, and a
        closed tab must not leave a thread waiting for an answer that can never come. A
        stop, or an answer that says nothing, both give back the default - which is always
        the option that changes nothing - except FicHub's, see `FICHUB_QUESTION`.
        """

        name = str(question.get('name') or '')
        # a per-work question in one of several cases is answered, defaulted and remembered by
        # its case (`SCENARIOS`), not by the question's name
        kind = str(question.get('scenario') or name)
        # a stop always gets the built-in default, which changes nothing (bar FicHub's, which
        # a stopped run never acts on); every other unanswered question takes settings.ini's
        stopped = dict(default)
        default = configured_answer(kind, default, self.answer_defaults.get(kind))
        prior = None if name in ASKED_PER_WORK else self.prior_answers.get(name)
        if prior is not None:
            # a resumed run does not ask again what the attempt before it was already told,
            # and a background run was told before it started
            print((strings.AO3_INFO_BACKGROUND_ANSWER if self.background
                   else strings.AO3_INFO_RESUME_ANSWER).format(prior.get('choice')))
            self.answered_how(ANSWERED_UP_FRONT if self.background else ANSWERED_EARLIER)
            return dict(prior)
        if kind in self.always_answers:
            print(strings.AO3_INFO_ALWAYS_ANSWER.format(self.always_answers[kind].get('choice')))
            self.answered_how(ANSWERED_ALWAYS)
            return dict(self.always_answers[kind])
        nobody_here = nobody_here_setting() if self.nobody_here is None else self.nobody_here
        if nobody_here and kind in self.went_unanswered:
            # one a work, and the last went unanswered: waiting on every one would hold an
            # unattended run for half an hour a work
            print(strings.AO3_INFO_NOBODY_ANSWERING.format(default.get('choice')))
            self.answered_how(ANSWERED_NOBODY)
            return dict(default)
        if self.background:
            # nobody is there to answer, so waiting would stall the run for half an hour and
            # then take the default anyway
            print(strings.AO3_INFO_BACKGROUND_DEFAULT.format(default.get('choice')))
            self.answered_how(ANSWERED_BACKGROUND_DEFAULT)
            return dict(default)

        timeout = self.timeout_seconds(name)
        if timeout <= 0:
            # set to take the default at once: said, so the log shows why nobody was asked
            print(strings.AO3_INFO_QUESTION_NOT_ASKED.format(default.get('choice')))
            self.answered_how(ANSWERED_NOT_ASKED)
            return dict(default)

        self.answer = {}
        self.answered.clear()
        self.emit({'type': progress.QUESTION, **question,
                   'default': default.get('choice'), 'timeoutMinutes': timeout / 60})

        waited = 0.0
        while not self.answered.is_set():
            if self.cancel.is_set():
                self.answered_how(ANSWERED_STOPPED)
                return stopped
            if waited >= timeout:
                print(strings.AO3_INFO_QUESTION_TIMED_OUT.format(default.get('choice')))
                self.answered_how(ANSWERED_TIMED_OUT)
                # every question: the rest of its kind need not wait (`nobody_here`)
                self.went_unanswered.add(kind)
                return default
            self.answered.wait(timeout=ANSWER_POLL_SECONDS)
            waited += ANSWER_POLL_SECONDS

        self.answered_how(ANSWERED_BY_YOU)
        answer = dict(self.answer or default)
        # ticked *always* on a scenario's question: taken for the rest of this run too (the
        # page keeps it for later runs)
        if answer.pop('always', False) and kind in ALWAYS_KINDS:
            self.always_answers[kind] = dict(answer)
        return answer

    def timeout_seconds(self, name: str) -> float:
        """How long the question `name` waits: the page's own wait for it where the run was sent
        one (`question_timeouts`, or the older `guessedDateTimeoutMinutes` /
        `questionTimeoutMinutes`), else settings.ini's (`timeout_minutes_for`)."""

        if name in self.question_timeouts: return self.question_timeouts[name] * 60
        if name == INFERRED_DATE_QUESTION:
            return (unsure_question_timeout_seconds() if self.unsure_timeout_minutes is None
                    else self.unsure_timeout_minutes * 60)
        if name in TIMEOUT_SETTING_FOR: return timeout_minutes_for(name) * 60
        return (question_timeout_seconds() if self.question_timeout_minutes is None
                else self.question_timeout_minutes * 60)

    def answered_how(self, how: str) -> None:
        """Note how the question just asked was answered, for the record of it that follows -
        so History can say whether you chose, or the run took a default (and why)."""

        if self.record is not None: self.record.pending_how = how


    def progress(self) -> dict:
        """How far this run has got, as its history file records it."""
        return self.record.data.setdefault('progress', {}) if self.record else {}

    @property
    def ao3(self):
        return self._ao3

    @ao3.setter
    def ao3(self, value) -> None:
        """Every runner builds its own downloader and hands it over here - which is where a
        retry carrying on from an earlier attempt tells it which formats that attempt already
        saved whole, so they are not fetched again."""

        self._ao3 = value
        # a test may stand a mock in for the class itself
        real = isinstance(Ao3, type) and isinstance(value, Ao3)
        if real: value.run_id = self.id
        done = self.earlier_progress().get('formatsDone') if getattr(self, 'resume', None) else None
        if value is not None and isinstance(done, dict):
            value.formats_done = {str(work): {str(x).upper() for x in formats or []}
                                  for work, formats in done.items()}
        if real and getattr(self, 'resume', None) and \
                not getattr(self, 'carried_checked', False):
            # once, before the run leans on anything its earlier attempt says it did
            self.carried_checked = True
            check_carried(self, value)

    def earlier_progress(self) -> dict:
        """How far the run this one resumes had got; empty when it resumes nothing."""
        return (self.resume or {}).get('progress') or {}

    def checkpoint(self, **fields) -> None:
        if self.record: self.record.checkpoint(**fields)


    def skipping(self) -> bool:
        """Whether the step in progress should be abandoned, consuming the request.

        Cleared as it is read, so one press skips one step rather than every step after it.
        """

        if not self.skip.is_set(): return False
        self.skip.clear()
        return True


    def reply(self, answer: dict) -> None:
        """Hand an answer back to whatever asked."""

        self.answer = answer or {}
        self.answered.set()

    # region the library, through the page

    def storage_call(self, op: str, args: dict, content: bytes | None = None) -> dict:
        """Ask the page to do one thing to the library, and wait for it to be done.

        The page owns the folder, so this is how every file a run touches is read or
        written. The request goes out on the event stream and the answer comes back to
        `POST /api/jobs/<id>/storage/<request>`. Bytes to write are not put in the event -
        the page collects them from `GET /api/jobs/<id>/blobs/<request>`, so a large epub
        does not travel as text.

        **A stop does not cut this short.** A write the run has started is finished, and the
        history file written as a run stops has to be written too; the run notices the stop
        at its next checkpoint as usual. What does end the wait is the page going away: with
        no page connected for `PAGE_GRACE_SECONDS`, nothing will ever answer, and the run
        fails saying so rather than hanging.
        """

        request = uuid.uuid4().hex
        event = {'type': progress.STORAGE, 'id': request, 'op': op, **args}
        if content is not None:
            self.blobs[request] = content
            event['blob'] = True
        done = threading.Event()
        with self.lock:
            self.storage_pending[request] = {'event': event, 'done': done, 'answer': {}}
        self.events.put(event)

        waited = 0.0
        limit = setting_integer(strings.INI_LIBRARY_TIMEOUT, STORAGE_TIMEOUT_SECONDS // 60, 1) * 60
        grace = setting_integer(strings.INI_PAGE_GONE, PAGE_GRACE_SECONDS)
        try:
            while not done.wait(ANSWER_POLL_SECONDS):
                waited += ANSWER_POLL_SECONDS
                if waited >= limit or self.page_gone(grace):
                    raise OSError(strings.ERROR_PAGE_GONE)
            with self.lock:
                return self.storage_pending[request]['answer']
        finally:
            with self.lock:
                self.storage_pending.pop(request, None)
            self.blobs.pop(request, None)

    def storage_reply(self, request: str, answer: dict) -> bool:
        """The page's answer to one request. False when nothing is waiting for it."""

        with self.lock:
            pending = self.storage_pending.get(request)
            if not pending: return False
            pending['answer'] = answer if isinstance(answer, dict) else {}
        pending['done'].set()
        return True

    def unanswered(self) -> list[dict]:
        """Requests the page has not answered - sent again to a page that reconnects."""

        with self.lock:
            return [x['event'] for x in self.storage_pending.values()]

    def page_gone(self, grace: float | None = None) -> bool:
        grace = PAGE_GRACE_SECONDS if grace is None else grace
        with self.lock:
            return (self.listeners == 0
                    and time.monotonic() - self.last_listener > grace)

    def page_connected(self, connected: bool) -> None:
        with self.lock:
            self.listeners += 1 if connected else -1
            self.last_listener = time.monotonic()

    # endregion


    def finish(self) -> None:
        self.finished_at = time.monotonic()
        self.done.set()
        self.events.put(None)


class Steps:
    """The steps a run intends to take, and where it has got to.

    A checklist rather than a log: it is sent once up front so the ui can show what is
    still to come, and then one event per change. That is why it cannot be built from
    `PHASE` events - a phase says what kind of work is happening and repeats (a combined
    run downloads twice, checks files twice), while a step is a place in a plan.

    A step that turns out to have nothing to do is **skipped, not failed**. A run with no
    unfinished fics has not gone wrong.
    """

    def __init__(self, report, plan: list[tuple[str, str]], on_start=None,
                 on_change=None) -> None:
        self.report = report
        self.plan = plan
        self.current: str | None = None
        # told which step is starting, so the history file says where an interrupted run was
        self.on_start = on_start
        # how each step has ended so far, by its id - kept in the history file, so a retry
        # can say which was the last to finish and offer to carry on from the next
        self.outcomes: dict[str, str] = {}
        self.on_change = on_change
        progress.report(report, progress.STEPS,
                        steps=[{'id': i, 'label': label} for i, label in plan])

    def _set(self, step: str, status: str) -> None:
        progress.report(self.report, progress.STEP, id=step, status=status)
        self.outcomes[step] = status
        if self.on_change: self.on_change(dict(self.outcomes))

    def label_of(self, step: str) -> str:
        return dict(self.plan).get(step, step)

    def start(self, step: str) -> None:
        self.current = step
        self._set(step, progress.STEP_RUNNING)
        if self.on_start: self.on_start(step, dict(self.plan).get(step, step))

    def earlier(self, step: str) -> None:
        """A resumed run's step that the attempt it picks up from had already finished."""
        if self.current == step: self.current = None
        self._set(step, progress.STEP_EARLIER)

    def done(self, step: str) -> None:
        if self.current == step: self.current = None
        self._set(step, progress.STEP_DONE)

    def skip(self, step: str) -> None:
        if self.current == step: self.current = None
        self._set(step, progress.STEP_SKIPPED)

    def fail(self, step: str) -> None:
        """Mark one step failed while the run carries on - indexing that broke off partway,
        whose run still downloads what it did index."""
        if self.current == step: self.current = None
        self._set(step, progress.STEP_FAILED)

    def fail_current(self) -> None:
        """Mark whatever was in progress as failed, when a run ends badly.

        Only the step actually running: the ones after it never started, and saying they
        failed would blame them for something that happened before they were reached.
        """

        if self.current: self._set(self.current, progress.STEP_FAILED)
        self.current = None


def action_name(action: str) -> str:
    """The button this action belongs to, for a history read months later.

    Kept on the helper rather than taken from the page, because a run's record has to make
    sense on its own - it is read back by the history tab, but it is also just a file.
    """

    return {
        ACTION_BOOKMARKS: strings.ACTION_NAME_BOOKMARKS,
        ACTION_UPDATE: strings.ACTION_NAME_UPDATE,
        ACTION_COLLECTIONS: strings.ACTION_NAME_COLLECTIONS,
        ACTION_COLLECTION: strings.ACTION_NAME_COLLECTION,
        ACTION_NEW: strings.ACTION_NAME_NEW,
        ACTION_SYNC: strings.ACTION_NAME_SYNC,
        ACTION_WORK: strings.ACTION_NAME_WORK,
        ACTION_WORKS: strings.ACTION_NAME_WORKS,
        ACTION_IMPORT: strings.ACTION_NAME_IMPORT,
        ACTION_CUSTOM: strings.ACTION_NAME_CUSTOM,
        ACTION_QUICK: strings.ACTION_NAME_QUICK,
    }.get(action, action)


def checks_non_bookmarks(job: Job) -> bool:
    """Whether this run checks every non-bookmark in the index for updates.

    Asked for, on a scan, and a scan that indexes: re-reading a work writes its entry, so a
    run writing no json - or a custom run told to skip indexing - cannot do it.
    """

    if not job.options.get('nonBookmarks'): return False
    if job.action not in NON_BOOKMARK_ACTIONS: return False
    if strings.AO3_DOWNLOAD_TYPE_METADATA not in job.filetypes: return False
    return job.action != ACTION_CUSTOM or bool(job.options.get('reindex'))


def step_plan(job: Job) -> list[tuple[str, str]]:
    """What this particular run is going to do, in order.

    Built from the action and the options rather than written per action, so a step that
    depends on a choice - images, skipping the indexing - appears only when it will
    actually happen. A checklist that lists work the run will not do is worse than none.
    """

    downloads = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes
    plan: list[tuple[str, str]] = [('login', strings.STEP_LOGIN)]

    if job.action in COLLECTION_ACTIONS:
        works = bool(job.options.get('collectionWorks'))
        if job.action == ACTION_COLLECTIONS:
            plan.append(('collections', strings.STEP_INDEX_COLLECTIONS_WORKS if works
                         else strings.STEP_INDEX_COLLECTIONS))
        else:
            plan.append(('collection', strings.STEP_INDEX_COLLECTION_WORKS if works
                         else strings.STEP_INDEX_COLLECTION))
        # the works met on the way are downloaded the way any scan downloads what it indexed.
        # nothing marks a series here unless the run was asked to follow them
        if works and job.options.get('series'):
            plan.append(('series', strings.STEP_SERIES))
        if works and downloads:
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD))
    elif job.action == ACTION_IMPORT:
        # no series walk: an import is about the files you already have
        plan.append(('index', strings.STEP_INDEX_IMPORT))
        # replacing outdated copies downloads with no format added: those a work already has
        if downloads or job.options.get('replaceOutdated'):
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD_IMPORT))
    elif job.action in (ACTION_WORK, ACTION_WORKS):
        one = job.action == ACTION_WORK
        plan.append(('index', strings.STEP_INDEX_ONE if one else strings.STEP_INDEX_MANY))
        plan.append(('series', strings.STEP_SERIES))
        if downloads:
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD_ONE if one
                         else strings.STEP_DOWNLOAD_MANY))
    elif job.action == ACTION_UPDATE:
        plan.append(('read', strings.STEP_READ_INDEX))
        if downloads: plan.append(('check', strings.STEP_CHECK_FILES))
        plan.append(('update', strings.STEP_UPDATE))
    elif job.action == ACTION_NEW:
        # the first pass of the combined run, on its own: it indexes what is new and
        # downloads that. no gap pass, because `run_new` does not run one
        plan.append(('index', strings.STEP_INDEX_NEW))
        plan.append(('series', strings.STEP_SERIES))
        if downloads:
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD_NEW))
    elif job.action == ACTION_SYNC:
        plan.append(('index', strings.STEP_INDEX_NEW))
        plan.append(('series', strings.STEP_SERIES))
        if downloads:
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD_NEW))
        plan.append(('update', strings.STEP_UPDATE))
        if downloads: plan.append(('gaps', strings.STEP_FILL_GAPS))
    else:
        # a full scan, a quick scan and a custom run differ only in where the walk stops
        indexing = job.action != ACTION_CUSTOM or job.options['reindex']
        # the custom run's window is its own shape; a quick scan's window keeps the quick
        # scan's two walks, so it falls through to the branch below
        if job.action == ACTION_CUSTOM and (job.options['dates'] or rechecks(job)):
            # a window of time chooses from the index and re-reads each one it picked -
            # the unfinished-fics shape rather than a scan. The walk that brings the index
            # up to date first is only there when the run was not told to skip indexing
            window = [('login', strings.STEP_LOGIN)]
            # listed whenever the run could index, even when it was told not to: a step
            # the user actively turned off is worth seeing struck through, where one this
            # workflow simply never had is only noise. `run_custom_dates` marks it skipped
            # a range of dates bookmarked reads the listing, and picks works, by that date
            bookmarked = listing_order(job) == 'bookmarked' and not rechecks(job)
            if metadata:
                window.append(('index', strings.STEP_INDEX_BOOKMARKED_WINDOW if bookmarked
                               else strings.STEP_INDEX_WINDOW))
            window.extend([('read', strings.STEP_READ_RECHECK if rechecks(job)
                            else strings.STEP_READ_BOOKMARKED_WINDOW if bookmarked
                            else strings.STEP_READ_WINDOW),
                           ('series', strings.STEP_SERIES)])
            if checks_non_bookmarks(job):
                window.append(('nonbookmarks', strings.STEP_NON_BOOKMARKS))
            window.extend([('check', strings.STEP_CHECK_FILES),
                           ('update', strings.STEP_UPDATE_WINDOW),
                           ('fichub', strings.STEP_FICHUB),
                           ('cleanup', strings.STEP_CLEANUP),
                           ('report', strings.STEP_REPORT)])
            return window
        if job.action == ACTION_QUICK:
            # two walks: new bookmarks by the date they were bookmarked, then changed fics
            # by the date ao3 updated them - see run_quick
            if job.options['dates']:
                plan.append(('bookmarked', strings.STEP_INDEX_BOOKMARKED_WINDOW))
                plan.append(('index', strings.STEP_INDEX_UPDATED_WINDOW))
            else:
                plan.append(('bookmarked', strings.STEP_INDEX_BOOKMARKED_SINCE))
                plan.append(('index', strings.STEP_INDEX_SINCE))
        elif indexing and metadata:
            plan.append(('index', strings.STEP_INDEX_ALL))
        else:
            plan.append(('index', strings.STEP_USE_INDEX))
        # after every walk is over: a series is marked while indexing and walked here, so
        # nothing a listing holds is read twice
        plan.append(('series', strings.STEP_SERIES))
        # after the series walk, which has usually reached most of them already
        if checks_non_bookmarks(job):
            plan.append(('nonbookmarks', strings.STEP_NON_BOOKMARKS))
        if downloads:
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD))
        if job.options['images'] and job.action == ACTION_CUSTOM:
            plan.append(('images', strings.STEP_IMAGES))

    # every run can fail to get a work from ao3, and FicHub is asked for those before the
    # end. every run can end with files to tidy away, and every run reports - in that order,
    # so a work FicHub gave us is linked to its collections, and anything the cleanup could
    # not remove is in the report
    plan.append(('fichub', strings.STEP_FICHUB))
    plan.append(('cleanup', strings.STEP_CLEANUP))
    plan.append(('report', strings.STEP_REPORT))
    return plan


CONSOLE_LOCK = threading.Lock()


def console_logging() -> bool:
    return FileOps().get_ini_value_boolean(strings.INI_CONSOLE_LOGGING, False)


def to_console(text: str) -> None:
    """Print to the helper's own console, whatever a run has done to `sys.stdout`.

    A run redirects stdout into its event stream (`run_job`), and that redirect is
    process-wide: an ordinary `print` from a request thread while a run is going would land
    in that run's messages to the page instead of the console. `sys.__stdout__` is the real
    one. Locked, so lines from two threads never interleave mid-line.
    """

    console = sys.__stdout__
    if console is None: return # no console at all, as under pythonw
    with CONSOLE_LOCK:
        try:
            console.write(f'{time.strftime("%H:%M:%S")} {text}\n')
            console.flush()
        except (OSError, ValueError):
            pass # a console that has gone is never worth failing a run over


class LineStream(io.TextIOBase):
    """Turns the console output of the existing code into progress messages."""

    def __init__(self, emit: Callable[[str], None]) -> None:
        self.emit = emit
        self.buffer_text = ''

    def write(self, text: str) -> int:
        self.buffer_text += text
        while '\n' in self.buffer_text:
            line, self.buffer_text = self.buffer_text.split('\n', 1)
            line = line.strip()
            if line: self.emit(line)
        return len(text)


def run_job(job: Job, password: str) -> None:
    """Execute a job. Mirrors the console actions, minus the prompts."""

    def report(event: dict) -> None:
        job.emit(event)

    # read once per run: a setting that changed halfway through would log half a run
    echo = console_logging()
    tag = f'[run {job.id[:8]}]'

    # what a run says before its history file exists - the setup, the 'logging in' - kept to
    # start that file's log with, so the log is the whole account the run window showed
    before_record: list[str] = []

    def said(line: str) -> None:
        job.emit({'type': progress.MESSAGE, 'text': line})
        if echo: to_console(f'{tag} {line}')
        if job.record: job.record.line(line)
        else: before_record.append(runs.stamped(line))

    stream = LineStream(said)

    try:
        # the library is the page's: every file goes through it - or, for a background run,
        # through the helper's own line to Dropbox, answering exactly as the page would
        fileops = FileOps(storage=PageStorage(job.library or job))
        fileops.initialize()
        use_name_pattern(fileops)
        # before anything is announced: a resumed run takes the earlier run's workflow, file
        # types and options, so the checklist and the history file describe that run
        if job.options.get('resume'): prepare_resume(job, fileops)
        with contextlib.redirect_stdout(stream):
            with Repository(fileops, progress=report, cancelled=job.cancel.is_set,
                            held=job.held.is_set) as repo:
                # a pause lands between the library's reads and writes too, not only at ao3
                if isinstance(fileops.storage, PageStorage): fileops.storage.gate = repo.hold_if_asked
                # the zone a run's own lines say a time in - the person's AO3 zone
                repo.zone = job.ao3_zone
                job.emit({'type': progress.STARTED, 'action': job.action,
                          'filetypes': job.filetypes, 'options': job.options})
                # which zone the floors and ceilings are turned into dates in, said up front -
                # it decides where every walk with a date stops
                if job.ao3_zone_missing:
                    print(strings.AO3_INFO_AO3_ZONE_MISSING.format(job.ao3_zone_missing))
                elif job.ao3_zone_name:
                    print(strings.AO3_INFO_AO3_ZONE.format(job.ao3_zone_name))
                # the checklist goes out before anything happens, so the ui can show what
                # is still to come rather than only what has already been done
                job.steps = Steps(report, step_plan(job), on_start=lambda step, label:
                                  job.checkpoint(step=step, stepLabel=label),
                                  on_change=lambda outcomes: job.checkpoint(steps=outcomes))

                # announced separately so the ui can show it is waiting, and say whether
                # the credentials worked before anything else starts
                skip_login = bool(job.options.get('skipLogin'))
                if not skip_login:
                    job.steps.start('login')
                    progress.report(report, progress.PHASE, name=progress.AUTHENTICATING)
                    print(strings.AO3_INFO_LOGGING_IN.format(job.username))
                # written here rather than at the end: a run killed mid-flight cannot write
                # its own epitaph, so a record still saying 'running' is how the history
                # page recognises one that was interrupted.
                #
                # and here rather than a few lines earlier, so a history file always means
                # a run that got as far as trying to log in. everything before this point
                # is setup that cannot reach ao3, and a record for one of those would be a
                # history entry for something that never happened.
                job.record = runs.RunRecord(fileops, job.id, job.action,
                                            action_name(job.action), job.filetypes,
                                            job.options,
                                            settings=settings_for_record(fileops),
                                            background=job.background,
                                            printed=before_record, helper=job.helper,
                                            url=job.url, username=job.username)
                job.record.max_lines = run_log_lines(job)
                # the issues and fic lists go into every save, not only the last one
                job.record.source = lambda: job.ao3
                # the steps this run set out to take, and how each has gone so far - what a
                # retry reads to say which finished last, and to offer the next
                job.checkpoint(stepPlan=[[step, label] for step, label in job.steps.plan],
                               steps=dict(job.steps.outcomes))
                if skip_login:
                    # asked for: everything goes on as it would, with what ao3 shows anyone.
                    # private bookmarks are not on the listing, and a work only a login can
                    # see fails and goes to FicHub
                    print(strings.AO3_INFO_NOT_LOGGING_IN)
                    repo.logged_in = False
                    begin_record(job, fileops)
                    job.steps.skip('login')
                else:
                    repo.login(job.username, password)
                    print(strings.AO3_INFO_LOGGED_IN)
                    begin_record(job, fileops)
                    progress.report(report, progress.AUTHENTICATED, username=job.username)
                    job.steps.done('login')

                runners()[job.action](job, fileops, repo, report)
                # every runner ends by calling report_failures, so by the time it returns
                # the reporting has happened. marked here rather than inside that function
                # so the step is ticked once per run and not once per place it is called.
                job.steps.done('report')
        close_record(job, runs.STATUS_ABANDONED if job.abandoned
                     else runs.STATUS_STOPPED if job.cancel.is_set() else runs.STATUS_SUCCESS)
        say_unsure_files(job)
        say_duplicate_copies(job)
        job.emit({'type': progress.FINISHED, 'cancelled': job.cancel.is_set(),
                  'abandoned': job.abandoned})
    except exceptions.CancelledException:
        # a stop the runner did not catch - taken at a pause gate outside its loops, say, or
        # during the login - is still a stop, not a failure. everything written stays
        # written either way, and a run abandoned while paused must say it was abandoned
        close_record(job, runs.STATUS_ABANDONED if job.abandoned else runs.STATUS_STOPPED)
        say_unsure_files(job)
        say_duplicate_copies(job)
        job.emit({'type': progress.FINISHED, 'cancelled': True, 'abandoned': job.abandoned})
    except Exception as e:
        # the step that was running is the one that failed; the ones after it never started
        job.steps.fail_current()
        close_record(job, runs.STATUS_FAILED, str(e))
        # a lapsed login is not a crash and there is a specific thing to do about it, so it
        # is flagged rather than left to be recognised from the wording of an error
        expired = isinstance(e, exceptions.SessionExpiredException)
        for item in job.removals:
            if item.get('status') == 'pending':
                item['status'] = 'kept'
                item['error'] = strings.CLEANUP_FAILED_RUN
        if job.removals and job.record:
            try:
                job.record.removals(job.removals)
            except Exception:
                pass
        report_not_removed(job, job.emit)
        say_unsure_files(job)
        say_duplicate_copies(job)
        job.emit({'type': progress.FAILED, 'error': str(e), 'sessionExpired': expired,
                  'detail': traceback.format_exc()})
    finally:
        # the Dropbox sign-in a background run was handed goes with the run - the page
        # promised it would. the job stays listed a while for a page reattaching, and must
        # not keep the token for that long
        job.library = None
        job.finish()


def retry_progress(earlier: dict, mode: str) -> dict:
    """What a retry takes on of the earlier attempt's progress, by how it is retried.

    `formatsDone` - every format of every work it saved whole - goes with the ways that carry
    on (INDEX, DOWNLOADS, FAILED), so those fetch only what is still missing, and is dropped by
    the ways that start something from the top. The old resume (no mode) takes everything.
    """

    saved = json.loads(json.dumps(earlier.get('progress') or {})) if isinstance(
        earlier.get('progress'), dict) else {}
    window = {key: saved[key] for key in ('floor',) if key in saved}
    done = {key: saved[key] for key in ('formatsDone',) if key in saved}
    if mode in (RETRY_TOP, RETRY_REINDEX): return window
    if mode == RETRY_FAILED: return {**window, **done, 'scope': failed_work_ids(earlier)}
    if mode == RETRY_REDOWNLOAD:
        saved.pop('formatsDone', None)
        return saved
    if mode == RETRY_INDEX:
        for key in ('scope', 'step', 'stepLabel', 'steps', 'nonBookmarksDone', 'updateDone'):
            saved.pop(key, None)
    return saved


def prepare_resume(job: Job, fileops: FileOps) -> None:
    """Take on the earlier run this one picks up from: its workflow, file types and options,
    how far it got, and the answers it was given.

    Refused, before anything starts, when that run cannot be resumed - `resume_problem`
    says why in words the page shows.
    """

    mode = job.options.get('retryMode') or ''
    earlier = runs.find_run(fileops, job.options['resume'])
    active = active_job_ids(exclude=job.id)
    problem = retry_problem(earlier, mode, active) if mode else resume_problem(earlier, active)
    if problem: raise exceptions.Ao3DownloaderException(problem)

    job.action = earlier['action']
    job.filetypes = list(earlier.get('filetypes') or [])
    # the collection it was pointed at; a resume request carries no link of its own
    job.url = earlier.get('url') or job.url
    # whether to log in is this attempt's own choice, made with the login it was given
    job.options = {**resolve_options(earlier.get('options')), 'resume': earlier['id'],
                   'retryMode': mode, 'skipLogin': bool(job.options.get('skipLogin'))}
    job.resume = {
        'id': earlier['id'],
        'file': earlier.get('file') or '',
        'first': earlier.get('resumesFirst') or earlier['id'],
        'baseline': earlier.get('baseline') or '',
        'progress': retry_progress(earlier, mode),
    }
    if mode == RETRY_FAILED and job.action in FIC_ACTIONS:
        # a fic run's failures are fics it could not read: just those, by their links
        links = [str(x.get('link') or '') for x in earlier.get('failures') or []
                 if isinstance(x, dict) and x.get('link')]
        job.url = '\n'.join(links)
        # an import stays an import, so the works it gets are still marked as imported
        if job.action != ACTION_IMPORT:
            job.action = ACTION_WORKS if len(links) > 1 else ACTION_WORK
    if mode:
        failed = len(failed_work_ids(earlier))
        print(strings.AO3_INFO_RETRYING.format(
            earlier.get('actionName') or earlier['action'],
            {RETRY_TOP: strings.AO3_INFO_RETRY_TOP, RETRY_INDEX: strings.AO3_INFO_RETRY_INDEX,
             RETRY_REINDEX: strings.AO3_INFO_RETRY_REINDEX,
             RETRY_REDOWNLOAD: strings.AO3_INFO_RETRY_REDOWNLOAD,
             RETRY_DOWNLOADS: strings.AO3_INFO_RETRY_DOWNLOADS,
             RETRY_FAILED: strings.AO3_INFO_RETRY_FAILED.format(failed)}[mode],
            runs.shown(earlier.get('started'), job.ao3_zone),
            earlier.get('status') or ''))
    # what the earlier attempt was actually told wins; a background run's up-front answers
    # stand in for any question it never reached. not from the top: that asks everything again
    if mode != RETRY_TOP:
        job.prior_answers = {**job.prior_answers,
                             **{str(c['question']): {k: v for k, v in c.items()
                                                     if k in ('choice', 'date')}
                                for c in earlier.get('choices') or []
                                if isinstance(c, dict) and c.get('question') and c.get('choice')}}
    print(strings.AO3_INFO_RESUMING.format(
        earlier.get('actionName') or earlier['action'],
        runs.shown(earlier.get('started'), job.ao3_zone),
        (earlier.get('progress') or {}).get('stepLabel') or strings.AO3_INFO_RESUME_NO_STEP))


def begin_record(job: Job, fileops: FileOps) -> None:
    """Once the login has worked: set the run's baseline, and, when resuming, start from the
    earlier run's progress and tell that run it has been picked up.

    The baseline is the moment the login succeeded - what a later quick scan measures back
    to. A resumed run keeps the **first** attempt's, because it is finishing that run's work:
    anything changed since then is for the next scan to find.
    """

    resume = job.resume
    job.baseline = (resume or {}).get('baseline') or runs.now()
    if not job.record: return
    # which zone its floors and ceilings were dated in - explains where a walk stopped
    job.record.data['ao3TimeZone'] = job.ao3_zone_name or 'UTC'
    if resume:
        job.record.data['progress'] = json.loads(json.dumps(resume['progress']))
        job.record.logged_in(job.baseline, resumes=resume['id'], first=resume['first'])
        if resume.get('file'): runs.amend_run(fileops, resume['file'], {'resumedBy': job.id})
    else:
        job.record.logged_in(job.baseline)


def background_answers(raw) -> dict[str, dict]:
    """A background run's answers to the questions it may meet, checked before it starts.

    Nobody will be there to answer, so they are given up front, by question name - the same
    shape a resumed run carries over (`prior_answers`). A question left out gets the answer
    that changes nothing when it comes up. Anything that could not be acted on is refused
    here, while there is still someone to tell.
    """

    if raw is None: return {}
    if not isinstance(raw, dict): raise ValueError('the answers have to be given by question')
    answers = {}
    for name, answer in raw.items():
        if name in RETIRED_QUESTIONS: continue
        if name not in CHOICES_FOR:
            raise ValueError(f"there is no question called '{name}'")
        choice = (answer or {}).get('choice') if isinstance(answer, dict) else None
        if choice not in CHOICES_FOR[name]:
            raise ValueError(f"'{choice}' is not an answer to '{name}' - it is one of "
                             f"{', '.join(CHOICES_FOR[name])}")
        answers[name] = {'choice': choice, 'date': parse_text.get_date_stamp(answer.get('date') or '')}
    return answers


def run_question_settings(defaults, timeout) -> tuple[dict[str, str], int | None]:
    """The default answers and question timeout a page's User settings sent with a run,
    checked before it starts: each answer one `strings.INI_ANSWER_CHOICES` offers for its
    question, the timeout a whole number of minutes. Neither sent leaves settings.ini's."""

    chosen: dict[str, str] = {}
    if defaults is not None:
        if not isinstance(defaults, dict):
            raise ValueError('the default answers have to be given by question')
        for name, choice in defaults.items():
            if name in RETIRED_QUESTIONS: continue
            key = ANSWER_SETTING_FOR.get(name)
            if not key: raise ValueError(f"there is no question called '{name}'")
            if choice not in strings.INI_ANSWER_CHOICES[key]:
                raise ValueError(f"'{choice}' is not a default answer to '{name}' - it is one of "
                                 f"{', '.join(strings.INI_ANSWER_CHOICES[key])}")
            chosen[name] = choice
    if timeout is None: return chosen, None
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 0:
        raise ValueError('the question timeout is a whole number of minutes, 0 or more')
    return chosen, timeout


def question_timeouts(raw) -> dict[str, int]:
    """The wait a page's User settings sent for each question with one of its own
    (`TIMEOUT_SETTING_FOR`), checked before a run starts: whole minutes, 0 or more."""

    if raw is None: return {}
    if not isinstance(raw, dict): raise ValueError('the question waits have to be given by question')
    chosen: dict[str, int] = {}
    for name, minutes in raw.items():
        if name in RETIRED_QUESTIONS: continue
        if name not in TIMEOUT_SETTING_FOR: raise ValueError(f"there is no question called '{name}'")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            raise ValueError('a question waits a whole number of minutes, 0 or more')
        chosen[name] = minutes
    return chosen


def always_answers(raw) -> dict[str, dict]:
    """The answers a page's User settings says to always use, by case (`ALWAYS_KINDS`: the
    guessed-date `SCENARIOS`, and `retry-reread`), checked before a run starts: yes or no. None
    sent, none."""

    if raw is None: return {}
    if not isinstance(raw, dict): raise ValueError('the answers to always use have to be given by case')
    chosen: dict[str, dict] = {}
    for scenario, choice in raw.items():
        if scenario not in ALWAYS_KINDS:
            raise ValueError(f"there is no case called '{scenario}' - it is one of {', '.join(sorted(ALWAYS_KINDS))}")
        allowed = RETRY_REREAD_CHOICES if scenario == RETRY_REREAD_QUESTION else INFERRED_DATE_CHOICES
        if choice not in allowed:
            raise ValueError(f"'{choice}' is not an answer to always use for '{scenario}'")
        chosen[scenario] = {'choice': choice}
    return chosen


def active_jobs() -> list[dict]:
    """The runs going right now, as the page's warning and the history's pinned panel need
    them: enough to name one and say what state it is in, never anything it was given."""

    with Handler.jobs_lock:
        going = [job for job in Handler.jobs.values() if not job.done.is_set()]
    return [{'id': job.id, 'action': job.action, 'actionName': action_name(job.action),
             'background': job.background, 'started': job.started,
             'paused': job.held.is_set(), 'abandonsAt': abandons_at(job),
             'step': job.steps.label_of(job.steps.current) if job.steps.current else ''}
            for job in sorted(going, key=lambda x: x.started)]


def active_job_ids(exclude: str = '') -> set[str]:
    """The runs this helper is working on right now."""

    with Handler.jobs_lock:
        return {job_id for job_id, job in Handler.jobs.items()
                if not job.done.is_set() and job_id != exclude}


def resume_problem(record: dict | None, active: set[str]) -> str:
    """Why a run cannot be picked up from, or '' when it can."""

    if not record: return strings.RESUME_NOT_FOUND
    if record.get('action') not in RESUME_ACTIONS: return strings.RESUME_WRONG_ACTION
    options = record.get('options') or {}
    if record.get('action') == ACTION_CUSTOM and not options.get('dates') and \
            (int(options.get('pages') or 0) or int(options.get('start') or 1) > 1):
        return strings.RESUME_SLICE
    if record.get('action') == ACTION_COLLECTION and not record.get('url'):
        return strings.RESUME_NO_LINK
    if record.get('status') == runs.STATUS_SUCCESS: return strings.RESUME_FINISHED
    if record.get('status') == runs.STATUS_RUNNING and record.get('id') in active:
        return strings.RESUME_STILL_RUNNING
    if not isinstance(record.get('progress'), dict): return strings.RESUME_TOO_OLD
    return ''


def failed_work_ids(record: dict) -> list[str]:
    """The works a run could not get, by number - what a retry of just those fetches."""

    ids: list[str] = []
    for failure in record.get('failures') or []:
        if not isinstance(failure, dict): continue
        number = str(failure.get('id') or '') or parse_text.get_work_number(str(failure.get('link') or ''))
        if number and number not in ids: ids.append(str(number))
    return ids


# the steps that make up a run's indexing, and its downloads - for telling whether both finished
INDEX_STEPS = ('index', 'bookmarked', 'collections', 'collection', 'series', 'nonbookmarks')
DOWNLOAD_STEPS = ('check', 'download', 'update')


def finished_both(record: dict) -> bool:
    """Whether a run completed both its indexing and its downloads - so there is nothing to
    carry on from, and a retry starts one of them from the top or takes just its failures.

    Read from how each of its steps went (a step done, done earlier, or skipped counts); a run
    from before steps were saved counts only when it finished.
    """

    saved = record.get('progress') if isinstance(record.get('progress'), dict) else {}
    plan = [step[0] for step in (saved.get('stepPlan') or []) if step]
    steps = saved.get('steps') or {}
    if not plan or not steps: return record.get('status') == runs.STATUS_SUCCESS
    over = (progress.STEP_DONE, progress.STEP_EARLIER, progress.STEP_SKIPPED)
    wanted = [step for step in plan if step in INDEX_STEPS + DOWNLOAD_STEPS]
    return bool(wanted) and all(steps.get(step) in over for step in wanted)


def retry_problem(record: dict | None, mode: str, active: set[str]) -> str:
    """Why `record` cannot be retried this way, or '' when it can."""

    if not isinstance(record, dict): return strings.RETRY_NOT_FOUND
    if record.get('status') == runs.STATUS_RUNNING and record.get('id') in active:
        return strings.RETRY_STILL_RUNNING
    action = record.get('action')
    options = record.get('options') or {}
    progress_so_far = record.get('progress') if isinstance(record.get('progress'), dict) else None
    if action == ACTION_COLLECTION and not record.get('url'): return strings.RESUME_NO_LINK
    if action in FIC_ACTIONS and not record.get('url'): return strings.RETRY_NO_FIC_LINKS
    if mode == RETRY_TOP: return ''
    if mode in (RETRY_INDEX, RETRY_DOWNLOADS) and action not in LIST_ACTIONS and \
            record.get('status') == runs.STATUS_PARTIAL:
        # it reached the end: there is nothing to carry on from, only what it missed
        return strings.RETRY_PARTIAL_DONE
    if mode in (RETRY_INDEX, RETRY_DOWNLOADS) and finished_both(record):
        return strings.RETRY_ALL_DONE
    if action in LIST_ACTIONS and mode == RETRY_DOWNLOADS:
        # several fics carry on fic by fic: what the earlier attempt saved is passed over
        return '' if progress_so_far is not None else strings.RESUME_TOO_OLD
    if mode == RETRY_REINDEX:
        # from the first page, so a slice's page numbers are not trusted to have stayed put
        return '' if action in RESUME_ACTIONS else strings.RETRY_NO_INDEX
    if mode == RETRY_FAILED:
        if action not in RESUME_ACTIONS and action not in FIC_ACTIONS:
            return strings.RETRY_FAILED_WRONG_ACTION
        if failed_work_ids(record): return ''
        # only a run that finished everything can say everything arrived
        return strings.RETRY_NO_FAILURES if record.get('status') == runs.STATUS_SUCCESS \
            else strings.RETRY_NO_FAILURES_UNFINISHED
    if action not in RESUME_ACTIONS: return strings.RETRY_NO_INDEX
    if action == ACTION_CUSTOM and not options.get('dates') and \
            (int(options.get('pages') or 0) or int(options.get('start') or 1) > 1):
        return strings.RESUME_SLICE
    if progress_so_far is None: return strings.RESUME_TOO_OLD
    if mode in (RETRY_DOWNLOADS, RETRY_REDOWNLOAD) and progress_so_far.get('scope') is None:
        return strings.RETRY_NO_DOWNLOADS
    return ''


def retry_default(record: dict, available: set[str]) -> str:
    """The way to retry a run that picks up from its first step that did not finish.

    A run whose indexing broke off carries on with its indexing; one that got past indexing
    and stopped carries on with its downloads; one that finished but could not get some works
    retries just those; anything else starts again from the top.
    """

    if record.get('status') == runs.STATUS_PARTIAL:
        # some of its indexing failed: everything is indexed again (a fic run re-reads its
        # failed fics anyway); only downloads failed: just those
        if record.get('indexFailures') and record.get('action') not in FIC_ACTIONS and \
                RETRY_REINDEX in available:
            return RETRY_REINDEX
        if RETRY_FAILED in available: return RETRY_FAILED
    steps = ((record.get('progress') or {}).get('steps') or {}) if isinstance(
        record.get('progress'), dict) else {}
    index_steps = ('index', 'bookmarked', 'collections', 'collection')
    index_broke = bool(record.get('indexFailures')) or any(
        steps.get(step) in (progress.STEP_FAILED, progress.STEP_RUNNING) for step in index_steps)
    unfinished = record.get('status') != runs.STATUS_SUCCESS
    if index_broke and RETRY_INDEX in available: return RETRY_INDEX
    if unfinished and RETRY_DOWNLOADS in available: return RETRY_DOWNLOADS
    if unfinished and RETRY_INDEX in available and steps: return RETRY_INDEX
    if RETRY_FAILED in available: return RETRY_FAILED
    return RETRY_TOP


def retry_choices(record: dict, active: set[str]) -> dict:
    """Every way `record` could be retried, whether each can be and why not, and the one to
    offer first."""

    modes = [{'mode': mode, 'available': not retry_problem(record, mode, active),
              'reason': retry_problem(record, mode, active)} for mode in RETRY_MODES]
    if record.get('action') in FIC_ACTIONS:
        # a fic run has no listing to carry on with: it is the fics, or the failed ones - and,
        # for several fics, carrying on from where it stopped
        kept = (RETRY_TOP, RETRY_DOWNLOADS, RETRY_FAILED) \
            if record.get('action') in LIST_ACTIONS else (RETRY_TOP, RETRY_FAILED)
        modes = [m for m in modes if m['mode'] in kept]
    available = {m['mode'] for m in modes if m['available']}
    return {'modes': modes, 'default': retry_default(record, available) if available else '',
            'failedWorks': len(failed_work_ids(record))}


def retryable_among(records: list[dict], active: set[str]) -> list[dict]:
    """Every run that has ended among `records`, each with how it can be retried. Newest
    first, as given. A run still going is left out: it is paused or resumed in its window."""

    found = []
    for index, record in enumerate(records):
        if not isinstance(record, dict): continue
        if record.get('status') == runs.STATUS_RUNNING and record.get('id') in active: continue
        warnings = []
        if record.get('resumedBy'): warnings.append(strings.RESUME_ALREADY_RESUMED)
        if record.get('action') not in COLLECTION_ACTIONS and \
                record.get('status') != runs.STATUS_SUCCESS and \
                any(isinstance(x, dict) and x.get('status') == runs.STATUS_SUCCESS
                    and covered_the_whole_listing(x) for x in records[:index]):
            warnings.append(strings.RESUME_NEWER_SCAN)
        if record.get('status') == runs.STATUS_PARTIAL:
            if record.get('indexFailures') and record.get('action') not in FIC_ACTIONS:
                warnings.append(strings.RETRY_WARN_INDEX_FAILED)
            elif record.get('failures'):
                warnings.append(strings.RETRY_WARN_DOWNLOADS_FAILED)
        found.append({**record, 'retry': retry_choices(record, active), 'warnings': warnings})
    return found


def carried_works(earlier: dict) -> set[str]:
    """Every work an earlier attempt's progress says it indexed or settled."""

    found: set[str] = set()

    def take(values) -> None:
        for value in values or []:
            if isinstance(value, (str, int)) and str(value): found.add(str(value))

    take(earlier.get('scope'))
    for walk in (earlier.get('walks') or {}).values():
        if isinstance(walk, dict): take(walk.get('works'))
    for key in ('seriesWorks', 'nonBookmarksDone', 'updateDone'):
        take(earlier.get(key))
    take((earlier.get('formatsDone') or {}).keys())
    return found


def check_carried(job: Job, ao3: Ao3) -> None:
    """Before a retry carries on, check what its earlier attempt says it did is still so.

    **Indexed:** every work the earlier attempt's progress names must have its index file. A
    work whose file is gone (deleted by hand, a library restored from a backup) is indexed
    again from its own page - one request each - so everything after has an entry to work
    from; one that will not index is a failure, offered to FicHub at the end.

    **Downloaded:** every format it saved whole (`formatsDone`) must still be in the folder,
    with the date in its name the same as its index entry's `date_updated`. A file that is
    missing, undated, or dated otherwise is not done after all, and is fetched again. The
    entry's `last_indexed_by` says which run last wrote it: when that is not this run or an
    attempt it carries on from, the entry has been rewritten since - the file is still judged
    against it, since it is the newest the index knows, and the run says so.

    Only what the retry carries on from is checked: a retry from the top carries nothing.
    """

    earlier = job.earlier_progress()
    fileops = ao3.fileops
    chain = {str(x) for x in [job.resume.get('id'), job.resume.get('first'),
                               *(earlier.get('chain') or [])] if x}
    job.checkpoint(chain=sorted(chain | {job.id}))

    works = carried_works(earlier)
    if works:
        print(strings.AO3_INFO_RETRY_CHECK_INDEX.format(len(works)))
        entries = ao3.list_entries(strings.INDEXING_FOLDER_NAME)
        missing = sorted((w for w in works if w not in entries), key=lambda x: (len(x), x))
        if not missing:
            print(strings.AO3_INFO_RETRY_INDEX_OK)
        else:
            print(strings.AO3_INFO_RETRY_INDEX_MISSING.format(len(missing), ', '.join(missing)))
            for work in missing:
                link = f'{strings.AO3_BASE_URL}/works/{work}'
                print(strings.AO3_INFO_RETRY_REINDEXING.format(work))
                try:
                    ao3.index_one_work(link)
                except (exceptions.CancelledException, exceptions.SessionExpiredException):
                    raise
                except Exception as e:
                    ao3.record_failure(link, e)
                    # nothing to judge its files against now
                    ao3.formats_done.pop(work, None)

    done = getattr(ao3, 'formats_done', None)
    if not isinstance(done, dict) or not done: return
    print(strings.AO3_INFO_RETRY_CHECK_DOWNLOADS.format(len(done)))
    entries = indexed_entries(ao3, fileops, set(done))
    formats = sorted({f for saved in done.values() for f in saved})
    try:
        existing = shared.scan_downloaded_works(fileops.worksfolder, formats,
                                                storage=fileops.storage)
    except Exception:
        existing = {}
    dropped = 0
    for work in sorted(done, key=lambda x: (len(x), x)):
        entry = entries.get(work)
        wanted = parse_text.get_date_stamp((entry or {}).get('date_updated'))
        writer = str((entry or {}).get(indexing.LAST_INDEXED_BY) or '')
        if entry and writer and writer not in chain | {job.id}:
            print(strings.AO3_INFO_RETRY_INDEX_REWRITTEN.format(work, writer))
        for filetype in sorted(done[work]):
            copy = (existing.get(work) or {}).get(filetype)
            if not entry:
                problem = strings.AO3_INFO_RETRY_NO_ENTRY
            elif not copy:
                problem = strings.AO3_INFO_RETRY_FILE_MISSING
            elif not wanted or copy.get('date') != wanted:
                problem = strings.AO3_INFO_RETRY_FILE_DATE.format(
                    copy.get('date') or strings.AO3_INFO_RETRY_NO_DATE,
                    wanted or strings.AO3_INFO_RETRY_NO_DATE)
            else:
                continue
            done[work].discard(filetype)
            dropped += 1
            print(strings.AO3_INFO_RETRY_FETCH_AGAIN.format(work, filetype, problem))
        if not done[work]: del done[work]
    print(strings.AO3_INFO_RETRY_DOWNLOADS_OK if not dropped
          else strings.AO3_INFO_RETRY_DOWNLOADS_DROPPED.format(dropped))
    # this run's progress started as a copy of the earlier attempt's: it must not pass on
    # formats that turned out not to be there
    job.checkpoint(formatsDone={work: sorted(saved) for work, saved in done.items()})


def records_by_id(fileops: FileOps, ids) -> list[dict]:
    """The index entries for these work numbers, in the order given; ones the index no
    longer holds are left out."""

    wanted = [str(x) for x in ids or []]
    if not wanted: return []
    by_id = {str(r.get('id') or ''): r for r in shared.read_index(fileops)}
    return [by_id[x] for x in dict.fromkeys(wanted) if x in by_id]


def resumed_scope(job: Job, fileops: FileOps, ao3: Ao3 | None = None,
                  report=None) -> list[dict] | None:
    """The works a resumed run covers, when the run it picks up from had already settled
    them - got as far as checking its files. None when it had not. (Whether to read them
    again from AO3 is asked as they are checked - `reread_carried`, from `plan_refresh`.)"""

    scope = job.earlier_progress().get('scope')
    if scope is None: return None
    print(strings.AO3_INFO_RESUME_SCOPE.format(len(scope)))
    job.checkpoint(scope=list(scope))
    return records_by_id(fileops, scope)


# the retry ways that take works from the earlier attempt's index entries without reading them
# again: carrying on its indexing (a walk or collection it finished), and all three download ways.
# `top` and `reindex` read every listing again
CARRYING_RETRY_MODES = frozenset({'', 'index', 'redownload', 'downloads', 'failed'})


def carried_records(job: Job, records: list[dict]) -> list[dict]:
    """Of the works a retry is about to check, the ones this attempt has not read from AO3 -
    taken from the index as the earlier attempt left it. None on a run that is not a retry
    carrying on."""

    if not job.resume or (job.options.get('retryMode') or '') not in CARRYING_RETRY_MODES:
        return []
    ao3 = getattr(job, 'ao3', None)
    read = getattr(ao3, 'reindexed', None) or set()
    return [r for r in records if str(r.get('id') or '') not in read]


def reread_carried(job: Job, ao3: Ao3, records: list[dict], report=None) -> list[dict]:
    """Ask once a run whether to read each carried-on work again from AO3 before downloading
    it, and do so on yes - once a work, however many formats it has. A work AO3 updated since
    the earlier attempt then has an entry, and so a file name, with the date it has now. One
    that will not read is a failure (offered to FicHub at the end) and is not downloaded from
    its old entry. Default no: the index as the earlier attempt left it.

    Each entry re-read is updated **in place**, since the caller downloads from the same
    dictionaries; the ones that would not read are returned, for the caller to leave out. The
    answer stands for the rest of the run (`Job.reread_choice`), so a later batch of the same
    run is not asked again."""

    if not records: return []
    choice = getattr(job, 'reread_choice', None)
    if choice is None:
        print(strings.AO3_INFO_RETRY_REREAD_ASK.format(len(records)))
        answer = job.ask({'name': RETRY_REREAD_QUESTION, 'count': len(records),
                          'choices': list(RETRY_REREAD_CHOICES)}, {'choice': RETRY_REREAD_NO})
        choice = answer.get('choice') if answer.get('choice') in RETRY_REREAD_CHOICES else RETRY_REREAD_NO
        job.reread_choice = choice
        if job.record:
            job.record.choice({'question': RETRY_REREAD_QUESTION, 'count': len(records),
                               'choice': choice})
        if choice != RETRY_REREAD_YES:
            print(strings.AO3_INFO_RETRY_REREAD_SKIPPED)
    if choice != RETRY_REREAD_YES or job.cancel.is_set():
        return []

    print(strings.AO3_INFO_RETRY_REREADING.format(len(records)))
    unread: list[dict] = []
    for done, record in enumerate(records, start=1):
        if job.cancel.is_set(): break
        link = record.get('link') or ''
        title = record.get('title') or link
        print(strings.AO3_INFO_UPDATE_WORK.format(done, len(records), title))
        if report is not None:
            progress.report(report, progress.WORK, title=title, link=link, done=done,
                            total=len(records), phase=progress.INDEXING)
        try:
            print(strings.AO3_INFO_UPDATE_READING)
            fresh = ao3.refresh_one(record)
            print(strings.AO3_INFO_UPDATE_INDEXED)
        except exceptions.CancelledException:
            print(strings.INFO_CANCELLED)
            raise
        except exceptions.SessionExpiredException:
            raise
        except Exception as e:
            ao3.record_failure(link, e)
            ao3.log_error({'link': link}, e)
            unread.append(record)
            continue
        if fresh is not record:
            updated = dict(fresh)
            record.clear()
            record.update(updated)
    return unread


def save_scope(job: Job, records: list[dict]) -> None:
    """Record which works this run covers, as it starts checking files - what a resumed
    run goes on to check and download without indexing again."""

    job.checkpoint(scope=[str(r['id']) for r in records if r.get('id')])


def finish_walk_step(job: Job, ao3: Ao3, step: str) -> None:
    """Mark a listing walk's step: taken from the earlier attempt, failed when the walk
    broke off on an error (its pages so far are kept, and the run carries on with them -
    but the step did not do what it says), or done."""

    if getattr(ao3, 'walk_skipped', False): mark_earlier(job, step)
    elif getattr(ao3, 'walk_failed', False): job.steps.fail(step)
    else: job.steps.done(step)


def mark_earlier(job: Job, *steps: str) -> None:
    """Mark steps the resumed run's earlier attempt finished - the ones this plan has."""

    planned = {step for step, _ in job.steps.plan}
    for step in steps:
        if step in planned: job.steps.earlier(step)


def restore_series(job: Job, ao3: Ao3) -> None:
    """Give a resumed run the series the earlier attempt had marked, and the ones it had
    already walked, so neither is lost nor walked twice."""

    earlier = job.earlier_progress()
    for marked in earlier.get('seriesMarked') or []:
        if isinstance(marked, dict) and marked.get('id'):
            ao3.series_marked.setdefault(str(marked['id']), {
                'id': str(marked['id']), 'title': marked.get('title') or '',
                'bookmark': marked.get('bookmark')})
    for series_id in earlier.get('seriesDone') or []:
        ao3.series_read.setdefault(str(series_id), [])


# an IANA time zone name as a browser gives it: `Europe/London`, `America/Argentina/Salta`, `UTC`
ZONE_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+)*$')


def ao3_zone(name):
    """The zone AO3 shows this person's dates in - from the page's User settings, the
    browser's own zone unless they changed it - or None for UTC. ValueError for something that
    is not a zone name at all. A name this computer cannot look up (no tz database) is None,
    said in the run's log by the caller, rather than refusing the run."""

    if name in (None, ''): return None
    if not isinstance(name, str) or len(name) > 64 or not ZONE_NAME.match(name):
        raise ValueError(f"'{name}' is not a time zone name")
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def range_moment(value) -> str:
    """A typed range end as it is kept: a UTC moment `YYYY-MM-DDTHH:MM:SS+00:00`, or a bare
    `YYYY-MM-DD` from a page that sent one. Anything else is '' - no limit at that end, the
    safe direction, as `get_date_stamp` has always made it."""

    text = str(value or '').strip()
    try:
        at = datetime.datetime.fromisoformat(text)
    except ValueError:
        return parse_text.get_date_stamp(text)
    if at.tzinfo is None: return parse_text.get_date_stamp(text[:10])
    return at.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()


def range_day(job, key: str) -> str:
    """A typed range end (`dateFrom`/`dateTo`) as the day it is in the person's AO3 zone - what
    AO3's dates are compared with."""

    return ao3_day(job.options.get(key), job.ao3_zone)


def zone_lookup_works() -> bool:
    """Whether a zone other than UTC can be looked up here - false on a system with no zone
    database and no `tzdata` packed in, where every AO3 zone falls back to UTC."""

    return ao3_zone('Europe/London') is not None


def ao3_day(stamp, zone=None) -> str:
    """The day a recorded moment fell on as AO3 dates things: `YYYY-MM-DD` in `zone` (UTC when
    None). AO3 writes only a date on its listings, in the zone it shows this person, so a floor
    or ceiling - a UTC moment - is turned into a date **in that zone** before the two are
    compared: a fic AO3 dates on or after it was updated on or after the moment, and none is
    missed. A naive time (written before times were UTC) is taken as written."""

    text = str(stamp or '')
    try:
        at = datetime.datetime.fromisoformat(text)
    except ValueError:
        return text[:10]
    if at.tzinfo is None: return text[:10]
    return at.astimezone(zone or datetime.timezone.utc).strftime('%Y-%m-%d')


def retry_ceiling(job: Job, end: str = '') -> str:
    """The newest date a retry wants anything from: the day its first attempt started (its
    baseline), or `end` - a date range's - when that is earlier. A first attempt has none, and
    walks from page 1. Every retry in a chain shares the first attempt's baseline, so every
    one of them stops at the same ceiling."""

    if not job.resume: return ''
    started = ao3_day(job.baseline, job.ao3_zone)
    end = parse_text.get_date_stamp(end) if end else ''
    return min(d for d in (started, end) if d) if (started or end) else ''


def walk_listing(job: Job, fileops: FileOps, ao3: Ao3, name: str, link: str,
                 anchored: bool, ceiling: str = '', **kwargs) -> list[dict]:
    """Walk one listing through `get_metadata`, saving how far it gets - and, when resuming,
    carrying on from where the earlier attempt stopped.

    `name` tells this run's walks apart (`all`, `bookmarked`, `updated`). A walk the earlier
    attempt finished is not walked again: its works are taken from the index. One it did
    not finish is picked up from the page it stopped on when `anchored` - a listing sorted by
    date bookmarked, where the last bookmark it saved can be found again (`find_anchor`).
    A listing sorted by date updated is walked again from the first page: a fic ao3 updated
    since moves to the top, so no place in it stays put.

    `ceiling` is the newest date a **retry** has any use for, in the listing's own sort -
    a date range's end, or the first attempt's start. A retried walk starts at the first page
    holding that date rather than page 1, and one that broke off starts at whichever is older,
    the ceiling or the date it reached (from the page it stopped on). Fics dated after the
    ceiling are not indexed (`get_metadata(ceiling=)`); on it, they are. A first attempt
    walks from page 1 whatever it is given: this only shortens a retry, it never changes how
    a listing is walked.

    Returns the works the walk covers, in both attempts. Whether it was walked at all this
    time is left on `ao3.walk_skipped`, for the caller's checklist.
    """

    walks = job.progress().setdefault('walks', {})
    earlier = (job.earlier_progress().get('walks') or {}).get(name) if job.resume else None
    carried: list[str] = []
    start = ao3.start
    ao3.walk_skipped = False

    if earlier and earlier.get('done'):
        print(strings.AO3_INFO_RESUME_WALK_DONE)
        walks[name] = earlier
        job.checkpoint(walks=walks)
        ao3.walk_skipped = True
        return records_by_id(fileops, earlier.get('works'))
    sort = 'bookmarked' if anchored else 'updated'
    reached = str((earlier or {}).get('anchor', {}).get('date') or '') if earlier else ''
    # an anchor saved before walks recorded their sort is a date bookmarked
    if reached and (not earlier.get('page') or
                    (earlier.get('anchor') or {}).get('sort', 'bookmarked') != sort):
        reached = ''
    ceiling = parse_text.get_date_stamp(ceiling) if job.resume and ceiling else ''
    target = min(d for d in (reached, ceiling) if d) if (reached or ceiling) else ''
    if target:
        if target == ceiling and ceiling != reached:
            print(strings.AO3_INFO_RESUME_FROM_CEILING.format(ceiling))
        hint = int(earlier['page']) if reached else 1
        page = find_anchor(ao3, link, hint, {'date': target, 'sort': sort})
        if page:
            ao3.start = page
            carried = [str(x) for x in (earlier or {}).get('works') or []]
        else:
            print(strings.AO3_INFO_RESUME_ANCHOR_LOST)
    elif earlier:
        print(strings.AO3_INFO_RESUME_WALK_AGAIN)

    state = {'page': None, 'anchor': None, 'done': False, 'works': list(carried)}

    def on_page(page: int, anchor: dict | None, works: list[str]) -> None:
        state['page'] = page
        if anchor: state['anchor'] = anchor
        state['works'].extend(x for x in works if x not in state['works'])
        walks[name] = state
        job.checkpoint(walks=walks, seriesMarked=list(ao3.series_marked.values()),
                       externalsSaved=externals_so_far(job, ao3))

    ao3.on_page = on_page
    try:
        if ceiling: kwargs.update(ceiling=ceiling, ceiling_on=sort)
        records = ao3.get_metadata(link, job.options['workdates'], **kwargs)
    finally:
        ao3.on_page = None
        ao3.start = start
    if ao3.walk_failed and ao3.index_failures:
        # which of this run's walks it was - a quick scan makes two
        ao3.index_failures[-1]['walk'] = name
    if ao3.walk_finished and not job.cancel.is_set():
        state['done'] = True
        walks[name] = state
        job.checkpoint(walks=walks, seriesMarked=list(ao3.series_marked.values()),
                       externalsSaved=externals_so_far(job, ao3))
    return merge_by_work(records_by_id(fileops, carried), records)


def find_anchor(ao3: Ao3, link: str, page: int, anchor: dict) -> int | None:
    """The page a retried walk carries on from: the first page of the listing now holding
    anything dated on or before `anchor['date']`, the date the earlier attempt got down to -
    or None when no such page is left.

    It looks for the **date**, not the bookmark. Pages move between attempts - bookmarks
    added since push everything down, ones removed pull it up, and on a listing sorted by
    date updated a fic ao3 updated since jumps to the top - but the listing is still in date
    order, newest first. So every fic on that date sits from this page on, and starting here
    reaches the first of them. Fics above it the earlier attempt read already.

    The search starts at the page the earlier attempt stopped on and goes as far either way
    as it has to, bounded by the listing's length: forward while a page is all newer, back
    while the page before still reaches the date - doubling the step and then halving it, so
    a listing that has moved by a hundred pages costs a handful of requests, not a hundred.
    """

    date = str(anchor.get('date') or '')
    if not date: return None
    selector = SORT_DATE_SELECTORS.get(anchor.get('sort') or 'bookmarked')
    seen: dict[int, bool] = {}
    total = None

    def reaches(number: int) -> bool:
        """Whether this page holds anything on or before the date (pages past the end do)."""
        nonlocal total
        if number in seen: return seen[number]
        print(strings.AO3_INFO_RESUME_LOOKING.format(number, date))
        soup = ao3.repo.get_soup(parse_text.set_page_number(link, number))
        if total is None: total = parse_soup.get_total_pages(soup) or 1
        dates = [d for d in (parse_text.get_date_stamp(parse_soup.get_text_or_empty(b, selector))
                             for b in parse_soup.get_blurbs(soup)) if d]
        seen[number] = number > total or bool(dates and min(dates) <= date)
        return seen[number]

    current = max(1, page)
    reaches(current)
    if current > total:
        current = total
    if reaches(current):
        # walk back: the latest page known to reach the date, and one before it that does not
        hi, lo, step = current, 0, 1
        while hi > 1:
            probe = max(1, hi - step)
            if reaches(probe):
                hi = probe
                step *= 2
            else:
                lo = probe
                break
    else:
        # walk forward to the first page that reaches it
        lo, hi, step = current, None, 1
        while hi is None:
            probe = min(total, lo + step)
            if reaches(probe):
                hi = probe
            elif probe >= total:
                return None
            else:
                lo = probe
                step *= 2
    while hi - lo > 1:
        middle = (lo + hi) // 2
        if reaches(middle): hi = middle
        else: lo = middle
    print(strings.AO3_INFO_RESUME_FOUND.format(hi, date))
    return hi


def force_stop(job: Job) -> dict | None:
    """End a run at once, as a stop would, without waiting for its thread to notice.

    A stop sets a flag the run reads at its next gate; a run whose thread never reaches one -
    stuck in a request, waiting on a page that has gone - stays 'running', and holds the
    helper so nothing else can start. This does what the end of a stop does, here and now:
    the record says `stopped` with the reason, keeps its log and issues, and is **frozen**
    so the thread cannot write over it if it wakes; the run is marked done, so the helper
    takes a new one; and a page still listening is told it finished.

    The record goes back to the page to write rather than being saved here. A run that is
    not in the background writes its history through the page that started it, and when that
    page has gone - the usual reason to be here - a save would wait on nobody. The page
    asking holds the library, so it writes it. Returns `{file, data}`, or None when the run
    had no record yet (it never reached the login) or had already ended.

    A thread that wakes later unwinds at its next gate, since `cancel` is set; it may finish
    what it was in the middle of first.
    """

    job.cancel.set()
    job.held.clear()
    if job.done.is_set(): return None

    written = None
    record = job.record
    if record is not None:
        try:
            record.collect(job.ao3)
        except Exception:
            pass
        try:
            record.data['log'].append(runs.stamped(strings.AO3_INFO_FORCE_STOPPED))
        except Exception:
            pass
        record.data['status'] = runs.STATUS_STOPPED
        record.data['error'] = strings.ERROR_FORCE_STOPPED
        record.data['finished'] = runs.now()
        record.frozen = True
        written = {'file': os.path.basename(record.path), 'data': runs.snapshot(record)}

    job.emit({'type': progress.MESSAGE, 'text': strings.AO3_INFO_FORCE_STOPPED})
    job.emit({'type': progress.FINISHED, 'cancelled': True, 'forced': True})
    job.library = None
    job.finished_at = time.monotonic()
    job.done.set()
    return written


def outcome_of(ao3, error: str = '') -> tuple[str, str]:
    """How a run that reached its end went, from what it could and could not get.

    - **failed**: its indexing failed everywhere it tried - nothing indexed - and nothing was
      downloaded (or nothing needed to be)
    - **partial**: some indexing failed (a listing page, a collection, a fic's own page), or
      a fic or a format could not be downloaded - and something still came of it
    - **success**: everything it set out to index and get, it did. Bookmarks that were never
      works (series, external, deleted) were never there to get, so they do not count

    Neither partial nor failed is ever a floor a quick scan measures back to. A failure
    FicHub made good in the end is not one.
    """

    gaps = index_gaps(ao3)
    failures = list(getattr(ao3, 'failures', None) or [])
    reindexed = getattr(ao3, 'reindexed', None) or set()
    downloaded = getattr(ao3, 'downloaded', None) or set()
    if gaps and not reindexed and not downloaded:
        return runs.STATUS_FAILED, error or strings.ERROR_ALL_INDEXING_FAILED
    if gaps or failures: return runs.STATUS_PARTIAL, error
    return runs.STATUS_SUCCESS, error


def close_record(job: Job, status: str, error: str = '') -> None:
    """Finish this run's history file, whatever happened to the run.

    A stop is `stopped`, not `failed`: the user asked for it and everything written stays
    written. Anything thrown in here is swallowed - a run that downloaded a library
    successfully must not be reported as failed because a note about it could not be saved.
    """

    if not job.record: return
    try:
        # older runs' logs go before this one's record is finished, so the line saying so is
        # in this run's own log
        if keeps_recent_logs_only(job):
            pruned = runs.prune_old_logs(job.record.fileops)
            if pruned:
                # said by hand: the run's own printing has ended by now
                said = strings.AO3_INFO_OLD_RUN_LOGS_REMOVED.format(pruned, runs.RECENT_RUN_LOGS)
                job.record.line(said)
                job.emit({'type': progress.MESSAGE, 'text': said})
    except Exception:
        pass
    try:
        if status == runs.STATUS_SUCCESS: status, error = outcome_of(job.ao3, error)
        job.record.collect(job.ao3)
        job.record.finish(status, error)
    except Exception:
        pass


def run_bookmarks(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """The 'download from ao3 link' action, pointed at the user's own bookmarks.

    Works already in the downloads folder are skipped, so a second run only picks up
    bookmarks added since the last one.
    """

    link = sorted_bookmarks_link(job)
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes
    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]

    # 0 means every page, which Ao3 expects as None
    pages = job.options['pages'] or None

    start = job.options['start']

    ao3 = Ao3(repo, fileops, downloadtypes, pages, job.options['series'],
              job.options['images'], progress=report, cancelled=job.cancel.is_set,
              start=start)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    restore_series(job, ao3)

    # indexing first: every bookmark gets its json before any work is downloaded, so an
    # interrupted run still leaves a complete index of what is bookmarked.
    records: list[dict] = []
    scoped = resumed_scope(job, fileops, ao3, report)
    if scoped is not None:
        # the earlier attempt got as far as checking its files: nothing left to index
        records = scoped
        mark_earlier(job, 'index', 'series', 'nonbookmarks')
    elif metadata:
        job.steps.start('index')
        progress.report(report, progress.PHASE, name=progress.INDEXING)
        print(strings.AO3_INFO_INDEXING)
        records = walk_listing(job, fileops, ao3, 'all', link, anchored=True,
                               ceiling=retry_ceiling(job), own_bookmarks=True)
        finish_walk_step(job, ao3, 'index')
        records = merge_by_work(records,
                                index_series_and_non_bookmarks(job, fileops, ao3, report))
    else:
        job.steps.skip('index')
        job.steps.skip('series')

    if downloadtypes and not job.cancel.is_set():
        job.steps.start('check')
        save_scope(job, records)
        # the index is what says how recently each work was updated, so this can only be
        # judged once indexing has run
        plan = plan_refresh(job, fileops, records, downloadtypes, report)
        # a run that wrote no index has no plan, and so no scan of the folder either - but
        # the listing it is about to walk still needs telling what is already here
        existing = plan['existing'] if records else shared.scan_downloaded_works(
            fileops.worksfolder, downloadtypes, storage=fileops.storage)
        # an out-of-date copy is not 'already downloaded', so it must not be skipped
        visited = shared.already_downloaded(existing, downloadtypes, records, plan['stale'])
        ao3.superseded = plan['superseded']
        job.steps.done('check')

        job.steps.start('download')
        progress.report(report, progress.PHASE, name=progress.DOWNLOADING)
        print(strings.AO3_INFO_DOWNLOADING)

        if can_use_index(job, records):
            # the index already knows every work number, so neither the listing nor each
            # work's page has to be read again. newest first, so a run that is stopped has
            # got through the fics most likely to be worth having
            ao3.download_indexed(newest_first(records), visited, existing,
                                 forced=bool(job.options.get('overwrite')))
        else:
            # the download walks the same listing, so it begins on the same page. with no
            # index to judge from, each work's page is: given the folder scan, every format is
            # fetched only when missing or older than the page says, or when overwriting
            ao3.existing_copies = existing
            ao3.overwriting = bool(job.options.get('overwrite'))
            ao3.judge_copy = lambda *copy: judge_long_way(job, ao3, *copy)
            try:
                ao3.download(parse_text.set_page_number(link, start), visited)
            finally:
                ao3.existing_copies = None
                ao3.judge_copy = None
        job.steps.done('download')
    else:
        # a metadata-only run, or one stopped during indexing: these never start
        job.steps.skip('check')
        job.steps.skip('download')

    # a run that leaves gaps should say which works they were, rather than leaving it to be
    # worked out from the log afterwards. outside the download block on purpose: a
    # metadata-only run downloads nothing and can still skip bookmarks that are not works
    finish_run(job, fileops, ao3, report)


def say_unsure_files(job: Job) -> None:
    """At the end of a run, how many files it came across with no date in the app's own form in
    their names: the page suggests refreshing the library and dating them in Resolve issues, so
    the next run need not ask about them again. Nothing is said for none."""

    count = len(getattr(job, 'unsure_files', ()) or ())
    if count: job.emit({'type': progress.UNSURE_FILES, 'count': count})


def judge_long_way(job: Job, ao3, work_url: str, number: str, filetype: str, stamp: str,
                   copy: dict) -> bool:
    """The long way round's copy it cannot judge alone, put through the same questions a scan
    from the index asks: a name with no date in the app's own form (`ask_about_unsure_copies`,
    undated ones included - there was no undated question on this path), and, overwriting, a
    copy newer than the page (`keep_newer_copies`). Whether to fetch the format; a format to
    fetch is named in `superseded`, so the new file replaces the old."""

    record = {'id': number, 'link': work_url, 'date_updated': stamp}
    existing = {number: {filetype.upper(): copy}}
    plan = shared.plan_downloads([record], existing, [filetype], overwrite=ao3.overwriting)
    plan['overwrite'] = ao3.overwriting
    ask_about_unsure_copies(job, [record], existing, plan, [filetype],
                            overwriting=ao3.overwriting)
    if ao3.overwriting: keep_newer_copies(job, [record], existing, plan, [filetype])
    path = (plan['superseded'].get(work_url) or {}).get(filetype)
    if path:
        ao3.superseded.setdefault(work_url, {})[filetype] = path
        return True
    return False


def can_use_index(job: Job, records: list[dict]) -> bool:
    """Whether the full scan's download phase can work from the index instead of opening
    each work's page.

    It needs an index to work from - a run with JSON unticked has none, which is in practice
    the one case that goes the long way round - and must not want embedded images, which are
    found on the work page. (Mark-as-read and series links used to send it the long way too;
    neither does any more.) The long way never writes the index: a run with no JSON chose not
    to keep one.
    """

    if not records: return False
    if job.options['images']: return False
    return True


def index_marked_series(job: Job, ao3: Ao3, report) -> list[dict]:
    """Walk every series marked for walkthrough during indexing, and return the works it
    indexed, for the download step to take with the rest.

    Its own step, after indexing is over, so every work a listing holds has been read from
    the listing first. A series you bookmarked is always marked; the series your works are
    part of are marked only when the run was asked to (`series`). With nothing marked the
    step is skipped - a run with no series to walk has not gone wrong.
    """

    # a resumed run carries on from the series the earlier attempt had already walked
    earlier = job.earlier_progress() if job.resume else {}
    done = [str(x) for x in earlier.get('seriesDone') or []]
    walked = [str(x) for x in earlier.get('seriesWorks') or []]
    carried = records_by_id(ao3.fileops, walked) if walked else []

    if job.cancel.is_set() or not ao3.series_marked:
        if not job.cancel.is_set(): print(strings.AO3_INFO_SERIES_NONE)
        job.steps.skip('series')
        return carried
    if done and all(series_id in ao3.series_read for series_id in ao3.series_marked):
        print(strings.AO3_INFO_RESUME_SERIES_DONE)
        mark_earlier(job, 'series')
        return carried

    def on_series(series_id: str, works: list[str]) -> None:
        done.append(series_id)
        walked.extend(works)
        job.checkpoint(seriesDone=done, seriesWorks=walked,
                       seriesMarked=list(ao3.series_marked.values()))

    job.steps.start('series')
    job.checkpoint(seriesMarked=list(ao3.series_marked.values()))
    progress.report(report, progress.PHASE, name=progress.INDEXING)
    print(strings.AO3_INFO_SERIES_STEP.format(len(ao3.series_marked)))
    ao3.on_series = on_series
    try:
        works = ao3.walk_marked_series()
    finally:
        ao3.on_series = None
    job.steps.done('series')
    return merge_by_work(carried, works)


def index_series_and_non_bookmarks(job: Job, fileops: FileOps, ao3: Ao3, report) -> list[dict]:
    """The series step, and - when the run was asked to - the non-bookmarks step after it.

    Returns every work either one indexed, for the download step to take with the rest.
    """

    non_bookmarks = mark_non_bookmarks(job, fileops, ao3) if checks_non_bookmarks(job) else None
    walked = index_marked_series(job, ao3, report)
    if non_bookmarks is None: return walked
    return merge_by_work(walked, update_non_bookmarks(job, ao3, non_bookmarks, report))


def non_bookmarks_in(records: list[dict]) -> list[dict]:
    """The works in the index you have not bookmarked yourself - there because something else
    led a run to them, such as another work's series.

    Every entry that does not say `bookmarked: true` - one that says nothing about it is not
    counted as a bookmark (see `ao3.was_bookmark`).
    """

    return [record for record in records
            if record.get(strings.BOOKMARKED_FIELD) is not True
            and (record.get(strings.BOOKMARK_TYPE_FIELD) or strings.BOOKMARK_TYPE_WORK)
            == strings.BOOKMARK_TYPE_WORK]


def series_ids_of(record: dict) -> list[tuple[str, str]]:
    """Every series a work's entry says it belongs to or was found through, as (id, title)."""

    found: dict[str, str] = {}
    for member in record.get(strings.SERIES_MEMBERSHIP_FIELD) or []:
        if isinstance(member, dict) and member.get('id'):
            found.setdefault(str(member['id']), str(member.get('title') or ''))
    for series_id in record.get(indexing.FROM_SERIES) or []:
        if series_id: found.setdefault(str(series_id), '')
    return list(found.items())


def mark_non_bookmarks(job: Job, fileops: FileOps, ao3: Ao3) -> list[dict]:
    """Find the non-bookmarks this run has not already read, and mark their series.

    No requests. Most non-bookmarks are in the index because of a series, and walking the
    series re-reads 20 of its works per request - far cheaper than opening each work. So
    their series are marked for walkthrough here, just before that step, and only what the
    walk does not reach is left for `update_non_bookmarks` to open one at a time.

    A work already indexed this run - found in your bookmarks after all, or through a series
    already walked - is left out: it is as fresh as it can be.
    """

    found = [record for record in non_bookmarks_in(shared.read_index(fileops))
             if str(record.get('id') or '') not in ao3.reindexed]
    print(strings.AO3_INFO_NON_BOOKMARKS.format(len(found)))
    for record in found:
        for series_id, title in series_ids_of(record):
            ao3.mark_series(series_id, title)
    return found


def update_non_bookmarks(job: Job, ao3: Ao3, found: list[dict], report) -> list[dict]:
    """Re-read each non-bookmark the series walk did not reach, from its own page.

    One request per work: a work in no series, or one its series no longer lists, has no
    cheaper way to be read. **Not narrowed by a date range or a floor.** Those are judged on
    your bookmarks listing, which never shows a non-bookmark, so there is nothing to measure
    one against without reading it - the option's own wording says so.

    A work that will not read is recorded as a failure and keeps the entry it had. Returns
    the works it re-read, which go on to be downloaded with the rest of the run.
    """

    left = newest_first([record for record in found
                         if str(record.get('id') or '') not in ao3.reindexed])
    # a resumed run does not re-read the ones the earlier attempt already had
    before = [str(x) for x in (job.earlier_progress().get('nonBookmarksDone') or [])] \
        if job.resume else []
    carried = [record for record in left if str(record.get('id') or '') in before]
    left = [record for record in left if str(record.get('id') or '') not in before]
    finished = list(before)
    if job.cancel.is_set() or not left:
        if job.cancel.is_set():
            job.steps.skip('nonbookmarks')
        elif carried:
            print(strings.AO3_INFO_RESUME_NON_BOOKMARKS_DONE)
            mark_earlier(job, 'nonbookmarks')
        else:
            print(strings.AO3_INFO_NON_BOOKMARKS_NONE_LEFT)
            job.steps.skip('nonbookmarks')
        return carried

    job.steps.start('nonbookmarks')
    progress.report(report, progress.PHASE, name=progress.INDEXING)
    print(strings.AO3_INFO_NON_BOOKMARKS_READING.format(len(left)))
    fresh: list[dict] = list(carried)
    for done, record in enumerate(left, start=1):
        if job.cancel.is_set(): break
        if job.skipping():
            print(strings.AO3_INFO_STEP_SKIPPED)
            job.steps.skip('nonbookmarks')
            return fresh
        link = record.get('link') or ''
        title = record.get('title') or link
        print(strings.AO3_INFO_UPDATE_WORK.format(done, len(left), title))
        progress.report(report, progress.WORK, title=title, link=link, done=done,
                        total=len(left), phase=progress.INDEXING)
        try:
            fresh.append(ao3.refresh_one(record))
        except exceptions.CancelledException:
            print(strings.INFO_CANCELLED)
            break
        except exceptions.SessionExpiredException:
            raise
        except Exception as e:
            ao3.record_failure(link, e)
            ao3.log_error({'link': link}, e)
        finished.append(str(record.get('id') or ''))
        job.checkpoint(nonBookmarksDone=finished)
    job.steps.done('nonbookmarks')
    return fresh


def bookmarks_link(job: Job) -> str:
    return f'{strings.AO3_BASE_URL}/users/{job.username}/bookmarks'


# the two orders a custom run can read your bookmarks listing in
LISTING_ORDERS = ('bookmarked', 'updated')


def listing_order(job: Job) -> str:
    """The order a custom run reads your bookmarks listing in: as asked, else each shape's
    own - a date range by date updated, everything else by date bookmarked - so a run that
    was not asked (an older page, a retry of an older run) does exactly what it always did."""

    asked = job.options.get('order')
    if asked in LISTING_ORDERS: return asked
    return 'updated' if job.options.get('dates') else 'bookmarked'


def sorted_bookmarks_link(job: Job) -> str:
    """Your bookmarks, newest bookmarked first - asked for by name.

    It is also ao3's default order, but a run that may be resumed has to be sure of it:
    finding where an earlier attempt stopped goes by the date each bookmark was made.
    """

    return f'{bookmarks_link(job)}?{strings.AO3_SORT_BY_BOOKMARKED}'


def index_new_bookmarks(job: Job, fileops: FileOps, ao3: Ao3, report) -> list[dict]:
    """Index from the newest bookmark until one already held, and return what was new."""

    job.steps.start('index')
    progress.report(report, progress.PHASE, name=progress.INDEXING)
    print(strings.AO3_INFO_INDEXING_NEW)

    known = shared.indexed_work_ids(fileops)
    # a retry starts at its ceiling, as every walk does; a first attempt is the plain walk
    if job.resume:
        records = walk_listing(job, fileops, ao3, 'new', bookmarks_link(job), anchored=True,
                               ceiling=retry_ceiling(job), known=known, own_bookmarks=True)
    else:
        records = ao3.get_metadata(bookmarks_link(job), job.options['workdates'], known=known,
                                   own_bookmarks=True)

    print(strings.AO3_INFO_NEW_FOUND.format(len(records)) if records
          else strings.AO3_INFO_NEW_NONE)
    finish_walk_step(job, ao3, 'index')
    # a series you bookmarked since last time is walked, and its works downloaded with the rest
    return merge_by_work(records, index_marked_series(job, ao3, report))


def download_planned(job: Job, fileops: FileOps, ao3: Ao3, records: list[dict],
                     downloadtypes: list[str], report,
                     overwrite: list[str] | None = None, keep_existing: bool = False) -> None:
    """Settle anything undated among these works, then download them.

    The same rule a full run downloads by, applied to whichever slice of the index the
    caller has in hand rather than to the whole listing.

    Works are fetched **newest first**. A long run then gets through the fics you are most
    likely to be waiting on before the ones that have not moved in years, which matters
    because a run can be stopped and where it got to should be the useful half.
    """

    if not records or not downloadtypes or job.cancel.is_set():
        job.steps.skip('check')
        job.steps.skip('download')
        return

    job.steps.start('check')
    save_scope(job, records)
    plan = plan_refresh(job, fileops, records, downloadtypes, report, overwrite)
    if keep_existing:
        keep_existing_copies(records, plan, downloadtypes)
        ao3.keep_message = strings.AO3_INFO_KEEPING_YOURS
    # an out-of-date copy is not 'already downloaded', so it must not be skipped
    visited = shared.already_downloaded(plan['existing'], downloadtypes, records, plan['stale'])
    if ao3.held_only:
        # a format fetched only to replace a copy is not missing from a work without one
        behind = {parse_text.get_work_number(x) for x in plan['stale']}
        for record in records:
            work = str(record.get('id') or '')
            have = {str(x).upper() for x in (plan['existing'].get(work) or {})}
            if work not in behind and record.get('link') and all(
                    x.upper() in have or x.upper() in ao3.held_only for x in downloadtypes):
                visited.append(record['link'])
    ao3.superseded = plan['superseded']
    ao3.keep_formats = plan.get('keep') or {}
    ao3.keep_said = plan.get('keptSaid') or set()
    job.steps.done('check')

    job.steps.start('download')
    progress.report(report, progress.PHASE, name=progress.DOWNLOADING)
    print(strings.AO3_INFO_DOWNLOADING)
    ao3.download_indexed(newest_first(records), visited, plan['existing'],
                         forced=set(overwrite) if overwrite is not None
                         else bool(job.options.get('overwrite')))
    job.steps.done('download')


def fill_missing_formats(job: Job, fileops: FileOps, ao3: Ao3, skip: set[str],
                         downloadtypes: list[str], report, reindex: bool = True,
                         only: set[str] | None = None) -> None:
    """Finished works, already indexed, simply missing a format this run asked for.

    The case the other two passes leave behind: not new, so the newest-first walk never
    reached it, and not unfinished, so the update pass ignored it. A fic indexed and saved
    as html long ago, on a run that now asks for pdf as well, is only findable this way.

    A fic that needs fetching is **re-read first**, exactly as the update pass does, so the
    file about to be written is named for the version ao3 has now rather than for whatever
    the index last recorded. Getting that wrong would write a new file carrying an old date,
    which is the one thing every later run's idea of 'outdated' depends on.

    Only the missing formats are fetched, never the whole set. A work that has html and
    wants pdf costs its re-read plus one transfer here, not two transfers - rate limit is
    the scarce thing, and re-fetching a file already on disk spends it for nothing.
    """

    if not downloadtypes or job.cancel.is_set():
        job.steps.skip('gaps')
        return

    job.steps.start('gaps')
    progress.report(report, progress.PHASE, name=progress.CHECKING_FILES)
    print(strings.AO3_INFO_CHECKING_GAPS)

    index = shared.read_index(fileops)
    unfinished = {str(x.get('id') or '') for x in shared.incomplete_works(index)}
    existing = shared.scan_downloaded_works(fileops.worksfolder, downloadtypes,
                                            storage=fileops.storage)

    gaps: list[tuple[dict, list[str]]] = []
    for record in newest_first(index):
        work = str(record.get('id') or '')
        if not work or not record.get('link'): continue
        if work in skip or work in unfinished: continue
        # `only` narrows this to the works a run actually covered. a full scan fills the
        # gaps in what it just walked, not in every fic the index has ever held - some of
        # those are no longer bookmarked, and fetching them would be a surprise
        if only is not None and work not in only: continue
        have = existing.get(work, {})
        missing = [x for x in downloadtypes if x.upper() not in have]
        if missing: gaps.append((record, missing))

    if not gaps:
        print(strings.AO3_INFO_GAPS_NONE)
        # nothing to fill is not a failure - it is the answer most runs get
        job.steps.done('gaps')
        return

    print(strings.AO3_INFO_GAPS_FOUND.format(len(gaps)))
    progress.report(report, progress.PHASE, name=progress.DOWNLOADING)

    maximum = fileops.get_ini_value_integer(
        strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
    wanted = ao3.filetypes
    abandoned = False
    try:
        for done, (record, missing) in enumerate(gaps, start=1):
            if job.cancel.is_set(): break
            if job.skipping():
                print(strings.AO3_INFO_STEP_SKIPPED)
                abandoned = True
                break
            log: dict = {'link': record['link']}
            try:
                ao3.check_cancelled()
                print(strings.AO3_INFO_GAP_WORK.format(
                    done, len(gaps), record.get('title') or record['link'],
                    ', '.join(missing)))
                progress.report(ao3.progress, progress.WORK,
                                title=record.get('title') or '', link=record['link'],
                                done=done, total=len(gaps), phase=progress.DOWNLOADING)
                # the entry first, then the file - so the name carries the version ao3 has
                # now rather than the one the index happened to be holding. skipped when
                # the caller has only just read the listing: the entry is already current,
                # and re-reading it would cost a request per fic to learn nothing.
                fresh = record
                if reindex:
                    fresh = ao3.refresh_one(record)
                    print(strings.AO3_INFO_GAP_INDEXED)
                ao3.filetypes = missing
                ao3.download_one_indexed(fresh, maximum, log, done, len(gaps))
            except exceptions.CancelledException:
                break
            except exceptions.SessionExpiredException:
                raise  # every fic after this one would fail the same way
            except Exception as e:
                ao3.record_failure(record['link'], e)
                ao3.log_error(log, e)
    finally:
        # the caller's Ao3 is borrowed, not ours to leave reconfigured
        ao3.filetypes = wanted
    job.steps.skip('gaps') if abandoned else job.steps.done('gaps')


def save_images(job: Job, fileops: FileOps, ao3: Ao3, records: list[dict], report) -> None:
    """Fetch each work's page, purely for the images embedded in it.

    Runs **after** the files themselves are down, never instead of them. The indexed path
    reads no work page, so this has to fetch one per fic - an extra request each, which is
    why only a custom run offers it and why it says so plainly before you start.

    A work page that will not load costs its images and nothing else. This is the last thing
    a run does, and losing a second copy of some pictures is not worth ending it over.
    """

    if not records or job.cancel.is_set():
        job.steps.skip('images')
        return

    job.steps.start('images')
    progress.report(report, progress.PHASE, name=progress.DOWNLOADING)
    print(strings.AO3_INFO_IMAGES_START)

    maximum = fileops.get_ini_value_integer(
        strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
    saved = 0
    done = 0

    abandoned = False
    for record in records:
        if job.cancel.is_set(): break
        if job.skipping():
            print(strings.AO3_INFO_STEP_SKIPPED)
            abandoned = True
            break
        if not record.get('id'): continue
        done += 1
        try:
            ao3.check_cancelled()
            progress.report(ao3.progress, progress.WORK, title=record.get('title') or '',
                            link=record.get('link') or '', done=done, total=len(records),
                            phase=progress.DOWNLOADING)
            count = ao3.save_images_for(record, maximum)
            saved += count
            print(strings.AO3_INFO_IMAGE_WORK.format(
                done, len(records), record.get('title') or record.get('id'), count))
        except exceptions.CancelledException:
            break
        except exceptions.SessionExpiredException:
            raise  # every work page after this one would come back logged out
        except Exception as e:
            ao3.record_failure(record.get('link') or '', e)
            ao3.log_error({'link': record.get('link') or ''}, e)

    print(strings.AO3_INFO_IMAGES_DONE.format(saved, done))
    job.steps.skip('images') if abandoned else job.steps.done('images')


def run_new(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Index only the bookmarks added since last time, then download them."""

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    ao3 = Ao3(repo, fileops, downloadtypes, None, False, job.options['images'],
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    records = index_new_bookmarks(job, fileops, ao3, report)
    download_planned(job, fileops, ao3, records, downloadtypes, report)
    finish_run(job, fileops, ao3, report)


def run_sync(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """New bookmarks, then the unfinished ones, then whatever formats are still missing.

    Three passes, each covering what the one before it cannot, and none of them walking the
    whole listing - which is what makes this the one to run routinely. What it gives up is
    stated in the ui and has to be acknowledged: a fic the index already calls finished is
    never re-read, so chapters added to it afterwards are not noticed, and a gap left in the
    index by an interrupted run stays a gap because the walk stops at the first fic it
    recognises. A full scan is the answer to both.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    # one Ao3 for all three passes, so every failure lands in the same list and the run
    # names them once at the end rather than three times over
    ao3 = Ao3(repo, fileops, downloadtypes, None, False, job.options['images'],
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    records = index_new_bookmarks(job, fileops, ao3, report)
    download_planned(job, fileops, ao3, records, downloadtypes, report)

    if not job.cancel.is_set():
        update_incomplete(job, fileops, ao3, downloadtypes, report)

    if not job.cancel.is_set():
        # the works the first two passes already dealt with are not gaps
        handled = {str(x.get('id') or '') for x in records}
        fill_missing_formats(job, fileops, ao3, handled, downloadtypes, report)

    finish_run(job, fileops, ao3, report)


def run_work(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Index one fic and download it, from a link or a bare work number.

    **It always replaces whatever copy you already have.** Every other run is pointed at a
    library and has to be careful about what it spends, so it skips anything already on disk
    and current. This one is pointed at a single fic by hand: asking for it and being told
    nothing happened because the copy looked fine is not the answer anybody came for, and
    the whole cost of being wrong is one request per format, for one work.

    So the option is forced on rather than offered - the ui does not show the checkbox for
    this run, because a box that cannot be unticked is not a choice. Setting it on the job's
    own options is what makes the history file say what the run actually did.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    link = work_link(job.url)
    if not link:
        raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)

    job.options['overwrite'] = True

    ao3 = Ao3(repo, fileops, downloadtypes, None, job.options['series'], job.options['images'],
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    work = parse_text.get_work_number(link) or ''
    job.steps.start('index')
    progress.report(report, progress.PHASE, name=progress.INDEXING)
    print(strings.AO3_INFO_ONE_WORK.format(work))
    try:
        record = ao3.index_one_work(link, find_existing=existing_entry(ao3, fileops, work))
    except (exceptions.CancelledException, exceptions.SessionExpiredException):
        raise
    except Exception as e:
        # a work ao3 will not show us - deleted, hidden, locked - is a failure of this one
        # work rather than of the run: FicHub may still have it, and is asked at the end
        ao3.record_failure(link, e)
        ao3.log_error({'link': link}, e)
        ao3.index_failures.append({'kind': 'work', 'id': str(work), 'link': link, 'error': str(e),
                                   **failure_reason(e)})
        print(strings.AO3_INFO_ONE_WORK_UNREADABLE.format(e))
        print(strings.AO3_INFO_ONE_WORK_NOT_INDEXED.format(work))
        job.steps.fail_current()
        # nothing to walk or download from ao3 now - said, rather than left waiting
        for step in ('series', 'check', 'download'): job.steps.skip(step)
        finish_run(job, fileops, ao3, report)
        return
    say_indexed(ao3, work)
    ao3.mark_series_of(record)
    job.steps.done('index')

    records = merge_by_work([record], index_marked_series(job, ao3, report))
    # the fic asked for is replaced whatever copy there is; the rest of its series is
    # fetched only where it is missing or behind, as any run would
    download_planned(job, fileops, ao3, records, downloadtypes, report,
                     overwrite=[record.get('link') or link])
    print(strings.AO3_INFO_ONE_WORK_DONE.format(work))
    finish_run(job, fileops, ao3, report)


def say_indexed(ao3, work: str) -> None:
    """Say whether a fic's index entry was written, by its number.

    Read off what was saved (`reindexed`), not assumed from the lookup having worked: a save
    that failed is swallowed and logged by `save_metadata`, and the run must not claim it.
    """

    try:
        written = str(work) in ao3.reindexed
    except Exception:
        written = False
    print((strings.AO3_INFO_ONE_WORK_INDEXED if written
           else strings.AO3_INFO_ONE_WORK_NOT_INDEXED).format(work))


def run_works(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """The single-fic run over a list: index each fic, then download them all.

    Every fic is looked up before anything is downloaded, as a scan indexes before it
    downloads, and one that ao3 will not show is recorded and passed over rather than ending
    the run. FicHub is asked about all of those **once, at the end** (`finish_run`), not
    after each fic - a question per fic would hold the run up at every one.

    It replaces the copies of the fics named, as the single-fic run does, and only those -
    the rest of a series it goes on to walk is fetched where it is missing or behind.
    """

    run_fic_list(job, fileops, repo, report, importing=False)


def work_numbers(given) -> list[str]:
    """A list of work numbers from a request: anything that is not one is dropped."""

    if not isinstance(given, list): return []
    return [str(x) for x in given if str(x).isdigit()]


def run_import(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Index the works whose files were found in your library with no index entry, and fetch
    the formats asked for.

    The several-fics run over the works the page found, with three differences, all because
    these are files you already have rather than fics asked for by hand:

    - each entry it makes is marked `from_import` (unless the work turns out to be your
      bookmark), so the Works tab lists it as *Imported*;
    - it **never overwrites**. A copy is replaced only when ao3 has a newer version than the
      date in its name, and only when the import was told to (`replaceOutdated`); otherwise
      only the formats you do not have are fetched;
    - undated files are left alone without asking: the page has just offered to date them, and
      a file left undated there was left that way on purpose.

    No series walk: an import is about what is in the folder.
    """

    run_fic_list(job, fileops, repo, report, importing=True)


def run_fic_list(job: Job, fileops: FileOps, repo: Repository, report, importing: bool) -> None:
    """Look up a list of fics, then download them - several fics, or an import."""

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    links = [x for x in job.url.split('\n') if x.strip()]
    if not links:
        raise exceptions.InvalidLinkException(
            strings.ERROR_NO_IMPORT_WORKS if importing else strings.ERROR_NO_WORK_LINKS)

    # a list asked for by hand replaces what it names; an import never does
    job.options['overwrite'] = not importing
    if importing:
        job.options['series'] = False
    ao3 = Ao3(repo, fileops, downloadtypes, None, job.options['series'], job.options['images'],
              progress=report, cancelled=job.cancel.is_set)
    if importing: ao3.origin_field = strings.FROM_IMPORT_FIELD
    job.ao3 = ao3

    job.steps.start('index')
    progress.report(report, progress.PHASE, name=progress.INDEXING)
    print((strings.AO3_INFO_IMPORT_WORKS if importing
           else strings.AO3_INFO_MANY_WORKS).format(len(links)))

    # carrying on: a fic the earlier attempt saved in every format is done - not looked up,
    # not fetched. one partway through is looked up and only its missing formats fetched
    # (`formats_done`); one it never reached is done in full
    wanted = {x.upper() for x in downloadtypes}
    finished = {work for work, saved in (ao3.formats_done or {}).items()
                if wanted and wanted <= set(saved)} if job.resume else set()

    records: list[dict] = []
    asked: list[str] = []
    for done, link in enumerate(links, start=1):
        if job.cancel.is_set(): break
        if job.skipping():
            print(strings.AO3_INFO_STEP_SKIPPED)
            break
        work = parse_text.get_work_number(link) or ''
        if work in finished:
            print(strings.AO3_INFO_RETRY_FIC_DONE.format(done, len(links), work))
            continue
        print(strings.AO3_INFO_MANY_WORK.format(done, len(links), work))
        progress.report(report, progress.WORK, title=link, link=link, done=done,
                        total=len(links), phase=progress.INDEXING)
        try:
            record = ao3.index_one_work(link, find_existing=existing_entry(ao3, fileops, work))
        except (exceptions.CancelledException, exceptions.SessionExpiredException):
            raise
        except Exception as e:
            # one fic ao3 will not show is that fic's failure, never the run's
            ao3.record_failure(link, e)
            ao3.log_error({'link': link}, e)
            ao3.index_failures.append({'kind': 'work', 'id': str(work), 'link': link,
                                       'error': str(e), **failure_reason(e)})
            print(strings.AO3_INFO_ONE_WORK_UNREADABLE.format(e))
            print(strings.AO3_INFO_ONE_WORK_NOT_INDEXED.format(work))
            continue
        say_indexed(ao3, work)
        ao3.mark_series_of(record)
        records.append(record)
        asked.append(record.get('link') or link)
    if job.cancel.is_set():
        finish_run(job, fileops, ao3, report)
        return
    # a fic whose page would not read was not indexed: the step says so, and the run goes on
    # with the rest - the fics themselves are named in its issues
    if any(gap.get('kind') == 'work' for gap in ao3.index_failures): job.steps.fail('index')
    else: job.steps.done('index')

    if importing:
        name_files_from_index(fileops, records)
        replace = bool(job.options.get('replaceOutdated'))
        index_only = set(job.options.get('indexOnly') or [])
        updating = [r for r in records if str(r.get('id') or '') not in index_only]
        if index_only and len(updating) < len(records):
            print(strings.AO3_INFO_IMPORT_INDEX_ONLY.format(len(records) - len(updating)))
        if replace:
            # replacing outdated copies covers every format a work has, not only those asked
            # for: the others are fetched only where a copy is there to be replaced
            asked_for = {x.upper() for x in downloadtypes}
            ao3.held_only = {x for x in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES if x not in asked_for}
            downloadtypes = downloadtypes + [x for x in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES
                                             if x in ao3.held_only]
            ao3.filetypes = downloadtypes
        elif downloadtypes: print(strings.AO3_INFO_IMPORT_KEEPING)
        download_planned(job, fileops, ao3, updating, downloadtypes, report,
                         keep_existing=not replace)
    else:
        records = merge_by_work(records, index_marked_series(job, ao3, report))
        download_planned(job, fileops, ao3, records, downloadtypes, report, overwrite=asked)
    finish_run(job, fileops, ao3, report)


def run_quick(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """A full scan's shape, stopping where ao3 stopped changing things.

    It walks the bookmarks listing **sorted by when ao3 last updated each work** and stops
    at the first one older than the last run that actually finished. Everything past that
    point is, by definition, a work ao3 has not touched since we last looked.

    The sort is not optional. Verified against the live site: the default listing is
    ordered by when each work was *bookmarked* and jumps about by years, so this walk down
    an unsorted listing would stop after a fic or two and miss nearly everything.

    With no completed run on record there is no floor, so it reads the whole listing - the
    honest answer the first time, rather than a short walk from a date it invented.

    A date range replaces the floor it works out for itself with one the user gave, and from
    there it is the custom run's window in every respect - same walk, same stop, same per-fic
    pass. The two are alternatives because they are the same mechanism given a different
    number, and there is no sense in measuring back to both.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes

    ao3 = Ao3(repo, fileops, downloadtypes, None, job.options['series'], False,
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3
    restore_series(job, ao3)

    scoped = resumed_scope(job, fileops, ao3, report)
    if scoped is not None:
        # the earlier attempt got as far as checking its files: nothing left to index
        mark_earlier(job, 'bookmarked', 'index', 'series', 'nonbookmarks')
        download_planned(job, fileops, ao3, scoped, downloadtypes, report)
        finish_run(job, fileops, ao3, report)
        return

    # a date range gives both walks their floor directly, and a ceiling too; otherwise the
    # floor comes from an earlier scan
    window = bool(job.options['dates'])
    ceiling = range_day(job, 'dateTo') if window else ''
    earlier = job.earlier_progress()
    if job.resume and job.baseline:
        # a resumed scan finishes the first attempt's work, which reached up to the moment
        # it logged in. anything changed since is the next scan's to find
        started = ao3_day(job.baseline, job.ao3_zone)
        ceiling = min(ceiling, started) if ceiling else started

    # the user may have picked the scan to measure back to, in which case nothing is worked
    # out or asked
    # the floor is kept as the UTC moment it stands for (`floor_at`) and compared as the day
    # that moment is in the person's AO3 zone (`floor`)
    floor_at = (chosen_floor_at(fileops, job.options['floorRun'])
                if job.options.get('floorRun') else '')
    if job.resume and 'floor' in earlier:
        # the floor the first attempt measured back to, not one worked out afresh - the runs
        # on record have changed since, and this is still that run. an older record kept a day
        floor_at = str(earlier.get('floor') or '')
        floor = ao3_day(floor_at, job.ao3_zone)
        print(strings.AO3_INFO_RESUME_FLOOR.format(floor or strings.AO3_INFO_DATE_ANY))
    elif window:
        floor_at = job.options['dateFrom']
        floor = range_day(job, 'dateFrom')
        print(strings.AO3_INFO_QUICK_WINDOW.format(floor or strings.AO3_INFO_DATE_ANY,
                                                    ceiling or strings.AO3_INFO_DATE_NOW))
    elif floor_at:
        floor = ao3_day(floor_at, job.ao3_zone)
        print(strings.AO3_INFO_QUICK_CHOSEN_FLOOR.format(floor))
    else:
        if job.options.get('floorRun'):
            # it was checked when the run was started, so this is a history file removed in
            # between. falling back to the usual rules beats guessing at a date
            print(strings.AO3_INFO_QUICK_CHOSEN_GONE)
        floor_at = quick_scan_floor_at(fileops)
        floor = ao3_day(floor_at, job.ao3_zone)
        if floor:
            print(strings.AO3_INFO_QUICK_FLOOR.format(floor))
        else:
            # nothing qualifies as a floor, but an index already here is worth measuring from
            # if the user says so - see settle_quick_floor
            floor_at = settle_quick_floor(job, fileops, report)
            floor = ao3_day(floor_at, job.ao3_zone)
            if not floor: print(strings.AO3_INFO_QUICK_NO_FLOOR)
    job.checkpoint(floor=floor_at)

    records: list[dict] = []
    if metadata:
        progress.report(report, progress.PHASE, name=progress.INDEXING)
        print(strings.AO3_INFO_INDEXING)

        # 1. new bookmarks, newest bookmarked first, back to the floor. this is the pass the
        # updated-date walk cannot do: a fic bookmarked yesterday that ao3 last updated in
        # 2019 sits far below the floor on that listing and would never be reached
        job.steps.start('bookmarked')
        print(strings.AO3_INFO_QUICK_BOOKMARKED.format(floor or strings.AO3_INFO_DATE_ANY))
        # a retry starts at its ceiling - the first attempt's start, or a date range's end -
        # and leaves out anything bookmarked after it. but not a date range with no floor:
        # then this walk is also the updated-date half, and dates updated are in no order here
        by_bookmarked = walk_listing(
            job, fileops, ao3, 'bookmarked', sorted_bookmarks_link(job), anchored=True,
            ceiling=ceiling if not window or floor else '',
            stop_before=floor, stop_on='bookmarked', own_bookmarks=True)
        finish_walk_step(job, ao3, 'bookmarked')

        # 2. fics ao3 has changed since the floor, newest updated first - the ones already
        # bookmarked before it, which the first pass stopped short of
        by_updated: list[dict] = []
        if not floor:
            # with nothing to stop at, the first pass read every bookmark already. a second
            # full walk would cost a request per 20 works to learn nothing new
            print(strings.AO3_INFO_QUICK_UPDATED_NOT_NEEDED)
            job.steps.skip('index')
        elif not job.cancel.is_set():
            job.steps.start('index')
            print(strings.AO3_INFO_QUICK_UPDATED.format(floor))
            # a retry picks it up from the date updated it had reached (`find_anchor`): a fic
            # ao3 updated since jumps to the top, so its page is found by date, not by number
            by_updated = walk_listing(
                job, fileops, ao3, 'updated', f'{bookmarks_link(job)}?{strings.AO3_SORT_BY_UPDATED}',
                anchored=False, ceiling=ceiling, stop_before=floor, own_bookmarks=True)
            finish_walk_step(job, ao3, 'index')

        if window:
            # a listing cannot be entered at a date, so both walks start at the newest and read
            # past the ceiling on the way down. what lands above it is indexed but not taken:
            # each walk keeps only the works whose own date - the one it walked by - is in range
            if not floor:
                # the first walk read everything, so the updated-date half comes from it too
                by_updated = by_bookmarked
            by_bookmarked = works_dated_between(by_bookmarked, 'date_bookmarked', floor, ceiling)
            by_updated = works_dated_between(by_updated, 'date_updated', floor, ceiling)
        elif job.resume and ceiling:
            # a walk from the top reads past the first attempt's start on the way down. only
            # what ao3 updated up to then is this run's to download
            by_updated = works_dated_between(by_updated, 'date_updated', floor, ceiling)
            print(strings.AO3_INFO_RESUME_CEILING.format(ceiling, len(by_updated)))

        # either scan may have found a fic; the other may have found it too
        records = merge_by_work(by_bookmarked, by_updated)
        if window: print(strings.AO3_INFO_QUICK_IN_WINDOW.format(len(records)))
        records = merge_by_work(records,
                                index_series_and_non_bookmarks(job, fileops, ao3, report))
    else:
        job.steps.skip('bookmarked')
        job.steps.skip('index')
        job.steps.skip('series')

    download_planned(job, fileops, ao3, records, downloadtypes, report)
    finish_run(job, fileops, ao3, report)


def works_dated_between(records: list[dict], field: str, start: str, end: str) -> list[dict]:
    """The records whose `field` date falls inside a window, both ends counting.

    An empty end means no limit there. A record with no readable date for that field is left
    out rather than guessed at - the same rule `works_updated_between` follows, because it
    cannot be placed in the window.
    """

    chosen = []
    for record in records:
        stamp = parse_text.get_date_stamp(record.get(field) or '')
        if not stamp: continue
        if start and stamp < start: continue
        if end and stamp > end: continue
        chosen.append(record)
    return chosen


def merge_by_work(*passes: list[dict]) -> list[dict]:
    """Every record from several walks, once each, in the order first seen.

    Keyed on the work number, falling back to the link: the same fic found by two walks is
    one download, not two. The later walk's record wins, because it was read more recently.
    """

    merged: dict[str, dict] = {}
    for records in passes:
        for record in records or []:
            key = str(record.get('id') or record.get('link') or '')
            if not key: continue
            merged[key] = record
    return list(merged.values())


def quick_scan_floor(fileops: FileOps, zone=None) -> str:
    """The date a quick scan indexes back to, or '' when there is nothing to go on.

    The day the last successful **full scan or quick scan** started. Two conditions, and
    both matter:

    - it has to have **finished**. A run that failed, was stopped, or was interrupted may
      have given up before reaching works updated before it began, and treating it as a
      floor would leave exactly those unseen for ever after.
    - it has to be a run that **covered the whole listing down to its own floor**. A full
      scan reads everything; a quick scan reads everything since the previous floor, so a
      chain of them is unbroken back to a full scan. Nothing else qualifies: the combined
      run and 'just new bookmarks' stop at the first fic they recognise, an update run and
      a date window read no listing at all, and a custom run covers whatever slice it was
      told to. Any of those can finish perfectly while never looking at a fic ao3 updated
      that day, so measuring back to one would skip it permanently.
    """

    return ao3_day(quick_scan_floor_at(fileops), zone)


def quick_scan_floor_at(fileops: FileOps) -> str:
    """The moment `quick_scan_floor` stands for, in UTC as it is kept: when the last run that
    qualifies began its reach (its login, or its first attempt's if resumed). '' for none."""

    last = runs.last_successful(fileops, match=floor_worthy,
                                statuses=(runs.STATUS_SUCCESS, runs.STATUS_PARTIAL))
    return runs.baseline_of(last) if last else ''


def newest_indexed_on(records: list[dict], zone=None) -> str:
    """The day the index was last written, as `YYYY-MM-DD`, or '' when it never was.

    `last_indexed` is stamped on every entry each time a run touches it, so the newest one
    across the whole index is the last time anything was indexed at all - which is the only
    date the index itself can offer as a floor.
    """

    return ao3_day(newest_indexed_at(records), zone)


def newest_indexed_at(records: list[dict]) -> str:
    """The latest `last_indexed` moment across the index, as written (UTC), or ''."""

    newest, newest_at = '', None
    for record in records:
        stamp = str(record.get(indexing.LAST_INDEXED) or '')
        try:
            at = datetime.datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if at.tzinfo is None: at = at.replace(tzinfo=datetime.timezone.utc)
        if newest_at is None or at > newest_at: newest, newest_at = stamp, at
    return newest


def settle_quick_floor(job: Job, fileops: FileOps, report) -> str:
    """Ask how far back to go when no run qualifies as a floor but an index exists.

    A quick scan measures back to the last run that covered the whole listing. Without one
    it reads everything - honest, but hours on a large library, and pointless if the index
    in the folder is recent and was simply built by something this app has no record of: an
    older version, a restored backup, a run whose history file was lost.

    The index can offer a date of its own (`last_indexed`), but it is a weaker promise than
    a completed run: it says when an entry was last written, not that everything was seen.
    So it is offered rather than taken, and **the default is the full listing** - the answer
    that cannot leave a gap. Whatever goes wrong here, a quick scan must not quietly decide
    to look at less than it should.

    Returns the moment to index back to (UTC, as kept), or '' for the whole listing.
    """

    records = shared.read_index(fileops)
    if not records: return ''

    indexed_at = newest_indexed_at(records)
    indexed_on = ao3_day(indexed_at, job.ao3_zone)
    if not indexed_on: return ''

    print(strings.AO3_INFO_QUICK_ASKING.format(len(records), indexed_on))
    print(strings.AO3_INFO_QUICK_WAITING)

    answer = job.ask(
        {'name': QUICK_QUESTION, 'count': len(records), 'date': indexed_on,
         'choices': list(QUICK_CHOICES)},
        # a stop, or a closed tab, reads everything rather than guessing at less
        {'choice': QUICK_FULL})
    choice = answer.get('choice')

    if job.record:
        job.record.choice({'question': QUICK_QUESTION, 'count': len(records),
                           'choice': choice, 'date': indexed_on})

    if choice == QUICK_SINCE_INDEX:
        print(strings.AO3_INFO_QUICK_SINCE_INDEX.format(indexed_on))
        return indexed_at

    print(strings.AO3_INFO_QUICK_CHOSE_FULL)
    return ''


def floor_runs(fileops: FileOps) -> list[dict]:
    """Every earlier run in the library a quick scan may measure back to, newest first."""

    return floors_among(runs.read_runs(fileops))


def floors_among(records: list[dict]) -> list[dict]:
    """The runs among `records` a quick scan may be told to measure back to.

    The same rule `quick_scan_floor` applies to the latest one, applied to all of them: it
    finished, and it reached every work ao3 had updated by the time it started. Offering a
    run that fails either test would let the user pick a floor with a hole behind it.

    Takes the records rather than reading them because the page owns the library: it reads
    the run history itself and asks this which of it qualifies, so the rule lives here once.
    """

    return [record for record in records if isinstance(record, dict) and floor_worthy(record)]


def floor_worthy(record: dict) -> bool:
    """Whether a run can be a floor: it covered the whole listing, and indexed all of it.

    A finished run can. So can a **partly finished** one whose indexing all passed and whose
    only failures were downloads - every work ao3 had updated by the time it began was seen,
    which is all a floor promises - **unless any of them failed for ao3's maintenance**: an
    outage says nothing about the works, and a run that met one may have met it sooner than
    its failures show. A partly finished floor is offered with its missing works named
    (`missing_downloads`), so the page can warn before a quick scan measures back to it.
    """

    if not covered_the_whole_listing(record): return False
    status = record.get('status')
    if status == runs.STATUS_SUCCESS: return True
    if status != runs.STATUS_PARTIAL or record.get('indexFailures'): return False
    failures = [x for x in record.get('failures') or [] if isinstance(x, dict)]
    return not any(x.get('reason') == REASON_MAINTENANCE
                   or strings.ERROR_AO3_DOWN in str(x.get('error') or '') for x in failures)


def missing_downloads(record: dict) -> list[str]:
    """The works a partly finished floor could not download, by number."""

    if record.get('status') != runs.STATUS_PARTIAL: return []
    return [str(x.get('id')) for x in record.get('failures') or []
            if isinstance(x, dict) and x.get('id')]


def chosen_floor(fileops: FileOps, run_id: str, zone=None) -> str:
    """The day a chosen earlier scan started, in the person's AO3 zone, or '' when it is not a
    run that can be one."""

    return ao3_day(chosen_floor_at(fileops, run_id), zone)


def chosen_floor_at(fileops: FileOps, run_id: str) -> str:
    """The moment a chosen earlier scan's reach began (UTC, as kept), or '' when it is not a
    run that can be one."""

    if not run_id: return ''
    # that one run's record, by its file name, and the same rule `floor_runs` applies
    record = runs.find_run(fileops, run_id)
    return runs.baseline_of(record) if record and floors_among([record]) else ''


def covered_the_whole_listing(record: dict) -> bool:
    """Whether a finished run reached every work ao3 had updated by the time it started.

    Only a full scan and a quick scan do. A quick scan given a **date range** does not: it
    stops at the date the user picked rather than at the previous floor, so anything older
    than that was never looked at - which is the same hole a half-covering run leaves, and
    the reason this is a question about the record rather than about the button.
    """

    if record.get('action') == ACTION_BOOKMARKS: return True
    if record.get('action') != ACTION_QUICK: return False
    return not (record.get('options') or {}).get('dates')


def run_custom(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """A full scan with its parts made optional.

    Indexing can be skipped, in which case the run works from whatever the index already
    holds - no listing is read at all, and every judgement about what is out of date is
    made against however old that index is. That is the point of the option and also its
    whole risk, which is why it is off by default.

    It can also cover a **window of time** instead of a slice of the listing. The two are
    alternatives rather than settings that combine: one picks works by where they sit in
    the listing and the other by when ao3 last touched them, and a run cannot both be
    walking a listing and not walking it.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes
    pages = job.options['pages'] or None
    start = job.options['start']

    if job.options['dates']:
        # a window walks the sorted listing down to its own floor, so a page limit left
        # over from the other shape of this run would cut that walk short
        pages, start = None, 1

    ao3 = Ao3(repo, fileops, downloadtypes, pages, job.options['series'],
              job.options['images'], progress=report, cancelled=job.cancel.is_set,
              start=start)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    if job.options['dates'] or rechecks(job):
        run_custom_dates(job, fileops, ao3, downloadtypes, report)
        finish_run(job, fileops, ao3, report)
        return

    restore_series(job, ao3)
    scoped = resumed_scope(job, fileops, ao3, report)
    if scoped is not None:
        # the earlier attempt got as far as checking its files: nothing left to index
        records = scoped
        mark_earlier(job, 'index', 'series', 'nonbookmarks')
        download_planned(job, fileops, ao3, records, downloadtypes, report)
        if job.options['images']: save_images(job, fileops, ao3, records, report)
        finish_run(job, fileops, ao3, report)
        return

    job.steps.start('index')
    walked = False
    if job.options['reindex'] and metadata:
        progress.report(report, progress.PHASE, name=progress.INDEXING)
        print(strings.AO3_INFO_INDEXING)
        # a slice may be read by date updated instead: the same walk, a different listing.
        # a fic ao3 updates moves to the top there, so a broken walk starts again rather than
        # being picked up from a page (`anchored`)
        by_updated = job.action == ACTION_CUSTOM and listing_order(job) == 'updated'
        records = walk_listing(job, fileops, ao3, 'all',
                               f'{bookmarks_link(job)}?{strings.AO3_SORT_BY_UPDATED}' if by_updated
                               else sorted_bookmarks_link(job),
                               anchored=not by_updated, ceiling=retry_ceiling(job),
                               own_bookmarks=True)
        walked = not ao3.walk_skipped
        walk_broke = ao3.walk_failed
    else:
        print(strings.AO3_INFO_USING_LAST_INDEX)
        records = shared.read_index(fileops)
        print(strings.AO3_INFO_INDEXED_COUNT.format(len(records)))
        # not re-read, but what each entry says about its series is enough to walk them
        for record in records: ao3.mark_series_of(record)
        walked = True
        walk_broke = False
    if walk_broke: job.steps.fail('index')
    else: job.steps.done('index') if walked else mark_earlier(job, 'index')

    records = merge_by_work(records, index_series_and_non_bookmarks(job, fileops, ao3, report))
    download_planned(job, fileops, ao3, records, downloadtypes, report)

    # last, and only when asked: it costs a work page per fic, which is exactly what the
    # rest of this run is built to avoid
    if job.options['images']:
        save_images(job, fileops, ao3, records, report)

    finish_run(job, fileops, ao3, report)


def work_links(text: str) -> tuple[list[str], list[str]]:
    """Every work in a paste of links or work numbers, and whatever in it was neither.

    Separated by anything people separate a list with - new lines, commas, spaces,
    semicolons, in any mix. Each one goes through `work_link`, so a link to any chapter and a
    bare number both count; the same work twice is one work, kept where it first appeared.
    """

    links: list[str] = []
    unknown: list[str] = []
    for piece in re.split(r'[\s,;]+', text or ''):
        if not piece: continue
        link = work_link(piece)
        if link is None: unknown.append(piece)
        elif link not in links: links.append(link)
    return links, unknown


def work_link(value: str) -> str | None:
    """A work link from either a link or a bare work number.

    Pasting the number off the address bar is as natural as pasting the whole url, and both
    say the same thing. Anything else - a series, a collection, a listing, a typo - comes
    back as None so the caller refuses it before a run starts rather than after.
    """

    text = (value or '').strip()
    if not text: return None
    if text.isdigit(): return f'{strings.AO3_BASE_URL}/works/{text}'

    work = parse_text.get_work_number(text)
    if not work: return None
    if strings.AO3_DOMAIN not in text.lower(): return None
    return f'{strings.AO3_BASE_URL}/works/{work}'


def copy_name(copy: dict) -> str:
    return os.path.basename(str(copy['path']).replace('\\', '/'))


def nominated_names(have: dict, formats: list[str]) -> dict[str, str]:
    """Each format's nominated file for comparison (`shared.nominated_first`), by name."""
    return {x: copy_name(have[x.upper()]) for x in formats if have.get(x.upper())}


def other_copies(have: dict, formats: list[str]) -> dict[str, list[str]]:
    """Each format's other copies beside its nominated file for comparison, by name - kept
    whatever a question about the format is answered. Formats with none are left out."""
    return {x: [copy_name(c) for c in have[x.upper()].get('older') or []]
            for x in formats if (have.get(x.upper()) or {}).get('older')}


def say_other_copies(others: dict[str, list[str]]) -> None:
    for filetype, names in others.items():
        print(strings.AO3_INFO_UNSURE_OTHER_COPIES.format(filetype, '; '.join(names)))


def undated_copies(existing: dict, work: str, filetypes: list[str]) -> list[str]:
    """The requested formats of a work whose file carries no date in the app's own form."""

    have = existing.get(str(work)) or {}
    return [x for x in filetypes if have.get(x.upper()) and not have[x.upper()].get('date')]


def unsure_scenario(guessed: str, incoming: str, source: str,
                    overwriting: bool = False) -> tuple[str, bool, str]:
    """Which of the three cases a file without the app's own date is, against the incoming
    version from `source`; whether replacing it is recommended; and why.

    - **older**: a date guessed from its name (*Infer date*) is before the incoming one - we
      *think* the incoming version is newer: replace. On an overwriting run, a guess the
      **same** as the incoming date is here too - a file with the app's own date and that date
      is replaced by an overwrite, so the guess is recommended the same way.
    - **newer**: the guessed date is later (or the same, on a run that does not overwrite) - we
      think yours is as new: keep.
    - **unknown**: no date can be read from its name: from AO3, replace - AO3's own copy is the
      version AO3 serves now, so replacing is probably safe, on any run. From FicHub, keep - its
      copy may be an older cached one. A guessed date with no incoming one to compare: keep.

    Only ever a recommendation: every case's default is to keep the file."""

    side = 'fichub' if source == strings.SOURCE_FICHUB else 'ao3'
    if not guessed:
        if source == strings.SOURCE_FICHUB:
            return f'{side}-{SCENARIO_UNKNOWN}', False, strings.UNSURE_CANNOT_INFER_FICHUB
        return f'{side}-{SCENARIO_UNKNOWN}', True, strings.UNSURE_CANNOT_INFER_AO3
    said, theirs = parse_text.written_date(guessed), parse_text.written_date(incoming)
    if not incoming:
        return (f'{side}-{SCENARIO_UNKNOWN}', False,
                strings.UNSURE_NO_INCOMING_DATE.format(said, source))
    if guessed < incoming:
        return (f'{side}-{SCENARIO_OLDER}', True,
                strings.UNSURE_THINK_OLDER.format(said, source, theirs))
    if guessed == incoming and overwriting:
        return (f'{side}-{SCENARIO_OLDER}', True,
                strings.UNSURE_THINK_SAME_OVERWRITE.format(said, source, theirs))
    return (f'{side}-{SCENARIO_NEWER}', False,
            (strings.UNSURE_THINK_SAME if guessed == incoming
             else strings.UNSURE_THINK_NEWER).format(said, source, theirs))


def ask_about_unsure_copies(job: 'Job | None', records: list[dict], existing: dict, plan: dict,
                            filetypes: list[str], source: str = strings.SOURCE_AO3,
                            skip: set[str] = frozenset(), overwriting: bool | set[str] = False,
                            incoming_date: str | None = None) -> set[str]:
    """Files whose names carry **no date in the app's own form** are never replaced unasked -
    from AO3 or FicHub, overwriting or not.

    Only a date written the app's way (`get_date_from_filename`) is a version the run can trust.
    Every other file is one of six scenarios (`SCENARIOS`: AO3 or FicHub, and `unsure_scenario`'s
    older / newer / unknown), and the run asks **once per work and format** - each file is its
    own version, and its own case - (`INFERRED_DATE_QUESTION`, carrying `scenario`), saying what
    it thinks and recommending: replace when it thinks yours is older, keep otherwise. `yes`
    replaces that file, `no` keeps it. The default is the scenario's own (`SCENARIO_SETTINGS` in settings.ini, or the
    page's *Defaults used during a run*) - keep unless changed - and an answer you chose to
    **always** use for a scenario (`Job.always_answers`, from the page's User settings) is taken
    without asking. A file to replace goes in `superseded` (the work in `stale`); one kept
    leaves it, into `plan['keep']`.

    `skip` is works another question already asked about; `incoming_date` stands in for the
    record's own date (FicHub's copy older than the index). Answers the works it asked about.
    """

    asked: set[str] = set()
    keep: dict[str, set[str]] = plan.setdefault('keep', {})
    for record in records:
        work = str(record.get('id') or '')
        link = record.get('link') or ''
        if not work or not link or work in skip: continue
        overwrites = overwriting is True or (
            isinstance(overwriting, (set, frozenset)) and link in overwriting)
        have = existing.get(work) or {}
        replacing = plan['superseded'].get(link) or {}
        # an overwrite put these in `superseded` without judging them
        candidates = [x for x in undated_copies(existing, work, filetypes)
                      if overwrites or x not in replacing]
        if not candidates: continue
        guessed = {x: parse_text.infer_date_from_filename(have[x.upper()]['path'])
                   for x in candidates}
        incoming = parse_text.get_date_stamp(
            incoming_date if incoming_date is not None else (record.get('date_updated') or ''))
        judged = {x: unsure_scenario(guessed[x], incoming, source, overwrites) for x in candidates}
        if job is not None:
            job.unsure_files.update(str(have[x.upper()]['path']) for x in candidates)
        print(strings.AO3_INFO_UNSURE_COPIES.format(
            work, ', '.join(candidates), source, parse_text.written_date(incoming) if incoming else '?'))
        names = {x: os.path.basename(str(have[x.upper()]['path']).replace('\\', '/')) for x in candidates}
        # no copy of the format is dated the app's way, so none is the clear one to judge by:
        # the question names every copy. Only the one it asks about is replaced; the others
        # are kept, for Resolve issues (`note_duplicate_copies`)
        others = {x: other_copies(have, [x]).get(x, []) for x in candidates}
        for filetype in candidates:
            print(strings.AO3_INFO_UNINDEXED_FORMAT.format(filetype, judged[filetype][2]))
            say_other_copies(other_copies(have, [filetype]))
        asked.add(work)
        plan.setdefault('keptSaid', set()).add(link)

        replace: list[str] = []
        alongside: list[str] = []
        # keep both is offered only with an incoming date to name the new file by
        offered = list(INFERRED_DATE_CHOICES) if incoming else [INFERRED_DATE_YES, INFERRED_DATE_NO]
        # one question per work and format: each file is its own version, and its own case
        for filetype in candidates:
            scenario, recommended = judged[filetype][0], judged[filetype][1]
            formats = [filetype]
            choice = INFERRED_DATE_NO
            if job is not None:
                answer = job.ask({'name': INFERRED_DATE_QUESTION, 'scenario': scenario, 'count': 1,
                                  'ids': [work], 'formats': formats, 'date': incoming,
                                  'source': source, 'fileDates': {x: guessed[x] for x in formats},
                                  'fileNames': {x: names[x] for x in formats},
                                  'otherFiles': {x: others[x] for x in formats if others[x]},
                                  'reasons': {x: judged[x][2] for x in formats},
                                  'recommended': INFERRED_DATE_YES if recommended else INFERRED_DATE_NO,
                                  'overwriting': overwrites,
                                  'choices': offered},
                                 {'choice': INFERRED_DATE_NO})
                choice = answer.get('choice') if answer.get('choice') in offered \
                    else INFERRED_DATE_NO
                if job.cancel.is_set(): choice = INFERRED_DATE_NO
                if job.record:
                    job.record.choice({'question': INFERRED_DATE_QUESTION, 'scenario': scenario,
                                       'count': 1, 'works': [work], 'formats': formats,
                                       'fileNames': [names[x] for x in formats],
                                       'otherFiles': [n for x in formats for n in others[x]],
                                       'fileDates': {x: guessed[x] for x in formats},
                                       'date': incoming, 'reasons': [judged[x][2] for x in formats],
                                       'choice': choice, 'source': source,
                                       'recommended': INFERRED_DATE_YES if recommended else INFERRED_DATE_NO})
            if choice == INFERRED_DATE_YES: replace += formats
            if choice == INFERRED_DATE_BOTH: alongside += formats

        for filetype in candidates:
            if filetype in replace:
                plan['superseded'].setdefault(link, {})[filetype] = have[filetype.upper()]['path']
                print(strings.AO3_INFO_UNINDEXED_REPLACING.format(filetype))
            elif filetype in alongside:
                plan['superseded'].setdefault(link, {})[filetype] = KEEP_BOTH
                print(strings.AO3_INFO_KEEPING_BOTH.format(filetype))
            else:
                (plan['superseded'].get(link) or {}).pop(filetype, None)
                keep.setdefault(link, set()).add(filetype.upper())
                print(strings.AO3_INFO_UNINDEXED_KEEPING.format(filetype))
        if link in plan['superseded'] and not plan['superseded'][link]:
            plan['superseded'].pop(link)
        missing = any(not have.get(x.upper()) for x in filetypes)
        if plan['superseded'].get(link) or missing:
            if link not in plan['stale']: plan['stale'].append(link)
        elif link in plan['stale']:
            plan['stale'].remove(link)
        if link in plan.get('undated', []): plan['undated'].remove(link)
    return asked


def note_duplicate_copies(job: Job, records: list[dict], existing: dict,
                          downloadtypes: list[str]) -> None:
    """Note the run's works that have more than one file of a format, and keep every one.

    The run judges each format by one copy: the newest dated the app's way
    (`scan_downloaded_works`) - or, with none dated so, it asks about it naming every copy
    (`ask_about_unsure_copies`). It replaces only the copy it judged, and **never deletes the
    others**: one with a guessed date or none cannot be told older without guessing. Only the
    run's own works (`records`). The end of the run says how many there are and offers Resolve
    issues, which sorts duplicates by hand (`say_duplicate_copies`)."""

    works = {str(x.get('id')) for x in records if x.get('id')}
    wanted = {x.upper() for x in downloadtypes}
    found = getattr(job, 'duplicate_copies', None)
    if found is None: return
    noted = 0
    for work in sorted(works & set(existing), key=lambda x: (len(x), x)):
        for filetype, newest in (existing.get(work) or {}).items():
            if filetype not in wanted: continue
            others = newest.get('older') or []
            if not others: continue
            key = f'{work}:{filetype}'
            if key not in found: noted += 1
            found[key] = len(others)
    if noted:
        print(strings.AO3_INFO_DUPLICATES_KEPT.format(noted))


def say_duplicate_copies(job: Job) -> None:
    """At the end of a run, how many of its works still have more than one file of a format -
    every copy kept - so the page can offer Resolve issues to sort them. Nothing for none."""

    found = getattr(job, 'duplicate_copies', None) or {}
    if not found: return
    works = len({key.split(':', 1)[0] for key in found})
    job.emit({'type': progress.DUPLICATE_COPIES, 'works': works, 'files': sum(found.values())})


def cleanup(job: Job, fileops: FileOps, ao3) -> None:
    """Remove the older copies marked for removal, and note on indexed works which of your
    collections hold them - the step before the report.

    Skipped when there is nothing to do, and when the run was stopped: a stop keeps
    everything as it is, and the report says what was left. A marked file this run has since
    downloaded over - the same name - is kept, since it is no longer the older copy. Each
    file's outcome goes into the history as it happens.
    """

    pending = [x for x in job.removals if x.get('status') == 'pending']
    if job.cancel.is_set():
        if pending:
            print(strings.AO3_INFO_CLEANUP_STOPPED.format(len(pending)))
            for item in pending:
                item['status'] = 'kept'
                item['error'] = strings.CLEANUP_STOPPED
            if job.record: job.record.removals(job.removals)
        job.steps.skip('cleanup')
        return

    links = collection_links(job, fileops, ao3)
    if not pending and not links:
        job.steps.skip('cleanup')
        return

    job.steps.start('cleanup')
    if links: write_collection_links(fileops, links)
    if not pending:
        job.steps.done('cleanup')
        return
    print(strings.AO3_INFO_CLEANUP.format(len(pending)))
    written = list(getattr(ao3, 'written', None) or [])
    for item in pending:
        if any(fileops.same_file(item['path'], path) for path in written):
            item['status'] = 'kept'
            item['error'] = strings.CLEANUP_WROTE_OVER
            print(strings.AO3_INFO_CLEANUP_KEPT.format(item['file']))
        elif fileops.delete_file(item['path']):
            item['status'] = 'removed'
            print(strings.AO3_INFO_CLEANUP_REMOVED.format(item['file']))
        else:
            item['status'] = 'kept'
            item['error'] = strings.CLEANUP_NOT_DELETED
            print(strings.AO3_INFO_CLEANUP_FAILED.format(item['file'], strings.CLEANUP_NOT_DELETED))
        if job.record: job.record.removals(job.removals)
    job.steps.done('cleanup')


# the runs whose cleanup notes which collections hold the works they covered: every
# workflow but the debug ones (the combined run, new bookmarks only, update incomplete)
LINKING_ACTIONS = (ACTION_BOOKMARKS, ACTION_QUICK, ACTION_CUSTOM, ACTION_WORK, ACTION_WORKS,
                   ACTION_COLLECTIONS, ACTION_COLLECTION, ACTION_IMPORT)


def covered_works(job: Job, ao3) -> set[str]:
    """Every work this run covered - not only what it indexed this attempt.

    What it indexed (`reindexed`), and everything its progress names: its scope, every
    walk's works, the works its series walk found, the non-bookmarks and date-window fics it
    got through. A resumed run starts its progress with a copy of the earlier attempt's, and
    the earlier attempt's own is read too, so a work that attempt indexed - which this one
    takes from the index rather than reading again - is still covered.
    """

    found: set[str] = set()

    def take(values) -> None:
        for value in values or []:
            if isinstance(value, (str, int)) and str(value): found.add(str(value))

    reindexed = getattr(ao3, 'reindexed', None)
    if isinstance(reindexed, set): take(reindexed)
    for saved in (job.progress(), job.earlier_progress()):
        if not isinstance(saved, dict): continue
        take(saved.get('scope'))
        for walk in (saved.get('walks') or {}).values():
            if isinstance(walk, dict): take(walk.get('works'))
        for key in ('seriesWorks', 'nonBookmarksDone', 'updateDone'):
            take(saved.get(key))
    return found


def externals_so_far(job: Job, ao3) -> list[str]:
    """Every external work this run has saved an entry for, the attempts it resumes
    included, for its progress.

    `Ao3.externals_saved` is this attempt's alone, so the checkpoint adds it to what the
    progress already says - a resumed run starts from a copy of its earlier attempt's, so a
    chain of resumes keeps the first attempt's too. A walk says which works it read in its
    own entry; external works are kept here instead, because nothing needs to know which
    walk found one, only that the run saved it.
    """

    return sorted(covered_externals(job, ao3))


def covered_externals(job: Job, ao3) -> set[str]:
    """The external works this run saved an entry for, by ao3's number for them - in this
    attempt, and in every earlier attempt it resumes, as their progress records them."""

    found: set[str] = set()
    saved = getattr(ao3, 'externals_saved', None)
    if isinstance(saved, set): found |= {str(x) for x in saved}
    for progress in (job.progress(), job.earlier_progress()):
        if not isinstance(progress, dict): continue
        for value in progress.get('externalsSaved') or []:
            if isinstance(value, (str, int)) and str(value): found.add(str(value))
    return found


def collection_links(job: Job, fileops: FileOps, ao3) -> list[tuple[str, list[str]]]:
    """The index entries that are missing a collection that holds them, and the whole list
    each should have - `(path, from_collections)`.

    **This is the one place `from_collections` is set**, for every workflow but the debug
    ones. Each looks at every work it covered (`covered_works`) and every external work it
    saved, against every collection saved in the library - so a work bookmarked after its
    collection was indexed learns it too. A collection run also looks at every work and
    external work the collections it read list - so with *Index and download encountered
    works* off, a work you had already indexed still learns it is in the collection.

    Only entries already in the index are touched, and only when a collection is missing
    from them. Nothing here reaches ao3, and anything that goes wrong is left undone rather
    than failing a run over a note about where a work was found.
    """

    try:
        if job.action not in LINKING_ACTIONS: return []
        held: dict[str, dict] = {}
        folder = os.path.join(fileops.downloadfolder, strings.COLLECTIONS_FOLDER_NAME)
        for name in fileops.list_files(folder):
            if not str(name).lower().endswith('.json'): continue
            collection = indexing.flatten(fileops.load_json(
                os.path.join(strings.COLLECTIONS_FOLDER_NAME, name))) or {}
            if collection.get('name'): held[str(collection['name'])] = collection
        if not held: return []

        by_work: dict[str, set[str]] = {}
        by_external: dict[str, set[str]] = {}
        by_series: dict[str, set[str]] = {}
        for name, collection in held.items():
            for work in [*(collection.get('work_ids') or []), *(collection.get('bookmark_ids') or [])]:
                by_work.setdefault(str(work), set()).add(name)
            for external in collection.get('external_ids') or []:
                by_external.setdefault(str(external), set()).add(name)
            for series in collection.get('series_ids') or []:
                by_series.setdefault(str(series), set()).add(name)
        # a series a collection holds holds its works for it too - which works, the series'
        # own entry says
        series_folder = os.path.join(strings.INDEXING_FOLDER_NAME, strings.SERIES_INDEX_FOLDER_NAME)
        for series, works_in_it in works_of_series(fileops, series_folder, set(by_series)).items():
            for work in works_in_it:
                by_work.setdefault(work, set()).update(by_series[series])

        works = covered_works(job, ao3)
        externals = covered_externals(job, ao3)
        series = covered_series(job, ao3)
        if job.action in COLLECTION_ACTIONS:
            read = {x for x in job.collections_read if x in held}
            works |= {w for w, names in by_work.items() if names & read}
            externals |= {e for e, names in by_external.items() if names & read}
            series |= {x for x, names in by_series.items() if names & read}

        return [*entries_missing(fileops, strings.INDEXING_FOLDER_NAME, works, by_work),
                *entries_missing(fileops, os.path.join(strings.INDEXING_FOLDER_NAME,
                                                       strings.EXTERNAL_INDEX_FOLDER_NAME),
                                 externals, by_external),
                *entries_missing(fileops, series_folder, series, by_series)]
    except exceptions.CancelledException:
        raise
    except Exception:
        return []


def covered_series(job: Job, ao3) -> set[str]:
    """The series this run read or marked - in this attempt, and in every earlier attempt it
    resumes, as their progress records them - by series number."""

    found: set[str] = set()
    for attribute in ('series_read', 'series_ids_found', 'series_marked'):
        value = getattr(ao3, attribute, None)
        if isinstance(value, dict): found |= {str(x) for x in value}
    for progress in (job.progress(), job.earlier_progress()):
        if not isinstance(progress, dict): continue
        for value in progress.get('seriesDone') or []:
            if isinstance(value, (str, int)) and str(value): found.add(str(value))
        for marked in progress.get('seriesMarked') or []:
            if isinstance(marked, dict) and marked.get('id'): found.add(str(marked['id']))
    return found


def works_of_series(fileops: FileOps, subfolder: str, wanted: set[str]) -> dict[str, list[str]]:
    """The works each wanted series' entry lists, by series - read only for those series."""

    found: dict[str, list[str]] = {}
    if not wanted: return found
    for name in fileops.list_files(os.path.join(fileops.downloadfolder, subfolder)):
        if not str(name).lower().endswith('.json'): continue
        number = parse_text.get_work_number_from_filename(name)
        if number not in wanted: continue
        entry = indexing.flatten(fileops.load_json(os.path.join(subfolder, name))) or {}
        found[number] = [str(x) for x in entry.get(strings.SERIES_WORKS_FIELD) or []]
    return found


def entries_missing(fileops: FileOps, subfolder: str, ids: set[str],
                    holders: dict[str, set[str]]) -> list[tuple[str, list[str]]]:
    """The entries in `subfolder`, among `ids`, that lack a collection `holders` says holds
    them - found by the number their file name starts with, read only when they might."""

    wanted = {x for x in ids if x in holders}
    if not wanted: return []
    found = []
    for name in fileops.list_files(os.path.join(fileops.downloadfolder, subfolder)):
        if not str(name).lower().endswith('.json'): continue
        work = parse_text.get_work_number_from_filename(name)
        if work not in wanted: continue
        path = os.path.join(subfolder, name)
        data = fileops.load_json(path)
        if not isinstance(data, dict): continue
        have = {str(x) for x in data.get(indexing.FROM_COLLECTIONS) or []}
        if holders[work] - have:
            found.append((path, sorted(have | holders[work])))
    return found


def write_collection_links(fileops: FileOps, links: list[tuple[str, list[str]]]) -> None:
    """Add the collections to each entry. `from_collections` is identity, not a reading, so
    it goes straight onto the file - no new reading is added for it."""

    if not links: return
    print(strings.AO3_INFO_COLLECTIONS_LINKING)
    written = 0
    for path, names in links:
        try:
            data = fileops.load_json(path)
            if not isinstance(data, dict): continue
            data[indexing.FROM_COLLECTIONS] = names
            fileops.save_json(path, data)
            written += 1
        except exceptions.CancelledException:
            raise
        except Exception:
            continue
    if written:
        print(strings.AO3_INFO_COLLECTIONS_LINKED_ONE if written == 1
              else strings.AO3_INFO_COLLECTIONS_LINKED.format(written))


def report_not_removed(job: Job, report) -> None:
    """Name the older copies a run marked for removal and did not remove."""

    left = [{'id': x['id'], 'link': f'{strings.AO3_BASE_URL}/works/{x["id"]}',
             'file': x['file'], 'old': x['keeping'],
             'error': x.get('error') or strings.CLEANUP_STOPPED}
            for x in job.removals if x.get('status') != 'removed']
    if not left: return
    print(strings.AO3_INFO_NOT_REMOVED.format(len(left)))
    progress.report(report, progress.NOT_REMOVED, notRemoved=left)


def fichub_candidates(ao3) -> list[dict]:
    """The failures FicHub could help with: ao3 works, by number.

    A bookmark that was never a work (an external work, a series) is in `skipped_works`, not
    here, and a work a listing showed only as deleted has no number to ask about - FicHub
    is asked by the work's link. A series is left to ao3: FicHub makes one book of a whole
    series, which is not how this library keeps one.
    """

    found = []
    for failure in list(getattr(ao3, 'failures', None) or []):
        work = str(failure.get('id') or '')
        link = str(failure.get('link') or '')
        if not work or parse_text.get_work_number(link) != work: continue
        if strings.AO3_DOMAIN not in link.lower(): continue
        found.append(failure)
    return found


def rescue_with_fichub(job: Job, fileops: FileOps, ao3, report) -> None:
    """Ask FicHub for the works ao3 would not give us, once the person running it says yes.

    Every run comes through here, after everything it asked ao3 for, so anything it failed
    on - a download, a re-read for an update, a single fic's own page - gets a second
    chance. A work FicHub has is indexed from what it says (when the run writes json) and
    downloaded in the formats the run asked for, by the same rules a download from ao3
    follows: only what is missing or behind, named the same way, checked the same way. Its
    reading in the index carries `retrieved_from`, so it can be told apart.

    A work FicHub does not have either stays in the failures, with both reasons. Asked as
    a question, defaulting to yes - see `FICHUB_QUESTION`.
    """

    candidates = fichub_candidates(ao3)
    if not candidates or job.cancel.is_set():
        job.steps.skip('fichub')
        return

    works = [str(x['id']) for x in candidates]
    print(strings.AO3_INFO_FICHUB_ASK.format(len(works), ', '.join(works)))
    answer = job.ask({'name': FICHUB_QUESTION, 'count': len(works), 'ids': works,
                      'choices': list(FICHUB_CHOICES)},
                     {'choice': FICHUB_YES})
    choice = answer.get('choice') if answer.get('choice') in FICHUB_CHOICES else FICHUB_YES
    if job.record:
        job.record.choice({'question': FICHUB_QUESTION, 'count': len(works), 'works': works,
                           'choice': choice})
    if choice != FICHUB_YES or job.cancel.is_set():
        print(strings.AO3_INFO_FICHUB_DECLINED)
        job.steps.skip('fichub')
        return

    job.steps.start('fichub')
    print(strings.AO3_INFO_FICHUB_TRYING.format(len(works), ', '.join(works)))
    progress.report(report, progress.PHASE, name=progress.FICHUB)
    filetypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    indexes = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes
    wanted = set(works)
    entries = indexed_entries(ao3, fileops, wanted)
    # every format, not only the run's: a format FicHub gives that there was no file of is
    # warned about when another of the work's files is dated later (`note_fichub_older`). one
    # listing, narrowed to the run's formats for everything else
    every = shared.scan_downloaded_works(fileops.worksfolder, strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES,
                                         storage=fileops.storage) if filetypes else {}
    asked = {x.upper() for x in filetypes}
    existing = {work: {t: c for t, c in copies.items() if t in asked}
                for work, copies in every.items()}
    existing = {work: copies for work, copies in existing.items() if copies}
    maximum = fileops.get_ini_value_integer(
        strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
    overwrite = bool(job.options.get('overwrite'))

    # an import keeps to what it was asked: a work only looked up is indexed and nothing
    # fetched for it, and without `replaceOutdated` a format you hold a copy of is never
    # fetched again - the same rules its ao3 side follows (`indexOnly`, `keep_existing_copies`)
    importing = job.action == ACTION_IMPORT
    index_only = {str(x) for x in job.options.get('indexOnly') or []} if importing else set()
    keep_held = importing and not job.options.get('replaceOutdated')

    for done, failure in enumerate(candidates, start=1):
        if job.cancel.is_set(): break
        if job.skipping():
            print(strings.AO3_INFO_STEP_SKIPPED)
            job.steps.skip('fichub')
            return
        work = str(failure['id'])
        types = fichub_formats_for(work, filetypes, existing, index_only, keep_held)
        rescue_one(ao3, failure, entries.get(work), existing, types,
                   indexes, maximum, overwrite, done, len(candidates), job=job,
                   every=every.get(work))

    # an import names each work's files from its entry once it has one - FicHub's entries
    # too, the same way its ao3 ones were (`name_files_from_index`: keeping each file's own
    # date, or none)
    if importing and indexes:
        named = [x for x in candidates if str(x['id']) in ao3.reindexed]
        if named:
            fresh = indexed_entries(ao3, fileops, {str(x['id']) for x in named})
            name_files_from_index(fileops, list(fresh.values()))

    if job.cancel.is_set(): return
    job.steps.done('fichub')


def fichub_formats_for(work: str, filetypes: list[str], existing: dict, index_only: set[str],
                       keep_held: bool) -> list[str]:
    """The formats to ask FicHub for, for one work of a run: none for a work an import only
    looks up, and - for an import keeping your copies - only the formats with no copy on disk."""

    if work in index_only:
        if filetypes: print(strings.AO3_INFO_FICHUB_INDEX_ONLY.format(work))
        return []
    if not keep_held: return filetypes
    have = existing.get(work) or {}
    held = [x for x in filetypes if have.get(x.upper())]
    if held: print(strings.AO3_INFO_KEEPING_YOURS.format(', '.join(held)))
    return [x for x in filetypes if not have.get(x.upper())]


def existing_entry(ao3, fileops: FileOps, work: str):
    """For a fic run: how to find this fic's index entry once ao3 has shown it.

    The fic runs ask ao3 first and the library second - an entry is only needed to save
    what ao3 said, and a fic ao3 will not show goes to FicHub without the library being
    read at all. Found by number (`indexed_entries`), never by reading the whole index, and
    said before and after, so the log names what is being waited on.
    """

    def find() -> dict | None:
        if not work: return None
        print(strings.AO3_INFO_INDEX_CHECK.format(work))
        existing = indexed_entries(ao3, fileops, {work}).get(work)
        say_entry_found(ao3, work, existing)
        return existing
    return find


def say_entry_found(ao3, work: str, existing: dict | None) -> None:
    """Say whether a fic run found the index file it was looking for, and which."""

    if not existing:
        print(strings.AO3_INFO_INDEX_NOT_FOUND.format(work))
        return
    try:
        name = os.path.basename(ao3.entry_path({'id': work}))
    except Exception:
        name = ''
    print(strings.AO3_INFO_INDEX_FOUND.format(work, name or existing.get('title') or ''))


def indexed_entries(ao3, fileops: FileOps, works: set[str]) -> dict[str, dict]:
    """The index entries of just these works, by number.

    Found by the number their file names start with (`Ao3.entry_path`, one listing of the
    index folder) and read one file each - never the whole index, which in Dropbox is a
    download per entry, and took a run thirteen minutes to find one work's. The fic runs and
    the FicHub step use it; a run that really works through the index still reads it all.
    """

    entries: dict[str, dict] = {}
    for work in sorted(works):
        try:
            record = indexing.flatten(fileops.load_json(ao3.entry_path({'id': work})))
        except Exception:
            continue
        if record and record.get('link'): entries[work] = record
    return entries


def rescue_one(ao3, failure: dict, entry: dict | None, existing: dict, filetypes: list[str],
               indexes: bool, maximum: int, overwrite: bool, done: int, total: int,
               job: 'Job | None' = None, every: dict | None = None) -> None:
    """One work from FicHub: look it up, download what is missing or behind, index it.

    The index is written after the downloads, so its FicHub reading can say which formats
    came from FicHub. A work counts as rescued only when nothing it was asked for failed;
    otherwise it stays in the failures, its ao3 reason beside FicHub's.
    """

    link = failure['link']
    title = (entry or {}).get('title') or link
    print(strings.AO3_INFO_FICHUB_WORK.format(done, total, failure['id'], title))
    progress.report(ao3.progress, progress.WORK, title=title, link=link, done=done,
                    total=total, phase=progress.FICHUB)
    log: dict = {'link': link, 'source': strings.FICHUB_SITE}
    arrived: list[str] = []

    try:
        answer = fichub.lookup(ao3.repo, link)
        record = fichub.entry_from(answer, link, entry)
        # a fic run asked for this one by its link: say so, unless it is your bookmark
        if job is not None and job.action in FIC_ACTIONS and not was_bookmark(entry):
            record[strings.FROM_IMPORT_FIELD if job.action == ACTION_IMPORT
                   else strings.FROM_LINK_FIELD] = True
        title = record.get('title') or title
        print(strings.AO3_INFO_FICHUB_FOUND.format(failure['id'], title))

        # FicHub's copy is a cache: when it is older than what the index already says, it
        # replaces nothing and does not rewrite the index - see `older_on_fichub`
        behind = older_on_fichub(entry, record)
        # a work the index had no entry for when the run began: its copies are asked about
        # one work at a time below (`ask_about_unindexed_copies`), overwriting or not - not by
        # the older-copy question, which judges by an entry it never had
        before = indexed_before(job)
        work = str(failure['id'])
        # what the run was asked, before an older FicHub copy narrows it to what it may replace
        run_overwrites = overwrite
        held_new = [x for x in filetypes if (existing.get(work) or {}).get(x.upper())] \
            if before is not None and work not in before else []
        if behind:
            if not older_fichub_formats(job, failure, existing,
                                        [x for x in filetypes if x not in held_new], behind,
                                        overwrite and not held_new) and not held_new:
                return
            alongside = behind.get('alongside') or []
            filetypes = behind['missing'] + behind['replace'] + alongside + \
                [x for x in held_new if x not in behind['missing'] + behind['replace'] + alongside]
            overwrite = bool(behind['replace'])

        def from_fichub(filetype: str) -> bytes:
            print(strings.AO3_INFO_FICHUB_FETCHING.format(filetype, failure['id']))
            return fichub.download(ao3.repo, answer, filetype)

        problem: Exception | None = None
        if filetypes:
            plan = shared.plan_downloads([record], existing, filetypes, overwrite=overwrite)
            plan['overwrite'] = overwrite
            # kept, with FicHub's copy saved beside each (keep both): fetched, nothing replaced
            for filetype in (behind or {}).get('alongside') or []:
                plan['superseded'].setdefault(link, {})[filetype] = KEEP_BOTH
                if link not in plan['stale']: plan['stale'].append(link)
            asked = ask_about_unindexed_copies(job, [record], existing, plan, filetypes, before,
                                               strings.SOURCE_FICHUB, overwriting=run_overwrites)
            # a file with no date in the app's own form is never replaced unasked - an import's
            # own window has already chosen what to do with its files
            if not behind and (job is None or job.action != ACTION_IMPORT):
                ask_about_unsure_copies(job, [record], existing, plan, filetypes,
                                        strings.SOURCE_FICHUB, skip=asked,
                                        overwriting=overwrite)
            # overwriting: a file with the app's own date later than FicHub's copy is newer than
            # it, so it is asked about rather than replaced (an older FicHub copy is judged
            # file by file in `older_fichub_formats` instead)
            if overwrite and not behind and job is not None:
                keep_newer_copies(job, [record], existing, plan, filetypes, skip=asked)
            fetching = say_what_each_format_needs(record, existing, filetypes, plan)
            if behind and not fetching:
                # an older copy, and every copy of yours kept: nothing came from FicHub
                reason = strings.ERROR_FICHUB_OUTDATED.format(parse_text.written_date(behind['fichub']), parse_text.written_date(behind['indexed']))
                failure['error'] = strings.ERROR_AO3_AND_FICHUB.format(failure.get('error') or '', reason)
                failure['fichub'] = reason
                return
            if fetching:
                ao3.superseded = plan['superseded']
                # every file of the work, in any format (`every`), for the warning below
                held = dict(every if every is not None else existing.get(work) or {})
                try:
                    fetch_formats(ao3, record, fetching, maximum, log, done, total,
                                  fetch=from_fichub,
                                  arrived=arrived)
                except (exceptions.CancelledException, exceptions.SessionExpiredException):
                    raise
                except Exception as e:
                    problem = e
                note_fichub_older(ao3, failure, record, entry, held, list(arrived))

        if indexes and behind:
            print(strings.AO3_INFO_FICHUB_INDEX_KEPT.format(failure['id']))
        elif indexes:
            print(strings.AO3_INFO_FICHUB_INDEXING.format(failure['id']))
            ao3.save_metadata({**record, strings.RETRIEVED_FROM_FIELD:
                               {'site': strings.FICHUB_SITE, 'downloaded': arrived}},
                              from_mirror=True)
            print((strings.AO3_INFO_FICHUB_INDEXED if str(failure['id']) in ao3.reindexed
                   else strings.AO3_INFO_FICHUB_NOT_INDEXED).format(failure['id']))
        if problem is not None: raise problem
    except exceptions.CancelledException:
        print(strings.INFO_CANCELLED)
        raise
    except exceptions.SessionExpiredException:
        raise
    except Exception as e:
        failure['error'] = strings.ERROR_AO3_AND_FICHUB.format(failure.get('error') or '', e)
        failure['fichub'] = str(e)
        print(strings.AO3_INFO_FICHUB_FAILED_TOO.format(e))
        ao3.log_error(log, e)
        return

    ao3.failures[:] = [x for x in ao3.failures if x is not failure]
    ao3.rescued.append({'id': failure['id'], 'link': link, 'title': title,
                        'downloaded': arrived})


def note_fichub_older(ao3, failure: dict, record: dict, entry: dict | None, held: dict,
                      arrived: list[str]) -> None:
    """Warn when a format FicHub gave is dated before the last known update date for the work -
    the index's `date_updated`, or the date written the app's way in the name of any of the
    work's files (never a guessed one): one there was no file of (`formats`), and one that
    replaced a file of yours (`replaced`, by format, with your file's own date - '' when its
    name had none). It is kept: an older version beats none, and beats an older file. But
    FicHub's copy may be an older cached one, so the run says so as it happens and again at
    its end (`ao3.fichub_older`)."""

    if not arrived: return
    fichub_date = parse_text.get_date_stamp(record.get('date_updated'))
    if not fichub_date: return
    known = [(parse_text.get_date_stamp((entry or {}).get('date_updated')), '')]
    known += [(copy.get('date') or '', filetype) for filetype, copy in held.items()
              if isinstance(copy, dict)]
    latest, source = max(((d, f) for d, f in known if d), default=('', ''))
    if not latest or fichub_date >= latest: return
    work = str(failure['id'])
    since = strings.FICHUB_OLDER_FROM_FILE.format(source) if source else ''
    taken = [x for x in arrived if x.upper() not in held]
    replaced = {x.upper(): str((held.get(x.upper()) or {}).get('date') or '')
                for x in arrived if x.upper() in held}
    for filetype in taken:
        print(strings.AO3_INFO_FICHUB_OLDER_TAKEN.format(
            filetype, work, parse_text.written_date(fichub_date), parse_text.written_date(latest), since))
    for filetype, yours in replaced.items():
        print(strings.AO3_INFO_FICHUB_OLDER_REPLACED.format(
            filetype, work, parse_text.written_date(fichub_date),
            strings.FICHUB_OLDER_YOURS_DATED.format(parse_text.written_date(yours)) if yours
            else strings.NO_DATE_IN_NAME,
            parse_text.written_date(latest), since))
    ao3.fichub_older.append({'id': work, 'link': failure.get('link') or '',
                             'title': record.get('title') or '', 'formats': taken,
                             'replaced': replaced,
                             'fichub': fichub_date, 'latest': latest, 'latestFrom': source})


def older_on_fichub(entry: dict | None, record: dict) -> dict | None:
    """FicHub's date and the index's, when FicHub's copy is the older of the two - else None.

    Judged by `date_updated`, the same field every other decision about versions reads: the
    index's from before FicHub's answer is merged in, FicHub's from its own answer. A work
    the index has no date for, or FicHub gives none, is not judged older.
    """

    indexed = parse_text.get_date_stamp((entry or {}).get('date_updated'))
    mirror = parse_text.get_date_stamp(record.get('date_updated'))
    if indexed and mirror and mirror < indexed:
        return {'fichub': mirror, 'indexed': indexed, 'missing': [], 'replace': []}
    return None


def older_fichub_formats(job, failure: dict, existing: dict, filetypes: list[str],
                         behind: dict, overwrite: bool = False) -> bool:
    """FicHub's copy is older than the index: decide what, if anything, to take from it.

    **Each file is judged against FicHub's date by the date in its own name** - never by the
    index's, which says how current the entry is, not which version a file holds:

    - **no file**: taken, unasked, into `behind['missing']` - an older version beats none,
      and the run warns about it at the end (`note_fichub_older`).
    - **a file older than FicHub's copy**: replaced, unasked - FicHub's is newer than what you
      have, even though it is behind AO3's (the outdated rule: incoming newer than the file).
    - **a file the same date**: kept - unless the run overwrites, which replaces it.
    - **a file newer than FicHub's copy, or with no date in its name**: never replaced unasked;
      a run that overwrites asks (`OVERWRITE_OLDER_QUESTION`, default no) naming each file's
      own date.

    What to replace goes in `behind['replace']`. False means take nothing: the work stays a
    failure, saying why. The index is never rewritten from it (its reading is newer).
    """

    work = str(failure['id'])
    fichub_date = behind['fichub']
    print(strings.AO3_INFO_FICHUB_OUTDATED.format(work, parse_text.written_date(fichub_date), parse_text.written_date(behind['indexed'])))
    have = existing.get(work) or {}
    missing = [x for x in filetypes if x.upper() not in have]
    present = [x for x in filetypes if x.upper() in have]
    reason = strings.ERROR_FICHUB_OUTDATED.format(parse_text.written_date(fichub_date), parse_text.written_date(behind['indexed']))

    # a format you have no file of at all: taken, unasked - an older version beats none, and
    # the end of the run warns that it may be an older cached copy (`note_fichub_older`)
    if missing:
        print(strings.AO3_INFO_FICHUB_TAKING_OLDER.format(', '.join(missing), work))
        behind['missing'] = missing

    file_date = {x: (have[x.upper()].get('date') or '') for x in present}
    replace: list[str] = []
    asking: list[str] = []
    undated: list[str] = []
    for filetype in present:
        date = file_date[filetype]
        if date and date < fichub_date:
            print(strings.AO3_INFO_FICHUB_NEWER_THAN_FILE.format(filetype, fichub_date, date))
            replace.append(filetype)
        elif date and date == fichub_date:
            if overwrite: replace.append(filetype)
            else: print(strings.AO3_INFO_FICHUB_SAME_AS_FILE.format(filetype, date))
        elif not date:
            undated.append(filetype)
        elif overwrite and job is not None:
            asking.append(filetype)
        else:
            print(strings.AO3_INFO_FICHUB_NOT_NEWER.format(filetype, date))

    if asking:
        dated = [file_date[x] for x in asking if file_date[x]]
        print(strings.AO3_INFO_OLDER_THAN_COPY.format(
            work, parse_text.written_date(fichub_date), ', '.join(asking),
            ', '.join(parse_text.written_date(file_date[x]) if file_date[x] else strings.NO_DATE_IN_NAME for x in asking)))
        say_other_copies(other_copies(have, asking))
        if ask_yes_no(job, OVERWRITE_OLDER_QUESTION, OVERWRITE_OLDER_NO,
                      {'ids': [work], 'formats': asking, 'date': fichub_date,
                       'newer': max(dated) if dated else '',
                       'fileDates': {x: file_date[x] for x in asking},
                       'fileNames': nominated_names(have, asking),
                       'otherFiles': other_copies(have, asking)}, work, asking):
            replace += asking
            for filetype in asking:
                print(strings.AO3_INFO_REPLACING_NEWER.format(filetype, work))
        else:
            for filetype in asking:
                print(strings.AO3_INFO_KEEPING_NEWER.format(filetype))

    # no date in the app's own form: never replaced unasked, guessed date or none
    # (`ask_about_unsure_copies`), whether or not the run overwrites
    if undated:
        plan = {'superseded': {}, 'stale': [], 'undated': []}
        record = {'id': work, 'link': failure.get('link') or work}
        ask_about_unsure_copies(job, [record], existing, plan, undated, strings.SOURCE_FICHUB,
                                overwriting=overwrite, incoming_date=fichub_date)
        chosen = plan['superseded'].get(record['link']) or {}
        replace += [x for x, path in chosen.items() if path != KEEP_BOTH]
        behind['alongside'] = [x for x, path in chosen.items() if path == KEEP_BOTH]
    behind['replace'] = replace
    if behind['missing'] or behind['replace'] or behind.get('alongside'): return True
    if not missing and not asking and not undated:
        print(strings.AO3_INFO_FICHUB_OUTDATED_NOTHING)
    failure['error'] = strings.ERROR_AO3_AND_FICHUB.format(failure.get('error') or '', reason)
    failure['fichub'] = reason
    return False


def ask_yes_no(job, name: str, default: str, details: dict, work: str,
               formats: list[str], kept: dict | None = None) -> bool:
    """Ask one of the per-work yes-or-no questions, record the answer, and say if it was yes.
    `kept` is anything more the run's history should keep with the answer."""

    answer = job.ask({'name': name, 'count': 1, **details, 'choices': ['yes', 'no']},
                     {'choice': default})
    choice = answer.get('choice') if answer.get('choice') in ('yes', 'no') else default
    if job.record:
        job.record.choice({'question': name, 'count': 1, 'works': [work],
                           'formats': formats, 'choice': choice, **(kept or {})})
    return choice == 'yes' and not job.cancel.is_set()


def finish_run(job: Job, fileops: FileOps, ao3, report) -> None:
    """How every run ends: FicHub for what ao3 would not give us, the cleanup step, then
    the report of anything left undone."""

    rescue_with_fichub(job, fileops, ao3, report)
    cleanup(job, fileops, ao3)
    report_failures(ao3, report)
    report_not_removed(job, report)


def plan_refresh(job: Job, fileops: FileOps, records: list[dict],
                 downloadtypes: list[str], report, only: list[str] | None = None) -> dict:
    """What the downloads folder already holds, and which of it ao3 has moved past.

    Says what it is doing at each step, because from the outside 'checking what you have'
    and 'checking what is out of date' look the same as a stall.
    """

    if not records:
        return {'stale': [], 'undated': [], 'superseded': {}, 'existing': {},
                'overwrite': False}

    # a retry carrying on: the works taken from the earlier attempt's index entries without
    # reading them again - asked once a run whether to read them now (`reread_carried`). One
    # that will not read is a failure, not downloaded from its old entry
    carried = carried_records(job, records)
    if carried and getattr(job, 'ao3', None) is not None:
        unread = {id(r) for r in reread_carried(job, job.ao3, carried, report)}
        if unread:
            records[:] = [r for r in records if id(r) not in unread]
        if not records:
            return {'stale': [], 'undated': [], 'superseded': {}, 'existing': {},
                    'overwrite': False}

    progress.report(report, progress.PHASE, name=progress.CHECKING_FILES)
    print(strings.AO3_INFO_CHECKING_FILES)
    existing = shared.scan_downloaded_works(fileops.worksfolder, downloadtypes,
                                            storage=fileops.storage)

    # `only` names the works to overwrite when it is not all of them - a single-fic run
    # replaces that fic, not the rest of its series
    overwrite: bool | set[str] = set(only) if only is not None else bool(job.options.get('overwrite'))

    # a file with no date in the app's own form - guessed or none - is asked about per work
    # once the plan is made (`ask_about_unsure_copies`); a work the index had no entry for
    # when the run began, per copy (`ask_about_unindexed_copies`)
    before = indexed_before(job)
    note_duplicate_copies(job, records, existing, downloadtypes)

    progress.report(report, progress.PHASE, name=progress.CHECKING_VERSIONS)
    print(strings.AO3_INFO_CHECKING_VERSIONS)
    plan = shared.plan_downloads(records, existing, downloadtypes, overwrite=overwrite)
    plan['existing'] = existing
    # so the per-format lines can say why a current-looking copy is being fetched again
    plan['overwrite'] = bool(overwrite)
    asked = ask_about_unindexed_copies(job, records, existing, plan, downloadtypes, before,
                                       overwriting=overwrite)
    if job.action == ACTION_IMPORT:
        # the page offered to date them before the import started; left undated there, kept
        if plan['undated']: print(strings.AO3_INFO_IMPORT_UNDATED_KEPT)
    else:
        ask_about_unsure_copies(job, records, existing, plan, downloadtypes, skip=asked,
                                 overwriting=overwrite)
    if overwrite: keep_newer_copies(job, records, existing, plan, downloadtypes, skip=asked)

    if plan['stale'] and overwrite:
        # not 'out of date' - most of them are not, and saying so would be a lie the user
        # would reasonably act on
        print(strings.AO3_INFO_OVERWRITING.format(len(plan['stale'])))
    elif plan['stale']:
        print(strings.AO3_INFO_OUT_OF_DATE.format(len(plan['stale'])))
    else:
        print(strings.AO3_INFO_UP_TO_DATE)

    progress.report(report, progress.REFRESH, stale=len(plan['stale']),
                    undated=len(plan['undated']), stamped=0)
    return plan


def run_collections(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Save a json file for every collection the user has, under downloads/collections.

    Only work ids are recorded for the items in a collection: the works themselves are
    described by the index, so repeating their metadata here would only go stale.
    """

    link = f'{strings.AO3_BASE_URL}/users/{job.username}/collections'
    pages = job.options['pages'] or None

    progress.report(report, progress.PHASE, name=progress.COLLECTIONS)
    print(strings.AO3_INFO_COLLECTIONS)

    ao3 = collections_ao3(job, fileops, repo, report, pages)
    records = crawl_collections(job, fileops, ao3, 'collections',
                                lambda: ao3.get_collections(link))
    note_collections_read(job, records)

    if records is None:
        pass # resumed at its download step: every collection was read by the earlier attempt
    elif records:
        print(strings.AO3_INFO_COLLECTIONS_DONE.format(
            len(records), fileops.describe(
                os.path.join(fileops.downloadfolder, strings.COLLECTIONS_FOLDER_NAME))))
    else:
        print(strings.AO3_INFO_COLLECTIONS_NONE)

    download_collection_works(job, fileops, ao3, report)
    # a collection crawl can leave gaps too, and used not to say so at all
    finish_run(job, fileops, ao3, report)


def run_collection(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Index one collection from a link, which need not be one of the user's own.

    Written to the same downloads/collections folder, in the same shape, as the
    collections you own - so an indexed collection is an indexed collection either way.
    """

    progress.report(report, progress.PHASE, name=progress.COLLECTIONS)

    ao3 = collections_ao3(job, fileops, repo, report, None)
    records = crawl_collections(job, fileops, ao3, 'collection',
                                lambda: ao3.get_collection(job.url))
    note_collections_read(job, records)

    if records:
        print(strings.AO3_INFO_COLLECTIONS_DONE.format(
            len(records), fileops.describe(
                os.path.join(fileops.downloadfolder, strings.COLLECTIONS_FOLDER_NAME))))

    download_collection_works(job, fileops, ao3, report)
    finish_run(job, fileops, ao3, report)


def collections_ao3(job: Job, fileops: FileOps, repo: Repository, report,
                    pages: int | None) -> Ao3:
    """The Ao3 a collections run crawls with - told to index the works it meets, when the
    run was asked to, and to follow their series when that was asked too."""

    works = bool(job.options.get('collectionWorks'))
    downloadtypes = ([x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
                     if works else [])
    ao3 = Ao3(repo, fileops, downloadtypes, pages, works and job.options['series'], False,
              progress=report, cancelled=job.cancel.is_set)
    if works: ao3.collection_works = []
    ao3.follow_subcollections = bool(job.options.get('subcollections'))
    ao3.follow_parents = bool(job.options.get('parentCollections'))
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3
    watch_collections(job, fileops, ao3)
    return ao3


def note_collections_read(job: Job, records: list[dict] | None) -> None:
    """Which collections this run covered, for its cleanup to note on the works they hold.
    A run resumed at its download step read none itself: the earlier attempt's count."""

    if records is None:
        job.collections_read = list((job.earlier_progress().get('collections') or {}).keys())
    else:
        job.collections_read = [str(r['name']) for r in records if r.get('name')]


def crawl_collections(job: Job, fileops: FileOps, ao3: Ao3, step: str, crawl) -> list[dict] | None:
    """Read the collections - or, for a run resumed after the earlier attempt reached its
    download step, nothing at all: that attempt saved the works it was downloading (`scope`),
    so the run goes straight back to them. None in that case."""

    scoped = resumed_scope(job, fileops, ao3, ao3.progress)
    if scoped is not None:
        mark_earlier(job, step, 'series')
        ao3.collection_works = list(scoped)
        ao3.scoped = True
        return None
    job.steps.start(step)
    records = crawl()
    # a collection whose listing broke off was saved with what it had, but not finished
    if any(gap.get('kind') == 'collection' for gap in ao3.index_failures): job.steps.fail(step)
    else: job.steps.done(step)
    return records


def watch_collections(job: Job, fileops: FileOps, ao3: Ao3) -> None:
    """Save a collection run's progress as it goes, and give a resumed one what the earlier
    attempt saved.

    Checkpointed after **every page** of each collection's works and bookmarked-items
    listings - the page and the work numbers found so far - and when a collection is saved,
    with every work number it holds. A resumed run skips the collections finished before and
    carries each unfinished listing on from its last saved page (`Ao3.collect_work_ids`).
    """

    state = job.progress().setdefault('collections', {})
    if job.resume:
        earlier = job.earlier_progress().get('collections') or {}
        ao3.collections_before = json.loads(json.dumps(earlier))
        # what was finished stays finished in this attempt's record too, so a second resume
        # skips it as well
        for slug, saved in earlier.items():
            if isinstance(saved, dict) and saved.get('done'): state[slug] = saved
        restore_series(job, ao3)
    ao3.records_for = lambda ids: records_by_id(fileops, ids)

    def on_page(slug: str, key: str, page, ids: list[str], done: bool = False,
                externals: list[str] | None = None, series: list[str] | None = None) -> None:
        listing = state.setdefault(slug, {'done': False, 'listings': {}})['listings'] \
            .setdefault(key, {})
        listing['ids'] = list(ids)
        listing['done'] = done
        if externals: listing['externals'] = list(externals)
        if series: listing['series'] = list(series)
        if page is not None: listing['page'] = page
        job.checkpoint(collections=state, seriesMarked=list(ao3.series_marked.values()),
                       externalsSaved=externals_so_far(job, ao3))

    def on_done(slug: str, works: list[str], family: list[str] | None = None) -> None:
        # the relatives it links to go with it, so a resume that skips it still follows them
        state[slug] = {'done': True, 'works': list(works), 'family': list(family or [])}
        job.checkpoint(collections=state, seriesMarked=list(ao3.series_marked.values()),
                       externalsSaved=externals_so_far(job, ao3))

    ao3.on_collection_page = on_page
    ao3.on_collection_done = on_done


def download_collection_works(job: Job, fileops: FileOps, ao3: Ao3, report) -> None:
    """The works a collections run indexed on its way through, downloaded as a scan would.

    Everything after the crawl is borrowed: their series are walked as any run walks the
    series it marked, and the download step is the one every scan ends with - so a copy on
    disk that is current is skipped, and one ao3 has moved past is replaced.
    """

    if ao3.collection_works is None: return
    print(strings.AO3_INFO_COLLECTION_WORKS_TOTAL.format(len(ao3.collection_works)))
    records = ao3.collection_works
    # a run resumed at its download step walked its series in the earlier attempt
    if job.options.get('series') and getattr(ao3, 'scoped', False) is not True:
        records = merge_by_work(records, index_marked_series(job, ao3, report))
    download_planned(job, fileops, ao3, records, list(ao3.filetypes), report)


def run_update(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """The 'update bookmarks marked as incomplete' action.

    Driven by the index rather than by the files on disk. The index already records which
    works were unfinished when they were last read and holds a link to each, so nothing has
    to be parsed out of an ebook to find a chapter count, and no listing has to be walked to
    rediscover where the works are.

    The limitation that carries is stated in the ui, and has to be acknowledged before the
    run starts: a fic that had already finished when it was last indexed is not in this
    list, however much has been added to it since.

    Unlike a bookmarks run, this does **not** index everything before downloading anything.
    It cannot: a bookmarks run reads the whole listing in a handful of requests and so knows
    every work's current state up front, while here each fic has to be opened individually
    before there is anything new to say about it. So it works one fic at a time - re-read
    it, write its entry, fetch it if the copy is behind - which also means a run stopped
    partway has finished every fic it touched rather than half-finishing all of them.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    ao3 = Ao3(repo, fileops, downloadtypes, None, False, job.options['images'],
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    update_incomplete(job, fileops, ao3, downloadtypes, report)
    finish_run(job, fileops, ao3, report)


def update_incomplete(job: Job, fileops: FileOps, ao3: Ao3, downloadtypes: list[str],
                      report) -> None:
    """The unfinished-fics pass, on an Ao3 the caller owns.

    Split out from `run_update` so a combined run can put it after its own indexing pass
    and still report every failure from both together, on the one Ao3 that collected them.
    """

    # 1. the index, off disk. no requests at all.
    job.steps.start('read')
    progress.report(report, progress.PHASE, name=progress.SCANNING)
    print(strings.AO3_INFO_READING_INDEX)
    incomplete = newest_first(shared.incomplete_works(shared.read_index(fileops)))
    job.steps.done('read')

    if not incomplete:
        print(strings.AO3_INFO_INCOMPLETE_NONE)
        # nothing unfinished is a perfectly good answer, not a failure
        job.steps.skip('check')
        job.steps.skip('update')
        return

    print(strings.AO3_INFO_INCOMPLETE_FOUND.format(len(incomplete)))
    refresh_and_download(job, fileops, ao3, incomplete, downloadtypes, report)


def refresh_and_download(job: Job, fileops: FileOps, ao3: Ao3, records: list[dict],
                         downloadtypes: list[str], report) -> None:
    """Re-read each of these fics and fetch whatever the re-read says is needed.

    The one-fic-at-a-time pass, given a list rather than finding its own. The unfinished
    works are one way to choose that list; a window of dates is another, and both want
    exactly this afterwards - so it lives here rather than twice.

    Works are done newest first, because a run can be stopped and where it got to should be
    the half worth having.
    """

    # what is already downloaded for those works. a file with no date in the app's own form
    # is asked about per work as each fic is judged (`ask_about_unsure_copies`)
    records = newest_first(records)
    save_scope(job, records)
    existing: dict = {}
    refresh_undated = False
    overwrite = bool(job.options.get('overwrite'))
    # taken before this pass starts adding to it: whatever the run indexed off the listing
    # beforehand has an entry too new to be worth re-reading one fic at a time
    already_fresh = set(ao3.reindexed)
    if downloadtypes:
        job.steps.start('check')
        progress.report(report, progress.PHASE, name=progress.CHECKING_FILES)
        print(strings.AO3_INFO_CHECKING_FILES)
        existing = shared.scan_downloaded_works(fileops.worksfolder, downloadtypes,
                                            storage=fileops.storage)
        job.steps.done('check')
    else:
        job.steps.skip('check')

    # one fic at a time: re-read it, then fetch it if the copy is behind
    job.steps.start('update')
    progress.report(report, progress.PHASE, name=progress.UPDATING)
    maximum = fileops.get_ini_value_integer(
        strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)

    checked = 0
    fetched = 0
    skipped_step = False
    # a resumed run does not go over the fics the earlier attempt already finished
    before = {str(x) for x in (job.earlier_progress().get('updateDone') or [])} \
        if job.resume else set()
    finished = sorted(before)
    if before: print(strings.AO3_INFO_RESUME_UPDATE_DONE.format(
        len([r for r in records if str(r.get('id') or '') in before])))
    for record in records:
        if job.cancel.is_set(): break
        if job.skipping():
            print(strings.AO3_INFO_STEP_SKIPPED)
            skipped_step = True
            break
        if str(record.get('id') or '') in before: continue
        checked += 1
        try:
            fetched += update_one_work(ao3, record, existing, downloadtypes, maximum,
                                       refresh_undated, checked, len(records), report,
                                       overwrite=overwrite, already_fresh=already_fresh,
                                       job=job)
        except exceptions.CancelledException:
            # a stop is not a failed run; what has been written so far stays written
            break
        finished.append(str(record.get('id') or ''))
        job.checkpoint(updateDone=finished)

    print(strings.AO3_INFO_UPDATE_DONE.format(checked, fetched))
    # a step that was abandoned must not claim to have finished
    job.steps.skip('update') if skipped_step else job.steps.done('update')


def rechecks(job: 'Job') -> bool:
    """A custom run that skips walking the listing but looks every indexed work up on AO3 -
    each one re-read, its entry rewritten, and its files judged against what AO3 says now. The
    date window's per-fic pass with no window: every work in the index, dated or not. Only
    without indexing (a walk would have read them) and without a window (which re-reads its
    own works anyway)."""

    return job.action == ACTION_CUSTOM and bool(job.options.get('recheck')) and \
        not job.options.get('reindex', True) and not job.options.get('dates')


def run_custom_dates(job: Job, fileops: FileOps, ao3: Ao3, downloadtypes: list[str],
                     report) -> None:
    """The custom run's other shape: a window of time rather than a slice of the listing.

    Works are chosen from the index by when ao3 last updated them, then each is re-read and
    fetched if the copy is behind - the same per-fic pass the unfinished-fics run uses,
    given a different list.

    The index is brought up to date first, unless the run was told to skip indexing. That
    walk goes down the bookmarks listing **sorted by when ao3 last updated each work** and
    stops at the first fic older than the window's earliest date: everything past that point
    is, by definition, outside the window. The sort is what makes the stop sound - see
    `Ao3.get_metadata` - and with no earliest date there is no floor, so the walk runs to
    the end of the listing.

    It matters because the window is judged on what the index records. Skip the indexing and
    a fic whose entry is older than ao3's truth is chosen, or missed, on the strength of
    that entry. The per-fic re-read then corrects each entry it touches, which is why the
    pass re-reads before it decides what to download.
    """

    # the typed range, as days in the person's AO3 zone - the dates AO3's are compared with
    start = range_day(job, 'dateFrom')
    end = range_day(job, 'dateTo')
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes

    restore_series(job, ao3)
    # no re-read question here: `refresh_and_download` reads every work again anyway
    scoped = resumed_scope(job, fileops)
    if scoped is not None:
        # the earlier attempt got as far as checking its files: nothing left to index
        mark_earlier(job, 'index', 'read', 'series', 'nonbookmarks')
        if scoped:
            refresh_and_download(job, fileops, ao3, scoped, downloadtypes, report)
        else:
            job.steps.skip('check')
            job.steps.skip('update')
        return

    # a range of dates bookmarked rather than dates updated: the listing read newest
    # bookmarked first, stopping at the first bookmark made before the range, and the works
    # picked by the date each was bookmarked
    bookmarked = listing_order(job) == 'bookmarked' and not rechecks(job)
    if job.options['reindex'] and metadata:
        job.steps.start('index')
        progress.report(report, progress.PHASE, name=progress.INDEXING)
        if bookmarked:
            print(strings.AO3_INFO_DATE_INDEXING_BOOKMARKED.format(start) if start
                  else strings.AO3_INFO_DATE_NO_FLOOR)
            # the quick scan's first walk, given the range's older end as its floor
            walk_listing(job, fileops, ao3, 'bookmarked', sorted_bookmarks_link(job),
                         anchored=True, ceiling=retry_ceiling(job, end), stop_before=start,
                         stop_on='bookmarked', own_bookmarks=True)
        else:
            print(strings.AO3_INFO_DATE_INDEXING.format(start) if start
                  else strings.AO3_INFO_DATE_NO_FLOOR)
            # the whole index is read below rather than just what came back here: a fic in
            # the window that is no longer bookmarked is still one the window asked for. a
            # retry starts at the window's end: nothing updated after it is chosen
            walk_listing(job, fileops, ao3, 'updated',
                         f'{bookmarks_link(job)}?{strings.AO3_SORT_BY_UPDATED}', anchored=False,
                         ceiling=retry_ceiling(job, end), stop_before=start, own_bookmarks=True)
        finish_walk_step(job, ao3, 'index')
    elif metadata:
        # asked for, and turned off - so it is shown as skipped rather than dropped
        print(strings.AO3_INFO_USING_LAST_INDEX)
        job.steps.skip('index')

    job.steps.start('read')
    progress.report(report, progress.PHASE, name=progress.SCANNING)
    recheck = rechecks(job)
    if recheck:
        # every indexed work, dated or not: each is looked up on AO3 before anything is judged
        chosen = newest_first(shared.read_index(fileops))
    elif bookmarked:
        print(strings.AO3_INFO_DATE_WINDOW_BOOKMARKED.format(start or strings.AO3_INFO_DATE_ANY,
                                                             end or strings.AO3_INFO_DATE_ANY))
        # only a bookmark has a date bookmarked: a work you never bookmarked, or one whose
        # entry predates the field, is not in a range of them
        chosen = newest_first(works_dated_between(shared.read_index(fileops), 'date_bookmarked',
                                                  start, end))
    else:
        print(strings.AO3_INFO_DATE_WINDOW.format(start or strings.AO3_INFO_DATE_ANY,
                                                  end or strings.AO3_INFO_DATE_ANY))
        chosen = works_updated_between(shared.read_index(fileops), start, end)
    job.steps.done('read')

    # the works the window picked out of the index were not all read on the walk, so their
    # series are marked from what their entries say. the ones the walk did read marked theirs
    # as it went
    for record in chosen: ao3.mark_series_of(record)
    chosen = newest_first(merge_by_work(
        chosen, index_series_and_non_bookmarks(job, fileops, ao3, report)))

    if not chosen:
        print(strings.AO3_INFO_RECHECK_NONE if recheck else strings.AO3_INFO_DATE_NONE)
        # an empty window is an answer, not a failure
        job.steps.skip('check')
        job.steps.skip('update')
        return

    print(strings.AO3_INFO_RECHECK.format(len(chosen)) if recheck
          else strings.AO3_INFO_DATE_FOUND.format(len(chosen)))
    refresh_and_download(job, fileops, ao3, chosen, downloadtypes, report)


def works_updated_between(records: list[dict], start: str, end: str) -> list[dict]:
    """The indexed works ao3 last updated inside a window, newest first.

    Judged on the index's own `date_updated`, normalised through `get_date_stamp` so the
    two forms ao3 writes compare properly. **Both ends are inclusive**: a window of a single
    day is a real thing to ask for, and would otherwise select nothing.

    An empty bound means no limit at that end, so one date alone gives 'since then' or
    'up to then'. A work with no readable date is left out rather than guessed at - it
    cannot be placed in a window, and including it would make the window a lie.
    """

    chosen = []
    for record in records:
        updated = parse_text.get_date_stamp(record.get('date_updated') or '')
        if not updated: continue
        if start and updated < start: continue
        if end and updated > end: continue
        chosen.append(record)
    return newest_first(chosen)


def newest_first(records: list[dict]) -> list[dict]:
    """Records in the order ao3 last updated them, most recent first.

    A long run gets through the fics you are most likely to be waiting on before the ones
    that have not moved in years - which matters because a run can be stopped, and where it
    got to should be the useful half rather than an arbitrary one.

    Sorted on the normalised stamp rather than the raw field, because a listing writes
    '14 Dec 2024' and a work page writes '2024-12-14' for the same day. An entry with no
    usable date sorts last: it cannot be placed, and guessing would put it at the front.
    """

    return sorted(
        records,
        key=lambda x: parse_text.get_date_stamp(x.get('date_updated') or '') or '',
        reverse=True)


def indexed_before(job: 'Job | None') -> set[str] | None:
    """The works the index held when this run began (`Ao3.indexed_before_run`), from the run's
    own downloader - or None where there is nothing to say it, which asks nothing: no real
    downloader (a test's stand-in), or an import, whose works are ones with no entry by
    definition and whose own rules (keep what you have, or replace what is outdated, as the
    Resolve issues window chose) already decide their copies."""

    if job is None or getattr(job, 'action', None) == ACTION_IMPORT: return None
    ao3 = getattr(job, '_ao3', None)
    if not (isinstance(Ao3, type) and isinstance(ao3, Ao3)): return None
    try:
        return ao3.indexed_before_run()
    except Exception:
        return None


def unindexed_copy_advice(incoming: str, file_date: str, source: str,
                          overwriting: bool = False, guessed: bool = False) -> tuple[str, str]:
    """What to recommend for one copy when the index has nothing to judge it by, and why.

    'yes' when the incoming version is newer than the date read from the copy's name - or the
    same, on a run that overwrites (it was asked to replace even current copies). 'no' when it
    is older, the same on a run that does not overwrite, or no incoming date. A copy whose name
    holds no date follows the guessed-date question's rule: 'yes' from AO3 (its copy is the
    version AO3 serves now), 'no' from FicHub (its copy may be an older cached one).
    """

    said, theirs = parse_text.written_date(file_date), parse_text.written_date(incoming)
    words = {'source': source, 'theirs': theirs, 'said': said}
    if not incoming:
        return UNINDEXED_COPY_NO, strings.UNINDEXED_REASON_NO_DATE.format(**words)
    if not file_date:
        # the same rule as the guessed-date question: AO3's own copy is the version AO3 serves now,
        # so replacing a file with no readable date is probably safe; FicHub's may be an older cache
        if source == strings.SOURCE_FICHUB:
            return UNINDEXED_COPY_NO, strings.UNINDEXED_REASON_NO_FILE_DATE_FICHUB.format(**words)
        return UNINDEXED_COPY_YES, strings.UNINDEXED_REASON_NO_FILE_DATE_AO3.format(**words)
    # `guessed`: the date was read loosely out of the name, not written the app's way - the
    # recommendation is the same, but the reason says it is a guess so the reader can weigh it
    if incoming > file_date:
        return UNINDEXED_COPY_YES, (strings.UNINDEXED_REASON_NEWER_GUESSED if guessed
                                    else strings.UNINDEXED_REASON_NEWER).format(**words)
    if incoming == file_date and overwriting:
        return UNINDEXED_COPY_YES, (strings.UNINDEXED_REASON_SAME_OVERWRITING_GUESSED if guessed
                                    else strings.UNINDEXED_REASON_SAME_OVERWRITING).format(**words)
    return UNINDEXED_COPY_NO, (strings.UNINDEXED_REASON_NOT_NEWER_GUESSED if guessed
                               else strings.UNINDEXED_REASON_NOT_NEWER).format(**words)


def ask_about_unindexed_copies(job: 'Job | None', records: list[dict], existing: dict,
                               plan: dict, filetypes: list[str], before: set[str] | None,
                               source: str = strings.SOURCE_AO3,
                               overwriting: bool | set[str] = False) -> set[str]:
    """Ask before a copy of a work **the index had no entry for when the run began** is replaced.

    With no entry of its own, nothing but the copy's name says which version it holds - the
    date the run just indexed is the incoming version's, not the copy's - so the version check
    has nothing to go on. For each such work with a copy of a requested format, the run asks
    (`UNINDEXED_COPY_QUESTION`) whatever it would otherwise have done, overwriting or not. Each
    copy is judged on its own (`unindexed_copy_advice`), from a date read out of its name the way
    the Resolve issues window's *Infer date* does (`parse_text.infer_date_from_filename`), and
    the reason said. The answer is per work: **yes** replaces every copy, **recommended** (offered
    when only some are) replaces just the recommended ones, **no** keeps them all - and **no is
    always the default**. A copy to replace goes in `superseded` (and the work in `stale`); one
    kept leaves it, into `plan['keep']`. Formats with no copy are fetched either way. Answers the
    works it asked about, so no other question asks about them again. `before` is
    `Ao3.indexed_before_run()`; None asks nothing. `overwriting` is the run's overwrite (True, or
    the links it overwrites).
    """

    asked: set[str] = set()
    if job is None or before is None: return asked
    keep: dict[str, set[str]] = plan.setdefault('keep', {})
    for record in records:
        work = str(record.get('id') or '')
        link = record.get('link') or ''
        if not work or not link or work in before: continue
        have = existing.get(work) or {}
        formats = [x for x in filetypes if have.get(x.upper())]
        if not formats: continue

        overwrites = overwriting is True or (isinstance(overwriting, (set, frozenset)) and link in overwriting)
        incoming = parse_text.get_date_stamp(record.get('date_updated') or '')
        dates = {x: parse_text.infer_date_from_filename(have[x.upper()]['path']) for x in formats}
        # each copy named whole, so the reader can judge it by eye (as the guessed-date question does)
        names = {x: os.path.basename(str(have[x.upper()]['path']).replace('\\', '/')) for x in formats}
        # a date written the app's way is known; any other was guessed from the name
        guessed = {x for x in formats if dates[x] and not parse_text.get_date_from_filename(names[x])}
        advice = {x: unindexed_copy_advice(incoming, dates[x], source, overwrites, x in guessed)
                  for x in formats}
        recommended_formats = [x for x in formats if advice[x][0] == UNINDEXED_COPY_YES]
        recommended = (UNINDEXED_COPY_NO if not recommended_formats
                       else UNINDEXED_COPY_YES if len(recommended_formats) == len(formats)
                       else UNINDEXED_COPY_RECOMMENDED)
        print(strings.AO3_INFO_UNINDEXED_COPY.format(work, ', '.join(formats), source,
                                                     parse_text.written_date(incoming) if incoming else '?'))
        for filetype in formats:
            print(strings.AO3_INFO_UNINDEXED_FORMAT.format(filetype, advice[filetype][1]))
            say_other_copies(other_copies(have, [filetype]))
        asked.add(work)

        # copies with no date written the app's way can be kept with the incoming version saved
        # beside them; one dated the app's way is kept as it is on that answer
        undated = [x for x in formats if not parse_text.get_date_from_filename(names[x])]
        choices = ([UNINDEXED_COPY_RECOMMENDED] if recommended == UNINDEXED_COPY_RECOMMENDED else []) + \
            [UNINDEXED_COPY_YES, UNINDEXED_COPY_NO] + \
            ([UNINDEXED_COPY_BOTH] if undated and incoming else [])
        answer = job.ask({'name': UNINDEXED_COPY_QUESTION, 'count': 1, 'ids': [work],
                          'formats': formats, 'date': incoming, 'source': source,
                          'fileDates': dates, 'fileNames': names, 'guessedDates': sorted(guessed),
                          'otherFiles': other_copies(have, formats),
                          'reasons': {x: advice[x][1] for x in formats},
                          'recommended': recommended, 'recommendedFormats': recommended_formats,
                          'bothFormats': undated if UNINDEXED_COPY_BOTH in choices else [],
                          'overwriting': overwrites, 'choices': choices},
                         {'choice': UNINDEXED_COPY_NO})
        # 'recommended' is taken whenever it is sent - it means the recommended copies, all or none
        choice = answer.get('choice') if answer.get('choice') in UNINDEXED_COPY_CHOICES else UNINDEXED_COPY_NO
        # keep both only where it was offered: with no file to keep beside, it would replace
        if choice == UNINDEXED_COPY_BOTH and UNINDEXED_COPY_BOTH not in choices: choice = UNINDEXED_COPY_NO
        if job.cancel.is_set(): choice = UNINDEXED_COPY_NO
        replace = formats if choice == UNINDEXED_COPY_YES \
            else recommended_formats if choice == UNINDEXED_COPY_RECOMMENDED else []
        alongside = undated if choice == UNINDEXED_COPY_BOTH else []
        if job.record:
            job.record.choice({'question': UNINDEXED_COPY_QUESTION, 'count': 1, 'works': [work],
                               'formats': formats, 'choice': choice, 'replaced': replace,
                               'keptBoth': alongside,
                               'fileNames': [names[x] for x in formats],
                               'recommended': recommended, 'source': source})

        replacing = plan['superseded'].setdefault(link, {})
        # this said what became of each copy, so the later per-format lines need not again
        plan.setdefault('keptSaid', set()).add(link)
        for filetype in formats:
            if filetype in replace:
                replacing[filetype] = have[filetype.upper()]['path']
                print(strings.AO3_INFO_UNINDEXED_REPLACING.format(filetype))
            elif filetype in alongside:
                replacing[filetype] = KEEP_BOTH
                print(strings.AO3_INFO_KEEPING_BOTH.format(filetype))
            else:
                replacing.pop(filetype, None)
                keep.setdefault(link, set()).add(filetype.upper())
                print(strings.AO3_INFO_UNINDEXED_KEEPING.format(filetype))
        if not replacing: plan['superseded'].pop(link, None)
        missing = any(not have.get(x.upper()) for x in filetypes)
        if replace or alongside or missing:
            if link not in plan['stale']: plan['stale'].append(link)
        elif link in plan['stale']: plan['stale'].remove(link)
        if link in plan.get('undated', []): plan['undated'].remove(link)
    return asked


def keep_newer_copies(job: 'Job', records: list[dict], existing: dict, plan: dict,
                      filetypes: list[str], skip: set[str] = frozenset()) -> None:
    """On an overwriting run, ask before replacing a copy with an **older** version.

    Overwriting replaces every copy, current or not - but a copy whose name carries a later
    date than the version about to be written is newer than it, and replacing it would lose
    something. For each such work the run asks (`OVERWRITE_OLDER_QUESTION`, default no,
    the usual 30-minute timeout), naming the formats. On no, those formats leave the plan:
    out of `superseded`, into `plan['keep']` (which the downloader honours), and a work with
    nothing else to fetch leaves `stale` too, so it is passed over rather than downloaded.
    """

    keep: dict[str, set[str]] = plan.setdefault('keep', {})
    for record in records:
        link = record.get('link') or ''
        replacing = plan['superseded'].get(link)
        if not replacing: continue
        current = parse_text.get_date_stamp(record.get('date_updated'))
        if not current: continue
        work = str(record.get('id') or '')
        # already asked about as a work the index had no entry for
        if work in skip: continue
        have = existing.get(work) or {}
        newer = {x: have[x.upper()]['date'] for x in replacing
                 if (have.get(x.upper()) or {}).get('date') and have[x.upper()]['date'] > current}
        if not newer: continue

        formats = sorted(newer)
        print(strings.AO3_INFO_OLDER_THAN_COPY.format(
            work, parse_text.written_date(current), ', '.join(formats), ', '.join(parse_text.written_date(x) for x in sorted(set(newer.values())))))
        say_other_copies(other_copies(have, formats))
        if ask_yes_no(job, OVERWRITE_OLDER_QUESTION, OVERWRITE_OLDER_NO,
                      {'ids': [work], 'formats': formats, 'date': current,
                       'newer': max(newer.values()),
                       'fileNames': nominated_names(have, formats),
                       'otherFiles': other_copies(have, formats)}, work, formats):
            for filetype in formats:
                print(strings.AO3_INFO_REPLACING_NEWER.format(filetype, work))
            continue

        keep.setdefault(link, set()).update(x.upper() for x in formats)
        for filetype in formats: replacing.pop(filetype, None)
        if not replacing:
            plan['superseded'].pop(link, None)
            missing = any(not have.get(x.upper()) for x in filetypes)
            if not missing and link in plan['stale']: plan['stale'].remove(link)


def name_files_from_index(fileops: FileOps, records: list[dict]) -> int:
    """An import's works, once indexed: each file of theirs in works/ that is not named the way
    its index entry names it is renamed so it is - **keeping the date its own name ends in**,
    which is the version the file holds and may well be older than AO3's. A file with no date
    keeps none. Never over another file; one that will not rename is said and left. Answers how
    many were renamed.

    Only an import does this: its files came from elsewhere, named however they were, and an
    entry has just been made for them. Every other run's files were named by a run already.
    """

    if not records: return 0
    by_work = {str(r.get('id') or ''): r for r in records if r.get('id')}
    maximum = fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
    folder = fileops.worksfolder
    try:
        paths = fileops.storage.files_under(folder) if fileops.storage else \
            [os.path.join(folder, x) for x in os.listdir(folder)]
    except Exception as e:
        print(strings.AO3_INFO_IMPORT_NAMES_UNREADABLE.format(e))
        return 0

    renamed = 0
    names: dict[str, str] = {}
    for path in paths:
        name = path.replace('\\', '/').rsplit('/', 1)[-1]
        extension = os.path.splitext(name)[1]
        record = by_work.get(parse_text.get_work_file_number(name) or '')
        if record is None or extension.lower() not in WORK_FILE_EXTENSIONS: continue
        wanted = indexed_file_name(record, parse_text.get_date_from_filename(name) or '',
                                   extension, maximum)
        if wanted == name: continue
        new = os.path.join(os.path.dirname(path), wanted)
        if fileops.exists(new) or not fileops.rename_file(path, new):
            print(strings.AO3_INFO_IMPORT_NAME_KEPT.format(name, wanted))
            continue
        print(strings.AO3_INFO_IMPORT_RENAMED.format(name, wanted))
        names[name] = wanted
        renamed += 1
    follow_renames_in_exclusions(fileops, names)
    return renamed


def follow_renames_in_exclusions(fileops: FileOps, names: dict[str, str]) -> int:
    """A file the import renamed keeps its place on the page's exclusion lists: every entry
    naming its old name is given the new one, or the next look at the library would take the
    renamed file for a new one and ask about it again. Answers how many names changed; a list
    that will not read or save is said and left."""

    if not names: return 0
    try:
        document = fileops.load_json(strings.IMPORT_EXCLUDED_FILE_NAME)
    except Exception:
        document = None
    entries = document.get('excluded') if isinstance(document, dict) else None
    if not isinstance(entries, list): return 0
    changed = 0
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('files'), list): continue
        files = []
        for x in entry['files']:
            files.append(names.get(x, x) if isinstance(x, str) else x)
            if isinstance(x, str) and x in names: changed += 1
        entry['files'] = files
    if not changed: return 0
    try:
        fileops.save_json(strings.IMPORT_EXCLUDED_FILE_NAME, document)
    except Exception as e:
        print(strings.AO3_INFO_IMPORT_EXCLUDED_UNSAVED.format(e))
        return 0
    print(strings.AO3_INFO_IMPORT_EXCLUDED_RENAMED.format(changed,
                                                          'file' if changed == 1 else 'files'))
    return changed


def keep_existing_copies(records: list[dict], plan: dict, filetypes: list[str]) -> None:
    """Keep every copy already in the folder, current or not - an import told not to replace
    outdated copies.

    Each format a work has a copy of leaves `superseded` for `plan['keep']`, which the
    downloader passes over, and a work with no format missing leaves `stale`, so it is not
    fetched at all. Formats with no copy are still fetched: that is what the import was asked
    to do.
    """

    keep: dict[str, set[str]] = plan.setdefault('keep', {})
    existing = plan.get('existing') or {}
    for record in records:
        link = record.get('link') or ''
        have = existing.get(str(record.get('id') or '')) or {}
        held = {x.upper() for x in filetypes if have.get(x.upper())}
        if not held: continue
        keep.setdefault(link, set()).update(held)
        replacing = plan['superseded'].get(link)
        if replacing is not None:
            for filetype in list(replacing):
                if filetype.upper() in held: replacing.pop(filetype, None)
            if not replacing: plan['superseded'].pop(link, None)
        missing = any(not have.get(x.upper()) for x in filetypes)
        if not missing and link in plan['stale']: plan['stale'].remove(link)


def say_what_each_format_needs(record: dict, existing: dict, filetypes: list[str],
                               plan: dict) -> list[str]:
    """Say what is going to happen to each requested format, and return the ones to fetch.

    Per format rather than per fic, because a run asking for html and pdf can want one and
    already have the other - and 'downloading it' said neither which nor why.

    The verdicts come straight out of `plan_downloads` rather than being worked out again
    here: `superseded` already names exactly the formats it decided to replace, so there is
    one definition of outdated (see **What "outdated" means, exactly**) and this only puts
    words to it.
    """

    have = existing.get(str(record.get('id') or ''), {})
    replacing = plan['superseded'].get(record.get('link') or '', {})
    kept = (plan.get('keep') or {}).get(record.get('link') or '', set())

    wanted: list[str] = []
    for filetype in filetypes:
        copy = have.get(filetype.upper())
        if filetype.upper() in kept:
            if (record.get('link') or '') not in plan.get('keptSaid', ()):
                print(strings.AO3_INFO_KEEPING_NEWER.format(filetype))
        elif not copy:
            print(strings.AO3_INFO_FORMAT_MISSING.format(filetype))
            wanted.append(filetype)
        elif filetype in replacing:
            wanted.append(filetype)
            # a question about this work already said what becomes of each copy
            if (record.get('link') or '') in plan.get('keptSaid', ()): continue
            # a run told to overwrite replaces copies that are perfectly current, so the
            # line has to say which reason it is or it reads as a version check gone wrong
            print(strings.AO3_INFO_FORMAT_REPLACING.format(filetype) if plan.get('overwrite')
                  else strings.AO3_INFO_FORMAT_OUTDATED.format(filetype))
        elif copy['date'] is None:
            print(strings.AO3_INFO_FORMAT_UNDATED.format(filetype))
        else:
            print(strings.AO3_INFO_FORMAT_CURRENT.format(filetype))

    return wanted


def fetch_formats(ao3: Ao3, record: dict, wanted: list[str], maximum: int, log: dict,
                  done: int, total: int, **source) -> int:
    """Download exactly the formats named, and leave the downloader as it was found.

    `download_one_indexed` fetches whatever `ao3.filetypes` holds, so asking it for one
    work used to mean asking for every format that work's run wanted - including the ones
    already on disk and current. That is a request each, spent for nothing, and rate limit
    is the scarce thing here.
    """

    keep = ao3.filetypes
    try:
        ao3.filetypes = wanted
        ao3.download_one_indexed(record, maximum, log, done, total, **source)
    finally:
        ao3.filetypes = keep
    return 1


def update_one_work(ao3: Ao3, record: dict, existing: dict, filetypes: list[str],
                    maximum: int, refresh_undated: bool, done: int, total: int,
                    report, overwrite: bool = False,
                    already_fresh: set[str] | None = None, job: 'Job | None' = None) -> int:
    """Bring one fic's entry up to date, and fetch it again if the copy is behind.

    Says what it is doing at each step rather than only at the end, because this is the
    slow part of the run and a line per fic is the only sign it is still moving.

    `already_fresh` holds the works **this run has just indexed off the listing**. Their
    entries were written minutes ago from a blurb carrying the same `date_updated` a work
    page reports, so re-reading them costs a request each and learns nothing. On a date
    window that is the whole list - the run indexed exactly these fics moments earlier -
    so it is the difference between one request per fic and none.

    Anything *not* in that set is re-read as before. An entry from an earlier run cannot
    say whether ao3 has moved on since, and a fic in the window that is no longer
    bookmarked was never on the walk at all.

    Returns 1 if the fic was downloaded, 0 if only its entry changed. A fic that cannot be
    read is recorded as a failure and skipped - it keeps the entry it already had.
    """

    link = record.get('link') or ''
    log: dict = {'link': link}

    try:
        ao3.check_cancelled()
        title = record.get('title') or link
        print(strings.AO3_INFO_UPDATE_WORK.format(done, total, title))
        progress.report(ao3.progress, progress.WORK, title=title, link=link,
                        done=done, total=total, phase=progress.UPDATING)

        if str(record.get('id') or '') in (already_fresh or set()):
            # this run wrote the entry from its own listing walk minutes ago, and a listing
            # blurb reports the same updated date a work page does. asking again would
            # spend a request to be told what we were just told
            print(strings.AO3_INFO_UPDATE_ALREADY_FRESH)
            fresh = record
        else:
            print(strings.AO3_INFO_UPDATE_READING)
            fresh = ao3.refresh_one(record)
            print(strings.AO3_INFO_UPDATE_INDEXED)

        if not filetypes:
            print(strings.AO3_INFO_UPDATE_NOTHING)
            return 0

        # the same rule a bookmarks run uses, asked about one work rather than all of them
        plan = shared.plan_downloads([fresh], existing, filetypes,
                                     refresh_undated=refresh_undated, overwrite=overwrite)
        plan['overwrite'] = overwrite
        asked = ask_about_unindexed_copies(job, [fresh], existing, plan, filetypes,
                                           indexed_before(job), overwriting=overwrite)
        if job is not None and job.action != ACTION_IMPORT:
            ask_about_unsure_copies(job, [fresh], existing, plan, filetypes, skip=asked,
                                     overwriting=overwrite)
        if overwrite and job is not None:
            keep_newer_copies(job, [fresh], existing, plan, filetypes, skip=asked)
        wanted = say_what_each_format_needs(fresh, existing, filetypes, plan)

        if not wanted:
            return 0

        ao3.superseded = plan['superseded']
        return fetch_formats(ao3, fresh, wanted, maximum, log, done, total)

    except exceptions.CancelledException:
        print(strings.INFO_CANCELLED)
        raise
    except exceptions.SessionExpiredException:
        raise  # every fic after this one would fail the same way
    except Exception as e:
        ao3.record_failure(link, e)
        ao3.log_error(log, e)
        return 0


def report_failures(ao3: Ao3, report) -> None:
    """Name the works a run could not fetch, and the bookmarks that were never works.

    Both at the end, both as lists rather than counts, because either one leaves a gap
    between what was bookmarked and what is on disk - and a number alone gives nobody a way
    to find out which ones, or to go and look at them.

    They stay two separate lists on purpose. A failure is something that went wrong and
    might not next time; a skipped bookmark is a series, or a work hosted somewhere else,
    or one that has been deleted - nothing went wrong and no amount of retrying would
    change it. Putting them together would make the first look routine.
    """

    if ao3.skipped_works:
        print(strings.AO3_INFO_SKIPPED_WORKS.format(len(ao3.skipped_works)))
        progress.report(report, progress.SKIPPED, skipped=ao3.skipped_works)

    # a third list: the download worked, but the file it replaced is still there. nothing is
    # lost, so it is not a failure to retry - but there are two copies now, and a number
    # alone would leave nobody able to find which
    kept = getattr(ao3, 'kept_copies', None)
    if isinstance(kept, list) and kept:
        print(strings.AO3_INFO_KEPT_COPIES.format(len({x['id'] for x in kept})))
        progress.report(report, progress.KEPT_COPIES, keptCopies=kept)

    older = getattr(ao3, 'fichub_older', None)
    if isinstance(older, list) and older:
        print(strings.AO3_INFO_FICHUB_OLDER_COPIES.format(len(older)))
        progress.report(report, progress.FICHUB_OLDER, fichubOlder=older)

    rescued = getattr(ao3, 'rescued', None)
    if isinstance(rescued, list) and rescued:
        print(strings.AO3_INFO_FICHUB_RESCUED.format(len(rescued)))
        progress.report(report, progress.RESCUED, rescued=rescued)

    if not ao3.failures: return
    print(strings.AO3_INFO_FAILED_WORKS.format(len(ao3.failures)))
    progress.report(report, progress.FAILURES, failures=ao3.failures)


def runners() -> dict:
    """What each action actually runs.

    A table rather than a chain of elifs: that chain ended in a bare `else`, which quietly
    turned every unrecognised action into an update run, and `ACTIONS` is already the guard
    over which names are allowed.

    Built per call rather than held at module level on purpose - a module-level dict would
    capture these functions at import, so replacing one afterwards (which every test of the
    dispatch does) would change the name and not the table.
    """

    return {
        ACTION_BOOKMARKS: run_bookmarks,
        ACTION_UPDATE: run_update,
        ACTION_COLLECTIONS: run_collections,
        ACTION_COLLECTION: run_collection,
        ACTION_NEW: run_new,
        ACTION_SYNC: run_sync,
        ACTION_WORK: run_work,
        ACTION_WORKS: run_works,
        ACTION_IMPORT: run_import,
        ACTION_CUSTOM: run_custom,
        ACTION_QUICK: run_quick,
    }


def page_may_call(origin: str, hosted_page: str) -> bool:
    """Whether a page at this origin may read this helper's answers.

    The page on this computer always may - the angular dev server is on a different port,
    so it counts as another origin. The one published elsewhere may when settings.ini names
    it (`PageOrigin`), compared exactly: a prefix test would let
    `https://someone.github.io.example.com` through.
    """

    if origin.startswith('http://localhost:') or origin.startswith('http://127.0.0.1:'):
        return True
    return bool(hosted_page) and origin == hosted_page


class Handler(BaseHTTPRequestHandler):
    jobs: dict[str, Job] = {}
    jobs_lock = threading.Lock()
    # the Windows app sets this (desktop.py): it is the one copy that can update itself.
    # everything else answers the update endpoints 404
    updater: 'updates.Updater | None' = None
    # the address this helper listens on - `serve` sets it. Only a helper on this computer lets
    # the page edit its settings.ini (see `settings_file_editable`)
    host: str = HOST
    # the settings.ini this copy was built with, where it packs one - the packaged app sets it
    # (desktop.py) to its deployment's. The page's defaults, and what Reset puts back
    settings_defaults: str = ''
    # wrong passcodes, by address: three and that address is refused for an hour
    passcode_guard = access.PasscodeGuard()

    # every answer carries a Server header, a stranger's 404 included: it names nothing, so an
    # address probed from outside does not say what is there (or which Python runs it)
    server_version = 'helper'
    sys_version = ''

    def log_message(self, format: str, *args) -> None:
        """Silent unless `EnableConsoleLogging` is on - the console belongs to the download
        output, and a page polling the helper would otherwise bury it."""

        if console_logging(): to_console(f'[request] {format % args}')

    def log_request(self, code='-', size='-') -> None:
        # the method, the path and the answer - never the headers, which is where the
        # passcode travels, and never a body, which is where the sealed login does
        if not console_logging(): return
        status = code.value if hasattr(code, 'value') else code
        to_console(f'[request] {self.command} {self.path} {status}')

    # region plumbing

    def cors(self) -> None:
        origin = self.headers.get('Origin', '')
        if page_may_call(origin, access.page_origin(FileOps())):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        # Authorization carries the passcode of a hosted helper
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        # a page published on the web calling a helper on this computer: chrome asks the
        # helper whether it agrees to be reached from a public site before it lets the page
        if self.headers.get('Access-Control-Request-Private-Network') == 'true':
            self.send_header('Access-Control-Allow-Private-Network', 'true')

    def admitted(self) -> bool:
        """Whether this request may go any further, answering it if not.

        Only a helper with `RequirePasscode` on asks anything. A request without the passcode
        is told 401 when it comes from the page - so the page can ask for the passcode - and
        404 when it comes from anywhere else, the same answer as a path that does not exist,
        so a stranger probing the address learns nothing about what is there. The Origin
        header can be written by anyone outside a browser; all that buys is the word 401.
        """

        fileops = FileOps()
        if not access.passcode_required(fileops): return True
        from_page = page_may_call(self.headers.get('Origin', ''), access.page_origin(fileops))
        address, source = access.client_address(
            self.headers, self.client_address[0], not is_loopback(Handler.host))
        guard = Handler.passcode_guard
        # a blocked address is refused before its passcode is looked at, right or wrong
        left = guard.blocked_for(address)
        if left:
            self.refuse_blocked(from_page, left)
            return False
        header = self.headers.get('Authorization')
        if access.passcode_matches(header, access.configured_passcode()):
            guard.right(address)
            return True
        # a request with no passcode is not a guess; one with the wrong passcode is
        if header and guard.wrong(address):
            # said whatever the console setting: rare, and the owner's to know - with where
            # the address was read, since which header a host sends could not be checked here
            to_console(f'[passcode] {address} blocked for {access.BLOCK_SECONDS // 60} minutes '
                       f'after {access.GUESSES_ALLOWED} wrong passcodes (address read from {source})')
            self.refuse_blocked(from_page, access.BLOCK_SECONDS)
            return False
        if from_page:
            self.send_json(401, {'error': 'this helper needs its passcode', 'passcode': True})
        else:
            self.send_json(404, {'error': 'not found'})
        return False

    def refuse_blocked(self, from_page: bool, seconds: float) -> None:
        """429 to the page, saying for how long - and 404 to anything else, as an unknown
        path is, so a stranger probing the address still learns nothing."""

        if not from_page:
            self.send_json(404, {'error': 'not found'})
            return
        minutes = max(1, math.ceil(seconds / 60))
        payload = json.dumps({
            'error': f'too many wrong passcodes - try again in {minutes} minutes',
            'blocked': True, 'retryAfterMinutes': minutes,
        }).encode('utf-8')
        self.send_response(429)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Retry-After', str(math.ceil(seconds)))
        self.cors()
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.cors()
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict:
        length = int(self.headers.get('Content-Length') or 0)
        if not length: return {}
        return json.loads(self.rfile.read(length).decode('utf-8'))

    def send_settings_file(self) -> None:
        """settings.ini's editable settings, for the page's User settings tab - or, from a
        helper that is not on this computer, only that it cannot be edited from here."""

        if not settings_file_editable():
            self.send_json(200, {'editable': False, 'settings': []})
            return
        path = FileOps().inifile
        try:
            with open(path, encoding='utf-8', newline='') as f:
                text = f.read()
        except OSError:
            text = ''
        self.send_json(200, {'editable': True, 'file': os.path.abspath(path),
                             'settings': settings_file.editable_settings(
                                 text, defaults=built_settings()),
                             'logFiles': log_file_places()})

    def save_settings_file(self) -> None:
        """Write the page's edits into settings.ini, in place. 403 from a helper that is not
        on this computer; 400, writing nothing, for a setting or value it will not take."""

        if not settings_file_editable():
            self.send_json(403, {'error': strings.ERROR_SETTINGS_NOT_EDITABLE})
            return
        try:
            asked = self.read_json()
        except Exception:
            self.send_json(400, {'error': 'invalid json'})
            return
        reset = asked.get('reset') is True
        values = {} if reset else asked.get('values')
        if not isinstance(values, dict):
            self.send_json(400, {'error': 'values must be an object'})
            return
        path = FileOps().inifile
        try:
            settings_file.ensure_settings_file(path)
            settings = settings_file.update_settings_file(path, values, built_settings(), reset)
        except ValueError as e:
            self.send_json(400, {'error': str(e)})
            return
        except OSError as e:
            self.send_json(500, {'error': f'could not write settings.ini: {e}'})
            return
        self.send_json(200, {'editable': True, 'file': os.path.abspath(path), 'settings': settings,
                             'logFiles': log_file_places()})

    def do_OPTIONS(self) -> None:
        # a preflight never carries the passcode - a browser sends none - so one is answered
        # for a page that may call this helper; behind a passcode, anything else is told what
        # an unknown path is, so it learns nothing about what is here
        fileops = FileOps()
        if access.passcode_required(fileops) and not page_may_call(
                self.headers.get('Origin', ''), access.page_origin(fileops)):
            self.send_json(404, {'error': 'not found'})
            return
        self.send_response(204)
        self.cors()
        self.end_headers()

    def refuse_method(self) -> None:
        """Any other method: past the passcode like everything else, then 405 - never
        http.server's own error page, which says what is answering."""

        if not self.admitted(): return
        self.send_json(405, {'error': 'method not allowed'})

    do_HEAD = do_PUT = do_DELETE = do_PATCH = refuse_method

    # endregion

    def do_GET(self) -> None:
        if not self.admitted(): return

        if self.path == '/api/auth':
            # nothing to say beyond having got this far: the page asks this to check a passcode
            self.send_json(200, {'ok': True})
            return

        if self.path == '/api/config':
            fileops = FileOps()
            self.send_json(200, {
                'username': fileops.get_setting(strings.SETTING_USERNAME) or '',
                'filetypes': strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA,
                'forced': FORCED_FILETYPES,
                'defaults': DEFAULT_FILETYPES,
                'settings': read_settings(fileops),
                # whether this helper can look up an AO3 time zone at all - the Windows app's
                # build checks it, since Windows has no zone database but the one packed in
                'zoneLookup': zone_lookup_works(),
                # only the Windows app: its version, and how an update is going
                **({'app': Handler.updater.status()} if Handler.updater else {}),
            })
            return


        if self.path == '/api/settings-file':
            self.send_settings_file()
            return

        if self.path == '/api/jobs':
            # which runs are really going, so the page can tell an interrupted run's record -
            # still saying 'running' - from one that is
            self.send_json(200, {'active': sorted(active_job_ids()), 'jobs': active_jobs()})
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/events'):
            self.stream_events(self.path.split('/')[3])
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/record'):
            self.send_live_record(self.path.split('/')[3])
            return

        if self.path.startswith('/api/jobs/') and '/blobs/' in self.path:
            parts = self.path.split('/')
            self.send_blob(parts[3], parts[5])
            return

        self.send_json(404, {'error': 'not found'})

    def do_POST(self) -> None:
        if not self.admitted(): return

        if self.path == '/api/update':
            self.start_update()
            return

        if self.path == '/api/settings-file':
            self.save_settings_file()
            return

        if self.path == '/api/runs/floors':
            # the page reads the run history out of the library it holds, and asks which of
            # those runs a quick scan may measure back to
            try:
                records = self.read_json().get('runs')
            except Exception:
                self.send_json(400, {'error': 'invalid json'})
                return
            # a partly finished floor names the works it could not download, for the warning
            self.send_json(200, {'runs': [
                {**record, 'missingDownloads': missing_downloads(record)}
                for record in floors_among(records if isinstance(records, list) else [])]})
            return

        if self.path == '/api/file-names':
            # the page dates files in the library itself, and names them the way a download
            # would - from the work's index entry where it has one
            try:
                files = self.read_json().get('files')
            except Exception:
                self.send_json(400, {'error': 'invalid json'})
                return
            fileops = FileOps()
            use_name_pattern(fileops)
            maximum = fileops.get_ini_value_integer(strings.INI_NAME_LENGTH,
                                                    strings.INI_DEFAULT_NAME_LENGTH)
            self.send_json(200, {'names': file_names_for(files, maximum)})
            return

        if self.path == '/api/runs/retryable':
            # the same arrangement: the page reads the history, the rule for how a run can
            # be retried is the helper's
            try:
                records = self.read_json().get('runs')
            except Exception:
                self.send_json(400, {'error': 'invalid json'})
                return
            self.send_json(200, {'runs': retryable_among(
                records if isinstance(records, list) else [], active_job_ids())})
            return

        if self.path.startswith('/api/jobs/') and '/storage/' in self.path:
            parts = self.path.split('/')
            self.storage_reply(parts[3], parts[5])
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/cancel'):
            self.cancel_job(self.path.split('/')[3])
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/force-stop'):
            self.force_stop_job(self.path.split('/')[3])
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/answer'):
            self.answer_job(self.path.split('/')[3])
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/pause'):
            self.hold_job(self.path.split('/')[3], True)
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/resume'):
            self.hold_job(self.path.split('/')[3], False)
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/skip'):
            self.skip_step(self.path.split('/')[3])
            return

        if self.path != '/api/jobs':
            self.send_json(404, {'error': 'not found'})
            return

        try:
            body = self.read_json()
        except Exception:
            self.send_json(400, {'error': 'invalid json'})
            return

        action = body.get('action')
        if action not in ACTIONS:
            # naming both sides matters: the usual cause is not a bad request but a helper
            # left running from an earlier session, which predates the action being added
            self.send_json(400, {'error':
                f"this helper does not know the action '{action}'. It understands "
                f"{', '.join(ACTIONS)}. If the button you pressed is newer than the helper, "
                'it is running older code - close its window and start the application again.'})
            return

        try:
            username, password, dropbox = access.credentials_from(body)
        except access.AccessError as e:
            self.send_json(400, {'error': str(e)})
            return
        options = resolve_options(body.get('options'))
        if options['skipLogin']:
            # no password is used, so none is kept. a run reading your own listing is found
            # by your username; any other has no use for one either
            password = ''
            if action not in USERNAME_ACTIONS: username = ''
            elif not username:
                self.send_json(400, {'error': 'a username is required to read your bookmarks '
                                              'or collections, even without logging in'})
                return
        elif not username or not password:
            self.send_json(400, {'error': 'username and password are required'})
            return

        # the option only means anything on the runs that offer it. the ui never sends it
        # otherwise, but the rule belongs here, where what arrives in a request is turned
        # into what a run may actually do - a stray flag must not make a routine run
        # re-fetch a whole library
        if action not in OVERWRITE_ACTIONS: options['overwrite'] = False
        # the import's alone: every other run replaces what is outdated as a matter of course
        if action != ACTION_IMPORT:
            options['replaceOutdated'] = False
            options['indexOnly'] = []
        # the scans alone can be resumed; the run itself checks the one named can be
        if action not in RESUME_ACTIONS: options['resume'] = options['retryMode'] = ''
        # the same for checking non-bookmarks, which costs a request per work outside a series
        if action not in NON_BOOKMARK_ACTIONS: options['nonBookmarks'] = False
        # a chosen floor is the quick scan's alone, and has to name a run that can be one -
        # refused here rather than discovered on the thread, so a bad pick is a straight answer
        if action != ACTION_QUICK: options['floorRun'] = ''
        # indexing the works a collection holds is the collection runs' alone. without it they
        # write nothing but the collections' files, so no series is followed either
        if action not in COLLECTION_ACTIONS:
            options['collectionWorks'] = False
            options['subcollections'] = False
            options['parentCollections'] = False
        elif not options['collectionWorks']: options['series'] = False
        # a chosen floor is checked by the run, once it can read the history through the page:
        # one that turns out not to qualify falls back to the usual rules and says so
        # only a custom run skipping its indexing, with no window, looks every indexed work up
        if action != ACTION_CUSTOM or options['reindex'] or options['dates']:
            options['recheck'] = False
        # a custom run told to skip indexing writes no json, because json is the index - unless
        # it looks every indexed work up on AO3, which rewrites each entry it reads
        indexing_run = options['reindex'] or action != ACTION_CUSTOM or options['recheck']
        filetypes = resolve_filetypes(body.get('filetypes'), force=indexing_run)
        # a collections run that is not indexing their works downloads nothing, so its record
        # must not say it saved html
        if action in COLLECTION_ACTIONS and not options['collectionWorks']:
            filetypes = list(FORCED_FILETYPES)
        # re-reading a non-bookmark writes its entry, which a run told not to index has ruled out
        # (and one looking every indexed work up re-reads the non-bookmarks among them anyway)
        if not indexing_run or options['recheck']: options['nonBookmarks'] = False

        url = (body.get('url') or '').strip()
        # checked here rather than on the thread, so a bad link is a straight answer to the
        # request instead of a job that starts and immediately fails. not for a retry: it
        # carries no link of its own - the run takes the earlier run's, from its record
        if options['resume']:
            pass
        elif action == ACTION_WORK:
            link = work_link(url)
            if not link:
                self.send_json(400, {'error': strings.ERROR_NOT_A_WORK_LINK})
                return
            # normalised now, so the run is handed a link rather than whatever was pasted
            url = link
        elif action in LIST_ACTIONS:
            links, unknown = work_links(url)
            # several fics take at most MAX_WORK_LINKS; an import any number
            most = None if action == ACTION_IMPORT else MAX_WORK_LINKS
            problem = (strings.ERROR_NOT_WORK_LINKS.format(', '.join(unknown[:10]))
                       if unknown else (strings.ERROR_NO_IMPORT_WORKS if action == ACTION_IMPORT
                                        else strings.ERROR_NO_WORK_LINKS) if not links
                       else strings.ERROR_TOO_MANY_WORK_LINKS.format(len(links), most)
                       if most is not None and len(links) > most else '')
            if problem:
                self.send_json(400, {'error': problem})
                return
            # one link to a line, which is also how the history file shows them
            url = '\n'.join(links)
        elif action in ACTIONS_NEEDING_URL:
            if strings.AO3_BASE_URL not in url or not parse_text.get_collection_name(url):
                self.send_json(400, {'error': strings.ERROR_NOT_A_COLLECTION})
                return

        background = body.get('background') is True
        library, answers = None, {}
        if background:
            # the page is not going to be there, so the library has to be reachable without
            # it - which only a library in Dropbox is
            if not dropbox:
                self.send_json(400, {'error': strings.ERROR_BACKGROUND_NEEDS_DROPBOX})
                return
            try:
                answers = background_answers(body.get('answers'))
            except ValueError as e:
                self.send_json(400, {'error': str(e)})
                return
            library = dropbox_library.DropboxChannel(dropbox['refreshToken'], dropbox['appKey'])

        try:
            answer_defaults, question_timeout = run_question_settings(
                body.get('answerDefaults'), body.get('questionTimeoutMinutes'))
            always = always_answers(body.get('alwaysAnswers'))
            _, unsure_timeout = run_question_settings(None, body.get('guessedDateTimeoutMinutes'))
            timeouts = question_timeouts(body.get('questionTimeouts'))
            log_lines, trim_logs = run_log_settings(body.get('runLogMaxLines'), body.get('trimOldRunLogs'))
            nobody_here = body.get('nobodyHere')
            if nobody_here is not None and not isinstance(nobody_here, bool):
                raise ValueError("'nobody's here' is true or false")
            zone_name = str(body.get('ao3TimeZone') or '')
            zone = ao3_zone(zone_name)
        except ValueError as e:
            self.send_json(400, {'error': str(e)})
            return

        job = Job(action, filetypes, username, options, url, background=background,
                  library=library, answers=answers)
        job.answer_defaults = answer_defaults
        job.always_answers = always
        job.question_timeout_minutes = question_timeout
        job.unsure_timeout_minutes = unsure_timeout
        job.question_timeouts = timeouts
        job.nobody_here = nobody_here
        job.run_log_max_lines = log_lines
        job.trim_old_run_logs = trim_logs
        job.ao3_zone = zone
        job.ao3_zone_name = zone_name if zone is not None else ''
        # a name this computer could not look up is said in the run's log once it starts
        job.ao3_zone_missing = zone_name if zone_name and zone is None else ''
        # only a label, written into the history file: which helper the page started it on
        job.helper = str(body.get('helper') or '')[:300]
        # one run at a time, checked and taken under the same lock so two starts arriving
        # together cannot both get in. two runs writing one library would each plan from a
        # folder the other is changing
        with Handler.jobs_lock:
            # claimed under this same lock by start_update, so a run cannot slip in between
            # the check that none is going and the app closing to update
            updating = Handler.updater is not None and Handler.updater.busy()
            busy = next((j for j in Handler.jobs.values() if not j.done.is_set()), None)
            if busy is None and not updating: Handler.jobs[job.id] = job
        if updating:
            self.send_json(409, {'error': strings.ERROR_RUN_DURING_UPDATE})
            return
        if busy is not None:
            self.send_json(409, {'error': strings.ERROR_RUN_IN_PROGRESS, 'activeJob': busy.id})
            return

        thread = threading.Thread(target=run_job, args=(job, password), daemon=True)
        thread.start()

        self.send_json(202, {'jobId': job.id, 'filetypes': filetypes, 'options': options})

    def start_update(self) -> None:
        """Update the Windows app to the latest release: 202 once it is downloading, and the
        app closes and starts again on its own. Never while a run is going - restarting would
        end it - and a run cannot start while an update is under way."""

        if Handler.updater is None:
            self.send_json(404, {'error': 'not found'})
            return
        with Handler.jobs_lock:
            busy = next((j for j in Handler.jobs.values() if not j.done.is_set()), None)
            claimed = busy is None and Handler.updater.claim()
        if busy is not None:
            self.send_json(409, {'error': strings.ERROR_UPDATE_DURING_RUN, 'activeJob': busy.id})
            return
        if not claimed:
            self.send_json(409, {'error': 'an update is already under way'})
            return
        try:
            release = Handler.updater.begin()
        except updates.UpdateError as e:
            self.send_json(409, {'error': str(e)})
            return
        self.send_json(202, {'version': release.version})

    def cancel_job(self, job_id: str) -> None:
        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        # the run notices at its next checkpoint and unwinds, keeping what it has saved
        job.cancel.set()
        self.send_json(202, {'cancelling': True})

    def send_live_record(self, job_id: str) -> None:
        """A run's record as the helper holds it now, for History's Download log.

        The file in the library is saved only every `LOG_FLUSH_SECONDS`, so a log read from it
        while the run is going is behind what the run window shows. The helper's copy is the
        whole of it. 404 for a run this helper does not have, or one with no record yet - the
        page then reads the file.
        """

        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        record = job.record if job else None
        if record is None:
            self.send_json(404, {'error': 'no such job'})
            return
        self.send_json(200, {'record': runs.snapshot(record)})

    def force_stop_job(self, job_id: str) -> None:
        """End a run now, from the History tab, whatever its thread is doing.

        The last resort for a run that will not stop - its page gone, its thread stuck where
        no stop is noticed. See `force_stop`. Answers with the record as it now stands, for
        the page to write into the library.
        """

        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return
        self.send_json(200, {'stopped': True, 'record': force_stop(job)})

    def skip_step(self, job_id: str) -> None:
        """Abandon the step a run is on and let it go to the next.

        A debug tool, offered only when settings.ini turns it on. It really does skip: what
        that step would have done does not happen, and the checklist marks it skipped rather
        than done so the run does not claim otherwise.
        """

        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        job.skip.set()
        self.send_json(202, {'skipping': True})

    def hold_job(self, job_id: str, hold: bool) -> None:
        """Pause or resume a run.

        Setting the flag is all this does; the run itself decides when to act on it, at the
        one point where stopping is safe. So this answers immediately and a run midway
        through a file keeps going until that file is written.

        A stop is never blocked by a pause, and resuming a run nobody paused does nothing,
        so the two buttons cannot be used to wedge each other.
        """

        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        if hold:
            # a second press does not restart the clock on a pause already going
            if not job.held.is_set():
                job.held_since = time.monotonic()
                job.held_at = runs.now()
            job.held.set()
        else:
            job.held.clear()
            job.held_since = None
            job.held_at = ''
        self.send_json(202, {'paused': hold})

    def answer_job(self, job_id: str) -> None:
        """Hand a run the answer to the question it is waiting on."""

        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        try:
            body = self.read_json()
        except Exception:
            self.send_json(400, {'error': 'invalid json'})
            return

        choice = body.get('choice')
        if choice not in ANSWER_CHOICES:
            # a run waiting on an answer must not be sent something it cannot act on
            self.send_json(400, {'error':
                f"'{choice}' is not one of {', '.join(ANSWER_CHOICES)}"})
            return

        job.reply({'choice': choice, 'date': parse_text.get_date_stamp(body.get('date') or ''),
                   # a scenario's question answered for every time it comes up
                   'always': body.get('always') is True})
        self.send_json(202, {'answered': True})


    def storage_reply(self, job_id: str, request: str) -> None:
        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return
        try:
            answer = self.read_json()
        except Exception:
            answer = {'error': 'the page sent an answer that could not be read'}
        if not job.storage_reply(request, answer):
            self.send_json(404, {'error': 'nothing is waiting for that'})
            return
        self.send_json(202, {'received': True})

    def send_blob(self, job_id: str, request: str) -> None:
        """The bytes of one write, for the page to put in the library."""

        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        content = job.blobs.get(request) if job else None
        if content is None:
            self.send_json(404, {'error': 'nothing to collect'})
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(content)))
        self.cors()
        self.end_headers()
        self.wfile.write(content)

    def stream_events(self, job_id: str) -> None:
        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.cors()
        self.end_headers()

        # anything that happened before this connection opened. taken, and the listener
        # counted, in one go: a background run only queues events while someone is listening,
        # so one emitted between the two would otherwise reach neither
        with job.lock:
            backlog = list(job.history)
            job.listeners += 1
            job.last_listener = time.monotonic()
        # by identity: the queue holds the same dicts as the history, and comparing each one
        # by value against hours of backlog would be slow
        replayed = {id(event) for event in backlog}
        try:
            for event in backlog:
                self.write_event(event)
            # a request about the library that a page which went away never answered - this
            # page is the only one that can. it may also still be in the queue, so the page
            # does each request once, by id
            for event in job.unanswered():
                self.write_event(event)
            # a page attaching to a run that has already ended has everything it will get -
            # the end was consumed by whoever was listening then, so nothing is coming
            if job.done.is_set(): return
            while True:
                try:
                    event = job.events.get(timeout=STREAM_HEARTBEAT_SECONDS)
                except queue.Empty:
                    # nothing to say, but saying it is how a closed page is found out
                    self.wfile.write(b': still here\n\n')
                    self.wfile.flush()
                    continue
                if event is None: break
                if id(event) in replayed: continue
                self.write_event(event)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass # the page navigated away
        finally:
            job.page_connected(False)
            # the stream is over, so the connection is too. the `keep-alive` header above
            # tells BaseHTTPRequestHandler to hold it open for another request, and a page
            # reading to the end of the stream would then wait for ever
            self.close_connection = True

    def write_event(self, event: dict) -> None:
        self.wfile.write(f'data: {json.dumps(event)}\n\n'.encode('utf-8'))
        self.wfile.flush()


def already_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """Whether a helper is already answering on this port.

    This asks by connecting, rather than by trying to bind and seeing what happens, because
    the two questions have different answers. On Windows SO_REUSEADDR - which HTTPServer
    turns on by default - lets a second process bind a port another one is already
    listening on: both 'start', and which of them answers any given request is undefined.
    The result is a helper that is silently the wrong one, an older build from a previous
    session answering the new page with its own settings.ini and its own code, which looks
    exactly like the new build ignoring its config.

    Turning SO_REUSEADDR off would stop that, but it also makes the port unbindable for
    minutes after a normal shutdown, while closed connections sit in TIME_WAIT - so
    stopping the application and starting it again would fail for no good reason. Probing
    for a live listener separates the two: a helper that is actually there is refused, and
    a port merely remembered by the operating system is not.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((host, port)) == 0


def background_running() -> bool:
    """Whether a background run is going and working - one paused is not.

    A paused run is waiting for someone, not doing anything, so it is not worth keeping a
    host awake for: if nobody comes back it is abandoned anyway (`abandon_overdue`). Nor is
    one told to stop: it is only unwinding, and a stop has to leave the host free to sleep
    whether the unwinding is quick or not.
    """

    with Handler.jobs_lock:
        return any(job.background and not job.done.is_set() and not job.held.is_set()
                   and not job.cancel.is_set() for job in Handler.jobs.values())


def paused_run_timeout() -> int:
    """Minutes a background run may sit paused before it is abandoned; 0 for never."""

    try:
        minutes = FileOps().get_ini_value_integer(strings.INI_PAUSED_RUN_TIMEOUT,
                                                  strings.INI_DEFAULT_PAUSED_RUN_TIMEOUT)
    except Exception:
        return strings.INI_DEFAULT_PAUSED_RUN_TIMEOUT
    return max(0, minutes)


def abandon_overdue(now: float | None = None, minutes: int | None = None) -> list[str]:
    """End every background run left paused longer than the timeout, and say which.

    Abandoning is a stop the helper takes on the user's behalf, so it goes the way a stop
    goes: `cancel` is set, the run unwinds at the pause gate it is waiting at - nothing is
    part-written there - and everything saved is kept. `abandoned` is what makes its record
    say so, rather than claim the user stopped it. A run that is not in the background is
    never abandoned: it needs its page, and ends when the page goes anyway.
    """

    minutes = paused_run_timeout() if minutes is None else minutes
    if not minutes: return []
    now = time.monotonic() if now is None else now
    ended = []
    with Handler.jobs_lock:
        jobs = list(Handler.jobs.values())
    for job in jobs:
        if not job.background or job.done.is_set() or job.cancel.is_set(): continue
        if not job.held.is_set() or job.held_since is None: continue
        if now - job.held_since < minutes * 60: continue
        job.abandoned = True
        said = strings.AO3_INFO_ABANDONED.format(minutes)
        job.emit({'type': progress.MESSAGE, 'text': said})
        if job.record: job.record.line(said)
        job.cancel.set()
        ended.append(job.id)
    return ended


# how long a finished run stays listed - long enough for a page to reattach and be shown how
# it ended, not so long that a helper up for weeks holds every run it ever did
FORGET_FINISHED_SECONDS = 60 * 60


def forget_finished(now: float | None = None) -> list[str]:
    """Drop runs that ended more than an hour ago. Their history files say how they went."""

    now = time.monotonic() if now is None else now
    with Handler.jobs_lock:
        old = [job_id for job_id, job in Handler.jobs.items()
               if job.done.is_set() and job.finished_at is not None
               and now - job.finished_at >= FORGET_FINISHED_SECONDS]
        for job_id in old: del Handler.jobs[job_id]
    return old


def abandons_at(job: Job) -> str:
    """When a paused background run will be abandoned, as an iso time, or '' for never."""

    minutes = paused_run_timeout()
    if not job.background or not job.held.is_set() or not job.held_at or not minutes: return ''
    try:
        paused = datetime.datetime.fromisoformat(job.held_at)
    except ValueError:
        return ''
    return (paused + datetime.timedelta(minutes=minutes)).isoformat(timespec='seconds')


def keep_awake_once(url: str, get=None) -> bool:
    """Knock on the helper's own front door, if a background run needs it kept awake.

    A free hosted service may be stopped after about 15 minutes with no request from outside -
    and a background run is exactly one with nobody's page talking to it. A request to its
    own public address goes out and back in through the host, which counts. Only while a
    background run is going: the rest of the time the service is left to sleep as usual.
    The answer does not matter (it is a 404 without the passcode); arriving is the point.
    """

    if not url or not background_running(): return False
    try:
        (get or requests.get)(url.rstrip('/') + '/api/awake', timeout=30)
    except Exception:
        pass # a knock that did not land costs nothing; the next one may
    return True


def watch_background(stop: threading.Event, url: str) -> None:
    """Look after background runs while nobody's page is: abandon one paused too long, and
    keep a host that sleeps awake for one that is working."""

    since_knock = 0.0
    while not stop.wait(WATCH_SECONDS):
        abandon_overdue()
        forget_finished()
        since_knock += WATCH_SECONDS
        if since_knock >= KEEP_AWAKE_SECONDS:
            since_knock = 0.0
            keep_awake_once(url)


def is_loopback(host: str) -> bool:
    return host == 'localhost' or host == '::1' or host.startswith('127.')


def built_settings() -> str:
    """The text of the settings.ini this copy was built with, or '' for a copy with none."""

    if not Handler.settings_defaults: return ''
    try:
        with open(Handler.settings_defaults, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def log_file_places() -> dict:
    """Where the helper's log file and the update logs are on this computer - said only with
    settings.ini, which only a helper on this computer offers. The update logs only where the
    app can update itself."""

    places = {'logFile': os.path.abspath(FileOps().logfile)}
    if Handler.updater:
        folder = Handler.updater.update_dir
        places['updateLogs'] = [str(folder / updates.LOG_NAME), str(folder / updates.OUTPUT_NAME)]
    return places


def settings_file_editable() -> bool:
    """Whether the page may edit this helper's settings.ini.

    Only a helper on this computer, and only one that asks for no passcode. A hosted helper's
    settings.ini is written by the deploy from its variables and baked into an image that a
    restart replaces, so an edit there would be lost and would disagree with the deployment;
    and it answers anyone who has the passcode, which is not the same as owning the file.
    """

    return is_loopback(Handler.host) and not access.passcode_required(FileOps())


def startup_problem(host: str, fileops: FileOps) -> str:
    """Why this helper must not start as configured, or '' when it may.

    Every one of these fails closed. A helper told to want a passcode and not given one
    would otherwise accept nobody or - worse, depending on how the check was written -
    everybody; and one listening beyond this computer without a passcode would hand any
    stranger the ao3 login of whoever used it last.
    """

    required = access.passcode_required(fileops)
    if required and not access.configured_passcode():
        return (f'{strings.INI_REQUIRE_PASSCODE} is on in settings.ini, but no passcode is '
                f'set. Put it in the {access.ENV_PASSCODE} environment variable.')
    if not is_loopback(host):
        if not required:
            return (f'refusing to listen on {host}, which other computers can reach, with '
                    f'{strings.INI_REQUIRE_PASSCODE} off. Turn it on in settings.ini and set '
                    f'{access.ENV_PASSCODE}.')
        if not access.configured_private_key():
            return (f'refusing to listen on {host} without {access.ENV_PRIVATE_KEY}: a hosted '
                    'helper only takes the ao3 login encrypted.')
    try:
        access.private_key()
    except ValueError as e:
        return str(e)
    return ''


def bring_settings_up_to_date(path: str, template: str | None = None) -> None:
    """Write settings.ini if it is missing, or add any setting it lacks, and say which - and
    comment out, marked deprecated, any setting this version no longer reads.

    The user's own values are left as they are. `template` is what to fill in from: the
    package's own settings.ini, or - for the Windows app - the defaults its deployment built
    it with. A settings.ini that cannot be written (read-only, say) is reported and left: the
    helper still runs on the defaults, which is what it would have done anyway.
    """

    try:
        created, added, deprecated = settings_file.ensure_settings_file(path, template)
    except OSError as e:
        print(f'settings.ini: could not bring {os.path.abspath(path)} up to date ({e}); '
              'using the defaults for anything missing')
        return
    if created:
        print(f'settings.ini: created {os.path.abspath(path)}')
    if added:
        print(f'settings.ini: added {", ".join(added)} to {os.path.abspath(path)}, with their '
              'defaults - edit them there to change them')
    if deprecated:
        print(f'settings.ini: {", ".join(deprecated)} no longer used by this version - commented '
              f'out in {os.path.abspath(path)} and marked deprecated')


def serve(port: int | None = None, host: str | None = None) -> None:
    host = host or os.environ.get(ENV_HOST) or HOST
    port = port or int(os.environ.get(ENV_PORT) or DEFAULT_PORT)

    # before anything reads it: a settings.ini that is missing is written, and one written
    # before a setting existed gets that setting added, with its explanation and default
    bring_settings_up_to_date(FileOps().inifile)
    # every file name the helper reads is read by FileNamePattern - from the first request on,
    # not only once a run or the page's config has asked for it
    use_name_pattern(FileOps())

    problem = startup_problem(host, FileOps())
    if problem:
        print(f'could not start: {problem}')
        raise SystemExit(1)

    # asking 0.0.0.0 whether anything is there means asking this computer
    probe = HOST if host in ('0.0.0.0', '::', '') else host
    if already_listening(probe, port):
        print(f'could not start: something is already listening on {host}:{port}.')
        print('that is almost always an ao3downloader helper left running from an earlier')
        print('session. close its window, or stop it with:')
        print(f'    powershell -c "Get-NetTCPConnection -LocalPort {port} -State Listen | '
              'ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"')
        print('then start this again. carrying on would leave the page talking to the old')
        print('helper, which has its own settings and may be running older code.')
        raise SystemExit(1)

    threading.Thread(target=watch_background,
                     args=(threading.Event(), os.environ.get(ENV_EXTERNAL_URL, '')),
                     daemon=True).start()

    Handler.host = host
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f'ao3downloader local api listening on http://{host}:{port}')
    if access.passcode_required(FileOps()):
        print('every request needs the passcode; logins are only taken encrypted'
              if access.configured_private_key() else 'every request needs the passcode')
    if console_logging():
        # said up front, so a host's log shows the setting took before anything arrives
        print(f'{strings.INI_CONSOLE_LOGGING} is on: every request and every line a run says '
              'is printed here')
    print('this window has to stay open while the web ui is running.')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nstopping')
    finally:
        httpd.server_close()


if __name__ == '__main__':
    serve()
