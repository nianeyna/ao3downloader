import {
  Component,
  ElementRef,
  Injectable,
  OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { HelperConnection } from './helper-connection';
import { Jobs } from './jobs';
import { Library } from './library';
import { issuesOf, saveText } from './issues';
import { DropboxLibraryStore, LibraryStore, LocalLibraryStore, readRunHistory } from './library-store';
import type { RunHistory } from './jobs';
import { safeGet } from './storage';
import { SAVED_USERNAME_KEY, ao3TimeZone } from './preferences';
import { VisitLog } from './visit-log';

/**
 * The feedback tab on the right edge of every page, and the form it opens.
 *
 * A submission goes to the feedback Worker (`feedback_worker/`),
 * never to the helper: the Worker holds the GitHub token and opens an issue labelled
 * `feedback` and its kind (general feedback, a feature suggestion or a bug report). So nobody leaves the page or signs up for anything,
 * and a hosted copy's helper is never asked to do it. A bot
 * check stands in front of it - the page shows the widget, the Worker checks its token.
 *
 * The tab is only there when the build was given the Worker's address and the widget's site
 * key (`feedbackUrl`, `turnstileSiteKey` in app-config.json) - a copy built on this computer
 * has neither, and a form that could never be sent is not offered.
 */

/** what kind of feedback it is - general to begin with; the Worker labels the issue by it */
export type FeedbackKind = 'general' | 'feature' | 'bug';

export const FEEDBACK_KINDS: { value: FeedbackKind; label: string; title: string }[] = [
  { value: 'general', label: 'General feedback', title: 'Feedback' },
  { value: 'feature', label: 'Feature suggestion', title: 'Feature suggestion' },
  { value: 'bug', label: 'Bug report', title: 'Bug report' },
];

/** a quick question, answered 1 to 5 by one of five words - the Worker's `RATINGS`, keyed the same */
export type RatingKey = 'easy' | 'useful' | 'confusing' | 'complete';

/**
 * The optional quick questions, folded away to begin with. Each is five radio buttons, its
 * words in `scale` (1 first - the Worker's `scale`, which the issue says), none picked to begin
 * with: unanswered until one is, and not sent unless one is. Clear unpicks it.
 */
export const RATING_QUESTIONS: { key: RatingKey; question: string; scale: string[] }[] = [
  { key: 'easy', question: 'How easy is FicFairy to use?',
    scale: ['Very hard', 'Hard', 'Neutral', 'Easy', 'Very easy'] },
  { key: 'useful', question: 'How useful do you find it?',
    scale: ['Not useful', 'Slightly useful', 'Neutral', 'Useful', 'Very useful'] },
  { key: 'confusing', question: 'How confusing do you find it?',
    scale: ['Not at all confusing', 'Slightly confusing', 'Neutral', 'Confusing', 'Very confusing'] },
  { key: 'complete', question: 'Does it do everything you want?',
    scale: ['Missing a lot', 'Missing some', 'Neutral', 'Mostly', 'Does everything I want'] },
];

/** what is said in place of the AO3 username in an attached log */
export const USERNAME_REMOVED = '[your AO3 username]';

const TURNSTILE_SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
/** the same remembered username the run window fills in */
const USERNAME_KEY = SAVED_USERNAME_KEY;
/** the Worker's own limits - anything longer it refuses (message, name) or trims (the log) */
export const MESSAGE_LIMIT = 5000;
export const NAME_LIMIT = 100;
/** how long a send may take before it counts as failed, rather than 'Sending...' for ever */
export const SEND_TIMEOUT_MS = 30_000;
/**
 * GitHub refuses an issue whose body is longer than this, so feedback is held at it.
 * `ISSUE_RESERVE` is kept for everything the Worker adds around what was written - the
 * kind, the name (up to `NAME_LIMIT`), version, copy, library kind, browser (up to 300), the
 * quick questions' answers, the headings and the folds and fences around each log - generously,
 * so a count the page says fits always does.
 */
export const ISSUE_BODY_LIMIT = 65536;
export const ISSUE_RESERVE = 1500;

/** how long the issue would be: the message and each log as they will be sent, plus the reserve */
export function issueLength(message: string, log: string, visit: string): number {
  return ISSUE_RESERVE + message.length + log.length + visit.length;
}

/** at most this much of a run's log goes with feedback - its newest part - the Worker's `LIMITS.log` */
export const LOG_ATTACH_LIMIT = 60000;

/** at most this much of the visit's log goes with feedback - its newest part, where a bug is */
export const VISIT_ATTACH_LIMIT = 30000;
/** the line an attached visit log opens with when its earlier part was left out */
export const VISIT_CUT_NOTE = '(earlier entries left out - this is the most recent part of the visit log)';

/** the line an attached run log carries, under its heading, when its earlier part was left out */
export const LOG_CUT_NOTE = '(earlier lines left out - this is the most recent part of the run log)';

/** how much of a log goes with feedback: as much as its cap takes, or only its last lines */
export type LogAmount = 'most' | 1000 | 500 | 100;
export const LOG_AMOUNTS: LogAmount[] = ['most', 1000, 500, 100];
/** the least of a log that Trim to fit keeps rather than leave it next to nothing */
export const TRIM_KEEPS_AT_LEAST = 1000;

/**
 * The newest part of a log that goes with feedback: its last `lines` lines (when a number),
 * then at most `limit` characters of those, from a whole line - opening with `note` whenever
 * anything was left out. `limit` too small to hold even the note leaves the note alone.
 */
export function logExcerpt(text: string, amount: 'most' | number, limit: number, note: string): { text: string; cut: boolean } {
  let kept = text;
  let cut = false;
  if (amount !== 'most') {
    const all = text.split('\n');
    if (all.length > amount) {
      kept = all.slice(-amount).join('\n');
      cut = true;
    }
  }
  if (limit <= note.length + 1) return { text: text ? note : '', cut: !!text };
  if (cut && kept.length + note.length + 1 <= limit) return { text: `${note}\n${kept}`, cut };
  const part = newestPart(kept, limit, note);
  return { text: part.text, cut: cut || part.cut };
}

/** the newest part of a log, at most `limit` long, starting on a whole line, and whether any was left out */
export function newestPart(text: string, limit = VISIT_ATTACH_LIMIT, note = VISIT_CUT_NOTE): { text: string; cut: boolean } {
  if (text.length <= limit) return { text, cut: false };
  const tail = text.slice(text.length - (limit - note.length - 1));
  const start = tail.indexOf('\n');
  return { text: `${note}\n${start >= 0 ? tail.slice(start + 1) : tail}`, cut: true };
}

/** GitHub's new-issue page takes the text in its address, which browsers cap; the log never goes */
const PREFILL_LIMIT = 4000;

/**
 * The bot-check widget, behind a seam: the tests stand in for it, since it cannot load
 * in jsdom. `render` resolves to the widget's id once it is on the page.
 */
@Injectable({ providedIn: 'root' })
export class Turnstile {
  private loading: Promise<TurnstileApi> | null = null;

  async render(element: HTMLElement, siteKey: string, token: (value: string) => void): Promise<string> {
    const api = await this.load();
    return api.render(element, {
      sitekey: siteKey,
      theme: 'dark',
      callback: (value: string) => token(value),
      'expired-callback': () => token(''),
      'error-callback': () => token(''),
    });
  }

  /** a token works once, so a refused submission needs a fresh check */
  reset(id: string): void {
    window.turnstile?.reset(id);
  }

  remove(id: string): void {
    window.turnstile?.remove(id);
  }

  private load(): Promise<TurnstileApi> {
    if (window.turnstile) return Promise.resolve(window.turnstile);
    // a failed load is not kept, so opening the form again tries again
    this.loading ??= new Promise<TurnstileApi>((resolve, reject) => {
      const script = document.createElement('script');
      script.src = TURNSTILE_SCRIPT;
      script.async = true;
      script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error('no turnstile')));
      script.onerror = () => {
        script.remove();
        reject(new Error('could not load the bot check'));
      };
      document.head.appendChild(script);
    }).catch((error) => {
      this.loading = null;
      throw error;
    });
    return this.loading;
  }
}

interface TurnstileApi {
  render(element: HTMLElement, options: Record<string, unknown>): string;
  reset(id: string): void;
  remove(id: string): void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

/** the newest run's log, with what it needs to be read */
export interface LatestLog {
  actionName: string;
  started: string;
  username: string;
  lines: string[];
  /** the run's overview, put on top of its log so a trimmed log still says which run it is */
  summary: string[];
}

/** What a run was and how it went, as History's entry says it, a line each. */
export function runSummary(record: Record<string, unknown>): string[] {
  const text = (value: unknown) => (typeof value === 'string' ? value : '');
  const count = (value: unknown) => (Array.isArray(value) ? value.length : 0);
  const lines = [`# ${text(record['actionName']) || text(record['action']) || 'a run'}`];
  lines.push(`Status: ${text(record['status']) || 'unknown'}`);
  lines.push(`Started: ${text(record['started']) || 'unknown'}`);
  lines.push(`Finished: ${text(record['finished']) || 'not finished'}`);
  if (text(record['error'])) lines.push(`Error: ${text(record['error'])}`);
  const filetypes = Array.isArray(record['filetypes']) ? record['filetypes'].map(String).join(', ') : '';
  if (filetypes) lines.push(`File types: ${filetypes}`);
  if (record['background']) lines.push('Ran in the background: yes');
  lines.push(`Re-indexed ${count(record['reindexed'])}, downloaded ${count(record['downloaded'])}, updated ${count(record['updated'])}`);
  const issues = issuesOf(record as unknown as RunHistory);
  const kinds: [number, string][] = [
    [issues.indexGaps?.length ?? 0, 'where indexing broke off'],
    [issues.failures.length, 'could not be downloaded'],
    [issues.keptCopies.length, 'to check by hand'],
    [issues.notRemoved.length, 'older copies not removed'],
    [issues.skipped.length, 'bookmarks that are not works'],
    [issues.fichubOlder?.length ?? 0, 'from an older FicHub copy'],
    [issues.repairClashes?.length ?? 0, 'not repaired: name clash'],
  ];
  const said = kinds.filter(([n]) => n).map(([n, what]) => `${n} ${what}`);
  lines.push(`Issues: ${said.length ? said.join('; ') : 'none'}`);
  const trimmed = Number(record['logTrimmed']) || 0;
  lines.push(`Log: ${count(record['log']).toLocaleString('en')} lines${trimmed ? ` (${trimmed.toLocaleString('en')} earlier lines dropped by the run itself)` : ''}`);
  return lines;
}

/**
 * A run still going, asked of the helper by the record's path: its file is saved only every
 * couple of minutes, and only as lines arrive, so it can be far behind what the run window shows.
 * Null when the run is not going, or the helper does not answer - the file is read then.
 */
export type LiveRecord = (path: string) => Promise<Record<string, unknown> | null>;

/** The newest run record in the library, or null when there is none or it will not read. */
export async function readLatestLog(store: LibraryStore, live?: LiveRecord): Promise<LatestLog | null> {
  try {
    // named for when they started, so the newest is last by name
    const newest = (await store.list('runs', false)).filter((path) => /\.json$/i.test(path)).sort().pop();
    return newest ? await readRunLog(store, newest, live) : null;
  } catch {
    return null;
  }
}

/** One run record's log, by its path in the library, or null when it will not read. */
export async function readRunLog(store: LibraryStore, path: string, live?: LiveRecord): Promise<LatestLog | null> {
  try {
    const going = live ? await live(path).catch(() => null) : null;
    const record = (going ?? JSON.parse((await store.read(path)) ?? '')) as Record<string, unknown>;
    if (!record || typeof record !== 'object') return null;
    const text = (value: unknown) => (typeof value === 'string' ? value : '');
    return {
      actionName: text(record['actionName']) || text(record['action']),
      started: text(record['started']),
      username: text(record['username']),
      lines: Array.isArray(record['log']) ? record['log'].map(String) : [],
      summary: runSummary(record),
    };
  } catch {
    return null;
  }
}

/** what is said in place of a file path in an attached log */
export const PATH_REMOVED = '[file path removed]';

/** what is said in place of a time zone named in an attached log */
export const ZONE_REMOVED = '[your time zone]';

/**
 * The log as it will be sent, with everything that could say who or where someone is taken out:
 *
 * - every AO3 username named, in any case;
 * - the AO3 time zone (`zones`), which names a region - not UTC, which names nobody;
 * - anything shaped like an IP address (v4 or v6) or an email address;
 * - every file path on a computer, whole (`C:\...`, `\\server\share\...`, `/home/...`, `file://...`) -
 *   a path names the folders someone keeps things in, and often their account name;
 * - anything that looks like a password.
 *
 * A run's log is made of work titles, links, file names and dates, and names none of those
 * things on purpose - a library is reached by paths inside it, never by where it lives - so
 * most of this is a backstop. It is done here because this is what the person sees before
 * sending; the Worker scrubs passwords again.
 */
export function redactLog(text: string, usernames: string[], zones: string[] = []): string {
  let redacted = text;
  const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const names = [...new Set(usernames.map((name) => name.trim()).filter(Boolean))]
    // longest first, so a name containing another is replaced whole
    .sort((a, b) => b.length - a.length);
  for (const name of names) {
    redacted = redacted.replace(new RegExp(escape(name), 'gi'), USERNAME_REMOVED);
  }
  const named = [...new Set(zones.map((zone) => zone.trim()))].filter(
    (zone) => zone && !/^(Etc\/)?(UTC|GMT|Universal|Zulu)$/i.test(zone),
  );
  for (const zone of named) {
    redacted = redacted.replace(new RegExp(escape(zone), 'g'), ZONE_REMOVED);
  }
  return redacted
    .replace(/[\w.+-]+@[\w-]+(\.[\w-]+)+/g, '[email removed]')
    .replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, '[IP address removed]')
    // v6: four or more groups (a time of day has three), or a :: shorthand between hex groups
    .replace(/\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}\b|\b[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*::(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*)?\b/gi, '[IP address removed]')
    .replace(/file:\/\/\S+/gi, PATH_REMOVED)
    // a Windows or network path, spaces and all, up to a colon, quote or line end
    .replace(/(?:\b[A-Za-z]:|\\\\[^\\\s]+)[\\/][^:*?"<>|\r\n]*/g, (path) => PATH_REMOVED + (path.match(/\s+$/)?.[0] ?? ''))
    // an absolute path elsewhere: two or more parts, starting where a word could, and - as a
    // name can hold spaces - running on to a colon, quote or line end, since taking too much
    // is the safe side. A link's own path follows its host, never a space, so AO3 links stay
    .replace(/(^|[\s"'(=\[])\/(?:[^\/\s"'<>|]+\/)+[^:*?"<>|\r\n]*/gm, (_, before: string) => `${before}${PATH_REMOVED}`)
    .replace(/(password["']?\s*[:=]\s*)("[^"]*"|'[^']*'|\S+)/gi, '$1[removed]');
}

type Stage = 'form' | 'sending' | 'sent';

@Component({
  selector: 'app-feedback',
  templateUrl: './feedback.html',
  styleUrl: './feedback.css',
  host: { '(document:keydown.escape)': 'escape()' },
})
export class Feedback implements OnDestroy {
  private readonly helper = inject(HelperConnection);
  private readonly library = inject(Library);
  private readonly jobs = inject(Jobs);
  private readonly turnstile = inject(Turnstile);
  private readonly visit = inject(VisitLog);

  /** whether this copy can send feedback at all */
  protected readonly offered = computed(() => !!this.helper.settings().feedbackUrl);
  protected readonly open = signal(false);
  protected readonly stage = signal<Stage>('form');

  protected readonly kind = signal<FeedbackKind | ''>('general');
  protected readonly kinds = FEEDBACK_KINDS;
  /** the quick questions moved off the middle - only these are sent */
  protected readonly ratings = signal<Partial<Record<RatingKey, number>>>({});
  protected readonly ratingQuestions = RATING_QUESTIONS;
  protected readonly message = signal('');
  protected readonly name = signal('');
  protected readonly attachLog = signal(false);
  /** this visit's own log (`VisitLog`) - for a bug outside a run - attached on its own tick */
  /** which run's log goes with the feedback: the most recent, or one picked from the history */
  protected readonly logChoice = signal<'latest' | 'choose'>('latest');
  /** the runs to choose from, read in the background as the form opens; null until read */
  protected readonly runList = signal<RunHistory[] | null>(null);
  protected readonly runListFailed = signal(false);
  /** the chosen run's file name in `runs/` */
  protected readonly chosenRun = signal('');
  /** the run history read the form's opening started - stopped if the form closes first */
  private historyAbort: AbortController | null = null;
  /** which preview read is the latest, so an earlier slower one never lands over it */
  private previewRead = 0;
  protected readonly attachVisit = signal(false);
  /** the visit's log as it stands, redacted, before any of it is left out, as the form opened (`takeVisit`) */
  private readonly visitText = signal('');
  /** how much of each log goes, and the most Trim to fit left room for (null: its own cap) */
  protected readonly visitAmount = signal<LogAmount>('most');
  protected readonly logAmount = signal<LogAmount>('most');
  protected readonly visitTrimmedTo = signal<number | null>(null);
  protected readonly logTrimmedTo = signal<number | null>(null);
  private readonly visitPart = computed(() =>
    logExcerpt(this.visitText(), this.visitAmount(), Math.min(VISIT_ATTACH_LIMIT, this.visitTrimmedTo() ?? Infinity), VISIT_CUT_NOTE));
  /** the visit's log exactly as it would be sent */
  protected readonly visitPreview = computed(() => this.visitPart().text);
  /** only the newest part of the visit's log is attached - the form says so */
  protected readonly visitCut = computed(() => this.visitPart().cut);
  protected readonly visitLines = computed(() => this.visitText() ? this.visitText().split('\n').length : 0);
  protected readonly logAmounts = LOG_AMOUNTS;
  /** the chosen run's overview and its log, redacted, before any of the log is left out */
  private readonly logRead = signal<{ head: string; body: string } | null>(null);
  private readonly logPart = computed(() => {
    const read = this.logRead();
    if (!read) return { text: '', cut: false };
    // the overview always goes, on top, and counts towards the cap like the rest
    const room = Math.min(LOG_ATTACH_LIMIT, this.logTrimmedTo() ?? Infinity) - read.head.length - 2;
    const part = logExcerpt(read.body, this.logAmount(), room, LOG_CUT_NOTE);
    return { text: `${read.head}\n\n${part.text}`, cut: part.cut };
  });
  /** only the newest part of the run's log is attached - the form says so */
  protected readonly logCut = computed(() => this.logPart().cut);
  protected readonly logLines = computed(() => this.logRead()?.body.split('\n').length ?? 0);
  protected readonly logAttachLimit = LOG_ATTACH_LIMIT;
  /** how full the message is: said near the limit, and at it, since the box stops taking more */
  protected readonly messageNearLimit = computed(() => this.message().length >= MESSAGE_LIMIT * 0.9);
  protected readonly messageAtLimit = computed(() => this.message().length >= MESSAGE_LIMIT);
  protected readonly nameNearLimit = computed(() => this.name().length >= NAME_LIMIT * 0.9);
  protected readonly nameAtLimit = computed(() => this.name().length >= NAME_LIMIT);
  /** the log exactly as it would be sent, once read; '' while reading or when there is none */
  protected readonly logPreview = computed(() => this.logPart().text);
  protected readonly logNote = signal('');
  /** the run log as it will be sent */
  private readonly logToSend = computed(() => (this.attachLog() ? this.logPreview() : ''));
  /** how long the issue would be, counted as it is typed and ticked */
  protected readonly issueChars = computed(() =>
    issueLength(this.message().trim(), this.logToSend(), this.attachVisit() ? this.visitPreview() : ''));
  /** over GitHub's limit: Send is held until something is taken off */
  protected readonly tooLong = computed(() => this.issueChars() > ISSUE_BODY_LIMIT);
  protected readonly overBy = computed(() => Math.max(0, this.issueChars() - ISSUE_BODY_LIMIT));
  protected readonly issueLimit = ISSUE_BODY_LIMIT;
  protected readonly issueReserve = ISSUE_RESERVE;
  protected readonly canAttach = computed(() => !!this.library.store());

  protected readonly token = signal('');
  protected readonly checkProblem = signal('');
  protected readonly problem = signal('');
  protected readonly sent = signal<{ number: number; url: string } | null>(null);

  protected readonly messageLimit = MESSAGE_LIMIT;
  protected readonly nameLimit = NAME_LIMIT;
  protected readonly visitAttachLimit = VISIT_ATTACH_LIMIT;
  /** whether Trim to fit could bring it under: the run's overview, at least, has to go whole */
  protected readonly canTrim = computed(() =>
    (this.attachLog() && !!this.logPreview()) || (this.attachVisit() && !!this.visitPreview()));
  private readonly repository = computed(() => `https://github.com/${this.helper.settings().releasesRepo}`);
  protected readonly feedbackList = computed(() => `${this.repository()}/issues?q=label%3Afeedback`);
  /** where to go when the form cannot be sent - it needs a GitHub account, so it is the fallback */
  protected readonly newIssue = computed(() => `${this.repository()}/issues/new`);
  /** the same, with what was written filled in - so sending it by hand loses nothing either */
  protected readonly newIssueFilled = computed(() => {
    const message = this.message().trim();
    const title = `${kindTitle(this.kind())}: ${message.split('\n')[0].slice(0, 60)}`;
    const body = message.length > PREFILL_LIMIT ? `${message.slice(0, PREFILL_LIMIT)}...` : message;
    const query = new URLSearchParams({ title, body });
    return `${this.newIssue()}?${query}`;
  });
  /** the form could not be sent, either way - the window then offers the text and GitHub */
  protected readonly failed = computed(() => !!this.problem() || !!this.checkProblem());
  protected readonly canSend = computed(
    () =>
      this.stage() === 'form' &&
      !!this.kind() &&
      !!this.message().trim() &&
      this.message().length <= MESSAGE_LIMIT &&
      this.name().length <= NAME_LIMIT &&
      !!this.token() &&
      !this.tooLong() &&
      (!this.attachLog() || !!this.logPreview()),
  );

  private readonly widget = viewChild<ElementRef<HTMLElement>>('check');
  private widgetId = '';

  constructor() {
    // the widget goes in when its place appears - the form opening - and nowhere else
    effect(() => {
      const element = this.widget()?.nativeElement;
      if (element) untracked(() => void this.mountCheck(element));
    });
  }

  ngOnDestroy(): void {
    this.unmountCheck();
  }

  /** opens the form - from the tab, or from the Report a bug page's button */
  show(): void {
    if (this.stage() === 'sent') this.reset();
    this.visit.note('Feedback form opened');
    this.open.set(true);
    // the visit's log is taken as it is now, once: what the preview shows from here is what
    // is sent, however long the form stays open. each opening takes it afresh
    this.takeVisit();
    this.readRunList();
  }

  /**
   * Read the runs to choose a log from, in the background: nothing waits on it but choosing
   * a run. What History last read is used as it is; otherwise the history is read, and that
   * read stops if the form closes first (`close`).
   */
  private readRunList(): void {
    const store = this.library.store();
    if (!store || this.runList()) return;
    const read = this.jobs.historyRead;
    if (read?.store === store) {
      this.runList.set(read.runs);
      return;
    }
    // one already reading is left to finish
    if (this.historyAbort) return;
    const abort = new AbortController();
    this.historyAbort = abort;
    this.runListFailed.set(false);
    readRunHistory(store, abort.signal).then(
      (runs) => {
        if (abort.signal.aborted) return;
        this.runList.set(runs);
        this.historyAbort = null;
      },
      () => {
        if (!abort.signal.aborted) this.runListFailed.set(true);
      },
    );
  }

  protected close(): void {
    // the run history read the opening started is not wanted any more
    if (this.historyAbort) {
      this.historyAbort.abort();
      this.historyAbort = null;
    }
    // read afresh next time, since a run may finish meanwhile - unless one was chosen from it
    if (!this.chosenRun()) this.runList.set(null);
    this.open.set(false);
    this.unmountCheck();
    // a sent form starts afresh next time; an unsent one keeps what was typed
    if (this.stage() === 'sent') this.reset();
  }

  protected escape(): void {
    if (this.open() && this.stage() !== 'sending') this.close();
  }

  /** the names the page knows - each one comes out of any log before it is shown or sent */
  private knownNames(extra = ''): string[] {
    return [extra, this.jobs.config()?.username ?? '', safeGet(USERNAME_KEY)];
  }

  protected toggleVisit(on: boolean): void {
    // the copy taken as the form opened, ticked or not - never read again while it is open
    this.attachVisit.set(on);
    this.visitTrimmedTo.set(null);
  }

  /** the visit's log as it stands as the form opens - the one copy the form shows and sends */
  private takeVisit(): void {
    this.visitText.set(redactLog(this.visit.text(), this.knownNames(), [ao3TimeZone()]));
  }

  protected async toggleLog(on: boolean): Promise<void> {
    this.attachLog.set(on);
    if (on) this.readRunList();
    await this.loadLogPreview();
  }

  protected async setLogChoice(choice: 'latest' | 'choose'): Promise<void> {
    this.logChoice.set(choice);
    await this.loadLogPreview();
  }

  protected async chooseRun(file: string): Promise<void> {
    this.chosenRun.set(file);
    await this.loadLogPreview();
  }

  /** what a run reads as in the list to choose from */
  protected runLabel(run: RunHistory): string {
    const when = new Date(run.started);
    const at = Number.isNaN(when.getTime()) ? run.started : when.toLocaleString();
    return `${run.actionName || run.action} - ${at} - ${run.status}`;
  }

  /**
   * A run still going is read from the helper, as History's Download log reads it - found among
   * the runs going by the id its file name ends with (`<started>-<id8>.json`)
   */
  private async liveRecord(path: string): Promise<Record<string, unknown> | null> {
    const short = path.replace(/\.json$/i, '').split('-').pop() ?? '';
    const run = short ? this.jobs.activeRuns().find((active) => active.id.startsWith(short)) : undefined;
    return run ? this.jobs.liveRecord(run.id) : null;
  }

  /** the log as it will be sent, for whichever run is chosen; empty (and Send held) until there is one */
  private async loadLogPreview(): Promise<void> {
    const read = ++this.previewRead;
    this.logRead.set(null);
    this.logTrimmedTo.set(null);
    this.logNote.set('');
    if (!this.attachLog()) return;
    const store = this.library.store();
    if (!store) return;
    const choosing = this.logChoice() === 'choose';
    if (choosing && !this.chosenRun()) return;
    const live = (path: string) => this.liveRecord(path);
    const log = choosing
      ? await readRunLog(store, `runs/${this.chosenRun()}`, live)
      : await readLatestLog(store, live);
    if (read !== this.previewRead || !this.attachLog()) return;
    if (!log || !log.lines.length) {
      this.logNote.set(choosing ? 'That run has no log to attach.' : 'There is no run log in this library to attach yet.');
      return;
    }
    const head = log.summary.join('\n');
    // trimmed here, as the Worker would, so what is shown is exactly what is sent - the
    // run's overview kept on top, since a trimmed log no longer says which run it is
    const names = this.knownNames(log.username);
    const shownHead = redactLog(head, names, [ao3TimeZone()]);
    const body = redactLog(log.lines.join('\n'), names, [ao3TimeZone()]);
    this.logRead.set({ head: shownHead, body });
  }

  /** how many characters of the logs fit beside what was written, once the reserve is kept */
  private logRoom(): number {
    return ISSUE_BODY_LIMIT - ISSUE_RESERVE - this.message().trim().length;
  }

  /**
   * Cut the attached logs down just far enough to send: the visit's log first, since a run's
   * usually says more, down to `TRIM_KEEPS_AT_LEAST`; then the run's log, whose overview always
   * stays. Newest lines are kept. Choosing how much of a log to attach puts its own back.
   */
  protected trimToFit(): void {
    const room = this.logRoom();
    const runLog = this.attachLog() ? this.logPreview().length : 0;
    if (this.attachVisit() && this.visitPreview()) {
      const visitRoom = room - runLog;
      const floor = Math.min(this.visitPreview().length, TRIM_KEEPS_AT_LEAST);
      this.visitTrimmedTo.set(Math.max(visitRoom, floor));
    }
    const visit = this.attachVisit() ? this.visitPreview().length : 0;
    if (this.attachLog() && runLog + visit > room) this.logTrimmedTo.set(Math.max(0, room - visit));
    this.visit.note(`Feedback: trimmed the attached logs to fit (${this.issueChars().toLocaleString('en')} characters)`);
  }

  /** whether Trim to fit has cut either log, so it can be undone */
  protected readonly trimmed = computed(() => this.logTrimmedTo() !== null || this.visitTrimmedTo() !== null);

  /** put back what Trim to fit cut - every line is still held, so nothing is lost */
  protected undoTrim(): void {
    this.logTrimmedTo.set(null);
    this.visitTrimmedTo.set(null);
    this.visit.note('Feedback: undid trim to fit');
  }

  protected setLogAmount(value: string): void {
    this.logAmount.set(value === 'most' ? 'most' : (Number(value) as LogAmount));
    this.logTrimmedTo.set(null);
  }

  protected setVisitAmount(value: string): void {
    this.visitAmount.set(value === 'most' ? 'most' : (Number(value) as LogAmount));
    this.visitTrimmedTo.set(null);
  }

  /** what a choice of how much of a log to attach is called */
  protected amountWords(amount: LogAmount, cap: number): string {
    return amount === 'most' ? `As much as fits (up to ${cap.toLocaleString('en')} characters)` : `The last ${amount.toLocaleString('en')} lines`;
  }

  protected async send(event?: Event): Promise<void> {
    event?.preventDefault();
    if (!this.canSend()) return;
    this.stage.set('sending');
    this.problem.set('');
    try {
      // offline is a failure like any other, said at once rather than after a timeout
      if (navigator.onLine === false) throw new Error('this computer is offline');
      const visit = this.attachVisit() ? this.visitPreview() : '';
      const response = await fetch(this.helper.settings().feedbackUrl, {
        method: 'POST',
        signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: this.kind(),
          ratings: this.ratings(),
          message: this.message().trim(),
          name: this.name().trim(),
          visit,
          log: this.logToSend(),
          version: this.helper.settings().version,
          copy: this.helper.isLocal() ? 'on their own computer' : 'the hosted page',
          storage: this.storageKind(),
          browser: navigator.userAgent,
          turnstileToken: this.token(),
        }),
      });
      const answer = (await response.json().catch(() => ({}))) as {
        number?: number;
        url?: string;
        error?: string;
      };
      if (!response.ok || !answer.url) {
        throw new Error(answer.error || `the feedback service answered ${response.status}`);
      }
      this.sent.set({ number: answer.number ?? 0, url: answer.url });
      this.stage.set('sent');
      this.unmountCheck();
    } catch (error) {
      this.problem.set(failureReason(error));
      this.stage.set('form');
      // a token works once: whatever happened to this one, the next try needs another
      this.token.set('');
      if (this.widgetId) this.turnstile.reset(this.widgetId);
    }
  }

  /**
   * Where the library the page has open lives - Dropbox or this computer - and nothing more.
   * Never the folder's name: the issue is public, and a folder can be named for its owner.
   */
  protected storageKind(): string {
    const store = this.library.store();
    if (store instanceof DropboxLibraryStore) return 'Dropbox';
    if (store instanceof LocalLibraryStore) return 'a folder on this computer';
    // a browser without a folder picker hands a folder over as files, which can be read only
    if (this.library.data()) return 'a folder on this computer (read only)';
    return 'no library open';
  }

  /** a quick question's word picked: answered from now on, until cleared */
  protected setRating(key: RatingKey, value: number): void {
    this.ratings.update((r) => ({ ...r, [key]: value }));
  }

  /** back to unanswered: no word picked, and nothing is sent for it */
  protected clearRating(key: RatingKey): void {
    this.ratings.update((r) => {
      const next = { ...r };
      delete next[key];
      return next;
    });
  }

  protected ratingOf(key: RatingKey): number | undefined {
    return this.ratings()[key];
  }

  /** how many of the quick questions are answered, for the fold's summary */
  protected readonly ratedCount = computed(() => Object.keys(this.ratings()).length);

  /** the answers as lines, for the saved copy of a feedback that could not be sent */
  private ratingLines(): string[] {
    return RATING_QUESTIONS.filter((q) => this.ratings()[q.key] !== undefined).map(
      (q) => `${q.question} ${q.scale[(this.ratings()[q.key] ?? 1) - 1]}`,
    );
  }

  /** everything that was written, as a file, so a failed send never loses it */
  protected downloadAttempt(): void {
    const lines = [
      '# FicFairy feedback - not sent',
      '',
      `Kind: ${FEEDBACK_KINDS.find((k) => k.value === this.kind())?.label ?? '(not chosen)'}`,
      ...this.ratingLines(),
      `Name: ${this.name().trim() || '(none given)'}`,
      `Version: ${this.helper.settings().version || '(built on this computer)'}`,
      `Library: ${this.storageKind()}`,
      `Written: ${new Date().toISOString()}`,
      '',
      '## Feedback',
      '',
      this.message().trim(),
    ];
    if (this.logToSend()) {
      lines.push('', '## Latest run log (AO3 username removed)', '', this.logPreview());
    }
    if (this.attachVisit() && this.visitPreview()) {
      lines.push('', '## What I did on this visit (AO3 username removed)', '', this.visitPreview());
    }
    saveText(lines.join('\n') + '\n', `ao3downloader-feedback-${new Date().toISOString().slice(0, 10)}`);
  }

  private reset(): void {
    this.stage.set('form');
    this.kind.set('general');
    this.ratings.set({});
    this.message.set('');
    this.name.set('');
    this.attachLog.set(false);
    this.logChoice.set('latest');
    this.chosenRun.set('');
    this.logRead.set(null);
    this.logTrimmedTo.set(null);
    this.logAmount.set('most');
    this.attachVisit.set(false);
    this.visitText.set('');
    this.visitTrimmedTo.set(null);
    this.visitAmount.set('most');
    this.logNote.set('');
    this.problem.set('');
    this.sent.set(null);
    this.token.set('');
  }

  private async mountCheck(element: HTMLElement): Promise<void> {
    this.unmountCheck();
    this.checkProblem.set('');
    try {
      const id = await this.turnstile.render(element, this.helper.settings().turnstileSiteKey, (value) =>
        this.token.set(value),
      );
      // closed while it loaded: the element it went into is gone
      if (!this.open() || this.widget()?.nativeElement !== element) {
        this.turnstile.remove(id);
        return;
      }
      this.widgetId = id;
    } catch {
      this.checkProblem.set(
        'The bot check would not load - this computer may be offline, or a blocker or this ' +
          'network may be stopping it.',
      );
    }
  }

  private unmountCheck(): void {
    if (this.widgetId) this.turnstile.remove(this.widgetId);
    this.widgetId = '';
    this.token.set('');
  }
}

/** why a send failed, in words for the failure panel */
export function failureReason(error: unknown): string {
  if (error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
    return 'the feedback service took too long to answer';
  }
  const reason = error instanceof Error ? error.message : String(error);
  // what a browser says when it never got an answer at all: offline, blocked, or the service down
  if (error instanceof TypeError) return 'the feedback service could not be reached';
  return reason || 'something went wrong';
}

/** how an issue's title names a kind of feedback, as the Worker does */
export function kindTitle(kind: FeedbackKind | ''): string {
  return FEEDBACK_KINDS.find((k) => k.value === kind)?.title ?? 'Feedback';
}
