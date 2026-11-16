# region file ops

# based on https://docs.microsoft.com/en-us/windows/win32/fileio/naming-a-file#naming-conventions
INVALID_FILENAME_CHARACTERS = r'<>:"/\|?*.' + ''.join(chr(i) for i in range(32))
TIMESTAMP_FORMAT = '%m/%d/%Y, %H:%M:%S'

IMAGE_FOLDER_NAME = 'images'
INDEXING_FOLDER_NAME = 'indexing'
COLLECTIONS_FOLDER_NAME = 'collections'
HTML_FOLDER_NAME = 'source_code.html'
SETTINGS_FOLDER_NAME = 'source_code.settings'
LOG_FOLDER_NAME = 'logs'
# one json file per run, recording what it set out to do and what became of it. a subfolder
# of the downloads folder, beside `indexing` and `collections` - so everything that walks
# that folder has to skip it by name, exactly as it skips those.
RUNS_FOLDER_NAME = 'runs'
# downloaded works live here rather than in the library's top level, so the files a person
# actually reads are not mixed in with the app's own folders
WORKS_FOLDER_NAME = 'works'
# series and external-work bookmarks have no work number, and everything reading indexing/
# as works goes by the number a file name starts with - a series id could be mistaken for a
# work's. so they are kept in folders of their own inside indexing/, which nothing reading
# works looks into
SERIES_INDEX_FOLDER_NAME = 'series'
EXTERNAL_INDEX_FOLDER_NAME = 'external'
# every folder a library is expected to have. the web page creates whichever are missing
# when a library is opened, and a local run does the same as it starts
LIBRARY_FOLDER_NAMES = ('indexing', 'collections', 'images', 'runs', 'works')
LOG_FILE_NAME = 'log.jsonl'
SETTINGS_FILE_NAME = 'data.json'
TEMPLATE_FILE_NAME = 'template.html'
VISUALIZATION_FILE_NAME = 'logvisualization{}.html'
IGNORELIST_FILE_NAME = 'ignorelist.txt'

# settings, data and logs normally sit in the working directory. a deployed bundle keeps
# them in separate folders, so these let it say where without moving the working directory.
ENV_CONFIG_FOLDER = 'AO3DOWNLOADER_CONFIG_FOLDER'
ENV_LOG_FOLDER = 'AO3DOWNLOADER_LOG_FOLDER'
INI_FILE_NAME = 'settings.ini'
INI_SECTION_NAME = 'settings'

INI_WAIT_TIME = 'ExtraWaitTime'
INI_PASSWORD_SAVE = 'SavePassword'
INI_NAME_LENGTH = 'FileNameLength'
INI_NAME_PATTERN = 'FileNamePattern'
INI_DEBUG_LOGGING = 'EnableDebugLogging'
# adds a debug panel to the download window. for working on the app, not for using it.
INI_DEBUG_TOOLS = 'EnableDebugTools'
# prints every request and every line a run says to the helper's own console
INI_CONSOLE_LOGGING = 'EnableConsoleLogging'
# how long a background run may sit paused before the helper abandons it
INI_PAUSED_RUN_TIMEOUT = 'PausedRunTimeoutMinutes'
INI_DEFAULT_PAUSED_RUN_TIMEOUT = 10
# how long a question waits for an answer before taking its default; 0 takes it at once
INI_QUESTION_TIMEOUT = 'QuestionTimeoutMinutes'
INI_DEFAULT_QUESTION_TIMEOUT = 30
# how long a question about a file with no date in the app's own form waits: shorter, since a
# run can ask one per work and format
INI_UNSURE_QUESTION_TIMEOUT = 'GuessedDateQuestionTimeoutMinutes'
INI_DEFAULT_UNSURE_QUESTION_TIMEOUT = 1
# how long each of the questions a run can ask once per work waits - each its own, since one
# can come up hundreds of times in a run
INI_OVERWRITE_OLDER_TIMEOUT = 'OverwriteNewerCopyQuestionTimeoutMinutes'
INI_UNINDEXED_COPY_TIMEOUT = 'UnindexedCopyQuestionTimeoutMinutes'
# once a question goes unanswered, the rest like it in that run take their default at once
# rather than each waiting out its time ('nobody's here'). off asks every one, each waiting
INI_NOBODY_HERE = 'NobodyHereTakeDefaults'
# how many lines a run's own log keeps before its oldest give way, and whether only the most
# recent runs keep their logs at all
INI_RUN_LOG_MAX_LINES = 'RunLogMaxLines'
INI_TRIM_OLD_RUN_LOGS = 'KeepLogsOfRecentRunsOnly'
# how large the helper's log file and the updater's logs may grow, in MB, before their
# oldest lines are dropped; 0 for no limit
INI_LOG_FILE_MAX_MB = 'LogFileMaxMB'
INI_UPDATE_LOG_MAX_MB = 'UpdateLogMaxMB'
INI_DEFAULT_LOG_FILE_MAX_MB = 100
INI_DEFAULT_UPDATE_LOG_MAX_MB = 10
AO3_INFO_OLD_RUN_LOGS_REMOVED = 'removed the log from {} older run(s) - only the {} most recent runs keep theirs'
# what each question answers itself with when nobody does - on a timeout, a stop, and a
# background run that was not told. today's answers are the template's defaults
INI_QUICK_FLOOR_ANSWER = 'QuickScanFloorAnswer'
INI_FICHUB_ANSWER = 'FicHubAnswer'
INI_OVERWRITE_OLDER_ANSWER = 'OverwriteNewerCopyAnswer'
# a file without the app's own date in its name, by where the incoming version is from and
# what the date guessed from its name says: no keeps the file, yes replaces it
INI_AO3_GUESSED_OLDER_ANSWER = 'AO3GuessedOlderAnswer'
INI_AO3_GUESSED_NEWER_ANSWER = 'AO3GuessedNewerAnswer'
INI_AO3_UNKNOWN_DATE_ANSWER = 'AO3UnknownDateAnswer'
INI_FICHUB_GUESSED_OLDER_ANSWER = 'FicHubGuessedOlderAnswer'
INI_FICHUB_GUESSED_NEWER_ANSWER = 'FicHubGuessedNewerAnswer'
INI_FICHUB_UNKNOWN_DATE_ANSWER = 'FicHubUnknownDateAnswer'
INI_RETRY_REREAD_ANSWER = 'RetryRereadAnswer'
# each of those settings, the answers it may be, and the one it is when unset or misread
INI_ANSWER_CHOICES = {
    # not 'stamp': dating files needs a date, which only someone answering can give
    INI_QUICK_FLOOR_ANSWER: ('full', 'since'),
    INI_FICHUB_ANSWER: ('yes', 'no'),
    INI_OVERWRITE_OLDER_ANSWER: ('no', 'yes'),
    INI_AO3_GUESSED_OLDER_ANSWER: ('no', 'yes', 'both'),
    INI_AO3_GUESSED_NEWER_ANSWER: ('no', 'yes', 'both'),
    INI_AO3_UNKNOWN_DATE_ANSWER: ('no', 'yes', 'both'),
    INI_FICHUB_GUESSED_OLDER_ANSWER: ('no', 'yes', 'both'),
    INI_FICHUB_GUESSED_NEWER_ANSWER: ('no', 'yes', 'both'),
    INI_FICHUB_UNKNOWN_DATE_ANSWER: ('no', 'yes', 'both'),
    INI_RETRY_REREAD_ANSWER: ('no', 'yes'),
}
# how long one request to ao3 may take in all, and how often a run says it is still waiting
INI_REQUEST_TIMEOUT = 'RequestTimeoutSeconds'
INI_STILL_WAITING = 'StillWaitingSeconds'
# ao3's maintenance page: how many more tries, how far apart
INI_MAINTENANCE_RETRIES = 'MaintenanceRetries'
INI_MAINTENANCE_DELAY = 'MaintenanceRetrySeconds'
# the longest a retry of a failed request waits before asking again
INI_RETRY_MAX_DELAY = 'RetryMaxWaitSeconds'
# how long a run waits for the page to read or write the library, and how long for a page
# that has gone to come back
INI_LIBRARY_TIMEOUT = 'LibraryTimeoutMinutes'
INI_PAGE_GONE = 'PageGoneSeconds'
INI_MAX_RETRIES = 'MaxRetries'
INI_MAX_TIMEOUTS = 'MaxTimeouts'
# a hosted helper: every request needs the passcode, whose value is an environment variable
INI_REQUIRE_PASSCODE = 'RequirePasscode'
# the address of the page (e.g. https://someone.github.io) allowed to call a hosted helper
INI_PAGE_ORIGIN = 'PageOrigin'
# where the page finds its helper. read by the page's build, not by the helper
INI_HELPER_URL = 'HelperUrl'
INI_DEFAULT_HELPER_URL = 'http://127.0.0.1:4400'

INI_DEFAULT_NAME_LENGTH = 50

# how the date stamp on a downloaded file is written, and how long it is with its space.
# it goes on the end because the work number has to stay first for files to be matched
# back to their index entry.
DATE_STAMP_FORMAT = '%Y-%m-%d'
DATE_STAMP_LENGTH = 11

# How a downloaded file is named. Fixed rather than configurable: the work number has to
# come first for a file to be matched back to its index entry, and the date has to come
# last for the version it holds to be readable, so the parts that could vary are the ones
# that matter least. The ui shows this back instead of offering it as a setting.
FILE_NAME_PATTERN = '{worknum} {title} - {author}'

# how the date on the end is described when the naming is shown back to the user, and an
# example of the whole thing, so the rule can be read rather than deduced
DATE_STAMP_PLACEHOLDER = '{date updated}'
FILE_NAME_EXAMPLE_PARTS = ['1234567', 'The Trees Are Burning', 'library_of_alexandria', '2026-08-23']

SETTING_USERNAME = 'username'
SETTING_PASSWORD = 'password'
SETTING_FILETYPES = 'filetypes'
SETTING_API_TOKEN = 'api_token'
SETTING_UPDATE_FOLDER = 'update_folder'
SETTING_UPDATE_FILETYPES = 'update_filetypes'

# endregion

# region ui

PROMPT_YES = 'y'
PROMPT_NO = 'n'

PROMPT_MENU = '\'{}\' to display the menu again'
PROMPT_CHOOSE = 'please enter your choice, or \'{}\' to quit:'
PROMPT_OPTIONS = 'options'
PROMPT_INVALID_ACTION = 'please choose a valid action'

# for action description changes be sure to update readme
ACTION_DESCRIPTION_DISPLAY_MENU = 'display menu'
ACTION_DESCRIPTION_AO3 = 'download from ao3 link'
ACTION_DESCRIPTION_UPDATE = 'download latest version of incomplete fics'
ACTION_DESCRIPTION_PINBOARD = 'download bookmarks from pinboard'
ACTION_DESCRIPTION_VISUALIZATION = 'convert logfile into interactable html'
ACTION_DESCRIPTION_REDOWNLOAD = 're-download fics saved in one format in a different format'
ACTION_DESCRIPTION_UPDATE_SERIES = 'download missing fics from series'
ACTION_DESCRIPTION_LINKS_ONLY = 'get all work links from an ao3 listing (saves links only)'
ACTION_DESCRIPTION_MARKED_FOR_LATER = 'download marked for later list and mark all as read (requires login)'
ACTION_DESCRIPTION_FILE_INPUT = 'download links from file'
ACTION_DESCRIPTION_CONFIGURE_IGNORELIST = 'configure ignore list (list of links to never try to download)'

PINBOARD_PROMPT_API_TOKEN = 'please enter api token'
PINBOARD_PROMPT_INCLUDE_UNREAD = 'do you want to include unread bookmarks? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
PINBOARD_PROMPT_DATE = 'do you want to get bookmarks only after a specific date? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
PINBOARD_PROMPT_ENTER_DATE = 'please enter the date formatted {}:'
PINBOARD_INFO_GETTING_BOOKMARKS = 'getting bookmark urls from pinboard'
PINBOARD_INFO_NUM_RETURNED = '{} bookmarks returned'

AO3_PROMPT_LOGIN = 'do you want to log in to ao3? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_USERNAME = 'please enter username:'
AO3_PROMPT_PASSWORD = 'please enter password:\nNOTE: password {} be saved. to change this behavior,\nquit the script (using ctrl+c or by closing the window)\nand edit the \'' + INI_PASSWORD_SAVE + '\' setting in the ' + INI_FILE_NAME + '\nfile before running the script again\nNOTE: password input will not be displayed in this window'
AO3_PROMPT_PASSWORD_SAVE_TRUE = 'will'
AO3_PROMPT_PASSWORD_SAVE_FALSE = 'will not'
AO3_PROMPT_USE_SAVED_DOWNLOAD_TYPES = 'use saved download type list? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_ACCEPTABLE_DOWNLOAD_TYPES = ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML']
AO3_DOWNLOAD_TYPE_METADATA = 'JSON'
AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA = AO3_ACCEPTABLE_DOWNLOAD_TYPES + [AO3_DOWNLOAD_TYPE_METADATA]
AO3_PROMPT_DOWNLOAD_TYPE = 'please enter download type. choose from the following (case-sensitive):\n' + '\n'.join(AO3_ACCEPTABLE_DOWNLOAD_TYPES)
AO3_PROMPT_DOWNLOAD_TYPE_WITH_METADATA = (
    'please enter download type. choose from the following (case-sensitive):\n'
    + '\n'.join(AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA)
    + '\nNOTE: ' + AO3_DOWNLOAD_TYPE_METADATA + ' does not download the works themselves. it saves work and\n'
    + 'bookmark metadata for every work on the page to a single ' + AO3_DOWNLOAD_TYPE_METADATA.lower() + ' file.')
AO3_PROMPT_DOWNLOAD_TYPES_COMPLETE = 'done entering file types? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_LINK = 'please enter a link to ao3 (for example bookmarks, search results, or a series)'
AO3_PROMPT_LAST_PAGE = 'do you want to start downloading from the page you stopped on last time? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_PAGES = 'please enter page number to stop on. enter 0 to download all pages.'
AO3_PROMPT_IMAGES = 'do you want to download embedded images? (will be saved separately) ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_SERIES = 'do you want to get works from all encountered series links? (bookmarked series and subscriptions will always be downloaded, regardless of this option) ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_METADATA = 'do you want to include work metadata? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_PROMPT_FILE_INPUT = 'please enter complete file path (including file extension) to file containing links to download (must be a text file with one link on each line)'
AO3_PROMPT_METADATA_WORK_DATES = 'do you want to look up the original publication date of every work? this is the only\nfield that is not on the listing page, so it requires loading each work separately\nand is a lot slower. ({}/{})'.format(PROMPT_YES, PROMPT_NO)
AO3_INFO_LOGIN = 'logging in'
# the web ui shows the console output as the run's log, and logging in is the first thing
# it does. without a line here the modal opens on an empty log and looks like it hung
AO3_INFO_LOGGING_IN = 'logging in as {}'
AO3_INFO_NOT_LOGGING_IN = ('not logging in to AO3, as asked. private bookmarks will not be found, '
                           'works only logged-in users can see will fail, and FicHub is offered '
                           'for them at the end')
AO3_INFO_LOGGED_IN = 'successfully logged in'
AO3_INFO_DOWNLOADING = 'downloading works'
AO3_INFO_FILE_TYPE = 'added {} to list of download types'
AO3_INFO_METADATA = 'getting metadata'
AO3_INFO_INDEXING = 'indexing: saving a json file for every bookmark before downloading any works'
AO3_INFO_COLLECTIONS = 'syncing collections'
AO3_INFO_COLLECTION_SAVED = 'saved collection {}'
AO3_INFO_COLLECTION_UNCHANGED = 'collection {} still has {} {}, so the saved ones are kept'
AO3_INFO_COLLECTIONS_DONE = 'saved {} collections to {}'
# said per collection when the run indexes the works it holds as well
AO3_INFO_COLLECTION_WORKS = 'collection {}: indexed {} works not already found this run'
AO3_INFO_COLLECTION_WORKS_TOTAL = '{} works found across the collections'
AO3_INFO_DUPLICATE_ENTRIES = ('{} has {} index files - left from an older version, which gave a retitled work a '
                              'second one. writing to the most recently indexed: {}')
AO3_INFO_COLLECTIONS_LINKING = 'linking the works covered in this run to any collections you have indexed'
AO3_INFO_COLLECTIONS_LINKED = '{} works have been linked to your collections'
AO3_INFO_COLLECTIONS_LINKED_ONE = '1 work has been linked to your collections'
AO3_INFO_COLLECTION_SERIES = 'collection {}: reading the works in the {} series bookmarked in it'
AO3_INFO_COLLECTION_SERIES_UNCHANGED = 'series {}: its entry already lists all {} works, so it is not read again'
AO3_INFO_COLLECTION_EXTERNALS = 'collection {}: indexed {} external works (hosted off ao3, so never downloaded)'
# a collection's subcollections and parent, when the run follows them
AO3_INFO_COLLECTION_FAMILY = 'collection {}: linked from {}, so reading it too'
AO3_INFO_COLLECTION_FAMILY_LIMIT = ('read {} related collections, the most one run will follow - '
                                    'leaving the {} still queued')
# the most related collections one run reads. each is read at most once anyway, so this only
# matters for a family so large that following it would take one run across much of ao3
COLLECTION_FAMILY_LIMIT = 200
AO3_INFO_COLLECTIONS_NONE = 'no collections found for that user'
AO3_INFO_COLLECTION_ONE = 'indexing the collection {}'

# one of these four is said for every file a download writes. indented to sit under the fic
INFO_SAVED_NEW_COPY = '    new download: {}'
# said for an outdated copy removed and for a copy written over under the same name alike
INFO_REPLACED_OLD_COPY = '    replaced the older copy: {}'
INFO_KEPT_OLD_COPY = '    a new copy was downloaded, but the old copy still exists as it could not be safely deleted: {}'
# the new file failed its check and was removed. the first names the old copy still on disk;
# the second is a first download, or a same-name overwrite, where there is no old copy left
INFO_DAMAGED_KEPT_OLD = '    a new copy was downloaded, but found to have a problem so was removed. the old copy still exists: {}'
INFO_DAMAGED_REMOVED = '    a new copy was downloaded, but found to have a problem so was removed: {}'
INFO_UNCONFIRMED = '    a new copy was downloaded, but could not be confirmed: {}'
# why, recorded with each so the run's report can say
KEPT_NOT_DELETED = 'the older copy {} could not be deleted - it may be open in another program, read-only, or locked by a sync or antivirus tool'
UNCONFIRMED_REASON = 'checking the downloaded file {} failed, so it was left as it is and nothing else was deleted: {}'
DAMAGED_REASON = 'the downloaded file {} {}, so it was removed'
DAMAGED_REASON_KEPT_OLD = 'the downloaded file {} {}, so it was removed. the older copy {} is still there'
DAMAGED_NOT_REMOVED = ' - but removing it failed too, so delete it by hand'
SAVED_NOT_FOUND = 'could not be found at {}'
SAVED_WRONG_SIZE = 'was the wrong size: expected {} bytes, found {}'
SAVED_UNREADABLE = 'could not be read back: {}'
SAVED_FINE_ON_SECOND_LOOK = 'did not match the downloaded size when first checked'
AO3_INFO_KEPT_COPIES = '{} works were downloaded but need checking by hand'
ERROR_REPLACE_OLD_COPY = 'Problem removing the copy a download replaced. The old file is still there.'
AO3_INFO_OUT_OF_DATE = '{} downloaded works have been updated on ao3 since you saved them'
# an index entry's field saying whether the logged-in user has bookmarked the fic: True off
# their own bookmarks listing or a work page saying 'Edit Bookmark', False off a page saying
# 'Bookmark', and absent when nothing has been able to tell
BOOKMARKED_FIELD = 'bookmarked'
# what a bookmark is of. a work found only through a bookmarked series is still an
# individual work - `from_series` says how it got into the index
BOOKMARK_TYPE_FIELD = 'bookmark_type'
BOOKMARK_TYPE_WORK = 'individual work'
BOOKMARK_TYPE_EXTERNAL = 'external work'
BOOKMARK_TYPE_SERIES = 'series bookmark'
# the bookmarked series a work was found through, by series id
FROM_SERIES_FIELD = 'from_series'
# the works a series held when it was last read, on the series' own entry
SERIES_WORKS_FIELD = 'work_ids'
# on a work: the series it is part of, as [{id, title, part}] - read off its blurb or page
SERIES_MEMBERSHIP_FIELD = 'series'
# the bookmark's own fields: what you wrote and when. a work read off a series page has
# none of them, so an existing entry keeps its own rather than having them blanked
# set on an entry a fic run indexed from its link or work number when it was not one of your
# bookmarks. identity, so a later reading from any other run keeps it; the page sorts it into
# 'Downloaded by ID or URL', after your bookmarks and collections
FROM_LINK_FIELD = 'from_link'
# a work first indexed because its file was found in your library with no index entry, and
# imported (`ACTION_IMPORT`) - not your bookmark. an identity field, like `from_link`
FROM_IMPORT_FIELD = 'from_import'
BOOKMARK_OWN_FIELDS = ('date_bookmarked', 'bookmark_notes', 'bookmark_tags',
                       'bookmark_collections', 'bookmark_private', 'bookmark_rec',
                       BOOKMARKED_FIELD)
AO3_INFO_CHECKING_FILES = 'checking which of these you have already downloaded'
AO3_INFO_CHECKING_VERSIONS = 'checking which of your downloads ao3 has a newer version of'
AO3_INFO_UP_TO_DATE = 'everything else you have is already the current version'
AO3_INFO_OVERWRITING = 'overwriting {} downloaded works at your request, current or not'
AO3_INFO_FROM_INDEX = 'downloading {} works directly, without re-indexing'
AO3_INFO_FROM_INDEX_NEW = '  {} new - not downloaded before'
AO3_INFO_FROM_INDEX_UPDATING = '  {} already downloaded, updating to the newest version'
AO3_INFO_FROM_INDEX_OVERWRITING = '  {} already downloaded, downloading again at your request'
AO3_INFO_FROM_INDEX_MISSING = '  {} already downloaded, fetching a format you do not have yet'
AO3_INFO_FAILED_WORKS = '{} works could not be downloaded'
# the 'new bookmarks only' walk, which stops at the first fic it already has
AO3_INFO_INDEXING_NEW = 'indexing your newest bookmarks, stopping at the first one you already have'
AO3_INFO_REACHED_KNOWN = 'reached a fic you have already indexed - nothing newer left to find'
# the quick scan's stop: it walks a listing ordered by when ao3 last updated each work, so
# the first one older than the floor means everything after it is older too
AO3_INFO_REACHED_OLDER = 'reached a fic ao3 last updated before {} - nothing older to check'
AO3_INFO_QUICK_FLOOR = 'indexing works ao3 has updated since your last completed run, on {}'
AO3_INFO_QUICK_NO_FLOOR = 'no completed run on record, so this reads the whole listing'
AO3_INFO_QUICK_WINDOW = 'looking for works bookmarked or updated between {} and {}'
AO3_INFO_QUICK_IN_WINDOW = '{} works were bookmarked or updated in that date range'
AO3_INFO_DATE_NOW = 'now'
AO3_INFO_QUICK_CHOSEN_FLOOR = 'measuring back to the scan you chose, which started on {}'
AO3_INFO_QUICK_CHOSEN_GONE = ('the scan you chose is no longer on record, so this falls back to '
                              'your last completed scan')
# the web page holds the library, so a run that loses the page loses its folder
ERROR_PAGE_GONE = ('the page holding your library was closed or lost its connection, so the '
                   'run could not reach your files. Keep the page open while a run is going; '
                   'starting the run again picks up where this one stopped.')
AO3_INFO_QUICK_BOOKMARKED = 'indexing bookmarks you have added since {}'
AO3_INFO_QUICK_UPDATED = 'indexing works ao3 has updated since {}'
AO3_INFO_QUICK_UPDATED_NOT_NEEDED = ('no floor, so the first pass already read every bookmark '
                                     '- not reading the listing a second time')
# no run qualifies as a floor, but the index already holds something. asked rather than
# decided: a full listing is hours on a large library, and the date the index was last
# written is a guess only the person who built it can judge
AO3_INFO_QUICK_ASKING = ('no completed scan on record, but your index already holds {} works, '
                        'last written on {}')
AO3_INFO_QUICK_WAITING = 'waiting for you to choose how far back to go'
AO3_INFO_QUICK_SINCE_INDEX = 'indexing works ao3 has updated since your index was last written, on {}'
AO3_INFO_QUICK_CHOSE_FULL = 'reading the whole listing, as a first scan would'
# sorting the bookmarks listing by when ao3 last updated each work, rather than by when it
# was bookmarked. verified against the live site: the default order is by date bookmarked
# and jumps about, so a walk that stops at the first older fic would stop almost at once.
AO3_SORT_BY_UPDATED = 'bookmark_search%5Bsort_column%5D=bookmarkable_date'
# 'Date Bookmarked' on ao3's own sort menu - verified against the live search form, where
# it is `created_at` beside `bookmarkable_date` for 'Date Updated'
AO3_SORT_BY_BOOKMARKED = 'bookmark_search%5Bsort_column%5D=created_at'
AO3_INFO_NEW_NONE = 'no new bookmarks since the last run'
AO3_INFO_NEW_FOUND = 'found {} newly bookmarked works'
# the gap-filling pass at the end of a combined run
AO3_INFO_CHECKING_GAPS = 'checking your finished fics for formats this run asked for but you do not have'
AO3_INFO_GAPS_NONE = 'nothing missing - every finished fic has the formats you asked for'
AO3_INFO_GAPS_FOUND = '{} finished works are missing a format you asked for'
AO3_INFO_GAP_WORK = '[{} of {}] {} - fetching {}'
AO3_INFO_GAP_INDEXED = '    index updated'
# the debug tool, which really does skip: whatever the step would have done does not happen
AO3_INFO_STEP_SKIPPED = 'skipping the rest of this step at your request'
# one fic on its own, by link or work number
AO3_INFO_ONE_WORK = 'looking up work {} on AO3'
# said before and after a fic run looks for the index entry it already has, once ao3 has
# shown the work - a lookup by number, but one that reaches into the library (in Dropbox,
# a download), so it is named
AO3_INFO_INDEX_CHECK = 'looking for an existing index file for work {}...'
AO3_INFO_INDEX_FOUND = 'found the index file for work {}: {}'
AO3_INFO_INDEX_NOT_FOUND = 'no index file for work {} yet - a new one will be made'
# said for each fic a fic run looks up: whether its index entry was actually written - a
# step marked done (or a series step skipped) says nothing about this fic on its own
AO3_INFO_ONE_WORK_INDEXED = 'index updated for work {}'
AO3_INFO_ONE_WORK_NOT_INDEXED = 'index not updated for work {}'
AO3_INFO_ONE_WORK_UNREADABLE = 'AO3 would not show this work: {}'
AO3_INFO_ONE_WORK_DONE = 'finished with work {}'
AO3_INFO_MANY_WORKS = '{} fics to look up'
AO3_INFO_MANY_WORK = 'fic {} of {}: looking up work {} on AO3'
# a custom run told to work from what is already indexed
# the separate images pass, which costs a work page per fic on top of everything else
AO3_INFO_IMAGES_START = 'now fetching each work page for the images embedded in it - this is the slow part'
AO3_INFO_IMAGE_WORK = '[{} of {}] {} - {} images saved'
AO3_INFO_IMAGES_DONE = 'saved {} images from {} works'

# a custom run covering a window of time rather than a slice of the listing
AO3_INFO_DATE_WINDOW = 'looking for works ao3 last updated between {} and {}'
AO3_INFO_DATE_ANY = 'the beginning'
AO3_INFO_DATE_NONE = 'no indexed works fall in that window'
AO3_INFO_DATE_FOUND = '{} indexed works fall in that window'
AO3_INFO_RECHECK = 'looking up every work in your index on AO3, one at a time - {} works'
AO3_INFO_RECHECK_NONE = 'there are no works in your index to look up'
AO3_INFO_DATE_INDEXING = 'indexing bookmarks by when ao3 last updated them, back to {}'
AO3_INFO_DATE_NO_FLOOR = 'no earliest date given, so this indexes the whole listing'

AO3_INFO_USING_LAST_INDEX = 'skipping indexing - working from what is already in your index'
AO3_INFO_INDEXED_COUNT = 'your index holds {} works'

AO3_INFO_READING_INDEX = 'reading your index for fics it last saw unfinished'
AO3_INFO_INCOMPLETE_FOUND = 'the index lists {} works as unfinished'
# said per fic, so the log reads as a running account of what is happening to each one
AO3_INFO_UPDATE_WORK = '[{} of {}] {}'
# said before the request, not after: opening the fic page is the slow part, so without a
# line first the run looks stalled on the fic it has only just named
AO3_INFO_UPDATE_READING = '    reading latest index'
AO3_INFO_UPDATE_INDEXED = '    index updated'
AO3_INFO_UPDATE_ALREADY_FRESH = (
    '    already indexed earlier in this run by a previous step - downloading directly')
# said per format, not per fic. a run asking for html and pdf can want one and already have
# the other, and 'downloading it' told you neither which nor why
# which button was pressed, recorded in the run's history file. the label rather than the
# action name, so a history read months later says what was actually clicked - and kept
# here rather than taken from the ui, because the file has to make sense on its own.
ACTION_NAME_BOOKMARKS = '(Full scan) Reindex & Update All'
ACTION_NAME_UPDATE = 'Just update any bookmarks marked as incomplete'
ACTION_NAME_COLLECTIONS = 'Index my collections'
ACTION_NAME_COLLECTION = 'Index collection by URL'
ACTION_NAME_NEW = 'Just download newly added bookmarks'
ACTION_NAME_SYNC = 'Download new bookmarks and update incomplete fics'
ACTION_NAME_WORK = 'Download/update a specific fic'
ACTION_NAME_WORKS = 'Download/update several fics'
ACTION_NAME_IMPORT = 'Import works found in your library'
ACTION_NAME_CUSTOM = 'Custom run'
ACTION_NAME_QUICK = 'Quick Scan'

# the checklist a run shows: what it intends to do, in order. one label per step, so the
# panel reads as a plan rather than as a log that has to be interpreted.
STEP_LOGIN = 'Log in to AO3'
STEP_INDEX_ALL = 'Index every bookmark'
STEP_INDEX_NEW = 'Index bookmarks added since last time'
STEP_INDEX_BOOKMARKED_SINCE = 'Index bookmarks added since your last run'
STEP_INDEX_SINCE = 'Index works AO3 has updated since your last run'
STEP_INDEX_BOOKMARKED_WINDOW = 'Index bookmarks added in that date range'
STEP_INDEX_UPDATED_WINDOW = 'Index works AO3 updated in that date range'
STEP_INDEX_ONE = 'Index this fic'
STEP_INDEX_MANY = 'Index these fics'
STEP_INDEX_IMPORT = 'Index the works found in your library'
STEP_INDEX_COLLECTIONS = 'Index your collections'
STEP_INDEX_COLLECTION = 'Index this collection'
# the same crawl, told to index each work it meets as well - see Ao3.collect_work_ids
STEP_INDEX_COLLECTIONS_WORKS = 'Index your collections and the works in them'
STEP_INDEX_COLLECTION_WORKS = 'Index this collection and the works in it'
STEP_USE_INDEX = 'Read the index already saved'
STEP_CHECK_FILES = 'Read your existing downloaded files'
# a scan indexes first, so by the time this runs it knows which copies ao3 has moved
# past - those are replaced rather than skipped, which is why it is not just 'download'
STEP_DOWNLOAD = 'Download or update works as necessary'
# the single-fic run always replaces what you have, so nothing about it is conditional
STEP_DOWNLOAD_ONE = 'Download this fic'
STEP_DOWNLOAD_MANY = 'Download these fics'
STEP_DOWNLOAD_IMPORT = 'Download the formats asked for'
# the runs that only ever fetch bookmarks added since last time say so, because on those
# 'the works' would read as the whole library
STEP_DOWNLOAD_NEW = 'Download newly added works'
STEP_READ_INDEX = 'Read existing index for unfinished fics'
STEP_INDEX_WINDOW = 'Index works AO3 has updated since that date'
STEP_READ_WINDOW = 'Find indexed works updated in that date range'
# a custom run skipping the indexing, told to look every indexed work up on AO3 (`recheck`)
STEP_READ_RECHECK = 'Read every work in your index'
STEP_UPDATE_WINDOW = 'Download or update each fic as necessary'
STEP_UPDATE = 'Re-index each fic, then download or update as necessary'
STEP_FILL_GAPS = 'Fetch any format still missing'
STEP_IMAGES = 'Save embedded images separately'
STEP_REPORT = 'Report any failures'
STEP_SERIES = 'Index works in series marked for walkthrough'
STEP_NON_BOOKMARKS = 'Check remaining non-bookmarks for updates'
STEP_CLEANUP = 'Cleanup'
# after everything ao3 was asked for, before the cleanup: the works ao3 would not give us,
# asked for again from a mirror of it
STEP_FICHUB = 'Try FicHub for works AO3 would not give us'

# FicHub (fichub.net) keeps copies of ao3 works, including some ao3 no longer serves. its
# api answers a work's link with the work's details and where each format can be fetched
FICHUB_SITE = 'fichub'
SOURCE_AO3 = 'AO3'
SOURCE_FICHUB = 'FicHub'
FICHUB_BASE_URL = 'https://fichub.net'
FICHUB_API_URL = FICHUB_BASE_URL + '/api/v0/epub'
# the formats FicHub makes. ao3's azw3 is not among them
FICHUB_FORMATS = ('EPUB', 'HTML', 'MOBI', 'PDF')
# on an index reading made from FicHub rather than ao3: {'site': 'fichub', 'downloaded':
# [formats fetched from it]}. a reading from ao3 never carries it
RETRIEVED_FROM_FIELD = 'retrieved_from'
AO3_INFO_FICHUB_ASK = ('{} works could not be fetched from AO3 ({}). '
                       'waiting for you to choose whether to try FicHub for them...')
AO3_INFO_FICHUB_DECLINED = 'not trying FicHub'
AO3_INFO_FICHUB_TRYING = 'trying FicHub for {} works: {}'
# each said before the thing it describes happens, so the run says what it is waiting on
AO3_INFO_FICHUB_WORK = 'FicHub {} of {}: asking FicHub about work {} ({})...'
AO3_INFO_FICHUB_FOUND = '  FicHub has work {}: {}'
AO3_INFO_FICHUB_FETCHING = '  fetching {} of work {} from FicHub...'
AO3_INFO_FICHUB_INDEXING = '  writing the index entry for work {} from what FicHub says...'
AO3_INFO_FICHUB_INDEX_ONLY = '  work {}: only looked up for its index entry - nothing downloaded from FicHub'
AO3_INFO_FICHUB_NOT_INDEXED = '  index not updated for work {}'
AO3_INFO_FICHUB_INDEXED = '  index updated for work {} from FicHub'
# a format there was no file of, taken from FicHub although FicHub's copy is dated before the
# latest update date known for the work - in the index, or in another of its files' names
AO3_INFO_FICHUB_OLDER_TAKEN = ('  warning: the {} of work {} from FicHub is dated {}, older than the last known '
                               'update date we have ({}{}) - it may be an older cached copy')
FICHUB_OLDER_FROM_FILE = ', from your {}'
AO3_INFO_FICHUB_OLDER_REPLACED = ('  warning: the {} of work {} from FicHub, dated {}, replaced your copy ({}) - '
                                  'but it is still older than the last known update date we have ({}{}) - it may '
                                  'be an older cached copy')
FICHUB_OLDER_YOURS_DATED = 'dated {}'
AO3_INFO_FICHUB_OLDER_COPIES = ('{} works got a format from FicHub that may be an older cached copy - '
                                'older than the last known update date we have, whether you had no file of it or '
                                'it replaced an older one')
AO3_INFO_FICHUB_RESCUED = '{} works AO3 would not give us came from FicHub instead'
AO3_INFO_FICHUB_FAILED_TOO = '  not on FicHub either: {}'
# FicHub's copy is a cache, and can be older than what the index already says of the work
AO3_INFO_FICHUB_OUTDATED = ('  FicHub\'s copy of work {} was last updated {}, older than the last '
                            'known update date we have ({})')
AO3_INFO_IMPORT_UNDATED_KEPT = 'files with no date in their names were left undated before the import started, so they are kept as they are'
AO3_INFO_ALWAYS_ANSWER = '  you chose to always answer this the same way: {}'
AO3_INFO_NOBODY_ANSWERING = '  nobody answered the last question like this, so the rest take the default without waiting: {}'
AO3_INFO_FICHUB_OUTDATED_NOTHING = '  nothing FicHub has is newer than what you have, so nothing is taken from FicHub'
AO3_INFO_FICHUB_NEWER_THAN_FILE = '  {}: FicHub\'s copy ({}) is newer than yours ({}), though older than the last known update date we have - replacing it'
AO3_INFO_FICHUB_SAME_AS_FILE = '  {}: yours is the same version as FicHub\'s ({}) - keeping it'
AO3_INFO_FICHUB_NOT_NEWER = '  {}: yours ({}) is newer than FicHub\'s copy - keeping it'
NO_DATE_IN_NAME = 'no date in its name'
AO3_INFO_UNSURE_COPIES = ('  work {}: your {} - no date written the way this app writes one, so '
                          'nothing is replaced without asking. {}\'s version is dated {}')
UNSURE_NO_INCOMING_DATE = 'your file\'s name looks dated {} (a guess), but {} gives no date to compare it with - we recommend keeping yours'
UNSURE_THINK_OLDER = 'your file\'s name looks dated {} (a guess), so we think {}\'s version ({}) is newer - we recommend replacing it'
UNSURE_THINK_SAME = 'your file\'s name looks dated {} (a guess), the same as {}\'s version ({}) - we recommend keeping yours'
UNSURE_THINK_NEWER = 'your file\'s name looks dated {} (a guess), so we think yours is newer than {}\'s version ({}) - we recommend keeping yours'
# an overwriting run: a guess the same as the incoming date is replaced like an older one, as a
# file with the app's own date would be
UNSURE_THINK_SAME_OVERWRITE = 'your file\'s name looks dated {} (a guess), the same as {}\'s version ({}), and this run overwrites - we recommend replacing it'
# no date to read, from AO3: AO3's own copy is the version AO3 serves now, so replacing is probably
# safe - recommended on every run, though the default still keeps yours
UNSURE_CANNOT_INFER_AO3 = 'no date can be read from your file\'s name, so we cannot tell which is newer - but the incoming copy is AO3\'s own, so it is probably safe to replace it - we recommend replacing it'
# FicHub keeps copies it fetched at some time: one may be older than AO3's latest
UNSURE_CANNOT_INFER_FICHUB = 'no date can be read from your file\'s name, so we cannot tell which is newer - and FicHub\'s copy may be an older cached one, not up to date with AO3\'s latest - we recommend keeping yours'
AO3_INFO_FICHUB_TAKING_OLDER = ('  no {} of work {} on disk - taking FicHub\'s copy anyway: an older '
                                'version is better than none')
AO3_INFO_FICHUB_INDEX_KEPT = '  index for work {} left as it was: its last known update date is newer than FicHub\'s copy'
# an overwriting run whose version is older than the copy already on disk
AO3_INFO_OLDER_THAN_COPY = ('  the version about to be downloaded of work {} ({}) is older than '
                            'your {} ({}) - waiting for you to choose whether to replace it...')
AO3_INFO_KEEPING_NEWER = '  {}: keeping your newer copy'
# a work the index had no entry for when the run began: its files did not come from this app, so
# the run asks - recommending from the date in each file's own name (the only thing that dates a
# file), defaulting to no
AO3_INFO_UNINDEXED_COPY = ('  work {} was not in your index when this run began, so your {} did not '
                           'come from this app - each is judged only by the date in its own name. '
                           'the version from {} is dated {} - waiting for you to choose whether to '
                           'replace it...')
AO3_INFO_UNINDEXED_FORMAT = '    {}: {}'
AO3_INFO_UNINDEXED_REPLACING = '  {}: replacing your copy, as asked'
AO3_INFO_UNINDEXED_KEEPING = '  {}: keeping your copy'
# why each copy of an unindexed work is or is not recommended for replacing - worded as the
# guessed-date question words it, saying whether the date in the name is certain (written the
# app's way) or only a guess. Named fields: source, theirs (the incoming date), said (the file's)
UNINDEXED_REASON_NEWER = "its name is dated {said}, so {source}'s version ({theirs}) is newer. We recommend replacing it"
UNINDEXED_REASON_NEWER_GUESSED = "its name looks dated {said} (a guess), so we think {source}'s version ({theirs}) is newer. We recommend replacing it"
UNINDEXED_REASON_SAME_OVERWRITING = "its name is dated {said}, the same as {source}'s version, and this run overwrites. We recommend replacing it"
UNINDEXED_REASON_SAME_OVERWRITING_GUESSED = "its name looks dated {said} (a guess), the same as {source}'s version ({theirs}), and this run overwrites. We recommend replacing it"
UNINDEXED_REASON_NOT_NEWER = "its name is dated {said}, so yours is as new as {source}'s version ({theirs}) or newer. We recommend keeping it"
UNINDEXED_REASON_NOT_NEWER_GUESSED = "its name looks dated {said} (a guess), so we think yours is as new as {source}'s version ({theirs}) or newer. We recommend keeping it"
UNINDEXED_REASON_NO_FILE_DATE_AO3 = "no date can be read from its name, so we can't tell whether AO3's version ({theirs}) is newer. But the incoming copy is AO3's own, so it is probably safe to replace it. We recommend replacing it"
UNINDEXED_REASON_NO_FILE_DATE_FICHUB = "no date can be read from its name, so we can't tell whether FicHub's version ({theirs}) is newer. FicHub's copy may be an older cached one, not up to date with AO3's latest. We recommend keeping it"
UNINDEXED_REASON_NO_DATE = "{source} gives no date for its version, so there is nothing to compare with. We recommend keeping it"
# an import told not to replace outdated copies keeps every copy you have, current or not
AO3_INFO_KEEPING_YOURS = '  {}: keeping the copy you have (not replacing outdated copies)'
AO3_INFO_IMPORT_WORKS = '{} works found in your library to look up'
AO3_INFO_IMPORT_RENAMED = 'renamed to match its index entry: {} -> {}'
AO3_INFO_IMPORT_NAME_KEPT = 'could not rename {} to match its index entry ({} is taken, or the rename was refused) - left as it is'
AO3_INFO_IMPORT_NAMES_UNREADABLE = 'could not list your works folder to name the imported files from their index entries: {}'
# the page's list of files and works never to offer again in Resolve issues found in your
# library, at the library's top. the page reads it; an import renaming a file keeps it current
IMPORT_EXCLUDED_FILE_NAME = 'import-excluded.json'
AO3_INFO_IMPORT_EXCLUDED_RENAMED = 'exclusion list updated for {} renamed {}'
AO3_INFO_IMPORT_EXCLUDED_UNSAVED = 'could not update the exclusion list for the renamed files: {}'
AO3_INFO_IMPORT_KEEPING = 'not replacing outdated copies: only formats you do not have are fetched'
AO3_INFO_IMPORT_INDEX_ONLY = '{} of these works are only indexed: no format is fetched for them'
ERROR_NO_IMPORT_WORKS = 'There are no works to import.'
AO3_INFO_REPLACING_NEWER = '  replacing your newer {} of work {} with the older version, as asked'
ERROR_FICHUB_OUTDATED = 'FicHub only has an older version (updated {}; the last known update date we have is {})'
ERROR_FICHUB_LOOKUP = 'FicHub could not find it ({})'
ERROR_FICHUB_STATUS = 'FicHub answered {}'
ERROR_FICHUB_NOT_JSON = 'FicHub answered with something that is not its usual reply'
ERROR_FICHUB_WRONG_WORK = 'FicHub answered about a different work ({})'
ERROR_FICHUB_NO_FORMAT = 'FicHub does not offer {}'
ERROR_FICHUB_NOT_A_FILE = 'FicHub sent a page instead of the {} file ({})'
ERROR_FICHUB_ELSEWHERE = 'FicHub pointed the {} download somewhere other than fichub.net'
AO3_INFO_FORCE_STOPPED = ('force stopped from the History tab. anything this run was in the middle of '
                          'was left unfinished; everything it had already saved is kept')
ERROR_FORCE_STOPPED = 'Force stopped from the History tab'
ERROR_AO3_AND_FICHUB = 'AO3: {} | FicHub: {}'
# a work with more than one file of a format: each is judged by the newest copy dated the app's
# way, and no other copy is ever deleted by a run
AO3_INFO_DUPLICATES_KEPT = ('{} formats of these works have more than one file - each is compared by '
                            'its nominated file (the newest dated the way this app dates them, else '
                            'the newest by a guessed date, else the first by name), and every other '
                            'copy is kept. Resolve issues can clean them up later')
AO3_INFO_KEEPING_BOTH = '  {}: keeping your copy, and saving the incoming version beside it as a new file'
AO3_INFO_UNSURE_OTHER_COPIES = '    you also have other {} copies of it - these will be kept for now, and can be cleaned up later: {}'
AO3_INFO_CLEANUP = 'removing {} older copies marked for removal'
AO3_INFO_CLEANUP_REMOVED = '  removed {}'
AO3_INFO_CLEANUP_FAILED = '  could not remove {}: {}'
AO3_INFO_CLEANUP_KEPT = '  kept {}: this run downloaded a file to that name'
AO3_INFO_CLEANUP_STOPPED = 'the run was stopped, so the {} older copies marked for removal were left in place'
AO3_INFO_NOT_REMOVED = '{} older copies marked for removal were not removed - the list below says which'
CLEANUP_STOPPED = 'the run stopped before the cleanup step'
CLEANUP_FAILED_RUN = 'the run failed before the cleanup step'
CLEANUP_WROTE_OVER = 'this run downloaded a file to that name, so it is no longer the older copy'
CLEANUP_NOT_DELETED = 'the file could not be deleted'

AO3_INFO_FORMAT_MISSING = '    no copy in {} - downloading now'
AO3_INFO_FORMAT_OUTDATED = '    outdated version in {} - replacing now'
AO3_INFO_FORMAT_CURRENT = '    already have the current version in {}'
AO3_INFO_FORMAT_UNDATED = '    copy in {} has no date, so it cannot be judged - left alone'
AO3_INFO_FORMAT_REPLACING = '    downloading {} again at your request'
AO3_INFO_UPDATE_CURRENT = '    you already have the current version - nothing to download'
AO3_INFO_UPDATE_BEHIND = '    your copy is behind, downloading the new version'
AO3_INFO_UPDATE_MISSING = '    you have no copy of this one, downloading it'
AO3_INFO_UPDATE_NOTHING = '    nothing to download, only the index was updated'
AO3_INFO_UPDATE_DONE = 'checked {} works and downloaded {}'
AO3_INFO_INCOMPLETE_NONE = 'the index lists no unfinished works. nothing to check.'
AO3_INFO_INCOMPLETE_GREW = '{} of them need downloading again'
AO3_INFO_INCOMPLETE_UNCHANGED = 'none of them have changed since you last downloaded them'
ERROR_WORK_STATS = 'Could not read the stats from that work page'
ERROR_NOT_A_WORK_FILE = 'Ao3 answered with a page rather than the {} file ({}). The work may have been deleted, made restricted, or be unavailable in that format.'
ERROR_NOT_A_WORK_FILE_STATUS = 'status {}'
# a format that failed while the rest of the work's formats were still tried
INFO_FORMAT_FAILED = '    {} could not be downloaded: {}'
ERROR_FORMAT_FAILED = '{}: {}'
ERROR_NOT_A_WORK_FILE_TYPE = 'status {}, but the content was a web page'

# how many entries ao3 puts on a page of a listing. only used to work out how many works
# sit before a run that starts partway through, so its positions carry on from there.
AO3_LISTING_PAGE_SIZE = 20
AO3_INFO_METADATA_WORK_DATES = 'looking up publication dates for {} works'
AO3_INFO_METADATA_PROGRESS = 'finished {} of {} works'
# said before the request, not after it. fetching a listing page is the slow part, and a
# log that only reports finished pages sits unchanged for the whole of every wait - which
# reads as a hang rather than as work in progress. the total is not known until the first
# page comes back, so the first one has nothing to count towards.
AO3_INFO_METADATA_FETCHING = 'fetching page {} of {}'
AO3_INFO_METADATA_FETCHING_FIRST = 'fetching page {}'
AO3_INFO_METADATA_PAGE = 'finished page {} of {}. {} works so far'
# a listing of one page carries no pagination for the total to be read from, so there is
# genuinely nothing to count towards - saying 'of None' would be worse than saying nothing
AO3_INFO_METADATA_PAGE_ONLY = 'finished page {}. {} works so far'
AO3_INFO_METADATA_SKIPPED = 'skipped {} bookmarks that are not works (series, external works, or deleted works)'
# why one bookmark could not be indexed. said per bookmark, so the list at the end names
# each one rather than leaving a count to be worked out from
AO3_INFO_SKIPPED_WORKS = '{} bookmarks were not works and could not be downloaded - the list below says which, and why'
SKIPPED_SERIES = 'a series, not a single work'
AO3_INFO_SERIES_MARKED = 'marking series for walkthrough: "{}"'
AO3_INFO_SERIES_MARKED_BOOKMARK = 'marking series for walkthrough: "{}" (a series you bookmarked)'
AO3_INFO_SERIES_STEP = 'indexing the works in {} series marked for walkthrough'
AO3_INFO_SERIES_NONE = 'no series were marked for walkthrough'
AO3_INFO_NON_BOOKMARKS = ('checking {} non-bookmarks for updates - marking their series for '
                          'walkthrough first, which reads 20 works a request')
AO3_INFO_NON_BOOKMARKS_READING = ('reading {} non-bookmarks the series walk did not reach, '
                                  'one request each')
AO3_INFO_NON_BOOKMARKS_NONE_LEFT = 'every non-bookmark was read by the series walk'
AO3_INFO_SERIES_READING = 'walking through the series "{}" for the works in it'
AO3_INFO_SERIES_READ = '  {} works in that series: {} indexed from it, {} already indexed this run'
ERROR_SERIES = 'could not read a series marked for walkthrough - its works were not indexed from it'
SKIPPED_EXTERNAL = 'an external work, hosted somewhere other than ao3'
SKIPPED_DELETED = 'the work has been deleted'
# an author hides a work by putting it in an unrevealed collection. it keeps its work
# number and is indexed like any other, but ao3 will not serve the file until it opens.
SKIPPED_UNREVEALED = 'in an unrevealed collection - it cannot be downloaded until it is revealed'
SKIPPED_PRIVATE = 'the work has been made private'
SKIPPED_UNKNOWN = 'not a work - it may have been deleted, made private, or hidden'
AO3_INFO_METADATA_WRITTEN = 'wrote metadata for {} works to {}'
AO3_INFO_METADATA_INCREMENTAL = 'saving one json file per work as each page is read. if you need to stop\nearly, press ctrl+c rather than closing the window'
AO3_INFO_METADATA_NONE = 'no works found on that page. nothing was written'

PROMPT_LINKS_ONLY = 'save links to a file instead of downloading? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
INFO_LINKS_FILE_WRITTEN = 'wrote {} links to {}'
INFO_NO_LINKS_TO_WRITE = 'no links to write'

UPDATE_PROMPT_INPUT = 'input path to folder containing files you want to check for updates (also checks subfolders)'
UPDATE_INFO_FILES = 'getting list of files'
UPDATE_INFO_NUM_RETURNED = '{} files found'
UPDATE_INFO_URLS = 'getting urls of incomplete fics'
UPDATE_INFO_URLS_DONE = 'finished getting urls of incomplete fics'
UPDATE_INFO_DOWNLOADING = 're-downloading incomplete works'
UPDATE_ACCEPTABLE_FILE_TYPES = ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML']
UPDATE_PROMPT_USE_SAVED_FILE_TYPES = 'use saved list of file types to check for updates? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
UPDATE_PROMPT_USE_SAVED_FOLDER = 'check same folder as last time? ({}/{})'.format(PROMPT_YES, PROMPT_NO)
UPDATE_PROMPT_FILE_TYPE = 'please enter the file type of the files you would like to check for updates. choose from the following (case-sensitive):\n' + '\n'.join(UPDATE_ACCEPTABLE_FILE_TYPES)
UPDATE_INFO_FILE_TYPE = 'added {} to list of file types to check for updates'
UPDATE_INFO_FILTER = 'filtering out works that could not be downloaded on previous runs'

SERIES_INFO_FILES = 'getting list of works belonging to series'
SERIES_INFO_URLS = 'finding all series urls'
SERIES_INFO_NUM = '{} series found'
SERIES_INFO_DOWNLOADING = 'downloading works missing from series'
SERIES_INFO_FILTER = 'filtering out series that could not be downloaded on previous runs'

REDOWNLOAD_PROMPT_FOLDER = 'please enter the folder containing the files you want to re-download (also checks subfolders):'
REDOWNLOAD_PROMPT_FILE_TYPE = 'please enter file type you want to convert from. choose from the following (case sensitive):\n' + '\n'.join(UPDATE_ACCEPTABLE_FILE_TYPES)
REDOWNLOAD_INFO_FILE_TYPE = 'added {} to list of file types to convert from'
REDOWNLOAD_INFO_URLS = 'getting work urls'
REDOWNLOAD_INFO_DONE = 'done getting work urls. {} urls found'

IGNORELIST_INFO_INITIALIZED = f'{IGNORELIST_FILE_NAME} has been added to the main script folder. you can use this file to perma-skip downloading works or series that you know you don\'t want to download. to use this file open it in a text editor (the default text editor for Windows is called Notepad. on Mac, you can use TextEdit) and add the links you want to ignore, one on each line. these should be links to ao3 works or series. other links will be ignored. each link MUST begin with https://archiveofourown.org and be placed at the start of a new line. you may also *optionally* add a comment after each link. comments must begin with a SEMICOLON followed by a SPACE: `; ` and must not contain any newline characters (the entire comment must be on the same line as the link). otherwise, you can write anything you want in the comment. comments are for your personal reference only and are not used by the script.'
IGNORELIST_PROMPT_CHECK_DELETED = 'do you want to check the log file for deleted links and add them to the ignore list automatically? ({}/{})'.format(PROMPT_YES, PROMPT_NO)

INFO_NO_LOG_FILE = 'no log file'
INFO_NO_FILE = 'file does not exist: {}'
INFO_NO_FOLDER = 'folder does not exist: {}'
INFO_SAVED_FOLDER_MISSING = 'previously saved folder no longer exists: {}'
INFO_EXCLUDING_WORKS = 'filtering out works that are already in the downloads folder'
INFO_STARTING_PAGE = 'starting page'
INFO_FINISHED_PAGE = 'finished getting page {}. starting page {} of {}'
INFO_PARSING_LOGS = 'parsing data from log entries with timestamps starting at {} and ending at {}'
INFO_CANCELLED = 'stopped at your request. anything already saved has been kept.'
INFO_LINKS_LIST_CANCELED = '\nlink list generation manually canceled. list may not be complete.'
INFO_NO_WORKS_ON_PAGE = 'ending scrape because no work or series urls were found on page'
INFO_PAGE_LIMIT_REACHED = 'ending scrape because page limit was reached'

MESSAGE_TOO_MANY_REQUESTS = 'ao3 has requested a {} second break\npaused at: {}\nresuming at: {}'
MESSAGE_RESUMING = 'resuming execution'
# a break the user asked for, as opposed to one ao3 demanded. it says where the run got to
# because that is the whole reassurance being offered: nothing was left half done
MESSAGE_HELD = 'paused. the work in progress has finished and nothing new will be started'
MESSAGE_RELEASED = 'resuming'
MESSAGE_INCOMPLETE_FIC = 'found incomplete fic'
MESSAGE_FIC_FILE = 'found fic file'
MESSAGE_SERIES_FILE = 'found work in series'
MESSAGE_RETRY = 'Retrying {} request. Attempt {}. {} seconds until next attempt.'
# said in the run itself, so a request ao3 keeps refusing reads as retries rather than a hang
MESSAGE_RETRYING = 'AO3 answered {} for {} - trying again in {}s (attempt {} of {})'
MESSAGE_RETRYING_UNLIMITED = 'AO3 answered {} for {} - trying again in {}s (attempt {}, no limit set)'
MESSAGE_STILL_WAITING = 'still waiting for AO3 to answer {} ({}s so far)'
MESSAGE_TIMED_OUT_RETRYING = 'AO3 did not answer {} in time - trying again in {}s (timeout {} of {})'
# ao3's own maintenance page, which it serves in place of whatever was asked for
AO3_DOWN_MARKER = 'the archive is down for maintenance'
MESSAGE_AO3_DOWN_RETRY = 'AO3 says it is down for maintenance - checking again in {}s ({} of {})'
ERROR_SETTINGS_NOT_EDITABLE = ('settings.ini can only be changed from the page on a helper running on '
                               'this computer. Edit a hosted copy\'s settings through its deployment.')
ERROR_AO3_DOWN = ('AO3 is down for maintenance, so nothing more can be fetched from it on this run. '
                  'Try again once it is back - https://status.archiveofourown.org')
MESSAGE_SUCCESS = 'Successful {} request with status code {}'
MESSAGE_WELCOME = 'welcome to ao3downloader!\nthe script has been initialized in the following directory:\n\t{}\nif you would like to change any settings, you may do so by entering\n\'{}\' to quit this menu and then editing the file \'{}\'\n(located at the above folder path) before running the script again.\n'
MESSAGE_DOWNLOAD_FOLDER = 'downloads will be saved to:\n\t{}\n'
MESSAGE_EXIT = '\nexiting'
MESSAGE_INI_FILE_CHANGED = 'the options available in ' + INI_FILE_NAME + ' have changed. a copy of the new default settings file has been saved as {}. please review the changes and update ' + INI_FILE_NAME + ' accordingly.'
MESSAGE_INI_DIFFERENCES = 'the following differences were found:\n'
MESSAGE_INI_ADDED_KEY = 'added \'{}\' to \'{}\' section.\n'
MESSAGE_INI_REMOVED_KEY = 'removed \'{}\' from \'{}\' section.\n'
MESSAGE_INI_ADDED_SECTION = '\'{}\' section has been added.\n'
MESSAGE_INI_REMOVED_SECTION = '\'{}\' section has been removed.\n'
MESSAGE_LOGIN_RESET = 'login details have been reset; please try again'

# endregion

# region ao3 scraping

AO3_DOMAIN = 'archiveofourown.org'
AO3_BASE_URL = 'https://' + AO3_DOMAIN

# ao3 serves work files from a host of their own, and the links on a work page redirect
# there. going straight to it skips that redirect. the segment after the work number is a
# slug of the title which ao3 ignores, so a fixed one does just as well - verified against
# the live site: both spellings return byte-identical files.
AO3_DOWNLOAD_BASE_URL = 'https://download.' + AO3_DOMAIN
AO3_DOWNLOAD_SLUG = 'fic'
AO3_LOGIN_URL = AO3_BASE_URL + '/users/login'
AO3_MARK_READ_URL = AO3_BASE_URL + '/works/{}/mark_as_read'

AO3_PROCEED = 'Yes, Continue'
AO3_MARK_READ = 'Mark as Read'

# endregion

# region pinboard scraping

POSTS_FROM_DATE_URL = 'https://api.pinboard.in/v1/posts/all?auth_token={}&fromdt={}'
ALL_POSTS_URL = 'https://api.pinboard.in/v1/posts/all?auth_token={}'
TIMESTAMP_URL = '{}-{}-{}T00:00:00Z'

# endregion

# region error messages

ERROR_INVALID_LINK = 'Not an ao3 link'
ERROR_LOCKED = 'Locked'
ERROR_DELETED = 'Deleted'
ERROR_HIDDEN = 'Hidden'
ERROR_FAILED_LOGIN = 'Failed login: {}'
ERROR_PROCEED_LINK = 'Problem getting proceed link'
ERROR_DOWNLOAD_LINK = 'Problem getting download link'
ERROR_LOG_FILE = 'Problem parsing log file during initial setup'
ERROR_INCOMPLETE_FIC = 'Problem parsing file while checking for incomplete fics'
ERROR_FIC_IN_SERIES = 'Problem parsing file while checking for fics in series'
ERROR_REDOWNLOAD = 'Error processing file for re-download'
ERROR_IMAGE = 'Problem getting image'
RETRY_NOT_FOUND = 'That run is not in this library\'s history any more.'
RETRY_STILL_RUNNING = 'That run is still going - wait for it to finish, or stop it first.'
RETRY_NO_INDEX = 'Only a full scan, quick scan, custom run or collection run can carry on with its indexing.'
RETRY_NO_DOWNLOADS = 'It never got as far as settling which works to check and download.'
RETRY_NO_FAILURES = 'Every work it set out to get arrived - there is nothing that failed to retry.'
# a run that did not finish - stopped, force stopped, interrupted, abandoned, failed or partly
# done - has no failures to retry, but did not get everything either: never say it did
RETRY_NO_FAILURES_UNFINISHED = ('This run did not get everything it set out to get, but nothing it '
                                'tried to download failed - so there is nothing for this choice to '
                                'retry. Choose another way to retry it.')
RETRY_FAILED_WRONG_ACTION = 'Only a scan, a collection run or a fic run can retry just the works it could not get.'
RETRY_PARTIAL_DONE = ('It reached the end, so there is nothing to carry on from - start its '
                      'indexing or its downloads from the top, or retry just the works it could '
                      'not get.')
RETRY_WARN_INDEX_FAILED = ('Some of its indexing failed, so it may have missed fics - and a fic '
                           'that was not indexed cannot be downloaded. We strongly recommend '
                           'starting its indexing from the top.')
RETRY_WARN_DOWNLOADS_FAILED = ('Its indexing finished, but some fics or formats could not be '
                               'downloaded. We strongly recommend retrying just the works it '
                               'could not get.')
RETRY_ALL_DONE = ('It finished both its indexing and its downloads, so there is nothing to carry '
                  'on from - start its indexing or its downloads from the top, or retry just '
                  'the works it could not get.')
RETRY_NO_FIC_LINKS = 'This run is from before fic runs saved the fics they were given - start it again from its button.'
AO3_INFO_RETRYING = 'retrying {} from {}, {} ({})'
AO3_INFO_RETRY_TOP = 'the top'
AO3_INFO_RETRY_INDEX = 'where its indexing stopped'
AO3_INFO_RETRY_REINDEX = 'the start of its indexing'
AO3_INFO_RETRY_DOWNLOADS = 'where its downloads stopped'
AO3_INFO_RETRY_REDOWNLOAD = 'the start of its downloads'
AO3_INFO_RETRY_FAILED = 'the {} works it could not get'
AO3_INFO_FORMAT_DONE_EARLIER = '{}: already downloaded for work {} by the attempt this run carries on from'
AO3_INFO_INDEX_GAP = 'indexing stopped: {} could not be read at page {}{} - {}. {}'
REASON_WORDS_MAINTENANCE = 'AO3 was down for maintenance'
REASON_WORDS_STATUS = 'AO3 answered with status {}'
REASON_WORDS_CONNECTION = 'AO3 could not be reached'
REASON_WORDS_NO_DATA = 'the page AO3 served had nothing on it that could be read'
AO3_INFO_INDEX_GAP_LISTING = 'your bookmarks'
AO3_INFO_INDEX_GAP_COLLECTION = 'the {1} of collection {0}'
AO3_INFO_INDEX_GAP_READ = 'pages {} to {} were indexed ({} works).'
AO3_INFO_INDEX_GAP_NONE_READ = 'no page was indexed before it.'
AO3_INFO_INDEX_GAP_DATE = 'the last page read reached works {} on {}.'
AO3_INFO_INDEX_GAP_WORK = 'indexing stopped for work {}: its page could not be read ({})'
ERROR_LINKS_LIST = 'Error encountered while getting links list. List may not be complete.'
ERROR_HTTP_REQUEST = 'Unrecoverable error encountered while making web request'
ERROR_LISTING_UNREADABLE = 'ao3 answered with a page that is not a listing - nothing on it could be indexed'
ERROR_ALL_INDEXING_FAILED = 'Every part of its indexing failed, and nothing was downloaded.'
ERROR_INVALID_STATUS_CODE = 'Request failed with status code {}'
ERROR_TIMEOUT = 'Request exceeded the timeout limit of {} seconds'
ERROR_CLOUDFLARE = 'Cloudflare challenge or error page detected'
ERROR_MARK_READ = 'Problem marking work as read'
ERROR_MARK_READ_SKIP = 'Skipping marking work as read; could not find form input'
ERROR_PDF_PARSE = 'Problem parsing pdf; skipping update check'
ERROR_SERIES_LINK = 'Expected series information, but could not find it'
ERROR_WORK_BLURB = 'Could not find work metadata in list'
ERROR_METADATA_BLURB = 'Problem parsing work metadata from listing'
ERROR_METADATA_SAVE = 'Problem saving work metadata file'
ERROR_COLLECTIONS = 'Error encountered while syncing collections. Some may be missing.'
ERROR_NOT_A_COLLECTION = 'That is not a link to an ao3 collection. It should look like https://archiveofourown.org/collections/somename'
ERROR_SESSION_EXPIRED = (
    'AO3 has stopped recognising your login, so the rest of this run would fail. '
    'Everything downloaded so far has been kept - log in again and start the same run, '
    'and it will carry on from what is still missing.')
ERROR_UPDATE_DURING_RUN = 'A run is in progress. Updating restarts the app, which would stop it - update once it is complete.'
ERROR_RUN_DURING_UPDATE = 'The app is updating itself, and will restart in a moment. Start the run once it is back.'
ERROR_RUN_IN_PROGRESS = 'A run is already in progress. Wait until it is complete to start a new one - the History tab shows it.'
ERROR_BACKGROUND_NEEDS_DROPBOX = 'A background run needs a library in Dropbox, and this request came without a Dropbox sign-in. Sign in to Dropbox and try again.'
ERROR_NOT_WORK_LINKS = ('These are not AO3 works: {}. Paste work links like '
                        'https://archiveofourown.org/works/1234567, or work numbers, separated by '
                        'new lines, commas, spaces or semicolons.')
ERROR_NO_WORK_LINKS = 'Paste at least one AO3 work link or work number.'
ERROR_TOO_MANY_WORK_LINKS = 'That is {} fics - one run takes at most {}. Split them into smaller runs.'
ERROR_NOT_A_WORK_LINK = 'That is not an ao3 work. Paste a link like https://archiveofourown.org/works/1234567, or just the work number.'
ERROR_COLLECTION_PROFILE = 'Problem reading a collection profile page'
ERROR_COLLECTION_ITEMS = 'Problem reading the items in a collection'
ERROR_COLLECTION_SAVE = 'Problem saving collection file'
ERROR_METADATA_WORK_DATES = 'Problem getting publication dates from work page'
ERROR_METADATA_NOT_A_LISTING = 'The {} download type needs a link to a listing of works, such as bookmarks, search results, or a series. It cannot be used with a link to a single work.'

FAILED_LOGIN_NOT_FOUND = 'could not retrieve login page'
FAILED_LOGIN_NO_RESPONSE = 'could not get a response from login request'
FAILED_LOGIN_INVALID_CREDENTIALS = 'invalid username or password'
FAILED_LOGIN_NO_FORM = 'could not find login form. page title was: {}'
FAILED_LOGIN_NO_TOKEN = 'could not find authenticity token field in login form'
FAILED_LOGIN_NO_TOKEN_VALUE = 'authenticity token field was empty'

# endregion


# region resuming an earlier run - see helper_files/RESUMING.md

AO3_INFO_RESUMING = 'resuming the {} that started {} - it stopped at: {}'
AO3_INFO_RESUME_NO_STEP = 'before its first step'
AO3_INFO_RESUME_ANSWER = 'using the answer the earlier attempt was given: {}'
AO3_INFO_ABANDONED = 'this background run was left paused for {} minutes, so the helper has abandoned it. everything it saved is kept - resume it from the History tab, or start the same run again and it carries on from what is still missing.'
AO3_INFO_BACKGROUND_ANSWER = 'using the answer given before this background run started: {}'
AO3_INFO_AO3_ZONE = "AO3's dates are read as dates in {}"
AO3_INFO_AO3_ZONE_MISSING = "this computer cannot look up the time zone {}, so AO3's dates are read as dates in UTC"
AO3_INFO_QUESTION_NOT_ASKED = 'settings.ini says to take the default here without asking (QuestionTimeoutMinutes is 0), so it takes: {}'
AO3_INFO_QUESTION_TIMED_OUT = 'nobody answered in time (QuestionTimeoutMinutes), so it takes the default: {}'
AO3_INFO_BACKGROUND_DEFAULT = 'this background run was not told what to do here, so it takes the default: {}'
# a retry carrying on downloading what its earlier attempt indexed: re-read each work first?
AO3_INFO_RETRY_REREAD_ASK = ('these {} works were indexed by the earlier attempt - waiting for you to choose '
                             'whether to read each again from AO3 before downloading (one request a work)...')
AO3_INFO_RETRY_REREAD_SKIPPED = ('downloading from the index as the earlier attempt left it - a work AO3 has '
                                 'updated since is named with the date the index has')
AO3_INFO_RETRY_REREADING = 'reading each of these {} works again from AO3 before downloading'
AO3_INFO_RESUME_SCOPE = ('the earlier attempt had finished indexing - checking and downloading '
                         'its {} works')
AO3_INFO_RESUME_WALK_DONE = 'the earlier attempt finished this walk - taking its works from the index'
# a collection run picking up where it left off
AO3_INFO_RESUME_COLLECTION_DONE = 'collection {}: finished by the earlier attempt - taking its works from the index'
AO3_INFO_RESUME_COLLECTION_PAGE = 'collection {}: carrying on through its {} from page {}, where the earlier attempt got to'
AO3_INFO_RESUME_COLLECTION_SHORT = ('collection {}: found {} works of the {} it holds - some have moved to '
                                    'the front since, so reading pages 1 to {} again')
AO3_INFO_RESUME_WALK_AGAIN = ('walking this listing again from the first page: the earlier attempt '
                              'did not save a date to carry on from')
# a retry checking what its earlier attempt says it did, before carrying on from it
AO3_INFO_RETRY_FIC_DONE = '({}/{}) work {}: saved in every format by the earlier attempt - passed over'
AO3_INFO_RETRY_CHECK_INDEX = 'checking the {} works the earlier attempt indexed still have their index files'
AO3_INFO_RETRY_INDEX_OK = 'every one of them does'
AO3_INFO_RETRY_INDEX_MISSING = '{} have no index file any more, so they are indexed again from their own pages: {}'
AO3_INFO_RETRY_REINDEXING = 'indexing work {} again'
AO3_INFO_RETRY_CHECK_DOWNLOADS = 'checking the files the earlier attempt saved for {} works are still there, dated as the index says'
AO3_INFO_RETRY_DOWNLOADS_OK = 'every one of them is'
AO3_INFO_RETRY_DOWNLOADS_DROPPED = '{} files will be fetched again'
AO3_INFO_RETRY_FETCH_AGAIN = 'work {} {}: fetching again - {}'
AO3_INFO_RETRY_NO_ENTRY = 'it has no index entry to compare it with'
AO3_INFO_RETRY_FILE_MISSING = 'the file is not in the folder'
AO3_INFO_RETRY_FILE_DATE = 'the file is dated {}, the index {}'
AO3_INFO_RETRY_NO_DATE = 'no date'
AO3_INFO_RETRY_INDEX_REWRITTEN = 'work {}: its index entry was rewritten since by another run ({}) - its files are checked against that'
AO3_INFO_RESUME_FROM_CEILING = 'nothing after {} is wanted from this listing, so the walk starts there'
AO3_INFO_RESUME_LOOKING = 'looking for where the earlier attempt stopped (fics dated {1}): page {0}'
AO3_INFO_RESUME_FOUND = 'the first fic dated {1} or earlier is now on page {0} - carrying on from there'
AO3_INFO_RESUME_ANCHOR_LOST = ('nothing in the listing is now dated as far back as where the '
                               'earlier attempt stopped, so this walk starts again from the first page')
AO3_INFO_RESUME_SERIES_DONE = 'the earlier attempt walked every marked series already'
AO3_INFO_RESUME_NON_BOOKMARKS_DONE = 'the earlier attempt already checked every non-bookmark'
AO3_INFO_RESUME_FLOOR = 'measuring back to {}, as the earlier attempt did'
AO3_INFO_RESUME_CEILING = ('keeping works ao3 updated up to {}, when the first attempt started: '
                           '{} of them')
AO3_INFO_RESUME_UPDATE_DONE = 'the earlier attempt already finished {} of these fics'

RESUME_NOT_FOUND = 'That run is not in this library\'s history.'
RESUME_WRONG_ACTION = 'Only full scans, quick scans, custom runs and collection runs can be resumed.'
RESUME_NO_LINK = ('This run is from before collection runs saved their link, so it cannot be '
                  'resumed - start it again from its button, with the link.')
RESUME_SLICE = ('A custom run over a slice of your bookmarks listing cannot be resumed: '
                'bookmarks added or removed since move every page, so the same page numbers '
                'no longer hold the same bookmarks.')
RESUME_FINISHED = 'That run finished - there is nothing to resume.'
RESUME_STILL_RUNNING = 'That run is still going.'
RESUME_TOO_OLD = ('That run is from before runs saved their progress, so there is nothing to '
                  'pick up from. Start it again instead.')
RESUME_ALREADY_RESUMED = 'It has already been resumed once.'
RESUME_NEWER_SCAN = ('A full or quick scan has finished since, so resuming this one will mostly '
                     'go over ground already covered.')

# endregion
