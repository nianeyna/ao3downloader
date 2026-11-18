import { RECENT_RUN_LOGS } from './run-logs';
import { HelperConnection } from './helper-connection';
import { DeviceSupport } from './device-support';
import { inAo3Zone, shownTime, writtenDate } from './preferences';
import { Component, computed, effect, inject, signal, untracked, output } from '@angular/core';
import { WorkLink } from './work-link';
import { DecimalPipe } from '@angular/common';
import { ActiveRun, IndexGap, Jobs, RunChoice, RunHistory, RunRemoval } from './jobs';
import { describeGap, fichubOlderWords, issueCount, issuesOf, issuesReport, saveText } from './issues';
import { Library } from './library';
import { StorageChoice } from './storage-choice';
import { VisitLog } from './visit-log';
import { DummyData } from './dummy-data';
import { ProgressBar } from './progress-bar';
import { HISTORY_LIMIT } from './library-store';


/**
 * What past runs did, read back from the helper's run files.
 *
 * The fic lists are collapsed by default and the rest of the card is not: a run that
 * touched a thousand works would otherwise bury the next one, and the number is usually
 * all anybody wants from it.
 */
/** what each way a question can be answered says in a run's history */
const HOW_ANSWERED: Record<string, string> = {
  answered: 'You answered.',
  'timed-out': 'Nobody answered in time, so it took the default.',
  'not-asked': 'Not asked: settings.ini says to take the default at once.',
  'background-default': 'A background run that was not told, so it took the default.',
  'up-front': 'Answered before this background run started.',
  earlier: 'Taken from the earlier attempt this run retried.',
  stopped: 'The run was stopped while it waited, so it took the answer that changes nothing.',
  always: 'Not asked: you chose to always answer this case this way (User settings).',
  'nobody-answering': 'Not asked: an earlier question like it went unanswered, so it took the default at once.',
};

/** past this many links a run's links fold away, as its lists of works do */
export const LINKS_SHOWN = 10;

@Component({
  selector: 'app-history',
  imports: [DecimalPipe, ProgressBar, WorkLink],
  templateUrl: './history.html',
  styleUrl: './history.css',
})
export class History {
  private readonly jobs = inject(Jobs);
  private readonly visit = inject(VisitLog);
  protected readonly writtenDate = writtenDate;
  protected readonly recentRunLogs = RECENT_RUN_LOGS;
  protected readonly fichubOlderWords = fichubOlderWords;
  private readonly library = inject(Library);
  /** dummy data on screen: a retry would start a real run, so it is held as every run is */
  protected readonly dummy = inject(DummyData).active;
  /** held on a phone, or a browser that cannot write to a folder (`device-support.ts`) */
  protected readonly device = inject(DeviceSupport);
  /** a guest's history is the dummy library's: nothing in it can be retried (`guest.ts`) */
  protected readonly guest = inject(HelperConnection).guest;
  private readonly storage = inject(StorageChoice);
  /**
   * ' from Dropbox' while the library is there: History is always read straight from it - every
   * run's file downloaded again, nothing taken from this browser - and the button says so
   */
  protected readonly fromWhere = computed(() =>
    this.storage.mode() === 'dropbox' && !this.dummy() ? ' from Dropbox' : '',
  );

  protected readonly runs = signal<RunHistory[]>([]);
  /**
   * The folded lists opened, by run and list - a list is drawn only once opened: a run can touch
   * any number of works (an import has no limit), and every one drawn behind a closed fold still
   * slows the tab.
   */
  protected readonly openLists = signal<ReadonlySet<string>>(new Set());
  protected toggleList(key: string, open: boolean): void {
    this.openLists.update((now) => {
      const next = new Set(now);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });
  }
  /** a run's links, one to a line - shown as they are up to this many, folded past it */
  protected readonly linksShown = LINKS_SHOWN;
  protected linksOf(run: RunHistory): string[] {
    return (run.url ?? '').split('\n').filter(Boolean);
  }
  /** the most runs the tab reads and lists - older ones stay in runs/, just not shown */
  protected readonly historyLimit = HISTORY_LIMIT;
  protected readonly loading = signal(true);
  /** when the list shown was read from the library, for 'List refreshed' */
  protected readonly readAt = signal<Date | null>(null);
  protected readonly shownTime = shownTime;
  /** the library is being read: its own panel shows, so this tab's would be a second bar */
  protected readonly libraryLoading = this.library.loading;
  /** true when the helper could not be reached at all, which is not the same as no runs */
  protected readonly unavailable = signal(false);

  constructor() {
    // the history lives in the library, so it is read again whenever the library changes -
    // switching to Dropbox while looking at this page shows Dropbox's runs. Opening the tab
    // shows the list last read for this library rather than reading it again (a long history
    // in Dropbox is a download per record); Refresh, or a run starting or ending, reads anew
    effect(() => {
      const store = this.library.store();
      untracked(() => {
        const kept = this.jobs.historyRead;
        if (store && kept?.store === store) {
          this.runs.set(kept.runs);
          this.readAt.set(kept.at);
          this.unavailable.set(false);
          this.loading.set(false);
          void this.jobs.refreshActiveRuns();
        } else {
          void this.load();
        }
      });
    });
  }

  /** the older copies a run removed in its cleanup step */
  /** how a question was answered, in a sentence - '' on records from before it was kept */
  protected howWords(choice: RunChoice): string {
    return HOW_ANSWERED[choice.how ?? ''] ?? '';
  }

  protected removedOf(run: RunHistory): RunRemoval[] {
    return (run.removals ?? []).filter((x) => x.status === 'removed');
  }

  /**
   * The older copies a run marked for removal and did not remove. A record still saying
   * `pending` is a run that never reached its cleanup step - interrupted before it could
   * say so itself.
   */
  protected notRemovedOf(run: RunHistory): RunRemoval[] {
    return (run.removals ?? []).filter((x) => x.status !== 'removed');
  }

  /** a run to pick up where it left off, in a custom run */
  readonly resume = output<string>();
  /** a background run to open the progress window onto */
  readonly viewProgress = output<ActiveRun>();

  /**
   * The runs the helper is working on right now, pinned above the history.
   *
   * From the helper rather than from the history files: a file saying `running` might be a
   * run that was interrupted, and only the helper knows which ones really are going.
   */
  protected readonly activeRuns = this.jobs.activeRuns;

  /** the run whose force stop is being confirmed, by id */
  protected readonly confirmingForce = signal('');
  /** the run being force stopped right now, so it cannot be pressed twice */
  protected readonly forcing = signal('');
  protected readonly forceProblem = signal('');

  /** end a run that will not stop, then read the history again to show how it ended */
  protected async forceStop(active: ActiveRun): Promise<void> {
    if (this.forcing()) return;
    this.forcing.set(active.id);
    this.forceProblem.set('');
    try {
      await this.jobs.forceStop(active.id, this.library.store());
      this.confirmingForce.set('');
      await this.load();
    } catch (e) {
      this.forceProblem.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.forcing.set('');
    }
  }

  /** how many issues a run reported, across every kind */
  protected issuesIn(run: RunHistory): number {
    return issueCount(issuesOf(run));
  }

  /**
   * Save every issue a run reported as one text file - available for every run, for as
   * long as its history file is there, not only in the window of a run just finished.
   */
  protected downloadIssues(run: RunHistory): void {
    saveText(
      issuesReport(issuesOf(run), `Issues from ${run.actionName} started ${this.when(run.started)}`),
      `run-issues-${this.stampOf(run)}`,
    );
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    // what is going now, for the pinned panel - not waited on: the history is read out of
    // the library, and is worth showing whether or not the helper answers
    void this.jobs.refreshActiveRuns();
    const found = await this.jobs.loadRuns(this.library.store());
    // a run the history calls 'running' that the helper is not working on was interrupted:
    // marked so in the file and in the list already read - never the whole history again.
    // only asked when there is one, which is seldom
    if (found?.some((run) => run.status === 'running')) {
      await this.jobs.settleInterrupted(this.library.store(), found);
    }
    this.unavailable.set(found === null);
    this.runs.set(found ?? []);
    // a retry started from here opens on its run using this list, rather than reading it again
    const store = this.library.store();
    const at = new Date();
    this.jobs.historyRead = found && store ? { store, runs: found, at } : null;
    this.readAt.set(found ? at : null);
    this.loading.set(false);
    this.visit.note(
      found
        ? `History: ${found.length} past runs read${this.fromWhere()} (each fetched, never from this browser's cache)`
        : `History: past runs could not be read${this.fromWhere()}`,
    );
  }

  /**
   * What to call a run's outcome.
   *
   * A record still saying 'running' is one that never finished - the file is written when
   * a run starts, so the absence of an ending is the evidence that it was interrupted.
   */
  protected outcome(run: RunHistory): string {
    switch (run.status) {
      case 'success':
        return 'Finished';
      case 'partial':
        // short, as a pill: what went wrong is listed on the card itself
        return 'Partly Finished';
      case 'stopped':
        return 'Stopped';
      case 'failed':
        return 'Failed';
      case 'running':
        // only the helper can say a run is really going; a record can only say it started
        if (!this.jobs.isThisHelpers(run)) return 'Running on another helper';
        return this.activeRuns().some((active) => active.id === run.id)
          ? 'Running'
          : 'Running - not confirmed by the helper';
      case 'abandoned':
        return 'Abandoned';
      default:
        return 'Interrupted';
    }
  }

  /** set while a run's log is being read to be saved, so it cannot be asked for twice */
  protected readonly readingLog = signal('');

  /**
   * Save the account a run gave in its window - every line it printed - as a text file.
   *
   * Read from the run's history file when asked for, not with the history: a log can run to
   * thousands of lines, and a hundred of them would be a lot to read to draw a list.
   */
  protected async downloadLog(run: RunHistory): Promise<void> {
    const store = this.library.store();
    if (!store || this.readingLog()) return;
    this.readingLog.set(run.id);
    try {
      // a run still going is asked of the helper first: the file catches up only every
      // couple of minutes, and would download behind what the run window shows
      const live = this.activeRuns().some((active) => active.id === run.id)
        ? await this.jobs.liveRecord(run.id)
        : null;
      const record = (live ??
        JSON.parse((await store.read(`runs/${run.file}`)) ?? '{}')) as LogRecord;
      const lines = Array.isArray(record.log) ? record.log : [];
      const head = [
        `# ${run.actionName}, started ${this.when(run.started)}`,
        `# ${this.outcome(run)}${run.finished ? `, ${this.when(run.finished)}` : ''}`,
        ...this.runSettingsHead(run, record),
      ];
      if (record.logTrimmed) {
        head.push(`# the first ${record.logTrimmed} lines were dropped to keep the file small`);
      }
      saveText([...head, '', ...lines].join('\n') + '\n', `run-log-${this.stampOf(run)}`);
    } catch {
      // the file is gone or unreadable; the button stays, and the list says what there was
    } finally {
      this.readingLog.set('');
    }
  }

  /**
   * What a run was asked to do and what it ran under, for the top of its saved log - read
   * from the run's own file, so a log read on its own still says how the run was set up.
   * Every option and every setting is listed as it was recorded, not only the ones the
   * History entry puts into words: a log is read to explain a run, and a setting left out
   * is the one that would have.
   */
  private runSettingsHead(run: RunHistory, record: LogRecord): string[] {
    const head = ['#'];
    const links = String(record.url ?? run.url ?? '').split('\n').map((x) => x.trim()).filter(Boolean);
    if (links.length === 1) head.push(`# Link: ${links[0]}`);
    if (links.length > 1) head.push(`# Links (${links.length}):`, ...links.map((x) => `#   ${x}`));
    const filetypes = Array.isArray(record.filetypes) ? record.filetypes : run.filetypes;
    head.push(`# File types: ${filetypes?.join(', ') || 'none'}`);
    const options = record.options ?? run.options ?? {};
    const said = this.settingsOf({ ...run, options });
    if (said.length) head.push(`# Options: ${said.join(', ')}`);
    if (record.background) head.push('# Ran in the background');
    if (record.helper) head.push(`# Helper: ${record.helper}`);
    head.push(...listed('Run options', options));
    // not where settings.ini is, nor the account: a log is passed around - attached to an
    // issue, say - and a path names the person's folders as surely as a username does
    const settings = { ...(record.settings ?? {}) };
    delete settings['file'];
    head.push(...listed('settings.ini', settings));
    return head;
  }

  /** a run's start and id, for naming the files saved from it */
  private stampOf(run: RunHistory): string {
    const started = run.started ? new Date(run.started) : new Date();
    const day = Number.isNaN(started.getTime()) ? '' : started.toISOString().slice(0, 10);
    return `${day}-${run.id.slice(0, 8)}`;
  }

  /** a time of day, for when a paused run will be abandoned */
  protected timeOf(stamp: string | undefined): string {
    const parsed = stamp ? new Date(stamp) : null;
    return parsed && !Number.isNaN(parsed.getTime())
      ? parsed.toLocaleTimeString([], inAo3Zone({ hour: '2-digit', minute: '2-digit' }))
      : '';
  }

  protected describeGap(gap: IndexGap): string {
    return describeGap(gap);
  }

  /** when it ran, in the person's AO3 zone rather than as an iso stamp */
  protected when(stamp: string | null): string {
    if (!stamp) return '';
    const parsed = new Date(stamp);
    return Number.isNaN(parsed.getTime()) ? stamp : parsed.toLocaleString([], inAo3Zone());
  }

  /** the settings worth showing back, as words rather than as a json dump */
  protected settingsOf(run: RunHistory): string[] {
    const options = run.options ?? {};
    const said: string[] = [];
    if (options['reindex'] === false) {
      said.push(options['recheck'] ? 'no reindexing - each indexed work looked up on AO3' : 'no reindexing');
    }
    if (options['pages']) said.push(`up to page ${options['pages']}`);
    if (Number(options['start'] ?? 1) > 1) said.push(`from page ${options['start']}`);
    if (options['order'] === 'updated' && !options['dates']) said.push('read by date updated');
    if (options['order'] === 'bookmarked' && options['dates']) said.push('read by date bookmarked');
    if (options['collectionWorks']) said.push('indexed and downloaded the works in them');
    if (options['subcollections']) said.push('with subcollections');
    if (options['parentCollections']) said.push('with parent collections');
    if (options['series']) said.push('all works from encountered series');
    if (options['images']) said.push('save images separately');
    return said;
  }

  /**
   * Whether History offers Retry on a run: every run that has ended. One still going is
   * paused and resumed in its own window, and one only a different helper is running is
   * that helper's. Which ways it can be retried is the helper's to say, in the run window.
   */
  protected canRetry(run: RunHistory): boolean {
    if (run.status !== 'running') return true;
    return this.jobs.isThisHelpers(run) && !this.activeRuns().some((active) => active.id === run.id);
  }

  /** the other run of a resume, by id, for the link either way */
  protected runById(id: string | null | undefined): RunHistory | undefined {
    return id ? this.runs().find((run) => run.id === id) : undefined;
  }

  protected workLink(id: string): string {
    return `https://archiveofourown.org/works/${id}`;
  }
}

/** the parts of a run's history file its saved log is built from */
interface LogRecord {
  log?: string[];
  logTrimmed?: number;
  url?: string;
  filetypes?: string[];
  options?: Record<string, unknown>;
  settings?: Record<string, unknown>;
  background?: boolean;
  helper?: string;
}

/** one `# key: value` line each, under a heading - nothing at all when there is nothing */
function listed(title: string, values: Record<string, unknown>): string[] {
  const keys = Object.keys(values).sort();
  if (!keys.length) return [];
  return [
    `# ${title}:`,
    ...keys.map((key) => {
      const value = values[key];
      const shown = value === null || value === undefined ? ''
        : typeof value === 'object' ? JSON.stringify(value) : String(value);
      return `#   ${key}: ${shown}`;
    }),
  ];
}
