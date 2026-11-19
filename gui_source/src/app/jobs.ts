import { Injectable, signal } from '@angular/core';
import { useNamePattern } from './naming';
import {
  LibraryStore,
  StorageRequest,
  answerStorage,
  noteRunEnded,
  readRunHistory,
  readUnsettledRuns,
  runHistoryBatches,
} from './library-store';
import { HelperConnection } from './helper-connection';
import { DropboxHandover } from './dropbox';
import type { AppStatus } from './updates';

/**
 * Talks to the local helper (ao3downloader.server) that actually performs downloads.
 *
 * The browser cannot do this work itself: ao3 sends no CORS headers, a page cannot hold an
 * ao3 login session, and the update scan has to read ebook files on disk. So the helper runs
 * the same python the console menu runs, and this service drives it.
 */

export type JobAction =
  | 'bookmarks'
  | 'update'
  | 'collections'
  | 'collection'
  /** newest bookmarks only, stopping at the first one already indexed */
  | 'new'
  /** new bookmarks, then the unfinished ones, then the formats still missing */
  | 'sync'
  /** one fic, by link or work number */
  | 'work'
  /** several fics, pasted as links or work numbers */
  | 'works'
  /** works whose files are in the library with no index entry, found by the page */
  | 'import'
  /** the full scan with its parts made optional */
  | 'custom'
  /** a full scan that stops at the works ao3 has not touched since the last run */
  | 'quick';

/** what settings.ini says, so a run can show what it is working from */
export interface ServerSettings {
  /** which settings.ini is in force - not obvious, and worth being able to check */
  file: string;
  extraWaitTime: number;
  /** how every downloaded file is named. fixed, not a setting - shown so it can be read */
  fileNamePattern: string;
  fileNameLength: number;
  /** the naming rule as an actual name, built through the same truncation */
  fileNameExample: string;
  maxRetries: number;
  maxTimeouts: number;
  debugLogging: boolean;
  /** whether the helper prints every request and every run line to its own console */
  consoleLogging?: boolean;
  /** minutes a paused background run is kept before the helper abandons it; 0 is never */
  pausedRunTimeoutMinutes?: number;
  /** minutes a question waits for its answer before taking its default; 0 is at once */
  questionTimeoutMinutes?: number;
  /** the same, for a question about a file without the app's own date (1 by default) */
  guessedDateTimeoutMinutes?: number;
  /** the questions asked once per work that have a wait of their own, in minutes, by name */
  questionTimeouts?: Partial<Record<OwnWaitQuestion, number>>;
  /** 'nobody's here': once one goes unanswered, the rest like it take their default at once */
  nobodyHere?: boolean;
  /** what each question answers itself with when nobody answers it, from settings.ini */
  answerDefaults?: Partial<Record<DefaultName, string>>;
}

export interface ServerConfig {
  username: string;
  filetypes: string[];
  /** ticked and locked: produced whatever the request says */
  forced: string[];
  /** ticked when the dialog opens, but free to untick */
  defaults: string[];
  settings?: ServerSettings;
  /** only the Windows, Mac or Linux app: its version, and whether it can update itself */
  app?: AppStatus;
}

/**
 * What a run window works from until the helper has answered - the helper's own lists
 * (`strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA`, `FORCED_FILETYPES`,
 * `DEFAULT_FILETYPES`), so the options and file types can be chosen while a hosted helper
 * wakes. The run is never started on it: Start waits for the helper's real answer.
 */
export const BUILT_IN_CONFIG: ServerConfig = {
  username: '',
  filetypes: ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML', 'JSON'],
  forced: ['JSON'],
  defaults: ['JSON', 'HTML'],
};

/** the questions the console menu asks after the file types */
export interface JobOptions {
  /**
   * Go without logging in to AO3. Only the runs pointed at fics by hand offer it; works only
   * a login can see then fail, and FicHub is offered for them at the end.
   */
  skipLogin?: boolean;
  /** page to begin on; 1 is the start of the listing */
  start: number;
  /** page to stop on; 0 means every page */
  pages: number;
  series: boolean;
  images: boolean;
  workdates: boolean;
  /**
   * Fetch every requested format again, whether or not the copy held is behind.
   *
   * The answer to a file that is damaged or truncated - something no version check can
   * see, because the name and the date are both right and only the bytes are wrong.
   */
  overwrite: boolean;
  /**
   * An import: replace a copy you have when AO3 has a newer version than the date in its
   * name. Off, an import fetches only the formats you do not have. The import's alone.
   */
  replaceOutdated?: boolean;
  /** an import: the works among its links only looked up for their index entry */
  indexOnly?: string[];
  /** an import: files with no date in their names to replace with AO3's latest version, by name */
  repair?: string[];
  /** an import: FicHub may repair a file AO3 would not give, when as new as the date its name suggests */
  repairFicHub?: boolean;
  /** an import: when the date guessed from the file's name is no later than FicHub's */
  repairFicHubOlder?: boolean;
  /** an import: and when no date can be guessed from the file's name */
  repairFicHubUndated?: boolean;
  /** an import: instead, keep such a file and name it with FicHub's date, never over another */
  repairFicHubRename?: boolean;
  /** an import: FicHub's choice keeps to the date guessed from each file's name */
  repairFicHubCheck?: boolean;
  /** an import: where AO3 has the work, only name the file with AO3's date */
  repairRenameOnly?: boolean;
  /**
   * Check every non-bookmark in the index for updates too - the works it holds only because
   * something else led a run to them, such as another work's series. Not narrowed by a date
   * range or a floor. The three scans only, and only while they index.
   */
  nonBookmarks?: boolean;
  /**
   * A collections run: index every work in the collections as it crawls them, and download
   * those as a scan would. The two collection runs only.
   */
  collectionWorks?: boolean;
  /**
   * A collections run: read each collection's subcollections, or its parent, as well - and
   * theirs in turn, however far removed, each collection at most once.
   */
  subcollections?: boolean;
  parentCollections?: boolean;
  /**
   * Whether to read AO3's listing at all, or work from what the index already holds.
   *
   * Only a custom run offers this. It defaults to true everywhere else: a run that quietly
   * skipped indexing would judge everything against however stale the index happened to be.
   */
  reindex: boolean;
  /** skipping the indexing, look every indexed work up on AO3 (a custom run's alone) */
  recheck?: boolean;
  /**
   * Whether to cover a date window instead of a slice of the listing.
   *
   * The two are alternatives rather than settings that combine, so `dates` decides which of
   * `start`/`pages` and `dateFrom`/`dateTo` the helper reads at all.
   */
  dates: boolean;
  /**
   * A custom run's order for its slice of pages or its date range: by date bookmarked or by
   * date updated. Empty is each shape's own - pages by date bookmarked, a range by date updated
   */
  order?: '' | 'bookmarked' | 'updated';
  /** inclusive ends of that window, YYYY-MM-DD; empty means no limit at that end */
  dateFrom: string;
  dateTo: string;
  /**
   * A quick scan's chosen floor: the id of an earlier completed scan to measure back to.
   *
   * Only the id is sent. The helper reads the date off that run's own record and refuses
   * one that is not a valid floor, so a request can never invent a date.
   */
  floorRun: string;
  /**
   * The earlier run to pick up where it left off, by id. The helper reads that run's own
   * record and takes its workflow, file types and options from it - see helper_files/RESUMING.md.
   */
  resume?: string;
  /** how that run is retried - the helper's RETRY_MODES */
  retryMode?: RetryMode;
}

/** what to do about downloaded files that carry no date, asked part way through a run */
export type UndatedChoice = 'stamp' | 'refresh' | 'skip';

/**
 * How far back a quick scan should reach when no run qualifies as a floor.
 *
 * 'since' measures back to the day the index was last written; 'full' reads the whole
 * listing, which is what it does when there is nothing to go on at all.
 */
export type QuickFloorChoice = 'since' | 'full';

/** what to do about older copies of a work beside the newest one */
export type DuplicatesChoice = 'newest' | 'leave';

/** whether to ask FicHub for the works AO3 would not give us - yes, by default */
export type FicHubChoice = 'yes' | 'no';

/** anything a run may be answered with; the run only reads its own question's replies */
/** a copy of a work with no earlier index entry: replace just the recommended copies */
export type UnindexedCopyChoice = 'recommended' | 'both';
export type AnswerChoice = UndatedChoice | QuickFloorChoice | DuplicatesChoice | FicHubChoice | UnindexedCopyChoice;

/** one older copy a run marked for removal, and what became of it */
export interface RunRemoval {
  id: string;
  filetype: string;
  file: string;
  /** the newest copy, which is the one kept */
  keeping: string;
  status: 'pending' | 'removed' | 'kept';
  /** why it was kept, when it was */
  error?: string;
}

/**
 * Where a step has got to.
 *
 * 'skipped' is not 'failed'. A run with no unfinished fics skips that step and nothing has
 * gone wrong, so the two must not look alike.
 */
export type StepStatus = 'waiting' | 'running' | 'done' | 'skipped' | 'failed' | 'earlier';

/** one step of the checklist a run publishes before it starts */
export interface RunStep {
  id: string;
  label: string;
  status: StepStatus;
}

/**
 * How a past run ended.
 *
 * `running` is also what an **interrupted** run is left as: the record is written when a
 * run starts, and a run killed mid-flight never gets to write its ending. The page turns
 * that into `interrupted` once the helper confirms it is not working on it - see
 * `Jobs.settleInterrupted`.
 */
/**
 * How a run ended. `abandoned` is a background run the helper ended because it was left
 * paused past `PausedRunTimeoutMinutes` - ended the way a stop ends one. `partial` reached its end
 * but some indexing failed (`indexFailures` says where) or some fic or format could not be
 * downloaded - never a floor for a quick scan. `failed` includes a run whose indexing failed
 * everywhere it tried and got nothing.
 */
export type RunStatus =
  | 'running'
  | 'success'
  | 'partial'
  | 'failed'
  | 'stopped'
  | 'interrupted'
  | 'abandoned';

/**
 * One place a run's indexing broke off. A listing or a collection's listing says which pages
 * were read (`firstPage` to `lastPage`, null when none were), the page that failed, and how far
 * back in date it got; a fic run's fic says which work's own page would not read.
 */
export interface IndexGap {
  kind: 'listing' | 'collection' | 'work';
  /** which of the run's walks: 'all', 'bookmarked' or 'updated' */
  walk?: string;
  listing?: string;
  /** the date the listing is in order of: 'bookmarked', 'updated', or '' for ao3's default */
  sort?: string;
  collection?: string;
  /** a collection's 'works' or 'bookmarked items' */
  items?: string;
  firstPage?: number;
  lastPage?: number | null;
  failedPage?: number;
  totalPages?: number | null;
  works?: number;
  reachedBookmarked?: string;
  reachedUpdated?: string;
  id?: string;
  link?: string;
  error: string;
  /** why: 'maintenance', 'status' (with `status`), 'connection', 'no-data' or 'other' */
  reason?: string;
  status?: number;
}

/** how a run can be retried - see the helper's RETRY_MODES */
export type RetryMode = 'top' | 'reindex' | 'index' | 'redownload' | 'downloads' | 'failed';

export interface RetryChoices {
  modes: { mode: RetryMode; available: boolean; reason: string }[];
  /** the way that picks up from its first step that did not finish; '' when none can */
  default: RetryMode | '';
  /** how many works it could not get */
  failedWorks: number;
}

/** something a run stopped to ask, what was answered, and what came of it */
export interface RunChoice {
  at: string;
  question: string;
  choice: string;
  date?: string;
  /** how many works the question was about */
  count?: number;
  /** how many files those works held between them - a work in two formats is two files */
  files?: number;
  /** the work numbers the question was about */
  works?: string[];
  /** the formats a per-work question was about */
  formats?: string[];
  /** the files given a date, when that was the answer */
  renamed?: { id: string; from: string; to: string }[];
  /**
   * How it was answered: by you, or a default and why. Missing on records from before it was
   * kept. `answered` you chose; `timed-out` nobody answered in time; `not-asked` settings.ini
   * says to take the default at once; `background-default` a background run not told;
   * `up-front` a background run told before it started; `earlier` an earlier attempt's answer;
   * `stopped` the run was stopped while it waited; `always` an answer you chose to always
   * use for that case; `nobody-answering` an earlier one like it went unanswered, so this
   * took its default at once.
   */
  how?: string;
  /** on an `unindexed-copy` answer: what was recommended, where the incoming version was
   *  from, and the formats replaced */
  recommended?: string;
  source?: string;
  replaced?: string[];
  /** on an `unindexed-copy` answer of Keep both: the copies a new version was saved beside */
  keptBoth?: string[];
  /** on an `inferred-date` answer: which of the six cases it was, the file and the dates */
  scenario?: Scenario;
  fileNames?: string[];
  fileDates?: Record<string, string>;
}

/** one past run, as the helper wrote it down */
export interface RunHistory {
  /** on a floor offered to a quick scan: the works a partly finished one could not download */
  missingDownloads?: string[];
  file: string;
  id: string;
  action: string;
  actionName: string;
  started: string;
  finished: string | null;
  status: RunStatus;
  filetypes: string[];
  options: Record<string, unknown>;
  /** the link the run was pointed at - a collection, or a fic - absent on older runs */
  url?: string;
  /** the ao3 account it logged in as - never the password; absent on older runs */
  username?: string;
  reindexed: string[];
  downloaded: string[];
  updated: string[];
  choices: RunChoice[];
  failures: WorkFailure[];
  skipped: WorkFailure[];
  /** new copies downloaded while the old copy could not be deleted - absent on older runs */
  keptCopies?: WorkFailure[];
  /** works AO3 would not give us that FicHub did - absent on older runs */
  rescued?: RescuedWork[];
  /** formats taken from FicHub that may be older cached copies - absent on older runs */
  fichubOlder?: FicHubOlder[];
  /** Resolve issues' repairs a name clash stopped - absent on older runs */
  repairClashes?: RepairClash[];
  /** older copies marked for removal, and what became of each - absent on older runs */
  removals?: RunRemoval[];
  error: string;
  /**
   * The moment the login succeeded - what a later quick scan measures back to. A resumed
   * run carries its first attempt's. Absent on older runs, whose `started` stands in.
   */
  baseline?: string | null;
  /** the run this one picked up from, and the first attempt of that chain */
  resumes?: string | null;
  resumesFirst?: string | null;
  /** the run that later picked this one up */
  resumedBy?: string;
  /** carried on in the helper after the page closed - absent on older runs */
  background?: boolean;
  /** the helper it was started on, as the page named it - absent on older runs */
  helper?: string;
  /** how many lines of the run window's account its history file holds, and how many it dropped */
  logLines?: number;
  logTrimmed?: number;
  /** its log was taken out, being older than the most recent runs - how many lines it had */
  logPruned?: number;
  /** where its indexing broke off - absent on older runs */
  indexFailures?: IndexGap[];
  /**
   * How far the run got, as it saved it - see helper_files/RESUMING.md. `stepPlan` is the steps it set out
   * to take, `steps` how each had gone when it last saved.
   */
  progress?: {
    step?: string;
    stepLabel?: string;
    stepPlan?: [string, string][];
    steps?: Record<string, string>;
  } & Record<string, unknown>;
}

/** a run that has ended, as offered for retrying */
export interface RetryableRun extends RunHistory {
  retry: RetryChoices;
  /** things worth knowing before retrying it */
  warnings: string[];
}

/** when a run's reach began: its baseline, or its start on runs from before baselines */
export function baselineOf(run: RunHistory): string {
  return run.baseline || run.started;
}

/**
 * Whether a json file read out of the downloads folder is one of these run records.
 *
 * They live in a `runs` subfolder, but a folder read through the File System Access API
 * arrives **flat** - the paths are gone - so the only thing left to tell them apart by is
 * their shape. Without this a run record is rendered as a bookmark: `flattenRecord` hands
 * back anything carrying an `id`, and a run record has one.
 *
 * Three fields rather than one, because `id` alone is what caused the problem and `action`
 * alone is a word a fic could plausibly use. No work or collection record carries all of
 * `action`, `status` and `started`.
 */
export function isRunRecord(parsed: unknown): boolean {
  if (!parsed || typeof parsed !== 'object') return false;
  const record = parsed as Record<string, unknown>;
  return (
    typeof record['action'] === 'string' &&
    typeof record['status'] === 'string' &&
    typeof record['started'] === 'string'
  );
}

/** a work the run could not download */
/** a work AO3 would not give us that FicHub did, and the formats that came from it */
export interface RescuedWork {
  id: string;
  link: string;
  title: string;
  downloaded: string[];
}

/** a format taken from FicHub, there being no file of it, though FicHub's copy is dated
 *  before the last known update date for the work - kept, but maybe an older cached copy */
/** a file Resolve issues asked to repair from AO3 or FicHub, not repaired because the name it
 *  would be given is already another file's - both were kept as they are */
export interface RepairClash {
  id: string;
  link: string;
  /** e.g. 'EPUB' */
  format: string;
  /** the file as it is named, and kept */
  file: string;
  /** the name it would have been given, already taken */
  wanted: string;
  /** 'AO3' or 'FicHub' */
  site: string;
}

export interface FicHubOlder {
  id: string;
  link: string;
  title: string;
  formats: string[];
  /** FicHub's date, YYYY-MM-DD */
  fichub: string;
  /** the last known update date, YYYY-MM-DD */
  latest: string;
  /** the format whose file name carries `latest`, or '' when it is the index's */
  latestFrom: string;
  /** formats whose file of yours FicHub's copy replaced, each with that file's own date ('' for
   *  none) - absent on older runs */
  replaced?: Record<string, string>;
}

export interface WorkFailure {
  /** the ao3 work number, when the link had one in it */
  id: string | null;
  link: string;
  error: string;
  /**
   * What the listing called it, when there is anything to call it.
   *
   * Only skipped bookmarks carry this. A bookmark of a deleted work has no number and no
   * link to identify it by, so without the title there would be nothing on the row at all.
   */
  title?: string;
  /** a kept copy only: the name of the file that was just downloaded */
  file?: string;
  /** a kept copy only: the name of the older copy still on disk */
  old?: string;
}

export interface JobEvent {
  type: string;
  text?: string;
  /** a `message` event's: when the helper said it, in UTC */
  at?: string;
  /** on a `page` event: position within the slice being fetched, which drives the bar */
  page?: number;
  total?: number;
  /** on a `page` event: the same page's actual number in the listing, for the wording */
  listingPage?: number;
  listingTotal?: number;
  /**
   * On a `page` event: this page is about to be fetched rather than finished.
   *
   * The fetch is the slow part of indexing, so the run says what it is asking for before
   * it asks - a caption written only once a page is in describes the wrong page for as
   * long as the next one takes to arrive.
   */
  fetching?: boolean;
  works?: number;
  done?: number;
  title?: string;
  /** which format is being fetched for the work named in `title` */
  filetype?: string;
  phase?: string;
  /** which stage of the run has just started, on a `phase` event */
  name?: string;
  /** who the helper signed in as, on an `authenticated` event */
  username?: string;
  /** on a `refresh` event: works ao3 has updated since they were saved */
  stale?: number;
  /** on a `refresh` event: works saved before file names carried a date */
  undated?: number;
  /** on a `refresh` event: existing files this run gave a date to, by renaming them */
  stamped?: number;
  /** on a `failures` event: the works that would not download */
  failures?: WorkFailure[];
  /** on a `skipped` event: bookmarks that were never works, and why each one was not */
  skipped?: WorkFailure[];
  /** on a `keptCopies` event: new copies downloaded while the old copy could not be deleted */
  keptCopies?: WorkFailure[];
  /** on a `rescued` event: works AO3 would not give us that FicHub did */
  rescued?: RescuedWork[];
  /** on a `fichubOlder` event: formats taken from FicHub that may be older cached copies */
  fichubOlder?: FicHubOlder[];
  /** on a `repairClashes` event: Resolve issues' repairs a name clash stopped */
  repairClashes?: RepairClash[];
  /** on a `question` event: the work numbers it is about, where it names them */
  ids?: string[];
  /** on a `steps` event: the checklist this run intends to work through */
  steps?: { id: string; label: string }[];
  /** on a `step` event: which step changed, and to what */
  id?: string;
  status?: StepStatus;
  /** on a `question` event: which question is being asked, and how many works it concerns */
  count?: number;
  /** on a `question` event: how many files those works hold between them */
  files?: number;
  /** on a `notRemoved` event: older copies marked for removal that are still there */
  notRemoved?: WorkFailure[];
  choices?: string[];
  /** on a `question` event: the date the question is offering, where it has one */
  date?: string;
  /** on a per-work question: the formats it is about */
  formats?: string[];
  /** on an `overwrite-older` question: the date of the copy on disk, newer than `date` */
  newer?: string;
  /** on an `unindexed-copy` question: the date read from each copy's name ('' for none),
   *  where the incoming version is from, the answer recommended and why */
  fileDates?: Record<string, string>;
  source?: string;
  /** 'yes', 'no', or 'recommended' when only some copies are worth replacing */
  recommended?: string;
  recommendedFormats?: string[];
  /** on an `inferred-date` question: which of the six cases it is, and each file's whole name */
  scenario?: Scenario;
  fileNames?: Record<string, string>;
  /** the same format's other copies, beside the nominated file for comparison - kept whatever is answered */
  otherFiles?: Record<string, string[]>;
  /** on an `unindexed-copy` question: the copies Keep both saves a new version beside */
  bothFormats?: string[];
  /** why each copy is or is not recommended for replacing */
  reasons?: Record<string, string>;
  overwriting?: boolean;
  /** a question's: the answer it takes if nobody gives one, and after how many minutes */
  default?: string;
  timeoutMinutes?: number;
  seconds?: number;
  until?: string;
  error?: string;
  /**
   * On a `failed` event: whether AO3 stopped recognising the login mid-run.
   *
   * Flagged by the helper rather than left to be guessed from the error text - it is not a
   * crash, and there is a specific thing to do about it.
   */
  sessionExpired?: boolean;
  folder?: string;
  action?: string;
  filetypes?: string[];
  options?: JobOptions;
  cancelled?: boolean;
  /** on `finished`: a background run the helper ended because it was left paused too long */
  abandoned?: boolean;
}

export interface StartRequest {
  action: JobAction;
  filetypes: string[];
  options: JobOptions;
  username: string;
  password: string;
  /** the collection to index, for the one action that works from a link */
  url?: string;
  /**
   * Carry on in the helper with the page closed - see `dropbox_library.py`. Needs `dropbox`,
   * since a folder on this computer can only be reached through the page.
   */
  background?: boolean;
  /** a background run's answers to the questions it may meet, by question name */
  answers?: BackgroundAnswers;
  /** a background run's way into the library; sealed with the login when there is a key */
  dropbox?: DropboxHandover | null;
  /**
   * What unanswered questions take, and after how many minutes, from this browser's User
   * settings - sent only by a page whose helper's settings.ini it cannot edit (a hosted copy)
   */
  answerDefaults?: Partial<Record<DefaultName, string>>;
  questionTimeoutMinutes?: number;
  /** a hosted copy's wait for a question about a file without the app's own date */
  guessedDateTimeoutMinutes?: number;
  /** a hosted copy's wait for each question asked once per work that has its own */
  questionTimeouts?: Partial<Record<OwnWaitQuestion, number>>;
  /** a hosted copy's 'nobody's here' (`NobodyHereTakeDefaults`) */
  nobodyHere?: boolean;
  /** a hosted copy's own run-log length, and whether old runs' logs are taken out (`run-logs.ts`) */
  runLogMaxLines?: number;
  trimOldRunLogs?: boolean;
  /** answers you chose to always use, by case - taken without asking (User settings) */
  alwaysAnswers?: Partial<Record<Scenario, 'yes' | 'no' | 'both'>>;
  /** the zone AO3 shows this person's dates in (User settings; the browser's own by default) */
  ao3TimeZone?: string;
}

/** the questions asked once per work with a wait of their own (`TIMEOUT_SETTING_FOR`, bar inferred-date) */
export type OwnWaitQuestion = 'overwrite-older' | 'unindexed-copy';

/** the questions a run can stop to ask, by the name the helper gives them */
export type QuestionName =
  'quick-floor' | 'fichub' | 'overwrite-older' |
  'unindexed-copy' | 'inferred-date' | 'retry-reread';

/**
 * The six cases of a file whose name has no date written the app's way, asked about one work
 * at a time: where the incoming version is from, and what the date guessed from the name says
 * (older than it, the same or newer, or none can be read). Each has its own default, and may
 * have an answer you chose to always use (`ao3.alwaysAnswers`).
 */
export type Scenario =
  'ao3-older' | 'ao3-newer' | 'ao3-unknown' | 'fichub-older' | 'fichub-newer' | 'fichub-unknown';

/** what an answer can be kept for, to be taken without asking (the helper's `ALWAYS_KINDS`) */
export type AlwaysKind = Scenario | 'retry-reread';

/** what has a default answer: a question, or one of the cases of `inferred-date` */
export type DefaultName = QuestionName | Scenario;

/** answers given before a background run starts, since nobody will be there to give them */
export type BackgroundAnswers = Partial<Record<QuestionName, { choice: AnswerChoice; date?: string }>>;

/** a run the helper is working on right now */
export interface ActiveRun {
  id: string;
  action: JobAction;
  actionName: string;
  /** carried on in the helper, with or without a page - one the page can attach to */
  background: boolean;
  started: string;
  /** paused by the user */
  paused: boolean;
  /** when a paused background run will be abandoned unless resumed, or '' for never */
  abandonsAt?: string;
  /** the step it is on, as the checklist words it */
  step: string;
}

/** the helper's answer when a run is already in progress */
export class RunInProgressError extends Error {
  constructor(
    message: string,
    readonly activeJob: string,
  ) {
    super(message);
  }
}

@Injectable({ providedIn: 'root' })
export class Jobs {
  /**
   * Where the helper is and how to reach it. A constructor parameter with a default rather
   * than `inject()`, so a test can still say `new Jobs()`.
   */
  constructor(private readonly helper: HelperConnection = new HelperConnection()) {}

  /** null until checked; false means the helper is not running */
  readonly available = signal<boolean | null>(null);
  readonly config = signal<ServerConfig | null>(null);
  /**
   * The runs the helper is working on, as last asked. Shared, because the banner, the
   * history's pinned panel and the run buttons all go by it - and a page that has just
   * started or finished a run has to change all three at once.
   */
  readonly activeRuns = signal<ActiveRun[]>([]);
  /**
   * Works asked to be downloaded or updated from a listing, by work number - one entry's ⋯ menu,
   * a placeholder's *download it now*, or everything ticked. `App` takes it, goes to the Works tab
   * and opens *Download/update a specific fic* (one) or *several fics* with the numbers in the
   * link box; nothing else reads it.
   */
  readonly fetchWorksAsked = signal<string[] | null>(null);
  /**
   * Works' indexes asked to be looked up from a listing, by work number - a file no index entry
   * matches: its *Look up its index from AO3 here* link or ⋯ menu item (one), or the selection
   * bar's *Look up N indexes* (those ticked). `App` takes it and opens Resolve issues straight on
   * the index question, for those works or every work with none.
   */
  readonly lookUpAsked = signal<string[] | null>(null);

  async loadConfig(): Promise<ServerConfig | null> {
    try {
      const response = await this.helper.call(`/api/config`);
      if (!response.ok) throw new Error(String(response.status));
      const config = (await response.json()) as ServerConfig;
      // every name in the library is read by the helper's pattern from here on
      useNamePattern(config.settings?.fileNamePattern);
      this.config.set(config);
      this.available.set(true);
      return config;
    } catch {
      this.available.set(false);
      return null;
    }
  }

  /**
   * Every run the helper has written down, newest first.
   *
   * Returns null rather than throwing when the helper is not there: the history page is
   * something to read, and a page that shows an error where a list should be is less
   * useful than one that says the helper is not running.
   */
  /**
   * The earlier runs a quick scan may be told to measure back to, newest first.
   *
   * Asked of the helper rather than filtered here, so the rule for what counts as a floor
   * lives in one place - the same place that enforces it when the run starts.
   */
  async loadFloorRuns(store: LibraryStore | null): Promise<RunHistory[] | null> {
    if (!store) return null;
    try {
      // the history is read out of the library here; which of it qualifies is the helper's
      // rule, so it is asked rather than decided twice
      const response = await this.helper.call(`/api/runs/floors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runs: await readRunHistory(store) }),
      });
      if (!response.ok) throw new Error(String(response.status));
      return ((await response.json()) as { runs: RunHistory[] }).runs ?? [];
    } catch {
      return null;
    }
  }

  /**
   * The newest run a quick scan would measure back to, or null when there is none (or the
   * helper cannot say). Read newest first a few records at a time, each batch put to the
   * helper, stopping at the first that qualifies - so a library whose last scan was a floor
   * downloads a handful of records, not the whole history.
   */
  async loadNewestFloor(store: LibraryStore | null): Promise<RunHistory | null> {
    if (!store) return null;
    try {
      for await (const batch of runHistoryBatches(store)) {
        const response = await this.helper.call(`/api/runs/floors`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ runs: batch }),
        });
        if (!response.ok) throw new Error(String(response.status));
        const floors = ((await response.json()) as { runs: RunHistory[] }).runs ?? [];
        if (floors.length) return floors[0];
      }
      return null;
    } catch {
      return null;
    }
  }

  /**
   * The runs the helper is working on right now, or null when it cannot be asked.
   */
  /**
   * Ask the helper which runs it is working on, and keep the answer in `activeRuns`.
   * Returns null, leaving the last answer, when it cannot be asked.
   */
  async refreshActiveRuns(): Promise<ActiveRun[] | null> {
    try {
      const response = await this.helper.call(`/api/jobs`);
      if (!response.ok) throw new Error(String(response.status));
      const runs = ((await response.json()) as { jobs?: ActiveRun[] }).jobs ?? [];
      // a run that has left the list has ended, and its record says how - History reads again
      const going = new Set(runs.map((run) => run.id));
      if (this.activeRuns().some((run) => !going.has(run.id))) this.forgetHistory();
      this.activeRuns.set(runs);
      return runs;
    } catch {
      return null;
    }
  }

  async activeJobs(): Promise<string[] | null> {
    try {
      const response = await this.helper.call(`/api/jobs`);
      if (!response.ok) throw new Error(String(response.status));
      return ((await response.json()) as { active?: string[] }).active ?? [];
    } catch {
      return null;
    }
  }

  /**
   * Mark the runs that were interrupted as such, and return how many there were.
   *
   * A run's record says `running` until the run writes its ending, and one that never got
   * the chance - the page was closed, the helper stopped or was shut down - says it for ever.
   * Any the helper is not working on right now were interrupted, matched **by the run's own
   * id**, so no other run anybody started can stand in for it.
   *
   * Two things are left alone rather than guessed at:
   *
   * - **a helper that does not answer.** A hosted helper waking up, or a dropped connection,
   *   looks exactly like one that is gone - and a background run may be going on it perfectly
   *   well. Marking it interrupted would offer it for resuming while it runs. The next time
   *   the helper answers, anything really interrupted is settled then.
   * - **a run started on a different helper** (its record's `helper`). The one on this
   *   computer knows nothing of a run the hosted one is doing in the same Dropbox library,
   *   and must not end it on paper. Records from before this was written say nothing, and
   *   are taken as this helper's.
   *
   * Whatever cannot be read or rewritten is left as it is: this is a correction, never worth
   * failing over.
   */
  async settleInterrupted(store: LibraryStore | null, history?: RunHistory[]): Promise<number> {
    if (!store) return 0;
    let settled = 0;
    try {
      // only the records not already known to have ended - see readUnsettledRuns - unless the
      // caller has the history in hand (the History tab), whose runs are then marked in place
      // so it need not read it all again
      const running = (history ?? (await readUnsettledRuns(store))).filter(
        (run) => run.status === 'running' && this.isThisHelpers(run),
      );
      if (!running.length) return 0;
      const answered = await this.activeJobs();
      if (answered === null) return 0;
      const active = new Set(answered);
      for (const run of running) {
        if (active.has(run.id)) continue;
        const path = `runs/${run.file}`;
        try {
          const record = JSON.parse((await store.read(path)) ?? '') as Record<string, unknown>;
          if (record['status'] !== 'running') continue;
          record['status'] = 'interrupted';
          await store.write(path, new Response(JSON.stringify(record, null, 2)));
          noteRunEnded(store, run.file);
          run.status = 'interrupted';
          settled++;
        } catch {
          continue;
        }
      }
    } catch {
      return settled;
    }
    return settled;
  }

  /** whether a run was started on the helper this page talks to, as far as its record says */
  isThisHelpers(run: RunHistory): boolean {
    return !run.helper || sameHelper(run.helper, this.helper.settings().helperUrl);
  }

  /**
   * The unfinished scans that could be picked up, newest first, each saying whether it can
   * be and what to know first. The rule is the helper's, so it is asked, as for floors.
   */
  /**
   * The run history the History tab last read, for the library it read it from. A retry
   * started from History opens on that run straight away, judged against this list rather
   * than the whole history read again (`loadRetryableRun`). History itself shows this list
   * again when it is opened, rather than reading the library each time; only its Refresh, a
   * run starting, and a run ending (`forgetHistory`) make it read again.
   */
  historyRead: { store: LibraryStore; runs: RunHistory[]; at: Date } | null = null;

  /** the history last read is behind: a run started or ended since, and wrote its record */
  forgetHistory(): void {
    this.historyRead = null;
  }

  /**
   * The helper's answer to the config asked for as a run window opened (`App.openRun`) - in
   * the background, so the options can be chosen while a hosted helper wakes. The run page
   * waits on it before starting (`DownloadDialog.readyToStart`).
   */
  connecting: Promise<ServerConfig | null> | null = null;
  /** a quick scan's newest floor, looked for as its window opened; null when none was asked */
  floorAhead: Promise<RunHistory | null> | null = null;

  /**
   * One run, with how it can be retried. The helper judges it alongside the runs newer than
   * it (a newer full scan is one of its warnings), taken from the list History already read
   * when there is one - so nothing is downloaded - and from the library otherwise.
   */
  async loadRetryableRun(store: LibraryStore | null, runId: string): Promise<RetryableRun | null> {
    if (!store || !runId) return null;
    try {
      const read = this.historyRead?.store === store ? this.historyRead.runs : null;
      const history = read?.some((run) => run.id === runId) ? read : await readRunHistory(store);
      const at = history.findIndex((run) => run.id === runId);
      if (at < 0) return null;
      const response = await this.helper.call(`/api/runs/retryable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runs: history.slice(0, at + 1) }),
      });
      if (!response.ok) throw new Error(String(response.status));
      const runs = ((await response.json()) as { runs: RetryableRun[] }).runs ?? [];
      return runs.find((run) => run.id === runId) ?? null;
    } catch {
      return null;
    }
  }

  /**
   * The names dating gives files (`POST /api/file-names`): from each work's index entry where it
   * has one, as a download would name it, with the date given. Null when the helper does not
   * answer - the page then adds the date to the name each file has.
   */
  async fileNames(files: readonly { file: { name: string }; date: string; record?: object; parts?: object }[]): Promise<string[] | null> {
    try {
      const response = await this.helper.call(`/api/file-names`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          files: files.map((x) => ({ name: x.file.name, date: x.date, record: x.record, parts: x.parts })),
        }),
      });
      if (!response.ok) return null;
      const names = ((await response.json()) as { names?: unknown }).names;
      return Array.isArray(names) && names.length === files.length ? names.map((x) => String(x ?? '')) : null;
    } catch {
      return null;
    }
  }

  async loadRetryableRuns(store: LibraryStore | null): Promise<RetryableRun[] | null> {
    if (!store) return null;
    try {
      await this.settleInterrupted(store);
      const response = await this.helper.call(`/api/runs/retryable`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runs: await readRunHistory(store) }),
      });
      if (!response.ok) throw new Error(String(response.status));
      return ((await response.json()) as { runs: RetryableRun[] }).runs ?? [];
    } catch {
      return null;
    }
  }

  /**
   * Every run written down in the library, newest first - read straight out of it, so the
   * history is there with the helper stopped. Null when no library is open.
   */
  async loadRuns(store: LibraryStore | null): Promise<RunHistory[] | null> {
    if (!store) return null;
    try {
      return await readRunHistory(store);
    } catch {
      return null;
    }
  }

  /**
   * Do one thing the helper asked of the library, and tell it how that went.
   *
   * A write's bytes are collected from the helper only now, as a stream, so a large epub
   * goes from the helper to the folder without being held whole. An answer that cannot be
   * delivered is left for the helper to notice - it gives up on a page it cannot hear from.
   */
  async answerStorage(jobId: string, request: StorageRequest, store: LibraryStore): Promise<void> {
    const answer = await answerStorage(store, request, async () => {
      const response = await this.helper.call(`/api/jobs/${jobId}/blobs/${request.id}`);
      if (!response.ok) throw new Error(`could not collect the file (${response.status})`);
      return response;
    });
    try {
      await this.helper.call(`/api/jobs/${jobId}/storage/${request.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(answer),
      });
    } catch {
      // the helper has gone; the stream closing says so
    }
  }

  /**
   * Ask a run to abandon the step it is on.
   *
   * A debug tool. Throws on refusal for the same reason pausing does: a skip that silently
   * did not happen would leave the page believing the run had moved on when it had not.
   */
  async skipStep(jobId: string): Promise<void> {
    const response = await this.helper.call(`/api/jobs/${jobId}/skip`, { method: 'POST' });
    if (!response.ok) throw new Error('could not skip the current step');
  }

  async start(request: StartRequest): Promise<string> {
    // the login goes sealed when this page was built with the helper's public key, and a
    // background run's Dropbox sign-in inside it - it is worth as much
    const { username, password, dropbox, ...rest } = request;
    const login = await this.helper.sealLogin(username, password, dropbox ? { dropbox } : {});
    const response = await this.helper.call(`/api/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // which helper this is, as this page names it - written into the history file, so a
      // page talking to another helper can tell the run is not one of its own
      body: JSON.stringify({ ...rest, ...login, helper: this.helper.settings().helperUrl }),
    });
    const answer = await response.json();
    if (response.status === 409) {
      throw new RunInProgressError(
        answer?.error ?? 'A run is already in progress.',
        answer?.activeJob ?? '',
      );
    }
    if (!response.ok) throw new Error(answer?.error ?? `request failed (${response.status})`);
    this.forgetHistory();
    return answer.jobId as string;
  }

  /**
   * Answer a question the run has stopped to ask.
   *
   * The run is blocked waiting for this, so a failure here matters: it is surfaced rather
   * than swallowed, and the helper gives up on its own after a while so nothing hangs for
   * ever if this never arrives.
   */
  async answer(jobId: string, choice: AnswerChoice, date = '', always = false): Promise<void> {
    const response = await this.helper.call(`/api/jobs/${jobId}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(always ? { choice, date, always } : { choice, date }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.error ?? `could not answer (${response.status})`);
    }
  }

  /**
   * End a run at once, as a last resort, whatever its thread is doing - from History, for a
   * run that will not stop or whose window has gone.
   *
   * The helper marks it stopped and done, so a new run can start, and hands back its record
   * as it now stands - log, issues, `stopped` - which this writes into the library itself.
   * A run that is not in the background saves its history through the window that started
   * it, and with that window gone a save from the helper would wait on nobody. Written only
   * where the record already is, so a run from another library is never written into this
   * one. Throws when the helper refuses or cannot be reached: a force stop that silently did
   * not happen would leave the run holding the helper.
   */
  async forceStop(jobId: string, store: LibraryStore | null): Promise<void> {
    const response = await this.helper.call(`/api/jobs/${jobId}/force-stop`, { method: 'POST' });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.error ?? `the helper would not stop it (${response.status})`);
    }
    const answer = (await response.json()) as {
      record?: { file: string; data: Record<string, unknown> } | null;
    };
    const record = answer.record;
    if (store && record?.file && !record.file.includes('/')) {
      const path = `runs/${record.file}`;
      if ((await store.read(path)) !== null) {
        await store.write(path, new Response(JSON.stringify(record.data, null, 2)));
      }
    }
    await this.refreshActiveRuns();
  }

  /**
   * A run's record as the helper holds it now, or null when this helper does not have that
   * run (over, restarted, or going on another helper) or cannot be reached.
   *
   * For a run still going: its file in the library is saved only every couple of minutes,
   * so a log read from there is behind the run window, and the helper's copy is not.
   */
  async liveRecord(jobId: string): Promise<Record<string, unknown> | null> {
    try {
      const response = await this.helper.call(`/api/jobs/${jobId}/record`);
      if (!response.ok) return null;
      const answer = (await response.json()) as { record?: Record<string, unknown> | null };
      return answer.record && typeof answer.record === 'object' ? answer.record : null;
    } catch {
      return null;
    }
  }

  /**
   * Ask the helper to stop. The run unwinds at its next checkpoint, keeping whatever it
   * has already written, so this is safe rather than destructive.
   */
  async cancel(jobId: string): Promise<void> {
    try {
      await this.helper.call(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
    } catch {
      // the helper may already have stopped; the stream closing will tell us
    }
  }

  /**
   * Pause or resume a run.
   *
   * The helper only sets a flag, so this returns straight away - the run acts on it at its
   * next safe point, which is before its next request. Throwing on a failure matters here:
   * a pause that silently did not happen would leave the page saying the run is paused
   * while it carries on downloading.
   */
  async setPaused(jobId: string, paused: boolean): Promise<void> {
    const what = paused ? 'pause' : 'resume';
    const response = await this.helper.call(`/api/jobs/${jobId}/${what}`, { method: 'POST' });
    if (response.ok) return;

    // a 404 here is nearly always a helper older than this page rather than a missing job.
    // the page is reloaded from disk on every refresh; the helper is a long-running process
    // that keeps whatever code it started with, so an app left running across an update
    // serves the new page from the old helper - which has no pause route at all
    if (response.status === 404) {
      throw new Error(
        `could not ${what} the run - the helper may be an older version that does not ` +
          'support pausing. Restart the app to update it.',
      );
    }
    throw new Error(`could not ${what} the run`);
  }

  /**
   * Subscribe to a job's progress. Returns a function that closes the stream.
   * The password is never part of this - it went out with the start request and is not stored.
   */
  stream(jobId: string, onEvent: (event: JobEvent) => void, onError: () => void): () => void {
    return this.helper.stream(
      `/api/jobs/${jobId}/events`,
      (data) => {
        try {
          onEvent(JSON.parse(data) as JobEvent);
        } catch {
          // a malformed frame is not worth tearing the run down for
        }
      },
      // the helper closes the stream when the job ends, which surfaces here too
      onError,
    );
  }
}

/** two helper addresses naming the same helper - case and a trailing slash aside */
export function sameHelper(a: string, b: string): boolean {
  const clean = (url: string) => url.trim().replace(/\/+$/, '').toLowerCase();
  return clean(a) === clean(b);
}
