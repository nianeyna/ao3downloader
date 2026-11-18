import { savedRunLogLines, savedTrimOldRunLogs } from './run-logs';
import {
  Component,
  DestroyRef,
  ElementRef,
  OnDestroy,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { WorkLink } from './work-link';
import { Chime } from './chime';

import { DecimalPipe } from '@angular/common';
import {
  ActiveRun,
  AnswerChoice,
  BackgroundAnswers,
  JobAction,
  JobEvent,
  JobOptions,
  Jobs,
  RetryMode,
  RetryableRun,
  RunStatus,
  RunHistory,
  baselineOf,
  RunStep,
  QuestionName,
  Scenario,
  RescuedWork,
  FicHubOlder,
  RunInProgressError,
  StartRequest,
  WorkFailure,
  BUILT_IN_CONFIG,
  ServerConfig,
} from './jobs';
import { DropboxSession } from './dropbox';
import { HelperConnection } from './helper-connection';
import { GUEST_USERNAME } from './guest-runs';

/** how fast a guest's made-up username types itself in, a letter at a time, on average */
const GUEST_TYPE_MS = 55;
/** the cursor ahead of the letters while the made-up username types itself */
const GHOST_CURSOR = '\u258F';
/** what fills the password box: never a real password, only its dots */
const GUEST_PASSWORD = 'not-a-real-pw';

/** what a guest's single-fic run types into its link box: plainly made up */
export const GUEST_WORK = '1234567';
/** ...and the several-fics run: made-up works, in every form the box takes - a number, a link, a
 *  chapter's link, and several to a line - to show what it accepts */
export const GUEST_WORKS = [
  '1234567',
  'https://archiveofourown.org/works/2345678',
  'https://archiveofourown.org/works/3456789/chapters/1111111',
  '4567890, 5678901',
].join('\n');

/** the gap before the next letter: uneven, as a hand's would be, and quick */
function ghostPause(): number {
  return Math.round(GUEST_TYPE_MS * (0.5 + Math.random()));
}
import { DebugMode } from './debug-mode';
import { VisitLog } from './visit-log';
import { LibraryFreshness } from './freshness';
import { safeGet, safeRemove, safeSet } from './storage';
import { Library } from './library';
import { DropboxLibraryStore, LibraryStore, StorageRequest } from './library-store';
import { RunIssues, attemptIssues, fichubOlderWords, issueCount, issuesReport } from './issues';
import { ImportRequest, LONG_IMPORT_REQUESTS, importRequests } from './imports';
import { REMEMBER_USERNAME_KEY, SAVED_USERNAME_KEY, SYNC_ACK_KEY, ao3TimeZone, inAo3Zone, utcToZonedDay, zonedDayToUtc, savedAnswerDefaults, savedQuestionTimeout, startingFiletypes, savedAlwaysAnswers, saveAlwaysAnswer, savedGuessedDateTimeout, savedOwnWaits, savedNobodyHere, writtenDate } from './preferences';

type Step =
  /**
   * Before the first real step is known. Which step a run opens on depends on the helper's
   * config and the run's own options (a link, the options, an acknowledgement, the file types),
   * and the config is asked for again as the window opens - so the window starts here, not on a
   * step it may jump away from a moment later.
   */
  | 'preparing'
  | 'link'
  | 'filetypes'
  | 'options'
  /** a quick scan choosing which earlier scan to measure back to */
  | 'floor'
  /** a quick scan whose floor would be a scan that could not download some works */
  | 'floor-warning'
  /** a custom run choosing which unfinished run to pick up where it left off */
  | 'resume'
  /** how the chosen run is retried, and its original dates and settings acknowledged */
  | 'retry-how'
  /** whether to run it in the background, and its answers up front - a hosted copy only */
  | 'background'
  | 'acknowledge'
  | 'credentials'
  | 'running'
  | 'done'
  | 'failed';

/** how long the run page waits on the helper (and a quick scan's floor) before giving up */
export const START_WAIT_MS = 2 * 60 * 1000;
const TIMED_OUT = Symbol('timed out');
const CANCELLED = Symbol('cancelled');
const HELPER_TIMED_OUT =
  'The helper did not answer within 2 minutes, so this run was not started. Nothing has changed.';
const HELPER_UNREACHABLE =
  'The helper could not be reached, so this run was not started. Nothing has changed.';

/** any page of a collection will do, so this only asks that a name follows /collections/ */
const COLLECTION_URL = /^https?:\/\/(www\.)?archiveofourown\.org\/collections\/([^/?#]+)/i;

/** any chapter or page of a work will do, so this only asks that digits follow /works/ */
const WORK_URL = /^https?:\/\/(www\.)?archiveofourown\.org\/works\/(\d+)/i;

/** a line of the run window's log, and when it was said */
export interface LogLine {
  text: string;
  at: Date;
}

/** a log line's time as the window shows it: the reader's own zone, to the second */
export function lineTime(at: Date): string {
  return at.toLocaleTimeString([], inAo3Zone({ hour: '2-digit', minute: '2-digit', second: '2-digit' }));
}

/** the most fics one 'several fics' run takes - the helper's MAX_WORK_LINKS */
export const MAX_WORKS = 500;

/**
 * The works in a paste of links or work numbers, and whatever in it was neither.
 *
 * Separated by anything people separate a list with - new lines, commas, spaces,
 * semicolons, in any mix. The same work twice is one work. The helper reads the paste again
 * by the same rule (`work_links`) and refuses what this would.
 */
export function parseWorkList(text: string): { ids: string[]; unknown: string[] } {
  const ids: string[] = [];
  const unknown: string[] = [];
  for (const piece of text.split(/[\s,;]+/)) {
    if (!piece) continue;
    const id = /^\d+$/.test(piece) ? piece : WORK_URL.exec(piece)?.[2];
    if (!id) unknown.push(piece);
    else if (!ids.includes(id)) ids.push(id);
  }
  return { ids, unknown };
}

/**
 * The index's own file type, which is not a copy of a work like the others.
 *
 * Matches `strings.AO3_DOWNLOAD_TYPE_METADATA` on the helper. Named here rather than read
 * out of `config.forced`, because what makes it special is what it *is* - the index - and
 * not that it happens to be on a list of locked types.
 */
/** the workflows the helper retries as themselves - its RESUME_ACTIONS */
const RETRY_AS_ITSELF = ['bookmarks', 'quick', 'custom', 'collections', 'collection'];

/**
 * The runs that read your own bookmarks or collections, found by your username - so they
 * need one even without a login. The helper's `USERNAME_ACTIONS`.
 */
export const USERNAME_ACTIONS: readonly string[] = ['bookmarks', 'new', 'sync', 'custom', 'quick', 'collections'];

const METADATA = 'JSON';

const USERNAME_KEY = SAVED_USERNAME_KEY;
const REMEMBER_KEY = REMEMBER_USERNAME_KEY;

/** which works a repair's downloads are for, as its summary says it */
const IMPORT_SCOPE_WORDS: Record<string, string> = {
  all: 'all fics found to have issues in this import',
  dates: 'any fics found to have date issues in this import',
  index: 'any fics found to have index issues in this import',
};
const MAX_LOG = 200;

@Component({
  selector: 'app-download-dialog',
  imports: [DecimalPipe, WorkLink],
  templateUrl: './download-dialog.html',
  styleUrl: './download-dialog.css',
})
export class DownloadDialog implements OnDestroy {
  private readonly jobs = inject(Jobs);
  private readonly library = inject(Library);
  private readonly visit = inject(VisitLog);
  private readonly chime = inject(Chime);
  /**
   * What the window opened with - its file types and every option as it would send them - so
   * the visit log can say which were left as they were and which were changed (`noteStart`).
   */
  private openedWith: { filetypes: string[]; options: Record<string, unknown> } | null = null;
  private readonly dropbox = inject(DropboxSession);
  private readonly helper = inject(HelperConnection);
  protected readonly debugMode = inject(DebugMode);
  private readonly freshness = inject(LibraryFreshness);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly action = input.required<JobAction>();
  /** a run to open set to resume - from the history's Resume button */
  readonly resumeFrom = input('');
  /**
   * A run already going in the background, to open straight onto its progress - from the
   * history's View progress button. Everything so far is replayed, so the window reads as
   * it would have had it been open all along.
   */
  readonly attachTo = input<ActiveRun | null>(null);
  /**
   * An import's works and what to do with them, chosen in the import window before this one
   * opens (`ImportDialog`) - so an import has no link, options or file types step here, only
   * the background choice (a hosted copy) and the login.
   */
  readonly importing = input<ImportRequest | null>(null);
  /** what the link box starts with - a work number, when the window was opened from a listing */
  readonly prefill = input('');
  /** roughly how many requests an import makes - over `LONG_IMPORT_REQUESTS` it says to leave the window open */
  protected readonly importRequestCount = computed(() => {
    const importing = this.importing();
    return importing ? importRequests(importing) : 0;
  });
  protected readonly longImport = LONG_IMPORT_REQUESTS;
  /**
   * The newest scan a quick scan would measure back to, once read: undefined until then, null
   * when there is none. 'Anything that has changed since my last run' needs only this, so only
   * the newest records are read for it - never the whole history (`Jobs.loadNewestFloor`).
   */
  private readonly newestFloorRead = signal<RunHistory | null | undefined>(undefined);
  private readonly newestFloor = this.newestFloorRead;
  /** the newest floor as it is being found - looked for as the window opened (`Jobs.floorAhead`) */
  private floorFinding: Promise<RunHistory | null> | null = null;
  /** the helper's answer to the config asked for as the window opened */
  private helperAnswer: Promise<ServerConfig | null> = Promise.resolve(null);
  /** the file types were changed by hand, so the helper's own defaults arriving late leave them */
  private filetypesTouched = false;
  /** the whole list is being read - asked for once, kept for as long as the window is open */
  private floorsLoading = false;

  /** every scan to measure back to, read the first time it is wanted and kept after */
  private loadAllFloors(): void {
    if (this.floorRuns() !== null || this.floorsLoading) return;
    this.floorsLoading = true;
    void this.jobs.loadFloorRuns(this.library.store()).then((runs) => {
      this.floorsLoading = false;
      this.floorRuns.set(runs ?? []);
      this.newestFloorRead.set(runs?.[0] ?? null);
    });
  }
  readonly closed = output<void>();
  /**
   * The run came across files with no date in the app's own form in their names, and the reader
   * chose to date them: the app closes this window, reads the library again and opens Resolve
   * issues on what it finds.
   */
  readonly resolveIssues = output<void>();

  protected readonly step = signal<Step>('preparing');
  protected readonly config = this.jobs.config;
  protected readonly available = this.jobs.available;

  protected readonly selected = signal<string[]>([]);
  protected readonly username = signal('');
  protected readonly password = signal('');
  /** opt-in: only true once the user has asked to be remembered */
  protected readonly remember = signal(false);

  // the questions the console menu asks after the file types
  protected readonly start = signal(1);
  protected readonly pages = signal(0);
  protected readonly series = signal(false);
  protected readonly images = signal(false);
  protected readonly workdates = signal(false);
  /** fetch every requested format again, whether or not the copy held is behind */
  protected readonly overwrite = signal(false);
  /** also check every non-bookmark in the index for updates */
  protected readonly nonBookmarks = signal(false);
  /** a collections run: index and download every work in the collections as well */
  protected readonly collectionWorks = signal(false);
  /** a collections run: read each collection's subcollections too, and theirs in turn */
  protected readonly subcollections = signal(false);
  /** a collections run: read each collection's parent too, and its parent in turn */
  protected readonly parentCollections = signal(false);

  /** the collection to index, for the action that works from a link */
  protected readonly collectionUrl = signal('');

  /** ticked once the limitation of this run has been read and accepted */
  protected readonly acknowledged = signal(false);
  /** the combined run's note only: turns it off for next time, once accepted */
  protected readonly dontAskAgain = signal(false);

  /**
   * A custom run may work from the index rather than reading AO3's listing again - its own
   * choice of what the run covers (`coverage` 'existing'), or, on a retry, whatever the run it
   * retries did (`retryReindex`)
   */
  protected readonly reindex = computed(() =>
    this.resuming() ? this.retryReindex() : this.coverage() !== 'existing');
  private readonly retryReindex = signal(true);
  /**
   * Skipping the indexing, how a custom run judges the files of the works in the index: against
   * the index as it stands (`index`, nothing read from AO3), or against AO3 now (`ao3`: each work
   * looked up, its entry rewritten - `recheck`, the default and listed first, at the owner's request)
   */
  protected readonly existingCheck = signal<'index' | 'ao3'>('ao3');
  /** a custom run looking every indexed work up on AO3 rather than walking the listing */
  protected readonly recheck = computed(() =>
    this.picksReindex() && !this.resuming() && this.coverage() === 'existing' &&
    this.existingCheck() === 'ao3');
  /** whether the run writes the index: by indexing, or by rewriting each work it looks up */
  protected readonly writesIndex = computed(() => this.reindex() || this.recheck());
  /**
   * What this run reaches for, as one choice rather than several flags.
   *
   * 'all' is the whole listing, 'pages' a slice of it, 'dates' a window of time, 'existing' no
   * listing at all - only the works already in the index (a custom run skipping its indexing). They are
   * alternatives - a run cannot be walking a listing and not walking it - so one signal
   * with three values cannot hold a combination that means nothing, which two booleans
   * could. A quick scan uses the same signal for its own pair: 'all' there means back to
   * its last completed run.
   */
  protected readonly coverage = signal<'all' | 'pages' | 'dates' | 'run' | 'resume' | 'existing'>('all');
  /**
   * A custom run picking up where an unfinished run left off. It then runs as that run -
   * its workflow, file types and options - so nothing else on the way in is a choice.
   */
  protected readonly resuming = computed(
    () => this.action() === 'custom' && this.coverage() === 'resume',
  );
  /** the earlier runs on offer for retrying, once they have been asked for */
  protected readonly retryableRuns = signal<RetryableRun[] | null>(null);
  /**
   * The list holds only the run History sent here, not every earlier run - so going back to
   * the list reads them all then, and only then.
   */
  private retryListPartial = false;
  /** the id of the one chosen */
  protected readonly resumeRun = signal('');
  protected readonly chosenResume = computed(
    () => this.retryableRuns()?.find((run) => run.id === this.resumeRun()) ?? null,
  );
  /** how the chosen run is retried - its own default until another is picked */
  protected readonly retryMode = signal<RetryMode | ''>('');

  /** ticked to say the retry is understood to run with the original run's dates and settings */
  protected readonly retryAcknowledged = signal(false);

  protected chooseRetryRun(id: string): void {
    this.resumeRun.set(id);
    this.retryMode.set(this.chosenResume()?.retry.default ?? '');
    // a different run has different dates and settings, so it is acknowledged afresh
    this.retryAcknowledged.set(false);
  }

  /**
   * What a retry of `run` will use, said before it is acknowledged: the dates it measures by
   * and the settings it runs with - both the original run's, carried through every retry in a
   * chain, never today's or whatever the window would offer now.
   */
  protected retryTerms(run: RetryableRun): { dates: string; settings: string[] } {
    const options = run.options ?? {};
    // every kept moment, said as the day it is in the person's AO3 zone
    const day = (value: unknown) => utcToZonedDay(value);
    const began = day(baselineOf(run));
    const ranged = !!options['dates'];
    let dates: string;
    if (run.action === 'quick') {
      const floor = ranged ? day(options['dateFrom']) : day(run.progress?.['floor']);
      const end = ranged ? day(options['dateTo']) : '';
      const ceiling = end && end < began ? end : began;
      dates = `Back to ${floor || 'the start of your bookmarks (it had no floor)'}, and up to ` +
        `${ceiling} - fics dated after that are left for your next scan.`;
    } else if (run.action === 'custom' && ranged) {
      const end = day(options['dateTo']);
      dates = `${options['order'] === 'bookmarked' ? 'Fics you bookmarked' : 'Fics AO3 updated'} from ${day(options['dateFrom']) || 'any date'} to ` +
        `${end && end < began ? end : began}.`;
    } else if (['bookmarks', 'custom', 'quick', 'sync', 'new'].includes(run.action)) {
      dates = `Up to ${began}, when its first attempt started - bookmarks after that are left ` +
        `for your next scan.`;
    } else {
      dates = `Its first attempt started ${began}.`;
    }
    const named: Record<string, string> = {
      overwrite: 'overwrite existing downloads',
      series: 'get all works from encountered series',
      nonBookmarks: 'check non-bookmarks for updates',
      images: 'save embedded images',
      collectionWorks: 'index and download encountered works',
      subcollections: 'follow subcollections',
      parentCollections: 'follow parent collections',
      skipLogin: 'without logging in',
    };
    const on = Object.entries(named).filter(([key]) => options[key] === true).map(([, name]) => name);
    if (options['reindex'] === false) {
      on.push(options['recheck'] ? 'skip indexing, each indexed work looked up on AO3' : 'skip indexing');
    }
    const settings = [
      `${run.actionName || run.action}, as it was run`,
      `File types: ${(run.filetypes ?? []).join(', ') || 'none'}`,
      `Options: ${on.length ? on.join('; ') : 'none ticked'}`,
    ];
    return { dates, settings };
  }

  /** a run's steps as it set out to take them, and how each went - older runs saved none */
  protected stepsOf(run: RetryableRun): { id: string; label: string; outcome: string }[] {
    const plan = run.progress?.stepPlan ?? [];
    const outcomes = run.progress?.steps ?? {};
    return plan.map(([id, label]) => ({ id, label, outcome: outcomes[id] ?? 'pending' }));
  }

  /** the label of the last step that finished before the first one that did not */
  protected lastFinishedStep(run: RetryableRun): string {
    let last = '';
    for (const step of this.stepsOf(run)) {
      if (step.outcome === 'done' || step.outcome === 'skipped' || step.outcome === 'earlier') {
        last = step.label;
      } else break;
    }
    return last;
  }

  protected outcomeWord(outcome: string): string {
    return (
      { done: 'finished', skipped: 'skipped', earlier: 'done by an earlier attempt',
        failed: 'failed', running: 'did not finish', pending: 'not reached' } as Record<string, string>
    )[outcome] ?? outcome;
  }

  /** what went wrong on the run being retried, said on the retry page */
  protected readonly retryIssues = computed(() => {
    const run = this.chosenResume();
    return run ? attemptIssues(run) : [];
  });

  /** why an earlier run cannot be retried any way at all: the helper's reason for the first way */
  protected whyNotRetryable(run: RetryableRun): string {
    return run.retry.modes.find((m) => !m.available && m.reason)?.reason || 'It cannot be retried.';
  }

  protected statusWord(status: RunStatus): string {
    return (
      { success: 'finished', partial: 'partly finished', failed: 'failed', stopped: 'stopped',
        interrupted: 'interrupted', abandoned: 'abandoned', running: 'interrupted' } as Record<string, string>
    )[status] ?? status;
  }

  protected retryLabel(mode: RetryMode, run: RetryableRun): string {
    switch (mode) {
      case 'top':
        return run.action === 'quick'
          ? 'From the top - the same window again, back to its floor and up to when it first started'
          : 'From the top';
      case 'reindex':
        return 'Start its indexing from the top - every walk read again from its start (its ceiling, if it has one; otherwise page 1), keeping its earlier answers, then everything checked and downloaded';
      case 'index':
        return 'Carry on from where its indexing stopped - walks it finished are taken from the index, one that broke off goes on from where it stopped, and formats it already saved are not fetched again';
      case 'redownload':
        return 'Start its downloads from the top - every work it had settled on, checked and downloaded again by the usual rules (on a run that overwrites, every format again)';
      case 'downloads':
        if (run.action === 'works') {
          return 'Carry on from where it stopped - a fic it saved in every format is passed over, the one it was partway through gets only its missing formats, and every fic it never reached is done in full';
        }
        return 'Carry on from where its downloads stopped - only the formats it had not saved yet: nothing for a fic it finished, the rest of one it was partway through, every format of one it never reached';
      case 'failed':
        // with none, a count of 0 reads as a promise that nothing went missing
        return run.retry.failedWorks
          ? `Just the ${run.retry.failedWorks} ${run.retry.failedWorks === 1 ? 'work' : 'works'} it could not get`
          : 'Just the works it could not get (none failed)';
    }
  }
  /** the earlier scans a quick scan can be measured back to, once they have been asked for */
  protected readonly floorRuns = signal<RunHistory[] | null>(null);
  /** the id of the one chosen */
  protected readonly floorRun = signal('');
  protected readonly useDates = computed(() => this.coverage() === 'dates');
  /**
   * Whether the window has a newer end as well as an older one.
   *
   * The older end is the one that always exists, because it is what the indexing walk
   * stops at - a window open at the top is just 'everything since'. The newer end only
   * narrows what is picked out of the index afterwards.
   */
  protected readonly betweenDates = signal(false);
  /**
   * The order a custom run reads your bookmarks listing in, one for each shape so each starts
   * at what that shape always did: a slice of pages by date bookmarked, a date range by date
   * updated. Nothing changes for a run where it is left alone.
   */
  protected readonly pagesOrder = signal<'bookmarked' | 'updated'>('bookmarked');
  protected readonly datesOrder = signal<'bookmarked' | 'updated'>('updated');
  /** the order offered, and sent, for the shape chosen - a custom run's slice or range alone */
  protected readonly offersOrder = computed(
    () => this.action() === 'custom' && (this.coverage() === 'pages' || this.coverage() === 'dates'),
  );
  protected readonly listingOrder = computed(() =>
    this.coverage() === 'dates' ? this.datesOrder() : this.pagesOrder());
  protected setListingOrder(order: 'bookmarked' | 'updated'): void {
    (this.coverage() === 'dates' ? this.datesOrder : this.pagesOrder).set(order);
  }
  /** the date a custom range is read by, as its boxes say it; a quick scan's are updated */
  protected readonly rangeWord = computed(() =>
    this.action() === 'custom' && this.datesOrder() === 'bookmarked' ? 'Bookmarked' : 'Updated');
  protected readonly dateFrom = signal('');
  protected readonly dateTo = signal('');

  /** what the run has said, each line with when it was said - shown in the reader's own time */
  protected readonly log = signal<LogLine[]>([]);
  protected readonly lineTime = lineTime;
  /** the zone a typed date range is in: the AO3 one, so it compares with AO3's dates as typed */
  protected readonly ao3Zone = ao3TimeZone();
  protected readonly percent = signal<number | null>(null);
  protected readonly paused = signal<{ seconds: number; until: string } | null>(null);
  protected readonly summary = signal('');
  protected readonly error = signal('');
  protected readonly folder = signal('');

  /** which stage of the run is in progress */
  protected readonly phase = signal('');

  /** null while the login is being checked, then whether it worked */
  protected readonly loginVerified = signal<boolean | null>(null);
  protected readonly signedInAs = signal('');

  /** what is being fetched right now */
  protected readonly currentTitle = signal('');
  protected readonly currentFiletype = signal('');

  protected readonly cancelling = signal(false);
  protected readonly wasCancelled = signal(false);
  /**
   * Whether the run ended because AO3 stopped recognising the login.
   *
   * Flagged by the helper rather than guessed from the error text: there is a specific
   * thing to do about it, and it is not a crash.
   */
  protected readonly sessionExpired = signal(false);

  /**
   * Whether the run is paused, and whether a pause has been asked for but not taken effect.
   *
   * These are two different things on purpose. The helper sets a flag and answers straight
   * away; the run itself only stops at its next safe point, which can be a whole file
   * later. Showing 'Paused' the instant the button is pressed would claim the run had
   * stopped while it was still downloading, so the button says 'Pausing...' until the run
   * itself confirms it by sending a `held` event.
   */
  protected readonly held = signal(false);
  protected readonly holdPending = signal(false);

  // these two are for the summary shown once the run has finished. while it is running the
  // log says all of this as it happens, a line at a time, so there is nothing for a
  // standing panel to add. the `refresh` event still carries an undated count and nothing
  // reads it - the log covers that too.
  /** works ao3 has updated since they were saved, which this run is fetching again */
  protected readonly staleCount = signal(0);
  /** existing files this run gave a date to, by renaming them */
  protected readonly stampedCount = signal(0);
  /**
   * The checklist this run published before it began, and where it has got to.
   *
   * Sent up front rather than built from what has happened, so the panel can show what is
   * still to come. Everything starts 'waiting' and the helper moves each one as it goes.
   */
  protected readonly steps = signal<RunStep[]>([]);

  /** works this run could not download */
  protected readonly failures = signal<WorkFailure[]>([]);
  /**
   * Bookmarks that were never works: a series, something hosted elsewhere, one deleted.
   *
   * Kept apart from `failures` because nothing went wrong with these - there was no work
   * there to fetch, and no amount of retrying would change that. Listing them together
   * would make a real failure look routine.
   */
  protected readonly skipped = signal<WorkFailure[]>([]);
  /**
   * Works whose new copy arrived but needs checking: the older copy could not be safely
   * deleted, or checking the new file itself went wrong. A new file found to be damaged is
   * not here - it was removed, and is reported with `failures`.
   *
   * Nothing is lost - both copies are on disk - so this is not a failure to retry, but it
   * is a problem the user has to go and sort out, so each one is named.
   */
  protected readonly keptCopies = signal<WorkFailure[]>([]);
  /** files this run met with no date in the app's own form in their names (`unsureFiles`) */
  protected readonly unsureFiles = signal(0);
  /** the run's works left with more than one file of a format, every copy kept (`duplicateCopies`) */
  protected readonly duplicateCopies = signal<{ works: number; files: number } | null>(null);
  /** older copies the run marked for removal and did not remove - stopped, failed, refused */
  protected readonly notRemoved = signal<WorkFailure[]>([]);
  /** on the duplicates question: how many older files there are across those works */
  protected readonly askedFiles = signal(0);
  /** on the FicHub question: the work numbers AO3 would not give us */
  protected readonly askedIds = signal<string[]>([]);
  /** works AO3 would not give us that FicHub did */
  protected readonly rescued = signal<RescuedWork[]>([]);
  /** formats taken from FicHub that may be older cached copies (`fichubOlder`) */
  protected readonly fichubOlder = signal<FicHubOlder[]>([]);

  /**
   * How many undated files the run has stopped to ask about, or 0 when it is not asking.
   *
   * The run is genuinely blocked while this is set - it cannot decide what counts as out
   * of date until it knows the answer - so the dialog shows the question in place of the
   * usual progress.
   */
  protected readonly asking = signal(0);
  /**
   * Which question is being asked, so the right panel answers it.
   *
   * There is more than one now - undated files, and how far back a quick scan should
   * reach - and they are answered through the same endpoint. Keying the panel on the
   * count alone would show the undated buttons for whatever asked last.
   */
  protected readonly question = signal('');
  /** the date a question is offering, where it has one */
  protected readonly askedDate = signal('');
  /** the formats a per-work question is about */
  protected readonly askedFormats = signal<string[]>([]);
  /** on an `overwrite-older` question: the date of the copy on disk */
  protected readonly askedNewer = signal('');
  /** on an `unindexed-copy` question: each copy's date from its name, where the incoming
   *  version is from, and the answer recommended with why */
  protected readonly askedFileDates = signal<Record<string, string>>({});
  protected readonly askedSource = signal('');
  protected readonly askedRecommended = signal('');
  protected readonly askedRecommendedFormats = signal<string[]>([]);
  protected readonly askedReasons = signal<Record<string, string>>({});

  /** the helper's reason as a sentence: 'Recommended: no - ...' */
  protected sentence(reason: string | undefined): string {
    return reason ? reason.charAt(0).toUpperCase() + reason.slice(1) + '.' : '';
  }
  /** what the question answers itself with if nobody does, and after how many minutes */
  protected readonly askedDefault = signal('');
  protected readonly askedTimeout = signal(0);
  /** how long the question waits, in words: in seconds under a minute (a guest's pretend run waits 10) */
  protected readonly askedWait = computed(() => {
    const minutes = this.askedTimeout();
    if (minutes > 0 && minutes < 1) {
      const seconds = Math.round(minutes * 60);
      return `${seconds} second${seconds === 1 ? '' : 's'}`;
    }
    return `${minutes.toLocaleString()} minute${minutes === 1 ? '' : 's'}`;
  });
  /** whether the 'give them a date' half of the question is showing */
  /** on an `inferred-date` question: its case, and whether to always answer it this way */
  protected readonly askedScenario = signal('');
  protected readonly askedFileNames = signal<Record<string, string>>({});
  /** on an `inferred-date` question: the format's other copies, none dated the app's way - kept */
  protected readonly askedOtherFiles = signal<Record<string, string[]>>({});
  /** the answers a question offers - Keep both only where it was */
  protected readonly askedChoices = signal<string[]>([]);
  /** on an `unindexed-copy` question: the copies Keep both would save a new version beside */
  protected readonly askedBothFormats = signal<string[]>([]);
  protected readonly writtenDate = writtenDate;
  protected readonly alwaysThisCase = signal(false);
  /** set once an answer has gone back, so it cannot be sent twice */
  protected readonly answering = signal(false);

  private jobId: string | null = null;
  /** the library this run was started in, which its requests are carried out against */
  private runStore: LibraryStore | null = null;
  /**
   * Requests already taken on, by id. A page that reconnects is sent again whatever it had
   * not answered, so the same request can arrive twice; it is done once.
   */
  private readonly handledStorage = new Set<string>();
  /**
   * Every path this run wrote, deleted or renamed - each of them through this page - so that
   * once it ends the listing can take in just those, rather than the whole library read again.
   */
  private readonly changedPaths = new Set<string>();
  /** requests are done one after another, in the order the run asked for them */
  private storageQueue: Promise<void> = Promise.resolve();
  private stop: (() => void) | null = null;
  private unloadGuard: ((event: BeforeUnloadEvent) => void) | null = null;

  protected readonly title = computed(() => {
    switch (this.action()) {
      case 'bookmarks':
        return '(Full scan) Reindex & Update All';
      case 'collections':
        return 'Index my collections';
      case 'collection':
        return 'Index collection by URL';
      case 'new':
        return 'Just download newly added bookmarks';
      case 'sync':
        return 'Download new bookmarks and update incomplete fics';
      case 'work':
        return 'Download/update a specific fic';
      case 'works':
        return 'Download/update several fics';
      case 'import':
        return 'Resolve issues found in your library';
      case 'custom':
        return 'Custom run';
      case 'quick':
        return 'Quick Scan';
      default:
        return 'Update incomplete fics';
    }
  });

  /**
   * The file types to list. JSON is the index - always written by a run that indexes, and
   * never one to pick - so it is listed only in debug mode; it is still sent with every run.
   */
  protected readonly shownFiletypes = computed(() => {
    const all = this.config()?.filetypes ?? [];
    return this.debugMode.on() ? all : all.filter((filetype) => filetype !== METADATA);
  });

  protected readonly blurb = computed(() => {
    switch (this.action()) {
      // a full scan and a quick scan say what they do at the top of their first page instead
      case 'bookmarks':
        return '';
      case 'collections':
        return 'Saves a json file describing each of your collections, including the work IDs it contains. It can index and download the works in them too.';
      case 'collection':
        return 'Indexes any one collection on AO3, whether or not it is yours. Saved alongside your own collections, in the same shape. It can index and download the works in it too.';
      case 'new':
        return 'Indexes your newest bookmarks and stops at the first one you already have, then downloads what it found. Usually a request or two.';
      case 'sync':
        return 'Three passes: your new bookmarks, then the fics your index last saw unfinished, then any finished fic missing a format you asked for.';
      case 'work':
        return 'Indexes one fic and downloads it, in whichever formats you pick. Use it for a single work you want now, or to repair one copy.';
      case 'works':
        return 'The same as downloading a specific fic, for a whole list at once: paste their links or work numbers, and each is indexed, then all are downloaded.';
      case 'import':
        return this.importBlurb();
      case 'custom':
        return 'A full scan with its parts made optional - choose the pages to cover, or skip reading AO3 entirely and work from what is already indexed.';
      case 'quick':
        return '';
      default:
        return 'Reads your index for fics it last saw unfinished, checks each one on AO3, brings its index entry up to date, and re-downloads any that have grown.';
    }
  });

  /** JSON is metadata rather than a work, so the update run cannot produce it */
  /** what an import will do, in a sentence, from what the import window chose */
  private importBlurb(): string {
    return this.importPlan().join('. ') + '.';
  }

  /** what a repair will do, a line each, from what the import window chose */
  protected readonly importPlan = computed(() => {
    const importing = this.importing();
    if (!importing) return [];
    const lines: string[] = [];
    const lookups = importing.lookups ?? 0;
    if (lookups) lines.push(`Lookup ${lookups.toLocaleString()} ${lookups === 1 ? 'work' : 'works'} with missing index`);
    const formats = (importing.filetypes ?? []).filter((x) => x !== METADATA);
    if (importing.scope !== 'skip' && formats.length) {
      const named = formats.length > 1
        ? `${formats.slice(0, -1).join(', ')} and ${formats[formats.length - 1]}`
        : formats[0];
      lines.push(`Download ${named} for ${IMPORT_SCOPE_WORDS[importing.scope] ?? IMPORT_SCOPE_WORDS['all']}`);
    }
    if (importing.scope !== 'skip' && importing.replaceOutdated) {
      lines.push('Will replace any outdated files with newer ones, if they exist');
    }
    return lines;
  });

  protected readonly metadataNotApplicable = computed(() => this.action() === 'update');

  /**
   * Which page of the listing to begin and end on. Only a custom run asks.
   *
   * A full scan covers everything by definition - that is what makes it a full scan, and
   * offering to cut it short there only makes it a custom run under another name.
   */
  protected readonly picksPages = computed(
    () => this.action() === 'custom' && this.coverage() === 'pages',
  );

  /**
   * Which runs can be given a window of time instead of their usual reach.
   *
   * A custom run swaps it for a slice of the listing; a quick scan swaps it for the floor
   * it works out on its own. Both end up walking the listing sorted by when AO3 last
   * updated each work and stopping at the older end, which is the one shape a date range
   * can be honoured in.
   *
   * On a quick scan it is a **debug** choice, because the whole point of that run is the
   * floor it works out for itself - picking your own date by hand is for testing what the
   * window does, not for using it. With the debug tools off the quick scan has nothing
   * left to ask, and skips its options step entirely.
   */
  protected readonly picksDates = computed(
    () =>
      this.action() === 'custom' ||
      (this.action() === 'quick' && this.debugTools()),
  );

  /**
   * Series expansion: the full scan only.
   *
   * Offered on the runs that index works one way or another - the two scans, the custom run
   * and the single fic. With it ticked, every work the run indexes marks the series it is
   * part of, and each marked series is walked once indexing is over, the same as a series
   * you bookmarked. The runs kept for debugging and the update run leave it out.
   */
  protected readonly picksSeries = computed(
    () =>
      (['bookmarks', 'quick', 'custom', 'work', 'works'] as JobAction[]).includes(this.action()) ||
      // a collections run meets works only when it was asked to index them
      (this.picksCollectionWorks() && this.collectionWorks()),
  );

  /**
   * Indexing and downloading the works in the collections: the two collection runs.
   *
   * The crawl reads every page of each collection's works anyway, and each blurb says
   * everything a bookmarks listing would, so indexing them costs nothing more - only the
   * downloads do. What follows is the download step every scan ends with.
   */
  protected readonly picksCollectionWorks = computed(
    () => this.action() === 'collections' || this.action() === 'collection',
  );

  /**
   * Embedded images: the custom run only.
   *
   * Image links are `<img>` tags in the work's rendered html, so they need the work page.
   * The custom run fetches it separately, after the files themselves have come down the
   * cheap way - which costs an extra request per work and is why it is opt-in, on the one
   * run that exists for asking about things like this.
   */
  protected readonly picksImages = computed(() => this.action() === 'custom');

  /**
   * Which runs may fetch a work again that nothing says is out of date.
   *
   * The two that can be pointed at a library and told to spend more on it: a full scan and
   * a custom run. It is the answer to a damaged or truncated file, which no version check
   * can see - the name and the date are both fine, and only the bytes are wrong.
   *
   * Deliberately not offered on the routine runs. They exist to be cheap, and a run that
   * re-fetches everything it already has is the opposite of that.
   *
   * Nor on the single-fic run, which always overwrites: a box that cannot be unticked is
   * not a choice. Asking for one fic by hand and being told nothing happened because the
   * copy looked fine is not the answer anybody came for, and being wrong costs one request
   * per format for one work.
   */
  protected readonly picksOverwrite = computed(
    () => this.action() === 'bookmarks' || this.action() === 'custom',
  );

  /**
   * Checking non-bookmarks for updates: the three scans.
   *
   * A listing of your bookmarks never shows a work you did not bookmark, so without this a
   * scan only reads one again when something else brings it there. Their series are walked
   * first, 20 works a request; only what that misses is opened one work at a time. Not on a
   * custom run told to skip indexing - re-reading a work writes its entry.
   */
  protected readonly picksNonBookmarks = computed(
    () =>
      (['bookmarks', 'quick', 'custom'] as JobAction[]).includes(this.action()) &&
      (!this.picksReindex() || this.reindex()),
  );

  /** only a custom run may work from the index instead of reading the listing */
  protected readonly picksReindex = computed(() => this.action() === 'custom');

  /**
   * Indexing collections on their own writes metadata only, so there are no file types to
   * pick - unless the run was asked to download the works in them too.
   */
  protected readonly picksFiletypes = computed(
    // an import's formats were chosen in the import window
    () => this.action() !== 'import' && (!this.picksCollectionWorks() || this.collectionWorks()),
  );
  protected readonly needsLink = computed(
    () => this.action() === 'collection' || this.action() === 'work' || this.action() === 'works',
  );
  /** the link step asks for a fic rather than a collection */
  protected readonly wantsWork = computed(() => this.action() === 'work');
  /** the link step asks for a list of fics */
  protected readonly wantsWorks = computed(() => this.action() === 'works');
  /** what the pasted list holds, as it is typed */
  protected readonly workList = computed(() => parseWorkList(this.collectionUrl()));
  protected readonly maxWorks = MAX_WORKS;

  /**
   * Whether to go without an AO3 login, offered on every run's options. Off unless ticked,
   * and warned about: logged out, AO3 shows only what anyone may see, so private bookmarks
   * are missed and restricted works fail.
   */
  protected readonly skipLogin = signal(false);
  /** whether this run will log in at all */
  protected readonly logsIn = computed(() => !this.skipLogin());
  /**
   * Whether this run still needs a username without a login: the ones that read your own
   * bookmarks or collections, found by your name. The helper's `USERNAME_ACTIONS`.
   */
  protected readonly needsUsername = computed(() =>
    USERNAME_ACTIONS.includes(
      // a retry is sent as custom when it is not one of the scans, so the run it retries
      // says whether it reads your own listing - a fic run's retry needs no username
      this.resuming() ? (this.chosenResume()?.action ?? this.sentAction()) : this.sentAction(),
    ),
  );
  /** what the login page says the username is for: your bookmarks, or your collections */
  protected readonly listingWord = computed(() => {
    const action = this.resuming() ? this.chosenResume()?.action : this.action();
    return action === 'collections' ? 'collections' : 'bookmarks';
  });
  /** the workflow the start request names - a retry is sent as the run it retries, or custom */
  protected readonly sentAction = computed<JobAction>(() => {
    const resumed = this.resuming() ? this.chosenResume() : null;
    return resumed
      ? RETRY_AS_ITSELF.includes(resumed.action) ? (resumed.action as JobAction) : 'custom'
      : this.action();
  });

  /**
   * Which runs say what they cannot do before anyone logs in for them.
   *
   * All three have a real limitation and none of them is obvious from the button: an update
   * pass never sees a fic that had finished, a full scan takes hours, and a combined run
   * trusts the index it already has. Better read before a long run than worked out after.
   */
  protected readonly needsAcknowledgement = computed(() => {
    const action = this.action();
    if (action === 'update' || action === 'bookmarks') return true;
    // these can be turned off - they are the runs people are meant to use routinely, and a
    // note that cannot be silenced is one they learn to click past. a quick scan carries
    // the same caveats as the combined run, so one answer covers both.
    return (action === 'sync' || action === 'quick') && !safeGet(SYNC_ACK_KEY);
  });

  /**
   * Whether this run has anything to ask on the options step.
   *
   * A step with nothing on it is worse than no step: it reads as something that failed to
   * load. When there is nothing to choose the run goes straight past it, in both
   * directions, rather than showing a page that says so. (Skipping the login is asked on the
   * login page, so it does not count.)
   */
  protected readonly hasOptions = computed(
    () =>
      this.picksPages() ||
      // a run that has swapped pages for a date window still has that choice to offer
      this.picksDates() ||
      this.picksSeries() ||
      this.picksImages() ||
      this.picksReindex() ||
      this.picksOverwrite() ||
      this.picksNonBookmarks() ||
      this.picksCollectionWorks() ||
      // it can always be pointed at an earlier scan, so it always has a choice to offer
      this.action() === 'quick',
  );

  /**
   * The options come before the file types, for every run.
   *
   * They have to for a custom run, where one of the options decides a file type - skipping
   * the indexing means no json, since json *is* the index - and asking which types you
   * want and then changing one behind you reads as the dialog overruling you. The rest
   * follow the same order because two orders is one more than anybody needs to learn.
   */
  protected readonly firstStep = computed<Step>(() => {
    if (this.needsLink()) return 'link';
    if (this.hasOptions()) return 'options';
    return this.picksFiletypes() ? 'filetypes' : this.loginStep();
  });

  /** whether what has been typed is something this run can act on */
  protected readonly linkIsValid = computed(() => {
    const typed = this.collectionUrl().trim();
    if (this.wantsWorks()) {
      const { ids, unknown } = this.workList();
      return ids.length > 0 && unknown.length === 0 && ids.length <= MAX_WORKS;
    }
    if (!this.wantsWork()) return COLLECTION_URL.test(typed);
    // a bare work number says the same thing as the whole url, and is what you get from
    // the address bar most easily
    return /^\d+$/.test(typed) || WORK_URL.test(typed);
  });

  /** what the current stage is doing, in words */
  protected readonly phaseLabel = computed(() => {
    switch (this.phase()) {
      case 'authenticating':
        return 'Verifying your AO3 login';
      case 'indexing':
        return 'Indexing - saving a json file for every bookmark';
      case 'scanning':
        return 'Reading your index for fics it last saw unfinished';
      case 'checking_files':
        return 'Checking which of these you have already downloaded';
      case 'checking_versions':
        return 'Checking which of your downloads AO3 has a newer version of';
      case 'updating':
        // an update run does one fic at a time: re-read it, then fetch it if the copy is
        // behind. so there is no separate 'downloading' stage to move on to
        return 'Re-reading each unfinished fic and replacing the copies that are behind';
      case 'downloading':
        return 'Downloading works';
      case 'collections':
        return 'Reading collections';
      default:
        return '';
    }
  });

  /** what the run was asked to do, shown back while it works */
  protected readonly chosenOptions = computed(() => {
    // a window opened onto a run already going chose nothing, so it has nothing to show
    // back - the run's own options are on its entry in the History tab
    if (this.attachedTo()) return [];
    const chosen: string[] = [];
    // only what this run was actually offered: showing back a setting it cannot act on
    // would read as a promise it is not going to keep
    if (this.resuming()) chosen.push('picking up an earlier run');
    if (this.picksDates() && this.useDates()) chosen.push(this.dateRange());
    if (this.picksPages()) chosen.push(this.pageRange());
    if (this.workdates()) chosen.push('look up publication dates');
    if (this.picksSeries() && this.series()) chosen.push('the rest of each series');
    if (this.picksImages() && this.images()) chosen.push('save images separately');
    if (this.picksReindex() && !this.reindex()) {
      chosen.push(this.recheck() ? 'each indexed work looked up on AO3' : 'no reindexing');
    }
    if (this.picksOverwrite() && this.overwrite()) chosen.push('overwrite existing files');
    if (this.picksNonBookmarks() && this.nonBookmarks()) chosen.push('check non-bookmarks');
    if (this.picksCollectionWorks() && this.collectionWorks()) chosen.push('the works in them');
    if (this.picksCollectionWorks() && this.subcollections()) chosen.push('subcollections');
    if (this.picksCollectionWorks() && this.parentCollections()) chosen.push('parent collections');
    return chosen;
  });

  /** the slice of the listing this run covers, in words */
  protected readonly pageRange = computed(() => {
    const start = this.start();
    const stop = this.pages();
    if (start <= 1) return stop === 0 ? 'all pages' : `pages 1 to ${stop}`;
    return stop === 0 ? `page ${start} onwards` : `pages ${start} to ${stop}`;
  });

  /**
   * The window this run covers, in words - the date range's answer to `pageRange`.
   *
   * Said oldest first, as a reader says a range - though the run walks the other way, down
   * from the newest and stopping at the older end.
   */
  protected readonly dateRange = computed(() => {
    const oldest = this.dateFrom();
    const newest = this.betweenDates() ? this.dateTo() : '';
    // a quick scan picks by either date; a custom run's range by the order it reads in
    const what = this.action() === 'quick' ? 'bookmarked or updated' : this.rangeWord().toLowerCase();
    if (!oldest) {
      return newest
        ? `any works that were ${what} on or before ${newest}, however long ago`
        : `any works, whenever they were ${what}`;
    }
    // oldest first, as a reader says a range
    return `any works that were ${what} between ${oldest} and ${newest || 'today'}`;
  });

  /**
   * Everything this run was asked on the way in, as label/value pairs.
   *
   * The two wizard pages read back in full - the options page and the file types page -
   * rather than only the choices that differ from the default, which is what
   * `chosenOptions` shows at a glance while the run works. Once the dialog has moved on,
   * this panel is the only place the answers still exist.
   *
   * Only what this run actually offered appears: a setting it never asked about would read
   * as one that was decided behind your back.
   */
  protected readonly runSettings = computed(() => {
    const rows: { label: string; value: string }[] = [];

    rows.push({
      label: 'File types',
      value: this.chosenFiletypes().join(', ') || 'nothing - indexing only',
    });

    if (this.resuming()) {
      const chosen = this.chosenResume();
      rows.push({
        label: 'Covers',
        value: chosen
          ? `picks up where the ${chosen.actionName} that started ` +
            `${chosen.started.slice(0, 16).replace('T', ' ')} left off, with its settings`
          : 'picks up where an earlier run left off',
      });
    } else if (this.picksFloorRun()) {
      const chosen = this.chosenFloorRun();
      rows.push({
        label: 'Covers',
        value: chosen
          ? `anything AO3 has updated since the scan that started ${baselineOf(chosen).slice(0, 10)}`
          : 'anything AO3 has updated since the scan you chose',
      });
    } else if (this.picksDates() && this.useDates()) {
      rows.push({ label: 'Covers', value: this.dateRange() });
      rows.push({ label: 'Ordered by', value: `date ${this.listingOrder()}` });
    } else if (this.picksPages()) {
      rows.push({ label: 'Covers', value: this.pageRange() });
      rows.push({ label: 'Ordered by', value: `date ${this.listingOrder()}` });
    } else if (this.action() === 'custom' && this.coverage() === 'existing') {
      rows.push({ label: 'Covers', value: 'every work already in your index' });
    } else if (this.picksDates() || this.action() === 'quick') {
      // the third choice: no slice and no window, so it reaches as far as the run can
      rows.push({
        label: 'Covers',
        value:
          this.action() === 'quick'
            ? 'anything AO3 has updated since your last completed run'
            : 'all bookmarks',
      });
    }
    if (this.picksReindex()) {
      rows.push({
        label: 'Indexing',
        value: this.reindex()
          ? "reading AO3's listing"
          : this.recheck()
            ? 'listing skipped - each indexed work looked up on AO3, its entry updated'
            : 'skipped - working from the saved index',
      });
    }
    if (this.picksCollectionWorks()) {
      rows.push({
        label: 'Works in the collections',
        value: this.collectionWorks()
          ? 'indexed, and downloaded or updated as necessary'
          : 'only their work numbers recorded',
      });
      rows.push({
        label: 'Related collections',
        value: [
          this.subcollections() ? 'subcollections' : '',
          this.parentCollections() ? 'parent collections' : '',
        ].filter(Boolean).join(' and ') + (this.subcollections() || this.parentCollections()
          ? ' too, however far removed, each read once'
          : 'not followed'),
      });
    }
    if (this.picksSeries()) {
      rows.push({
        label: 'If a work is part of a series',
        value: this.series()
          ? 'download all the other works in the series too, even if they are not bookmarked'
          : 'do nothing',
      });
    }
    if (this.picksImages()) {
      rows.push({
        label: 'Embedded images',
        value: this.images() ? 'saved separately' : 'not saved separately',
      });
    }
    if (this.picksOverwrite()) {
      rows.push({
        label: 'Existing files',
        value: this.overwrite() ? 'overwritten, current or not' : 'kept unless out of date',
      });
    }
    if (this.picksNonBookmarks()) {
      rows.push({
        label: 'Non-bookmarks',
        value: this.nonBookmarks()
          ? 'every one checked for updates, whatever the date range'
          : 'left alone unless this run reaches them',
      });
    }
    return rows;
  });

  /** what settings.ini says this run will work from */
  protected readonly settings = computed(() => this.config()?.settings ?? null);

  /**
   * Whether debug mode is on: the debug panel, and the quick scan's date range.
   *
   * Off unless deliberately asked for: skipping a step really does skip it, and what that
   * step would have done does not happen.
   */
  protected readonly debugTools = computed(() => this.debugMode.on());
  /** set once a skip has been asked for, so it cannot be sent twice by accident */
  protected readonly skipping = signal(false);

  // region running in the background

  /**
   * Whether this copy of the page offers background runs at all: only the hosted one, whose
   * helper is on a server and keeps going with every page closed. A helper on this computer -
   * the bundle, the Windows, Mac or Linux app, a dev build - stops with the app's own window,
   * so a run "in the background" there would carry on only as long as the page could have
   * stayed open anyway. Not offered, rather than offered and refused: the choice is not shown.
   */
  // not for a guest: a background run is carried on by the helper, which a guest never reaches
  protected readonly offersBackground = computed(() => !this.helper.isLocal() && !this.helper.guest());
  /** a guest's run is a pretend one, and its login is typed in for them (`guest.ts`) */
  protected readonly guest = this.helper.guest;
  private typing: ReturnType<typeof setTimeout> | null = null;
  /** the made-up login is typing itself in: the boxes glow faintly while it does */
  protected readonly ghostTyping = signal(false);

  /**
   * A guest's fic runs fill their own link box the same way, with made-up works - typed once per
   * window, and left to edit: any work number or link will do for a pretend run.
   */
  private linkTyped = false;
  private linkText = '';
  /** Continue pressed before the box has finished typing itself: put the rest in at once */
  private finishGuestLinks(): void {
    if (!this.linkText || !this.ghostTyping()) return;
    if (this.typing) clearTimeout(this.typing);
    this.typing = null;
    this.collectionUrl.set(this.linkText);
    this.ghostTyping.set(false);
  }
  private typeGuestLinks(): void {
    if (this.typing || this.linkTyped || this.collectionUrl()) return;
    const text = this.action() === 'works' ? GUEST_WORKS : GUEST_WORK;
    this.linkTyped = true;
    this.linkText = text;
    this.ghostTyping.set(true);
    let typed = 0;
    const next = () => {
      typed++;
      this.collectionUrl.set(text.slice(0, typed));
      if (typed < text.length) {
        // a link's run of letters goes quicker than a hand would type it, so the box fills fast
        this.typing = setTimeout(next, ghostPause() / 3);
        return;
      }
      this.typing = null;
      this.ghostTyping.set(false);
    };
    this.typing = setTimeout(next, GUEST_TYPE_MS * 4);
  }

  /**
   * A guest is never asked for an AO3 login: the made-up one types itself into the boxes the
   * moment the login page shows, as if someone unseen were at the keyboard - a letter at a time,
   * at a slightly uneven pace, with a cursor ahead of the letters, then the password's dots.
   * Nothing typed there goes anywhere. Start waits for it (`credentialsReady` wants both).
   */
  private typeGuestLogin(): void {
    if (this.typing || this.username() === GUEST_USERNAME) return;
    this.username.set('');
    this.password.set('');
    this.ghostTyping.set(true);
    let typed = 0;
    const next = () => {
      typed++;
      if (typed <= GUEST_USERNAME.length) {
        this.username.set(GUEST_USERNAME.slice(0, typed) + GHOST_CURSOR);
        this.typing = setTimeout(next, ghostPause());
        return;
      }
      this.username.set(GUEST_USERNAME);
      const dots = typed - GUEST_USERNAME.length;
      // never a real password: only enough for the box to show its dots, typed in too
      this.password.set(GUEST_PASSWORD.slice(0, dots));
      if (dots < GUEST_PASSWORD.length) {
        this.typing = setTimeout(next, ghostPause() / 2);
        return;
      }
      this.typing = null;
      this.ghostTyping.set(false);
    };
    this.typing = setTimeout(next, GUEST_TYPE_MS * 4);
  }
  /** whether this page's helper is on this computer - the app's own window, which a restart brings back */
  protected readonly local = computed(() => this.helper.isLocal());
  /** what starts FicFairy on this computer's system, for the helper-not-running advice; null when it cannot tell */
  protected readonly startProgram = computed(() => startProgramFor(systemName()));
  /** ticked: the run carries on in the helper with this page closed */
  protected readonly background = signal(false);
  /** whether the run on screen is a background one - chosen here, or attached to */
  protected readonly runningInBackground = signal(false);
  /** the run this window was opened onto, rather than started - see `attach` */
  private readonly attachedTo = signal<ActiveRun | null>(null);
  /**
   * The id of the run on screen, as a signal - what the pause deadline is looked up by.
   * (`jobId` stays a plain field for everything that only needs to send it.)
   */
  private readonly runId = signal('');

  /** minutes a paused background run is kept, from settings.ini; 0 is never */
  protected readonly pauseTimeout = computed(
    () => this.config()?.settings?.pausedRunTimeoutMinutes ?? 10,
  );

  /** asking whether to pause, before a background run is paused */
  protected readonly confirmingPause = signal(false);

  /** the time a paused background run will be abandoned unless resumed, for the reader */
  protected readonly abandonsAt = computed(() => {
    const at = this.jobs.activeRuns().find((run) => run.id === this.runId())?.abandonsAt;
    const when = at ? new Date(at) : null;
    return when && !Number.isNaN(when.getTime())
      ? when.toLocaleTimeString([], inAo3Zone({ hour: '2-digit', minute: '2-digit' }))
      : '';
  });

  /** the run ended because it was left paused too long */
  protected readonly abandoned = signal(false);

  /** the file types the run said it was saving, as it started - replayed to a late window */
  private readonly announcedFiletypes = signal<string[]>([]);

  /**
   * Why a background run cannot be chosen, or '' when it can.
   *
   * Only a library in Dropbox can be reached without the page. A folder on this computer is
   * open in this tab alone - the helper asks the page for every file, so closing it would
   * leave the run with nowhere to write.
   */
  protected readonly backgroundBlocked = computed(() => {
    if (!this.offersBackground()) return 'Only on the hosted copy of this page.';
    if (!(this.library.store() instanceof DropboxLibraryStore)) {
      return 'Only for a library in Dropbox: a folder on this computer can only be reached ' +
        'while this page is open.';
    }
    if (this.dropbox.status() !== 'signed-in') return 'Sign in to Dropbox first.';
    return '';
  });

  /** whether this run writes any downloaded works, rather than only the index */
  private readonly downloads = computed(() =>
    this.chosenFiletypes().some((x) => x !== METADATA),
  );

  /** whether the run replaces every copy anyway, which decides the undated question for it */
  private readonly overwrites = computed(
    () =>
      this.action() === 'work' ||
      this.action() === 'works' ||
      (this.picksOverwrite() && this.overwrite()),
  );

  /**
   * The questions this run could stop to ask, which a background run is asked up front.
   *
   * Worked out from the workflow and its options the same way the helper decides whether
   * to ask: a run that downloads nothing has no copies to judge; one that overwrites has
   * already settled every undated copy; only a quick scan with no earlier scan to measure
   * back to asks how far to go. Any run can fail to get a work from AO3, so every one may
   * ask about FicHub. Whether a question actually comes up depends on what is in the
   * library and on AO3 - these are answers held ready, used only if it does.
   */
  protected readonly backgroundQuestions = computed<QuestionName[]>(() => {
    if (this.resuming()) return ['fichub', 'overwrite-older'];
    const asked: QuestionName[] = [];
    if (this.action() === 'quick' && this.coverage() !== 'run' && this.coverage() !== 'dates') {
      asked.push('quick-floor');
    }
    // a collections run that reads no works fetches none, so none can fail
    const readsWorks = this.picksFiletypes() || this.action() === 'import';
    if (readsWorks) asked.push('fichub');
    // only a run that replaces what you have can be about to replace it with something older
    if (this.downloads() && this.overwrites()) asked.push('overwrite-older');
    return asked;
  });

  /** whether to try FicHub for works AO3 would not give us - yes, by default */
  protected readonly fichubAnswer = signal<'yes' | 'no'>('yes');
  /** whether to replace a copy with an older version of it - no, by default */
  protected readonly overwriteOlderAnswer = signal<'yes' | 'no'>('no');
  /** how far back a quick scan goes with nothing to measure to - everything, by default */
  protected readonly quickFloorAnswer = signal<'full' | 'since'>('full');

  /**
   * A background run's up-front answers start from what settings.ini says each question
   * answers itself with (`answerDefaults`), so they match what an unanswered question would
   * take. A value the page does not know leaves the built-in one.
   */
  private startFromDefaults(defaults: Partial<Record<QuestionName, string>>): void {
    const pick = <T extends string>(value: string | undefined, allowed: readonly T[]) =>
      allowed.find((x) => x === value);
    const yesNo = ['yes', 'no'] as const;
    const fichub = pick(defaults.fichub, yesNo);
    if (fichub) this.fichubAnswer.set(fichub);
    const overwrite = pick(defaults['overwrite-older'], yesNo);
    if (overwrite) this.overwriteOlderAnswer.set(overwrite);
    const floor = pick(defaults['quick-floor'], ['full', 'since'] as const);
    if (floor) this.quickFloorAnswer.set(floor);
  }

  /** this browser's default answers - only a hosted copy keeps any */
  private browserAnswers(): Partial<Record<QuestionName, string>> {
    return this.helper.isLocal() ? {} : savedAnswerDefaults();
  }

  /** what a hosted copy's User settings say about questions, sent with every run */
  private questionSettings(): Pick<StartRequest,
      'answerDefaults' | 'questionTimeoutMinutes' | 'ao3TimeZone' | 'alwaysAnswers' | 'guessedDateTimeoutMinutes'
      | 'questionTimeouts' | 'nobodyHere' | 'runLogMaxLines' | 'trimOldRunLogs'> {
    // every page sends the AO3 zone and the answers to always use: they are this browser's
    // settings wherever the helper is
    const always = savedAlwaysAnswers();
    const everyPage = {
      ao3TimeZone: ao3TimeZone(),
      ...(Object.keys(always).length ? { alwaysAnswers: always } : {}),
    };
    if (this.helper.isLocal()) return everyPage;
    const answers = savedAnswerDefaults();
    const timeout = savedQuestionTimeout();
    const guessed = savedGuessedDateTimeout();
    const waits = savedOwnWaits();
    const nobodyHere = savedNobodyHere();
    const logLines = savedRunLogLines();
    const trimLogs = savedTrimOldRunLogs();
    return {
      ...everyPage,
      ...(Object.keys(answers).length ? { answerDefaults: answers } : {}),
      ...(timeout === null ? {} : { questionTimeoutMinutes: timeout }),
      ...(guessed === null ? {} : { guessedDateTimeoutMinutes: guessed }),
      ...(Object.keys(waits).length ? { questionTimeouts: waits } : {}),
      ...(nobodyHere === null ? {} : { nobodyHere }),
      ...(logLines === null ? {} : { runLogMaxLines: logLines }),
      ...(trimLogs === null ? {} : { trimOldRunLogs: trimLogs }),
    };
  }

  /** the up-front answers, for the questions this run could ask */
  private readonly backgroundAnswers = computed<BackgroundAnswers>(() => {
    const answers: BackgroundAnswers = {};
    for (const name of this.backgroundQuestions()) {
      if (name === 'fichub') answers.fichub = { choice: this.fichubAnswer() };
      if (name === 'overwrite-older') {
        answers['overwrite-older'] = { choice: this.overwriteOlderAnswer() };
      }
      if (name === 'quick-floor') answers['quick-floor'] = { choice: this.quickFloorAnswer() };
    }
    return answers;
  });

  /** every up-front answer is a choice, so there is nothing that could be left unready */
  protected readonly backgroundAnswersReady = computed(() => true);

  protected setBackground(value: boolean): void {
    this.background.set(value && !this.backgroundBlocked());
  }

  /**
   * Close this window and leave the run going. Only a background run can: it reaches the
   * library itself, so nothing here is needed for it to carry on.
   */
  protected continueInBackground(): void {
    if (!this.runningInBackground()) return;
    this.stop?.();
    this.stop = null;
    this.releaseUnloadGuard();
    this.closed.emit();
  }

  /** open onto a background run already going, replaying everything it has said */
  private attach(run: ActiveRun): void {
    this.resetRunState();
    this.attachedTo.set(run);
    this.step.set('running');
    this.jobId = run.id;
    this.runId.set(run.id);
    this.runningInBackground.set(true);
    this.held.set(run.paused);
    this.append(`showing the ${run.actionName} started ${new Date(run.started).toLocaleString([], inAo3Zone())}`);
    this.stop = this.jobs.stream(run.id, (event) => this.onEvent(event), () => this.onStreamEnd());
  }

  // endregion

  constructor() {
    void this.init();
    // a work number handed over from a listing goes in the box once, as if typed
    let prefilled = false;
    effect(() => {
      const link = this.prefill();
      if (prefilled || !link) return;
      prefilled = true;
      untracked(() => {
        if (!this.collectionUrl()) this.collectionUrl.set(link);
      });
    });
    effect(() => {
      if (this.step() === 'credentials' && this.guest()) untracked(() => this.typeGuestLogin());
      if (this.step() === 'link' && this.guest() && (this.action() === 'work' || this.action() === 'works')) {
        untracked(() => this.typeGuestLinks());
      }
    });
    inject(DestroyRef).onDestroy(() => {
      if (this.typing) clearTimeout(this.typing);
    });
  }

  private async init(): Promise<void> {
    // the helper is asked as the window opens (`App.openRun`), and not waited on here: what it
    // said last, or the built-in lists, are enough to choose the options and file types by,
    // and Start waits for its answer (`readyToStart`)
    this.helperAnswer = this.jobs.connecting ?? this.jobs.loadConfig();
    this.jobs.connecting = null;
    this.floorFinding = this.jobs.floorAhead;
    this.jobs.floorAhead = null;
    void this.floorFinding?.then((floor) => {
      if (this.newestFloorRead() === undefined) this.newestFloorRead.set(floor);
    });

    // read after an await, not before: inputs are set once the constructor has returned
    await Promise.resolve();
    const attaching = this.attachTo();
    if (attaching) {
      // nothing to choose: the run is already going, so this opens straight onto it
      if (!(await this.helperAnswer)) return;
      this.folder.set(this.library.store()?.label ?? '');
      this.attach(attaching);
      return;
    }
    const known = this.config();
    const config = known ?? BUILT_IN_CONFIG;
    // a hosted copy's own User settings come before its helper's; a helper on this
    // computer has settings.ini for them, edited from the same tab
    this.startFromDefaults({ ...(config.settings?.answerDefaults ?? {}), ...this.browserAnswers() });
    // when the helper answers for the first time, what it says replaces the built-in lists
    // for whatever has not been chosen yet
    void this.helperAnswer.then((answer) => {
      if (!answer || known) return;
      if (!this.filetypesTouched) {
        this.selected.set(startingFiletypes(answer));
        // the helper's own defaults are what the window opened with, for the visit log
        if (this.openedWith) this.openedWith.filetypes = this.chosenFiletypes();
      }
      // the up-front answers are chosen on the login step: until then they are the defaults
      if (this.step() !== 'credentials' && this.step() !== 'background') {
        this.startFromDefaults({ ...(answer.settings?.answerDefaults ?? {}), ...this.browserAnswers() });
      }
      if (!this.username().trim()) this.username.set(answer.username || '');
    });

    // the library the page has open is where everything goes - the helper has none of its own
    this.folder.set(this.library.store()?.label ?? '');
    // the defaults are a starting point, not a rule: only `forced` cannot be unticked. This
    // browser's own choice, from the User settings tab, comes before the helper's
    this.selected.set(startingFiletypes(config));
    this.step.set(this.firstStep());
    if (this.resumeFrom() && this.action() === 'custom') {
      this.coverage.set('resume');
      this.toRetryHow(this.resumeFrom());
    }

    const remembered = safeGet(REMEMBER_KEY) === 'true';
    this.remember.set(remembered);
    // the saved username can come from the browser or from ao3downloader's own data.json
    this.username.set((remembered ? safeGet(USERNAME_KEY) : '') || config.username || '');
    this.openedWith = this.settingsNow();
  }

  /** the file types and options as a start request would carry them now */
  private settingsNow(): { filetypes: string[]; options: Record<string, unknown> } | null {
    try {
      const request = this.startRequest(null);
      return { filetypes: [...request.filetypes], options: { ...(request.options as unknown as Record<string, unknown>) } };
    } catch {
      return null;
    }
  }

  /**
   * Note in the visit log what this run was started with: every option and the file types,
   * each said to be left as the window opened with it or changed from that. Never the login.
   */
  private noteStart(background: boolean): void {
    const now = this.settingsNow();
    const shown = (value: unknown) => (Array.isArray(value) ? value.join(', ') || '(none)' : JSON.stringify(value ?? null));
    const lines = [`Run started: ${this.title()} (${this.sentAction()})${background ? ', in the background' : ''}`];
    if (now) {
      const first = this.openedWith;
      const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
      const says = (value: unknown, was: unknown) =>
        first === null ? '' : same(value, was) ? ' (left as the default)' : ` (changed from ${shown(was)})`;
      lines.push(`  file types: ${shown(now.filetypes)}${says(now.filetypes, first?.filetypes)}`);
      for (const [key, value] of Object.entries(now.options)) {
        lines.push(`  ${key}: ${shown(value)}${says(value, first?.options[key])}`);
      }
    }
    this.visit.note(lines.join('\n'));
  }

  ngOnDestroy(): void {
    this.stop?.();
    this.releaseUnloadGuard();
  }

  // region filetypes

  protected isForced(filetype: string): boolean {
    return (this.config()?.forced ?? []).includes(filetype);
  }

  /**
   * Whether this type is decided for you rather than chosen.
   *
   * On a custom run json is settled by the indexing switch in both directions - on when it
   * indexes, off when it does not - so it is locked either way rather than only when on.
   */
  protected isLocked(filetype: string): boolean {
    // a resumed run downloads what the run it picks up was downloading
    if (this.resuming()) return true;
    if (this.picksReindex() && filetype === METADATA) return true;
    return this.isForced(filetype);
  }

  protected isSelected(filetype: string): boolean {
    if (this.resuming()) return (this.chosenResume()?.filetypes ?? []).includes(filetype);
    if (this.picksReindex() && filetype === METADATA) return this.writesIndex();
    return this.selected().includes(filetype);
  }

  /** how many steps are behind this run, for the panel's summary line */
  protected readonly stepsDone = computed(
    () =>
      this.steps().filter(
        (x) => x.status === 'done' || x.status === 'skipped' || x.status === 'earlier',
      ).length,
  );

  /** why this type is locked, in a word, or '' when it is not */
  protected lockedBecause(filetype: string): string {
    if (!this.isLocked(filetype)) return '';
    if (this.resuming()) return 'from the earlier run';
    if (this.picksReindex() && filetype === METADATA) {
      return this.reindex() ? 'with indexing' : this.recheck() ? 'each work looked up' : 'not indexing';
    }
    return 'always on';
  }

  protected toggle(filetype: string): void {
    if (this.isLocked(filetype)) return;
    this.filetypesTouched = true;
    const current = this.selected();
    this.selected.set(
      current.includes(filetype) ? current.filter((x) => x !== filetype) : [...current, filetype],
    );
  }

  /**
   * The file types the run is actually asked for.
   *
   * `selected` holds what was ticked; on a custom run json is not ticked at all but
   * follows the indexing switch, so the two have to be reconciled before anything is sent
   * rather than the helper being left to guess which of them meant it.
   */
  protected readonly chosenFiletypes = computed(() => {
    // a window opened onto a run already going shows what the run said it was saving
    if (this.attachedTo()) return this.announcedFiletypes();
    if (this.resuming()) return this.chosenResume()?.filetypes ?? [];
    const importing = this.importing();
    if (this.action() === 'import' && importing) return importing.filetypes;
    // collections on their own are only ever indexed
    if (!this.picksFiletypes()) return [METADATA];
    if (!this.picksReindex()) return this.selected();
    const rest = this.selected().filter((x) => x !== METADATA);
    return this.writesIndex() ? [METADATA, ...rest] : rest;
  });

  protected readonly baselineOf = baselineOf;

  protected afterFiletypes(): void {
    this.toCredentials();
  }

  /** whether this run has a page for choosing which earlier scan to measure back to */
  protected readonly picksFloorRun = computed(
    () => this.action() === 'quick' && this.coverage() === 'run',
  );

  /** the scan chosen, for wording that names it */
  protected readonly chosenFloorRun = computed(
    () => this.floorRuns()?.find((run) => run.id === this.floorRun()) ?? null,
  );

  protected afterOptions(): void {
    if (this.resuming()) {
      this.toRetryList();
      return;
    }
    if (this.picksFloorRun()) {
      this.toFloorPage();
      return;
    }
    if (this.action() === 'quick' && this.coverage() === 'all') {
      // the floor the helper will measure back to is the newest scan that qualifies. one that
      // could not download some works still does - but say so, and offer another
      const known = this.newestFloor();
      if (known !== undefined) {
        // found as the window opened: nothing to read, and no warning page unless it needs one
        this.step.set(
          known?.missingDownloads?.length
            ? 'floor-warning'
            : this.picksFiletypes() ? 'filetypes' : this.loginStep(),
        );
        return;
      }
      // not found yet: on without it - the run page waits for it, and warns there if it must
      if (!this.floorFinding) this.floorFinding = this.jobs.loadNewestFloor(this.library.store());
      this.step.set(this.picksFiletypes() ? 'filetypes' : this.loginStep());
      return;
    }
    this.step.set(this.picksFiletypes() ? 'filetypes' : this.loginStep());
  }

  /** the floor a quick scan measures back to when none is chosen: the newest that qualifies */
  protected readonly automaticFloor = computed(() => this.newestFloor() ?? null);

  /** the whole list is read only here, once someone chooses to pick a scan themselves */
  private toFloorPage(): void {
    this.step.set('floor');
    this.loadAllFloors();
  }

  /** the warning answered: measure back to it anyway */
  protected useAutomaticFloor(): void {
    this.step.set(this.picksFiletypes() ? 'filetypes' : this.loginStep());
  }

  /** the warning answered: pick another scan to measure back to */
  protected chooseAnotherFloor(): void {
    this.coverage.set('run');
    this.toFloorPage();
  }

  /**
   * On with the run chosen. Its options are shown back in the (greyed-out) boxes, so the
   * settings panel and the options page say what the run will actually do.
   */
  /** the list of earlier runs to retry, read whole */
  private toRetryList(): void {
    this.step.set('resume');
    this.retryListPartial = false;
    // asked for fresh each time: a run may have been interrupted since the dialog opened
    this.retryableRuns.set(null);
    void this.jobs.loadRetryableRuns(this.library.store()).then((runs) => {
      this.retryableRuns.set(runs ?? []);
      // a run already chosen keeps its choice
      if (this.resumeRun()) this.chooseRetryRun(this.resumeRun());
    });
  }

  /**
   * Straight to how one run is retried - a retry started from History. Only that run is
   * judged, against the list History already read, so no list of every run is waited for.
   */
  private toRetryHow(runId: string): void {
    this.step.set('retry-how');
    this.retryListPartial = true;
    this.retryableRuns.set(null);
    this.resumeRun.set(runId);
    void this.jobs.loadRetryableRun(this.library.store(), runId).then((run) => {
      this.retryableRuns.set(run ? [run] : []);
      if (run) this.chooseRetryRun(run.id);
    });
  }

  /** from the list of earlier runs: on to how the chosen one is retried */
  protected afterRetryChoice(): void {
    if (!this.chosenResume()?.retry.default) return;
    this.step.set('retry-how');
  }

  protected afterResume(): void {
    const chosen = this.chosenResume();
    if (!chosen?.retry.default || !this.retryMode() || !this.retryAcknowledged()) return;
    const options = chosen.options ?? {};
    this.series.set(!!options['series']);
    this.images.set(!!options['images']);
    this.overwrite.set(!!options['overwrite']);
    this.nonBookmarks.set(!!options['nonBookmarks']);
    this.retryReindex.set(options['reindex'] !== false);
    // a retry logs in as the run it retries did: one that went without asks for no password,
    // and one reading your own listing is found by the account it read
    this.skipLogin.set(!!options['skipLogin']);
    if (this.skipLogin() && chosen.username && !this.username().trim()) {
      this.username.set(chosen.username);
    }
    this.step.set('filetypes');
  }

  protected afterFloor(): void {
    if (!this.floorRun()) return;
    this.step.set(this.picksFiletypes() ? 'filetypes' : this.loginStep());
  }

  /**
   * The step before this one, or null when this one is the first.
   *
   * Worked out rather than written down, because which steps a run has varies: a run with
   * nothing to choose has no options step at all, and only two ask for a link.
   */
  private stepBefore(step: Step): Step | null {
    const earlier: Step[] = [];
    if (this.needsLink()) earlier.push('link');
    if (this.hasOptions()) earlier.push('options');
    if (this.picksFloorRun()) earlier.push('floor');
    if (this.resuming()) earlier.push('resume', 'retry-how');
    if (this.picksFiletypes()) earlier.push('filetypes');
    if (this.needsAcknowledgement()) earlier.push('acknowledge');
    if (this.offersBackground()) earlier.push('background');
    earlier.push('credentials');

    const at = earlier.indexOf(step);
    return at > 0 ? earlier[at - 1] : null;
  }

  protected backFrom(step: Step): void {
    const previous = this.stepBefore(step);
    // the list was never read for a retry that came straight from History: read it now
    if (previous === 'resume' && this.retryListPartial) {
      this.toRetryList();
      return;
    }
    if (previous) {
      this.step.set(previous);
      return;
    }
    this.close();
  }

  /** whether stepping back from here goes anywhere other than out of the dialog */
  protected hasStepBefore(step: Step): boolean {
    return this.stepBefore(step) !== null;
  }

  /**
   * The step before the login: running in the background, where a hosted copy offers it, gets a
   * page of its own after any acknowledgement - its answers up front are a page in themselves.
   */
  private loginStep(): Step {
    return this.offersBackground() ? 'background' : 'credentials';
  }

  protected toCredentials(): void {
    // an update pass has a limitation worth reading before anyone logs in for it
    this.step.set(this.needsAcknowledgement() ? 'acknowledge' : this.loginStep());
  }

  /** from the acknowledgement: only on once it has actually been accepted */
  protected fromAcknowledgement(): void {
    if (!this.acknowledged()) return;
    // written only when they go through with it, so backing out never silences the note
    const shared = this.action() === 'sync' || this.action() === 'quick';
    if (shared && this.dontAskAgain()) safeSet(SYNC_ACK_KEY, 'true');
    this.step.set(this.loginStep());
  }

  protected setPages(value: string): void {
    const parsed = Number.parseInt(value, 10);
    this.pages.set(Number.isFinite(parsed) && parsed > 0 ? parsed : 0);
  }

  protected setStart(value: string): void {
    const parsed = Number.parseInt(value, 10);
    this.start.set(Number.isFinite(parsed) && parsed > 1 ? parsed : 1);
  }

  protected setCollectionUrl(value: string): void {
    this.collectionUrl.set(value);
  }

  /** from the link step: only worth going on once the link is one we can use */
  protected fromLink(): void {
    this.finishGuestLinks();
    if (!this.linkIsValid()) return;
    if (this.hasOptions()) {
      this.step.set('options');
      return;
    }
    this.step.set(this.picksFiletypes() ? 'filetypes' : this.loginStep());
  }

  // endregion

  // region credentials

  protected setUsername(value: string): void {
    this.username.set(value);
  }

  protected setPassword(value: string): void {
    this.password.set(value);
  }

  protected toggleRemember(value: boolean): void {
    this.remember.set(value);
  }

  /**
   * What the login page needs filled in before the run can start - the Start button is held
   * until it is, rather than pressed and quietly refusing
   */
  protected readonly credentialsReady = computed(() => {
    if (this.logsIn() && (!this.username().trim() || !this.password())) return false;
    return !(this.needsUsername() && !this.username().trim());
  });

  /**
   * A quick scan with no earlier scan on record to measure back to: it will read the whole
   * listing, which the first page says. Unknown (still being looked for) says nothing.
   */
  protected readonly firstScan = computed(
    () => this.action() === 'quick' && !this.resuming() && this.newestFloorRead() === null,
  );

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    if (!this.credentialsReady()) return;

    // only the username is ours to keep. the password is left to the browser's own
    // password manager, which stores it in the OS keychain rather than in page storage.
    // a run that does not log in leaves whatever was remembered alone
    if (this.guest() || (!this.logsIn() && !this.needsUsername())) {
      // nothing typed is used, so nothing typed is kept - and a guest's login is made up
    } else if (this.remember()) {
      safeSet(REMEMBER_KEY, 'true');
      safeSet(USERNAME_KEY, this.username().trim());
    } else {
      safeRemove(REMEMBER_KEY);
      safeRemove(USERNAME_KEY);
    }

    await this.run();
  }

  // endregion

  // region running

  /**
   * What the run page waits on before it starts a run, if it is still on its way: the helper's
   * answer (a hosted helper waking), and a quick scan's newest floor when it measures back to
   * its last run - with that floor's warning shown here, before anything starts, when it could
   * not download some works. Gives up after START_WAIT_MS. Cancel closes the window.
   */
  protected readonly waiting = signal<'' | 'helper' | 'floor' | 'floor-warning'>('');
  protected readonly waitedSeconds = signal(0);
  private waitDecided: ((go: boolean) => void) | null = null;

  private async readyToStart(): Promise<boolean> {
    const deadline = Date.now() + START_WAIT_MS;
    const started = Date.now();
    const tick = setInterval(() => this.waitedSeconds.set(Math.round((Date.now() - started) / 1000)), 1000);
    this.waitedSeconds.set(0);
    try {
      this.waiting.set('helper');
      const answer = await this.waitFor(this.helperAnswer, deadline);
      if (answer === CANCELLED) return false;
      if (answer === TIMED_OUT || !answer) {
        this.error.set(answer === TIMED_OUT ? HELPER_TIMED_OUT : HELPER_UNREACHABLE);
        this.step.set('failed');
        return false;
      }
      if (this.action() === 'quick' && this.coverage() === 'all' && !this.resuming()) {
        let floor = this.newestFloor();
        if (floor === undefined) {
          this.waiting.set('floor');
          const found = await this.waitFor(
            this.floorFinding ?? this.jobs.loadNewestFloor(this.library.store()), deadline);
          if (found === CANCELLED) return false;
          if (found === TIMED_OUT) {
            this.error.set(HELPER_TIMED_OUT);
            this.step.set('failed');
            return false;
          }
          floor = found;
          this.newestFloorRead.set(floor);
        }
        if (floor?.missingDownloads?.length) {
          clearInterval(tick);
          this.waiting.set('floor-warning');
          const go = await new Promise<boolean>((decide) => (this.waitDecided = decide));
          if (!go) return false;
        }
      }
      return true;
    } finally {
      clearInterval(tick);
      this.waitDecided = null;
      this.waiting.set('');
    }
  }

  /** a promise, or TIMED_OUT at the deadline, or CANCELLED if the wait was cancelled */
  private waitFor<T>(promise: Promise<T>, deadline: number): Promise<T | typeof TIMED_OUT | typeof CANCELLED> {
    return new Promise((done) => {
      const timer = setTimeout(() => done(TIMED_OUT), Math.max(0, deadline - Date.now()));
      this.waitDecided = () => {
        clearTimeout(timer);
        done(CANCELLED);
      };
      void promise.then((value) => {
        clearTimeout(timer);
        done(value);
      });
    });
  }

  /** the run failed before starting because the helper never answered */
  protected readonly helperNeverAnswered = computed(
    () => this.error() === HELPER_TIMED_OUT || this.error() === HELPER_UNREACHABLE,
  );

  /** the waiting page's Cancel: nothing has started, so the window just closes */
  protected cancelWaiting(): void {
    this.waitDecided?.(false);
    this.closed.emit();
  }

  /** the floor warning on the waiting page answered: measure back to it anyway */
  protected startWithFloor(): void {
    this.waitDecided?.(true);
  }

  /** the floor warning answered: pick another scan, back in the options */
  protected chooseAnotherFloorFromRun(): void {
    this.waitDecided?.(false);
    this.coverage.set('run');
    this.toFloorPage();
  }

  /** the helper did not answer: ask it again, and try once more */
  protected retryConnecting(): void {
    this.helperAnswer = this.jobs.loadConfig();
    void this.run();
  }

  private async run(): Promise<void> {
    this.step.set('running');
    this.resetRunState();
    this.runningInBackground.set(this.background());
    if (!(await this.readyToStart())) return;

    let jobId: string;
    try {
      // a resumed run is started as the run it picks up - a quick scan stays a quick scan
      const resumed = this.resuming() ? this.chosenResume() : null;
      const background = this.background() && !this.backgroundBlocked();
      // an ordinary run sends nothing about the background at all - in particular never the
      // Dropbox sign-in, which only a background run has any use for
      this.noteStart(background);
      jobId = await this.jobs.start(
        background
          ? {
              ...this.startRequest(resumed),
              ...this.questionSettings(),
              background: true,
              answers: this.backgroundAnswers(),
              dropbox: this.dropbox.handover(),
            }
          : { ...this.startRequest(resumed), ...this.questionSettings() },
      );
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
      this.visit.note(`Run did not start: ${this.error()}`);
      this.step.set('failed');
      // the page's idea of what is running is out of date, so it is asked again
      if (e instanceof RunInProgressError) void this.jobs.refreshActiveRuns();
      return;
    } finally {
      // the password has been handed over; don't keep it in component state
      this.password.set('');
    }

    this.jobId = jobId;
    this.runId.set(jobId);
    void this.jobs.refreshActiveRuns();
    // the run reads and writes through this library for as long as it lasts, even if the
    // page is switched to another one meanwhile - a run half in each would be no use
    this.runStore = this.library.store();
    this.handledStorage.clear();
    this.changedPaths.clear();
    // a background run does not need this page, so leaving it is not worth a warning
    if (!this.runningInBackground()) this.holdUnloadGuard();
    this.stop = this.jobs.stream(
      jobId,
      (event) => this.onEvent(event),
      () => this.onStreamEnd(),
    );
  }

  /** everything a run on screen shows, back to how it starts */
  private resetRunState(): void {
    this.log.set([]);
    this.percent.set(null);
    this.error.set('');
    this.currentTitle.set('');
    this.currentFiletype.set('');
    this.phase.set('');
    this.loginVerified.set(null);
    this.signedInAs.set('');
    this.cancelling.set(false);
    this.wasCancelled.set(false);
    this.staleCount.set(0);
    this.stampedCount.set(0);
    this.asking.set(0);
    this.answering.set(false);
    this.failures.set([]);
    this.skipped.set([]);
    this.keptCopies.set([]);
    this.fichubOlder.set([]);
    this.unsureFiles.set(0);
    this.duplicateCopies.set(null);
    this.notRemoved.set([]);
    this.steps.set([]);
    this.question.set('');
    this.abandoned.set(false);
    this.confirmingPause.set(false);
    this.held.set(false);
    this.holdPending.set(false);
    this.paused.set(null);
  }

  /** what the run is started with - everything but whether it runs in the background */
  private startRequest(resumed: RetryableRun | null): StartRequest {
    return {
      // a retry goes as the earlier run's own workflow where the helper resumes that kind, and
      // as a custom run otherwise (a fic run, a debug run) - the helper takes the workflow, file
      // types and options from the earlier run's record either way
      action: this.sentAction(),
      filetypes: this.chosenFiletypes(),
      options: {
        // a slice is only sent by the run that asked for one. the inputs keep whatever
        // was typed in them, so a run switched back to 'all bookmarks' would otherwise
        // carry a limit it no longer shows
        start: this.picksPages() ? this.start() : 1,
        pages: this.picksPages() ? this.pages() : 0,
        // only sent by a run that offered it - a collections run offers it only with its works
        series: this.picksSeries() && this.series(),
        collectionWorks: this.picksCollectionWorks() && this.collectionWorks(),
        subcollections: this.picksCollectionWorks() && this.subcollections(),
        parentCollections: this.picksCollectionWorks() && this.parentCollections(),
        images: this.images(),
        workdates: this.workdates(),
        // only offered on the runs that can be pointed at a known set of works
        overwrite: this.picksOverwrite() && this.overwrite(),
        // only the scans offer it, and not while skipping the indexing
        nonBookmarks: this.picksNonBookmarks() && this.nonBookmarks(),
        // only a custom run can turn this off; everything else always indexes
        reindex: this.picksReindex() ? this.reindex() : true,
        // skipping the indexing, every indexed work may still be looked up on AO3
        recheck: this.recheck(),
        // a window of time and a slice of the listing are alternatives, so the one not
        // chosen is not sent at all rather than sent and ignored
        dates: this.picksDates() && this.useDates(),
        // a custom run's slice or range, read in the order chosen for it; '' otherwise
        order: this.offersOrder() ? this.listingOrder() : '',
        // typed in the person's AO3 zone, sent as the UTC moments that day begins and the
        // newer end's ends - how the helper keeps them; it dates them in that zone again
        dateFrom: this.useDates() ? zonedDayToUtc(this.dateFrom()) : '',
        // an open-topped window has no newer end, so it must not carry one left behind
        // from a moment when 'between two dates' was ticked
        dateTo: this.useDates() && this.betweenDates() ? zonedDayToUtc(this.dateTo(), true) : '',
        floorRun: this.picksFloorRun() ? this.floorRun() : '',
        // the helper takes everything else from that run's own record
        resume: resumed ? resumed.id : '',
        retryMode: resumed ? this.retryMode() || undefined : undefined,
        skipLogin: !this.logsIn(),
        // an import's alone: whether a copy you have is replaced when AO3 has a newer version
        ...(this.action() === 'import'
          ? { replaceOutdated: !!this.importing()?.replaceOutdated, indexOnly: this.importing()?.indexOnly ?? [] }
          : {}),
      } satisfies JobOptions,
      // nothing is sent for a run that will not log in, whatever is in the boxes - but a
      // run reading your own listing is found by your username, login or not
      username: this.logsIn() || this.needsUsername() ? this.username().trim() : '',
      password: this.logsIn() ? this.password() : '',
      url: this.needsLink()
        ? this.collectionUrl().trim()
        : this.action() === 'import' ? this.importing()?.links : undefined,
    };
  }

  /**
   * Carry out one thing the helper needs done to the library. The page holds the library,
   * so every file a run reads or writes comes through here.
   */
  private doForHelper(request: StorageRequest): void {
    const jobId = this.jobId;
    const store = this.runStore;
    if (!jobId || !store || this.handledStorage.has(request.id)) return;
    this.handledStorage.add(request.id);
    if (request.op === 'write' || request.op === 'delete' || request.op === 'rename') {
      if (request.path) this.changedPaths.add(request.path);
      if (request.to) this.changedPaths.add(request.to);
    }
    this.storageQueue = this.storageQueue.then(() =>
      this.jobs.answerStorage(jobId, request, store),
    );
  }

  private onEvent(event: JobEvent): void {
    switch (event.type) {
      case 'storage':
        this.doForHelper(event as unknown as StorageRequest);
        break;
      case 'started':
        this.append('starting');
        this.announcedFiletypes.set(event.filetypes ?? []);
        break;
      case 'phase':
        this.phase.set(event.name ?? '');
        // the login is being checked; nothing is known about it yet
        if (event.name === 'authenticating') this.loginVerified.set(null);
        // each stage has its own scale, so the bar restarts rather than jumping back
        this.percent.set(null);
        this.summary.set('');
        this.currentTitle.set('');
        this.currentFiletype.set('');
        break;
      case 'page': {
        // the words say where that is in the listing itself - the page you would go and look at
        const where = event.listingPage ?? event.page;
        const outOf = event.listingTotal ?? event.total;

        if (event.fetching) {
          // a page about to be asked for is not a page that has arrived, so the bar shows
          // what is actually finished - everything before this one - while the caption
          // names the page in flight. the fetch is the slow part, and saying 'page 3' for
          // the whole time page 4 is on its way names the wrong page for all of it
          if (event.total) {
            this.percent.set(Math.round((((event.page ?? 1) - 1) / event.total) * 100));
          }
          // the first page is fetched before anything says how many there are
          this.summary.set(
            outOf ? `fetching page ${where ?? '?'} of ${outOf}` : `fetching page ${where ?? '?'}`,
          );
          break;
        }

        // the bar measures the slice being fetched, so it runs 1..n and ends full
        if (event.total) this.percent.set(Math.round(((event.page ?? 0) / event.total) * 100));
        // no total means the walk can stop anywhere - at a date floor, or at the first fic
        // already indexed - so there is no 'of' to give, and '?' would read as a fault
        this.summary.set(
          (outOf ? `page ${where ?? '?'} of ${outOf}` : `page ${where ?? '?'}`) +
            (event.works !== undefined ? ` - ${event.works} works so far` : ''),
        );
        break;
      }
      case 'work':
        if (event.total) this.percent.set(Math.round(((event.done ?? 0) / event.total) * 100));
        if (event.title) {
          this.currentTitle.set(event.title);
          // a work event without a filetype means the work page itself, not a format
          this.currentFiletype.set(event.filetype ?? '');
        }
        if (event.done !== undefined && event.total) {
          this.summary.set(
            event.phase === 'scanning'
              ? `checking file ${event.done} of ${event.total}`
              : `work ${event.done} of ${event.total}`,
          );
        }
        break;
      case 'paused':
        this.paused.set({ seconds: event.seconds ?? 0, until: event.until ?? '' });
        break;
      case 'resumed':
        this.paused.set(null);
        break;
      // the run itself confirming it has reached a safe point and stopped there. this is
      // what turns 'Pausing...' into 'Paused' - not the button press, which only asked
      case 'held':
        this.held.set(true);
        this.holdPending.set(false);
        // the helper knows when a paused background run will be abandoned
        if (this.runningInBackground()) void this.jobs.refreshActiveRuns();
        break;
      case 'released':
        this.held.set(false);
        this.holdPending.set(false);
        if (this.runningInBackground()) void this.jobs.refreshActiveRuns();
        break;
      case 'authenticated':
        this.loginVerified.set(true);
        this.signedInAs.set(event.username ?? '');
        break;
      case 'refresh':
        this.staleCount.set(event.stale ?? 0);
        this.stampedCount.set(event.stamped ?? 0);
        break;
      case 'failures':
        this.failures.set(event.failures ?? []);
        break;
      case 'skipped':
        this.skipped.set(event.skipped ?? []);
        break;
      case 'notRemoved':
        this.notRemoved.set(event.notRemoved ?? []);
        break;
      case 'keptCopies':
        this.keptCopies.set(event.keptCopies ?? []);
        break;
      case 'unsureFiles':
        this.unsureFiles.set(event.count ?? 0);
        break;
      case 'duplicateCopies':
        this.duplicateCopies.set(event.works ? { works: event.works, files: event.files ?? 0 } : null);
        break;
      case 'rescued':
        this.rescued.set(event.rescued ?? []);
        break;
      case 'fichubOlder':
        this.fichubOlder.set(event.fichubOlder ?? []);
        break;
      case 'steps':
        // everything starts waiting; the helper moves each one as it reaches it
        this.steps.set((event.steps ?? []).map((x) => ({ ...x, status: 'waiting' as const })));
        break;
      case 'step':
        this.steps.update((current) =>
          current.map((x) =>
            x.id === event.id ? { ...x, status: event.status ?? x.status } : x,
          ),
        );
        break;
      case 'question': {
        // the run is blocked until this is answered, so it takes over from the progress
        const asked = event.name ?? '';
        this.question.set(asked);
        // only a run with a page waits on a question (a background run takes its defaults and
        // sends none), so whoever is here is told: they may be in another tab
        if (asked) this.chime.waiting();
        this.askedDate.set(event.date ?? '');
        this.asking.set(event.count ?? 0);
        this.askedFiles.set(event.files ?? 0);
        this.askedIds.set(event.ids ?? []);
        this.askedFormats.set(event.formats ?? []);
        this.askedNewer.set(event.newer ?? '');
        this.askedFileDates.set(event.fileDates ?? {});
        this.askedSource.set(event.source ?? '');
        this.askedRecommended.set(event.recommended ?? '');
        this.askedScenario.set(event.scenario ?? '');
        this.askedFileNames.set(event.fileNames ?? {});
        this.askedOtherFiles.set(event.otherFiles ?? {});
        this.askedChoices.set(event.choices ?? []);
        this.askedBothFormats.set(event.bothFormats ?? []);
        this.alwaysThisCase.set(false);
        this.askedRecommendedFormats.set(event.recommendedFormats ?? []);
        this.askedReasons.set(event.reasons ?? {});
        this.askedDefault.set(event.default ?? '');
        this.askedTimeout.set(event.timeoutMinutes ?? 0);
            this.answering.set(false);
        break;
      }
      case 'message':
        if (event.text) this.append(event.text, event.at);
        break;
      case 'finished':
        this.wasCancelled.set(!!event.cancelled);
        this.abandoned.set(!!event.abandoned);
        if (!event.cancelled) this.percent.set(100);
        this.summary.set('');
        this.currentTitle.set('');
        this.currentFiletype.set('');
        this.step.set('done');
        this.finishUp();
        break;
      case 'failed':
        // a failure while the login was still being checked is a login failure, and
        // saying so is more use than a bare error message
        if (this.loginVerified() === null && this.phase() === 'authenticating') {
          this.loginVerified.set(false);
        }
        this.sessionExpired.set(!!event.sessionExpired);
        this.error.set(event.error ?? 'the download failed');
        this.step.set('failed');
        this.finishUp();
        break;
    }
  }

  private onStreamEnd(): void {
    // the stream also drops when the helper stops; only treat that as a failure
    // if the job never reported an outcome
    if (this.step() === 'running') {
      this.error.set(
        this.runningInBackground()
          ? 'Lost contact with the helper. The run may still be going there - the History ' +
              'tab shows it while it is, and View progress picks it up again.'
          : 'Lost contact with the local helper. Check the window it is running in.',
      );
      this.step.set('failed');
      this.finishUp();
    }
  }

  /**
   * Debug only: ask the run to abandon the step it is on.
   *
   * It really does skip - whatever that step would have done does not happen, and the
   * checklist marks it skipped rather than done so nothing claims otherwise.
   */
  protected async skipCurrentStep(): Promise<void> {
    if (!this.jobId || this.skipping()) return;
    this.skipping.set(true);
    try {
      await this.jobs.skipStep(this.jobId);
      this.append('debug: skipping the rest of this step');
    } catch {
      this.append('debug: could not skip the current step');
    }
    this.skipping.set(false);
  }

  /**
   * Debug only: fill the end-of-run report with made-up entries.
   *
   * Entirely in the page - nothing is sent to the helper and no run is affected. It exists
   * so the layout of both lists can be checked without having to find real works that fail,
   * which otherwise means waiting for a long run and hoping something goes wrong.
   */
  protected mockReport(): void {
    this.failures.set([
      { id: '111', link: 'https://archiveofourown.org/works/111', error: 'timed out' },
      { id: '222', link: 'https://archiveofourown.org/works/222',
        error: 'not a work file - it may be restricted to registered users' },
    ]);
    this.skipped.set([
      { id: '12345', link: 'https://archiveofourown.org/series/12345', title: 'A Series',
        error: 'a series, not a single work' },
      { id: null, link: 'https://example.com/fic/1', title: 'Elsewhere',
        error: 'an external work, hosted somewhere other than ao3' },
      { id: null, link: '', title: 'Gone', error: 'the work has been deleted' },
      { id: '75354806', link: 'https://archiveofourown.org/works/75354806',
        title: 'Mystery Work',
        error: 'in an unrevealed collection - it cannot be downloaded until it is revealed' },
      { id: null, link: '', title: 'Something',
        error: 'not a work - it may have been deleted, made private, or hidden' },
    ]);
    this.append('debug: showing a made-up report - nothing here really happened');
    this.step.set('done');
  }

  /** Ask the helper to stop. It keeps everything already written. */
  protected async requestStop(): Promise<void> {
    if (!this.jobId || this.cancelling()) return;
    this.cancelling.set(true);
    this.append('stopping at your request...');
    await this.jobs.cancel(this.jobId);
  }

  /**
   * Pause the run, or let it go again.
   *
   * Stopping is deliberately not blocked while paused, so this never has to be undone
   * first. If the helper refuses, the page says so rather than showing a pause that is
   * not really in force.
   */
  protected async togglePause(): Promise<void> {
    if (!this.jobId || this.holdPending() || this.cancelling()) return;

    const wanted = !this.held();
    // a background run left paused is abandoned after a while, which is worth knowing
    // before pressing pause rather than after
    if (wanted && this.runningInBackground() && this.pauseTimeout() && !this.confirmingPause()) {
      this.confirmingPause.set(true);
      // the window may be scrolled down to the log; the question has to be seen to be answered
      setTimeout(() =>
        this.host.nativeElement.querySelector('.confirm-pause')?.scrollIntoView?.({ block: 'nearest' }),
      );
      return;
    }
    this.confirmingPause.set(false);
    this.holdPending.set(true);
    try {
      await this.jobs.setPaused(this.jobId, wanted);
      this.append(wanted ? 'pausing after the work in progress...' : 'resuming...');
    } catch (error) {
      this.holdPending.set(false);
      // the helper's own words - it can tell a missing job from a helper too old to know
      // what a pause is, and which one it was is the whole of what to do about it
      this.append(
        error instanceof Error ? error.message : `could not ${wanted ? 'pause' : 'resume'} the run`,
      );
    }
  }

  private finishUp(): void {
    this.visit.note(`Run ended: ${this.step()}${this.error() ? ` - ${this.error()}` : ''}`);
    // the run's record now says how it ended, so History reads it again when next opened
    this.jobs.forgetHistory();
    this.paused.set(null);
    // a finished run is not a paused one, whatever it was when it reached the end
    this.held.set(false);
    this.holdPending.set(false);
    this.cancelling.set(false);
    // every change an ordinary run made went through this page and is taken in below, so it
    // is not one the works list should offer to refresh for. a background run's were not
    if (!this.runningInBackground()) this.freshness.takenIn(this.jobId);
    this.jobId = null;
    this.stop?.();
    this.stop = null;
    this.releaseUnloadGuard();
    // the banner and the run buttons go by what the helper says is running
    void this.jobs.refreshActiveRuns();
    // what the run wrote is in the listing once its last write has landed - new fics, their
    // tags, and their downloaded files - without opening the library again
    const changed = [...this.changedPaths];
    const store = this.runStore;
    this.changedPaths.clear();
    if (changed.length) {
      void this.storageQueue.then(() => this.library.refreshAfterRun(changed, store));
    }
  }

  /**
   * One line for the window. `at` is when the helper said it (UTC, on its `message` event), so a
   * background run's replayed lines keep their own times; a line the page says itself is now.
   */
  private append(text: string, at?: string): void {
    const said = at ? new Date(at) : new Date();
    const line = { text, at: Number.isNaN(said.getTime()) ? new Date() : said };
    const lines = [...this.log(), line];
    this.log.set(lines.length > MAX_LOG ? lines.slice(-MAX_LOG) : lines);
  }

  /** stop a reload or a tab close from silently killing a run in progress */
  private holdUnloadGuard(): void {
    this.unloadGuard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', this.unloadGuard);
  }

  private releaseUnloadGuard(): void {
    if (!this.unloadGuard) return;
    window.removeEventListener('beforeunload', this.unloadGuard);
    this.unloadGuard = null;
  }

  // endregion

  /**
   * Answer the question the run has stopped on, and let it carry on.
   *
   * The run is waiting on this, so the answer goes straight back rather than being kept
   * for a second run: everything after this point - which works count as out of date, and
   * therefore what gets downloaded - depends on it.
   */
  private async answerQuestion(choice: AnswerChoice, date = '', always = false): Promise<void> {
    if (!this.jobId || this.answering()) return;
    this.answering.set(true);
    try {
      await this.jobs.answer(this.jobId, choice, date, always);
      this.asking.set(0);
      this.question.set('');
    } catch (e) {
      // the run is still blocked, so this has to be said rather than swallowed
      this.answering.set(false);
      this.append(e instanceof Error ? e.message : String(e));
    }
  }

  /** ask FicHub for the works AO3 would not give us */
  protected tryFicHub(): void {
    void this.answerQuestion('yes');
  }

  /** leave the works AO3 would not give us as failures */
  protected skipFicHub(): void {
    void this.answerQuestion('no');
  }

  /** replace the newer copy with the older version anyway */
  protected replaceWithOlder(): void {
    void this.answerQuestion('yes');
  }

  /** keep the newer copy */
  protected keepNewerCopy(): void {
    void this.answerQuestion('no');
  }

  /**
   * A file without the app's own date: keep it, or replace it. With *always* ticked, this
   * browser keeps the answer for the case and sends it with every later run, and the run
   * takes it for every other work in the same case from now on - no more questions about it.
   */
  protected answerUnsure(choice: 'yes' | 'no' | 'both'): void {
    const scenario = this.askedScenario();
    const always = this.alwaysThisCase() && !!scenario;
    if (always) saveAlwaysAnswer(scenario as Scenario, choice);
    void this.answerQuestion(choice, '', always);
  }


  /**
   * A retry carrying on its downloads: read its works again from AO3 first, or not. With
   * *always* ticked the answer is kept in this browser and sent with every later run.
   */
  protected answerRetryReread(choice: 'yes' | 'no'): void {
    const always = this.alwaysThisCase();
    if (always) saveAlwaysAnswer('retry-reread', choice);
    void this.answerQuestion(choice, '', always);
  }

  /** a copy of a work with no earlier index entry: replace it, or keep it */
  protected replaceUnindexedCopy(): void {
    void this.answerQuestion('yes');
  }

  protected keepUnindexedCopy(): void {
    void this.answerQuestion('no');
  }

  /** keep the copies, and save the incoming version beside each one with no date written the app's way */
  protected keepBothUnindexed(): void {
    void this.answerQuestion('both');
  }

  /** replace only the copies recommended for it */
  protected replaceRecommendedCopies(): void {
    void this.answerQuestion('recommended');
  }

  /** measure back to the day the index was last written */
  protected quickScanSinceIndex(): void {
    void this.answerQuestion('since');
  }

  /** read the whole listing, as a first scan would */
  protected quickScanWholeListing(): void {
    void this.answerQuestion('full');
  }

  /** everything this run reported, by kind, as the report builds it */
  private readonly issues = computed<RunIssues>(() => ({
    failures: this.failures(),
    keptCopies: this.keptCopies(),
    notRemoved: this.notRemoved(),
    skipped: this.skipped(),
    fichubOlder: this.fichubOlder(),
  }));

  /** how many entries there are across every list of issues this run reported */
  protected readonly issueCount = computed(() => issueCount(this.issues()));

  /**
   * Every issue the run reported, as the text file the History tab saves for it. Built here
   * too so the account on screen and the file can be checked against each other.
   */
  /** one older FicHub copy, in words */
  protected fichubOlderWords(item: FicHubOlder): string {
    return fichubOlderWords(item);
  }

  protected issuesReport(): string {
    return issuesReport(this.issues());
  }

  /**
   * The answer a question takes when nobody gives one, in the words of the button that gives
   * it - 'Scan all bookmarks to be safe', not the 'full' the helper sends.
   */
  protected defaultWords(): string {
    const choice = this.askedDefault();
    const many = this.askedFormats().length > 1;
    const words: Record<string, Record<string, string>> = {
      'quick-floor': { full: 'Scan all bookmarks to be safe', since: `Only scan up until ${writtenDate(this.askedDate())}` },
      fichub: { yes: 'Try FicHub', no: 'No, leave them' },
      'overwrite-older': { no: 'No, keep my newer copy', yes: 'Yes, replace it' },
      'unindexed-copy': {
        no: many ? 'No, keep them all' : 'No, keep my copy',
        yes: many ? 'Yes, replace them all' : 'Yes, replace it',
        recommended: `Replace only ${this.askedRecommendedFormats().join(', ')}`,
        both: 'Keep both',
      },
      'inferred-date': { yes: many ? 'Replace them' : 'Replace it', no: 'Keep mine', both: 'Keep both' },
      'retry-reread': { yes: 'Yes, read them again', no: 'No, use the index as it is' },
    };
    return words[this.question()]?.[choice] ?? choice;
  }

  /** date the files this run asked about: close, and let the app read the library and open Resolve issues */
  protected resolveIssuesNow(): void {
    this.resolveIssues.emit();
    this.close();
  }

  protected close(): void {
    // the guard message explains why - unless the run carries on without this page
    if (this.step() === 'running') {
      this.continueInBackground();
      return;
    }
    this.closed.emit();
  }
}

/**
 * Today in UTC, as YYYY-MM-DD - the default answer to "which version are these?".
 *
 * UTC rather than local time so the default does not depend on which side of midnight the
 * machine's timezone happens to be, and so it matches the stamps written elsewhere. Being
 * a day out either way only moves the staleness boundary by a day, which is harmless.
 */
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** a real calendar date written as YYYY-MM-DD, not merely something shaped like one */
function isDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value ?? '')) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/** the name of the system this browser runs on, as far as the browser says */
function systemName(): string {
  const nav = typeof navigator === 'undefined' ? null : (navigator as Navigator & { userAgentData?: { platform?: string } });
  return nav?.userAgentData?.platform || nav?.platform || nav?.userAgent || '';
}

/**
 * What a person double-clicks (or runs) to start the app on their system - the same files the
 * release zips hold. Null for a system no zip is built for, such as a phone.
 */
export function startProgramFor(system: string): { file: string; how: string } | null {
  if (/android|iphone|ipad|ios/i.test(system)) return null;
  if (/mac|darwin/i.test(system)) return { file: 'Start FicFairy.command', how: 'double-click' };
  if (/win/i.test(system)) return { file: 'ficfairy.exe', how: 'double-click' };
  if (/linux|x11/i.test(system)) return { file: 'Start FicFairy.sh', how: 'run' };
  return null;
}
