"""Structured progress reporting.

The console UI learns what is happening from print statements. The local gui server needs
the same information as data - page counts for a progress bar, rate limit pauses to show
as a warning - so the pieces that know about those emit an event as well as printing one.

Callers that pass nothing (the whole command line app) get exactly the old behaviour.
"""

from collections.abc import Callable
from typing import Any

ProgressCallback = Callable[[dict[str, Any]], None]

# event types
STARTED = 'started'
PHASE = 'phase'
AUTHENTICATED = 'authenticated'
PAGE = 'page'
WORK = 'work'
MESSAGE = 'message'
# how many downloaded works ao3 has updated since they were saved, and how many were saved
# before file names carried a date and so cannot be judged either way
REFRESH = 'refresh'
# a run stops here and waits for an answer before going on. the ui replies through
# /api/jobs/<id>/answer; a cancel releases the wait so nothing can hang on it.
QUESTION = 'question'
# a request for the web page to read or write the library - the page owns the folder, so
# every file a run touches goes through one of these. never kept in the job's history: a
# page reconnecting must not be handed old writes to do again
STORAGE = 'storage'
# older copies a run marked for removal and did not remove - stopped, failed, or refused
NOT_REMOVED = 'notRemoved'
# the steps this run intends to take, sent once at the start, and then one of these per
# change as it works through them. kept separate from PHASE: a phase says what kind of work
# is happening and repeats (a combined run downloads twice), while a step is a place in a
# plan and happens once, which is the only thing a checklist can be built on.
STEPS = 'steps'
STEP = 'step'

# a step's state. 'skipped' is not 'failed' - a run with no unfinished fics skips that step
# and nothing went wrong.
STEP_WAITING = 'waiting'
STEP_RUNNING = 'running'
STEP_DONE = 'done'
STEP_SKIPPED = 'skipped'
STEP_FAILED = 'failed'
# a resumed run's step that the run it picks up from had already finished
STEP_EARLIER = 'earlier'

# works the run could not download, sent once at the end so the gaps can be named
FAILURES = 'failures'
# works ao3 would not give us that FicHub did, sent once at the end beside FAILURES
RESCUED = 'rescued'
# works whose new copy arrived but whose older copy could not be safely removed
KEPT_COPIES = 'keptCopies'
# formats FicHub gave that may be an older cached copy - taken anyway, and warned about
FICHUB_OLDER = 'fichubOlder'
# Resolve issues' repairs not done because the name they would give is already taken
REPAIR_CLASHES = 'repairClashes'
# how many files the run came across with no date in the app's own form in their names - each one
# asked about (or answered for you). the page suggests dating them in Resolve issues
UNSURE_FILES = 'unsureFiles'
# the run's works with more than one file of a format - every copy kept
DUPLICATE_COPIES = 'duplicateCopies'
# bookmarks that were never works to begin with - a series, something hosted elsewhere, or
# a work since deleted. kept apart from FAILURES because nothing went wrong with these:
# there was never a work there to fetch, and no amount of retrying would change that
SKIPPED = 'skipped'
# ao3 has asked for a break. nobody chose this and it ends by itself.
PAUSED = 'paused'
RESUMED = 'resumed'
# the user asked for a break. this one ends only when they say so, and is kept separate
# from ao3's on purpose - they read the same on screen but nothing else about them is alike
HELD = 'held'
RELEASED = 'released'
FINISHED = 'finished'
FAILED = 'failed'

# phase names, reported alongside PHASE. a run does these in order, and only the ones
# the chosen file types call for.
AUTHENTICATING = 'authenticating'
INDEXING = 'indexing'
COLLECTIONS = 'collections'
SCANNING = 'scanning'
# reading the downloads folder to see what is already there
CHECKING_FILES = 'checking_files'
# comparing what is there against what ao3 now reports, to find the outdated copies
CHECKING_VERSIONS = 'checking_versions'
# working through unfinished fics one at a time: re-read, then fetch if the copy is behind.
# a bookmarks run indexes everything before downloading anything; an update run does not,
# because each fic has to be read from ao3 before there is anything new to say about it.
UPDATING = 'updating'
DOWNLOADING = 'downloading'
# asking FicHub for the works ao3 would not give us, at the end of a run
FICHUB = 'fichub'


def report(callback: ProgressCallback | None, kind: str, **fields: Any) -> None:
    """Send one progress event.

    A listener that raises must never take a download down with it, so anything thrown
    by the consumer is swallowed here.
    """

    if callback is None: return
    try:
        callback({'type': kind, **fields})
    except Exception:
        pass
