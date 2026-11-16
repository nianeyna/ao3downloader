import { DebugMode } from './debug-mode';
import { ImportRequest } from './imports';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Chime, ChimePlayer } from './chime';
import { DownloadDialog, GUEST_WORK, GUEST_WORKS, parseWorkList, startProgramFor } from './download-dialog';
import { DEFAULT_PAGE_CONFIG, HelperConnection } from './helper-connection';
import { RUN_LOG_LINES_KEY, TRIM_OLD_RUN_LOGS_KEY } from './run-logs';
import { VisitLog } from './visit-log';
import { Library } from './library';
import { LibraryStore, StorageRequest } from './library-store';
import {
  ActiveRun,
  AnswerChoice,
  JobAction,
  JobEvent,
  RetryableRun,
  RunHistory,
  Jobs,
  ServerConfig,
  StartRequest,
  UndatedChoice,
} from './jobs';
import { AO3_TIME_ZONE_KEY, zonedDayToUtc } from './preferences';

const CONFIG: ServerConfig = {
  username: 'Someone',
  filetypes: ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML', 'JSON'],
  forced: ['JSON'],
  defaults: ['JSON', 'HTML'],
  settings: {
    file: 'C:\\app\\config\\settings.ini',
    extraWaitTime: 15,
    fileNamePattern: '{worknum} {title} - {author} {date updated}',
    fileNameLength: 50,
    fileNameExample: '1234567 The Trees Are Burning - library_of_alexandria 2026-08-23.html',
    maxRetries: 0,
    maxTimeouts: 3,
    debugLogging: false,
  },
};

/** a library that is open, as far as the dialog needs one */
function fakeStore(label: string): LibraryStore {
  const nothing = async () => {
    throw new Error('not used here');
  };
  return {
    label,
    check: async () => {},
    list: nothing,
    read: nothing,
    write: nothing,
    size: nothing,
    delete: nothing,
    rename: nothing,
    mkdir: nothing,
  };
}

/** how many times the whole list of runs to retry was asked for */
let listsRead = 0;

class FakeJobs extends Jobs {
  started: StartRequest[] = [];
  /** the scans the helper would offer as floors */
  floorRunsOnRecord: RunHistory[] = [];

  override async loadFloorRuns(): Promise<RunHistory[] | null> {
    return this.floorRunsOnRecord;
  }

  override async loadNewestFloor(): Promise<RunHistory | null> {
    return this.floorRunsOnRecord[0] ?? null;
  }

  override async refreshActiveRuns(): Promise<ActiveRun[] | null> {
    return this.activeRuns();
  }

  /** the ended runs the helper would offer for retrying */
  retryableOnRecord: RetryableRun[] = [];

  override async loadRetryableRuns(): Promise<RetryableRun[] | null> {
    listsRead++;
    return this.retryableOnRecord;
  }

  override async loadRetryableRun(_store: unknown, runId: string): Promise<RetryableRun | null> {
    return this.retryableOnRecord.find((run) => run.id === runId) ?? null;
  }

  /** how many times the history was checked for interrupted runs */
  settles = 0;

  override async settleInterrupted(): Promise<number> {
    this.settles++;
    return 0;
  }

  cancelled: string[] = [];
  answers: { jobId: string; choice: AnswerChoice; date: string; always?: boolean }[] = [];
  pauses: { jobId: string; paused: boolean }[] = [];
  /** set by a test that needs answering to fail, leaving the run still waiting */
  answerFails: string | null = null;
  /** set by a test that needs pausing to fail, so the run carries on regardless */
  pauseFails: string | null = null;
  /** job ids a debug skip was asked for */
  skipped: string[] = [];
  /** set by a test that needs a skip to be refused */
  skipFails = false;
  push: ((event: JobEvent) => void) | null = null;
  closed = false;
  /** set by a test that needs settings.ini to say something other than the default */
  settingsOverride: ServerConfig['settings'] | null = null;

  /** set by a test that needs to see the window before the helper's config has come back */
  configGate: Promise<void> | null = null;

  override async loadConfig(): Promise<ServerConfig | null> {
    if (this.configGate) await this.configGate;
    const config = this.settingsOverride
      ? { ...CONFIG, settings: this.settingsOverride }
      : CONFIG;
    this.config.set(config);
    this.available.set(true);
    return config;
  }

  override async start(request: StartRequest): Promise<string> {
    this.started.push(request);
    return 'job-1';
  }

  /** the storage requests the dialog carried out, and the library it used for each */
  storageAnswered: [string, LibraryStore][] = [];
  override async answerStorage(
    _jobId: string,
    request: StorageRequest,
    store: LibraryStore,
  ): Promise<void> {
    this.storageAnswered.push([request.id, store]);
  }

  override async cancel(jobId: string): Promise<void> {
    this.cancelled.push(jobId);
  }

  override async answer(jobId: string, choice: AnswerChoice, date = '', always = false): Promise<void> {
    if (this.answerFails) throw new Error(this.answerFails);
    this.answers.push(always ? { jobId, choice, date, always } : { jobId, choice, date });
  }

  override async setPaused(jobId: string, paused: boolean): Promise<void> {
    if (this.pauseFails) throw new Error(this.pauseFails);
    this.pauses.push({ jobId, paused });
  }

  override async skipStep(jobId: string): Promise<void> {
    if (this.skipFails) throw new Error('could not skip the current step');
    this.skipped.push(jobId);
  }

  override stream(_id: string, onEvent: (e: JobEvent) => void): () => void {
    this.push = onEvent;
    return () => {
      this.closed = true;
    };
  }
}

let jobs: FakeJobs;
let fixture: ComponentFixture<DownloadDialog>;
let element: HTMLElement;

async function open(action: JobAction = 'bookmarks') {
  fixture = TestBed.createComponent(DownloadDialog);
  fixture.componentRef.setInput('action', action);
  await fixture.whenStable();
  element = fixture.nativeElement as HTMLElement;
}

function button(text: string): HTMLButtonElement | undefined {
  return Array.from(element.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === text,
  );
}

/** the *always choose this* box's words, its spacing squashed */
function alwaysLabel(): string {
  return (element.querySelector('label.always-case')?.textContent ?? '').replace(/\s+/g, ' ');
}

function checkbox(labelText: string): HTMLInputElement | undefined {
  return Array.from(element.querySelectorAll<HTMLLabelElement>('label.check'))
    .find((l) => l.textContent?.includes(labelText))
    ?.querySelector('input') as HTMLInputElement | undefined;
}

function currentStep(): string {
  return element.querySelector('.dialog')?.getAttribute('data-step') ?? '';
}

/**
 * Walk the wizard to a step, by where it actually is rather than by counting clicks.
 *
 * The steps are not in the same order for every run: a custom run asks its options before
 * the file types and everything else asks them after, and several runs put an
 * acknowledgement in between. Counting clicks made every test quietly depend on which.
 */
async function advanceTo(target: 'options' | 'filetypes' | 'credentials' | 'running') {
  for (let guard = 0; guard < 8; guard++) {
    const at = currentStep();
    if (at === target || at === 'running') return;

    if (at === 'acknowledge') {
      element.querySelector<HTMLInputElement>('input[name="acknowledge"]')!.click();
      await fixture.whenStable();
    }

    // the two link actions cannot go on without one, so the walker supplies a valid one
    if (at === 'link') {
      const field = element.querySelector<HTMLInputElement>(
        'input[name="work"], input[name="collection"], textarea[name="works"]',
      )!;
      field.value =
        field.name === 'work'
          ? 'https://archiveofourown.org/works/1234567'
          : field.name === 'works'
            ? '1234567\n75354806'
            : 'https://archiveofourown.org/collections/yuletide2024';
      field.dispatchEvent(new Event('input'));
      await fixture.whenStable();
    }

    if (at === 'credentials') {
      // a run told not to log in has no password box
      const password = element.querySelector<HTMLInputElement>('input[name="password"]');
      if (password) {
        password.value = 'a-password';
        password.dispatchEvent(new Event('input'));
        await fixture.whenStable();
      }
      (button('Start download') ?? button('Start repair'))!.click();
      await fixture.whenStable();
      continue;
    }

    button('Continue')?.click();
    await fixture.whenStable();
  }

  throw new Error(`could not reach ${target}; stuck on ${currentStep()}`);
}

/**
 * Open the custom run and choose the page-slice coverage.
 *
 * It is no longer what the run opens on - 'All bookmarks' is the first row now - so a
 * test about the page inputs has to pick that coverage before they exist.
 */
async function toPageOptions() {
  await open('custom');
  await advanceTo('options');
  checkbox('A slice of your bookmarks listing')!.click();
  await fixture.whenStable();
}

describe('DownloadDialog', () => {
  it('says what order a slice of the bookmarks listing is in', async () => {
    await open('custom');
    await advanceTo('options');
    const slice = Array.from(element.querySelectorAll<HTMLLabelElement>('label.check'))
      .find((l) => l.textContent?.includes('A slice of your bookmarks listing'));
    // the slice walks the listing sorted by date bookmarked (sorted_bookmarks_link)
    expect(slice?.textContent).toContain('in the order you bookmarked them, newest first');
  });

  it('starts the link box with a work number handed over from a listing', async () => {
    fixture = TestBed.createComponent(DownloadDialog);
    fixture.componentRef.setInput('action', 'work');
    fixture.componentRef.setInput('prefill', '7654321');
    await fixture.whenStable();
    element = fixture.nativeElement as HTMLElement;
    expect((fixture.componentInstance as unknown as { collectionUrl: () => string }).collectionUrl()).toBe('7654321');
  });

  beforeEach(async () => {
    jobs = new FakeJobs();
    // the remembered username and the combined run's note both live here, and either would
    // carry between tests
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [{ provide: Jobs, useValue: jobs }] });
  });

  // region opening

  for (const action of ['quick', 'bookmarks', 'custom', 'sync', 'work', 'collection'] as JobAction[]) {
    it(`shows a spinner, not a step it would jump from, until it knows where a ${action} run opens`, async () => {
      // the page already knows the helper is there, so the window does not wait on that
      jobs.available.set(true);
      let release!: () => void;
      jobs.configGate = new Promise<void>((done) => (release = done));
      fixture = TestBed.createComponent(DownloadDialog);
      fixture.componentRef.setInput('action', action);
      fixture.detectChanges();
      element = fixture.nativeElement as HTMLElement;

      expect(currentStep()).toBe('preparing');
      expect(element.querySelector('.preparing .spinner')).not.toBeNull();
      expect(element.querySelector('input[type="checkbox"]')).toBeNull();

      release();
      // the config arrives, init picks the step, and the window draws it
      await new Promise((done) => setTimeout(done));
      await fixture.whenStable();
      fixture.detectChanges();
      expect(currentStep()).not.toBe('preparing');
      expect(element.querySelector('.preparing')).toBeNull();
    });
  }

  it('says the helper is not running rather than spinning when it does not answer', async () => {
    jobs.loadConfig = async () => {
      jobs.available.set(false);
      return null;
    };
    await open('quick');

    expect(element.querySelector('.preparing')).toBeNull();
    expect(element.textContent).toContain("isn't running");
  });

  it('tells someone whose helper is not running to start the app again, and folds the developer way away', async () => {
    jobs.loadConfig = async () => {
      jobs.available.set(false);
      return null;
    };
    await open('quick');

    const advice = element.querySelector('.restart-advice')?.textContent ?? '';
    expect(advice).toContain('Close this page, then start FicFairy again');
    expect(advice).toContain('open the helper in a terminal window');
    expect(advice).toContain('Chrome is recommended');
    const details = element.querySelector<HTMLDetailsElement>('details.developer-info');
    expect(details?.querySelector('summary')?.textContent).toContain('Advanced information for developers');
    expect(details?.open).toBe(false);
    expect(details?.textContent).toContain('uv run python -m ao3downloader.server');
  });

  it('names what starts the app on each system', () => {
    expect(startProgramFor('Windows')?.file).toBe('ficfairy.exe');
    expect(startProgramFor('macOS')?.file).toBe('Start FicFairy.command');
    expect(startProgramFor('MacIntel')?.file).toBe('Start FicFairy.command');
    expect(startProgramFor('Linux x86_64')?.file).toBe('Start FicFairy.sh');
    expect(startProgramFor('iPhone')).toBeNull();
    expect(startProgramFor('Android')).toBeNull();
    expect(startProgramFor('')).toBeNull();
  });

  // endregion

  // region file types

  /** JSON is listed only in debug mode, so the specs about its box turn that on first */
  function debugOn() {
    TestBed.overrideProvider(DebugMode, { useValue: { on: () => true } });
  }

  it('locks the file types that are always produced', async () => {
    debugOn();
    await open();
    await advanceTo('filetypes');

    for (const forced of CONFIG.forced) {
      const input = checkbox(forced)!;
      expect(input.checked, forced).toBe(true);
      expect(input.disabled, forced).toBe(true);
    }
    expect(checkbox('EPUB')!.disabled).toBe(false);
    expect(checkbox('EPUB')!.checked).toBe(false);
  });

  it('ticks html to begin with but lets it be turned off', async () => {
    // it costs a request per work on top of the indexing, which is the expensive half
    await open();
    await advanceTo('filetypes');

    const html = checkbox('HTML')!;
    expect(html.checked).toBe(true);
    expect(html.disabled).toBe(false);
  });

  it('asks for metadata only when everything else is unticked', async () => {
    await open('bookmarks');
    await advanceTo('filetypes');
    checkbox('HTML')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].filetypes).toEqual(['JSON']);
  });

  it('tells the helper nothing about where the library is', async () => {
    // the page holds the library and does the reading and writing; the helper only asks
    await open('bookmarks');
    await advanceTo('running');
    expect(Object.keys(jobs.started[0]).sort()).toEqual(
      ['action', 'ao3TimeZone', 'filetypes', 'options', 'password', 'url', 'username'].filter(
        (key) => key in jobs.started[0],
      ),
    );
    expect(JSON.stringify(jobs.started[0])).not.toMatch(/storage|refresh|dropbox/i);
  });

  it('tells the helper the AO3 time zone - this browser\'s own until one is chosen', async () => {
    await open('bookmarks');
    await advanceTo('running');
    expect(jobs.started[0].ao3TimeZone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  });

  it("tells the helper a hosted copy's own run-log choices, and nothing when left as they were", async () => {
    TestBed.inject(HelperConnection).settings.set({ ...DEFAULT_PAGE_CONFIG, helperUrl: 'https://ao3-helper.example.com' });
    localStorage.setItem(RUN_LOG_LINES_KEY, '20000');
    localStorage.setItem(TRIM_OLD_RUN_LOGS_KEY, 'false');
    await open('bookmarks');
    await advanceTo('running');
    expect(jobs.started[0].runLogMaxLines).toBe(20000);
    expect(jobs.started[0].trimOldRunLogs).toBe(false);
  });

  it('tells the helper the AO3 time zone chosen in User settings', async () => {
    localStorage.setItem(AO3_TIME_ZONE_KEY, 'Australia/Sydney');
    await open('bookmarks');
    await advanceTo('running');
    expect(jobs.started[0].ao3TimeZone).toBe('Australia/Sydney');
  });

  it('says files go to the library the page has open', async () => {
    TestBed.inject(Library).store.set(fakeStore('Dropbox app folder'));
    await open('bookmarks');
    await advanceTo('running');
    expect(element.querySelector('.chosen')?.textContent).toContain('Dropbox app folder');
  });

  it('carries out what the helper asks, once each, in the library the run started in', async () => {
    const store = fakeStore('My Fics');
    TestBed.inject(Library).store.set(store);
    await open('bookmarks');
    await advanceTo('running');

    const request = { type: 'storage', id: 'r1', op: 'read', path: 'indexing/1.json' };
    jobs.push!(request as unknown as JobEvent);
    // a page that reconnects is sent unanswered requests again
    jobs.push!(request as unknown as JobEvent);
    // switching library mid-run does not move the run
    TestBed.inject(Library).store.set(fakeStore('Somewhere else'));
    jobs.push!({ type: 'storage', id: 'r2', op: 'list', path: 'works' } as unknown as JobEvent);
    await new Promise((r) => setTimeout(r, 0));

    expect(jobs.storageAnswered.map(([id, used]) => [id, used.label])).toEqual([
      ['r1', 'My Fics'],
      ['r2', 'My Fics'],
    ]);
  });

  it('brings the listing up to date with just what the run changed, once it ends', async () => {
    const store = fakeStore('My Fics');
    const library = TestBed.inject(Library);
    library.store.set(store);
    const refreshed: { paths: string[]; store: unknown }[] = [];
    library.refreshAfterRun = async (paths, used) => {
      refreshed.push({ paths: [...paths].sort(), store: used });
    };
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'storage', id: 'w1', op: 'write', path: 'indexing/1 A.json' } as unknown as JobEvent);
    jobs.push!({ type: 'storage', id: 'r1', op: 'read', path: 'indexing/2 B.json' } as unknown as JobEvent);
    jobs.push!({ type: 'storage', id: 'm1', op: 'rename', path: 'works/1 A.html', to: 'works/1 A 2025-01-01.html' } as unknown as JobEvent);
    jobs.push!({ type: 'finished' } as JobEvent);
    await new Promise((r) => setTimeout(r, 0));

    // reads change nothing, so only the write and both ends of the rename are taken in
    expect(refreshed).toEqual([
      { paths: ['indexing/1 A.json', 'works/1 A 2025-01-01.html', 'works/1 A.html'], store },
    ]);
  });

  for (const action of ['bookmarks', 'quick', 'custom', 'sync', 'new', 'update', 'work', 'works'] as JobAction[]) {
    it(`lists JSON on a ${action} run's file types in debug mode`, async () => {
      debugOn();
      await open(action);
      await advanceTo('filetypes');
      expect(currentStep()).toBe('filetypes');
      expect(checkbox('JSON')).toBeTruthy();
    });

    it(`lists no JSON on a ${action} run's file types outside debug mode`, async () => {
      await open(action);
      await advanceTo('filetypes');
      expect(currentStep()).toBe('filetypes');
      expect(checkbox('JSON')).toBeFalsy();
    });
  }

  for (const action of ['bookmarks', 'custom'] as JobAction[]) {
    it(`says a ${action} run's overwrite takes in the non-bookmarks only when both are ticked`, async () => {
      await open(action);
      await advanceTo('options');
      const note = () => element.querySelector('.overwrite-non-bookmarks')?.textContent ?? '';
      expect(note()).toBe('');

      checkbox('Overwrite existing downloads')!.click();
      await fixture.whenStable();
      expect(note()).toBe('');

      checkbox('Check all non-bookmarks for updates too')!.click();
      await fixture.whenStable();
      expect(note()).toContain('This will include any non-bookmarks in this scan too.');

      checkbox('Overwrite existing downloads')!.click();
      await fixture.whenStable();
      expect(note()).toBe('');
    });
  }

  it('lists no JSON outside debug mode, and says nothing about it, but still sends it', async () => {
    // json is the index - always written by a run that indexes, never one to pick
    await open('bookmarks');
    await advanceTo('filetypes');

    expect(checkbox('JSON')).toBeFalsy();
    expect(checkbox('HTML')).toBeTruthy();
    expect(element.querySelector('.body')?.textContent).not.toContain('JSON');
    await advanceTo('running');
    expect(jobs.started[0].filetypes).toContain('JSON');
  });

  // endregion

  // region options step

  it('offers the rest of each series on every run that indexes works', async () => {
    for (const action of ['bookmarks', 'quick', 'custom', 'work'] as const) {
      await open(action);
      await advanceTo('options');

      expect(checkbox('download all its other works too'), action).toBeTruthy();
    }
    expect(element.textContent).toContain(
      'Downloads all works whenever a series is found - even if its other works are not ' +
        'bookmarked by you.',
    );
  });

  it('offers saving images separately only on a custom run', async () => {
    await open('custom');
    await advanceTo('options');
    expect(checkbox('images separately')).toBeTruthy();

    for (const action of ['bookmarks', 'sync', 'new', 'update'] as const) {
      await open(action);
      await advanceTo(currentStep() === 'options' ? 'options' : 'filetypes');
      expect(checkbox('images separately'), action).toBeUndefined();
    }
  });

  it('says plainly what saving images costs and what it is not, once it is ticked', async () => {
    // most people do not want this: the pictures are already inside the downloaded work
    await open('custom');
    await advanceTo('options');
    expect(element.querySelector('.body')?.textContent).not.toContain('already embedded');

    checkbox('images separately')!.click();
    await fixture.whenStable();
    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('already embedded inside all regular downloaded works');
    expect(said).toContain('their own folder');
    expect(said).toContain('make the download longer');
  });

  it('asks a full scan nothing about pages', async () => {
    // it covers everything by definition; offering to cut it short makes it a custom run
    // under another name
    await open('bookmarks');
    await advanceTo('options');

    expect(element.querySelector('input[name="pages"]')).toBeNull();
    expect(element.querySelector('input[name="start"]')).toBeNull();
  });

  it('opens a custom run on all bookmarks, with no slice to fill in', async () => {
    await open('custom');
    await advanceTo('options');

    expect(checkbox('All bookmarks')!.checked).toBe(true);
    expect(element.querySelector('input[name="start"]')).toBeNull();
    expect(element.querySelector('input[name="pages"]')).toBeNull();
  });

  // the inputs keep what was typed in them, so a run switched back to the whole listing
  // would otherwise carry a limit it no longer shows
  it('drops a page range once the run is switched back to all bookmarks', async () => {
    await toPageOptions();

    const pages = element.querySelector<HTMLInputElement>('input[name="pages"]')!;
    pages.value = '9';
    pages.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    checkbox('All bookmarks')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.start).toBe(1);
    expect(jobs.started[0].options.pages).toBe(0);
  });

  /**
   * Open the quick scan with the debug tools on.
   *
   * Picking your own date is a debug choice on that run - the point of it is the floor
   * it works out for itself - so with the tools off there is nothing to choose and no
   * options step at all.
   */
  async function openQuickDates() {
    jobs.settingsOverride = { ...CONFIG.settings!, debugTools: true };
    await open('quick');
    await advanceTo('options');
  }

  // a quick scan works out its own floor; a slice of the listing means nothing to it
  // with the date range gone there is nothing left for it to ask, and a step with nothing
  // on it reads as one that failed to load
  // it can always be pointed at an earlier scan, so it always has an options step now - but
  // the hand-picked date range stays a debug choice
  it('keeps the date range off a quick scan unless the debug tools are on', async () => {
    await open('quick');
    await advanceTo('options');

    expect(currentStep()).toBe('options');
    expect(checkbox('Choose which earlier scan to measure back to')).toBeTruthy();
    expect(checkbox('Choose my own date range')).toBeUndefined();
  });

  // region choosing which earlier scan a quick scan measures back to

  function scanOnRecord(id: string, started: string, action = 'quick'): RunHistory {
    return {
      file: `${id}.json`, id, action, actionName: action === 'quick' ? 'Quick Scan' : 'Full scan',
      started, finished: started, status: 'success', filetypes: ['JSON'], options: {},
      reindexed: [], downloaded: [], updated: [], choices: [], failures: [], skipped: [], error: '',
    };
  }

  it('dates a scan by when its reach began, which for a resumed scan is its first attempt',
    async () => {
      jobs.floorRunsOnRecord = [
        { ...scanOnRecord('b', '2026-09-02T12:00:00'), baseline: '2026-08-30T08:00:00' },
      ];
      await toFloorPage();

      const said = element.querySelector('.floor-runs')?.textContent ?? '';
      expect(said).toContain('2026-08-30');
    });

  async function toFloorPage() {
    await open('quick');
    await advanceTo('options');
    checkbox('Choose which earlier scan to measure back to')!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();
  }

  it('lists the scans that can be measured back to on a page of their own', async () => {
    jobs.floorRunsOnRecord = [
      scanOnRecord('b', '2026-09-01T12:00:00'),
      scanOnRecord('a', '2026-03-04T09:30:00', 'bookmarks'),
    ];

    await toFloorPage();

    expect(currentStep()).toBe('floor');
    const said = element.querySelector('.floor-runs')?.textContent ?? '';
    expect(said).toContain('2026-09-01');
    expect(said).toContain('2026-03-04');
    expect(said).toContain('Full scan');
  });

  it('will not go on until a scan has been chosen', async () => {
    jobs.floorRunsOnRecord = [scanOnRecord('a', '2026-03-04T09:30:00')];
    await toFloorPage();

    expect(button('Continue')!.disabled).toBe(true);

    element.querySelector<HTMLInputElement>('input[name="floorRun"]')!.click();
    await fixture.whenStable();

    expect(button('Continue')!.disabled).toBe(false);
  });

  it('sends the chosen scan with the job', async () => {
    jobs.floorRunsOnRecord = [
      scanOnRecord('newer', '2026-09-01T12:00:00'),
      scanOnRecord('older', '2026-03-04T09:30:00'),
    ];
    await toFloorPage();

    element.querySelectorAll<HTMLInputElement>('input[name="floorRun"]')[1].click();
    await fixture.whenStable();
    await advanceTo('running');

    expect(jobs.started[0].options.floorRun).toBe('older');
  });

  it('says so when there is no completed scan to choose', async () => {
    jobs.floorRunsOnRecord = [];

    await toFloorPage();

    const text = element.querySelector('.body')?.textContent ?? '';
    expect(text).toContain('Nothing on record can be measured back to');
    // says which runs would count, since a date-range quick scan on record does not
    expect(text).toContain('full scan');
    expect(text).toContain('quick scan with no date range');
    expect(button('Continue')!.disabled).toBe(true);
  });

  it('comes back to the options from the list', async () => {
    jobs.floorRunsOnRecord = [scanOnRecord('a', '2026-03-04T09:30:00')];
    await toFloorPage();

    button('Back')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('options');
  });

  it('names the chosen scan in the note, rather than claiming the last run', async () => {
    jobs.floorRunsOnRecord = [scanOnRecord('a', '2026-03-04T09:30:00')];
    await toFloorPage();
    element.querySelector<HTMLInputElement>('input[name="floorRun"]')!.click();
    await fixture.whenStable();

    await walkToNote();

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('since the scan you chose, which started on 2026-03-04');
    expect(said).not.toContain('since the last successful');
  });

  async function settled() {
    for (let i = 0; i < 5; i++) {
      await new Promise((done) => setTimeout(done, 0));
      await fixture.whenStable();
    }
  }

  it('needs no read at all for "since my last run" when the newest floor was found as it opened', async () => {
    const newest = vi.spyOn(jobs, 'loadNewestFloor');
    const all = vi.spyOn(jobs, 'loadFloorRuns');
    jobs.floorAhead = Promise.resolve(
      { ...scanOnRecord('p', '2026-09-02T12:00:00'), status: 'partial', missingDownloads: ['7'] });
    await open('quick');
    await settled();
    await advanceTo('options');
    button('Continue')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('floor-warning');
    expect(element.querySelector('.floor-warning')?.textContent).toContain('could not');
    expect(newest).not.toHaveBeenCalled();
    expect(all).not.toHaveBeenCalled();
  });

  it('goes on past "since my last run" without waiting for the floor, and warns on the run page', async () => {
    jobs.floorRunsOnRecord = [
      { ...scanOnRecord('p', '2026-09-02T12:00:00'), status: 'partial', missingDownloads: ['7', '9'] },
      scanOnRecord('a', '2026-08-01T09:00:00'),
    ];
    let found: (floor: RunHistory | null) => void = () => undefined;
    vi.spyOn(jobs, 'loadNewestFloor').mockImplementation(
      () => new Promise((resolve) => (found = resolve)));
    const all = vi.spyOn(jobs, 'loadFloorRuns');
    await open('quick');
    await advanceTo('options');
    button('Continue')!.click();
    await fixture.whenStable();

    // not found yet, and not waited for
    expect(currentStep()).toBe('filetypes');
    await advanceTo('running');
    await settled();
    expect(element.querySelector('.run-waiting')?.textContent).toContain('Finding the scan to measure back to');
    expect(jobs.started).toHaveLength(0);

    found(jobs.floorRunsOnRecord[0]);
    await settled();
    const said = element.querySelector('.floor-warning')?.textContent?.replace(/\s+/g, ' ') ?? '';
    expect(said).toContain('could not download 2 works: 7, 9');
    expect(jobs.started).toHaveLength(0);
    expect(all).not.toHaveBeenCalled();

    // using it starts the run, measuring back to it
    button('Use it as the floor')!.click();
    await settled();
    expect(jobs.started).toHaveLength(1);
  });

  it('starts at once when the floor needs no warning', async () => {
    jobs.floorRunsOnRecord = [scanOnRecord('a', '2026-08-01T09:00:00')];
    await open('quick');
    await advanceTo('running');
    await settled();
    expect(element.querySelector('.run-waiting')).toBeNull();
    expect(jobs.started).toHaveLength(1);
  });

  it('lets another scan be chosen from the run page instead of one that could not download some works', async () => {
    jobs.floorRunsOnRecord = [
      { ...scanOnRecord('p', '2026-09-02T12:00:00'), status: 'partial', missingDownloads: ['7'] },
      scanOnRecord('a', '2026-08-01T09:00:00'),
    ];
    await open('quick');
    await advanceTo('running');
    await settled();

    button('Choose a different scan')!.click();
    await settled();

    expect(currentStep()).toBe('floor');
    expect(jobs.started).toHaveLength(0);
    // the partly finished one is still listed, saying what it missed
    expect(element.querySelector('.floor-runs')?.textContent).toContain('could not download 7');
  });

  it('waits on the run page for a helper still waking, and can be cancelled', async () => {
    let answer: (config: null) => void = () => undefined;
    // what the page heard from the helper as it loaded; this window's own ask is still out
    jobs.config.set(await jobs.loadConfig());
    jobs.connecting = new Promise((resolve) => (answer = resolve));
    await open('update');
    await advanceTo('running');
    await settled();

    expect(element.querySelector('.run-waiting')?.textContent).toContain('Waiting for the helper to answer');
    expect(jobs.started).toHaveLength(0);
    let closed = false;
    fixture.componentInstance.closed.subscribe(() => (closed = true));
    button('Cancel')!.click();
    expect(closed).toBe(true);
    answer(null);
    await settled();
    expect(jobs.started).toHaveLength(0);
  });

  it('gives up on a helper that does not answer in 2 minutes, offering to try again', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      jobs.config.set(await jobs.loadConfig());
      jobs.connecting = new Promise(() => undefined);
      await open('update');
      await advanceTo('running');
      await vi.advanceTimersByTimeAsync(2 * 60 * 1000 + 10);
      await fixture.whenStable();

      expect(currentStep()).toBe('failed');
      expect(element.querySelector('.error')?.textContent).toContain('did not answer within 2 minutes');
      expect(button('Try again')).toBeTruthy();
      expect(jobs.started).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('asks nothing when the last scan got everything', async () => {
    jobs.floorRunsOnRecord = [scanOnRecord('a', '2026-08-01T09:00:00')];
    await open('quick');
    await advanceTo('options');
    button('Continue')!.click();
    await fixture.whenStable();

    expect(currentStep()).not.toBe('floor-warning');
  });

  it('sends no floor for a quick scan measuring back to its last run as usual', async () => {
    await open('quick');
    await advanceTo('running');

    expect(jobs.started[0].options.floorRun).toBe('');
  });

  // endregion

  it('offers a quick scan no page slice', async () => {
    await openQuickDates();

    expect(checkbox('A slice of your bookmarks listing')).toBeUndefined();
    expect(checkbox('Anything that has changed since my last run')).toBeTruthy();
  });

  it('asks a custom run which pages to cover', async () => {
    await toPageOptions();

    expect(element.querySelector('input[name="pages"]')).toBeTruthy();
    expect(element.querySelector('input[name="start"]')).toBeTruthy();
  });

  it('does not offer it on the runs kept for debugging, or the update run', async () => {
    for (const action of ['sync', 'new', 'update'] as const) {
      await open(action);
      await advanceTo(currentStep() === 'options' ? 'options' : 'filetypes');

      expect(checkbox('download all its other works too'), action).toBeUndefined();
    }
  });

  it('gives a run with nothing to choose no options step, asking about the login on the login page', async () => {
    for (const action of ['sync', 'new', 'update'] as const) {
      await open(action);

      expect(currentStep(), action).not.toBe('options');
      await advanceTo('credentials');
      expect(checkbox('Skip AO3 login?'), action).toBeTruthy();
    }
  });

  it('steps back from the file types to the options, and out from there', async () => {
    await open('bookmarks');
    await advanceTo('filetypes');

    button('Back')!.click();
    await fixture.whenStable();
    expect(currentStep()).toBe('options');
    expect(button('Cancel')).toBeTruthy();
  });

  it('does not offer the publication date lookup', async () => {
    // hidden from the ui: it costs one request per work and is rarely worth it
    await open('bookmarks');
    await advanceTo('options');

    expect(checkbox('publication date')).toBeUndefined();
  });

  it('never asks the helper for publication dates', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(jobs.started[0].options.workdates).toBe(false);
  });

  it('leaves out the questions that mean nothing for an update run', async () => {
    await open('update');

    // no listing to page through, no work page to read anything off, nothing to date - so
    // it has no options step at all
    expect(currentStep()).not.toBe('options');
    expect(element.querySelector('input[name="pages"]')).toBeNull();
    expect(checkbox('download all its other works too')).toBeUndefined();
    expect(checkbox('publication date')).toBeUndefined();
    expect(checkbox('images separately')).toBeUndefined();
  });

  it('notes in the visit log which options were left as the default and which were changed', async () => {
    await open('bookmarks');
    await advanceTo('options');
    checkbox('download all its other works too')!.click();
    await fixture.whenStable();
    await advanceTo('running');

    const text = TestBed.inject(VisitLog).text();
    expect(text).toContain('Run started:');
    expect(text).toContain('series: true (changed from false)');
    expect(text).toContain('overwrite: false (left as the default)');
    expect(text).toMatch(/file types: .*\(left as the default\)/);
    // the login is never noted
    expect(text).not.toMatch(/password/i);
  });

  it('sends the chosen options with the job', async () => {
    await open('bookmarks');
    await advanceTo('options');

    checkbox('download all its other works too')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started).toHaveLength(1);
    expect(jobs.started[0].options).toEqual({
      // a full scan covers the whole listing, so these are not its to choose
      start: 1,
      pages: 0,
      series: true,
      // images are a custom run's to ask for; a full scan is not offered them
      images: false,
      workdates: false,
      // only a custom run may turn this off, so every other run always indexes
      reindex: true,
      // offered on a full scan, but off unless it is asked for
      overwrite: false,
      // offered on a full scan too, and off unless it is asked for
      nonBookmarks: false,
      // the date window is a custom run's alternative to pages; nothing else offers it
      dates: false,
      dateFrom: '',
      dateTo: '',
      // only a quick scan pointed at an earlier scan sends one
      floorRun: '',
      // only a custom run picking up an earlier run sends one
      resume: '',
      skipLogin: false,
      // the collection runs' alone
      collectionWorks: false,
      subcollections: false,
      parentCollections: false,
    });
  });

  it('sends a custom run told to save images separately', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('images separately')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.images).toBe(true);
  });

  it('sends the page to start on as well as the one to stop after', async () => {
    await toPageOptions();

    const start = element.querySelector<HTMLInputElement>('input[name="start"]')!;
    start.value = '5';
    start.dispatchEvent(new Event('input'));
    const pages = element.querySelector<HTMLInputElement>('input[name="pages"]')!;
    pages.value = '9';
    pages.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.start).toBe(5);
    expect(jobs.started[0].options.pages).toBe(9);
  });

  /** tick the date range, and fill in the dates the chosen shape of window offers */
  async function chooseWindow(from: string, to = '') {
    checkbox('date range')!.click();
    await fixture.whenStable();

    if (to) {
      checkbox('Between two dates')!.click();
      await fixture.whenStable();
      const upper = element.querySelector<HTMLInputElement>('input[name="dateTo"]')!;
      upper.value = to;
      upper.dispatchEvent(new Event('input'));
    }

    const lower = element.querySelector<HTMLInputElement>('input[name="dateFrom"]')!;
    lower.value = from;
    lower.dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  it('says a typed date range is in the AO3 time zone chosen in User settings', async () => {
    localStorage.setItem(AO3_TIME_ZONE_KEY, 'Australia/Sydney');
    await open('custom');
    await advanceTo('options');
    await chooseWindow('2024-01-01', '2024-06-30');

    expect(element.querySelector('.range-zone')?.textContent).toContain('Australia/Sydney');
    // and the dates go to the helper as the UTC moments they stand for
    await advanceTo('running');
    // typed in the AO3 zone, sent as the UTC moment that day begins there
    expect(jobs.started[0].options.dateFrom).toBe('2023-12-31T13:00:00+00:00');
    expect(jobs.started[0].options.dateTo).toBe('2024-06-30T13:59:59+00:00');
    expect(jobs.started[0].ao3TimeZone).toBe('Australia/Sydney');
  });

  it('sends a date window instead of pages when the custom run asks for one', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('2024-01-01', '2024-06-30');

    await advanceTo('running');

    expect(jobs.started[0].options.dates).toBe(true);
    expect(jobs.started[0].options.dateFrom).toBe(zonedDayToUtc('2024-01-01'));
    expect(jobs.started[0].options.dateTo).toBe(zonedDayToUtc('2024-06-30', true));
  });

  // 'since a date' is open at the top, so there is no newer end to send. a date left over
  // from a moment when 'between two dates' was ticked would silently narrow the run
  it('sends no newer end for a window that is open at the top', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('2024-01-01', '2024-06-30');

    checkbox('Everything updated since')!.click();
    await fixture.whenStable();

    expect(element.querySelector('input[name="dateTo"]')).toBeNull();

    await advanceTo('running');

    expect(jobs.started[0].options.dateFrom).toBe(zonedDayToUtc('2024-01-01'));
    expect(jobs.started[0].options.dateTo).toBe('');
  });

  // the live example, the same thing the page slice offers. read newest first, because
  // that is the direction the run works in
  it('says what a window covers while it is being chosen', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('2024-01-01');

    expect(element.textContent).toContain(
      'any works that were updated between today and 2024-01-01',
    );

    await chooseWindow('2024-01-01', '2024-06-30');

    expect(element.textContent).toContain(
      'any works that were updated between 2024-06-30 and 2024-01-01',
    );
  });

  // the earliest date is what the indexing walk stops at, so without one it reads the lot
  it('warns that a window with no earliest date indexes the whole listing', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('');

    expect(element.textContent).toContain('reads the whole listing');

    await chooseWindow('2024-01-01');

    expect(element.textContent).not.toContain('reads the whole listing');
    expect(element.textContent).toContain('stops at the first fic older than');
  });

  // the two are alternatives, so choosing the window has to take the page inputs away
  // rather than leave a slice showing that the run will not honour
  it('hides the page inputs while the date window is chosen', async () => {
    await toPageOptions();

    expect(element.querySelector('input[name="start"]')).not.toBeNull();

    checkbox('date range')!.click();
    await fixture.whenStable();

    expect(element.querySelector('input[name="start"]')).toBeNull();
    expect(element.querySelector('input[name="pages"]')).toBeNull();

    checkbox('bookmarks listing')!.click();
    await fixture.whenStable();

    expect(element.querySelector('input[name="start"]')).not.toBeNull();
  });

  // an end left empty means no limit there, and the summary has to say so - a blank in a
  // list of what the run will do reads as something that failed to fill in
  it('describes an open-ended window in the summary of what was chosen', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('2024-01-01');

    await advanceTo('running');

    expect(element.textContent).toContain(
      'any works that were updated between today and 2024-01-01',
    );
  });

  // nothing but a custom run works from a date window, so nothing else may show the choice
  it('offers the date window on the custom run alone', async () => {
    await open('bookmarks');
    await advanceTo('options');

    expect(checkbox('date range')).toBeUndefined();
  });

  it('treats a blank or first page as starting at the beginning', async () => {
    await toPageOptions();

    const start = element.querySelector<HTMLInputElement>('input[name="start"]')!;
    start.value = '';
    start.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.start).toBe(1);
  });

  it('says which slice of the listing the run will cover', async () => {
    await toPageOptions();

    const start = element.querySelector<HTMLInputElement>('input[name="start"]')!;
    start.value = '5';
    start.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(element.textContent).toContain('page 5 onwards');
  });

  it('treats a blank or zero page limit as every page', async () => {
    await toPageOptions();

    const pages = element.querySelector<HTMLInputElement>('input[name="pages"]')!;
    pages.value = '';
    pages.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.pages).toBe(0);
  });

  // endregion

  // region syncing collections

  // endregion

  // region acknowledging what an update pass cannot see

  async function toAcknowledgement(): Promise<void> {
    await open('update');
    button('Continue')?.click();
    await fixture.whenStable();
    button('Continue')?.click();
    await fixture.whenStable();
  }

  function acknowledgeBox(): HTMLInputElement | null {
    return element.querySelector<HTMLInputElement>('input[name="acknowledge"]');
  }

  it('asks an update run to acknowledge the gap before the login', async () => {
    await toAcknowledgement();

    expect(acknowledgeBox()).toBeTruthy();
    expect(element.querySelector('input[name="password"]')).toBeNull();
  });

  it('says plainly what an update pass will not find', async () => {
    await toAcknowledgement();

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('will not find a fic that was already finished');
    // and points at the run that does catch those
    expect(said).toContain('Reindex & Update All');
  });

  // the other half of the same limitation: the first is about fics the index has but calls
  // finished, this about fics the index has never heard of
  it('says it will not see unfinished fics bookmarked since the last scan', async () => {
    await toAcknowledgement();

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('will not pick up unfinished fics you have bookmarked since');
    expect(said).toContain('reads no listing');
  });

  it('will not go on until it has actually been acknowledged', async () => {
    await toAcknowledgement();

    expect(button('Continue')?.disabled).toBe(true);

    acknowledgeBox()!.click();
    await fixture.whenStable();

    expect(button('Continue')?.disabled).toBe(false);
  });

  it('reaches the login once acknowledged', async () => {
    await toAcknowledgement();
    acknowledgeBox()!.click();
    await fixture.whenStable();

    button('Continue')!.click();
    await fixture.whenStable();

    expect(element.querySelector('input[name="password"]')).toBeTruthy();
  });

  it('lets you go back to the note from the login', async () => {
    await toAcknowledgement();
    acknowledgeBox()!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();

    button('Back')!.click();
    await fixture.whenStable();

    expect(acknowledgeBox()).toBeTruthy();
  });

  it('asks no such thing of a bookmarks run', async () => {
    await open('bookmarks');
    await advanceTo('credentials');

    expect(acknowledgeBox()).toBeNull();
    expect(element.querySelector('input[name="password"]')).toBeTruthy();
  });

  it('asks no such thing of a collections run', async () => {
    await open('collections');

    expect(acknowledgeBox()).toBeNull();
  });

  // endregion

  // region works that would not download

  const FAILURES = [
    { id: '111', link: 'https://archiveofourown.org/works/111', error: 'deleted' },
    { id: '222', link: 'https://archiveofourown.org/works/222', error: 'locked' },
  ];

  async function finishWithFailures(failures = FAILURES): Promise<void> {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'failures', failures });
    jobs.push!({ type: 'finished', cancelled: false });
    await fixture.whenStable();
  }

  it('says nothing at the end about the listing, which takes in an ordinary run\'s changes itself', async () => {
    await finishWithFailures([]);

    const said = element.textContent ?? '';
    expect(said).not.toContain('Point the folder picker');
    expect(said).not.toContain('brings itself up to date');
    expect(said).not.toContain('brought up to date');
  });

  it('shows each line of the log with when it was said, in this browser\'s own time', async () => {
    await open('bookmarks');
    await advanceTo('running');
    const at = '2026-11-03T10:15:42+00:00';
    jobs.push!({ type: 'message', text: 'looking up work 7 on AO3', at } as JobEvent);
    await fixture.whenStable();

    const shown = element.querySelector('.log')?.textContent ?? '';
    const local = new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    expect(shown).toContain(`${local} looking up work 7 on AO3`);
  });

  it('says which works could not be downloaded', async () => {
    await finishWithFailures();

    const shown = element.querySelector('.failures')?.textContent ?? '';
    expect(shown).toContain('2');
    expect(shown).toContain('111');
    expect(shown).toContain('222');
    expect(shown).toContain('deleted');
  });

  it('makes clear the rest of the run still succeeded', async () => {
    await finishWithFailures();

    expect(element.querySelector('.failures')?.textContent).toContain(
      'Everything else was saved',
    );
  });

  it('links a failed work so it can be looked up', async () => {
    await finishWithFailures();

    const link = element.querySelector<HTMLAnchorElement>('.failed-list a')!;
    expect(link.getAttribute('href')).toBe('https://archiveofourown.org/works/111');
  });

  it('says nothing about failures when every work came down', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'finished', cancelled: false });
    await fixture.whenStable();

    expect(element.querySelector('.failures')).toBeNull();
  });

  it('does not list every one of a long list, but says how many there are', async () => {
    const many = Array.from({ length: 12 }, (_, i) => ({
      id: String(i), link: `https://archiveofourown.org/works/${i}`, error: 'gone',
    }));

    await finishWithFailures(many);

    expect(element.querySelectorAll('.failed-list li')).toHaveLength(5);
    expect(element.querySelector('.failures')?.textContent).toContain('7 more');
  });

  it('points at the History tab for the issues file rather than offering it here', async () => {
    // the file is on every run's history entry, where it stays available
    await finishWithFailures();

    expect(button('Export all issues')).toBeUndefined();
    expect(element.querySelector('.export-issues')?.textContent).toContain('History');
  });

  it('exports the work numbers, links and reasons', async () => {
    await finishWithFailures();

    const report = (fixture.componentInstance as unknown as {
      issuesReport(): string;
    }).issuesReport();

    const lines = report.trim().split('\n');
    expect(report).toContain('## 2 works that could not be downloaded');
    expect(lines.at(-2)).toBe('111\thttps://archiveofourown.org/works/111\tdeleted');
    expect(lines.at(-1)).toBe('222\thttps://archiveofourown.org/works/222\tlocked');
  });

  it('keeps an error that spans lines on one line of the export', async () => {
    // one work per line is the point: it has to stay feedable back in
    await finishWithFailures([
      { id: '111', link: 'https://archiveofourown.org/works/111', error: 'went\n  wrong' },
    ]);

    const report = (fixture.componentInstance as unknown as {
      issuesReport(): string;
    }).issuesReport();

    expect(report.trim().split('\n').at(-1)).toBe(
      '111\thttps://archiveofourown.org/works/111\twent wrong');
    expect(report).toContain('111\thttps://archiveofourown.org/works/111\twent wrong');
  });

  // endregion

  // region copies already on disk

  it('decides nothing about undated files up front', async () => {
    // what to do with them is asked during the run, once the count is known
    await open('bookmarks');
    await advanceTo('running');

    expect(jobs.started[0].options).not.toHaveProperty('refreshUndated');
    expect(jobs.started[0].options).not.toHaveProperty('stampUndated');
  });

  it('adds nothing to the running view about the copies already downloaded', async () => {
    // there used to be a standing panel here. the log says all of this as it happens, a
    // line at a time, so the panel only repeated what was already on screen
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'refresh', stale: 3, undated: 12, stamped: 40 });
    await fixture.whenStable();

    expect(element.querySelector('.refresh')).toBeNull();
  });

  it('counts the out-of-date copies in the summary once the run is over', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'refresh', stale: 3, undated: 12 });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('3');
    expect(said).toContain('out of date');
  });

  it('counts the files it dated in the summary once the run is over', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'refresh', stale: 0, undated: 0, stamped: 40 });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('40');
    expect(said).toContain('given a date');
  });

  it('says nothing about copies on disk when there is nothing to say', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'refresh', stale: 0, undated: 0 });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).not.toContain('out of date');
    expect(said).not.toContain('given a date');
  });

  // endregion

  // region being asked what to do about undated files

  /** a file whose date cannot be read, asked about by its case */
  async function askedAboutUndated(work = '75354806'): Promise<void> {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({
      type: 'question', name: 'inferred-date', scenario: 'ao3-unknown', count: 1, ids: [work],
      formats: ['HTML'], date: '2026-04-27', source: 'AO3', fileDates: { HTML: '' },
      reasons: { HTML: "no date can be read from your file's name, so we cannot tell which is newer - we recommend keeping yours" },
      recommended: 'no', choices: ['yes', 'no'],
    } as JobEvent);
    await fixture.whenStable();
  }

  /** the quick scan's question: no run to measure from, but an index already here */
  async function askedAboutTheFloor(count = 240, date = '2026-09-10'): Promise<void> {
    await open('quick');
    await advanceTo('running');
    jobs.push!({
      type: 'question',
      name: 'quick-floor',
      count,
      date,
      choices: ['since', 'full'],
    });
    await fixture.whenStable();
  }

  it('names the other copies of a format none of which is dated, and says they are kept', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'question', name: 'inferred-date', scenario: 'ao3-unknown', count: 1, ids: ['1'],
                 formats: ['EPUB'], date: '2026-04-27', source: 'AO3',
                 fileNames: { EPUB: '1 Wolfbird.epub' }, otherFiles: { EPUB: ['1 Wolfbird copy.epub'] },
                 choices: ['yes', 'no'] } as JobEvent);
    await fixture.whenStable();

    const said = element.querySelector('[data-question="inferred-date"]')?.textContent?.replace(/\s+/g, ' ') ?? '';
    expect(said).toContain('You also have other copies of this EPUB - these will be kept for now, and can be cleaned up later.');
    expect(element.querySelector('.other-copies .file-name.other')?.textContent).toContain('1 Wolfbird copy.epub');
  });

  it('says at the end how many works still have more than one file of a format', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'duplicateCopies', works: 3, files: 4 } as JobEvent);
    jobs.push!({ type: 'finished' } as JobEvent);
    await fixture.whenStable();

    const said = element.querySelector('.duplicate-copies')?.textContent?.replace(/\s+/g, ' ') ?? '';
    expect(said).toContain('3 works still have more than one file of the same format (4 extra copies)');
    expect(said).toContain('every other copy was kept');
    expect(button('Refresh library and resolve issues')).toBeTruthy();
  });

  /** the FicHub question: works AO3 would not give the run */
  async function askedAboutFicHub(ids = ['75354806']): Promise<void> {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'question', name: 'fichub', count: ids.length, ids,
                 choices: ['yes', 'no'] } as JobEvent);
    await fixture.whenStable();
  }

  it('asks whether to try FicHub, naming the works AO3 would not give', async () => {
    await askedAboutFicHub();

    const said = element.querySelector('.question')?.textContent ?? '';
    expect(said).toContain('AO3 would not give us 1 work');
    expect(said).toContain('FicHub');
    expect(element.querySelector('.question a')?.getAttribute('href'))
      .toBe('https://archiveofourown.org/works/75354806');
    expect(element.querySelectorAll('.question')).toHaveLength(1);
    expect(said).not.toContain('before file names carried a date');
  });

  it('dings when a question stops the run, so someone in another tab knows to come back', async () => {
    const play = vi.spyOn(TestBed.inject(ChimePlayer), 'play').mockImplementation(() => {});
    await open('bookmarks');
    await advanceTo('running');
    expect(play).not.toHaveBeenCalled();

    jobs.push!({ type: 'question', name: 'fichub', count: 1, ids: ['75354806'],
                 choices: ['yes', 'no'], default: 'yes', timeoutMinutes: 5 } as JobEvent);
    await fixture.whenStable();
    expect(play).toHaveBeenCalledTimes(1);
  });

  it('asks without a ding once this browser turned the sound off', async () => {
    const play = vi.spyOn(TestBed.inject(ChimePlayer), 'play').mockImplementation(() => {});
    TestBed.inject(Chime).set(false);
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'question', name: 'fichub', count: 1, ids: ['75354806'],
                 choices: ['yes', 'no'], default: 'yes', timeoutMinutes: 5 } as JobEvent);
    await fixture.whenStable();
    expect(element.querySelector('.question')).not.toBeNull();
    expect(play).not.toHaveBeenCalled();
  });

  it('says what an unanswered question will take, and after how long', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'question', name: 'fichub', count: 1, ids: ['75354806'],
                 choices: ['yes', 'no'], default: 'yes', timeoutMinutes: 5 } as JobEvent);
    await fixture.whenStable();

    const said = element.querySelector('.question-default')?.textContent ?? '';
    expect(said).toContain('within 5 minutes');
    // in the words of the button that gives it, not the 'yes' the helper sends
    expect(said).toContain('Try FicHub');
    expect(element.querySelector('.question')?.textContent).not.toContain('30 minutes');
    // inside the question's own panel, just above its buttons - the same place for every question
    const panel = element.querySelector('.question')!;
    const wait = panel.querySelector('.question-default')!;
    expect(wait).toBeTruthy();
    expect(wait.compareDocumentPosition(panel.querySelector('.question-actions')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(element.querySelectorAll('.question-default')).toHaveLength(1);
  });

  it('tries FicHub when told to, and leaves the works when told not to', async () => {
    await askedAboutFicHub();
    button('Try FicHub')!.click();
    await fixture.whenStable();
    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'yes', date: '' }]);
  });

  it('leaves the works as failures when told not to try FicHub', async () => {
    await askedAboutFicHub();
    button('No, leave them')!.click();
    await fixture.whenStable();
    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'no', date: '' }]);
  });

  it('warns at the end about a format taken from an older FicHub copy, never asking', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'fichubOlder', fichubOlder: [
      { id: '75354806', link: 'https://archiveofourown.org/works/75354806', title: 'Wolfbird',
        formats: ['HTML'], fichub: '2026-04-27', latest: '2026-05-10', latestFrom: 'EPUB' }] } as JobEvent);
    jobs.push!({ type: 'finished' } as JobEvent);
    await fixture.whenStable();

    const said = element.querySelector('.fichub-older')?.textContent?.replace(/\s+/g, ' ') ?? '';
    expect(said).toContain('older cached copy');
    expect(said).toContain("HTML (you had no file): FicHub's copy is dated 27 April 2026, older than the last known update date we have (10 May 2026, from your EPUB)");
    // a short list is open to begin with
    expect((element.querySelector('details.fichub-older') as HTMLDetailsElement).open).toBe(true);
    expect(element.querySelector('.question')).toBeNull();
  });

  it('asks about a file whose date is only guessed, saying what it thinks and recommends', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'question', name: 'inferred-date', scenario: 'fichub-older', count: 1,
                 ids: ['75354806'], formats: ['EPUB'], date: '2026-04-27', source: 'FicHub',
                 fileDates: { EPUB: '2024-12-14' },
                 fileNames: { EPUB: '75354806 Wolfbird - OpalApparition (14 Dec 2024).epub' },
                 reasons: {}, recommended: 'yes', choices: ['yes', 'no'],
                 default: 'no', timeoutMinutes: 1 } as JobEvent);
    await fixture.whenStable();

    const said = (element.querySelector('[data-question="inferred-date"]')?.textContent ?? '').replace(/\s+/g, ' ');
    // the whole file name, so it can be judged by eye
    expect(said).toContain('75354806 Wolfbird - OpalApparition (14 Dec 2024).epub');
    // dates written as a reader writes them
    expect(said).toContain("looks dated 14 December 2024 (a guess), so we think FicHub's version (27 April 2026) is newer");
    expect(said).toContain('We recommend replacing it');
    // the wait is said once, inside the panel and above its buttons - not above the panel too
    const panel = element.querySelector('[data-question="inferred-date"]')!;
    const wait = panel.querySelector('.question-default');
    expect(wait?.textContent?.replace(/\s+/g, ' ')).toContain('If nobody answers within 1 minute, the run carries on with: Keep mine');
    expect(wait!.compareDocumentPosition(panel.querySelector('.question-actions')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(element.querySelectorAll('.question-default')).toHaveLength(1);
    expect(said).not.toContain('Left unanswered');
    expect(element.querySelectorAll('.question')).toHaveLength(1);
    expect(button('Replace it (recommended)')).toBeTruthy();
    expect(alwaysLabel()).toContain('Always choose this when an existing file is guessed to be older than the incoming one (or the same, on a run that overwrites) from FicHub');
  });

  it('asks a retry once whether to read its carried-on works again, and can keep the answer', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'question', name: 'retry-reread', count: 12, default: 'no', timeoutMinutes: 30,
                 choices: ['no', 'yes'] } as JobEvent);
    await fixture.whenStable();

    const said = element.querySelector('[data-question="retry-reread"]')?.textContent?.replace(/\s+/g, ' ') ?? '';
    expect(said).toContain('carries on downloading 12 works');
    expect(said).toContain('not one for every file');
    expect(said).toContain('the run carries on with: No, use the index as it is');
    (element.querySelector('input[name="alwaysRetryReread"]') as HTMLInputElement).click();
    await fixture.whenStable();
    button('Yes, read them again')!.click();
    await fixture.whenStable();

    expect(jobs.answers.at(-1)).toMatchObject({ choice: 'yes' });
    expect(JSON.parse(localStorage.getItem('ao3.alwaysAnswers')!)).toEqual({ 'retry-reread': 'yes' });
  });

  it('asks before replacing a newer copy with an older version, keeping it by default', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'question', name: 'overwrite-older', count: 1, ids: ['1'],
                 formats: ['EPUB'], date: '2026-04-27', newer: '2026-05-10',
                 default: 'no', timeoutMinutes: 7, choices: ['yes', 'no'] } as JobEvent);
    await fixture.whenStable();

    const said = element.querySelector('[data-question="overwrite-older"]')?.textContent ?? '';
    expect(said).toContain('EPUB');
    expect(said.replace(/\s+/g, ' ')).toContain('newer (10 May 2026) than the version it would be replaced with (27 April 2026)');
    // the wait is said once, above the question, from the run's own setting and in the
    // button's words - never again in the panel's hint
    expect(said).not.toContain('30 minutes');
    expect(element.querySelector('.question-default')?.textContent?.replace(/\s+/g, ' '))
      .toContain('If nobody answers within 7 minutes, the run carries on with: No, keep my newer copy');
    expect(element.querySelectorAll('.question')).toHaveLength(1);

    button('No, keep my newer copy')!.click();
    await fixture.whenStable();
    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'no', date: '' }]);
  });

  it('asks about a copy of a work with no earlier index entry, recommending but keeping it by default', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'question', name: 'unindexed-copy', count: 1, ids: ['1'],
                 formats: ['PDF', 'EPUB', 'HTML'], date: '2026-11-06', source: 'AO3',
                 fileDates: { PDF: '2026-11-06', EPUB: '2026-11-03', HTML: '' },
                 fileNames: { PDF: '1 Fic - A 2026-11-06.pdf', EPUB: '1 Fic - A (3 Nov 2026).epub', HTML: '1 Fic - A.html' },
                 recommended: 'recommended', recommendedFormats: ['PDF', 'EPUB'],
                 reasons: {
                   PDF: 'recommended: yes - the AO3 version is the same date (2026-11-06), and this run overwrites existing downloads',
                   EPUB: 'recommended: yes - the AO3 version (2026-11-06) is newer than the date in your file name (2026-11-03)',
                   HTML: 'recommended: no - no date could be read from your file name, so it cannot be told which is newer',
                 },
                 default: 'no', choices: ['recommended', 'yes', 'no'] } as JobEvent);
    await fixture.whenStable();

    const panel = element.querySelector('[data-question="unindexed-copy"]')!;
    const said = panel.textContent ?? '';
    // the index never dates a file: the question says where the files came from, not that
    // nothing can tell their version
    expect(said.replace(/\s+/g, ' ')).toContain('your index had no entry for the work when this run began. This probably means these files were imported, and not downloaded through this tool');
    expect(said.replace(/\s+/g, ' ')).toContain('Do you want to replace them all with the latest version from AO3 (6 November 2026)?');
    expect(said).not.toContain('nothing to tell which version');
    expect(panel.querySelector('.file-dates li code')?.textContent).toBe('1 Fic - A 2026-11-06.pdf');
    const lines = Array.from(panel.querySelectorAll('.file-dates li')).map((li) => li.textContent?.replace(/\s+/g, ' ').trim());
    // the file's name, then the reason - which already says what its date is compared with
    expect(lines[0]).toContain('PDF 1 Fic - A 2026-11-06.pdf - Recommended: yes - the AO3 version is the same date');
    expect(lines[0]).not.toContain('in its name.');
    expect(lines[2]).toContain('HTML 1 Fic - A.html - Recommended: no - no date could be read');
    expect(said).not.toContain('Left unanswered');
    expect(element.querySelector('.question-default')?.textContent).toContain('No, keep them all');
    expect(element.querySelectorAll('.question')).toHaveLength(1);
    // only some recommended: replacing just those is offered, and stands out
    expect(button('Replace only PDF, EPUB')!.classList).toContain('primary');
    expect(button('Yes, replace them all')!.classList).not.toContain('primary');
    expect(button('No, keep them all')).toBeTruthy();

    button('Replace only PDF, EPUB')!.click();
    await fixture.whenStable();
    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'recommended', date: '' }]);
  });

  it('says how many works came from FicHub at the end', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'rescued', rescued: [{ id: '75354806', link: 'https://archiveofourown.org/works/75354806',
                                             title: 'Wolfbird', downloaded: ['EPUB'] }] } as JobEvent);
    jobs.push!({ type: 'finished' } as JobEvent);
    await fixture.whenStable();
    expect(element.querySelector('.rescued')?.textContent).toContain('1 work AO3 would not give us came');
  });

  it('reports older copies marked for removal that are still there, and exports them', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({
      type: 'notRemoved',
      notRemoved: [{ id: '111', link: 'https://archiveofourown.org/works/111',
                     file: '111 A 2024-01-01.pdf', old: '111 A 2025-06-01.pdf',
                     error: 'the run stopped before the cleanup step' }],
    } as JobEvent);
    jobs.push!({ type: 'finished', cancelled: true } as JobEvent);
    await fixture.whenStable();

    const said = element.textContent ?? '';
    expect(said).toContain('marked for');
    expect(said).toContain('111 A 2024-01-01.pdf');
    const report = (fixture.componentInstance as unknown as { issuesReport(): string }).issuesReport();
    expect(report).toContain('## 1 older copy marked for removal that is still there');
    expect(report).toContain(
      '111	111 A 2024-01-01.pdf	111 A 2025-06-01.pdf	the run stopped before the cleanup step');
  });

  // more than one question can stop a run, and they go back through the same endpoint -
  // so the panel has to be keyed on which one is being asked, not on the count
  it('asks how far back a quick scan should go, in its own words', async () => {
    await askedAboutTheFloor();

    const said = element.querySelector('.question')?.textContent ?? '';
    expect(said.replace(/\s+/g, ' ')).toContain('You have no prior successful runs, but your index already holds 240 works - the most recent of which was indexed on 10 September 2026.');
    expect(said).toContain('Scan all bookmarks to be safe');
    expect(said).toContain('If these indexes came from an interrupted or failed run');
    // and not the undated question's wording
    expect(said).not.toContain('before file names carried a date');
  });

  it('measures back to the index date when that is what was chosen', async () => {
    await askedAboutTheFloor();

    button('Only scan up until 10 September 2026')!.click();
    await fixture.whenStable();

    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'since', date: '' }]);
    expect(element.querySelector('.question')).toBeNull();
  });

  it('reads the whole listing when that is what was chosen', async () => {
    await askedAboutTheFloor();

    button('Scan all bookmarks to be safe')!.click();
    await fixture.whenStable();

    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'full', date: '' }]);
  });

  it('asks during the run, not after it', async () => {
    await askedAboutUndated();

    expect(element.querySelector('[data-question="inferred-date"]')).toBeTruthy();
    expect(element.querySelector('.offer')).toBeNull();
  });

  it('says nothing when the run has not asked anything', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(element.querySelector('.question')).toBeNull();
  });

  it('sends the choice to keep the file, or to replace it', async () => {
    await askedAboutUndated();
    button('Keep mine (recommended)')!.click();
    await fixture.whenStable();
    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'no', date: '' }]);

    await askedAboutUndated();
    button('Replace it')!.click();
    await fixture.whenStable();
    expect(jobs.answers.at(-1)).toEqual({ jobId: 'job-1', choice: 'yes', date: '' });
  });

  it('can always use the answer for that case, and keeps it for later runs', async () => {
    await askedAboutUndated();
    expect(alwaysLabel()).toContain('Always choose this when the date of an existing file cannot be judged from AO3');
    element.querySelector<HTMLInputElement>('input[name="alwaysThisCase"]')!.click();
    await fixture.whenStable();
    button('Keep mine (recommended)')!.click();
    await fixture.whenStable();

    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'no', date: '', always: true }]);
    expect(JSON.parse(localStorage.getItem('ao3.alwaysAnswers')!)).toEqual({ 'ao3-unknown': 'no' });
  });

  it('starts with the formats chosen in User settings ticked, and they can still be changed', async () => {
    localStorage.setItem('ao3.defaultFiletypes', JSON.stringify(['EPUB']));
    await open('bookmarks');
    await advanceTo('filetypes');

    expect(checkbox('EPUB')!.checked).toBe(true);
    expect(checkbox('HTML')!.checked).toBe(false);

    checkbox('EPUB')!.click();
    checkbox('HTML')!.click();
    await fixture.whenStable();
    await advanceTo('running');
    expect(jobs.started[0].filetypes).toEqual(['JSON', 'HTML']);
  });

  it('does not ask the same question twice over', async () => {
    await askedAboutUndated();

    button('Keep mine (recommended)')!.click();
    button('Keep mine (recommended)')?.click();
    await fixture.whenStable();

    expect(jobs.answers).toHaveLength(1);
  });

  it('puts the question away once it has been answered', async () => {
    await askedAboutUndated();

    button('Keep mine (recommended)')!.click();
    await fixture.whenStable();

    expect(element.querySelector('.question')).toBeNull();
  });

  it('says so when the answer could not be delivered, since the run is still waiting', async () => {
    await askedAboutUndated();
    jobs.answerFails = 'helper went away';

    button('Keep mine (recommended)')!.click();
    await fixture.whenStable();

    expect(element.querySelector('.log')?.textContent).toContain('helper went away');
    // still asking, so it can be tried again
    expect(element.querySelector('.question')).toBeTruthy();
  });

  it('does not carry an answer over from a previous run', async () => {
    await askedAboutUndated();
    button('Keep mine (recommended)')!.click();
    await fixture.whenStable();

    jobs.push!({ type: 'question', name: 'inferred-date', scenario: 'ao3-unknown', count: 1,
                 ids: ['333'], formats: ['HTML'], date: '2026-04-27', source: 'AO3',
                 reasons: {}, recommended: 'no', choices: ['yes', 'no'] } as JobEvent);
    await fixture.whenStable();

    expect(element.querySelector('.question')?.textContent).toContain('333');
    // the buttons are live again, rather than still locked from the last answer
    expect(button('Keep mine (recommended)')?.disabled).toBe(false);
  });

  // endregion

  // region indexing one collection by link

  const LINK = 'https://archiveofourown.org/collections/yuletide2024';

  function linkBox(): HTMLInputElement {
    return element.querySelector<HTMLInputElement>('input[name="collection"]')!;
  }

  async function typeLink(url: string): Promise<void> {
    const box = linkBox();
    box.value = url;
    box.dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  it('asks for the link first, before anything else', async () => {
    await open('collection');

    expect(linkBox()).toBeTruthy();
    expect(element.querySelector('input[name="password"]')).toBeNull();
    expect(element.querySelector('.dialog fieldset')).toBeNull();
  });

  it('will not go on until the link is one it can use', async () => {
    await open('collection');
    expect(button('Continue')?.disabled).toBe(true);

    await typeLink(LINK);

    expect(button('Continue')?.disabled).toBe(false);
  });

  it('says what is wrong with a link that is not a collection', async () => {
    await open('collection');

    await typeLink('https://archiveofourown.org/works/123');

    expect(button('Continue')?.disabled).toBe(true);
    expect(element.querySelector('.error')?.textContent).toContain('not a link to a collection');
  });

  it('accepts a link to any page of the collection', async () => {
    await open('collection');

    await typeLink(LINK + '/works?page=2');

    expect(button('Continue')?.disabled).toBe(false);
  });

  it('sends the link with the job', async () => {
    await open('collection');
    await typeLink(LINK);
    button('Continue')!.click();
    await fixture.whenStable();
    await advanceTo('running');

    expect(jobs.started[0].action).toBe('collection');
    expect(jobs.started[0].url).toBe(LINK);
  });

  it('lets you go back to correct the link', async () => {
    await open('collection');
    await typeLink(LINK);
    button('Continue')!.click();
    await fixture.whenStable();

    button('Back')!.click();
    await fixture.whenStable();

    expect(linkBox().value).toBe(LINK);
  });

  it('never sends a link on a job that does not take one', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(jobs.started[0].url).toBeUndefined();
  });

  // endregion

  // region the settings a run is using

  it('shows what settings.ini says, so the run can be taken at its word', async () => {
    await open('bookmarks');
    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('15');
    expect(shown).toContain('{worknum} {title} - {author}');
    expect(shown).toContain('50');
  });

  it('says when the helper is printing everything to its console, and not when it is not', async () => {
    await open('bookmarks');
    await advanceTo('running');
    expect(element.querySelector('.settings')?.textContent).not.toContain('Console logging');

    jobs.settingsOverride = { ...CONFIG.settings!, consoleLogging: true };
    fixture.destroy();
    await open('bookmarks');
    await advanceTo('running');
    expect(element.querySelector('.settings')?.textContent).toContain('Console logging');
  });

  // the wizard pages are gone by the time the run is working, so this panel is the only
  // place the answers given on them still exist
  it('reads back the file types chosen on the way in', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(element.querySelector('.settings')?.textContent).toContain('File types');
    expect(element.querySelector('.settings')?.textContent).toContain('JSON, HTML');
  });

  it('reads back the options chosen on the way in', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Overwrite existing downloads')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('overwritten, current or not');
    expect(shown).toContain("reading AO3's listing");
    expect(shown).toContain('all bookmarks');
  });

  it('leaves out settings the run never asked about', async () => {
    // a setting shown for a run that does not offer it reads as one decided behind you
    await open('update');
    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('File types');
    expect(shown).not.toContain('Series links');
    expect(shown).not.toContain('Existing files');
    expect(shown).not.toContain('Covers');
  });

  it('spells out how files are named, including the date', async () => {
    await open('bookmarks');
    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('{worknum} {title} - {author} {date updated}');
    expect(shown).toContain('cut to 50 characters');
  });

  it('shows the naming as a real example, and says it cannot be changed', async () => {
    await open('bookmarks');
    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('1234567 The Trees Are Burning - library_of_alexandria 2026-08-23.html');
    expect(shown).toContain('may be shortened to fit');
  });

  it('does not show which settings file was read', async () => {
    await open('bookmarks');
    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).not.toContain('settings.ini');
    expect(shown).not.toContain('Read from');
  });

  it('says what happens to the rest of a series, in words', async () => {
    await open('bookmarks');
    await advanceTo('options');
    checkbox('download all its other works too')!.click();
    await fixture.whenStable();
    await advanceTo('running');

    const said = element.querySelector('.settings')?.textContent ?? '';
    expect(said).toContain('If a work is part of a series');
    expect(said).toContain(
      'download all the other works in the series too, even if they are not bookmarked');
  });

  it('says it does nothing about the rest of a series when not asked to', async () => {
    await open('bookmarks');
    await advanceTo('running');

    const said = element.querySelector('.settings')?.textContent ?? '';
    expect(said).toContain('If a work is part of a series');
    expect(said).toContain('do nothing');
  });

  it('flags a zero wait, which is what trips the rate limit', async () => {
    jobs.settingsOverride = { ...CONFIG.settings!, extraWaitTime: 0 };
    await open('bookmarks');
    await advanceTo('running');

    expect(element.querySelector('.settings .warn')?.textContent).toContain('rate limit');
  });

  // endregion

  // region syncing your own collections

  it('names itself after the job it is doing', async () => {
    await open('collections');

    expect(element.querySelector('.dialog h2')?.textContent?.trim()).toBe('Index my collections');
  });

  it('opens on its one question - whether to take the works in them too', async () => {
    await open('collections');

    expect(currentStep()).toBe('options');
    expect(checkbox('Index and download encountered works')?.checked).toBe(false);
    // series only mean anything once there are works to follow them from
    expect(checkbox('download all its other works too')).toBeUndefined();
    expect(element.querySelector('.dialog input[type="number"]')).toBeNull();
  });

  it('says when the works are worth taking, under the choice', async () => {
    await open('collection');
    await advanceTo('options');

    const info = element.querySelector('[data-collection-works-info]')?.textContent ?? '';
    expect(info).toContain('only scanning a collection of your own');
    expect(info).toContain('outside of your own bookmark collection');
  });

  it('offers no way back past its first step', async () => {
    await open('collections');

    expect(button('Back')).toBeUndefined();
    expect(button('Cancel')).toBeTruthy();
  });

  it('goes straight from its question to the login when only indexing the collections', async () => {
    // collections on their own write metadata only: there are no file types to pick
    await open('collections');
    button('Continue')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('credentials');
  });

  it('indexes the collections alone unless asked for their works', async () => {
    await open('collections');
    await advanceTo('running');

    expect(jobs.started[0].filetypes).toEqual(['JSON']);
    expect(jobs.started[0].options.collectionWorks).toBe(false);
    expect(jobs.started[0].options.series).toBe(false);
  });

  it('asks for file types and offers series once asked for the works', async () => {
    await open('collection');
    await advanceTo('options');
    checkbox('Index and download encountered works')!.click();
    await fixture.whenStable();

    expect(element.textContent).toContain('the collection');
    checkbox('download all its other works too')!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();
    expect(currentStep()).toBe('filetypes');

    await advanceTo('running');
    expect(jobs.started[0].filetypes).toEqual(['JSON', 'HTML']);
    expect(jobs.started[0].options.collectionWorks).toBe(true);
    expect(jobs.started[0].options.series).toBe(true);
  });

  it('offers to follow a collection\'s subcollections and parent, and sends the choice', async () => {
    await open('collection');
    await advanceTo('options');
    checkbox('Include subcollections')!.click();
    await fixture.whenStable();

    expect(checkbox('Include parent collections')?.checked).toBe(false);
    expect(element.textContent).toContain('read at most once');
    await advanceTo('running');

    expect(jobs.started[0].options.subcollections).toBe(true);
    expect(jobs.started[0].options.parentCollections).toBe(false);
    const said = element.querySelector('.settings')?.textContent ?? '';
    expect(said).toContain('subcollections too, however far removed');
  });

  it('never offers the relatives of a collection on any other run', async () => {
    await open('bookmarks');
    await advanceTo('options');

    expect(checkbox('Include subcollections')).toBeUndefined();
    expect(checkbox('Include parent collections')).toBeUndefined();
  });

  it('says back that it is taking the works too', async () => {
    await open('collections');
    checkbox('Index and download encountered works')!.click();
    await fixture.whenStable();
    await advanceTo('running');

    const said = element.querySelector('.settings')?.textContent ?? '';
    expect(said).toContain('Works in the collections');
    expect(said).toContain('downloaded or updated as necessary');
  });

  it('sends the collections action', async () => {
    await open('collections');
    await advanceTo('running');

    expect(jobs.started).toHaveLength(1);
    expect(jobs.started[0].action).toBe('collections');
  });

  it('still shows progress and a stop button while it runs', async () => {
    await open('collections');
    await advanceTo('running');

    jobs.push!({ type: 'phase', name: 'collections' });
    jobs.push!({ type: 'work', title: 'Best of DCMK', phase: 'collections', done: 1 });
    await fixture.whenStable();

    expect(element.querySelector('.current')?.textContent).toContain('Best of DCMK');
    expect(button('Stop')).toBeTruthy();
  });

  // endregion

  // region running

  it('shows what the run was asked to do', async () => {
    TestBed.inject(Library).store.set(fakeStore('my_downloads'));
    await open('bookmarks');
    await advanceTo('running');

    const chosen = element.querySelector('.chosen')?.textContent ?? '';
    expect(chosen).toContain('JSON');
    expect(chosen).toContain('HTML');
    // the library the page has open - the helper has none of its own to name
    expect(chosen).toContain('my_downloads');
  });

  it('shows back only the settings the run was actually offered', async () => {
    // a full scan is not asked which pages to cover, so showing a page range back at it
    // reads as a setting that was chosen rather than one that does not exist
    await open('bookmarks');
    await advanceTo('running');
    expect(element.querySelector('.chosen')?.textContent).not.toContain('pages');

    // and a custom run says so only once it has actually been asked for a slice
    await toPageOptions();
    await advanceTo('running');
    expect(element.querySelector('.chosen')?.textContent).toContain('all pages');
  });

  it('names the fic and the format currently being fetched', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'work', title: '123 A Fic - Author', filetype: 'EPUB' });
    await fixture.whenStable();

    const current = element.querySelector('.current')?.textContent ?? '';
    expect(current).toContain('123 A Fic - Author');
    expect(current).toContain('EPUB');
  });

  it('keeps the fic name when a work event carries no format', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'work', title: '123 A Fic - Author' });
    await fixture.whenStable();

    const current = element.querySelector('.current')?.textContent ?? '';
    expect(current).toContain('123 A Fic - Author');
  });

  it('names the stage the run is in', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'phase', name: 'indexing' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain('Indexing');

    jobs.push!({ type: 'phase', name: 'downloading' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain('Downloading works');
  });

  it('shows what is being fetched only while something is being fetched', async () => {
    // this line used to stand there permanently reading 'Reading the bookmarks listing',
    // which was a plain lie during the login and during every stage of an update run
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'phase', name: 'downloading' });
    await fixture.whenStable();
    expect(element.querySelector('.current')).toBeNull();

    jobs.push!({ type: 'work', title: 'A Fic', filetype: 'EPUB', done: 1, total: 3 });
    await fixture.whenStable();
    expect(element.querySelector('.current')?.textContent).toContain('A Fic');
    expect(element.querySelector('.current')?.textContent).toContain('Downloading');
  });

  it('stops naming a fic once that stage is over', async () => {
    // otherwise the panel sits there still naming whatever it happened to finish on
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'phase', name: 'downloading' });
    jobs.push!({ type: 'work', title: 'A Fic', done: 1, total: 3 });
    await fixture.whenStable();
    expect(element.querySelector('.current')).toBeTruthy();

    jobs.push!({ type: 'phase', name: 'collections' });
    await fixture.whenStable();

    expect(element.querySelector('.current')).toBeNull();
  });

  it('puts what is being fetched between the step and the bar', async () => {
    // it qualifies the step - that says which part of the run, this says which fic - so it
    // belongs with it rather than stranded below the progress bar
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'phase', name: 'downloading' });
    jobs.push!({ type: 'work', title: 'A Fic', done: 1, total: 3 });
    await fixture.whenStable();

    const order = Array.from(element.querySelectorAll('.phase, .current, .bar'));
    expect(order.map((e) => e.className.split(' ')[0])).toEqual(['phase', 'current', 'bar']);
  });

  it('says Updating rather than Downloading during an update run', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'phase', name: 'updating' });
    jobs.push!({ type: 'work', title: 'A Fic', done: 1, total: 3 });
    await fixture.whenStable();

    expect(element.querySelector('.current')?.textContent).toContain('Updating');
  });

  // region the runs and what each says it cannot do

  /**
   * Walk on to the acknowledgement from wherever the dialog is, or to the login if this
   * run has no note to show.
   *
   * By where it has got to rather than by counting clicks: which steps come before the
   * note varies per run, and a count quietly depends on that. It stops at the login as
   * well, because a note that has been turned off leaves no step to stop at - and whether
   * that happened is what several of these tests are checking.
   */
  async function walkToNote() {
    for (let guard = 0; guard < 6; guard++) {
      const at = currentStep();
      if (at === 'acknowledge' || at === 'credentials') return;
      button('Continue')?.click();
      await fixture.whenStable();
    }
  }

  async function toNote(action: 'bookmarks' | 'sync' | 'update' | 'quick') {
    await open(action);
    await walkToNote();
  }

  it('warns that a full scan is a long job and names the lighter run', async () => {
    await toNote('bookmarks');

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('take a really long time');
    expect(said).toContain('Download new bookmarks and update incomplete fics');
    expect(button('Continue')?.disabled).toBe(true);
  });

  it('says what the combined run trusts and what it will miss', async () => {
    await toNote('sync');

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('trusts the index you already have');
    expect(said).toContain('already marked complete');
    expect(said).toContain('Reindex & Update All');
  });

  it('lets the combined run’s note be turned off, once it is accepted', async () => {
    await toNote('sync');
    element.querySelector<HTMLInputElement>('input[name="acknowledge"]')!.click();
    element.querySelector<HTMLInputElement>('input[name="dontAskAgain"]')!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();
    expect(element.querySelector('input[name="password"]')).toBeTruthy();

    await toNote('sync');

    // straight past it to the login this time
    expect(element.querySelector('input[name="acknowledge"]')).toBeNull();
    expect(element.querySelector('input[name="password"]')).toBeTruthy();
  });

  it('goes straight past a quick scan’s note once it is turned off', async () => {
    jobs.floorAhead = Promise.resolve(scanOnRecord('a', '2026-09-02T12:00:00'));
    await toNote('quick');
    expect(currentStep()).toBe('acknowledge');
    element.querySelector<HTMLInputElement>('input[name="acknowledge"]')!.click();
    element.querySelector<HTMLInputElement>('input[name="dontAskAgain"]')!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();
    expect(element.querySelector('input[name="password"]')).toBeTruthy();

    await toNote('quick');

    expect(currentStep()).not.toBe('acknowledge');
    expect(element.querySelector('.dialog .body')?.textContent).not.toContain('will not be restored by this Quick Scan');
    expect(element.querySelector('input[name="password"]')).toBeTruthy();
  });

  it('keeps asking when the note is turned off but then backed out of', async () => {
    // ticking the box is not the decision; going through with it is
    await toNote('sync');
    element.querySelector<HTMLInputElement>('input[name="dontAskAgain"]')!.click();
    await fixture.whenStable();

    await toNote('sync');

    expect(element.querySelector('input[name="acknowledge"]')).toBeTruthy();
  });

  it('warns on its first page that a quick scan with no scan on record does a full index', async () => {
    // there is nothing to measure back to until a run has completed, so the first one
    // walks the whole listing - which on a large library is hours, not minutes
    jobs.floorAhead = Promise.resolve(null);
    await open('quick');
    await settled();
    expect(currentStep()).toBe('options');
    const note = element.querySelector('.first-scan')?.textContent ?? '';
    expect(note).toContain('this will perform a full index');
    expect(note).toContain('may take several hours');

    // and not on the acknowledgement page any more
    await walkToNote();
    expect(element.querySelector('.dialog .body')?.textContent).not.toContain('this will perform a full index');
  });

  it('says what a quick scan does on its first page, above what it covers, and not again after', async () => {
    jobs.floorAhead = Promise.resolve(scanOnRecord('a', '2026-09-02T12:00:00'));
    await open('quick');
    await settled();
    expect(currentStep()).toBe('options');
    const body = element.querySelector('.dialog .body')!;
    const says = body.querySelector('.what-it-does');
    expect(says?.textContent).toContain('Scans your AO3 Bookmarks and updates anything that has changed');
    const covers = body.querySelector('fieldset')!;
    expect(says!.compareDocumentPosition(covers) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await walkToNote();
    expect(element.querySelector('.dialog .body')?.textContent).not.toContain('updates anything that has changed since the last');
  });

  it('says nothing about a full index when a scan is on record', async () => {
    jobs.floorAhead = Promise.resolve(scanOnRecord('a', '2026-09-02T12:00:00'));
    await open('quick');
    await settled();
    expect(element.querySelector('.first-scan')).toBeNull();
  });

  it('holds Start, visibly, until the login is filled in', async () => {
    jobs.floorAhead = Promise.resolve(scanOnRecord('a', '2026-09-02T12:00:00'));
    await open('quick');
    await settled();
    await advanceTo('options');
    for (let i = 0; i < 6 && currentStep() !== 'credentials'; i++) {
      if (currentStep() === 'acknowledge') {
        element.querySelector<HTMLInputElement>('input[name="acknowledge"]')!.click();
        await fixture.whenStable();
      }
      (button('Continue') ?? button('Use it as the floor'))?.click();
      await fixture.whenStable();
    }
    expect(currentStep()).toBe('credentials');
    const name = element.querySelector<HTMLInputElement>('input[name="username"]')!;
    name.value = '';
    name.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    const start = button('Start download')!;
    expect(start.disabled).toBe(true);
    expect(start.getAttribute('title')).toBe('Enter your AO3 username and password first');

    name.value = 'Someone';
    name.dispatchEvent(new Event('input'));
    const password = element.querySelector<HTMLInputElement>('input[name="password"]')!;
    password.value = 'a-password';
    password.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(button('Start download')!.disabled).toBe(false);
  });

  it('gives a quick scan its own caveat rather than the combined run’s', async () => {
    // a quick scan does re-read completed fics that changed, so the combined run's warning
    // about those would be untrue here
    await toNote('quick');

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('will not be restored by this Quick Scan');
    expect(said).toContain('(Full scan) Reindex & Update All');
    expect(said).not.toContain('not notice changes to fics already marked complete');
    expect(said).not.toContain('three passes');
  });

  // the answer to a damaged or truncated file, which no version check can see: the name
  // and the date are both right and only the bytes are wrong
  it.each(['bookmarks', 'custom'] as const)(
    'lets a %s run overwrite files nothing says are out of date',
    async (action) => {
      await open(action);
      await advanceTo('options');

      checkbox('Overwrite existing downloads')!.click();
      await fixture.whenStable();

      await advanceTo('running');

      expect(jobs.started[0].options.overwrite).toBe(true);
    },
  );

  // they exist to be cheap, and a run that re-fetches everything it holds is the opposite
  it.each(['sync', 'quick', 'update', 'work'] as const)(
    'does not offer %s the option to overwrite',
    async (action) => {
      await open(action);
      await advanceTo('filetypes');

      expect(checkbox('Overwrite existing downloads')).toBeUndefined();
    },
  );

  it('leaves overwriting off unless it is asked for', async () => {
    await open('custom');
    await advanceTo('running');

    expect(jobs.started[0].options.overwrite).toBe(false);
  });

  // a listing of your bookmarks never shows a work you did not bookmark, so a scan only
  // reads one again when it is asked to
  it.each(['bookmarks', 'quick', 'custom'] as const)(
    'lets a %s run check non-bookmarks for updates, saying what it checks',
    async (action) => {
      await open(action);
      await advanceTo('options');

      const box = checkbox('Check all non-bookmarks for updates too');
      expect(element.querySelector('.dialog .body')?.textContent).toContain(
        'added by URL or id',
      );
      box!.click();
      await fixture.whenStable();
      await advanceTo('running');

      expect(jobs.started[0].options.nonBookmarks).toBe(true);
    },
  );

  it.each(['sync', 'update', 'work'] as const)(
    'does not offer %s the option to check non-bookmarks',
    async (action) => {
      await open(action);
      await advanceTo('filetypes');

      expect(checkbox('Check all non-bookmarks for updates too')).toBeUndefined();
    },
  );

  // re-reading a work writes its entry, which skipping the indexing has ruled out
  it('does not offer it to a custom run told to skip indexing', async () => {
    await open('custom');
    await advanceTo('options');

    checkbox('Check all non-bookmarks for updates too')!.click();
    checkbox('Skip check for new bookmarks')!.click();
    await fixture.whenStable();

    expect(checkbox('Check all non-bookmarks for updates too')).toBeUndefined();
    await advanceTo('running');
    expect(jobs.started[0].options.nonBookmarks).toBe(false);
  });

  // a quick scan's two shapes, in its own words: the floor it works out for itself, or one
  // the user gives it
  it('offers a quick scan its own pair of coverage choices', async () => {
    await openQuickDates();

    expect(checkbox('Anything that has changed since my last run')).toBeTruthy();
    expect(checkbox('[DEBUG] Choose my own date range')).toBeTruthy();
    // that is the custom run's wording, and it walks no slice of the listing
    expect(checkbox('A slice of your bookmarks listing')).toBeUndefined();
    expect(element.querySelector('input[name="start"]')).toBeNull();
  });

  it('sends a quick scan the date range it was given', async () => {
    await openQuickDates();

    checkbox('Choose my own date range')!.click();
    await fixture.whenStable();
    const from = element.querySelector<HTMLInputElement>('input[name="dateFrom"]')!;
    from.value = '2026-01-01';
    from.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.dates).toBe(true);
    expect(jobs.started[0].options.dateFrom).toBe(zonedDayToUtc('2026-01-01'));
  });

  it('leaves a quick scan measuring back to the last run unless told otherwise', async () => {
    await open('quick');
    await advanceTo('running');

    expect(jobs.started[0].options.dates).toBe(false);
  });

  // the caveats differ: measuring back to the last run and measuring back to a date you
  // picked fail in different ways, so one note cannot cover both
  // the same method as the ordinary quick scan, given two dates instead of an earlier scan
  it('explains that a quick scan date range reads by date bookmarked, then by date updated', async () => {
    await openQuickDates();
    checkbox('Choose my own date range')!.click();
    await fixture.whenStable();
    const from = element.querySelector<HTMLInputElement>('input[name="dateFrom"]')!;
    from.value = '2026-01-01';
    from.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('by date bookmarked');
    expect(said).toContain('by date updated');
    expect(said).toContain('any works that were bookmarked or updated between today and 2026-01-01');
    // the custom run's single-walk wording does not belong here
    expect(said).not.toContain('re-read one at a time');
  });

  it('keeps the custom run date range worded as a single walk by date updated', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Choose my own date range')!.click();
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('sorted by when AO3 last updated each work');
    expect(said).not.toContain('by date bookmarked');
  });

  it('gives a quick scan over a date range its own caveats', async () => {
    await openQuickDates();

    checkbox('Choose my own date range')!.click();
    await fixture.whenStable();
    await walkToNote();

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('bookmarked');
    expect(said).toContain('in this date range');
    expect(said).toContain('once by date bookmarked and once by date updated');
    expect(said).not.toContain('since the last successful run');
    expect(said).not.toContain('will not be restored by this Quick Scan');
  });

  it('never lets the full scan note be turned off', async () => {
    // it is the run that costs hours; it says so every time
    await toNote('bookmarks');

    expect(element.querySelector('input[name="dontAskAgain"]')).toBeNull();
  });

  it('asks a single-fic run for a work, by link or by number', async () => {
    await open('work');

    const input = element.querySelector<HTMLInputElement>('input[name="work"]')!;
    expect(input).toBeTruthy();
    expect(button('Continue')?.disabled).toBe(true);

    input.value = '1234567';
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(button('Continue')?.disabled).toBe(false);
  });

  it('refuses a single-fic run anything that is not one work', async () => {
    await open('work');
    const input = element.querySelector<HTMLInputElement>('input[name="work"]')!;

    input.value = 'https://archiveofourown.org/collections/yuletide';
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(button('Continue')?.disabled).toBe(true);
    expect(element.querySelector('.error')?.textContent).toContain('not an AO3 work');
  });

  it('takes a chapter link as the work it belongs to', async () => {
    await open('work');
    const input = element.querySelector<HTMLInputElement>('input[name="work"]')!;

    input.value = 'https://archiveofourown.org/works/1234567/chapters/86677150';
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(button('Continue')?.disabled).toBe(false);
  });

  it('reads a pasted list of fics whatever separates them, and counts them', async () => {
    expect(parseWorkList('1\nhttps://archiveofourown.org/works/2/chapters/9, 3; 1  4')).toEqual({
      ids: ['1', '2', '3', '4'],
      unknown: [],
    });
    expect(parseWorkList('1 https://archiveofourown.org/series/5').unknown).toEqual([
      'https://archiveofourown.org/series/5',
    ]);

    await open('works');
    const box = element.querySelector<HTMLTextAreaElement>('textarea[name="works"]')!;
    box.value = '1234567\n75354806, 1234567';
    box.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(element.querySelector('.work-count')?.textContent).toContain('2 fics');
    expect(button('Continue')?.disabled).toBe(false);

    box.value = '1234567 not-a-fic';
    box.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(button('Continue')?.disabled).toBe(true);
    expect(element.querySelector('.error')?.textContent).toContain('not-a-fic');
  });

  it('will not go on with more fics than one run takes, saying how many to remove', async () => {
    await open('works');
    const box = element.querySelector<HTMLTextAreaElement>('textarea[name="works"]')!;
    box.value = Array.from({ length: 512 }, (_, n) => String(n + 1)).join('\n');
    box.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(element.querySelector('.too-many-works')?.textContent?.replace(/\s+/g, ' ')).toContain(
      'That is 512 fics - one run takes at most 500. Remove 12',
    );
    expect(button('Continue')?.disabled).toBe(true);
    // Enter in the box is the form's submit: held the same way
    element.querySelector<HTMLFormElement>('form.body')!.dispatchEvent(new Event('submit'));
    await fixture.whenStable();
    expect(element.querySelector('[data-step]')?.getAttribute('data-step')).toBe('link');

    box.value = Array.from({ length: 500 }, (_, n) => String(n + 1)).join('\n');
    box.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(element.querySelector('.too-many-works')).toBeNull();
    expect(button('Continue')?.disabled).toBe(false);
  });

  it("types made-up works into a guest's fic runs, and Continue takes the whole list at once", async () => {
    TestBed.inject(HelperConnection).guest.set(true);
    await open('works');
    await new Promise((done) => setTimeout(done, 400));
    await fixture.whenStable();
    const box = element.querySelector<HTMLTextAreaElement>('textarea[name="works"]')!;

    expect(box.classList).toContain('ghost-typing');
    expect(GUEST_WORKS.startsWith(box.value) && box.value.length > 0).toBe(true);
    expect(element.querySelector('.error')).toBeNull();

    element.querySelector<HTMLFormElement>('form.body')!.dispatchEvent(new Event('submit'));
    await fixture.whenStable();
    const typed = (fixture.componentInstance as unknown as { collectionUrl: () => string }).collectionUrl();
    expect(typed).toBe(GUEST_WORKS);
    expect(parseWorkList(typed)).toEqual({ ids: ['1234567', '2345678', '3456789', '4567890', '5678901'], unknown: [] });
  });

  it("types one made-up work into a guest's single-fic run, and nothing for anyone else", async () => {
    await open('work');
    await new Promise((done) => setTimeout(done, 400));
    expect(element.querySelector<HTMLInputElement>('input[name="work"]')!.value).toBe('');
    fixture.destroy();

    TestBed.inject(HelperConnection).guest.set(true);
    await open('work');
    element.querySelector<HTMLFormElement>('form.body')!.dispatchEvent(new Event('submit'));
    await fixture.whenStable();
    expect((fixture.componentInstance as unknown as { collectionUrl: () => string }).collectionUrl()).toBe(GUEST_WORK);
  });

  describe('an import', () => {
    const IMPORT: ImportRequest = {
      links: 'https://archiveofourown.org/works/1\nhttps://archiveofourown.org/works/2',
      count: 2,
      filetypes: ['JSON', 'EPUB'],
      replaceOutdated: true,
      indexOnly: ['2'],
      lookups: 2,
      scope: 'dates',
    };

    async function openImport(request: ImportRequest = IMPORT) {
      fixture = TestBed.createComponent(DownloadDialog);
      fixture.componentRef.setInput('action', 'import');
      fixture.componentRef.setInput('importing', request);
      await fixture.whenStable();
      element = fixture.nativeElement as HTMLElement;
    }

    it('opens straight on the login, its works and formats chosen in the import window', async () => {
      await openImport();
      expect(currentStep()).toBe('credentials');
      expect(element.querySelector('h2')?.textContent).toContain('Resolve issues found in your library');
      const lines = [...element.querySelectorAll('.import-summary li')].map((li) => li.textContent?.trim());
      expect(lines).toEqual([
        'Lookup 2 works with missing index',
        'Download EPUB for any fics found to have date issues in this import',
        'Will replace any outdated files with newer ones, if they exist',
      ]);
      expect(button('Start repair')).toBeTruthy();
      // nothing about remembering a username on a repair
      expect(element.textContent).not.toContain('Remember my username');
      expect(element.textContent).not.toContain('Only the username is saved');
      // the run needs no username of its own
      checkbox('Skip AO3 login?')!.click();
      await fixture.whenStable();
      expect(element.querySelector('input[name="username"]')).toBeNull();
    });

    it('asks to be left open, above what it will do, when the import makes more than 20 requests', async () => {
      // 2 lookups, 1 work updated in one other format, 3 files it may replace: about 6
      await openImport({ ...IMPORT, files: 3 });
      expect(element.querySelector('.long-run-note')).toBeNull();
      // 2 lookups, 1 work in one format, 18 files: about 21
      await openImport({ ...IMPORT, files: 18 });
      const note = element.querySelector('.long-run-note')!;
      expect(note.textContent).toContain('This may take a long time, with ~21 requests to work through');
      expect(note.textContent).toContain('leave this window open');
      expect(note.compareDocumentPosition(element.querySelector('.import-summary')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it('offers to skip the login below the username and password', async () => {
      await openImport();
      const skip = element.querySelector('input[name="skipLogin"]')!;
      const password = element.querySelector('input[name="password"]')!;
      expect(password.compareDocumentPosition(skip) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it('asks for a login, in case some of the works are restricted to AO3 users', async () => {
      await openImport();
      expect(checkbox('Skip AO3 login?')!.checked).toBe(false);
      expect(element.querySelector('.login-reason')?.textContent).toContain('restricted to AO3 users');
      expect(element.querySelector('input[name="username"]')).toBeTruthy();
      const password = element.querySelector<HTMLInputElement>('input[name="password"]')!;
      expect(password).toBeTruthy();

      // not started without the password
      password.value = '';
      password.dispatchEvent(new Event('input'));
      await fixture.whenStable();
      button('Start repair')!.click();
      await fixture.whenStable();
      expect(jobs.started).toHaveLength(0);

      await advanceTo('running');
      expect(jobs.started[0].options.skipLogin).toBe(false);
      expect(jobs.started[0].username).toBe('Someone');
      expect(jobs.started[0].password).toBe('a-password');
    });

    it('goes without the login only when told to skip it', async () => {
      await openImport();
      checkbox('Skip AO3 login?')!.click();
      await fixture.whenStable();
      expect(element.querySelector('.login-reason')).toBeNull();
      expect(element.querySelector('input[name="password"]')).toBeNull();
      // the same warning every run shows
      expect(element.querySelector('.skip-login-warning')?.textContent).toContain('not recommended');
      button('Start repair')!.click();
      await fixture.whenStable();
      expect(jobs.started[0].options.skipLogin).toBe(true);
      expect(jobs.started[0].password).toBe('');
    });

    it('sends the works, the formats and whether to replace outdated copies', async () => {
      await openImport();
      await advanceTo('running');
      const sent = jobs.started[0];
      expect(sent.action).toBe('import');
      expect(sent.url).toBe(IMPORT.links);
      expect(sent.filetypes).toEqual(['JSON', 'EPUB']);
      expect(sent.options.replaceOutdated).toBe(true);
      expect(sent.options.indexOnly).toEqual(['2']);
      expect(sent.options.overwrite).toBe(false);
    });

    it('keeps every copy you have unless told to replace outdated ones', async () => {
      await openImport({ ...IMPORT, filetypes: ['JSON'], replaceOutdated: false, scope: 'skip' });
      const lines = [...element.querySelectorAll('.import-summary li')].map((li) => li.textContent?.trim());
      expect(lines).toEqual(['Lookup 2 works with missing index']);
      await advanceTo('running');
      expect(jobs.started[0].options.replaceOutdated).toBe(false);
    });

    it('is the only run that sends whether to replace outdated copies', async () => {
      await open('works');
      await advanceTo('running');
      expect('replaceOutdated' in jobs.started[0].options).toBe(false);
      expect('indexOnly' in jobs.started[0].options).toBe(false);
    });
  });

  it('starts several fics with the paste as it was typed', async () => {
    await open('works');
    await advanceTo('running');
    expect(jobs.started[0].action).toBe('works');
    expect(jobs.started[0].url).toBe('1234567\n75354806');
    expect(jobs.started[0].options.skipLogin).toBe(false);
  });

  for (const action of ['work', 'works', 'bookmarks', 'quick', 'update', 'collection'] as JobAction[]) {
    it(`offers skipping the login on ${action}, on the login page, unticked, warning when ticked`, async () => {
      await open(action);
      await advanceTo('credentials');
      const box = checkbox('Skip AO3 login?')!;
      expect(box.checked).toBe(false);
      expect(element.querySelector('.skip-login-warning')).toBeNull();

      box.click();
      await fixture.whenStable();
      const warning = element.querySelector('.skip-login-warning')?.textContent ?? '';
      expect(warning).toContain('not recommended');
      expect(warning).toContain('restricted');
      expect(warning).toContain('FicHub');
      expect(warning).toContain('Private bookmarks');
    });
  }

  it('starts without a login when told to skip it, sending no credentials', async () => {
    await open('work');
    await advanceTo('credentials');
    expect(element.textContent).toContain('Log in to AO3 so restricted works');
    checkbox('Skip AO3 login?')!.click();
    await fixture.whenStable();
    // a fic run needs no account at all, so neither box nor sentence is left
    expect(element.querySelector('input[name="password"]')).toBeNull();
    expect(element.querySelector('input[name="username"]')).toBeNull();
    expect(element.textContent).not.toContain('Log in to AO3 so restricted works');
    expect(element.textContent).not.toContain('Enter your username');

    button('Start download')!.click();
    await fixture.whenStable();
    expect(jobs.started[0].options.skipLogin).toBe(true);
    expect(jobs.started[0].username).toBe('');
    expect(jobs.started[0].password).toBe('');
  });

  it('asks a run reading your own bookmarks for a username but no password when skipping the login', async () => {
    await open('bookmarks');
    await advanceTo('credentials');
    expect(element.textContent).toContain('your own bookmarks are visible');
    checkbox('Skip AO3 login?')!.click();
    await fixture.whenStable();
    expect(element.querySelector('input[name="password"]')).toBeNull();
    expect(element.textContent).not.toContain('Log in to AO3 so restricted works');
    expect(element.textContent).toContain('Enter your username to scan your public bookmarks');
    const name = element.querySelector<HTMLInputElement>('input[name="username"]')!;
    expect(name.value).toBe('Someone');

    // a run reading your bookmarks cannot start without one
    name.value = '';
    name.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    button('Start download')!.click();
    await fixture.whenStable();
    expect(jobs.started.length).toBe(0);

    name.value = 'Someone';
    name.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    button('Start download')!.click();
    await fixture.whenStable();
    expect(jobs.started[0].options.skipLogin).toBe(true);
    expect(jobs.started[0].username).toBe('Someone');
    expect(jobs.started[0].password).toBe('');
  });

  it('words the username for a collection run skipping the login as its collections', async () => {
    await open('collections');
    await advanceTo('credentials');
    expect(element.textContent).toContain('your own collections are visible');
    checkbox('Skip AO3 login?')!.click();
    await fixture.whenStable();
    expect(element.textContent).toContain('Enter your username to scan your public collections');
    expect(element.querySelector('input[name="username"]')).toBeTruthy();
    expect(element.querySelector('input[name="password"]')).toBeNull();
  });

  it('offers skipping the indexing only on a custom run', async () => {
    await open('custom');
    await advanceTo('options');
    expect(checkbox('Skip check for new bookmarks')).toBeTruthy();

    await open('bookmarks');
    await advanceTo('options');
    expect(checkbox('Skip check for new bookmarks')).toBeUndefined();
  });

  it('warns, once indexing is skipped, that files are judged against the last index', async () => {
    await open('custom');
    await advanceTo('options');
    expect(element.querySelector('.skip-index-warning')).toBeNull();

    checkbox('Skip check for new bookmarks')!.click();
    fixture.detectChanges();
    expect(element.querySelector('.skip-index-warning')!.textContent).toContain(
      'not against live AO3 data',
    );
  });

  it('asks a custom run its options before its file types', async () => {
    // one of its options decides a file type, so asking which types you want and then
    // changing one behind you would read as the dialog overruling you
    await open('custom');
    expect(currentStep()).toBe('options');

    button('Continue')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('filetypes');
  });

  it('asks every run its options before its file types', async () => {
    // two orders is one more than anybody needs to learn
    await open('bookmarks');
    expect(currentStep()).toBe('options');

    button('Continue')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('filetypes');
  });

  it('lets a custom run step back from the file types to its options', async () => {
    await open('custom');
    await advanceTo('options');
    button('Continue')!.click();
    await fixture.whenStable();

    button('Back')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('options');
  });

  it('ties a custom run’s JSON to whether it is indexing', async () => {
    // json *is* the index, so a run that indexes writes it and a run that does not cannot
    debugOn();
    await open('custom');
    await advanceTo('options');
    button('Continue')!.click();
    await fixture.whenStable();

    const json = checkbox('JSON')!;
    expect(json.checked).toBe(true);
    expect(json.disabled).toBe(true);
  });

  it('unticks and locks a custom run’s JSON when it is not indexing', async () => {
    debugOn();
    await open('custom');
    await advanceTo('options');
    checkbox('Skip check for new bookmarks')!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();

    const json = checkbox('JSON')!;
    expect(json.checked).toBe(false);
    expect(json.disabled).toBe(true);
    expect(element.querySelector('.body')?.textContent).toContain('no JSON is written');
  });

  it('does not ask the helper for JSON it will not write', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Skip check for new bookmarks')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].filetypes).not.toContain('JSON');
    expect(jobs.started[0].filetypes).toContain('HTML');
  });

  it('asks the helper for JSON when the custom run is indexing', async () => {
    await open('custom');
    await advanceTo('running');

    expect(jobs.started[0].filetypes).toContain('JSON');
  });

  it('leaves JSON locked on for every other run', async () => {
    debugOn();
    await open('bookmarks');
    await advanceTo('filetypes');

    const json = checkbox('JSON')!;
    expect(json.checked).toBe(true);
    expect(json.disabled).toBe(true);
  });

  it('sends a custom run told to skip indexing', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Skip check for new bookmarks')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.reindex).toBe(false);
  });

  it("offers skipping the indexing as a choice of what a custom run covers, with its hint and warning", async () => {
    await open('custom');
    await advanceTo('options');
    expect(element.querySelector('.skip-index-hint')).toBeNull();

    const choice = checkbox('Skip check for new bookmarks - Just update existing works')!;
    expect(choice.type).toBe('radio');
    expect(choice.name).toBe('coverage');
    choice.click();
    await fixture.whenStable();

    expect(element.querySelector('.skip-index-hint')!.textContent!.replace(/\s+/g, ' ')).toContain(
      'Simply checks all your existing works in FicFairy for downloads/updates.');
    expect(element.querySelector('.skip-index-warning')).toBeTruthy();
    // an alternative to the others: choosing it puts the date range away
    expect(checkbox('Choose my own date range')!.checked).toBe(false);
    await advanceTo('running');
    expect(jobs.started[0].options).toMatchObject({ reindex: false, dates: false, pages: 0 });
  });

  it('words the overwrite and series options plainly', async () => {
    await open('custom');
    await advanceTo('options');
    const label = (text: string) => checkbox(text)!.closest('label')!.parentElement!.textContent!.replace(/\s+/g, ' ');
    expect(checkbox('Overwrite existing downloads')).toBeTruthy();
    expect(label('Overwrite existing downloads')).toContain(
      'Regardless of whether the file was updated on AO3, just replace everything. Choose which formats get replaced on the next page.');
    expect(label('If a work is a part of a series, download all its other works too')).toContain(
      'Downloads all works whenever a series is found - even if its other works are not bookmarked by you.');
  });

  it('asks the lighter runs nothing about pages', async () => {
    // they start at the first page by definition; there is nothing to choose
    await open('sync');
    await advanceTo('options');

    expect(element.querySelector('input[name="pages"]')).toBeNull();
    expect(element.querySelector('input[name="start"]')).toBeNull();
  });

  it('says a long run is expected to be left running', async () => {
    await open('sync');
    await advanceTo('running');

    expect(element.querySelector('.warning')?.textContent).toContain('may take a long time');
    expect(element.querySelector('.warning')?.textContent).toContain('Leave this tab open');
  });

  // endregion

  // region the debug panel

  async function runningWithDebug(on: boolean) {
    jobs.settingsOverride = { ...CONFIG.settings!, debugTools: on };
    await open('sync');
    await advanceTo('running');
  }

  it('hides the debug panel unless settings.ini asks for it', async () => {
    // skipping a step really skips it, so this is not something to leave lying about
    await runningWithDebug(false);

    expect(element.querySelector('.settings.debug')).toBeNull();
  });

  it('shows the debug panel when settings.ini asks for it', async () => {
    await runningWithDebug(true);

    const panel = element.querySelector('.settings.debug');
    expect(panel).toBeTruthy();
    expect(button('Skip this step')).toBeTruthy();
    expect(button('Show a made-up report')).toBeTruthy();
  });

  it('asks the helper to skip the current step', async () => {
    await runningWithDebug(true);

    button('Skip this step')!.click();
    await fixture.whenStable();

    expect(jobs.skipped).toEqual(['job-1']);
    expect(element.querySelector('.log')?.textContent).toContain('skipping the rest');
  });

  it('says so when a skip is refused rather than pretending it worked', async () => {
    jobs.skipFails = true;
    await runningWithDebug(true);

    button('Skip this step')!.click();
    await fixture.whenStable();

    expect(element.querySelector('.log')?.textContent).toContain('could not skip');
  });

  it('fills both report lists with one of every kind, and says they are made up', async () => {
    await runningWithDebug(true);

    button('Show a made-up report')!.click();
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('a series, not a single work');
    expect(said).toContain('an external work');
    expect(said).toContain('the work has been deleted');
    expect(said).toContain('unrevealed collection');
    expect(said).toContain('made private, or hidden');
    // and the failures list, which is the other half of the report
    expect(element.querySelector('.failures:not(.skipped)')?.textContent).toContain(
      'timed out',
    );
  });

  it('sends nothing to the helper for a made-up report', async () => {
    // it is a picture of the layout, not a result - no run is affected
    await runningWithDebug(true);

    button('Show a made-up report')!.click();
    await fixture.whenStable();

    expect(jobs.skipped).toEqual([]);
    expect(jobs.cancelled).toEqual([]);
  });

  // endregion

  // region a login that lapses mid-run

  it('explains an expired login rather than showing a bare error', async () => {
    await open('sync');
    await advanceTo('running');

    jobs.push!({ type: 'failed', error: 'AO3 has stopped recognising your login',
                 sessionExpired: true });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('login expired while this was running');
    expect(said).toContain('Nothing was lost');
    // and says what to do, because re-running really does continue from what is missing
    expect(said).toContain('carries on from what is still missing');
  });

  it('shows an ordinary failure as itself', async () => {
    await open('sync');
    await advanceTo('running');

    jobs.push!({ type: 'failed', error: 'something else went wrong' });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('something else went wrong');
    expect(said).not.toContain('login expired');
  });

  // endregion

  // region the checklist of steps

  async function runningWithSteps(steps: { id: string; label: string }[]) {
    await open('sync');
    await advanceTo('running');
    jobs.push!({ type: 'steps', steps });
    await fixture.whenStable();
  }

  function stepRows() {
    return Array.from(element.querySelectorAll('.step-list li')).map((li) => ({
      label: li.querySelector('.step-label')?.textContent?.trim(),
      state: li.querySelector('.step-state')?.textContent?.trim(),
      status: li.className,
    }));
  }

  it('shows what the run intends to do before it has done any of it', async () => {
    // the point of the panel: what is still to come, not only what has happened
    await runningWithSteps([
      { id: 'login', label: 'Log in to AO3' },
      { id: 'index', label: 'Index bookmarks added since last time' },
    ]);

    expect(stepRows().map((r) => r.label)).toEqual([
      'Log in to AO3',
      'Index bookmarks added since last time',
    ]);
    expect(stepRows().every((r) => r.state === 'waiting')).toBe(true);
  });

  it('moves a step to in progress and then to done', async () => {
    await runningWithSteps([{ id: 'index', label: 'Index' }]);

    jobs.push!({ type: 'step', id: 'index', status: 'running' });
    await fixture.whenStable();
    expect(stepRows()[0].state).toBe('in progress');
    expect(stepRows()[0].status).toContain('step-running');

    jobs.push!({ type: 'step', id: 'index', status: 'done' });
    await fixture.whenStable();
    expect(stepRows()[0].state).toBe('done');
  });

  it('does not make a skipped step look like a failed one', async () => {
    // a run with no unfinished fics skips that step and nothing has gone wrong
    await runningWithSteps([
      { id: 'update', label: 'Update' },
      { id: 'gaps', label: 'Gaps' },
    ]);

    jobs.push!({ type: 'step', id: 'update', status: 'skipped' });
    jobs.push!({ type: 'step', id: 'gaps', status: 'failed' });
    await fixture.whenStable();

    expect(stepRows()[0].state).toBe('skipped');
    expect(stepRows()[0].status).not.toContain('step-failed');
    expect(stepRows()[0].status).toContain('step-skipped');
    expect(stepRows()[1].state).toBe('failed');

    // tagged on the line itself, so it reads as skipped without reading the column
    expect(stepRows()[0].label).toContain('[SKIP]');
    expect(stepRows()[1].label).not.toContain('[SKIP]');
  });

  it('counts how far through the run is', async () => {
    await runningWithSteps([
      { id: 'a', label: 'A' },
      { id: 'b', label: 'B' },
      { id: 'c', label: 'C' },
    ]);

    jobs.push!({ type: 'step', id: 'a', status: 'done' });
    jobs.push!({ type: 'step', id: 'b', status: 'skipped' });
    await fixture.whenStable();

    // a skipped step is behind the run just as much as a finished one
    expect(element.querySelector('.step-count')?.textContent).toContain('2 of 3');
  });

  it('leaves the other steps alone when one changes', async () => {
    await runningWithSteps([
      { id: 'a', label: 'A' },
      { id: 'b', label: 'B' },
    ]);

    jobs.push!({ type: 'step', id: 'b', status: 'running' });
    await fixture.whenStable();

    expect(stepRows()[0].state).toBe('waiting');
    expect(stepRows()[1].state).toBe('in progress');
  });

  it('shows no panel at all before a run has published a plan', async () => {
    await open('sync');
    await advanceTo('running');

    expect(element.querySelector('.run-steps')).toBeNull();
  });

  it('does not carry a checklist over into the next run', async () => {
    await runningWithSteps([{ id: 'a', label: 'A' }]);

    await open('sync');
    await advanceTo('running');

    expect(element.querySelector('.run-steps')).toBeNull();
  });

  // endregion

  // region bookmarks that were never works

  async function finishedWithSkipped(rows: unknown[]) {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'skipped', skipped: rows as never });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();
  }

  it('names each bookmark it could not download, and why', async () => {
    await finishedWithSkipped([
      { id: '12345', link: 'https://ao3/series/12345', title: 'A Series',
        error: 'a series, not a single work' },
      { id: null, link: '', title: 'Gone', error: 'the work has been deleted' },
    ]);

    const said = element.querySelector('.failures.skipped')?.textContent ?? '';
    expect(said).toContain('2');
    expect(said).toContain('a series, not a single work');
    expect(said).toContain('the work has been deleted');
  });

  it('still identifies a skipped bookmark that has no link at all', async () => {
    // a deleted work has no number and no link, so the title is all there is to show
    await finishedWithSkipped([
      { id: null, link: '', title: 'Gone', error: 'the work has been deleted' },
    ]);

    expect(element.querySelector('.failures.skipped')?.textContent).toContain('Gone');
  });

  it('does not call a skipped bookmark a failure', async () => {
    // nothing went wrong: there was no work there to fetch
    await finishedWithSkipped([
      { id: '1', link: 'https://ao3/series/1', title: 'S', error: 'a series' },
    ]);

    const said = element.querySelector('.failures.skipped')?.textContent ?? '';
    expect(said).toContain('Nothing has gone wrong');
    // and the red failures panel is not showing, because there were none
    expect(element.querySelector('.failures:not(.skipped)')).toBeNull();
  });

  it('offers the skipped list as a file, with a reason on every row', async () => {
    await finishedWithSkipped([
      { id: '12345', link: 'https://ao3/series/12345', title: 'S',
        error: 'a series, not a single work' },
      { id: null, link: '', title: 'Gone', error: 'the work has been deleted' },
    ]);

    // saved from the History tab now; this window says so
    expect(element.querySelector('.export-issues')?.textContent).toContain('History');

    const report = (fixture.componentInstance as unknown as {
      issuesReport(): string;
    }).issuesReport();
    expect(report).toContain('## 2 bookmarks that are not works');
    expect(report).toContain('12345\thttps://ao3/series/12345\ta series, not a single work');
    expect(report).toContain('\t\tthe work has been deleted');
  });

  it('suggests dating the files a run had to guess about, and hands that on to the app', async () => {
    await open('bookmarks');
    await advanceTo('running');
    let asked = 0;
    fixture.componentInstance.resolveIssues.subscribe(() => asked++);
    jobs.push!({ type: 'unsureFiles', count: 3 });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    const said = (element.querySelector('.unsure-files')?.textContent ?? '').replace(/\s+/g, ' ');
    expect(said).toContain('3 files in your library had no date in their names');
    expect(said).toContain('Resolve issues');
    element.querySelector<HTMLButtonElement>('.unsure-files button')!.click();
    expect(asked).toBe(1);
  });

  it('says nothing about dating when a run met no such files', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();
    expect(element.querySelector('.unsure-files')).toBeNull();
  });

  it('lists old copies that could not be deleted, and puts every issue in one file', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({
      type: 'skipped',
      skipped: [{ id: '1', link: 'a', title: 'S', error: 'a series' }] as never,
    });
    jobs.push!({ type: 'failures', failures: [{ id: '2', link: 'b', error: 'timed out' }] });
    jobs.push!({
      type: 'keptCopies',
      keptCopies: [{ id: '3', link: 'c', file: '3 New 2026-09-14.html',
                     old: '3 New 2026-01-01.html', error: 'locked' }],
    });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    const kept = element.querySelector('.failures.kept')?.textContent ?? '';
    expect(kept).toContain('checking by hand');
    expect(kept).toContain('3 New 2026-09-14.html');

    // saved from the History tab now; this window says so
    expect(element.querySelector('.export-issues')?.textContent).toContain('History');

    const report = (fixture.componentInstance as unknown as {
      issuesReport(): string;
    }).issuesReport();
    const headings = report.split('\n').filter((x) => x.startsWith('## '));
    expect(headings).toEqual([
      '## 1 work that could not be downloaded',
      '## 1 new copy downloaded that needs checking by hand',
      '## 1 bookmark that is not a work',
    ]);
    // the ids sit under their own heading
    const lines = report.split('\n');
    expect(lines[lines.indexOf(headings[1]) + 2]).toBe(
      '3\tc\t3 New 2026-09-14.html\t3 New 2026-01-01.html\tlocked');
  });

  it('keeps the two lists apart when a run has both', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({
      type: 'skipped',
      skipped: [{ id: '1', link: 'a', title: 'S', error: 'a series' }] as never,
    });
    jobs.push!({ type: 'failures', failures: [{ id: '2', link: 'b', error: 'timed out' }] });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    expect(element.querySelector('.failures.skipped')).toBeTruthy();
    expect(element.querySelector('.failures:not(.skipped)')).toBeTruthy();
  });

  it('does not carry a skipped list into the next run', async () => {
    await finishedWithSkipped([{ id: '1', link: 'a', title: 'S', error: 'a series' }]);

    await open('bookmarks');
    await advanceTo('running');

    expect(element.querySelector('.failures.skipped')).toBeNull();
  });

  // endregion

  // region pausing a run

  async function running() {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'phase', name: 'downloading' });
    await fixture.whenStable();
  }

  async function press(text: string) {
    button(text)!.click();
    await fixture.whenStable();
  }

  it('offers pausing alongside stopping while a run is going', async () => {
    await running();

    expect(button('Pause')).toBeTruthy();
    expect(button('Stop')).toBeTruthy();
  });

  it('does not say it is paused until the run says it has stopped', async () => {
    // the helper only sets a flag; the run acts on it at its next safe point, which can be
    // a whole file later. saying 'Paused' on the button press would claim it had stopped
    // while it was still downloading
    await running();

    await press('Pause');

    expect(jobs.pauses).toEqual([{ jobId: 'job-1', paused: true }]);
    expect(button('Pausing...')).toBeTruthy();
    expect(element.querySelector('.warning.held')).toBeNull();

    jobs.push!({ type: 'held' });
    await fixture.whenStable();

    expect(button('Resume')).toBeTruthy();
    expect(element.querySelector('.warning.held')?.textContent).toContain('Paused');
  });

  it('lets a paused run go again', async () => {
    await running();
    await press('Pause');
    jobs.push!({ type: 'held' });
    await fixture.whenStable();

    await press('Resume');
    expect(jobs.pauses.at(-1)).toEqual({ jobId: 'job-1', paused: false });

    jobs.push!({ type: 'released' });
    await fixture.whenStable();

    expect(button('Pause')).toBeTruthy();
    expect(element.querySelector('.warning.held')).toBeNull();
  });

  it('can still be stopped while it is paused', async () => {
    // a pause must never be able to trap a run, so stopping is never blocked behind it
    await running();
    await press('Pause');
    jobs.push!({ type: 'held' });
    await fixture.whenStable();

    expect(button('Stop')?.disabled).toBe(false);
    await press('Stop');

    expect(jobs.cancelled).toEqual(['job-1']);
  });

  it('does not claim a pause that the helper refused', async () => {
    // saying 'Paused' over a run that is still downloading is the worst of both
    jobs.pauseFails = 'could not pause the run';
    await running();

    await press('Pause');

    expect(button('Pause')).toBeTruthy();
    expect(element.querySelector('.warning.held')).toBeNull();
    expect(element.querySelector('.log')?.textContent).toContain('could not pause');
  });

  it('passes on why the pause was refused rather than a generic line', async () => {
    // a pause refused because the helper is older than the page is fixed by restarting the
    // app, and a flat 'could not pause' gives nobody a way to work that out
    jobs.pauseFails =
      'could not pause the run - the helper may be an older version that does not ' +
      'support pausing. Restart the app to update it.';
    await running();

    await press('Pause');

    expect(element.querySelector('.log')?.textContent).toContain('Restart the app');
  });

  it('offers no pause while the run is stopped waiting on a question', async () => {
    // it is already stopped dead waiting for the answer; a pause there would claim to do
    // something it cannot
    await running();
    jobs.push!({ type: 'question', name: 'undated', count: 2 });
    await fixture.whenStable();

    expect(button('Pause')).toBeUndefined();
    expect(button('Stop')).toBeTruthy();
  });

  it('does not carry a pause over into the next run', async () => {
    await running();
    await press('Pause');
    jobs.push!({ type: 'held' });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    expect(element.querySelector('.warning.held')).toBeNull();
  });

  // endregion

  it('names the stages an update run goes through', async () => {
    // an update run has no separate download stage: it re-reads and fetches one fic at a
    // time, so the last stage it reports covers both
    await toAcknowledgement();
    acknowledgeBox()!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();

    const password = element.querySelector<HTMLInputElement>('input[name="password"]')!;
    password.value = 'a-password';
    password.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    button('Start download')!.click();
    await fixture.whenStable();

    jobs.push!({ type: 'phase', name: 'scanning' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain('Reading your index');

    jobs.push!({ type: 'phase', name: 'checking_files' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain(
      'already downloaded',
    );

    jobs.push!({ type: 'phase', name: 'updating' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain(
      'Re-reading each unfinished fic',
    );
  });

  it('restarts the bar when the stage changes', async () => {
    // each stage has its own scale, so carrying a percentage across would be a lie
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 20, total: 20 });
    await fixture.whenStable();
    expect(element.querySelector('.percent')?.textContent).toContain('100');

    jobs.push!({ type: 'phase', name: 'downloading' });
    await fixture.whenStable();
    expect(element.querySelector('.percent')).toBeNull();
  });

  it('tracks progress from page events', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 20, total: 80, works: 400 });
    await fixture.whenStable();

    expect(element.querySelector('.percent')?.textContent).toContain('25');
  });

  // the fetch is the slow part of indexing, so naming the page that just finished names
  // the wrong page for as long as the next one takes to arrive
  it('names the page being fetched, not the last one that finished', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({
      type: 'page',
      page: 3,
      total: 80,
      listingPage: 3,
      listingTotal: 80,
      works: 57,
    });
    await fixture.whenStable();
    expect(element.querySelector('.status')?.textContent).toContain('page 3 of 80');

    jobs.push!({
      type: 'page',
      page: 4,
      total: 80,
      listingPage: 4,
      listingTotal: 80,
      fetching: true,
    });
    await fixture.whenStable();

    expect(element.querySelector('.status')?.textContent).toContain('fetching page 4 of 80');
  });

  it('does not count a page as done while it is still being fetched', async () => {
    // the caption names what is in flight; the bar still measures what has arrived
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 21, total: 80, fetching: true });
    await fixture.whenStable();

    expect(element.querySelector('.percent')?.textContent).toContain('25');
  });

  // a walk stopped by a date floor, or by the first fic already indexed, cannot know how
  // many pages it will read - so a finished page has no 'of', and certainly not 'of ?'
  it('gives no total for a page on a walk that can stop anywhere', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 3, listingPage: 3, works: 57 });
    await fixture.whenStable();

    const said = element.querySelector('.status')?.textContent ?? '';
    expect(said).toContain('page 3 - 57 works so far');
    expect(said).not.toContain(' of ');
  });

  it('names the first page before anything knows how many there are', async () => {
    // the total comes off the page itself, so the first fetch has no total to report
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 1, listingPage: 1, fetching: true });
    await fixture.whenStable();

    const said = element.querySelector('.status')?.textContent ?? '';
    expect(said).toContain('fetching page 1');
    expect(said).not.toContain('of ?');
  });

  it('warns when ao3 asks the run to slow down', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'paused', seconds: 300, until: '12:05:00' });
    await fixture.whenStable();

    const pause = element.querySelector('.pause')?.textContent ?? '';
    expect(pause).toContain('300');
    expect(pause).toContain('12:05:00');

    jobs.push!({ type: 'resumed' });
    await fixture.whenStable();
    expect(element.querySelector('.pause')).toBeNull();
  });

  // endregion

  // region stopping

  it('offers a stop button while the run is working', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(button('Stop')).toBeTruthy();
  });

  it('asks the helper to stop when it is pressed', async () => {
    await open('bookmarks');
    await advanceTo('running');

    button('Stop')!.click();
    await fixture.whenStable();

    expect(jobs.cancelled).toEqual(['job-1']);
    // and does not let it be pressed twice
    expect(button('Stopping...')?.disabled).toBe(true);
  });

  it('reports a stop as kept work rather than a failure', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'finished', cancelled: true });
    await fixture.whenStable();

    expect(element.querySelector('.error')).toBeNull();
    const warning = element.querySelector('.warning')?.textContent ?? '';
    expect(warning).toContain('Stopped');
    expect(warning).toContain('kept');
  });

  it('offers a way out of the modal once the stop has taken effect', async () => {
    await open('bookmarks');
    await advanceTo('running');

    button('Stop')!.click();
    await fixture.whenStable();
    jobs.push!({ type: 'finished', cancelled: true });
    await fixture.whenStable();

    expect(button('Stopping...')).toBeUndefined();
    expect(button('Close modal')).toBeTruthy();
  });

  it('reports a clean finish as success', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'finished', cancelled: false });
    await fixture.whenStable();

    expect(element.querySelector('.success')?.textContent).toContain('Finished');
  });

  // endregion

  // region retrying an earlier run

  const ALL_MODES = (available: Partial<Record<string, string>> = {}) =>
    (['top', 'reindex', 'index', 'redownload', 'downloads', 'failed'] as const).map((mode) => ({
      mode, available: !(mode in available), reason: available[mode] ?? '',
    }));

  function ended(over: Partial<RetryableRun> = {}): RetryableRun {
    return {
      file: 'r.json', id: 'r1', action: 'quick', actionName: 'Quick Scan',
      started: '2026-09-20T21:15:00', finished: null, status: 'partial',
      filetypes: ['JSON', 'PDF'], options: { series: true, nonBookmarks: true },
      reindexed: [], downloaded: [], updated: [], choices: [], failures: [], skipped: [],
      error: '',
      progress: {
        step: 'download', stepLabel: 'Download or update works as necessary',
        stepPlan: [['login', 'Log in'], ['bookmarked', 'Index newly bookmarked'],
                   ['index', 'Index recently updated'], ['download', 'Download']],
        steps: { login: 'done', bookmarked: 'done', index: 'failed', download: 'done' },
      },
      retry: { modes: ALL_MODES({ failed: 'Every work it set out to get arrived.' }),
               default: 'index', failedWorks: 0 },
      warnings: [], ...over,
    };
  }

  async function toRetryPage() {
    await open('custom');
    await advanceTo('options');
    checkbox('Retry an earlier run')!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();
  }

  async function pick(id = 'r1') {
    element.querySelector<HTMLInputElement>(`input[name="resumeRun"][value="${id}"]`)!.click();
    await fixture.whenStable();
  }

  async function toHow() {
    button('Continue')!.click();
    await fixture.whenStable();
  }

  async function acknowledge() {
    element.querySelector<HTMLInputElement>('input[name="retryAcknowledged"]')!.click();
    await fixture.whenStable();
  }

  it('puts retrying last among what a custom run covers, and hides the options it takes over', async () => {
    await open('custom');
    await advanceTo('options');
    const radios = Array.from(element.querySelectorAll<HTMLInputElement>('input[name="coverage"]'));
    const last = radios[radios.length - 1].closest('label')?.textContent ?? '';
    expect(last).toContain('Retry an earlier run');
    const options = element.querySelector<HTMLFieldSetElement>('fieldset.bare')!;
    expect(options.hidden).toBe(false);

    checkbox('Retry an earlier run')!.click();
    await fixture.whenStable();
    expect(options.hidden).toBe(true);
  });

  it('offers retrying an earlier run on a custom run only, with no experimental label',
    async () => {
      await open('custom');
      await advanceTo('options');
      expect(checkbox('Retry an earlier run')).toBeDefined();
      expect(element.querySelector('.body')?.textContent).not.toContain('[EXPERIMENTAL] Retry');

      fixture.destroy();
      await open('quick');
      await advanceTo('options');
      expect(checkbox('Retry an earlier run')).toBeUndefined();
    });

  it('greys out every other option once retrying is chosen', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Retry an earlier run')!.click();
    await fixture.whenStable();

    for (const label of ['Overwrite existing downloads',
                         'download all its other works too']) {
      // disabled by the fieldset around them, which the property does not reflect
      expect(checkbox(label)!.matches(':disabled')).toBe(true);
    }
  });

  it('says under a run that cannot be retried why not, where it is listed', async () => {
    jobs.retryableOnRecord = [
      ended({ id: 'r3', actionName: 'Collection',
              retry: { modes: ALL_MODES({ top: 'It has no link to go back to.', reindex: 'x', index: 'x',
                                          redownload: 'x', downloads: 'x', failed: 'x' }),
                       default: '', failedWorks: 0 } }),
    ];
    await toRetryPage();

    const row = element.querySelector('.floor-runs label.unavailable')!;
    expect(row.querySelector('.why-not')?.textContent).toContain('It has no link to go back to.');
  });

  it('no longer says on the first page that a slice cannot be retried', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Retry an earlier run')!.click();
    await fixture.whenStable();
    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('Retry a run that was stopped, failed, or interrupted. Some previous runs can be');
    expect(said).not.toContain('slice of pages');
  });

  it('lists every ended run, finished ones included, with any warnings', async () => {
    jobs.retryableOnRecord = [
      ended({ warnings: ['It has already been resumed once.'] }),
      ended({ id: 'r2', status: 'success', actionName: 'Full Scan',
              retry: { modes: ALL_MODES({ reindex: 'x', index: 'x', redownload: 'x', downloads: 'x', failed: 'x' }),
                       default: 'top', failedWorks: 0 } }),
    ];
    await toRetryPage();

    expect(currentStep()).toBe('resume');
    const said = element.querySelector('.floor-runs')?.textContent ?? '';
    expect(said).toContain('Quick Scan');
    expect(said).toContain('partly finished');
    expect(said).toContain('Full Scan');
    expect(said).toContain('finished');
    expect(said).toContain('It has already been resumed once.');
    expect(button('Continue')!.disabled).toBe(true);
  });

  it('says how each step went, the last one that finished, and offers carrying on from there',
    async () => {
      jobs.retryableOnRecord = [ended()];
      await toRetryPage();
      await pick();

      const steps = Array.from(element.querySelectorAll('.retry-steps li'))
        .map((li) => li.textContent?.replace(/\s+/g, ' ').trim());
      expect(steps).toEqual([
        'Log in - finished', 'Index newly bookmarked - finished',
        'Index recently updated - failed', 'Download - finished',
      ]);
      expect(element.querySelector('.retry-steps .hint')?.textContent)
        .toContain('The last step it finished was Index newly bookmarked');

      // how to retry it is on a page of its own, after the list
      await toHow();
      expect(currentStep()).toBe('retry-how');
      // the helper's default is picked, and a way it cannot be retried is greyed with why
      const modes = Array.from(element.querySelectorAll<HTMLInputElement>('input[name="retryMode"]'));
      expect(modes.find((m) => m.checked)?.value).toBe('index');
      // every way, in order: from the top, then indexing from its start or where it stopped,
      // then downloads from their start or where they stopped, then just the failures
      expect(modes.map((m) => m.value)).toEqual(
        ['top', 'reindex', 'index', 'redownload', 'downloads', 'failed']);
      const said = element.querySelector('.retry-modes')?.textContent ?? '';
      expect(said).toContain('Start its indexing from the top');
      expect(said).toContain('Start its downloads from the top');
      expect(said).toContain('the rest of one it was partway through');
      const failed = modes.find((m) => m.value === 'failed')!;
      expect(failed.disabled).toBe(true);
      expect(failed.closest('label')!.title).toContain('Every work it set out to get arrived');
    });

  it('says on the retry page what went wrong on the run being retried', async () => {
    const failures = Array.from({ length: 7 }, (_, i) => ({
      id: String(100 + i), link: `https://archiveofourown.org/works/${100 + i}`,
      error: 'not found', reason: 'status', status: 404,
    }));
    jobs.retryableOnRecord = [ended({
      status: 'stopped',
      failures,
      skipped: [{ id: null, link: '', error: 'a series' }],
      keptCopies: [{ id: '9', link: '', error: 'could not delete', file: '9 A - B 2026-01-01.pdf' }],
      indexFailures: [{
        kind: 'listing', walk: 'updated', sort: 'updated', failedPage: 4, totalPages: 9,
        firstPage: 1, lastPage: 3, works: 60, reason: 'maintenance', error: '',
      }],
    })];
    await toRetryPage();
    await pick();
    await toHow();

    const said = element.querySelector('.retry-issues')?.textContent ?? '';
    expect(said).toContain('What went wrong last time');
    expect(said).toContain('It was stopped before it finished');
    expect(said).toContain('Its indexing broke off in 1 place');
    expect(said).toContain('stopped at page 4 of 9: AO3 was down for maintenance');
    expect(said).toContain('7 works could not be downloaded');
    expect(said).toContain('Work 100: AO3 answered with status 404');
    // the first five, then how many more
    expect(said).not.toContain('Work 105');
    expect(said).toContain('and 2 more');
    expect(said).toContain('1 copy needs checking by hand');
    // retrying cannot turn a series into a work, so it is not one of the run's problems
    expect(said).not.toContain('a series');
  });

  it('says on the retry page when the run being retried recorded nothing wrong', async () => {
    jobs.retryableOnRecord = [ended({ status: 'success' })];
    await toRetryPage();
    await pick();
    await toHow();

    expect(element.querySelector('.retry-issues')?.textContent).toContain('Nothing');
  });

  it('retries a run that went without logging in without asking for a password', async () => {
    jobs.retryableOnRecord = [ended({ options: { skipLogin: true }, username: 'Someone' })];
    await toRetryPage();
    await pick();
    await toHow();
    element.querySelector<HTMLInputElement>('input[name="retryMode"][value="top"]')!.click();
    await fixture.whenStable();
    await acknowledge();
    button('Continue')!.click();
    await fixture.whenStable();
    await advanceTo('credentials');

    expect(element.querySelector('input[name="password"]')).toBeNull();
    expect(checkbox('Skip AO3 login?')!.checked).toBe(true);
    // a quick scan reads your bookmarks, found by the account the earlier run read
    expect(element.querySelector<HTMLInputElement>('input[name="username"]')?.value).toBe('Someone');

    await advanceTo('running');
    expect(jobs.started[0].options.skipLogin).toBe(true);
    expect(jobs.started[0].password).toBe('');
  });

  it('starts the retry as the run it retries, with the way of retrying chosen', async () => {
    jobs.retryableOnRecord = [ended()];
    await toRetryPage();
    await pick();
    await toHow();
    element.querySelector<HTMLInputElement>('input[name="retryMode"][value="top"]')!.click();
    await fixture.whenStable();
    await acknowledge();
    button('Continue')!.click();
    await fixture.whenStable();

    // the file types are the earlier run's, and cannot be changed
    expect(currentStep()).toBe('filetypes');
    const pdf = Array.from(element.querySelectorAll<HTMLLabelElement>('label'))
      .find((l) => l.textContent?.includes('PDF'))!.querySelector('input')!;
    expect(pdf.checked).toBe(true);
    expect(pdf.disabled).toBe(true);

    await advanceTo('running');

    const started = jobs.started[0];
    // a quick scan stays a quick scan
    expect(started.action).toBe('quick');
    expect(started.filetypes).toEqual(['JSON', 'PDF']);
    expect(started.options.resume).toBe('r1');
    expect(started.options.retryMode).toBe('top');
  });

  it('retries a fic run as a custom run, which the helper turns back into the fic run', async () => {
    jobs.retryableOnRecord = [ended({
      action: 'works', actionName: 'Download several fics', status: 'failed',
      failures: [{ id: '7', link: 'https://archiveofourown.org/works/7', error: 'gone' }],
      retry: { modes: ALL_MODES().filter((m) => m.mode === 'top' || m.mode === 'failed'),
               default: 'failed', failedWorks: 1 },
    })];
    await toRetryPage();
    await pick();
    await toHow();

    expect(element.querySelector('.retry-modes')?.textContent).toContain('Just the 1 work it could not get');
    await acknowledge();
    button('Continue')!.click();
    await fixture.whenStable();
    await advanceTo('running');

    expect(jobs.started[0].action).toBe('custom');
    expect(jobs.started[0].options.retryMode).toBe('failed');
  });

  it('asks for the original run\'s dates and settings to be acknowledged before going on',
    async () => {
      jobs.retryableOnRecord = [ended({
        baseline: '2026-09-20T21:15:00', options: { series: true, overwrite: true },
        progress: { ...ended().progress, floor: '2026-09-01' },
      })];
      await toRetryPage();
      await pick();
      await toHow();

      const terms = element.querySelector('.retry-terms')?.textContent?.replace(/\s+/g, ' ') ?? '';
      expect(terms).toContain('Back to 2026-09-01, and up to 2026-09-20');
      expect(terms).toContain('File types: JSON, PDF');
      expect(terms).toContain('overwrite existing downloads');
      expect(terms).toContain('get all works from encountered series');
      expect(button('Continue')!.disabled).toBe(true);

      await acknowledge();
      expect(button('Continue')!.disabled).toBe(false);

      // picking another way of retrying the same run keeps the tick
      element.querySelector<HTMLInputElement>('input[name="retryMode"][value="top"]')!.click();
      await fixture.whenStable();
      expect(button('Continue')!.disabled).toBe(false);
    });

  it('shows the chosen run\'s warnings in a panel of their own', async () => {
    jobs.retryableOnRecord = [ended({
      warnings: ['Some of its indexing failed, so it may have missed fics.'],
    })];
    await toRetryPage();
    await pick();
    await toHow();

    expect(element.querySelector('.retry-warning')?.textContent)
      .toContain('Some of its indexing failed');
  });

  it('names a date range as the dates a retry keeps', async () => {
    jobs.retryableOnRecord = [ended({
      action: 'custom', actionName: 'Custom run',
      options: { dates: true, dateFrom: '2026-01-01', dateTo: '2026-02-01' },
    })];
    await toRetryPage();
    await pick();
    await toHow();

    expect(element.querySelector('.retry-dates')?.textContent)
      .toContain('Fics AO3 updated from 2026-01-01 to 2026-02-01');
  });

  it('offers several fics carrying on from where they stopped', async () => {
    jobs.retryableOnRecord = [ended({
      action: 'works', actionName: 'Download several fics', status: 'stopped',
      retry: { modes: ALL_MODES().filter((m) => ['top', 'downloads', 'failed'].includes(m.mode)),
               default: 'downloads', failedWorks: 0 },
    })];
    await toRetryPage();
    await pick();
    await toHow();

    expect(element.querySelector('.retry-modes')?.textContent)
      .toContain('Carry on from where it stopped - a fic it saved in every format is passed over');
    expect(element.querySelector<HTMLInputElement>('input[name="retryMode"]:checked')!.value)
      .toBe('downloads');
  });

  it('opens a retry picked from the history straight on how to retry it', async () => {
    jobs.retryableOnRecord = [ended()];
    listsRead = 0;
    fixture = TestBed.createComponent(DownloadDialog);
    fixture.componentRef.setInput('action', 'custom');
    fixture.componentRef.setInput('resumeFrom', 'r1');
    await fixture.whenStable();
    element = fixture.nativeElement as HTMLElement;
    await new Promise((done) => setTimeout(done, 0));
    await fixture.whenStable();

    // straight to how it is retried: the list of every earlier run is never read
    expect(currentStep()).toBe('retry-how');
    expect(element.querySelector('.retry-which')?.textContent).toContain('Quick Scan');
    expect(element.querySelector<HTMLInputElement>('input[name="retryMode"]:checked')!.value).toBe('index');
    expect(listsRead).toBe(0);

    // going back reads the list then, with the run still chosen
    button('Back')!.click();
    await fixture.whenStable();
    await new Promise((done) => setTimeout(done, 0));
    await fixture.whenStable();
    expect(currentStep()).toBe('resume');
    expect(listsRead).toBe(1);
    expect(element.querySelector<HTMLInputElement>('input[name="resumeRun"]')!.checked).toBe(true);
  });

  // endregion
});
