/**
 * Guest mode's runs: pretend ones, played out in the page.
 *
 * A guest can start any run the page offers and watch it go through every step - the
 * checklist, the progress bar, the log, a question, the report at the end - but **nothing
 * happens**: no request leaves the page, nothing is written to the library or its history, and
 * the run is gone once its window closes. `GuestHelper` (`guest-helper.ts`) answers the page's
 * requests to the helper, and starts one of these for each run.
 *
 * The checklist is the helper's own (`server.step_plan`), ported below with the helper's own
 * labels (`strings.STEP_*`), so a pretend run lists exactly the steps a real one would for the
 * same choices. `test_guest_steps.py` holds the labels to `strings.py`; keep `guestPlan` in step
 * with `step_plan` when that changes. What each step says and how long it takes is made up,
 * from the dummy library on screen, worded the way the helper words its own lines.
 */

import type { JobAction, JobEvent, RescuedWork } from './jobs';

/** the username a guest's login fills itself in with */
export const GUEST_USERNAME = 'dark_knight_xox_111';

/** the helper's own words for each step (`strings.STEP_*`) - `test_guest_steps.py` checks them */
export const GUEST_STEP_LABELS = {
  STEP_LOGIN: 'Log in to AO3',
  STEP_INDEX_ALL: 'Index every bookmark',
  STEP_INDEX_NEW: 'Index bookmarks added since last time',
  STEP_INDEX_BOOKMARKED_SINCE: 'Index bookmarks added since your last run',
  STEP_INDEX_SINCE: 'Index works AO3 has updated since your last run',
  STEP_INDEX_BOOKMARKED_WINDOW: 'Index bookmarks added in that date range',
  STEP_INDEX_UPDATED_WINDOW: 'Index works AO3 updated in that date range',
  STEP_INDEX_ONE: 'Index this fic',
  STEP_INDEX_MANY: 'Index these fics',
  STEP_INDEX_IMPORT: 'Index the works found in your library',
  STEP_INDEX_COLLECTIONS: 'Index your collections',
  STEP_INDEX_COLLECTION: 'Index this collection',
  STEP_INDEX_COLLECTIONS_WORKS: 'Index your collections and the works in them',
  STEP_INDEX_COLLECTION_WORKS: 'Index this collection and the works in it',
  STEP_USE_INDEX: 'Read the index already saved',
  STEP_CHECK_FILES: 'Read your existing downloaded files',
  STEP_DOWNLOAD: 'Download or update works as necessary',
  STEP_DOWNLOAD_ONE: 'Download this fic',
  STEP_DOWNLOAD_MANY: 'Download these fics',
  STEP_DOWNLOAD_IMPORT: 'Download the formats asked for',
  STEP_DOWNLOAD_NEW: 'Download newly added works',
  STEP_READ_INDEX: 'Read existing index for unfinished fics',
  STEP_INDEX_WINDOW: 'Index works AO3 has updated since that date',
  STEP_READ_WINDOW: 'Find indexed works updated in that date range',
  STEP_READ_BOOKMARKED_WINDOW: 'Find indexed works bookmarked in that date range',
  STEP_READ_RECHECK: 'Read every work in your index',
  STEP_UPDATE_WINDOW: 'Download or update each fic as necessary',
  STEP_UPDATE: 'Re-index each fic, then download or update as necessary',
  STEP_FILL_GAPS: 'Fetch any format still missing',
  STEP_IMAGES: 'Save embedded images separately',
  STEP_REPORT: 'Report any failures',
  STEP_SERIES: 'Index works in series marked for walkthrough',
  STEP_NON_BOOKMARKS: 'Check remaining non-bookmarks for updates',
  STEP_CLEANUP: 'Cleanup',
  STEP_FICHUB: 'Try FicHub for works AO3 would not give us',
} as const;

/** the helper's names for each run (`strings.ACTION_NAME_*`) */
export const GUEST_ACTION_NAMES: Record<string, string> = {
  bookmarks: '(Full scan) Reindex & Update All',
  update: 'Just update any bookmarks marked as incomplete',
  collections: 'Index my collections',
  collection: 'Index collection by URL',
  new: 'Just download newly added bookmarks',
  sync: 'Download new bookmarks and update incomplete fics',
  work: 'Download/update a specific fic',
  works: 'Download/update several fics',
  import: 'Import works found in your library',
  custom: 'Custom run',
  quick: 'Quick Scan',
};

const L = GUEST_STEP_LABELS;
export type GuestStep = { id: string; label: string };
type Options = Record<string, unknown>;

/**
 * The checklist a run with these choices works through - `server.step_plan`, line for line,
 * after the clamps `do_POST` applies (a collection run without its works writes only json).
 */
export function guestPlan(action: JobAction, filetypes: string[], options: Options): GuestStep[] {
  const downloads = filetypes.filter((x) => x !== 'JSON');
  const metadata = filetypes.includes('JSON');
  const step = (id: string, label: string): GuestStep => ({ id, label });
  const plan: GuestStep[] = [step('login', L.STEP_LOGIN)];
  const nonBookmarks =
    !!options['nonBookmarks'] &&
    ['bookmarks', 'quick', 'custom'].includes(action) &&
    metadata &&
    (action !== 'custom' || reindexes(options));

  if (action === 'collections' || action === 'collection') {
    const works = !!options['collectionWorks'];
    if (action === 'collections') {
      plan.push(step('collections', works ? L.STEP_INDEX_COLLECTIONS_WORKS : L.STEP_INDEX_COLLECTIONS));
    } else {
      plan.push(step('collection', works ? L.STEP_INDEX_COLLECTION_WORKS : L.STEP_INDEX_COLLECTION));
    }
    if (works && options['series']) plan.push(step('series', L.STEP_SERIES));
    if (works && downloads.length) {
      plan.push(step('check', L.STEP_CHECK_FILES), step('download', L.STEP_DOWNLOAD));
    }
  } else if (action === 'import') {
    plan.push(step('index', L.STEP_INDEX_IMPORT));
    if (downloads.length || options['replaceOutdated']) {
      plan.push(step('check', L.STEP_CHECK_FILES), step('download', L.STEP_DOWNLOAD_IMPORT));
    }
  } else if (action === 'work' || action === 'works') {
    const one = action === 'work';
    plan.push(step('index', one ? L.STEP_INDEX_ONE : L.STEP_INDEX_MANY), step('series', L.STEP_SERIES));
    if (downloads.length) {
      plan.push(step('check', L.STEP_CHECK_FILES), step('download', one ? L.STEP_DOWNLOAD_ONE : L.STEP_DOWNLOAD_MANY));
    }
  } else if (action === 'update') {
    plan.push(step('read', L.STEP_READ_INDEX));
    if (downloads.length) plan.push(step('check', L.STEP_CHECK_FILES));
    plan.push(step('update', L.STEP_UPDATE));
  } else if (action === 'new' || action === 'sync') {
    plan.push(step('index', L.STEP_INDEX_NEW), step('series', L.STEP_SERIES));
    if (downloads.length) plan.push(step('check', L.STEP_CHECK_FILES), step('download', L.STEP_DOWNLOAD_NEW));
    if (action === 'sync') {
      plan.push(step('update', L.STEP_UPDATE));
      if (downloads.length) plan.push(step('gaps', L.STEP_FILL_GAPS));
    }
  } else {
    const indexing = action !== 'custom' || reindexes(options);
    const recheck = action === 'custom' && !!options['recheck'] && !reindexes(options) && !options['dates'];
    if (action === 'custom' && (options['dates'] || recheck)) {
      const window: GuestStep[] = [step('login', L.STEP_LOGIN)];
      // a range of dates bookmarked reads the listing, and picks works, by that date
      const bookmarked = options['order'] === 'bookmarked' && !recheck;
      if (metadata) window.push(step('index', bookmarked ? L.STEP_INDEX_BOOKMARKED_WINDOW : L.STEP_INDEX_WINDOW));
      window.push(step('read', recheck ? L.STEP_READ_RECHECK : bookmarked ? L.STEP_READ_BOOKMARKED_WINDOW : L.STEP_READ_WINDOW),
        step('series', L.STEP_SERIES));
      if (nonBookmarks) window.push(step('nonbookmarks', L.STEP_NON_BOOKMARKS));
      window.push(
        step('check', L.STEP_CHECK_FILES),
        step('update', L.STEP_UPDATE_WINDOW),
        step('fichub', L.STEP_FICHUB),
        step('cleanup', L.STEP_CLEANUP),
        step('report', L.STEP_REPORT),
      );
      return window;
    }
    if (action === 'quick') {
      if (options['dates']) {
        plan.push(step('bookmarked', L.STEP_INDEX_BOOKMARKED_WINDOW), step('index', L.STEP_INDEX_UPDATED_WINDOW));
      } else {
        plan.push(step('bookmarked', L.STEP_INDEX_BOOKMARKED_SINCE), step('index', L.STEP_INDEX_SINCE));
      }
    } else if (indexing && metadata) {
      plan.push(step('index', L.STEP_INDEX_ALL));
    } else {
      plan.push(step('index', L.STEP_USE_INDEX));
    }
    plan.push(step('series', L.STEP_SERIES));
    if (nonBookmarks) plan.push(step('nonbookmarks', L.STEP_NON_BOOKMARKS));
    if (downloads.length) plan.push(step('check', L.STEP_CHECK_FILES), step('download', L.STEP_DOWNLOAD));
    if (options['images'] && action === 'custom') plan.push(step('images', L.STEP_IMAGES));
  }
  plan.push(step('fichub', L.STEP_FICHUB), step('cleanup', L.STEP_CLEANUP), step('report', L.STEP_REPORT));
  return plan;
}

/** a custom run indexes unless told not to - the helper's own default (`resolve_options`) */
function reindexes(options: Options): boolean {
  return options['reindex'] !== false;
}

/** a work of the dummy library, as a pretend run talks about it */
export interface GuestWork {
  id: string;
  title: string;
  author: string;
  updated: string;
}

/** what a pretend run is started with: the start request, and the library on screen */
export interface GuestRunRequest {
  action: JobAction;
  filetypes: string[];
  options: Options;
  /** a fic run's link(s), one to a line */
  url?: string;
  username: string;
  ao3TimeZone?: string;
  works: GuestWork[];
  collections: string[];
}

/** a stop, pressed in the run window */
class Stopped extends Error {}
/** debug's Skip this step - not offered to a guest, but answered all the same */
class Skipped extends Error {}

/** how long a pretend run's question waits for an answer before taking its default */
export const GUEST_QUESTION_SECONDS = 10;

/** how long the pretend parts take, in ms - slow enough to follow, and the whole run still over in about a minute */
export const GUEST_PACE = { page: 1000, file: 110, format: 400, work: 650, step: 550, login: 1700, question: GUEST_QUESTION_SECONDS * 1000 };

/**
 * One pretend run: plays its events out over time, to whoever is listening, exactly as the
 * helper streams a real one - and stops, pauses, resumes and takes an answer the same way.
 */
export class GuestRun {
  readonly events: JobEvent[] = [];
  private readonly listeners = new Set<(event: JobEvent) => void>();
  done = false;
  private cancelled = false;
  private skipping = false;
  held = false;
  private holdAsked = false;
  private answer: ((choice: string) => void) | null = null;
  readonly started = new Date().toISOString();
  /** the checklist step it is on, for `GET /api/jobs` */
  current = '';
  readonly plan: GuestStep[];

  constructor(
    readonly id: string,
    readonly request: GuestRunRequest,
    private readonly pace = GUEST_PACE,
  ) {
    this.plan = guestPlan(request.action, request.filetypes, request.options);
  }

  /** every event so far, then each as it comes; returns how to stop listening */
  listen(onEvent: (event: JobEvent) => void, onEnd: () => void): () => void {
    for (const event of this.events) onEvent(event);
    if (this.done) {
      onEnd();
      return () => {};
    }
    const listener = (event: JobEvent) => {
      onEvent(event);
      if (event.type === 'finished' || event.type === 'failed') onEnd();
    };
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  stop(): void {
    this.cancelled = true;
  }
  pause(): void {
    this.holdAsked = true;
  }
  resume(): void {
    this.holdAsked = false;
  }
  skip(): void {
    this.skipping = true;
  }
  reply(choice: string): boolean {
    if (!this.answer) return false;
    this.answer(choice);
    return true;
  }

  private emit(event: JobEvent): void {
    this.events.push(event);
    for (const listener of [...this.listeners]) listener(event);
    if (event.type === 'finished' || event.type === 'failed') {
      this.done = true;
      this.listeners.clear();
    }
  }

  private say(text: string): void {
    this.emit({ type: 'message', text, at: new Date().toISOString() });
  }

  private mark(id: string, status: 'running' | 'done' | 'skipped' | 'failed'): void {
    if (!this.plan.some((x) => x.id === id)) return;
    if (status === 'running') this.current = this.plan.find((x) => x.id === id)?.label ?? '';
    this.emit({ type: 'step', id, status });
  }

  /** a wait that a stop ends, a pause holds, and a skip cuts short */
  private async wait(ms: number): Promise<void> {
    let left = ms;
    // checked even for no wait at all, so a stop lands on a step that does not wait
    do {
      if (this.cancelled) throw new Stopped();
      if (this.skipping) {
        this.skipping = false;
        throw new Skipped();
      }
      if (this.holdAsked && !this.held) {
        this.held = true;
        this.emit({ type: 'held' });
      }
      if (!this.holdAsked && this.held) {
        this.held = false;
        this.emit({ type: 'released' });
      }
      if (left <= 0 && !this.held) return;
      const slice = Math.min(100, Math.max(left, 1));
      await new Promise((resolve) => setTimeout(resolve, slice));
      if (!this.held) left -= slice;
    } while (left > 0 || this.held);
    if (this.cancelled) throw new Stopped();
  }

  /**
   * Ask the run window a question, and wait for its answer - or take its default on a stop, or
   * once `GUEST_QUESTION_SECONDS` have gone by with no answer, said in the log as the helper says
   * a question that timed out. A pause holds the clock, as it holds the rest of the run.
   */
  private ask(question: Omit<JobEvent, 'type'>, fallback: string): Promise<string> {
    const waitMs = this.pace.question;
    return new Promise((resolve) => {
      let left = waitMs;
      const check = setInterval(() => {
        if (!this.holdAsked) left -= 100;
        if (this.cancelled || left <= 0) {
          clearInterval(check);
          this.answer = null;
          if (!this.cancelled) this.say(`nobody answered within ${Math.round(waitMs / 1000)} seconds - carrying on with the default: ${fallback}`);
          resolve(fallback);
        }
      }, 100);
      this.answer = (choice) => {
        clearInterval(check);
        this.answer = null;
        resolve(choice);
      };
      this.emit({ ...question, type: 'question' });
    });
  }

  /** play the run through; resolves once it has finished, stopped or failed */
  async play(): Promise<void> {
    const request = this.request;
    const downloads = request.filetypes.filter((x) => x !== 'JSON');
    this.emit({ type: 'started', action: request.action, filetypes: request.filetypes, options: request.options as never });
    this.emit({ type: 'steps', steps: this.plan });
    this.say('starting - this is a pretend run: nothing is fetched from AO3 or saved anywhere');
    const failures: { id: string; link: string; error: string }[] = [];
    const rescued: RescuedWork[] = [];
    const works = this.worksFor();
    try {
      for (const { id } of this.plan) {
        try {
          await this.playStep(id, works, downloads, failures, rescued);
        } catch (error) {
          if (!(error instanceof Skipped)) throw error;
          this.say('skipped this step, as asked');
          this.mark(id, 'skipped');
        }
      }
      this.say('done - a pretend run changes nothing, so the library on screen is as it was');
      this.emit({ type: 'finished' });
    } catch (error) {
      if (error instanceof Stopped) {
        this.say('stopped');
        this.emit({ type: 'finished', cancelled: true });
        return;
      }
      this.emit({ type: 'failed', error: error instanceof Error ? error.message : String(error) });
    }
  }

  /** the works this run talks about: the fics a fic run was given, else the library's */
  private worksFor(): GuestWork[] {
    const { action, url, works } = this.request;
    if (action === 'work' || action === 'works') {
      // a work's number, never a chapter's: from a link's /works/<n>, or a bare number
      const ids = (url ?? '')
        .split(/[\s,;]+/)
        .map((token) => /works\/(\d+)/.exec(token)?.[1] ?? (/^\d+$/.test(token) ? token : ''))
        .filter(Boolean);
      const byId = new Map(works.map((w) => [w.id, w]));
      return [...new Set(ids)].map((id, n) =>
        byId.get(id) ?? { id, title: `A Fic Found by Its Link ${n + 1}`, author: 'Example_Writer', updated: today() },
      );
    }
    return works;
  }

  private fileName(work: GuestWork, format: string): string {
    return `${work.id} ${work.title} - ${work.author} ${work.updated || today()}.${format.toLowerCase()}`;
  }

  private async playStep(
    id: string,
    works: GuestWork[],
    downloads: string[],
    failures: { id: string; link: string; error: string }[],
    rescued: RescuedWork[],
  ): Promise<void> {
    const { action, options } = this.request;
    const pace = this.pace;
    switch (id) {
      case 'login': {
        this.say(`AO3's dates are read as dates in ${this.request.ao3TimeZone || 'UTC'}`);
        if (options['skipLogin']) {
          this.say('not logging in - only what anyone may see on AO3 is fetched');
          this.mark('login', 'skipped');
          return;
        }
        this.mark('login', 'running');
        this.emit({ type: 'phase', name: 'authenticating' });
        this.say(`logging in as ${this.request.username || GUEST_USERNAME}`);
        await this.wait(pace.login);
        this.say('successfully logged in');
        this.emit({ type: 'authenticated', username: this.request.username || GUEST_USERNAME });
        this.mark('login', 'done');
        return;
      }
      case 'index':
      case 'bookmarked': {
        this.mark(id, 'running');
        this.emit({ type: 'phase', name: 'indexing' });
        if (action === 'work' || action === 'works' || action === 'import') {
          for (const [n, work] of works.slice(0, 8).entries()) {
            this.emit({ type: 'work', title: work.title, done: n, total: Math.min(8, works.length) });
            this.say(`looking up work ${work.id} on AO3`);
            await this.wait(pace.work);
            this.say(`index updated for work ${work.id}`);
          }
        } else if (this.plan.find((x) => x.id === id)?.label === L.STEP_USE_INDEX) {
          this.say(`read ${works.length} works from the index already saved`);
          await this.wait(pace.step);
        } else {
          await this.walk(id === 'bookmarked' ? 'bookmarked' : 'updated', works);
        }
        this.mark(id, 'done');
        return;
      }
      case 'collections':
      case 'collection': {
        this.mark(id, 'running');
        this.emit({ type: 'phase', name: 'collections' });
        const names = this.request.collections.length ? this.request.collections : ['example_collection'];
        for (const name of action === 'collection' ? names.slice(0, 1) : names) {
          this.say(`reading collection ${name}`);
          await this.walk('collection', works.slice(0, 30));
          this.say(`collection ${name} saved`);
        }
        this.mark(id, 'done');
        return;
      }
      case 'series': {
        this.mark(id, 'running');
        await this.wait(pace.step);
        this.say(options['series'] ? 'no series marked for walkthrough on this run' : 'no series to walk through');
        this.mark(id, 'skipped');
        return;
      }
      case 'nonbookmarks': {
        this.mark(id, 'running');
        this.say('checking 3 works that are not bookmarks for updates');
        for (const work of works.slice(-3)) {
          await this.wait(pace.work);
          this.say(`  ${work.title}: up to date`);
        }
        this.mark(id, 'done');
        return;
      }
      case 'read': {
        this.mark(id, 'running');
        this.emit({ type: 'phase', name: 'scanning' });
        await this.wait(pace.step);
        const picked = this.picked(works);
        this.say(
          action === 'update'
            ? `${picked.length} unfinished fics in the index`
            : `${picked.length} indexed works updated in that date range`,
        );
        this.mark(id, 'done');
        return;
      }
      case 'check': {
        this.mark(id, 'running');
        this.emit({ type: 'phase', name: 'checking_files' });
        const total = Math.min(works.length, 40);
        for (let done = 1; done <= total; done += 4) {
          this.emit({ type: 'work', phase: 'scanning', done, total });
          await this.wait(pace.file);
        }
        this.say(`found downloaded files for ${Math.max(0, works.length - 3)} works`);
        this.mark(id, 'done');
        return;
      }
      case 'download':
      case 'update':
      case 'gaps': {
        this.mark(id, 'running');
        this.emit({ type: 'phase', name: id === 'download' ? 'downloading' : 'updating' });
        const list = id === 'download' ? this.picked(works) : this.picked(works).slice(0, 3);
        const formats = downloads.length ? downloads : ['HTML'];
        for (const [n, work] of list.entries()) {
          this.emit({ type: 'work', title: work.title, done: n, total: list.length });
          this.say(`${work.title} (work ${work.id})`);
          if (id !== 'download') {
            this.say(`  reading the fic page for ${work.title}`);
            await this.wait(pace.work);
            this.say(`  index updated for work ${work.id}`);
          }
          // one work AO3 will not give, so the report and FicHub have something to show
          if (n === 1 && list.length > 2 && id === 'download' && !failures.length) {
            await this.wait(pace.format);
            this.say(`  could not download ${work.title}: AO3 answered 404 for every format`);
            failures.push({ id: work.id, link: `https://archiveofourown.org/works/${work.id}`, error: 'AO3 answered 404 (status 404)' });
            continue;
          }
          for (const format of formats) {
            this.emit({ type: 'work', title: work.title, filetype: format, done: n, total: list.length });
            await this.wait(pace.format);
            this.say(
              n % 3 === 2
                ? `    already have the current version in ${format}`
                : `    new download: ${this.fileName(work, format)}`,
            );
          }
        }
        this.emit({ type: 'work', done: list.length, total: list.length });
        if (!list.length) {
          this.say('nothing to download');
          this.mark(id, 'skipped');
          return;
        }
        this.mark(id, 'done');
        return;
      }
      case 'images': {
        this.mark(id, 'running');
        for (const work of this.picked(works).slice(0, 2)) {
          await this.wait(pace.work);
          this.say(`  no embedded images in ${work.title}`);
        }
        this.mark(id, 'done');
        return;
      }
      case 'fichub': {
        if (!failures.length) {
          this.mark(id, 'skipped');
          return;
        }
        const ids = failures.map((x) => x.id);
        this.say(`${ids.length} works could not be fetched from AO3 (${ids.join(', ')}). Asking whether to try FicHub`);
        const choice = await this.ask(
          { name: 'fichub', count: ids.length, ids, choices: ['yes', 'no'], default: 'yes', timeoutMinutes: GUEST_QUESTION_SECONDS / 60 },
          'yes',
        );
        if (choice !== 'yes') {
          this.say('FicHub not asked');
          this.mark(id, 'skipped');
          return;
        }
        this.mark(id, 'running');
        this.emit({ type: 'phase', name: 'fichub' });
        this.say(`trying FicHub for ${ids.length} works: ${ids.join(', ')}`);
        for (const failure of failures.splice(0)) {
          const work = works.find((w) => w.id === failure.id);
          await this.wait(pace.work);
          this.say(`  found work ${failure.id} on FicHub`);
          const formats = (downloads.length ? downloads : ['HTML']).filter((x) => x !== 'AZW3');
          for (const format of formats) {
            await this.wait(pace.format);
            if (work) this.say(`    new download: ${this.fileName(work, format)}`);
          }
          rescued.push({ id: failure.id, link: failure.link, title: work?.title ?? failure.id, downloaded: formats });
        }
        this.emit({ type: 'rescued', rescued });
        this.mark(id, 'done');
        return;
      }
      case 'cleanup': {
        this.mark(id, 'running');
        await this.wait(pace.step);
        this.mark(id, 'done');
        return;
      }
      case 'report': {
        this.mark(id, 'running');
        this.emit({ type: 'failures', failures });
        this.emit({ type: 'skipped', skipped: [] });
        this.say(failures.length ? `${failures.length} works could not be downloaded` : 'every work asked for arrived');
        this.mark(id, 'done');
        return;
      }
    }
  }

  /** the works a run downloads: a handful of the newest, so the run is over quickly */
  private picked(works: GuestWork[]): GuestWork[] {
    const { action } = this.request;
    if (action === 'work') return works.slice(0, 1);
    if (action === 'works' || action === 'import') return works.slice(0, 6);
    return works.slice(0, action === 'bookmarks' || action === 'custom' ? 7 : 5);
  }

  /**
   * A listing walked page by page, as the helper narrates one: 'fetching page' before each,
   * 'finished page' after. A walk that can stop early (a quick scan's floor, a collection's
   * count) never states a total, as the helper's do not.
   */
  private async walk(kind: 'bookmarked' | 'updated' | 'collection', works: GuestWork[]): Promise<void> {
    const openEnded = this.request.action === 'quick' || this.request.action === 'new' || this.request.action === 'sync';
    const pages = openEnded ? 2 : Math.max(2, Math.min(5, Math.ceil(works.length / 20)));
    let found = 0;
    if (kind === 'bookmarked') this.say('walking your bookmarks, newest bookmarked first');
    if (kind === 'updated') this.say('walking your bookmarks, most recently updated first');
    for (let page = 1; page <= pages; page++) {
      const total = openEnded || page === 1 ? undefined : pages;
      this.emit({ type: 'page', fetching: true, page, total, listingPage: page, listingTotal: total });
      this.say(total ? `fetching page ${page} of ${total}` : `fetching page ${page}`);
      await this.wait(this.pace.page);
      found = Math.min(works.length, found + (openEnded ? 6 : 20));
      this.emit({ type: 'page', page, total: openEnded ? undefined : pages, listingPage: page,
        listingTotal: openEnded ? undefined : pages, works: found });
      this.say(openEnded ? `finished page ${page}. ${found} works so far` : `finished page ${page} of ${pages}. ${found} works so far`);
    }
    if (openEnded) this.say('reached works already indexed before your last run - stopping here');
  }
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}
