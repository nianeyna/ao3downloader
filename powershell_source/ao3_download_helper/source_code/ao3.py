"""Download works from ao3."""

import contextlib
import datetime
import os
import re
import sys
import traceback

import requests
from collections.abc import Callable

from bs4 import BeautifulSoup

from source_code import exceptions, indexing, naming, parse_soup, parse_text, progress, strings
from source_code.fileio import FileOps
from source_code.progress import ProgressCallback
from source_code.repo import Repository


# what replace_superseded did about an older copy
REPLACED = 'replaced'
KEPT = 'kept'
UNCONFIRMED = 'unconfirmed'


def bookmark_state(soup) -> dict:
    """The `bookmarked` field to write for a fic read from its own page, or nothing.

    Only a page that actually says - 'Edit Bookmark' or 'Bookmark' - changes the field. When
    it cannot tell (logged out, an unexpected page) the entry keeps whatever it had, so a
    fic a bookmarks walk marked as yours is not unmarked by a page that could not see.
    """

    try:
        state = parse_soup.get_bookmarked(soup)
    except Exception:
        return {}
    return {} if state is None else {strings.BOOKMARKED_FIELD: state}


def blank(value) -> bool:
    """Whether a value says nothing - empty, or a structure holding only empty values, as
    the tags a series page cannot give."""

    if isinstance(value, dict): return all(blank(v) for v in value.values())
    if isinstance(value, (list, tuple)): return len(value) == 0
    return value is None or value == ''



# where a blurb carries each date a bookmarks listing can be sorted by
SORT_DATE_SELECTORS = {'bookmarked': 'div.user p.datetime', 'updated': 'div.header p.datetime'}


def failure_reason(e: BaseException) -> dict:
    """Why a page or a file from ao3 could not be had, as a run records it.

    `reason` is one of `maintenance` (ao3's maintenance page, asked again and given up on),
    `status` (an answer outside 2xx - `status` holds the code), `connection` (no answer, or
    none in time), `no-data` (a page that came back but held nothing that could be read off
    it), or `other`. A failure several formats share names the worst of them: maintenance
    first, since it says ao3 itself was not there.
    """

    text = str(e)
    if isinstance(e, exceptions.Ao3DownException) or strings.ERROR_AO3_DOWN in text:
        return {'reason': REASON_MAINTENANCE}
    if isinstance(e, exceptions.InvalidStatusCodeException) or 'status code' in text:
        code = re.search(r'status code (\d{3})', text)
        return {'reason': REASON_STATUS, **({'status': int(code.group(1))} if code else {})}
    if isinstance(e, (exceptions.TimeoutException, requests.exceptions.ConnectionError,
                      requests.exceptions.Timeout)):
        return {'reason': REASON_CONNECTION}
    if text in (strings.ERROR_LISTING_UNREADABLE, strings.ERROR_WORK_STATS):
        return {'reason': REASON_NO_DATA}
    return {'reason': REASON_OTHER}


def failure_words(failed: dict) -> str:
    """Why something failed, in words: the recorded reason, then the error itself."""

    reason, error = failed.get('reason'), str(failed.get('error') or '')
    if reason == REASON_MAINTENANCE: words = strings.REASON_WORDS_MAINTENANCE
    elif reason == REASON_STATUS and failed.get('status'):
        words = strings.REASON_WORDS_STATUS.format(failed['status'])
    elif reason == REASON_CONNECTION: words = strings.REASON_WORDS_CONNECTION
    elif reason == REASON_NO_DATA: words = strings.REASON_WORDS_NO_DATA
    else: return error
    return f'{words} ({error})' if error and error != words else words


REASON_MAINTENANCE = 'maintenance'
REASON_STATUS = 'status'
REASON_CONNECTION = 'connection'
REASON_NO_DATA = 'no-data'
REASON_OTHER = 'other'


def listing_sort(link: str) -> str:
    """Which date a bookmarks listing is in order of, from its url: 'bookmarked', 'updated',
    or '' for ao3's own default (when each was bookmarked, but not asked for by name)."""

    if strings.AO3_SORT_BY_UPDATED in link: return 'updated'
    if strings.AO3_SORT_BY_BOOKMARKED in link: return 'bookmarked'
    return ''


def describe_listing_gap(gap: dict) -> str:
    """One line saying exactly where indexing broke off - which pages were read, which one
    failed, and how far back in date the listing got - for the run's window and its log."""

    if gap.get('kind') == 'work':
        return strings.AO3_INFO_INDEX_GAP_WORK.format(gap.get('id'), failure_words(gap))
    first, last, failed = gap.get('firstPage') or 1, gap.get('lastPage'), gap.get('failedPage')
    read = (strings.AO3_INFO_INDEX_GAP_NONE_READ if not last else
            strings.AO3_INFO_INDEX_GAP_READ.format(first, last, gap.get('works') or 0))
    total = gap.get('totalPages')
    where = (strings.AO3_INFO_INDEX_GAP_COLLECTION.format(gap.get('collection'), gap.get('items'))
             if gap.get('kind') == 'collection' else strings.AO3_INFO_INDEX_GAP_LISTING)
    line = strings.AO3_INFO_INDEX_GAP.format(where, failed, f' of {total}' if total else '',
                                             failure_words(gap), read)
    date = gap.get('reachedBookmarked') if gap.get('sort') == 'bookmarked' else \
        gap.get('reachedUpdated') if gap.get('sort') == 'updated' else gap.get('reachedBookmarked')
    if last and date:
        kind = 'updated' if gap.get('sort') == 'updated' else 'bookmarked'
        line += ' ' + strings.AO3_INFO_INDEX_GAP_DATE.format(kind, date)
    return line


def index_gaps(ao3) -> list[dict]:
    """The places this run's indexing broke off that still stand. A fic run's fic whose own
    page would not read counts only while it is still a failure - one FicHub supplied in the
    end was got after all."""

    gaps = list(getattr(ao3, 'index_failures', None) or [])
    failed = {str(x.get('id') or '') for x in getattr(ao3, 'failures', None) or []}
    return [gap for gap in gaps if gap.get('kind') != 'work' or str(gap.get('id')) in failed]


def page_bookmark_state(soup, existing: dict | None) -> dict:
    """What a work page may write to `bookmarked`: never a demotion of a known bookmark.

    Your AO3 bookmarks take precedence over every other way a fic came in. An entry the index
    already knows as your bookmark stays one when a fic run or the update pass reads its page,
    whatever the page shows; only an entry that is not yet a bookmark takes the page's word.
    """
    state = bookmark_state(soup)
    if was_bookmark(existing) and state.get(strings.BOOKMARKED_FIELD) is False:
        return {}
    return state


def carry_bookmark_details(document: dict, existing: dict | None) -> dict:
    """A reading with the bookmark details the entry on disk has that it does not say itself.

    A bookmark's notes, tags, date and the rest (`BOOKMARK_OWN_FIELDS`) carry on into every new
    reading - whether or not it is still a bookmark - unless the reading says otherwise: a walk
    of your AO3 bookmarks writes every one of them as AO3 has it, and that is what replaces
    them. Anything that knows nothing of your bookmark leaves them as they were.
    """

    on_disk = indexing.flatten(existing) or {}
    missing = {k: on_disk[k] for k in strings.BOOKMARK_OWN_FIELDS if k in on_disk and k not in document}
    return {**document, **missing} if missing else document


def keep_own_bookmark(document: dict, existing: dict | None) -> dict:
    """A FicHub reading with the bookmark's own fields as the entry on disk has them.

    FicHub cannot know whether a fic is your bookmark, nor your notes, tags or the date you
    bookmarked it. `fichub.entry_from` already carries them over from the entry it was handed,
    but that entry is read once, at the start of the FicHub step, and one that would not read
    then is handed over as None - so the file being written into is the last word: whatever it
    says of `bookmarked` and the rest is kept, and anything it does not say is not invented.

    How a fic came in (`from_link`, `from_import`) may be added alongside a bookmark: the page
    lists a bookmark as one whatever else its entry says (`originOf`).
    """

    on_disk = indexing.flatten(existing) or {}
    kept = {k: v for k, v in document.items() if k not in strings.BOOKMARK_OWN_FIELDS}
    kept.update({k: on_disk[k] for k in strings.BOOKMARK_OWN_FIELDS if k in on_disk})
    return kept


def was_bookmark(entry: dict | None) -> bool:
    """Whether an index entry is one of your bookmarks: only one that says so. An entry that
    says nothing (from before the field existed) is not counted as one, at the owner's request -
    such entries are marked by hand from the Works tab, or by the next walk of your bookmarks."""

    return bool(entry) and entry.get(strings.BOOKMARKED_FIELD) is True

class Ao3:
    def __init__(
            self, 
            repo: Repository, 
            fileops: FileOps, 
            filetypes: list[str], 
            pages: int | None, 
            series: bool, 
            images: bool,
            mark: bool = False,
            progress: ProgressCallback | None = None,
            cancelled: Callable[[], bool] | None = None,
            start: int = 1) -> None:
        self.repo = repo
        self.fileops = fileops
        self.progress = progress
        self.cancelled = cancelled
        # replaced at the start of each indexing run, so every file it touches agrees
        self.indexed_on = indexing.now()
        self.filetypes = filetypes
        self.pages = pages
        # which page of a listing to begin at. 'pages' is where to stop, and both are
        # absolute page numbers, so a run can cover a slice in the middle of a listing.
        self.start = start if start and start > 1 else 1
        # {work link: {FILETYPE: path of the copy this run is replacing}}. filled in by the
        # caller when it has worked out which downloads are out of date.
        self.superseded: dict[str, dict[str, str]] = {}
        # the folder scan, while downloading from the index: a format already here and not
        # named in `superseded` is current, and is not fetched again
        self.existing_copies: dict[str, dict[str, dict]] | None = None
        # the long way round (`download`), given the folder scan: whether the run overwrites,
        # the date each work on the listing says it was updated, and the works reopened
        # though every format was on disk, because a copy was behind
        self.overwriting = False
        # asks about a copy the long way round cannot judge alone - one whose name has no date
        # in the app's own form, or (overwriting) is newer than the page - answering whether
        # to fetch it. Set by the run; with none, such a copy is kept
        self.judge_copy = None
        self.listing_dates: dict[str, str] = {}
        self.reopened: set[str] = set()
        # formats of a work an overwriting run was told not to replace: the copy on disk is
        # newer than the version this run would write. by link, formats upper-case
        self.keep_formats: dict[str, set[str]] = {}
        # the works whose kept formats a question already said were kept - not said twice
        self.keep_said: set[str] = set()
        # what a kept format is said as: a newer copy kept on an overwriting run, or - on an
        # import told not to replace outdated copies - whatever copy you have
        self.keep_message = strings.AO3_INFO_KEEPING_NEWER
        # formats fetched only to replace a copy a work already has - an import told to replace
        # outdated copies, of formats it was not asked to add. a work with no copy of one of
        # these is not given one. upper-case
        self.held_only: set[str] = set()
        # the field marking a work a fic run indexed that is not your bookmark: by its link, or
        # (an import) because its file was found in your library
        self.origin_field = strings.FROM_LINK_FIELD
        # works this run could not download, in the order they were attempted. the log
        # records them too, but a run that leaves gaps should be able to say which ones
        # without anyone having to read a log file to find out.
        self.failures: list[dict] = []
        # works ao3 failed on that FicHub gave us instead: {id, link, title, downloaded}
        self.rescued: list[dict] = []
        # formats FicHub gave that there was no file of, dated before the last known update date
        # for the work: {id, link, title, formats, fichub, latest, latestFrom}. taken anyway (an
        # older version beats none), and warned about, since it may be an older cached copy
        self.fichub_older: list[dict] = []
        # Resolve issues' repairs not done: the name the file would get is another file's
        # ({id, link, file, wanted, site}) - reported at the end (`report_failures`)
        self.repair_clashes: list[dict] = []
        # new copies that arrived while the older copy they replace could not be removed.
        # nothing is lost, but there are now two copies, so the run names each one
        self.kept_copies: list[dict] = []
        # bookmarks that are not works at all, so could never be indexed or downloaded.
        # kept as a list rather than a count so the run can name each one at the end
        self.skipped_works: list[dict] = []
        # whether this run has already asked ao3 whether its login is still good. asked at
        # most once: it costs a request, and a lapsed session fails every work after it
        self.session_checked = False
        # what this run did to which fics, for the history file. three sets rather than one
        # because they answer different questions: what got a fresh index entry, what
        # arrived as a file, and what replaced a copy that was already on disk.
        self.reindexed: set[str] = set()
        # every file this run wrote, so the cleanup step can never remove one of them
        self.written: list[str] = []
        # when this run's readings were taken. `get_metadata` sets it as a walk starts; this
        # is for a run that indexes without walking a listing
        self.indexed_on = indexing.now()
        # series marked for walkthrough this run, by id, in the order they were marked:
        # `{id, title, bookmark}`, where `bookmark` is the series' own bookmark when it was
        # one of yours. walked once indexing is over - see `walk_marked_series`
        self.series_marked: dict[str, dict] = {}
        # series already walked this run, and the works each held
        self.series_read: dict[str, list[str]] = {}
        # set while the marked series are walked: a work met there does not mark its own
        # series, which would only mark the series being walked
        self.walking_series = False
        # told after each listing page is written, and after each series is walked, so a
        # run can save how far it got - see server.walk_listing. None when nobody asks
        self.on_page = None
        # the run writing the index, stamped on every entry it writes (`last_indexed_by`)
        self.run_id = ''
        self.on_series = None
        # whether the last listing walk reached its natural end - the last page, a page
        # limit, a floor or a known fic - rather than being stopped or failing partway
        self.walk_finished = False
        # set by server.walk_listing when a resumed run took a walk's works from the earlier
        # attempt rather than walking it again
        self.walk_skipped = False
        self.downloaded: set[str] = set()
        self.updated: set[str] = set()
        # work numbers seen on this run's listing that ao3 will not serve a file for yet,
        # because the work is in a collection that has not been revealed. they index fine;
        # it is only the download that is impossible, so they are held back from it.
        self.unrevealed: set[str] = set()
        # told after each page of a collection's listings, and after each collection is saved,
        # so a collection run can be resumed from there - see server.collections_ao3
        self.on_collection_page = None
        self.on_collection_done = None
        # what an earlier attempt of a resumed collection run saved, by collection
        self.collections_before: dict[str, dict] = {}
        # reads works back out of the index by number - a resumed run downloads what the
        # earlier attempt indexed without reading it from ao3 again
        self.records_for = None
        # set when a resumed collection run went straight back to its download step
        self.scoped = False
        # each index folder's entries by the number their file name starts with - see
        # `entry_path`. listed when first asked for, once per run
        self.entries_by_id: dict[str, dict[str, str]] = {}
        # the works the index held when this run first looked - before it wrote any entry.
        # `indexed_before_run`; a work outside it has no entry of its own to judge a copy by
        self.entries_at_start: set[str] | None = None
        # numbers found with more than one index file, and the one written to
        self.duplicate_entries: list[dict] = []
        # external works this run saved an entry for - its cleanup notes their collections
        self.externals_saved: set[str] = set()
        # collections saved with a listing that failed partway, which are not finished
        self.unfinished_collections: set[str] = set()
        # every place this run's indexing broke off: a listing walk that stopped on an error
        # (which pages it read, which page failed, how far back in date it got), a
        # collection listing, or a fic's own page. A run with any of these is only partly
        # done - see `index_gaps` - and never a floor for a quick scan
        self.index_failures: list[dict] = []
        # whether the last listing walk stopped on an error rather than ending as it should
        self.walk_failed = False
        # the formats of each work, by number, that this run saved whole - and those an earlier
        # attempt saved, which a retry carrying on from it does not fetch again (`format_done`)
        self.saved_formats: dict[str, set[str]] = {}
        self.formats_done: dict[str, set[str]] = {}
        # how far the collection listing being read has got: its first page, the last page
        # read in full, and the works found - said when one breaks off
        self.listing_read: dict = {}
        # whether a collection run follows each collection's subcollections, its parent, or
        # both - any number of steps away - and what it has read and has still to read
        # external works indexed off collections' bookmarked items this run, by ao3's number
        # for them - each written once, however many collections hold it
        self.externals_indexed: dict[str, dict] = {}
        self.last_externals: list[str] = []
        self.collection_externals = 0
        # series bookmarked among a collection's items, read back off `last_series` as external
        # works are; and the work numbers of each series this run has read for a collection
        # without indexing them - a series is read once however many collections hold it
        self.last_series: list[str] = []
        self.series_ids_found: dict[str, list[str]] = {}
        # how many works each series' blurb in a collection's items says it holds - when its
        # entry already lists that many, it is not read again
        self.series_counts: dict[str, int] = {}
        self.follow_subcollections = False
        self.follow_parents = False
        self.collections_seen: set[str] = set()
        self.family_queue: list[tuple[str, str]] = []
        # the works of every collection this run crawls, indexed as they are met - or None
        # when the run was not asked to, and a collection records only their work numbers
        self.collection_works: list[dict] | None = None
        # each work a collection crawl indexed, by id, so one met again in a second
        # collection is downloaded from what was read rather than read twice
        self.indexed_this_run: dict[str, dict] = {}
        self.series = series
        self.images = images
        self.mark = mark
        self.debug = fileops.get_ini_value_boolean(strings.INI_DEBUG_LOGGING, False)


    def download(self, link: str, visited: list[str] | None = None) -> None:

        log = {}
        if not visited: visited = []

        try:
            self.download_recursive(link, log, visited)
        except exceptions.CancelledException:
            # works already downloaded stay where they are; this is not a failure
            print(strings.INFO_CANCELLED)
        except exceptions.SessionExpiredException:
            raise  # every work after this one would fail the same way; let it end the run
        except Exception as e:
            self.log_error(log, e)


    def update(self, link: str, chapters: str) -> None:
        
        log = {}
        
        try:
            self.download_work(link, log, chapters)
        except exceptions.CancelledException:
            print(strings.INFO_CANCELLED)
        except Exception as e:
            self.log_error(log, e)


    def update_series(self, link: str, visited: list[str]) -> None:

        log = {}

        try:
            self.download_series(link, log, visited)
        except Exception as e:
            self.log_error(log, e)


    def get_metadata(self, link: str, workdates: bool,
                     known: set[str] | None = None, stop_before: str = '',
                     stop_on: str = 'updated', own_bookmarks: bool = False,
                     ceiling: str = '', ceiling_on: str = 'updated') -> list[dict]:
        """Walk a listing and save metadata for every work on it, one file per bookmark.

        One request per page rather than per work, so a bookmarks list of any size is
        cheap. Each page is written once it has been read in full, so a long run leaves
        usable output behind even if it is interrupted partway. Bookmarks of series,
        external works, and deleted works have none of the fields we're collecting, so
        they're counted and skipped rather than exported.

        `known` turns this into a **new bookmarks only** pass: walking stops at the first
        work already in that set, and only the works ahead of it are returned. Ao3 lists
        bookmarks newest first, so everything before the first familiar one is new and
        everything after it has been seen - which is what makes one stop enough, and what
        turns a run over a whole library into a request or two.

        That assumption is the catch, and it is why this is not the default. Re-bookmarking
        an old fic moves it to the front; a bookmark deleted and remade does the same. The
        run stops correctly either way, but a fic bookmarked *before* the stopping point
        and never indexed - because an earlier run was interrupted, say - stays unseen. A
        full walk is the answer to that, and the ui says so.

        `stop_before` is the other short walk: stop at the first work ao3 last updated
        before that date (`YYYY-MM-DD`). **It is only correct on a listing sorted by that
        date** - `strings.AO3_SORT_BY_UPDATED` - and the caller is responsible for asking
        for one. Verified against the live site: the default order is by when each work was
        bookmarked and jumps about by years, so this walk down an unsorted listing would
        stop almost immediately and miss nearly everything.

        `stop_on` says which date `stop_before` is measured against: `'updated'` (the
        work's own date, `div.header p.datetime`) or `'bookmarked'` (the bookmark's date,
        `div.user p.datetime`). The listing has to be sorted by the same date - a
        bookmarked stop down an updated-date listing is exactly as wrong as the reverse.

        `ceiling` (`YYYY-MM-DD`, measured on `ceiling_on`: 'updated' or 'bookmarked') is set
        by a **retry** alone: a blurb dated after it is passed over - not indexed, not
        returned - because it is after the date the run's first attempt began, and so the
        next scan's to find. The walk itself goes on exactly as before; only those blurbs are
        left out. On the date itself a blurb is kept: the ceiling counts.

        `own_bookmarks` says the listing is the logged-in user's own bookmarks, and marks
        every work read off it `bookmarked: True`. That is the one place the answer is
        certain - the fic is on the page because you bookmarked it. The caller says so rather
        than this guessing from the url, because a bookmarks url does not say whose.
        """

        if parse_text.is_work(link):
            raise exceptions.InvalidLinkException(
                strings.ERROR_METADATA_NOT_A_LISTING.format(strings.AO3_DOWNLOAD_TYPE_METADATA))
        if strings.AO3_BASE_URL not in link:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)

        source = link # the loop below walks `link` on to the next page
        # the listing itself is the source, not whichever page the run happened to begin
        # on, so a run that starts partway through still writes the same provenance
        link = parse_text.set_page_number(link, self.start)
        # one timestamp for the whole run, so every file this run touches agrees on when
        # it was indexed, and a second save of the same fic updates rather than appends
        self.indexed_on = indexing.now()

        # whether this walk can end before the listing does. a floor or a set of known works
        # stops it wherever the first older or familiar fic happens to sit, so the listing's
        # page count says nothing about how many pages this run will read - and 'page 3 of
        # 80' on a walk that stops at page 4 would be a promise it never meant to keep.
        # `total_pages` is still read and still ends the walk; it is only never *said*
        open_ended = bool(stop_before) or known is not None

        records: list[dict] = []
        seen: set[str] = set()
        skipped = 0
        total_pages = None
        self.walk_finished = False
        self.walk_failed = False
        # how far the walk got, for when it breaks off: the page it began on, the last one
        # read in full, and the dates on that page's last blurb - the bookmark's and the
        # work's own - which is how far back in time the listing was read
        first_page = parse_text.get_page_number(link)
        current = first_page
        last_good: int | None = None
        reached = {'bookmarked': '', 'updated': ''}

        try:
            while True:
                self.check_cancelled()
                current = parse_text.get_page_number(link)
                shown_total = None if open_ended else total_pages
                print(strings.AO3_INFO_METADATA_FETCHING.format(str(current), str(shown_total))
                      if shown_total else
                      strings.AO3_INFO_METADATA_FETCHING_FIRST.format(str(current)))
                # said before the request, so the ui names the page being fetched rather
                # than the last one that finished. the fetch is the slow part, and a
                # caption written only afterwards describes the wrong page for all of it
                asking, asking_of = self.page_progress(current, shown_total)
                progress.report(self.progress, progress.PAGE, page=asking, total=asking_of,
                                listingPage=current, listingTotal=shown_total, fetching=True)
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.fetch_page(link)
                if not parse_soup.get_blurbs(thesoup) and not parse_soup.looks_like_listing(thesoup):
                    # not a listing at all: an end to the walk taken from it would be a guess
                    raise exceptions.Ao3DownloaderException(strings.ERROR_LISTING_UNREADABLE)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(thesoup)
                page_records = []
                # bookmarks of a series or of a work off ao3: indexed in their own folders,
                # never downloaded, and never what a walk stops at
                page_series: list[dict] = []
                page_external: list[dict] = []
                reached_known = False
                for blurb in parse_soup.get_blurbs(thesoup):
                    if ceiling:
                        dated = parse_text.get_date_stamp(parse_soup.get_text_or_empty(
                            blurb, SORT_DATE_SELECTORS.get(ceiling_on, 'div.header p.datetime')))
                        if dated and dated > ceiling: continue
                    kind, number = parse_soup.get_blurb_kind(blurb)
                    if kind in (parse_soup.BLURB_SERIES, parse_soup.BLURB_EXTERNAL) and \
                            (number or kind == parse_soup.BLURB_EXTERNAL):
                        key = parse_soup.get_blurb_id(blurb) or f'{kind}-{number}'
                        if key in seen: continue
                        seen.add(key)
                        if kind == parse_soup.BLURB_SERIES:
                            document = parse_soup.get_series_bookmark_metadata(blurb, number)
                            document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_SERIES
                            page_series.append(document)
                        else:
                            document = parse_soup.get_external_bookmark_metadata(blurb, number)
                            document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_EXTERNAL
                            page_external.append(document)
                        document['source'] = source
                        if own_bookmarks: document[strings.BOOKMARKED_FIELD] = True
                        continue
                    worknum = number if kind == parse_soup.BLURB_WORK else None
                    if not worknum:
                        skipped += 1
                        # why, not just how many - a count leaves no way to tell which
                        # bookmark was passed over or to go and look at it
                        self.skipped_works.append(parse_soup.get_blurb_skip_reason(blurb))
                        continue
                    # it still gets indexed below - it has a number and a place in the
                    # listing - but asking ao3 for the file would fail by definition
                    self.note_unrevealed(blurb, worknum)

                    # a work only a collection led the index to is checked here, when reached:
                    # if you had not bookmarked it, it is new to your bookmarks, so the walk
                    # reads it (marking it bookmarked) and carries on
                    if known is not None and str(worknum) in known and \
                            (not hasattr(known, 'confirmed') or known.confirmed(str(worknum))):
                        # the first fic we already hold. everything past it on this page,
                        # and every page after it, has been seen before
                        print(strings.AO3_INFO_REACHED_KNOWN)
                        reached_known = True
                        break

                    if stop_before:
                        # only sound on a listing sorted by this date - see the docstring
                        selector = ('div.user p.datetime' if stop_on == 'bookmarked'
                                    else 'div.header p.datetime')
                        updated = parse_text.get_date_stamp(parse_soup.get_text_or_empty(
                            blurb, selector))
                        if updated and updated < stop_before:
                            print(strings.AO3_INFO_REACHED_OLDER.format(stop_before))
                            reached_known = True
                            break
                    # a work can be bookmarked more than once, and can shift between pages
                    # while we're paging through, so dedupe on the bookmark rather than the work
                    key = parse_soup.get_blurb_id(blurb) or str(worknum)
                    if key in seen: continue
                    seen.add(key)
                    document = {'source': source}
                    document.update(parse_soup.get_blurb_metadata(blurb))
                    document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_WORK
                    if own_bookmarks: document[strings.BOOKMARKED_FIELD] = True
                    records.append(document)
                    page_records.append(document)
                # nothing is written until the whole page has been read. a page is one unit
                # of work: it is fetched, parsed and only then saved, so a page abandoned
                # partway leaves no half-built entries and simply gets asked for again.
                # saving as each blurb was parsed made the page half-written by definition
                for document in page_records:
                    self.save_metadata(document)
                for document in page_external:
                    self.save_entry(document, strings.EXTERNAL_INDEX_FOLDER_NAME)
                # a series is not walked here: it is marked, and every marked series is
                # walked once indexing is over, so a work anywhere in the listing is read
                # from the listing and not a second time from a series
                for document in page_series:
                    self.save_series_entry(document)
                    self.mark_series(document['id'], document.get('title'), bookmark=document)
                for document in page_records:
                    self.mark_series_of(document)
                if self.on_page:
                    # the last bookmark on the page and the date it carries in the order the
                    # listing is sorted by - the date is what a retry looks for again, since
                    # pages move between attempts and an updated fic moves with them
                    blurbs = parse_soup.get_blurbs(thesoup)
                    anchor = None
                    if blurbs and parse_soup.get_blurb_id(blurbs[-1]):
                        sort = 'updated' if listing_sort(source) == 'updated' else 'bookmarked'
                        anchor = {'id': parse_soup.get_blurb_id(blurbs[-1]),
                                  'date': parse_text.get_date_stamp(parse_soup.get_text_or_empty(
                                      blurbs[-1], SORT_DATE_SELECTORS[sort])),
                                  'sort': sort}
                    self.on_page(current, anchor, [str(d['id']) for d in page_records
                                                   if d.get('id')])
                shown_total = None if open_ended else total_pages
                done, of = self.page_progress(current, shown_total)
                # two sets of numbers on purpose: the bar measures the slice being fetched,
                # so it runs 1..n and ends full, while the words say where that actually is
                # in the listing - 'page 42 of 80' is what you would go and look at
                progress.report(self.progress, progress.PAGE, page=done, total=of,
                                listingPage=current, listingTotal=shown_total,
                                works=len(records))
                last_good = current
                page_blurbs = parse_soup.get_blurbs(thesoup)
                if page_blurbs:
                    reached = {
                        'bookmarked': parse_text.get_date_stamp(parse_soup.get_text_or_empty(
                            page_blurbs[-1], 'div.user p.datetime')) or reached['bookmarked'],
                        'updated': parse_text.get_date_stamp(parse_soup.get_text_or_empty(
                            page_blurbs[-1], 'div.header p.datetime')) or reached['updated'],
                    }
                # said as soon as the page is in, and before any decision to stop: this used
                # to sit after the break checks, so the page a run ended on - the last one
                # of the listing, or the one the page limit stopped at - never reported
                # finishing at all
                print(strings.AO3_INFO_METADATA_PAGE.format(
                          str(current), str(shown_total), str(len(records)))
                      if shown_total else
                      strings.AO3_INFO_METADATA_PAGE_ONLY.format(
                          str(current), str(len(records))))
                # the works ahead of the familiar or older one are still new, so they were kept
                # and written; it is only the walking that stops here. after the page has said
                # it finished, not before - a walk stopped by a floor used to end on 'fetching
                # page 4' and never report the page it had actually read
                if reached_known or not total_pages or current >= total_pages:
                    self.walk_finished = True
                    break
                link = parse_text.get_next_page(link)
                if self.pages and parse_text.get_page_number(link) == self.pages + 1:
                    if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                    self.walk_finished = True
                    break
        except exceptions.CancelledException:
            # everything written so far stays on disk; this is not an error
            print(strings.INFO_CANCELLED)
        except Exception as e:
            # the walk ends here, keeping everything already written - but it did not reach
            # the end of the listing, and the run must say exactly how far it got rather
            # than carry on as though it had
            self.walk_failed = True
            gap = {
                'kind': 'listing', 'walk': '', 'listing': source,
                'sort': listing_sort(source),
                'firstPage': first_page, 'lastPage': last_good, 'failedPage': current,
                'totalPages': total_pages, 'works': len(records),
                'reachedBookmarked': reached['bookmarked'], 'reachedUpdated': reached['updated'],
                'error': str(e), **failure_reason(e),
            }
            self.index_failures.append(gap)
            print(strings.ERROR_LINKS_LIST)
            print(describe_listing_gap(gap))
            self.log_error({'message': strings.ERROR_LINKS_LIST, 'link': link}, e)
        except KeyboardInterrupt:
            print(strings.INFO_LINKS_LIST_CANCELED)

        if skipped: print(strings.AO3_INFO_METADATA_SKIPPED.format(str(skipped)))
        if workdates and records: self.add_work_dates(records)

        return records


    def save_images(self, soup, filename: list[str] | str, work_url: str,
                    title: str) -> int:
        """Save the images embedded in a work's page as files of their own.

        These are `<img>` tags in the work's rendered html, usually pointing at somewhere
        else entirely. The downloaded work normally carries them inside it already - this
        writes a second, separate copy of each, for when the pictures themselves are what
        is wanted.

        One image that will not come down never ends the run: ao3 has no say over hosts it
        does not own, and a dead image link is the single most ordinary failure here. Each
        is logged and the rest carry on. Returns how many were saved.
        """

        counter = 0
        for img in parse_soup.get_image_links(soup):
            # a site-relative src is ao3's own furniture, not part of the work
            if str.startswith(img, '/'): continue
            try:
                ext = os.path.splitext(img)[1]
                if '?' in ext: ext = ext[:ext.index('?')]
                response = self.repo.get_book(img)
                imagefile = filename + ' img' + str(counter).zfill(3) + ext
                self.fileops.save_bytes(
                    os.path.join(strings.IMAGE_FOLDER_NAME, imagefile), response)
                counter += 1
            except Exception as e:
                self.fileops.write_log({
                    'message': strings.ERROR_IMAGE, 'link': work_url, 'title': title,
                    'img': img, 'error': str(e), 'stacktrace': traceback.format_exc()})
        return counter


    def save_images_for(self, record: dict, maximum: int) -> int:
        """Fetch one indexed work's page purely to save the images embedded in it.

        The indexed download path never reads a work page - that is the whole of what makes
        it cheap - so there is nothing for `get_image_links` to read. This fetches the page
        separately, *after* the files themselves are safely down, which costs one extra
        request per work and is why nothing does it unless asked.

        The url is built from the work number rather than taken from the record, for the
        same reason the download links are: the number is the only part that matters.
        """

        link = f'{strings.AO3_BASE_URL}/works/{record["id"]}'
        soup = self.proceed(self.repo.get_soup(link))
        metadata = parse_soup.get_name_metadata_from_blurb(record)
        title = parse_soup.apply_name_pattern(metadata, strings.FILE_NAME_PATTERN)
        filename = naming.file_stem(
            metadata, parse_text.get_date_stamp(record.get('date_updated') or ''), maximum) \
            or str(record['id'])

        return self.save_images(soup, filename, link, ' / '.join(x for x in title if x))


    def index_one_work(self, link: str, existing: dict | None = None,
                       find_existing: Callable[[], dict | None] | None = None) -> dict:
        """Index a single fic from its own page, seen before or not.

        A work page and a bookmarks listing describe a fic differently, and the index is
        shaped by the listing. So an entry created here fills in only what a work page can
        honestly answer for - the title, the author, and the stats that get versioned - and
        leaves tags, the summary and the bookmark's own fields empty rather than inventing
        a second schema for them. A later bookmarks run fills those in, and `merge` treats
        it as the same document because the identity fields match.

        A fic already in the index keeps everything it has; only the stats are rewritten,
        exactly as `refresh_one` does.

        `find_existing` is how the fic runs hand that entry over: called only once ao3 has
        shown the work, so a fic ao3 will not show - down, deleted, locked - never costs a
        read of the library (in Dropbox, a download) on its way to FicHub.
        """

        soup = self.fetch_page(link, work=True)
        stats = parse_soup.get_work_stats(soup)
        if 'error' in stats:
            raise exceptions.Ao3DownloaderException(strings.ERROR_WORK_STATS)
        if find_existing is not None: existing = find_existing()

        record = dict(existing or {})
        if not record:
            page = parse_soup.get_work_metadata_from_work(soup, link)
            authors = [x.strip() for x in (page.get('author') or '').split(',') if x.strip()]
            record = {'id': parse_text.get_work_number(link), 'link': link,
                      'title': page.get('title') or '', 'authors': authors}

        fresh = {**record, **stats, **page_bookmark_state(soup, existing)}
        # an import marks only the entries it makes: a work already indexed came from
        # wherever it came from, and an import only brought its files up to date
        imported_before = self.origin_field == strings.FROM_IMPORT_FIELD and bool(existing)
        if not was_bookmark(existing) and fresh.get(strings.BOOKMARKED_FIELD) is not True \
                and not imported_before:
            fresh[self.origin_field] = True
        # a work page is only ever a work's - an entry made here is typed like any other
        fresh.setdefault(strings.BOOKMARK_TYPE_FIELD, strings.BOOKMARK_TYPE_WORK)
        # the series it is part of, read off its own page, so a run asked to walk them can
        memberships = parse_soup.get_series_memberships(soup)
        if memberships: fresh[strings.SERIES_MEMBERSHIP_FIELD] = memberships
        self.save_metadata(fresh)
        return fresh


    def refresh_one(self, record: dict) -> dict:
        """Re-read one fic from its own page and bring its index entry up to date.

        One request, going straight to the link the index already holds - no listing is
        walked to find it, because the index is the list.

        Only the fields a work page can speak to are written (see parse_soup.get_work_stats);
        the entry keeps the shape a bookmarks pass gave it, so tags and the bookmark's own
        fields are left as they were rather than half-overwritten from a page that says
        them differently.

        Returns the record as it now stands. Raises if the work cannot be read, which the
        caller turns into a recorded failure - the entry it already had stays as it was.
        """

        try:
            soup = self.fetch_page(record.get('link') or '', work=True)
            stats = parse_soup.get_work_stats(soup)
            if 'error' in stats:
                raise exceptions.Ao3DownloaderException(strings.ERROR_WORK_STATS)
        except (exceptions.CancelledException, exceptions.SessionExpiredException,
                exceptions.PausedException):
            raise
        except Exception as e:
            # a fic that could not be re-read is a gap in this run's index, not only a file
            # it could not get: the run is only partly done, and says which
            self.index_failures.append({'kind': 'work', 'id': str(record.get('id') or ''),
                                        'link': record.get('link') or '', 'error': str(e), **failure_reason(e)})
            raise

        fresh = {**record, **stats, **page_bookmark_state(soup, record)}
        self.save_metadata(fresh)
        return fresh

    def fetch_page(self, url: str, work: bool = False):
        """An ao3 page read for indexing, refused unless it is the page that was asked for.

        Ao3 serves 401, 403 and 404 as pages like any other, and read as a listing one has no
        bookmarks - which used to end a walk as though it had reached the end. Any status
        outside 2xx is a failure here, with the status in its reason. A work's page goes
        through `proceed` first, so a deleted or locked work still says so in its own words.
        """

        soup = self.repo.get_soup(url)
        if work: soup = self.proceed(soup)
        status = getattr(self.repo, 'last_status', None)
        if isinstance(status, int) and not 200 <= status < 300:
            raise exceptions.InvalidStatusCodeException(
                strings.ERROR_INVALID_STATUS_CODE.format(status))
        return soup


    def download_indexed(self, records: list[dict], visited: list[str] | None = None,
                         existing: dict | None = None,
                         forced: bool | set[str] = False) -> None:
        """Download the works the index lists, without reading ao3's listing again.

        The index already holds every work number and everything needed to name a file, so
        this skips two things the long way round pays for: walking the listing pages a
        second time to rediscover links we already have, and fetching each work's page to
        read a download link that the work number already determines.

        The trade-off is that nothing looks at the work page, so a work that is locked,
        deleted or hidden is not recognised as such - it just fails to download and is
        logged. Anything that genuinely needs the page (embedded images, marking as read,
        following series links) goes the long way round instead; see server.can_use_index.

        `existing` is the folder scan the run already made. Given it, the count is broken down
        by why each work is being fetched - see `say_why_downloading`. `forced` names the
        works being replaced at the user's request (`True` for all of them), so a current
        copy fetched again is not called out of date.
        """

        visited = visited or []
        maximum = self.fileops.get_ini_value_integer(
            strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        skip = set(visited)
        # an unrevealed work is held back rather than attempted: ao3 answers with a page
        # instead of a file, so the request is spent for certain and the run would report
        # it as a failure when nothing has actually gone wrong
        pending = [x for x in records
                   if x.get('id') and x.get('link') and x['link'] not in skip
                   and str(x['id']) not in self.unrevealed]

        print(strings.AO3_INFO_FROM_INDEX.format(len(pending)))
        if existing is not None: self.say_why_downloading(pending, existing, forced)

        self.existing_copies = existing
        try:
            self.download_pending(pending, maximum)
        finally:
            self.existing_copies = None

    def download_pending(self, pending: list[dict], maximum: int) -> None:
        """The loop of `download_indexed`, one work at a time."""

        for done, record in enumerate(pending, start=1):
            log: dict = {'link': record['link']}
            try:
                self.check_cancelled()
                self.download_one_indexed(record, maximum, log, done, len(pending))
            except exceptions.CancelledException:
                print(strings.INFO_CANCELLED)
                return
            except Exception as e:
                # one work that will not come down should not end the run - unless the
                # login has lapsed, in which case every work after it fails the same way
                self.check_session()
                self.record_failure(record['link'], e)
                self.log_error(log, e)


    def say_why_downloading(self, pending: list[dict], existing: dict,
                            forced: bool | set[str]) -> None:
        """Break the works about to be downloaded down by why: never downloaded, behind
        ao3, replaced at your request, or missing a format.

        Goes by what the check step already decided - `superseded` names the copies it will
        replace - so this only counts, and cannot disagree with it. A kind with none in it
        is not said.
        """

        new = updating = overwriting = missing = 0
        for record in pending:
            link = record['link']
            if not existing.get(str(record['id'])):
                new += 1
            elif link in self.superseded:
                if forced is True or (isinstance(forced, set) and link in forced):
                    overwriting += 1
                else:
                    updating += 1
            else:
                missing += 1
        for count, line in ((new, strings.AO3_INFO_FROM_INDEX_NEW),
                            (updating, strings.AO3_INFO_FROM_INDEX_UPDATING),
                            (overwriting, strings.AO3_INFO_FROM_INDEX_OVERWRITING),
                            (missing, strings.AO3_INFO_FROM_INDEX_MISSING)):
            if count: print(line.format(count))


    def download_one_indexed(self, record: dict, maximum: int, log: dict,
                             done: int, total: int,
                             fetch: Callable[[str], bytes] | None = None,
                             arrived: list[str] | None = None) -> None:
        """Fetch one work's files straight from its work number.

        `fetch` gets one format's bytes from somewhere other than ao3 - FicHub, for a work
        ao3 would not give us - and everything after it (the name, the checks on the saved
        file, replacing an older copy) is the same. `arrived` is filled with the formats
        that came down and were saved intact.
        """

        work = str(record['id'])
        metadata = parse_soup.get_name_metadata_from_blurb(record)
        title = parse_soup.apply_name_pattern(metadata, strings.FILE_NAME_PATTERN)
        updated = record.get('date_updated') or ''
        filename = naming.file_stem(metadata, parse_text.get_date_stamp(updated), maximum) or work

        log['title'] = title
        # the same two fields the long way round records, so the 'already downloaded' check
        # can rebuild this exact name next time
        log['updated'] = updated

        display = ' / '.join(x for x in title if x)
        failed: list[tuple[str, Exception]] = []
        kept = self.keep_formats.get(record['link']) or set()
        current = self.current_formats(record)
        wanted = self.wanted_formats(record)
        formats = [x for x in wanted if x.upper() not in kept
                   and not self.format_done(work, x) and x.upper() not in current]
        for filetype in wanted:
            if filetype.upper() in kept:
                if record['link'] not in self.keep_said: print(self.keep_message.format(filetype))
            elif self.format_done(work, filetype):
                print(strings.AO3_INFO_FORMAT_DONE_EARLIER.format(filetype, work))
            elif filetype.upper() in current:
                print(strings.AO3_INFO_FORMAT_CURRENT.format(filetype))
        for filetype in formats:
            self.check_cancelled()
            progress.report(self.progress, progress.WORK, title=display,
                            link=record['link'], filetype=filetype,
                            phase=progress.DOWNLOADING, done=done, total=total)
            with self.one_format(filetype, failed):
                content = fetch(filetype) if fetch else self.repo.download_file(
                    parse_text.get_direct_download_link(work, filetype), filetype)
                self.save_download(record['link'], filetype,
                                   filename + parse_text.get_file_type(filetype), content)
                if arrived is not None: arrived.append(filetype)

        # anything that did arrive is a download, even when a format beside it failed
        if len(failed) < len(formats): self.downloaded.add(work)
        self.raise_if_formats_failed(failed)
        log['success'] = True
        self.fileops.write_log(log)


    def wanted_formats(self, record: dict) -> list[str]:
        """The run's formats for this work, less any of `held_only` it has no copy of."""

        if not self.held_only: return list(self.filetypes)
        here = {str(x).upper()
                for x in ((self.existing_copies or {}).get(str(record.get('id'))) or {})}
        return [x for x in self.filetypes if x.upper() not in self.held_only or x.upper() in here]

    def current_formats(self, record: dict) -> set[str]:
        """The formats of this work already in the folder that the check step did not mark
        to be replaced - so current, and not fetched again.

        A work is downloaded because some format of it is missing or behind; the others may
        be perfectly current, and fetching them again spends a request each for nothing. The
        check step's `superseded` names exactly the copies it decided to replace (behind the
        index, undated ones the user chose to refresh, or every one on an overwriting run), so
        a copy here and not there is kept - the one rule for what is outdated. Only while
        downloading from the index with a folder scan to go by (`existing_copies`).
        """

        if not self.existing_copies: return set()
        here = {str(x).upper() for x in (self.existing_copies.get(str(record.get('id'))) or {})}
        replacing = {str(x).upper() for x in (self.superseded.get(record.get('link')) or {})}
        return here - replacing

    def format_done(self, work: str, filetype: str) -> bool:
        """Whether an earlier attempt this run carries on from already saved this format of
        this work whole - in which case it is not fetched again, even on a run that
        overwrites: that attempt already did the overwriting."""
        return filetype.upper() in self.formats_done.get(str(work), ())

    @contextlib.contextmanager
    def one_format(self, filetype: str, failed: list[tuple[str, Exception]]):
        """Try one format of a work, noting a failure and carrying on to the next format.

        A work used to stop at its first failing format, so a fic ao3 had no epub for never
        got its pdf either, and the failure named only the first. Each format is a separate
        file at its own url, so one missing says nothing about the others.

        A stop and a lapsed login still end everything - every format after would fail the
        same way, and a stop means stop.
        """

        try:
            yield
        except (exceptions.CancelledException, exceptions.SessionExpiredException):
            raise
        except Exception as e:
            failed.append((filetype, e))
            print(strings.INFO_FORMAT_FAILED.format(filetype, e))


    def raise_if_formats_failed(self, failed: list[tuple[str, Exception]]) -> None:
        """Fail the work once every format has been tried, naming each one that failed.

        One exception for the lot, because a work is one entry in the failure list and a
        work already counted as failed would not be recorded a second time. It is a
        `SavedFileException` only if every failure was one, so a folder problem still does
        not spend a request checking the login - but a single ao3 failure among them does.
        """

        if not failed: return
        message = '; '.join(strings.ERROR_FORMAT_FAILED.format(ft, e) for ft, e in failed)
        if all(isinstance(e, exceptions.SavedFileException) for _, e in failed):
            raise exceptions.SavedFileException(message)
        raise exceptions.DownloadException(message)


    def page_progress(self, current: int, total_pages: int | None) -> tuple[int, int | None]:
        """Where a page sits in the slice being fetched, rather than in the whole listing.

        A run over pages 42 to 80 is fetching 39 pages, and the first of them is page 1 of
        39. Reporting it as 42 of 80 would start the bar at half full and leave it at 100%
        having fetched less than half the listing. The stop page counts too: pages 42 to 60
        is 19 pages, not 39.
        """

        done = current - self.start + 1
        if not total_pages: return done, None
        last = min(total_pages, self.pages) if self.pages else total_pages
        return done, max(1, last - self.start + 1)


    def walk_pages(self, link: str, stop: int | None = None):
        """Yield each page of a paginated ao3 listing, following 'next' until it runs out -
        or until page `stop`, when given. It starts on whatever page `link` names."""

        total_pages = None
        while True:
            self.check_cancelled()
            soup = self.fetch_page(link)
            yield soup
            if total_pages is None:
                total_pages = parse_soup.get_total_pages(soup)
            pagenum = parse_text.get_page_number(link)
            if not total_pages or pagenum >= total_pages: break
            if stop and pagenum >= stop: break
            link = parse_text.get_next_page(link)
            if self.pages and parse_text.get_page_number(link) == self.pages + 1: break


    def collect_work_ids(self, link: str, collection: str = '', key: str = '',
                         earlier: dict | None = None, stop: int | None = None) -> list[str]:
        """Every work id on a listing, which is all a collection needs to record.

        The works themselves are described by the index in downloads/indexing, so there
        is nothing to gain from repeating their metadata here.

        When the run was asked to index the works too (`collection_works`), each one is
        indexed off the same page - the blurb carries everything a bookmarks listing would -
        so it costs nothing on top of the crawl. A page is written once it has been read in
        full, as a bookmarks listing is.

        `on_collection_page` is told after every page - which one, and every work number found
        so far - so a run can be resumed from there. `earlier` is that saved state from the
        attempt being resumed: the walk starts again **on the last page it saved**, not the
        one after. Works removed from the collection since pull later ones up a place, and
        reading that page again catches a work that moved onto it; works added since push
        others down, which only means one is seen twice, and is kept once.
        """

        found: list[str] = [str(x) for x in (earlier or {}).get('ids') or []]
        # the external works among the items, by ao3's number for them - a bookmarked-items
        # listing can hold them, and they have no work number to go in `found`. read back by
        # the caller off `last_externals`
        external_ids: list[str] = [str(x) for x in (earlier or {}).get('externals') or []]
        self.last_externals = external_ids
        # the series among the items, by ao3's number for them - read by the caller off
        # `last_series`, which reads each one's works once the listing is done
        series_ids: list[str] = [str(x) for x in (earlier or {}).get('series') or []]
        self.last_series = series_ids
        start = int((earlier or {}).get('page') or 1)
        if found:
            # read before this attempt: indexed then, so downloaded with the rest now
            self.keep_indexed(found)
        page = start
        self.listing_read = {'firstPage': start, 'lastPage': None, 'works': len(found)}
        for soup in self.walk_pages(parse_text.set_page_number(link, start) if start > 1
                                    else link, stop):
            readings: list[dict] = []
            externals: list[dict] = []
            for blurb in parse_soup.get_blurbs(soup):
                kind, work = parse_soup.get_blurb_kind(blurb)
                if kind == parse_soup.BLURB_SERIES:
                    if work and work not in series_ids: series_ids.append(work)
                    count = parse_text.get_count(parse_soup.get_text_or_empty(blurb, 'dd.works'))
                    if work and count: self.series_counts[work] = count
                    continue
                if kind == parse_soup.BLURB_EXTERNAL:
                    if work and work not in external_ids: external_ids.append(work)
                    if self.collection_works is None or not work: continue
                    # read already this run, off another collection: not read twice. which
                    # collections hold it is noted by the run's cleanup, from the files
                    if work in self.externals_indexed: continue
                    externals.append(parse_soup.get_external_bookmark_metadata(blurb, work))
                    continue
                if kind != parse_soup.BLURB_WORK or not work or work in found: continue
                found.append(work)
                if self.collection_works is None: continue
                self.note_unrevealed(blurb, work)
                if work in self.indexed_this_run:
                    # read already this run, off another collection: not read twice, only
                    # downloaded with the rest. which collections hold it is noted by the
                    # run's cleanup step, from the collections' own files
                    self.keep_collection_work(self.indexed_this_run[work])
                    continue
                readings.append(parse_soup.get_blurb_metadata(blurb))
            for document in readings:
                self.keep_collection_work(self.save_collection_work(document, collection, link))
            for document in externals:
                self.save_collection_external(document, collection, link)
            if self.on_collection_page and key:
                self.on_collection_page(collection, key, page, list(found),
                                        externals=list(external_ids), series=list(series_ids))
            self.listing_read = {'firstPage': start, 'lastPage': page, 'works': len(found)}
            page += 1
        return found


    def keep_indexed(self, ids: list[str]) -> None:
        """Add works an earlier attempt indexed to the ones this run downloads, from the index."""

        if self.collection_works is None or not self.records_for: return
        for record in self.records_for(ids):
            if record.get('id'): self.indexed_this_run.setdefault(str(record['id']), record)
            self.keep_collection_work(record)


    def keep_collection_work(self, document: dict) -> None:
        """Add a work to the ones this run will download, once."""

        if self.collection_works is None: return
        work = str(document.get('id') or '')
        if work and all(str(x.get('id') or '') != work for x in self.collection_works):
            self.collection_works.append(document)


    def save_collection_external(self, document: dict, collection: str, listing: str) -> None:
        """Index an external work - one hosted somewhere other than ao3 - that a collection's
        bookmarked items include, in the same folder your own bookmarked external works go.

        The rules of `save_collection_work`: it is somebody else's bookmark, so their notes and
        tags are not written in as yours, an entry that exists keeps its own, and a new one is
        not bookmarked. Never downloaded - there is nothing on ao3 to download. Which
        collections hold it is noted by the run's cleanup step, as for every entry.
        """

        path = self.as_not_yours(document, strings.EXTERNAL_INDEX_FOLDER_NAME)
        document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_EXTERNAL
        document['source'] = document.get('source') or listing
        self.save_entry(document, strings.EXTERNAL_INDEX_FOLDER_NAME, path)
        if document.get('id'): self.externals_indexed[str(document['id'])] = document
        self.collection_externals += 1


    def list_entries(self, folder: str) -> dict[str, str]:
        """Every entry in an index folder by the number its file name starts with.

        A library written by an older version can hold **two files for one work** - it used
        to write by the name a work would be given from its current title, so a retitled work
        got a second file. Where a number has more than one, the one written most recently
        (`last_indexed`) is the entry, the same one every time, and the run says which
        numbers it found doubled rather than quietly choosing. Nothing is deleted.
        """

        names: dict[str, list[str]] = {}
        try:
            for name in self.fileops.list_files(os.path.join(self.fileops.downloadfolder, folder)):
                if not str(name).lower().endswith('.json'): continue
                number = parse_text.get_work_number_from_filename(str(name))
                if number: names.setdefault(number, []).append(str(name))
        except Exception:
            return {}

        chosen: dict[str, str] = {}
        for number, found in names.items():
            if len(found) == 1:
                chosen[number] = found[0]
                continue

            def written(name: str) -> str:
                try:
                    data = self.fileops.load_json(os.path.join(folder, name))
                    return str((data or {}).get(indexing.LAST_INDEXED) or '')
                except Exception:
                    return ''
            chosen[number] = max(sorted(found), key=written)
            self.duplicate_entries.append({'id': number, 'files': sorted(found),
                                           'kept': chosen[number]})
            print(strings.AO3_INFO_DUPLICATE_ENTRIES.format(number, len(found), chosen[number]))
        return chosen


    def as_not_yours(self, document: dict, subfolder: str = '') -> str:
        """Make a reading of somebody else's bookmark safe to write as an entry of yours.

        Their notes, tags and the rest of `BOOKMARK_OWN_FIELDS` are blanked - to the empty
        shape a series work has, rather than removed - then an entry that already exists gets
        its own back, and its source. A new entry is recorded as not bookmarked. Returns the
        path the entry is at, or is to go - write it there.
        """

        for field in strings.BOOKMARK_OWN_FIELDS:
            if field in document:
                value = document[field]
                document[field] = [] if isinstance(value, list) else \
                    False if isinstance(value, bool) else ''
        document.pop(strings.BOOKMARKED_FIELD, None)
        path = self.entry_path(document, subfolder)
        existing = indexing.flatten(self.fileops.load_json(path)) or {}
        for field in strings.BOOKMARK_OWN_FIELDS:
            if field in existing: document[field] = existing[field]
        document.setdefault(strings.BOOKMARKED_FIELD, False)
        if existing.get('source'): document['source'] = existing['source']
        return path


    def entry_path(self, document: dict, subfolder: str = '') -> str:
        """Where an entry already lives, found by the number its file name starts with - or
        where a new one would go.

        Not by the name it would be given now: that is built from the title and author,
        which change - a retitled work, a renamed author - and a lookup by the new name misses
        the entry that is there, writes a second file for the same work, and records it as
        not bookmarked. `series_path` finds series the same way for the same reason. The
        folder is listed once per run and remembered.
        """

        folder = os.path.join(strings.INDEXING_FOLDER_NAME, subfolder) if subfolder \
            else strings.INDEXING_FOLDER_NAME
        known = self.entries_by_id.get(folder)
        if known is None:
            known = self.list_entries(folder)
            self.entries_by_id[folder] = known
            # the first listing comes before the first write into the folder, so it is the
            # index as the run found it
            if folder == strings.INDEXING_FOLDER_NAME and self.entries_at_start is None:
                self.entries_at_start = set(known)
        number = str(document.get('id') or '')
        if number and number in known: return os.path.join(folder, known[number])
        # not remembered here: a lookup can be made with little more than a number (a
        # series' `series_existing`), and the name built from that is not one to reuse. a
        # name is remembered once a file has been written under it - `remember_entry`
        return self.metadata_path(document, subfolder)


    def indexed_before_run(self) -> set[str]:
        """The works that had an index entry before this run wrote any - by number.

        A work outside it came into the index this run (or not at all), so a copy of it
        already in the library has no entry of its own to be judged against: the date the run
        just indexed says what is incoming, not what the copy holds. Every write goes through
        `entry_path`, which lists the folder before its first write, so that listing is the
        index as the run found it; with no write yet, a listing now is the same thing.
        """

        if self.entries_at_start is None:
            folder = strings.INDEXING_FOLDER_NAME
            known = self.entries_by_id.get(folder)
            if known is None:
                known = self.list_entries(folder)
                self.entries_by_id[folder] = known
            self.entries_at_start = set(known)
        return self.entries_at_start


    def remember_entry(self, path: str) -> None:
        """Note a file just written, so the rest of the run finds it by its number."""

        folder, name = os.path.split(path)
        number = parse_text.get_work_number_from_filename(name)
        known = self.entries_by_id.get(folder)
        if number and known is not None: known.setdefault(number, name)


    def save_collection_work(self, document: dict, collection: str, listing: str) -> dict:
        """Index one work read off a collection's listing.

        The same rules as a work read off a series page (`save_series_work`): a collection
        knows the work but nothing about your own bookmark of it. A listing of the
        collection's *bookmarks* carries somebody else's bookmark - their notes, their tags -
        so those fields are dropped rather than written in as yours. An entry that already
        exists keeps its own; a new one is recorded as **not bookmarked**.
        """

        path = self.as_not_yours(document)
        document['source'] = document.get('source') or listing
        document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_WORK
        self.save_metadata(document, path)
        if document.get('id'): self.indexed_this_run[str(document['id'])] = document
        self.mark_series_of(document)
        return document


    def collect_collection_links(self, link: str) -> list[str]:
        """Every collection linked from a collections listing."""

        found: list[str] = []
        for soup in self.walk_pages(link):
            for blurb in parse_soup.get_collection_blurbs(soup):
                slug = parse_soup.get_collection_slug(blurb)
                if not slug: continue
                url = f'{strings.AO3_BASE_URL}/collections/{slug}'
                if url not in found: found.append(url)
        return found


    def get_collections(self, link: str) -> list[dict]:
        """Walk a user's collections and save each one to its own file.

        Each collection is written as it is finished, so stopping partway keeps whatever
        was already saved, the same as indexing bookmarks does.
        """

        if strings.AO3_BASE_URL not in link:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)

        source = link
        self.indexed_on = indexing.now()
        records: list[dict] = []

        try:
            for soup in self.walk_pages(link):
                for blurb in parse_soup.get_collection_blurbs(soup):
                    slug = parse_soup.get_collection_slug(blurb)
                    if not slug: continue
                    self.take_collection(slug, source, records, blurb)
            self.walk_family(records)
        except exceptions.CancelledException:
            print(strings.INFO_CANCELLED)
        except Exception as e:
            print(strings.ERROR_COLLECTIONS)
            self.log_error({'message': strings.ERROR_COLLECTIONS, 'link': link}, e)
        except KeyboardInterrupt:
            print(strings.INFO_LINKS_LIST_CANCELED)

        return records


    def get_collection(self, link: str) -> list[dict]:
        """Index a single collection, given a link to any of its pages.

        Returns a list so a caller can treat this and get_collections alike. Costs one
        request for the profile plus the item listings, and skips those listings entirely
        when the counts say nothing has moved - the same as indexing your own collections.
        """

        if strings.AO3_BASE_URL not in link:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)
        slug = parse_text.get_collection_name(link)
        if not slug:
            raise exceptions.InvalidLinkException(strings.ERROR_NOT_A_COLLECTION)

        self.indexed_on = indexing.now()
        records: list[dict] = []

        try:
            print(strings.AO3_INFO_COLLECTION_ONE.format(slug))
            self.take_collection(slug, link, records)
            self.walk_family(records)
        except exceptions.CancelledException:
            print(strings.INFO_CANCELLED)
        except Exception as e:
            print(strings.ERROR_COLLECTIONS)
            self.log_error({'message': strings.ERROR_COLLECTIONS, 'link': link}, e)
        except KeyboardInterrupt:
            print(strings.INFO_LINKS_LIST_CANCELED)

        return records


    def take_collection(self, slug: str, source: str, records: list[dict], blurb=None) -> None:
        """Read one collection and save it - or, when the attempt being resumed finished it,
        take what that attempt saved. Either way its family is queued, when the run follows it.

        Every collection this run takes is remembered (`collections_seen`), which is what
        stops a family whose members point at each other from being walked round for ever:
        a collection is read at most once per run, however many others link to it.
        """

        self.collections_seen.add(slug)
        if self.finished_before(slug):
            records.append({'name': slug})
            return
        document = self.read_collection(slug, source, blurb)
        records.append(document)
        self.save_collection(document)
        self.collection_saved(slug, document)
        progress.report(self.progress, progress.WORK, title=document.get('title') or slug,
                        phase=progress.COLLECTIONS, done=len(records))
        print(strings.AO3_INFO_COLLECTION_SAVED.format(slug))
        self.queue_family(self.family_of(document), slug)


    def family_of(self, document: dict) -> list[str]:
        """The collections a collection links to that this run was asked to follow: its
        subcollections, its parent, or both - by short name."""

        found: list[str] = []
        if self.follow_subcollections:
            for url in document.get('subcollections') or []:
                slug = parse_text.get_collection_name(str(url or ''))
                if slug and slug not in found: found.append(slug)
        if self.follow_parents:
            slug = parse_text.get_collection_name(str(document.get('parent_collection') or ''))
            if slug and slug not in found: found.append(slug)
        return found


    def queue_family(self, slugs: list[str], via: str) -> None:
        """Queue relatives to be read once the collections asked for are done - each once,
        whether it has already been read, is waiting, or is linked from somewhere else too."""

        for slug in slugs:
            if slug in self.collections_seen or any(s == slug for s, _ in self.family_queue):
                continue
            self.family_queue.append((slug, via))


    def walk_family(self, records: list[dict]) -> None:
        """Read every queued relative, queueing theirs in turn, until there are none left.

        Ends because each collection is read at most once (`take_collection` remembers it,
        `queue_family` never queues one twice) and ao3 has only so many - and, should a
        family ever turn out enormous, `COLLECTION_FAMILY_LIMIT` stops it outright and says
        so, rather than letting one run wander the whole archive.
        """

        taken = 0
        while self.family_queue:
            self.check_cancelled()
            if taken >= strings.COLLECTION_FAMILY_LIMIT:
                print(strings.AO3_INFO_COLLECTION_FAMILY_LIMIT.format(
                    strings.COLLECTION_FAMILY_LIMIT, len(self.family_queue)))
                self.family_queue.clear()
                return
            slug, via = self.family_queue.pop(0)
            if slug in self.collections_seen: continue
            taken += 1
            print(strings.AO3_INFO_COLLECTION_FAMILY.format(slug, via))
            self.take_collection(slug, f'{strings.AO3_BASE_URL}/collections/{via}', records)


    def finished_before(self, slug: str) -> bool:
        """Whether the attempt being resumed finished this collection - in which case it is
        not read again, the works it found are downloaded from the index, and the relatives
        it saved are followed as though it had just been read."""

        before = self.collections_before.get(slug) or {}
        if not before.get('done'): return False
        print(strings.AO3_INFO_RESUME_COLLECTION_DONE.format(slug))
        self.keep_indexed([str(x) for x in before.get('works') or []])
        self.queue_family([str(x) for x in before.get('family') or []], slug)
        return True


    def collection_saved(self, slug: str, document: dict) -> None:
        """Tell the run a collection is finished - unless one of its listings failed partway,
        which a resumed run has to read again rather than skip."""

        if self.on_collection_done and slug not in self.unfinished_collections:
            series_works = [w for series_id in document.get('series_ids') or []
                            for w in self.series_read.get(str(series_id))
                            or self.series_ids_found.get(str(series_id)) or []]
            self.on_collection_done(slug, [str(x) for x in (document.get('work_ids') or []) +
                                           (document.get('bookmark_ids') or []) + series_works],
                                    self.family_of(document))


    def read_collection(self, slug: str, source: str, blurb=None) -> dict:
        """Everything one collection has to say, across its listing blurb and its pages.

        `blurb` is its entry in a collections listing, when the crawl came from one. There
        is none when a single collection is indexed by url, so the three things a blurb
        would have supplied - display title, description and flags - are read off the
        profile page instead, which carries all of them.
        """

        base = f'{strings.AO3_BASE_URL}/collections/{slug}'
        document = {'source': source, 'name': slug, 'link': base}
        if blurb is not None:
            document.update(parse_soup.get_collection_metadata(blurb))

        try:
            profile = self.repo.get_soup(f'{base}/profile')
            # only when there is no blurb: the listing is otherwise the established source
            # for these, and taking them from elsewhere would show up as a spurious change
            if blurb is None:
                document.update(parse_soup.get_collection_header(profile))
            document.update(parse_soup.get_collection_profile(profile))
        except exceptions.CancelledException:
            raise
        except Exception as e:
            self.log_error({'message': strings.ERROR_COLLECTION_PROFILE, 'link': base}, e)

        # what we already know about this collection, to avoid re-walking what has not moved
        previous = self.previous_collection(slug)

        indexing_works = self.collection_works is not None
        before = len(self.collection_works or [])
        externals_before = self.collection_externals
        for key, count_key, label, url in (
                ('work_ids', 'work_count', 'works', f'{base}/works'),
                ('bookmark_ids', 'bookmark_count', 'bookmarked items', f'{base}/bookmarks')):
            # an unchanged count says the work numbers are the same, not that the works are:
            # indexing them means reading the listing, so a run asked to never skips it
            kept = None if indexing_works else self.unchanged_items(
                previous, document, key, count_key)
            if kept is not None:
                document[key] = kept
                if key == 'bookmark_ids':
                    document['external_ids'] = [str(x) for x in previous.get('external_ids') or []]
                    document['series_ids'] = [str(x) for x in previous.get('series_ids') or []]
                print(strings.AO3_INFO_COLLECTION_UNCHANGED.format(slug, len(kept), label))
                continue
            earlier = ((self.collections_before.get(slug) or {}).get('listings') or {}).get(key)
            try:
                if earlier and earlier.get('done'):
                    document[key] = [str(x) for x in earlier.get('ids') or []]
                    externals = [str(x) for x in earlier.get('externals') or []]
                    series = [str(x) for x in earlier.get('series') or []]
                    if key == 'bookmark_ids':
                        document['external_ids'] = externals
                        document['series_ids'] = series
                    self.keep_indexed(document[key])
                    if self.on_collection_page:
                        self.on_collection_page(slug, key, None, document[key], done=True,
                                                externals=externals, series=series)
                    continue
                if earlier and int(earlier.get('page') or 1) > 1:
                    print(strings.AO3_INFO_RESUME_COLLECTION_PAGE.format(
                        slug, label, earlier['page']))
                ids = self.collect_work_ids(url, slug, key, earlier)
                externals = list(self.last_externals)
                series = list(self.last_series)
                resumed_from = int((earlier or {}).get('page') or 1)
                count = document.get(count_key)
                if key == 'work_ids' and resumed_from > 1 and isinstance(count, int) \
                        and len(ids) < count:
                    # fewer than the collection says it holds: works that moved to the front
                    # since the earlier attempt - updated ones, if the listing is ordered by
                    # date updated - sit on pages it had already read, so read those again
                    print(strings.AO3_INFO_RESUME_COLLECTION_SHORT.format(
                        slug, len(ids), count, resumed_from - 1))
                    ids = self.collect_work_ids(url, slug, key, {'ids': ids, 'page': 1},
                                                stop=resumed_from - 1)
                document[key] = ids
                if key == 'bookmark_ids':
                    document['external_ids'] = externals
                    document['series_ids'] = series
                if self.on_collection_page:
                    self.on_collection_page(slug, key, None, ids, done=True, externals=externals,
                                            series=series)
            except exceptions.CancelledException:
                raise
            except Exception as e:
                document[key] = []
                if key == 'bookmark_ids':
                    document['external_ids'] = []
                    # a failed listing keeps the series it had, so their works are not
                    # dropped from the file for want of a page
                    document['series_ids'] = [str(x) for x in previous.get('series_ids') or []]
                # saved with what it has, as ever - but not finished, so a resumed run reads it
                self.unfinished_collections.add(slug)
                read = self.listing_read or {}
                last = read.get('lastPage')
                gap = {
                    'kind': 'collection', 'collection': slug, 'listing': url,
                    'items': 'bookmarked items' if key == 'bookmark_ids' else 'works',
                    'firstPage': read.get('firstPage') or 1, 'lastPage': last,
                    'failedPage': (last or (read.get('firstPage') or 1) - 1) + 1,
                    'works': read.get('works') or 0, 'error': str(e), **failure_reason(e),
                }
                self.index_failures.append(gap)
                print(describe_listing_gap(gap))
                self.log_error({'message': strings.ERROR_COLLECTION_ITEMS, 'link': url}, e)

        # the works in each series are recorded in the series' own entry, not here - a
        # collection names the series, as it names works, and the index describes them
        series_works = self.collection_series(slug, document.get('series_ids') or [])

        if indexing_works:
            print(strings.AO3_INFO_COLLECTION_WORKS.format(
                slug, len(self.collection_works or []) - before))
            if self.collection_externals > externals_before:
                print(strings.AO3_INFO_COLLECTION_EXTERNALS.format(
                    slug, self.collection_externals - externals_before))

        # only worth asking for when the sidebar says there are some
        document['subcollections'] = []
        if document.get('subcollection_count'):
            kept = self.unchanged_items(previous, document, 'subcollections',
                                        'subcollection_count')
            if kept is not None:
                document['subcollections'] = kept
                print(strings.AO3_INFO_COLLECTION_UNCHANGED.format(
                    slug, len(kept), 'subcollections'))
            else:
                try:
                    document['subcollections'] = self.collect_collection_links(
                        document.get('subcollections_link') or f'{base}/collections')
                except exceptions.CancelledException:
                    raise
                except Exception as e:
                    self.log_error({'message': strings.ERROR_COLLECTION_ITEMS, 'link': base}, e)

        return document


    def collection_series(self, slug: str, series_ids: list[str]) -> dict[str, list[str]]:
        """Read every series bookmarked among a collection's items, and write its entry in
        `indexing/series/` with the works in it - the collection itself records only the
        series' number, as it does a work's.

        The entry follows the rules for any series not bookmarked by you: one that exists
        keeps what it says about your own bookmark of it; a new one is **not bookmarked**.
        Somebody else's bookmark of it - the collection's blurb, with their notes and tags - is
        never what the entry is written from; the series' own page is.

        When the run indexes the collection's works, the series' works are indexed too
        (`index_series`, the series walk's own: a new entry is not bookmarked) and downloaded
        with the rest; otherwise only the series' entry is written. A request per 20 works,
        once per run however many collections hold the series; one that will not read keeps
        the works its entry had. Returns the works of each series read.
        """

        found: dict[str, list[str]] = {}
        if series_ids:
            print(strings.AO3_INFO_COLLECTION_SERIES.format(slug, len(series_ids)))
        for series_id in series_ids:
            series_id = str(series_id)
            self.check_cancelled()
            works = self.series_read.get(series_id)
            if works is None: works = self.series_ids_found.get(series_id)
            if works is None: works = self.series_unchanged(series_id)
            if works is None and self.collection_works is not None:
                for document in self.index_series({'id': series_id, 'title': '', 'bookmark': None}):
                    if document.get('id'): self.indexed_this_run[str(document['id'])] = document
                    self.keep_collection_work(document)
                works = self.series_read.get(series_id)
            elif works is None:
                works = self.read_series(series_id)
            if works is None: continue
            # works indexed before this run, off a listing, are downloaded with the rest
            self.keep_indexed([w for w in works if w not in self.indexed_this_run])
            found[series_id] = list(works)
        return found


    def series_unchanged(self, series_id: str) -> list[str] | None:
        """The works a series' entry already lists, when the collection's blurb for it says it
        holds exactly that many - so a series a scan of your bookmarks (or an earlier run) has
        read is not read again. None when it has to be read: no entry, no count, a count that
        differs, or - when the run indexes the works - any of them not yet in the index."""

        count = self.series_counts.get(series_id)
        if not count: return None
        listed = [str(x) for x in self.series_existing(series_id).get(strings.SERIES_WORKS_FIELD) or []]
        if len(listed) != count: return None
        if self.collection_works is not None:
            indexed = {str(r.get('id')) for r in (self.records_for(listed) if self.records_for else [])}
            if not set(listed) <= indexed: return None
        print(strings.AO3_INFO_COLLECTION_SERIES_UNCHANGED.format(series_id, count))
        self.series_ids_found[series_id] = listed
        return listed


    def read_series(self, series_id: str) -> list[str] | None:
        """Read a series' pages for the works in it, without indexing any of them, and write
        the series' entry - or leave the entry as it was, and answer None, when it will not
        read."""

        link = f'{strings.AO3_BASE_URL}/series/{series_id}'
        print(strings.AO3_INFO_SERIES_READING.format(series_id))
        found: list[str] = []
        header: dict | None = None
        page = link
        try:
            total = None
            while True:
                self.check_cancelled()
                soup = self.fetch_page(page)
                if header is None: header = parse_soup.get_series_page_metadata(soup, series_id)
                if total is None: total = parse_soup.get_total_pages(soup)
                for blurb in parse_soup.get_blurbs(soup):
                    kind, work = parse_soup.get_blurb_kind(blurb)
                    if kind == parse_soup.BLURB_WORK and work and work not in found:
                        found.append(work)
                if not total or parse_text.get_page_number(page) >= total: break
                page = parse_text.get_next_page(page)
        except exceptions.CancelledException:
            raise
        except Exception as e:
            print(strings.ERROR_SERIES)
            self.log_error({'message': strings.ERROR_SERIES, 'link': link}, e)
            return None
        self.series_ids_found[series_id] = found
        self.save_series_entry(self.series_document(series_id, None, header, found))
        return found


    def previous_collection(self, name: str) -> dict:
        """The newest reading of this collection from an earlier run, or nothing.

        A missing or unreadable file is not a problem: it only means there is nothing to
        reuse, and everything gets fetched as it would on a first run.
        """

        try:
            stored = self.fileops.load_json(self.collection_path(name))
        except Exception:
            return {}
        if not isinstance(stored, dict): return {}

        readings = stored.get(indexing.INDEXES)
        if isinstance(readings, list) and readings and isinstance(readings[-1], dict):
            # identity lives at the root and is not versioned, so it goes back on top
            return {**readings[-1], **stored}
        return stored


    def unchanged_items(self, previous: dict, document: dict,
                        key: str, count_key: str) -> list | None:
        """The ids saved last time, when the count says a crawl would find the same ones.

        Walking a collection's works costs one request per twenty of them, so a large
        collection runs to hundreds of requests - by far the most expensive thing this
        does. Ao3 puts the total on the profile page we have already fetched, so an
        unchanged total is enough to keep what we have.

        Returns None whenever anything is uncertain, which means fetch it properly: no
        saved list, an empty one, or a count missing from either side.

        A partly-gathered list is never saved, so it cannot be reused: a stop raises out
        of read_collection before anything is written, and a failed crawl stores an empty
        list, which is rejected here. The length of the list is deliberately not compared
        against the count - a listing can hold bookmarks of series and external works,
        which have no work number and so are counted by ao3 but not recorded here.

        The one thing this cannot see is a collection that had a work added and another
        removed between runs, leaving the total the same. Delete its json file to force a
        full crawl.
        """

        saved = previous.get(key)
        if not isinstance(saved, list) or not saved: return None

        count = document.get(count_key)
        if count is None or count != previous.get(count_key): return None

        return list(saved)


    def collection_path(self, name: str) -> str:
        """Where one collection's file lives, named the same way everything else is."""

        maximum = self.fileops.get_ini_value_integer(
            strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        filename = parse_text.get_valid_filename([name], maximum) or name
        return os.path.join(
            strings.COLLECTIONS_FOLDER_NAME,
            filename + parse_text.get_file_type(strings.AO3_DOWNLOAD_TYPE_METADATA))


    def save_collection(self, document: dict) -> None:
        """Write one collection to its own json file, keeping its history."""

        try:
            path = self.collection_path(document.get('name') or 'collection')
            merged = indexing.merge(self.fileops.load_json(path), document, self.indexed_on,
                                    indexing.COLLECTION_IDENTITY_FIELDS)
            self.fileops.save_json(path, merged)
        except Exception as e:
            self.log_error({'message': strings.ERROR_COLLECTION_SAVE,
                            'link': document.get('link')}, e)


    def metadata_path(self, document: dict, subfolder: str = '') -> str:
        """Where one entry's json lives: named with the same pattern as a downloaded work,
        so a fic's metadata carries the same name as its epub or html, in indexing/ - or in
        a folder inside it, for the entries that are not works."""

        pattern = strings.FILE_NAME_PATTERN
        maximum = self.fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        name = parse_soup.apply_name_pattern(parse_soup.get_name_metadata_from_blurb(document), pattern)
        filename = parse_text.get_valid_filename(name, maximum)
        # a pattern can resolve to nothing if every field it uses is empty
        if not filename: filename = str(document.get('id') or 'bookmark')
        return os.path.join(
            strings.INDEXING_FOLDER_NAME, *([subfolder] if subfolder else []),
            filename + parse_text.get_file_type(strings.AO3_DOWNLOAD_TYPE_METADATA))


    def note_unrevealed(self, blurb, worknum) -> None:
        """Hold back a work in a collection that has not been revealed yet, and say why.

        It indexes fine - it has a number and a place in the listing - but ao3 will not serve
        its file until the collection is revealed, so asking would fail by definition.
        """

        if not parse_soup.is_unrevealed_blurb(blurb) or str(worknum) in self.unrevealed: return
        self.unrevealed.add(str(worknum))
        self.skipped_works.append(
            {'id': str(worknum),
             'link': parse_soup.get_full_work_url('/works/' + str(worknum)) or '',
             'title': parse_soup.get_text_or_empty(blurb, 'h4.heading'),
             'error': strings.SKIPPED_UNREVEALED})


    def save_metadata(self, document: dict, path: str | None = None,
                      from_mirror: bool = False) -> None:
        """Write one work to its own json file, in the indexing subfolder.

        Into the file its entry already has, found by the work number its name starts with
        (`entry_path`) - never by the name it would be given from today's title and author,
        which a retitled work or a renamed author would not match, leaving a second file for
        the same work beside the first.
        """

        # a reading made from FicHub says so (`from_mirror`); every other one is ao3's own,
        # and a record carried forward from a FicHub reading must not pass the mark on
        if not from_mirror and strings.RETRIEVED_FROM_FIELD in document:
            document = {k: v for k, v in document.items() if k != strings.RETRIEVED_FROM_FIELD}
        try:
            path = path or self.entry_path(document)
            existing = self.fileops.load_json(path)
            document = keep_own_bookmark(document, existing) if from_mirror \
                else carry_bookmark_details(document, existing)
            # keep whatever readings the file already holds, and add this one only if it
            # says something new
            merged = indexing.merge(existing, document, self.indexed_on, run_id=self.run_id)
            self.fileops.save_json(path, merged)
            self.remember_entry(path)
            if document.get('id'): self.reindexed.add(str(document['id']))
        except Exception as e:
            # one unwritable file shouldn't end the run
            self.log_error({'message': strings.ERROR_METADATA_SAVE, 'link': document.get('link')}, e)


    def save_entry(self, document: dict, subfolder: str, path: str | None = None) -> None:
        """Write a bookmark that is not a work - a series, an external work - to its folder
        inside indexing/, keeping its history the way a work's file does."""

        try:
            path = path or self.entry_path(document, subfolder)
            existing = self.fileops.load_json(path)
            merged = indexing.merge(existing, carry_bookmark_details(document, existing),
                                    self.indexed_on, run_id=self.run_id)
            self.fileops.save_json(path, merged)
            self.remember_entry(path)
            if subfolder == strings.EXTERNAL_INDEX_FOLDER_NAME and document.get('id'):
                self.externals_saved.add(str(document['id']))
        except Exception as e:
            self.log_error({'message': strings.ERROR_METADATA_SAVE, 'link': document.get('link')}, e)


    # region series marked for walkthrough

    def mark_series(self, series_id, title: str = '', bookmark: dict | None = None) -> None:
        """Mark a series to be walked for its works once indexing is over.

        A series you bookmarked is always marked. A series one of your works belongs to is
        marked too when the run was asked to (`series`) - see `mark_series_of`. Each is
        marked once, and said so once; a series marked again because it turned out to be
        bookmarked as well keeps that bookmark. Nothing is marked while series are being
        walked, since that would only mark the series in hand.
        """

        if self.walking_series or not series_id: return
        series_id = str(series_id)
        marked = self.series_marked.get(series_id)
        if marked is None:
            said = (strings.AO3_INFO_SERIES_MARKED_BOOKMARK if bookmark
                    else strings.AO3_INFO_SERIES_MARKED)
            print(said.format(title or series_id))
            self.series_marked[series_id] = {'id': series_id, 'title': title or '',
                                             'bookmark': bookmark}
        elif bookmark is not None and marked['bookmark'] is None:
            marked['bookmark'] = bookmark


    def mark_series_of(self, record: dict) -> None:
        """Mark every series a work is part of, when the run was asked to.

        Goes by what the record says, so it works as well for a work read off a listing a
        moment ago as for one taken from the index without being read again.
        """

        if not self.series: return
        for member in record.get(strings.SERIES_MEMBERSHIP_FIELD) or []:
            if isinstance(member, dict): self.mark_series(member.get('id'), member.get('title'))


    def walk_marked_series(self) -> list[dict]:
        """Walk every series marked this run, and return the works it indexed.

        What indexing a bookmarked series used to do inline, done here once indexing is
        over - so every work a listing holds has been read from the listing first, and is
        not read again from a series (see `index_series`).
        """

        self.walking_series = True
        indexed: list[dict] = []
        try:
            for marked in list(self.series_marked.values()):
                self.check_cancelled()
                if marked['id'] in self.series_read: continue
                works = self.index_series(marked)
                indexed.extend(works)
                if self.on_series:
                    self.on_series(marked['id'], [str(w['id']) for w in works if w.get('id')])
        except exceptions.CancelledException:
            # what was indexed stays indexed; the run notices the stop and ends
            print(strings.INFO_CANCELLED)
        finally:
            self.walking_series = False
        return indexed


    def index_series(self, marked: dict) -> list[dict]:
        """Walk one series' ao3 page and index every work in it; then write its entry.

        The page lists its works with the same blurbs a bookmarks listing uses, 20 to a page,
        so a series costs a request per 20 works. For each work on it:

        - **already indexed this run** - read off the listing, or from another series - it
          is left alone. It is not read twice.
        - **otherwise** it is indexed from the series page (`save_series_work`): an entry
          that exists keeps what it says about your own bookmark of it; a new one is
          recorded as not bookmarked.

        Returns the works it indexed, so they are downloaded with the rest of the run.
        """

        series_id = str(marked['id'])
        bookmark = marked.get('bookmark')
        link = f'{strings.AO3_BASE_URL}/series/{series_id}'
        print(strings.AO3_INFO_SERIES_READING.format(
            (bookmark or {}).get('title') or marked.get('title') or series_id))

        found: list[str] = []
        indexed: list[dict] = []
        already = 0
        header: dict | None = None
        walked = False
        page = link
        try:
            total = None
            while True:
                self.check_cancelled()
                soup = self.fetch_page(page)
                if header is None: header = parse_soup.get_series_page_metadata(soup, series_id)
                if total is None: total = parse_soup.get_total_pages(soup)
                readings = []
                for blurb in parse_soup.get_blurbs(soup):
                    kind, work = parse_soup.get_blurb_kind(blurb)
                    if kind != parse_soup.BLURB_WORK or not work or work in found: continue
                    found.append(work)
                    if work in self.reindexed:
                        already += 1
                        continue
                    readings.append(parse_soup.get_blurb_metadata(blurb))
                # a page at a time, as a listing is written
                for document in readings:
                    indexed.append(self.save_series_work(document, series_id, link))
                if not total or parse_text.get_page_number(page) >= total: break
                page = parse_text.get_next_page(page)
            walked = True
            self.series_read[series_id] = found
            print(strings.AO3_INFO_SERIES_READ.format(len(found), len(indexed), already))
        except exceptions.CancelledException:
            raise
        except Exception as e:
            # a series that will not read keeps the works list it had, rather than being
            # recorded as holding only the ones reached before it failed
            print(strings.ERROR_SERIES)
            self.log_error({'message': strings.ERROR_SERIES, 'link': link}, e)

        self.save_series_entry(self.series_document(series_id, bookmark, header,
                                                    found if walked else None))
        return indexed


    def series_document(self, series_id: str, bookmark: dict | None, header: dict | None,
                        works: list[str] | None) -> dict:
        """A series' entry: its own bookmark's reading when it is one of yours, otherwise
        what its page says, keeping whatever its existing entry already knows.

        A series marked only because a work of yours is in it is recorded as **not
        bookmarked** - unless its entry says you bookmarked it, which a run that did not
        reach that bookmark cannot contradict.

        **An entry you bookmarked keeps its reading as it is**, and only its works are brought
        up to date. The page describes a series differently from a bookmark blurb - no tags,
        its own date format - so writing the page over your bookmark's reading would blank
        your tags and add a reading that the next scan of your bookmarks undoes again. That
        scan is what brings a bookmarked series' own details up to date. And nothing the page
        leaves blank overwrites what the entry has.
        """

        if bookmark:
            document = dict(bookmark)
        else:
            existing = self.series_existing(series_id)
            document = {key: value for key, value in existing.items()
                        if key not in (indexing.INDEXES, indexing.LAST_INDEXED,
                                       indexing.INDEXED_ON)}
            if existing.get(strings.BOOKMARKED_FIELD) is not True:
                document.update({k: v for k, v in (header or {}).items()
                                 if v not in (None, '', []) and (not blank(v) or k not in document)})
            document.setdefault('id', series_id)
            document.setdefault('link', f'{strings.AO3_BASE_URL}/series/{series_id}')
            document.setdefault(strings.BOOKMARKED_FIELD, False)
            document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_SERIES
        if works is not None: document[strings.SERIES_WORKS_FIELD] = works
        return document


    def series_path(self, document: dict) -> str:
        """Where a series' entry lives - found by its id when it is already there, so a
        series renamed on ao3 keeps its one file rather than starting a second."""

        return self.entry_path(document, strings.SERIES_INDEX_FOLDER_NAME)


    def series_existing(self, series_id: str) -> dict:
        return indexing.flatten(self.fileops.load_json(self.series_path({'id': series_id}))) or {}


    def save_series_entry(self, document: dict) -> None:
        """Write a series' entry, keeping the works list it had when this reading has none -
        a bookmark read off the listing says nothing about the series' works."""

        try:
            path = self.series_path(document)
            existing = self.fileops.load_json(path)
            current = indexing.flatten(existing) or {}
            if strings.SERIES_WORKS_FIELD not in document and strings.SERIES_WORKS_FIELD in current:
                document = {**document, strings.SERIES_WORKS_FIELD: current[strings.SERIES_WORKS_FIELD]}
            merged = indexing.merge(existing, document, self.indexed_on)
            self.fileops.save_json(path, merged)
            self.remember_entry(path)
        except Exception as e:
            self.log_error({'message': strings.ERROR_METADATA_SAVE, 'link': document.get('link')}, e)


    def save_series_work(self, document: dict, series_id: str, series_link: str) -> dict:
        """Index one work read off a bookmarked series' page.

        A series page knows the work but nothing about your own bookmark of it, so an
        entry that already exists keeps its bookmark fields as they were - whether you
        bookmarked it, when, your notes and tags - and its source. A new one is recorded as
        **not bookmarked**: it is in the index because of the series. If the same run then
        meets it in your bookmarks listing, that reading says bookmarked, as any does.
        """

        path = self.entry_path(document)
        existing = indexing.flatten(self.fileops.load_json(path)) or {}
        for field in strings.BOOKMARK_OWN_FIELDS:
            if field in existing: document[field] = existing[field]
        document.setdefault(strings.BOOKMARKED_FIELD, False)
        document['source'] = existing.get('source') or series_link
        document[strings.BOOKMARK_TYPE_FIELD] = strings.BOOKMARK_TYPE_WORK
        document[indexing.FROM_SERIES] = [series_id]
        self.save_metadata(document, path)
        return document

    # endregion


    def add_work_dates(self, records: list[dict]) -> None:
        """Fill in date_created, and refine date_updated, by loading each work page.

        Listing pages show a single date and no publication date at all, so this is the
        only way to get both. It costs one request per work, hence the separate prompt.
        """

        print(strings.AO3_INFO_METADATA_WORK_DATES.format(str(len(records))))

        for index, record in enumerate(records, start=1):
            work_link = record.get('link')
            if not work_link: continue
            try:
                self.check_cancelled()
                thesoup = self.proceed(self.repo.get_soup(work_link))
                record['date_created'] = parse_soup.get_text_or_empty(thesoup, 'dd.published')
                # single chapter works have no status line; keep the listing date in that case
                updated = parse_soup.get_text_or_empty(thesoup, 'dd.status')
                if updated: record['date_updated'] = updated
                # the file was written during the crawl, so rewrite it with the dates in
                self.save_metadata(record)
            except exceptions.CancelledException:
                print(strings.INFO_CANCELLED)
                break
            except KeyboardInterrupt:
                print(strings.INFO_LINKS_LIST_CANCELED)
                break
            except Exception as e:
                self.log_error({'message': strings.ERROR_METADATA_WORK_DATES, 'link': work_link}, e)
            progress.report(self.progress, progress.WORK, done=index, total=len(records),
                            title=record.get('title', ''))
            if index % 10 == 0 or index == len(records):
                print(strings.AO3_INFO_METADATA_PROGRESS.format(str(index), str(len(records))))


    def get_work_links(self, link: str, metadata: bool) -> dict[str, dict]:
        
        links_list = {}
        visited_series = []

        try:
            self.get_work_links_recursive(links_list, link, visited_series, metadata)
        except Exception as e:
            print(strings.ERROR_LINKS_LIST)
            self.log_error({'message': strings.ERROR_LINKS_LIST}, e)
        except KeyboardInterrupt:
            print(strings.INFO_LINKS_LIST_CANCELED)

        return links_list


    def get_work_links_recursive(
            self, 
            links_list: dict[str, dict | None], 
            link: str, 
            visited_series: list[str], 
            metadata: bool, 
            soup: BeautifulSoup | None = None) -> None:

        if parse_text.is_work(link):
            if link not in links_list:
                if metadata and soup:
                    work_metadata = parse_soup.get_work_metadata_from_list(soup, link)
                    links_list[link] = work_metadata
                else:
                    links_list[link] = None
        elif parse_text.is_series(link):
            if link not in visited_series:
                visited_series.append(link)
                total_pages = None
                while True:
                    series_soup = self.repo.get_soup(link)
                    series_soup = self.proceed(series_soup)
                    if total_pages is None:
                        total_pages = parse_soup.get_total_pages(series_soup)
                    work_urls = parse_soup.get_work_urls(series_soup)
                    for work_url in work_urls:
                        self.get_work_links_recursive(links_list, work_url, visited_series, metadata, series_soup)
                    pagenum = parse_text.get_page_number(link)
                    if not total_pages or pagenum >= total_pages:
                        break
                    link = parse_text.get_next_page(link)
        elif strings.AO3_BASE_URL in link:
            # special case for subscriptions page - it doesn't have blurbs, so any series
            # links encountered are directly subscribed to and should always be downloaded.
            include_series = parse_text.is_subscriptions(link)
            total_pages = None
            while True:
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(thesoup)
                urls = parse_soup.get_work_and_series_urls(thesoup, include_series)
                self.note_listing_dates(thesoup)
                for url in urls:
                    self.get_work_links_recursive(links_list, url, visited_series, metadata, thesoup)
                pagenum = parse_text.get_page_number(link)
                if not total_pages or pagenum >= total_pages:
                    break
                link = parse_text.get_next_page(link)
                pagenum = parse_text.get_page_number(link)
                if self.pages and pagenum == self.pages + 1:
                    if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                    break
                print(strings.INFO_FINISHED_PAGE.format(str(pagenum - 1), str(pagenum), str(total_pages)))
        else:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)


    def download_recursive(self, link: str, log: dict, visited: list[str]) -> None:

        self.check_cancelled()

        if link in visited:
            # every format of it is on disk - but a copy behind the listing's date (or a run
            # that overwrites) still wants it, once
            if not (self.existing_copies is not None and link not in self.reopened
                    and parse_text.is_work(link) and self.listing_says_behind(link)):
                return
            self.reopened.add(link)
        else:
            visited.append(link)

        if parse_text.is_work(link):
            log = {}
            self.download_work(link, log, None)
        elif parse_text.is_series(link):
            log = {}
            self.download_series(link, log, visited)        
        elif strings.AO3_BASE_URL in link:
            # special case for subscriptions page - it doesn't have blurbs, so any series
            # links encountered are directly subscribed to and should always be downloaded.
            include_series = parse_text.is_subscriptions(link)
            total_pages = None
            while True:
                self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                thesoup = self.repo.get_soup(link)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(thesoup)
                urls = parse_soup.get_work_and_series_urls(thesoup, include_series)
                self.note_listing_dates(thesoup)
                for url in urls:
                    self.download_recursive(url, log, visited)
                if not self.mark:
                    pagenum = parse_text.get_page_number(link)
                    if not total_pages or pagenum >= total_pages:
                        break
                    link = parse_text.get_next_page(link)
                    pagenum = parse_text.get_page_number(link)
                    if self.pages and pagenum == self.pages + 1:
                        if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_PAGE_LIMIT_REACHED, 'level': 'debug'})
                        break
                    print(strings.INFO_FINISHED_PAGE.format(str(pagenum - 1), str(pagenum), str(total_pages)))
                    done, of = self.page_progress(pagenum - 1, total_pages)
                    progress.report(self.progress, progress.PAGE, page=done, total=of,
                                    listingPage=pagenum - 1, listingTotal=total_pages)
                else:
                    total_pages = parse_soup.get_total_pages(thesoup)
                    if not total_pages or total_pages <= 1:
                        break
        else:
            raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)


    def download_series(self, link: str, log: dict, visited: list[str]) -> None:
        """"Download all works in a series"""

        try:
            total_pages = None
            while True:
                series_soup = self.repo.get_soup(link)
                series_soup = self.proceed(series_soup)
                if total_pages is None:
                    total_pages = parse_soup.get_total_pages(series_soup)
                work_urls = parse_soup.get_work_urls(series_soup)
                if self.debug: self.fileops.write_log({'link': link, 'message': strings.INFO_STARTING_PAGE, 'level': 'debug'})
                for work_url in work_urls:
                    self.download_recursive(work_url, log, visited)
                pagenum = parse_text.get_page_number(link)
                if not total_pages or pagenum >= total_pages:
                    break
                link = parse_text.get_next_page(link)
        except exceptions.CancelledException:
            raise # let a stop unwind rather than being logged as a series failure
        except Exception as e:
            log['link'] = link
            self.log_error(log, e)


    def note_listing_dates(self, soup) -> None:
        """Remember the date each work on a listing page says it was last updated, by
        number - what decides whether a work already on disk in every format is behind."""

        if self.existing_copies is None: return
        for blurb in parse_soup.get_blurbs(soup):
            kind, number = parse_soup.get_blurb_kind(blurb)
            if kind != parse_soup.BLURB_WORK or not number: continue
            stamp = parse_text.get_date_stamp(parse_soup.get_text_or_empty(
                blurb, SORT_DATE_SELECTORS['updated']))
            if stamp: self.listing_dates[str(number)] = stamp

    def listing_says_behind(self, link: str) -> bool:
        """Whether a work with every format on disk should be opened anyway: the run
        overwrites, or the listing dates it later than one of its copies. An undated copy
        cannot be judged, so it never counts as behind."""

        if self.existing_copies is None: return False
        number = parse_text.get_work_number(link) or ''
        copies = self.existing_copies.get(number) or {}
        if self.overwriting: return bool(copies)
        stamp = self.listing_dates.get(number)
        return bool(stamp) and any(
            (copies.get(x.upper()) or {}).get('date') and copies[x.upper()]['date'] < stamp
            for x in self.filetypes if x.upper() in copies)

    def page_verdict(self, work_url: str, number: str, filetype: str, stamp: str) -> bool:
        """Whether to fetch this format, judged against the date the work's own page gives
        (`stamp`) - the same rule as everywhere: no copy, or a copy dated before it, is
        fetched; a current one is kept; an undated one cannot be judged and is left alone;
        an overwriting run fetches every one. An older copy is named in `superseded`, so
        the new file replaces it. Says which, per format. Without a folder scan to go by
        (`existing_copies`), every format is fetched, as it always was."""

        if self.existing_copies is None: return True
        copy = (self.existing_copies.get(number) or {}).get(filetype.upper())
        if not copy:
            print(strings.AO3_INFO_FORMAT_MISSING.format(filetype))
            return True
        date = copy.get('date')
        # only a date in the app's own form, no later than the page's, is replaced unasked
        if not date or (self.overwriting and stamp and date > stamp):
            if self.judge_copy is not None:
                return bool(self.judge_copy(work_url, number, filetype, stamp, copy))
            print(strings.AO3_INFO_FORMAT_UNDATED.format(filetype) if not date
                  else strings.AO3_INFO_KEEPING_NEWER.format(filetype))
            return False
        if self.overwriting:
            print(strings.AO3_INFO_FORMAT_REPLACING.format(filetype))
        elif stamp and date < stamp:
            print(strings.AO3_INFO_FORMAT_OUTDATED.format(filetype))
        else:
            print(strings.AO3_INFO_FORMAT_CURRENT.format(filetype))
            return False
        if copy.get('path'): self.superseded.setdefault(work_url, {})[filetype] = copy['path']
        return True

    def download_work(self, link: str, log: dict, chapters: str | None) -> None:
        """Download a single work"""

        try:
            log['link'] = link
            downloaded = self.try_download(link, log, chapters)
            if downloaded == False: return
        except exceptions.CancelledException:
            raise # a stop is not a failed download, and must not be logged as one
        except Exception as e:
            self.check_session()
            self.record_failure(link, e)
            self.log_error(log, e)
        else:
            log['success'] = True
            self.fileops.write_log(log)
            progress.report(self.progress, progress.WORK, title=log.get('title', ''), link=link)


    def try_download(self, work_url: str, log: dict, chapters: str | None) -> bool:
        """Main download logic"""

        thesoup = self.repo.get_soup(work_url)
        thesoup = self.proceed(thesoup)

        if chapters is not None: # TODO this is a super awkward place for this logic to be and I don't like it.
            currentchapters = parse_soup.get_current_chapters(thesoup)
            if int(currentchapters) <= int(chapters):
                return False
        
        maximum = self.fileops.get_ini_value_integer(strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        title = parse_soup.get_title(thesoup, work_url, strings.FILE_NAME_PATTERN)
        metadata = parse_soup.get_work_metadata_from_work(thesoup, work_url)
        # the name carries the date the work was last updated, so a file says which version
        # of a fic it holds. the title and author are cut short to leave room for it rather
        # than the other way round.
        updated = parse_soup.get_updated_date(thesoup)
        filename = naming.file_stem(metadata, parse_text.get_date_stamp(updated), maximum)
        log['title'] = title
        # recorded so the same name can be rebuilt when checking what is already downloaded
        log['updated'] = updated
        log['workskin'] = parse_soup.has_custom_skin(thesoup)

        # what is being fetched right now, so the ui can name the fic and the format
        display = ' / '.join(x for x in title if x)
        progress.report(self.progress, progress.WORK, title=display, link=work_url,
                        phase='downloading')

        failed: list[tuple[str, Exception]] = []
        number = parse_text.get_work_number(work_url) or ''
        stamp = parse_text.get_date_stamp(updated)
        for filetype in self.filetypes:
            self.check_cancelled()
            if self.format_done(number, filetype):
                print(strings.AO3_INFO_FORMAT_DONE_EARLIER.format(filetype, number))
                continue
            if not self.page_verdict(work_url, number, filetype, stamp): continue
            progress.report(self.progress, progress.WORK, title=display, link=work_url,
                            filetype=filetype, phase='downloading')
            with self.one_format(filetype, failed):
                link = parse_soup.get_download_link(thesoup, filetype)
                response = self.repo.get_book(link)
                self.save_download(work_url, filetype,
                                   filename + parse_text.get_file_type(filetype), response)

        if self.images:
            self.save_images(thesoup, filename, work_url, title)

        if self.mark:
            self.repo.mark_work_as_read(thesoup, work_url)

        self.raise_if_formats_failed(failed)

        return True


    def save_download(self, work_url: str, filetype: str, name: str, content: bytes) -> str:
        """Write one downloaded format, tidy up what it replaced, and say which happened.

        Both download paths come through here, so every file a run writes gets exactly one
        line in the modal. Only a deleted older copy used to be announced - a format arriving
        for the first time, or a copy overwritten under the same name, said nothing, and a
        run downloading hundreds of new files looked as though it was doing nothing at all.
        """

        # into works/, never the top level - that is the only place anything looks for them
        name = os.path.join(strings.WORKS_FOLDER_NAME, name)
        try:
            existed = self.fileops.is_file(os.path.join(self.fileops.downloadfolder, name))
        except Exception:
            # only decides the wording. a folder that cannot be asked is not a failed download
            existed = False

        # a file already there under this name is never written over directly: if the write went
        # wrong partway, that copy would be gone with nothing whole in its place (`swap_in`)
        saved = self.swap_in(name, content) if existed is True else self.fileops.save_bytes(name, content)
        if isinstance(saved, str): self.written.append(saved)
        new = os.path.basename(saved) if isinstance(saved, str) else name
        work = parse_text.get_work_number(work_url)
        old = self.superseded.get(work_url, {}).get(filetype)
        try:
            # a separate older file, as opposed to the one this write has just landed on top of
            separate = bool(old) and not self.fileops.same_file(old, saved)
        except Exception:
            separate = False
        old_name = os.path.basename(old) if separate else ''

        # the new file is checked before anything else happens, and for every download - a
        # first download can be cut short or snatched by a sync tool as easily as a
        # replacement can, and a short file named as current would be judged current forever
        try:
            intact = self.fileops.saved_intact(saved, len(content))
        except Exception as e:
            # cannot tell either way: leave everything where it is, and say so
            self.log_error({'message': strings.ERROR_REPLACE_OLD_COPY, 'link': work_url}, e)
            print(strings.INFO_UNCONFIRMED.format(new))
            self.note_kept(work, work_url, new, old_name,
                           strings.UNCONFIRMED_REASON.format(new, e))
            return saved

        if not intact:
            self.discard_damaged(work_url, saved, new, old_name, len(content))

        outcome, _, reason = self.replace_superseded(work_url, filetype, saved, len(content))

        if outcome == REPLACED:
            print(strings.INFO_REPLACED_OLD_COPY.format(new))
        elif outcome == KEPT:
            print(strings.INFO_KEPT_OLD_COPY.format(new))
            self.note_kept(work, work_url, new, old_name, reason)
        elif outcome == UNCONFIRMED:
            print(strings.INFO_UNCONFIRMED.format(new))
            self.note_kept(work, work_url, new, old_name, reason)
        elif existed:
            # same name, so the write itself was the replacement - which is still an update
            if work: self.updated.add(work)
            print(strings.INFO_REPLACED_OLD_COPY.format(new))
        else:
            print(strings.INFO_SAVED_NEW_COPY.format(new))
        # whole, checked and in place: a retry that carries on from this run passes it over
        if work: self.saved_formats.setdefault(str(work), set()).add(filetype.upper())
        return saved


    def swap_in(self, name: str, content: bytes) -> str:
        """Put a download in place of the file already at `name`, never losing that file.

        Written beside it first (`SWAP_NEW_SUFFIX`) and checked whole; only then is the old copy
        moved aside (`SWAP_OLD_SUFFIX`), the new one moved into its name, and the old one
        deleted. Each step is a whole operation, so at every moment one whole copy exists under
        some name: a write that goes wrong is deleted with the old copy untouched, and a move
        that fails puts the old copy back. Raises `SavedFileException` (a failure for the work,
        the copy kept) when the new file cannot be put in place. An aside left by a step that
        could not be undone is a name nothing reads as a work: an old copy left aside by an earlier
        swap is put back before this one starts (the copy in its name may not be whole), and
        Resolve issues puts any others right.
        """

        target = os.path.join(self.fileops.downloadfolder, name)
        shown = os.path.basename(name)
        aside = target + strings.SWAP_OLD_SUFFIX
        # an earlier swap left your copy aside: it is put back first, whatever is in its name now
        if self.fileops.exists(aside) is True:
            if not (self.fileops.delete_file(target) is True and self.fileops.rename_file(aside, target) is True):
                print(strings.INFO_SWAP_FAILED.format(shown))
                raise exceptions.SavedFileException(strings.SWAP_FAILED_REASON.format(shown, shown))
            print(strings.INFO_SWAP_RESTORED.format(shown))
        fresh = self.fileops.save_bytes(name + strings.SWAP_NEW_SUFFIX, content)
        try:
            intact = self.fileops.saved_intact(fresh, len(content)) is True
        except Exception:
            intact = False
        if not intact:
            problem = self.fileops.saved_problem(fresh, len(content))
            self.fileops.delete_file(fresh)
            print(strings.INFO_DAMAGED_KEPT_OLD.format(shown))
            raise exceptions.SavedFileException(
                strings.DAMAGED_REASON_KEPT_OLD.format(shown, problem, shown))

        moved_aside = self.fileops.rename_file(target, aside) is True
        if moved_aside and self.fileops.rename_file(fresh, target) is True:
            self.fileops.delete_file(aside)
            return target
        # could not swap: the old copy goes back (if it moved) and the new one is dropped
        if moved_aside: self.fileops.rename_file(aside, target)
        self.fileops.delete_file(fresh)
        print(strings.INFO_SWAP_FAILED.format(shown))
        raise exceptions.SavedFileException(strings.SWAP_FAILED_REASON.format(shown, shown))

    def note_kept(self, work: str | None, work_url: str, new: str, old: str,
                  reason: str) -> None:
        """Remember a download that arrived but needs a person to look at it.

        The same {id, link, error} shape a failure has, so it reports and exports the same
        way - plus both file names, because there may now be two copies to find.
        """

        self.kept_copies.append({'id': work or '', 'link': work_url, 'file': new,
                                 'old': old, 'error': reason})


    def discard_damaged(self, work_url: str, saved: str, new: str, old_name: str,
                        size: int) -> None:
        """Remove a download that is not on disk as it arrived, and fail the work with why.

        A missing or short file must not stay: its name carries the current date, so every
        later run would call it up to date and never fetch it again. Any older copy is left
        exactly where it is. Raises `SavedFileException`, so the caller records a failure
        and the work is not counted as downloaded.
        """

        problem = self.fileops.saved_problem(saved, size)
        if not isinstance(problem, str) or not problem:
            problem = strings.SAVED_FINE_ON_SECOND_LOOK
        removed = self.fileops.delete_file(saved) is True

        if old_name:
            print(strings.INFO_DAMAGED_KEPT_OLD.format(old_name))
            detail = strings.DAMAGED_REASON_KEPT_OLD.format(new, problem, old_name)
        else:
            print(strings.INFO_DAMAGED_REMOVED.format(new))
            detail = strings.DAMAGED_REASON.format(new, problem)
        if not removed: detail += strings.DAMAGED_NOT_REMOVED
        raise exceptions.SavedFileException(detail)


    def replace_superseded(self, work_url: str, filetype: str,
                           saved_path: str, size: int) -> tuple[str | None, str]:
        """Remove the copy a download has just replaced, once it is safe to.

        Deliberately cautious, because the alternative is losing a file the user still has
        and we no longer have. Four things all have to hold:

          - there was an older copy recorded for this work
          - it is the *same* file type. re-downloading the html must never remove the epub
          - the new file is not the old one under a different name - if the name did not
            change there is nothing to remove, the write already replaced it
          - the new file is on disk, in the folder in use, at its full length

        Anything short of that leaves the old file exactly where it is.

        Returns what happened - `REPLACED`, `KEPT` (would not delete), `UNCONFIRMED` (the new
        file could not be vouched for) or None (nothing older to remove) - with the old
        file's name and, when not replaced, why. It prints nothing itself, or a replacement
        would be announced twice; `save_download` does the saying. `save_download` checks the
        new file before calling this, so the check here is a second line of defence.
        """

        old = self.superseded.get(work_url, {}).get(filetype)
        if not old: return None, '', ''
        name = os.path.basename(old)
        new = os.path.basename(saved_path) if isinstance(saved_path, str) else ''

        try:
            if os.path.abspath(old) == os.path.abspath(saved_path): return None, '', ''
            if not self.fileops.saved_intact(saved_path, size):
                self.fileops.write_log({
                    'link': work_url, 'message': strings.INFO_UNCONFIRMED.format(saved_path),
                    'old': old, 'level': 'debug'})
                return UNCONFIRMED, name, strings.UNCONFIRMED_REASON.format(
                    new, strings.SAVED_FINE_ON_SECOND_LOOK)
            if self.fileops.delete_file(old):
                # an old copy actually gone is what makes this an update rather than a
                # first download, which is the distinction the history file records
                work = parse_text.get_work_number(work_url)
                if work: self.updated.add(work)
                self.fileops.write_log({
                    'link': work_url, 'message': strings.INFO_REPLACED_OLD_COPY.format(old),
                    'level': 'debug'})
                return REPLACED, name, ''
            return KEPT, name, strings.KEPT_NOT_DELETED.format(name)
        except Exception as e:
            # never let tidying up an old file break a download that succeeded
            self.log_error({'message': strings.ERROR_REPLACE_OLD_COPY, 'link': work_url}, e)
            return UNCONFIRMED, name, strings.UNCONFIRMED_REASON.format(new, e)


    def proceed(self, thesoup: BeautifulSoup) -> BeautifulSoup:
        """Check locked/deleted and proceed through explicit agreement if needed"""

        if parse_soup.is_locked(thesoup):
            raise exceptions.LockedException(strings.ERROR_LOCKED)
        if parse_soup.is_deleted(thesoup):
            raise exceptions.DeletedException(strings.ERROR_DELETED)
        if parse_soup.is_hidden(thesoup):
            raise exceptions.HiddenException(strings.ERROR_HIDDEN)
        if parse_soup.is_explicit(thesoup):
            proceed_url = parse_soup.get_proceed_link(thesoup)
            thesoup = self.repo.get_soup(proceed_url)
        return thesoup


    def check_cancelled(self) -> None:
        """Stop the run if the caller has asked it to.

        Called at loop boundaries rather than mid-work, so whatever was being written
        finishes first and nothing is left half-saved.
        """

        if self.cancelled is not None and self.cancelled():
            raise exceptions.CancelledException(strings.INFO_CANCELLED)


    def check_session(self) -> None:
        """End the run if ao3 has stopped recognising the login it started with.

        A lapsed session does not announce itself. Ao3 simply serves the logged-out view,
        so a restricted work comes back as a page instead of a file and
        `repo.download_file` rejects it - the same failure a deleted work produces. The
        difference is that a lapsed session fails *everything* from then on.

        So the check is made only when a download has already failed, and **only once per
        run**: it costs a request, and asking again after each of four hundred failures
        would cost four hundred. If the session is alive this is a per-work failure like
        any other and the run carries on.
        """

        # always called from an except block, so the exception being handled is the current
        # one. a damaged file on disk says nothing about the login - don't pay to ask
        if isinstance(sys.exc_info()[1], exceptions.SavedFileException): return
        if self.session_checked: return
        # a run told not to log in has no session to lose: a work that needs one fails on its
        # own, and goes to FicHub at the end like any other failure
        if getattr(self.repo, 'logged_in', True) is False: return
        self.session_checked = True
        if self.repo.still_logged_in(): return
        raise exceptions.SessionExpiredException(strings.ERROR_SESSION_EXPIRED)


    def record_failure(self, link: str, exception: Exception) -> None:
        """Remember a work that would not come down, so the run can say so at the end.

        Recorded once per work rather than once per file type: a work that fails usually
        fails for every format, and a list with the same number in it five times is worse
        than useless for feeding back in.
        """

        work = parse_text.get_work_number(link or '')
        if any(x['link'] == link for x in self.failures): return
        self.failures.append({'id': work, 'link': link, 'error': str(exception),
                              **failure_reason(exception)})


    def log_error(self, log: dict, exception: Exception):
        log['error'] = str(exception)
        log['success'] = False
        if not isinstance(exception, exceptions.Ao3DownloaderException):
            log['stacktrace'] = ''.join(traceback.TracebackException.from_exception(exception).format())
        self.fileops.write_log(log)
