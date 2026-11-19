import { DeviceSupport } from './device-support';
import { LibrarySetup } from './library-setup';
import { LibraryImports } from './imports';
import { DebugMode } from './debug';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App, shownTime } from './app';
import { BUILT_IN_CONFIG, Jobs, ServerConfig } from './jobs';
import { Library } from './library';
import { UpdateCheck } from './updates';
import { Bookmark, BookmarksExport } from './bookmarks';
import { Collection } from './collections';
import { DropboxSession } from './dropbox';
import { HelperConnection } from './helper-connection';
import { Turnstile } from './feedback';
import { StorageChoice } from './storage-choice';

function work(id: number): Bookmark {
  return {
    id: String(id),
    link: `https://archiveofourown.org/works/${id}`,
    title: `Work ${id}`,
    authors: ['Writer'],
    date_created: null,
    date_updated: '01 Jan 2020',
    fandoms: ['A Fandom'],
    warnings: ['No Archive Warnings Apply'],
    tags: {
      rating: 'Teen And Up Audiences',
      categories: ['M/M'],
      relationships: [],
      characters: [],
      additional: ['a tag'],
    },
    summary: 'first line\nsecond line',
    words: 1234,
    chapters_published: 3,
    chapters_total: null,
    comments: null,
    kudos: 7,
    bookmarks: null,
    hits: null,
    date_bookmarked: '02 Feb 2021',
    bookmark_notes: '',
    bookmark_tags: [],
    bookmark_collections: [],
    bookmark_private: false,
    bookmark_rec: false,
  };
}

function exportOf(count: number): BookmarksExport {
  const works = Array.from({ length: count }, (_, i) => work(i + 1));
  return {
    source: 'https://archiveofourown.org/users/Someone/bookmarks',
    retrieved: '01/01/2026, 12:00:00',
    count,
    works,
  };
}

function collection(name: string): Collection {
  return {
    name,
    link: `https://archiveofourown.org/collections/${name}`,
    title: `The ${name} Collection`,
    description: '',
    maintainers: [],
    tags: [],
    active_since: '',
    created: '',
    flags: [],
    challenge_type: 'No Challenge',
    multifandom: null,
    closed: false,
    moderated: false,
    unrevealed: false,
    anonymous: false,
    fandom_count: null,
    work_count: null,
    bookmark_count: null,
    subcollection_count: null,
    parent_collection: null,
    subcollections_link: null,
    subcollections: [],
    work_ids: [],
    bookmark_ids: [],
    external_ids: [],
  };
}

/** a library open and writable, as the page has once a folder is picked and set up */
function openLibrary(label = 'downloads'): void {
  const library = TestBed.inject(Library);
  library.folderName.set(label);
  const nothing = async () => {
    throw new Error('not used here');
  };
  library.store.set({
    label,
    check: async () => {},
    list: nothing,
    read: nothing,
    write: nothing,
    size: nothing,
    delete: nothing,
    rename: nothing,
    mkdir: nothing,
  });
}

async function render(count: number) {
  const library = TestBed.inject(Library);
  library.data.set(exportOf(count));
  // works only ever load out of a folder that was opened, and the runs are hidden
  // until one is - so a rendered library comes with the folder it came from
  openLibrary();

  const fixture = TestBed.createComponent(App);
  await fixture.whenStable();
  return { fixture, element: fixture.nativeElement as HTMLElement, library };
}

function actionLabels(element: HTMLElement): (string | undefined)[] {
  return Array.from(element.querySelectorAll('.actions button')).map((b) => b.textContent?.trim());
}

function tab(element: HTMLElement, name: string): HTMLButtonElement | undefined {
  return Array.from(element.querySelectorAll<HTMLButtonElement>('.views button')).find((b) =>
    b.textContent?.includes(name),
  );
}

async function showCollections(
  fixture: ComponentFixture<App>,
  element: HTMLElement,
): Promise<void> {
  tab(element, 'Collections')!.click();
  await fixture.whenStable();
}

/** the runs only exist once a folder is picked, which these are all about */
async function withFolder() {
  openLibrary();
  const fixture = TestBed.createComponent(App);
  await fixture.whenStable();
  return fixture.nativeElement as HTMLElement;
}

describe('App', () => {
  beforeEach(async () => {
    vi.stubGlobal('scrollTo', vi.fn());
    // the naming note remembers being dismissed, and that would carry between tests
    localStorage.clear();
    await TestBed.configureTestingModule({ imports: [App] }).compileComponents();
    TestBed.inject(Library).data.set(null);
    TestBed.inject(Library).collections.set([]);
    TestBed.inject(Library).copies.update((c) => ({ ...c, html: new Map() }));
    // a Chromium browser on a computer, unless a test says otherwise - jsdom has no folder picker
    DeviceSupport.assume = { writesFolders: true, mobile: false };
  });

  // the assumption is the class's, so it would carry into every spec file after this one
  afterEach(() => {
    DeviceSupport.assume = null;
  });

  // region a phone, or a browser that cannot write to a folder

  /** a library opened as a list of files, as those browsers open one: read-only, no store */
  async function readOnlyLibrary(mobile: boolean) {
    const device = TestBed.inject(DeviceSupport);
    device.writesFolders.set(false);
    device.mobile.set(mobile);
    const library = TestBed.inject(Library);
    library.openedName.set('downloads');
    library.data.set(exportOf(2));
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    return { fixture, element: fixture.nativeElement as HTMLElement };
  }

  it('holds every run button in a browser that cannot write to a folder, saying why, and explains on a click', async () => {
    const { fixture, element } = await readOnlyLibrary(false);
    const buttons = Array.from(element.querySelectorAll<HTMLButtonElement>('.actions button'));

    expect(buttons.length).toBeGreaterThanOrEqual(5);
    for (const button of buttons) {
      expect(button.classList).toContain('unavailable');
      expect(button.getAttribute('aria-disabled')).toBe('true');
      expect(button.title).toBe('Only available in a Chromium browser');
    }
    buttons[0].click();
    await fixture.whenStable();
    expect(element.querySelector('.device-modal')?.textContent).toContain('only available in a Chromium browser');
    // nothing was opened
    expect(element.querySelector('app-download-dialog')).toBeNull();
  });

  it('says mobile on a phone, whatever its browser', async () => {
    const { fixture, element } = await readOnlyLibrary(true);
    const quick = element.querySelector<HTMLButtonElement>('.actions button')!;

    expect(quick.title).toBe('Unavailable on mobile');
    quick.click();
    await fixture.whenStable();
    expect(element.querySelector('.device-modal')?.textContent).toContain('not available on mobile');
  });

  it("leaves a phone on the hosted copy free to run, unwarned - only the downloaded app holds it", async () => {
    const { element } = await readOnlyLibrary(true);
    expect(TestBed.inject(DeviceSupport).blocked()).toBe(true);

    TestBed.inject(HelperConnection).settings.update((c) => ({ ...c, helperUrl: 'https://ao3-helper.example.com' }));
    await Promise.resolve();
    expect(TestBed.inject(DeviceSupport).blocked()).toBe(false);
    TestBed.inject(DeviceSupport).mobile.set(false);
    // a computer's browser without the folder picker is still held, hosted or not
    expect(TestBed.inject(DeviceSupport).blocked()).toBe(true);
    expect(element).toBeTruthy();
  });

  it('holds nothing for Dropbox, or for a guest, on the same browser', async () => {
    TestBed.inject(DeviceSupport).writesFolders.set(false);
    TestBed.inject(StorageChoice).chosen.set('dropbox');
    expect(TestBed.inject(DeviceSupport).blocked()).toBe(false);

    TestBed.inject(StorageChoice).chosen.set('local');
    TestBed.inject(Library).data.set(exportOf(1));
    expect(TestBed.inject(DeviceSupport).blocked()).toBe(true);
    TestBed.inject(HelperConnection).guest.set(true);
    expect(TestBed.inject(DeviceSupport).blocked()).toBe(false);
  });

  // endregion

  it('leads with the everyday run and then the thorough one', async () => {
    // the order is the recommendation: a full scan is hours, and is not what most runs
    // should be
    const element = await withFolder();

    expect(actionLabels(element).slice(0, 2)).toEqual([
      'Quick Scan',
      '(Full scan) Reindex & Update All',
    ]);
  });

  it('offers the single-purpose runs beside the two scans, and no Advanced options without debug tools', async () => {
    const element = await withFolder();

    expect(actionLabels(element).slice(0, 5)).toEqual([
      'Quick Scan',
      '(Full scan) Reindex & Update All',
      'Download/update a specific fic',
      'Download/update several fics',
      'Custom run',
    ]);
    // nothing anyone can use would be in it, so it is not there at all
    expect(element.querySelector('.advanced')).toBeNull();
  });

  // they are the passes the two runs above are built from, kept for working on the app
  // rather than for using it
  it('hides the single-pass runs unless settings.ini turns the debug tools on', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    const labels = actionLabels(element).join(' ');
    expect(labels).not.toContain('update incomplete fics');
    expect(labels).not.toContain('marked as incomplete');
    expect(labels).not.toContain('newly added bookmarks');
  });

  it('offers the single-pass runs in red, marked as debug, when they are turned on', async () => {
    TestBed.inject(Jobs).config.set({
      username: '',
      filetypes: ['JSON', 'HTML'],
      forced: ['JSON'],
      defaults: ['JSON', 'HTML'],
      settings: {
        file: 'C:\\app\\config\\settings.ini',
        extraWaitTime: 15,
        fileNamePattern: '{worknum} {title} - {author} {date updated}',
        fileNameLength: 50,
        fileNameExample: '1234567 A Fic - Someone 2026-01-01.html',
        maxRetries: 0,
        maxTimeouts: 3,
        debugLogging: false,
      },
    });
    // debug mode is the one switch for the debug runs now - settings.ini's EnableDebugTools is gone
    TestBed.inject(DebugMode).set(true);

    const element = await withFolder();

    const debug = Array.from(element.querySelectorAll('.actions button.debug')).map((b) =>
      b.textContent?.trim(),
    );
    expect(debug).toEqual([
      '[DEBUG] Download new bookmarks and update incomplete fics',
      '[DEBUG] Just update any bookmarks marked as incomplete',
      '[DEBUG] Just download newly added bookmarks',
    ]);
    // the debug runs, and only they, are behind Advanced options
    const advanced = element.querySelector('.advanced');
    expect(advanced?.querySelector('summary')?.textContent?.trim()).toBe('Advanced options');
    expect(Array.from(advanced!.querySelectorAll('button')).every((b) => b.classList.contains('debug'))).toBe(true);
  });

  // writing into a folder you chose needs an API only Chromium has, and the moment it bites
  // is after a folder is picked and a run started - far too late to be told
  // region a run already in progress

  const going = {
    id: 'job-7', action: 'quick' as const, actionName: 'Quick Scan', background: true,
    started: '2026-09-28T10:00:00', paused: false, step: '',
  };

  it('will not let the library be changed while a run is going, and says why on hover', async () => {
    TestBed.inject(Jobs).activeRuns.set([going]);
    const element = await withFolder();

    // jsdom has no folder picker, so this is the file-input button (and no Forget)
    const refresh = element.querySelector<HTMLButtonElement>('.refresh-icon');
    if (refresh) {
      expect(refresh.disabled).toBe(true);
      expect(refresh.getAttribute('title')).toBe('Cannot be changed while an active run is in progress');
    }
    const locked = ['This computer', 'Dropbox', 'Choose downloads folder'].map((text) =>
      Array.from(element.querySelectorAll<HTMLButtonElement>('.topbar button')).find(
        (b) => b.textContent?.trim() === text,
      ),
    );
    for (const button of locked) {
      expect(button?.disabled).toBe(true);
      expect(button?.getAttribute('title')).toBe('Cannot be changed while an active run is in progress');
    }
  });

  it('shows times above the listing in the reader\'s own time zone, and an unreadable one as written', () => {
    const iso = '2026-09-10T12:34:56+00:00';
    expect(shownTime(iso)).toBe(new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }));
    expect(shownTime('sometime last week')).toBe('sometime last week');
  });

  it('holds the refresh icon and spins it while the list is read again', async () => {
    const library = TestBed.inject(Library);
    library.listedAt.set(new Date('2026-11-05T12:00:00Z'));
    const { fixture, element } = await render(1);
    library.refreshing.set(true);
    fixture.detectChanges();
    await fixture.whenStable();
    const icon = element.querySelector<HTMLButtonElement>('.refresh-icon')!;
    expect(icon.disabled).toBe(true);
    expect(icon.classList).toContain('spinning');
    library.refreshing.set(false);
  });

  it('offers Refresh as an icon beside List refreshed, not in the header, which reads it again', async () => {
    const library = TestBed.inject(Library);
    library.listedAt.set(new Date('2026-11-05T12:00:00Z'));
    const { element } = await render(1);
    const refresh = vi.spyOn(library, 'refresh').mockResolvedValue();

    expect([...element.querySelectorAll('.topbar button')].some((b) => b.textContent?.includes('Refresh'))).toBe(false);
    const button = element.querySelector<HTMLButtonElement>('.meta-line.note .refresh-icon')!;
    expect(button.textContent?.trim()).toBe('');
    expect(button.disabled).toBe(false);
    button.click();

    // pressed on purpose, it reads the whole library again, past this browser's copy of it
    expect(refresh).toHaveBeenCalledWith({ fresh: true });
  });

  it('names Dropbox on the Works and Collections Refresh while the library is there', async () => {
    const library = TestBed.inject(Library);
    library.listedAt.set(new Date('2026-11-05T12:00:00Z'));
    const { fixture, element } = await render(1);
    const button = element.querySelector<HTMLButtonElement>('.meta-line.note .refresh-icon')!;
    expect(button.getAttribute('aria-label')).toBe('Refresh the list');
    // the library in Dropbox: what the button is given then (this stand-in has no Dropbox
    // sign-in, so the page shows its sign-in panel rather than the listing)
    TestBed.inject(StorageChoice).chosen.set('dropbox');
    const words = (fixture.componentInstance as unknown as { refreshWords: () => Record<string, string> }).refreshWords();
    expect(words['label']).toBe('Refresh from Dropbox');
    expect(words['title']).toContain("download the library's index again");
    expect(words['busy']).toBe('Refreshing from Dropbox...');
  });

  it('says at the top when a run is already in progress, and that a new one must wait', async () => {
    TestBed.inject(Jobs).activeRuns.set([going]);
    const element = await withFolder();

    const banner = element.querySelector('.run-in-progress')?.textContent ?? '';
    expect(banner).toContain('A run is already in progress');
    expect(banner).toContain('Quick Scan, running in the background');
    expect(banner).toContain('You must wait until it is complete to start a new one');
  });

  it('says a paused run is paused', async () => {
    TestBed.inject(Jobs).activeRuns.set([{ ...going, paused: true }]);
    const element = await withFolder();

    expect(element.querySelector('.run-in-progress')?.textContent).toContain('Quick Scan, paused');
  });

  it('says when a paused background run will be abandoned', async () => {
    TestBed.inject(Jobs).activeRuns.set([
      { ...going, paused: true, abandonsAt: '2026-09-28T13:10:00' },
    ]);
    const element = await withFolder();

    const expected = new Date('2026-09-28T13:10:00')
      .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    expect(element.querySelector('.run-in-progress')?.textContent).toContain(
      `It will be abandoned at ${expected} unless resumed`);
  });

  it('holds every run button while one is going', async () => {
    TestBed.inject(Jobs).activeRuns.set([going]);
    const element = await withFolder();

    const buttons = Array.from(element.querySelectorAll<HTMLButtonElement>('.actions button'));
    expect(buttons.length).toBeGreaterThan(0);
    expect(buttons.every((b) => b.disabled)).toBe(true);
  });

  it('takes you to the run from the banner', async () => {
    TestBed.inject(Jobs).activeRuns.set([going]);
    const fixture = TestBed.createComponent(App);
    openLibrary();
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.trim() === 'Go to this run')!.click();
    await fixture.whenStable();

    expect(tab(element, 'History')?.getAttribute('aria-current')).toBe('page');
  });

  it('says nothing and holds nothing when no run is going', async () => {
    const element = await withFolder();

    expect(element.querySelector('.run-in-progress')).toBeNull();
    const buttons = Array.from(element.querySelectorAll<HTMLButtonElement>('.actions button'));
    expect(buttons.some((b) => !b.disabled)).toBe(true);
  });

  // endregion

  it('opens with no passcode window on a copy that needs none', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    expect((fixture.nativeElement as HTMLElement).querySelector('app-passcode-gate')).toBeNull();
  });

  it('puts the passcode window over the page when the helper wants one', async () => {
    TestBed.inject(HelperConnection).passcodeWanted.set(true);
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const gate = (fixture.nativeElement as HTMLElement).querySelector('app-passcode-gate');
    expect(gate?.textContent).toContain('passcode protected');
  });

  it('shows a bar while a Dropbox library is read, with a number only once there is one', async () => {
    TestBed.inject(StorageChoice).chosen.set('dropbox');
    const library = TestBed.inject(Library);
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    // a read under way: set once the page has opened, since opening a library starts afresh
    library.loading.set(true);
    library.readProgress.set({ stage: 'listing', found: 0 });
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    const bar = () => element.querySelector('.read-progress [role="progressbar"]');
    expect(bar()?.hasAttribute('aria-valuenow')).toBe(false);
    expect(element.querySelector('.read-progress .fill')?.classList).toContain('indeterminate');
    expect(element.querySelector('.read-progress')?.textContent).toContain('Listing your library in Dropbox');

    library.readProgress.set({ stage: 'reading', done: 50, total: 200 });
    await fixture.whenStable();
    expect(bar()?.getAttribute('aria-valuenow')).toBe('25');
    expect(element.querySelector('.read-progress')?.textContent).toContain('50 of 200 entries');
  });

  it('says once what each way of keeping a library needs, and that this browser has it', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const notice = (fixture.nativeElement as HTMLElement).querySelector('app-browser-notice')?.textContent ?? '';

    expect(notice).toContain('Planning to use Dropbox? You can use this tool on any browser.');
    expect(notice).toContain('Reading & saving works to a folder on a device:');
    expect(notice).toContain('Computer-only (no mobile functionality for now)');
    expect(notice).toContain('Requires a Chromium browser. This includes Chrome, Edge, Opera or Arc.');
    expect(notice).toContain('This is a Chromium browser, so you are good to go with either option');
    expect(notice).toContain('We recommend leaving it open overnight the first time you run a full scan');
  });

  it('warns a browser that cannot write to a folder, and words it for a phone on a phone', async () => {
    DeviceSupport.assume = { writesFolders: false, mobile: false };
    const desktop = TestBed.createComponent(App);
    await desktop.whenStable();
    const said = (desktop.nativeElement as HTMLElement).querySelector('app-browser-notice')?.textContent ?? '';
    expect(said).toContain('This browser cannot perform scans or save downloads to your device. Switch to a Chromium browser');
    expect(said).toContain('You can still read an imported library.');

    TestBed.inject(DeviceSupport).mobile.set(true);
    await desktop.whenStable();
    const phone = (desktop.nativeElement as HTMLElement).querySelector('app-browser-notice')?.textContent ?? '';
    expect(phone).toContain('This device cannot perform scans');
    expect(phone).toContain('This device cannot perform scans or save downloads. Use a computer with a Chromium browser.');
    // one warning, never both: on a phone the browser does not matter
    expect(phone).not.toContain('This browser cannot');
    expect(phone).not.toContain('This is a Chromium browser');
  });

  it("gives a phone running Chrome the phone's warning alone, as no phone can save to a folder", async () => {
    DeviceSupport.assume = null;
    vi.stubGlobal('showDirectoryPicker', () => undefined);
    vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(
      'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36',
    );
    const app = TestBed.createComponent(App);
    await app.whenStable();
    const said = (app.nativeElement as HTMLElement).querySelector('app-browser-notice')?.textContent ?? '';
    expect(said).toContain('This device cannot perform scans');
    expect(said).not.toContain('This browser cannot');
    expect(said).not.toContain('This is a Chromium browser');
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('says how background runs work in the FAQ on the hosted copy alone', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();
    const local = element.querySelector('app-faq')?.textContent ?? '';
    expect(local).not.toContain('Run as background task');
    expect(local).not.toContain('Continue in background');
    expect(local).not.toContain('Backgrounded Runs (Dropbox-only)');
    expect(local).toContain('Only one run can be performed at a time');

    TestBed.inject(HelperConnection).settings.update((c) => ({
      ...c, helperUrl: 'https://ao3-helper.example.com',
    }));
    const again = TestBed.createComponent(App);
    await again.whenStable();
    const againElement = again.nativeElement as HTMLElement;
    tab(againElement, 'FAQ')!.click();
    await again.whenStable();
    expect(againElement.querySelector('app-faq')?.textContent).toContain('Run as background task');
  });

  it('does not say it again once it has been dismissed', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    const dismiss = Array.from(
      element.querySelectorAll<HTMLButtonElement>('app-browser-notice button'),
    ).find((b) => b.textContent?.includes('Got it'));
    dismiss!.click();
    await fixture.whenStable();
    expect(element.querySelector('app-browser-notice')).toBeNull();

    // a second visit, with whatever the first one remembered
    const again = TestBed.createComponent(App);
    await again.whenStable();
    expect(
      (again.nativeElement as HTMLElement).querySelector('app-browser-notice'),
    ).toBeNull();
  });

  // every run reads the folder to see what is already there and writes back into it, so
  // there is nothing sensible to offer before one is picked - and the panel below already
  // asks for one, so an empty button bar above it would only repeat the question
  it('offers no run at all before a downloads folder is chosen', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.actions')).toBeNull();
    expect(actionLabels(element)).toEqual([]);
  });

  it('shows the runs once a folder has been chosen and opened', async () => {
    const library = TestBed.inject(Library);
    library.data.set(exportOf(1));
    openLibrary();

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.actions')).toBeTruthy();
    expect(actionLabels(element)).toContain('Quick Scan');
  });

  it('opens a run window at once, asking the helper and the history in the background', async () => {
    const library = TestBed.inject(Library);
    library.data.set(exportOf(1));
    openLibrary();
    const jobs = TestBed.inject(Jobs);
    const settle = vi.spyOn(jobs, 'settleInterrupted').mockImplementation(() => new Promise(() => undefined));
    const config = vi.spyOn(jobs, 'loadConfig').mockImplementation(() => new Promise(() => undefined));
    const newest = vi.spyOn(jobs, 'loadNewestFloor').mockImplementation(() => new Promise(() => undefined));
    const floors = vi.spyOn(jobs, 'loadFloorRuns');

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;
    const before = { settle: settle.mock.calls.length, config: config.mock.calls.length };
    Array.from(element.querySelectorAll<HTMLButtonElement>('.actions button'))
      .find((b) => b.textContent?.includes('Quick Scan'))!.click();
    fixture.detectChanges();

    // none of them answered, and the window is open anyway
    expect(element.querySelector('app-download-dialog')).toBeTruthy();
    expect(settle.mock.calls.length).toBe(before.settle + 1);
    expect(config.mock.calls.length).toBe(before.config + 1);
    expect(newest).toHaveBeenCalledTimes(1);
    expect(floors).not.toHaveBeenCalled();
  });

  it('checks for interrupted runs whenever a library is read', async () => {
    const jobs = TestBed.inject(Jobs);
    const settle = vi.spyOn(jobs, 'settleInterrupted').mockResolvedValue(0);
    const library = TestBed.inject(Library);
    TestBed.createComponent(App);
    TestBed.tick();
    const store = { label: 'x' } as never;
    library.lastRead.set({ store, at: Date.now() });
    TestBed.tick();
    expect(settle).toHaveBeenCalledWith(store);
  });

  it('offers no run for a folder that is only remembered, waiting on a reconnect', async () => {
    // a run writes through the page, and the page cannot write there until access is confirmed
    const library = TestBed.inject(Library);
    library.folderName.set('downloads');
    library.needsReconnect.set(true);

    const element = await (async () => {
      const fixture = TestBed.createComponent(App);
      await fixture.whenStable();
      return fixture.nativeElement as HTMLElement;
    })();

    expect(actionLabels(element)).toEqual([]);
  });

  it('hides the collections runs the same way', async () => {
    // no folder: the collections tab is reachable, but there is nothing to start
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    await showCollections(fixture, element);

    expect(element.querySelector('.actions')).toBeNull();
  });

  it('offers only the collections jobs on the collections page', async () => {
    // each page carries the buttons that fill it, so neither offers the other's job
    const { fixture, element } = await render(1);
    await showCollections(fixture, element);

    expect(actionLabels(element)).toEqual([
      'Index my collections',
      'Index collection by URL',
    ]);
  });

  it('puts the collections jobs under the collections heading, in one row with New collection', async () => {
    const { fixture, element } = await render(1);
    await showCollections(fixture, element);

    const view = element.querySelector('app-collections-view')!;
    const heading = view.querySelector('.listing-heading')!;
    const row = view.querySelector('.listing-actions')!;
    expect(heading.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const labels = Array.from(row.querySelectorAll('button')).map((b) => b.textContent?.trim());
    expect(labels.slice(0, 2)).toEqual(['Index my collections', 'Index collection by URL']);
  });

  it('switches between the two listings', async () => {
    const { fixture, element } = await render(3);
    expect(element.querySelectorAll('.blurb').length).toBe(3);

    await showCollections(fixture, element);
    expect(element.querySelector('app-collections-view')).toBeTruthy();
    expect(element.querySelectorAll('.blurb').length).toBe(0);

    tab(element, 'Works')!.click();
    await fixture.whenStable();
    expect(element.querySelector('app-collections-view')).toBeNull();
    expect(element.querySelectorAll('.blurb').length).toBe(3);
  });

  it('says above the listing when it was refreshed, and not when the index was last written', async () => {
    const library = TestBed.inject(Library);
    library.data.set(exportOf(3));
    library.listedAt.set(new Date('2026-11-03T10:00:00Z'));

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';

    expect(text).toContain('List refreshed');
    expect(text).not.toContain('Last indexed');
  });

  it('puts the run buttons under the listing heading and List refreshed, not above the listing', async () => {
    const { fixture, element } = await render(1);
    TestBed.inject(Library).listedAt.set(new Date('2026-11-03T10:00:00Z'));
    fixture.detectChanges();
    await fixture.whenStable();

    const list = element.querySelector('app-work-list')!;
    const heading = list.querySelector('.listing-heading')!;
    const note = list.querySelector('.meta-line.note')!;
    const quick = [...list.querySelectorAll('.actions button')].find((b) => b.textContent?.includes('Quick Scan'));
    expect(quick).toBeTruthy();
    expect(heading.compareDocumentPosition(quick!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(note.compareDocumentPosition(quick!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // and only once on the page
    expect([...element.querySelectorAll('.actions button')].filter((b) => b.textContent?.includes('Quick Scan')).length).toBe(1);
  });

  it('counts what each page holds on its tab', async () => {
    const library = TestBed.inject(Library);
    library.data.set(exportOf(3));
    library.collections.set([collection('a'), collection('b')]);

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(tab(element, 'Works')?.textContent).toContain('3');
    expect(tab(element, 'Collections')?.textContent).toContain('2');
  });

  it('opens a folder whose collections are synced but whose bookmarks are not', async () => {
    // collections can be indexed first, and that folder is not an empty one
    const library = TestBed.inject(Library);
    library.collections.set([collection('a')]);
    // collections only ever load out of a folder that was opened, so this state comes with
    // one - and without it the buttons are gated and the gate's own notice is what shows
    library.folderName.set('downloads');
    // read successfully - so 'no bookmarks' is known, not a guess
    vi.spyOn(library, 'showLocal').mockResolvedValue();
    const store = {} as never;
    library.store.set(store);
    library.lastRead.set({ store, at: Date.now() });

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.empty')).toBeNull();
    expect(element.querySelector('.notice')?.textContent).toContain('No bookmarks indexed');

    await showCollections(fixture, element);
    expect(element.querySelectorAll('.collection').length).toBe(1);
  });

  it('asks for a folder before anything is loaded', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.empty')).toBeTruthy();
    expect(element.querySelectorAll('.blurb').length).toBe(0);
  });

  it('shows 20 works on a page', async () => {
    const { element } = await render(25);

    expect(element.querySelectorAll('.blurb').length).toBe(20);
  });

  it('reports the range of everything listed, and under it the bookmarks and whose they are', async () => {
    const { fixture, element, library } = await render(25);
    // three of the 25 say they are bookmarks; the rest came in some other way
    library.data.update((d) => d && {
      ...d,
      works: d.works.map((w, i) => (i < 3 ? { ...w, bookmarked: true } : w)),
    });
    fixture.detectChanges();
    await fixture.whenStable();

    const heading = element.querySelector('.listing-heading')?.textContent ?? '';
    expect(heading).toContain('1 - 20 of 25 Works');
    expect(heading).not.toContain('Someone');
    const line = element.querySelector('.bookmark-count')?.textContent?.replace(/\s+/g, ' ').trim();
    expect(line).toBe('3 Bookmarks by Someone');
  });

  it('says nothing about bookmarks under the heading when none are', async () => {
    const { element } = await render(25);
    expect(element.querySelector('.listing-heading')?.textContent).toContain('1 - 20 of 25 Works');
    expect(element.querySelector('.bookmark-count')).toBeNull();
  });

  it('names nobody beside the bookmarks when no scan of anyone\'s bookmarks is known', async () => {
    const { fixture, element, library } = await render(5);
    library.data.update((d) => d && { ...d, source: '', works: d.works.map((w) => ({ ...w, bookmarked: true })) });
    fixture.detectChanges();
    await fixture.whenStable();
    expect(element.querySelector('.bookmark-count')?.textContent?.replace(/\s+/g, ' ').trim()).toBe('5 Bookmarks');
  });

  it('says Works, with nobody named, when no entry came off anyone\'s bookmarks', async () => {
    const { fixture, element, library } = await render(25);
    library.data.update((d) => d && { ...d, source: '' });
    fixture.detectChanges();
    await fixture.whenStable();

    const heading = element.querySelector('.listing-heading')?.textContent ?? '';
    expect(heading).toContain('1 - 20 of 25 Works');
    expect(heading).not.toContain(' by ');
  });

  it('shows the remainder on the last page', async () => {
    const { fixture, element } = await render(25);

    const pages = Array.from(element.querySelectorAll<HTMLButtonElement>('.pagination .page'));
    pages.find((button) => button.textContent?.trim() === '2')?.click();
    await fixture.whenStable();

    expect(element.querySelectorAll('.blurb').length).toBe(5);
    expect(element.querySelector('.listing-heading')?.textContent).toContain('21 - 25 of 25');
  });

  it('does not paginate when everything fits on one page', async () => {
    const { element } = await render(20);

    expect(element.querySelectorAll('.blurb').length).toBe(20);
    expect(element.querySelector('.pagination')).toBeNull();
  });

  it('renders the summary as separate paragraphs', async () => {
    const { element } = await render(1);

    expect(element.querySelectorAll('.blurb .summary p').length).toBe(2);
  });

  it('marks titles without a downloaded copy so they are not mistaken for local files', async () => {
    const { element } = await render(1);

    const title = element.querySelector('.heading a.title');
    expect(title?.classList.contains('local')).toBe(false);
    // and the listing no longer counts downloaded copies in a sentence of its own
    expect(element.querySelector('.meta-line.linked')).toBeNull();
  });

  it('links a title to its downloaded copy when the folder has one', async () => {
    const library = TestBed.inject(Library);
    library.data.set(exportOf(1));
    library.copies.update((c) => ({ ...c, html: new Map([['1', new File(['<html></html>'], '1 Work 1 - Writer.html')]]) }));

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.heading a.title')?.classList.contains('local')).toBe(true);
  });

  // region the history tab

  it('offers a history tab', async () => {
    const { element } = await render(1);

    expect(tab(element, 'History')).toBeTruthy();
  });

  it('shows past runs with no buttons to act on a folder', async () => {
    const { fixture, element } = await render(1);

    tab(element, 'History')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-history')).toBeTruthy();
    expect(element.querySelector('.actions')).toBeNull();
    expect(element.querySelector('app-work-list')).toBeNull();
  });

  it('reads the history without a folder having been chosen', async () => {
    // it describes runs, not the library, so it does not need one
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    tab(element, 'History')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-history')).toBeTruthy();
    expect(element.querySelector('.empty')).toBeNull();
  });

  // endregion

  // region the faq tab

  it('offers a faq alongside the two listings', async () => {
    const { element } = await render(1);

    expect(tab(element, 'FAQ')).toBeTruthy();
  });

  it('shows the faq with no buttons to act on a folder', async () => {
    // it is something to read, not a folder to do anything with
    const { fixture, element } = await render(1);

    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-faq')).toBeTruthy();
    expect(element.querySelector('.actions')).toBeNull();
    expect(element.querySelector('app-work-list')).toBeNull();
  });

  it('reads the faq without a folder having been chosen', async () => {
    // the likeliest moment to want it is when a download did not come out as expected,
    // which is also a moment nothing may be loaded
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-faq')).toBeTruthy();
    // and the 'choose a folder' panel steps out of the way
    expect(element.querySelector('.empty')).toBeNull();
  });

  it('answers the things that catch people out', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    const said = element.querySelector('app-faq')?.textContent ?? '';
    expect(said).toContain('No work skins');
    expect(said).toContain('Embedded audio and video');
    expect(said).toContain('Very large images');
    expect(said).toContain('offer to rename the files');
    expect(said).toContain('last updated on AO3');
    // unbookmarking or deleting a fic on AO3 removes nothing here, which surprises people
    expect(said).toContain('Any bookmarks that were un-bookmarked on AO3 will still remain in your FicFairy library');
    expect(said).toContain('hide/unhide');
  });

  it('explains what happens when a work cannot be downloaded', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    const said = element.querySelector('app-faq')?.textContent ?? '';
    expect(said).toContain('attempts to retrieve works from FicHub');
    expect(said).toContain('the run will warn you');
  });

  it('says how to give files missing dates one', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    const said = (element.querySelector('app-faq')?.textContent ?? '').replace(/\s+/g, ' ');
    expect(said).toContain('If any of your files are missing dates, refresh your library');
  });

  it('says why a login is needed at all', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    const said = element.querySelector('app-faq')?.textContent ?? '';
    expect(said).toContain("You don't need to 😊 Logging in is optional.");
    expect(said).toContain('Your private bookmarks');
    expect(said).toContain('Works restricted to registered users');
    expect(said).toContain('never stored by this page');
    const link = Array.from(element.querySelectorAll<HTMLAnchorElement>('app-faq a')).find((a) => a.textContent?.trim() === "Click here to read AO3's page on how they handle this.");
    expect(link?.getAttribute('href')).toBe('https://archiveofourown.org/faq/downloading-fanworks');
  });

  it('shows the logo beside the name, from the page itself, without reading it out twice', async () => {
    const { element } = await render(1);

    const heading = element.querySelector('.topbar h1');
    const logo = heading?.querySelector('img.logo');
    expect(logo?.getAttribute('src')).toBe('ficfairy-logo.png');
    expect(logo?.getAttribute('alt')).toBe('');
    expect(heading?.textContent?.trim()).toBe('Fic Fairy');
  });

  it('pins where to download the app to the top of the FAQ', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    const first = element.querySelector('app-faq .faq')?.firstElementChild;
    expect(first?.classList.contains('download-app')).toBe(true);
    expect(first?.querySelector('a')?.getAttribute('href')).toBe(
      'https://github.com/alexandria-p/ficfairy/releases/latest',
    );
    expect(first?.textContent).toContain('ficfairy.exe');
    expect(first?.textContent).toContain('ficfairy-ao3downloader-macos-apple-silicon.zip');
    expect(first?.textContent).toContain('ficfairy-ao3downloader-macos-intel.zip');
    expect(first?.textContent).toContain('Start FicFairy.command');
    expect(first?.textContent).toContain('ficfairy-ao3downloader-linux-x86_64.zip');
    expect(first?.textContent).toContain('Start FicFairy.sh');
  });

  it('on the hosted copy, says where to get the app in the footer instead of the FAQ', async () => {
    const { element: local } = await render(1);
    expect(local.querySelector('.app-footer .run-locally')).toBeNull();

    TestBed.inject(HelperConnection).settings.update((c) => ({
      ...c, helperUrl: 'https://ao3-helper.example.com',
    }));
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;
    const panel = element.querySelector('.app-footer .run-locally');
    expect(panel?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'Run this on your own computer - download the latest version from GitHub',
    );
    expect(panel?.querySelector('a')?.getAttribute('href')).toBe('https://github.com/alexandria-p/ficfairy/releases/latest');
    expect(element.querySelector('.app-footer')?.lastElementChild).toBe(panel);

    tab(element, 'FAQ')!.click();
    await fixture.whenStable();
    expect(element.querySelector('app-faq .download-app')).toBeNull();
  });

  it('holds the run buttons while the library is still being checked for issues', async () => {
    const { fixture, element } = await render(1);
    const quick = () => [...element.querySelectorAll('button')].find((b) => b.textContent?.includes('Quick Scan'))!;
    expect(quick().disabled).toBe(false);

    TestBed.inject(LibraryImports).checking.set(true);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(quick().disabled).toBe(true);
    expect(quick().getAttribute('title')).toBe('Wait until your library has finished loading');

    TestBed.inject(LibraryImports).checking.set(false);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(quick().disabled).toBe(false);
  });

  it('holds the run buttons while a cached copy of the library is shown and Dropbox is checked', async () => {
    const { fixture, element } = await render(1);
    const quick = () => [...element.querySelectorAll('button')].find((b) => b.textContent?.includes('Quick Scan'))!;
    expect(quick().disabled).toBe(false);

    TestBed.inject(Library).fromCache.set(Date.now());
    fixture.detectChanges();
    await fixture.whenStable();
    expect(quick().disabled).toBe(true);
    expect(quick().getAttribute('title')).toBe('Wait until your library has finished loading');

    // checked: the Resolve issues check runs then, and the buttons come back once it is done
    TestBed.inject(Library).fromCache.set(null);
    await vi.waitFor(async () => {
      fixture.detectChanges();
      await fixture.whenStable();
      expect(quick().disabled).toBe(false);
    });
  });

  it('says what setting the library up is doing in the loading bar, not over the page', async () => {
    const { fixture, element } = await render(1);
    const setup = TestBed.inject(LibrarySetup);
    setup.state.set('working');
    setup.caption.set('Creating folder `Dropbox/Apps/FicFairy/runs`');
    fixture.detectChanges();
    await fixture.whenStable();
    expect(element.querySelector('app-progress-bar')?.textContent).toContain('Creating folder Dropbox/Apps/FicFairy/runs');
    expect(element.querySelector('app-progress-bar code')?.textContent).toBe('Dropbox/Apps/FicFairy/runs');
    expect(element.querySelector('app-setup-overlay .cover')).toBeNull();
    setup.state.set('idle');
  });

  it('shows both listings\' headings while the library is first read, with nothing counted yet', async () => {
    const library = TestBed.inject(Library);
    vi.spyOn(library, 'showLocal').mockResolvedValue();
    const fixture = TestBed.createComponent(App);
    const element = fixture.nativeElement as HTMLElement;
    library.loading.set(true);
    fixture.detectChanges();
    await fixture.whenStable();

    expect(element.querySelector('app-work-list .listing-heading')?.textContent?.trim()).toBe('Works');
    expect(element.querySelector('app-work-list .meta-line.note')?.textContent).toContain('List not yet loaded');
    expect(element.querySelector('app-work-list .refresh-icon')).toBeNull();
    expect(element.querySelector<HTMLElement>('app-work-list details.filters')?.hidden).toBe(true);
    expect(element.querySelector('app-work-list .index .notice')).toBeNull();

    tab(element, 'Collections')!.click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(element.querySelector('app-collections-view .listing-heading')?.textContent?.trim()).toBe('Collections');
    expect(element.querySelector('app-collections-view .meta-line.note')?.textContent).toContain('List not yet loaded');
    expect(element.querySelector('app-collections-view .refresh-icon')).toBeNull();
    expect(element.querySelector('app-collections-view .collections .notice')).toBeNull();
    library.loading.set(false);
  });

  it('holds Try again on a failed read for 3, 2, 1, then reads again only when pressed', async () => {
    vi.useFakeTimers();
    try {
      const library = TestBed.inject(Library);
      vi.spyOn(library, 'showLocal').mockResolvedValue();
      const retry = vi.spyOn(library, 'retryRead').mockResolvedValue();
      const fixture = TestBed.createComponent(App);
      const element = fixture.nativeElement as HTMLElement;
      library.error.set('Could not read /Apps/FicFairy from Dropbox. Dropbox asked us to slow down.');
      library.readFailure.set({ waitSeconds: 3, slowDown: true });
      fixture.detectChanges();
      const button = () => element.querySelector<HTMLButtonElement>('.read-error .try-again')!;
      expect(element.querySelector('.read-error .slow-down')?.textContent).toContain('asking for a breather');
      expect(button().disabled).toBe(true);
      expect(button().textContent?.trim()).toBe('3...');

      vi.advanceTimersByTime(1000);
      fixture.detectChanges();
      expect(button().textContent?.trim()).toBe('2...');
      vi.advanceTimersByTime(2000);
      fixture.detectChanges();
      expect(button().disabled).toBe(false);
      expect(button().textContent?.trim()).toBe('Try again');
      // never by itself
      expect(retry).not.toHaveBeenCalled();

      button().click();
      expect(retry).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('lists no collections with no library open - the panel above says how to open one', async () => {
    const library = TestBed.inject(Library);
    vi.spyOn(library, 'showLocal').mockResolvedValue();
    library.store.set(null);
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;
    tab(element, 'Collections')!.click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(element.querySelector('app-collections-view')).toBeNull();
  });

  it('highlights the storage chosen, and only that one', async () => {
    const { element } = await render(1);
    const buttons = [...element.querySelectorAll('.storage button')];
    const circled = buttons.filter((b) => b.querySelector('svg.highlight'));
    expect(circled.length).toBe(1);
    expect(circled[0].classList.contains('current')).toBe(true);
  });

  it('has a Report a bug tab next to the FAQ that points at the GitHub issues', async () => {
    const { fixture, element } = await render(1);
    const tabs = Array.from(element.querySelectorAll('nav.views button')).map((b) => b.textContent?.trim());
    expect(tabs.indexOf('Report a bug')).toBe(tabs.indexOf('FAQ') + 1);

    tab(element, 'Report a bug')!.click();
    await fixture.whenStable();

    const page = element.querySelector('.report-bug');
    expect(page?.querySelector('a')?.getAttribute('href')).toBe(
      'https://github.com/alexandria-p/ficfairy/issues',
    );
    // something to read, not a folder to act on - no run buttons
    expect(element.querySelector('.actions')).toBeNull();
  });

  it('opens the feedback form from a button on the Report a bug page', async () => {
    // no bot-check widget in jsdom
    vi.spyOn(TestBed.inject(Turnstile), 'render').mockResolvedValue('widget');
    vi.spyOn(TestBed.inject(Turnstile), 'remove').mockImplementation(() => {});
    TestBed.inject(HelperConnection).settings.update((c) => ({
      ...c,
      feedbackUrl: 'https://feedback.example.com',
      turnstileSiteKey: 'site-key',
    }));
    const { fixture, element } = await render(1);
    tab(element, 'Report a bug')!.click();
    await fixture.whenStable();
    expect(element.querySelector('app-feedback .modal')).toBeNull();

    element.querySelector<HTMLButtonElement>('.report-bug button.send-feedback')!.click();
    await fixture.whenStable();

    // the same window the Feedback tab opens, not a second form
    expect(element.querySelectorAll('app-feedback .modal [role=dialog]')).toHaveLength(1);
  });

  it('offers no feedback button on the Report a bug page when this copy cannot send it', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'Report a bug')!.click();
    await fixture.whenStable();

    expect(element.querySelector('.report-bug button.send-feedback')).toBeNull();
  });

  it('has a User settings tab after Report a bug, with no run buttons and no folder to choose', async () => {
    const library = TestBed.inject(Library);
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;
    const tabs = Array.from(element.querySelectorAll('nav.views button')).map((b) => b.textContent?.trim());
    expect(tabs.indexOf('User settings')).toBe(tabs.indexOf('Report a bug') + 1);
    expect(library.data()).toBeNull();

    tab(element, 'User settings')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-user-settings')).not.toBeNull();
    expect(element.querySelector('.actions')).toBeNull();
    expect(element.textContent).not.toContain('Choose your downloads folder');
  });

  it('never asks for a folder on the DEBUG tab, where dummy data is turned off with none open', async () => {
    TestBed.inject(DebugMode).set(true);
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;
    expect(TestBed.inject(Library).data()).toBeNull();

    tab(element, 'DEBUG')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-debug-tab')).not.toBeNull();
    expect(element.textContent).not.toContain('Choose your downloads folder');
    TestBed.inject(DebugMode).set(false);
  });

  it('says its version and links the repository on every tab', async () => {
    const { fixture, element } = await render(1);
    TestBed.inject(HelperConnection).settings.update((c) => ({ ...c, version: '1.8.2' }));
    for (const name of ['Works', 'Collections', 'History', 'FAQ']) {
      tab(element, name)!.click();
      fixture.detectChanges();
      await fixture.whenStable();
      const footer = element.querySelector('.app-footer');
      expect(footer?.textContent).toContain('version 1.8.2');
      expect(footer?.querySelector('a')?.getAttribute('href')).toBe(
        'https://github.com/alexandria-p/ficfairy',
      );
    }
  });

  it('says a page built on this computer has no version', async () => {
    const { element } = await render(1);

    expect(element.querySelector('.app-footer')?.textContent).toContain('(built on this computer)');
  });

  it('offers to update only when the helper is the Windows app', async () => {
    const { fixture, element } = await render(1);
    const updates = TestBed.inject(UpdateCheck);
    updates.newer.set({ version: '1.8.3', url: 'https://github.com/x/y/releases/tag/v1.8.3' });
    fixture.detectChanges();
    await fixture.whenStable();

    const buttons = () => Array.from(element.querySelectorAll('.update-available button')).map((b) => b.textContent?.trim());
    // anywhere else, the page can only link the release
    expect(buttons()).not.toContain('Update now');
    expect(element.querySelector('.update-available a')?.textContent).toContain('Download it from GitHub');

    updates.canUpdate.set(true);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(buttons()).toContain('Update now');
  });

  it('says in the footer when this is the latest version', async () => {
    const { fixture, element } = await render(1);
    TestBed.inject(UpdateCheck).checked.set(true);
    fixture.detectChanges();
    await fixture.whenStable();

    const link = element.querySelector('.app-footer .footer-link');
    expect(link?.textContent?.trim()).toBe('up to date with latest');
    expect(link?.getAttribute('href')).toBe('https://github.com/alexandria-p/ficfairy/releases/latest');
  });

  it('says nothing in the footer about being the latest until GitHub has answered', async () => {
    const { element } = await render(1);

    expect(element.querySelector('.app-footer .footer-link')).toBeNull();
  });

  it('still says in the footer that a newer version is out once the banner is dismissed', async () => {
    const { fixture, element } = await render(1);
    const updates = TestBed.inject(UpdateCheck);
    updates.checked.set(true);
    updates.newer.set({ version: '1.8.3', url: 'https://github.com/x/y/releases/tag/v1.8.3' });
    updates.dismiss();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(element.querySelector('.update-available')).toBeNull();
    const link = element.querySelector('.app-footer .footer-link');
    expect(link?.textContent?.trim()).toBe('update to latest (1.8.3)');
    expect(link?.getAttribute('href')).toBe('https://github.com/x/y/releases/tag/v1.8.3');
  });

  it('in the Windows app, updating from the footer starts the update itself', async () => {
    const { fixture, element } = await render(1);
    const updates = TestBed.inject(UpdateCheck);
    updates.checked.set(true);
    updates.canUpdate.set(true);
    updates.newer.set({ version: '1.8.3', url: 'https://github.com/x/y/releases/tag/v1.8.3' });
    const started = vi.spyOn(updates, 'updateNow').mockResolvedValue();
    fixture.detectChanges();
    await fixture.whenStable();

    const link = element.querySelector('.app-footer .footer-link') as HTMLButtonElement;
    expect(link.tagName).toBe('BUTTON');
    link.click();

    expect(started).toHaveBeenCalledOnce();
  });

  it('says what is happening while the app updates itself', async () => {
    const { fixture, element } = await render(1);
    TestBed.inject(UpdateCheck).updating.set({ state: 'updating', version: '1.8.3' });
    fixture.detectChanges();
    await fixture.whenStable();

    expect(element.querySelector('.update-available')?.textContent).toContain('Updating to 1.8.3');
  });

  it('says when an update did not go through', async () => {
    const { fixture, element } = await render(1);
    TestBed.inject(UpdateCheck).updating.set({ state: 'failed', error: 'the file is in use' });
    fixture.detectChanges();
    await fixture.whenStable();

    const banner = element.querySelector('.update-failed');
    expect(banner?.textContent).toContain('the file is in use');
    expect(banner?.textContent).toContain('This copy and your library are as they were');
  });

  it('sends anyone whose update failed to download the latest release by hand, whatever went wrong', async () => {
    // a release whose zip was renamed is the case this is for: the app finds no file under the
    // name it knows, and the only way on is a new copy from the release page
    const { fixture, element } = await render(1);
    TestBed.inject(UpdateCheck).updating.set({
      state: 'failed', error: 'the latest release, 2.0.0, has no ficfairy-ao3downloader-windows.zip',
    });
    fixture.detectChanges();
    await fixture.whenStable();

    const banner = element.querySelector('.update-failed');
    expect(banner?.textContent).toContain('There was a problem updating the app');
    expect(banner?.textContent).toContain('has no ficfairy-ao3downloader-windows.zip');
    expect(banner?.textContent).toContain('download the latest version again');
    expect(banner?.querySelector('a.manual-download')?.getAttribute('href'))
      .toBe('https://github.com/alexandria-p/ficfairy/releases/latest');
  });

  it('says when a newer version is out, and stops for good when told to', async () => {
    const { fixture, element } = await render(1);
    TestBed.inject(UpdateCheck).newer.set({ version: '1.8.3', url: 'https://github.com/x/y/releases/tag/v1.8.3' });
    fixture.detectChanges();
    await fixture.whenStable();

    const banner = element.querySelector('.update-available');
    expect(banner?.textContent).toContain('1.8.3');
    expect(banner?.querySelector('a')?.getAttribute('href')).toBe('https://github.com/x/y/releases/tag/v1.8.3');

    (banner?.querySelector('button') as HTMLButtonElement).click();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(element.querySelector('.update-available')).toBeNull();
    expect(localStorage.getItem('ao3.updateCheckDismissed')).toBe('true');
  });

  // endregion

  // region the naming note shown before the folder picker

  function folderButton(element: HTMLElement): HTMLButtonElement {
    return Array.from(element.querySelectorAll<HTMLButtonElement>('.picker button')).find((b) =>
      b.textContent?.includes('folder'),
    )!;
  }

  function warningButton(element: HTMLElement, text: string): HTMLButtonElement | undefined {
    return Array.from(
      element.querySelectorAll<HTMLButtonElement>('app-folder-warning button'),
    ).find((b) => b.textContent?.trim() === text);
  }

  /** the picker this browser actually uses - jsdom has no directory picker, so the input */
  function watchPicker(element: HTMLElement) {
    const input = element.querySelector<HTMLInputElement>('input[type="file"]')!;
    const opened = vi.fn();
    input.click = opened;
    return opened;
  }

  async function clickFolder(fixture: ComponentFixture<App>, element: HTMLElement) {
    const opened = watchPicker(element);
    folderButton(element).click();
    await fixture.whenStable();
    return opened;
  }

  it('says how files have to be named before opening the picker', async () => {
    // the rule cannot be discovered afterwards: files named wrongly still load, they just
    // never match the index. so it is said at the one moment it can be acted on
    const { fixture, element } = await render(0);

    const opened = await clickFolder(fixture, element);

    expect(element.querySelector('app-folder-warning')).toBeTruthy();
    expect(element.querySelector('app-folder-warning')?.textContent).toContain('work ID at the start');
    // and where the date goes in the ideal name, and how it is written
    const ideal = element.querySelector('app-folder-warning .ideal')?.textContent?.replace(/\s+/g, ' ');
    expect(ideal).toContain('1234567 The Trees Are Burning - library_of_alexandria 2024-12-14.html');
    expect(element.querySelector('app-folder-warning')?.textContent).toContain('YYYY-MM-DD');
    expect(opened).not.toHaveBeenCalled();
  });

  it('opens the picker once the note has been read', async () => {
    const { fixture, element } = await render(0);
    const opened = await clickFolder(fixture, element);

    warningButton(element, 'Choose folder')!.click();
    await fixture.whenStable();

    expect(opened).toHaveBeenCalled();
    expect(element.querySelector('app-folder-warning')).toBeNull();
  });

  it('opens no picker when the note is backed out of', async () => {
    const { fixture, element } = await render(0);
    const opened = await clickFolder(fixture, element);

    warningButton(element, 'Cancel')!.click();
    await fixture.whenStable();

    expect(opened).not.toHaveBeenCalled();
    expect(element.querySelector('app-folder-warning')).toBeNull();
  });

  it('does not show the note again once it has been turned off', async () => {
    const { fixture, element } = await render(0);
    await clickFolder(fixture, element);

    const box = element.querySelector<HTMLInputElement>('input[name="dontAskAgain"]')!;
    box.click();
    await fixture.whenStable();
    warningButton(element, 'Choose folder')!.click();
    await fixture.whenStable();

    const opened = await clickFolder(fixture, element);

    expect(element.querySelector('app-folder-warning')).toBeNull();
    expect(opened).toHaveBeenCalled();
  });

  it('keeps asking when the note is turned off but then backed out of', async () => {
    // ticking the box is not the decision; going through with it is. otherwise a change of
    // mind at the last moment silences a warning the user never actually accepted
    const { fixture, element } = await render(0);
    await clickFolder(fixture, element);

    element.querySelector<HTMLInputElement>('input[name="dontAskAgain"]')!.click();
    await fixture.whenStable();
    warningButton(element, 'Cancel')!.click();
    await fixture.whenStable();

    await clickFolder(fixture, element);

    expect(element.querySelector('app-folder-warning')).toBeTruthy();
  });

  // endregion

  // region where the library lives

  function storageButton(element: HTMLElement, name: string): HTMLButtonElement {
    return Array.from(element.querySelectorAll<HTMLButtonElement>('.storage button')).find((b) =>
      b.textContent?.includes(name),
    )!;
  }

  it('keeps the library on this computer until told otherwise', async () => {
    const element = await withFolder();
    expect(storageButton(element, 'This computer').getAttribute('aria-pressed')).toBe('true');
    expect(actionLabels(element)).toContain('Quick Scan');
  });

  it('offers no run in dropbox until its folder is open', async () => {
    // the local folder is not where a run would write any more, and dropbox is not signed in
    const fixture = TestBed.createComponent(App);
    openLibrary();
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    storageButton(element, 'Dropbox').click();
    await fixture.whenStable();

    expect(actionLabels(element)).toEqual([]);
    expect(localStorage.getItem('ao3.storageMode')).toBe('dropbox');
  });

  it('remembers the local folder underneath a switch to dropbox and back', async () => {
    const fixture = TestBed.createComponent(App);
    openLibrary();
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    storageButton(element, 'Dropbox').click();
    await fixture.whenStable();
    storageButton(element, 'This computer').click();
    await fixture.whenStable();

    // still the folder that reopens - switching never forgets it
    expect(element.querySelector('.topbar .source')?.textContent).toContain('downloads');
  });

  it('says where to put the app key when this copy has no dropbox app', async () => {
    localStorage.setItem('ao3.storageMode', 'dropbox');
    TestBed.inject(DropboxSession).status.set('unconfigured');
    const element = await withFolder();

    expect(element.querySelector('.empty h2')?.textContent).toContain('not set up');
    expect(element.textContent).toContain('dropbox-config.ts');
    expect(element.textContent).not.toContain('Sign in with Dropbox');
  });

  it('opens the dropbox app folder as soon as someone is signed in', async () => {
    // there is nothing to choose: the app folder is all this app can see, so it is the library
    localStorage.setItem('ao3.storageMode', 'dropbox');
    const dropbox = TestBed.inject(DropboxSession);
    dropbox.status.set('signed-in');
    dropbox.account.set({ id: 'dbid:me', name: 'Me', email: 'me@example.com' });

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    // what opening the app folder leaves behind, once it is set up
    openLibrary('Dropbox app folder');
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const source = element.querySelector('.topbar .source');
    expect(source?.textContent).toContain('/Apps/FicFairy');
    expect(source?.getAttribute('title')).toContain('me@example.com');
    // the library is open, which is everything a run needs
    expect(actionLabels(element)).toContain('Quick Scan');
    const labels = Array.from(element.querySelectorAll('.topbar button')).map((b) =>
      b.textContent?.trim(),
    );
    expect(labels).toContain('Sign out');
    expect(labels.join(' ')).not.toContain('folder');
  });

  it('says where the library will live before anyone signs in', async () => {
    localStorage.setItem('ao3.storageMode', 'dropbox');
    TestBed.inject(DropboxSession).status.set('signed-out');
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.empty')?.textContent).toContain('/Apps/FicFairy');
    expect(actionLabels(element)).toEqual([]);
  });

  // endregion

  // region works with files and no index entry

  /** a library with these files in works/, as a run would list it */
  function libraryWithFiles(paths: string[]): void {
    openLibrary();
    const library = TestBed.inject(Library);
    const store = library.store()!;
    library.store.set({ ...store, list: async () => paths });
  }

  async function settled(fixture: ComponentFixture<App>): Promise<void> {
    // the listing is asked for, then the offer decided on
    for (let i = 0; i < 3; i++) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await fixture.whenStable();
    }
  }

  it('neither checks nor offers anything when the library could not be read', async () => {
    localStorage.clear();
    libraryWithFiles(['works/1 Work 1 - Writer 2024-01-01.html']);
    const library = TestBed.inject(Library);
    vi.spyOn(library, 'showLocal').mockResolvedValue();
    library.error.set('Could not read downloads.');
    library.readFailure.set({ waitSeconds: 3, slowDown: false });
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('app-import-dialog')).toBeNull();
    expect(element.querySelector('.import-issues')).toBeNull();
    library.readFailure.set(null);
  });

  it('neither checks nor offers anything while the library is still being read', async () => {
    localStorage.clear();
    libraryWithFiles(['works/1 Work 1 - Writer 2024-01-01.html']);
    const library = TestBed.inject(Library);
    // a read under way, which opening the page would otherwise start afresh
    vi.spyOn(library, 'showLocal').mockResolvedValue();
    library.loading.set(true);
    // the store is set before the index is read: against an empty index, work 1 looks unindexed
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('app-import-dialog')).toBeNull();
    expect(element.querySelector('.import-issues')).toBeNull();

    library.data.set(exportOf(1));
    library.worksById.set(new Map([['1', work(1)]]));
    library.loading.set(false);
    await settled(fixture);
    expect(element.querySelector('app-import-dialog')).toBeNull();
    expect(element.querySelector('.import-issues')).toBeNull();
  });

  it('offers the window and the reminder for duplicates alone, with nothing undated or unindexed', async () => {
    localStorage.clear();
    // work 1 is indexed and both copies are dated: the only issue is that there are two
    libraryWithFiles(['works/1 Work 1 - Writer 2024-01-01.html', 'works/1 Work 1 - Writer 2024-02-01.html']);
    TestBed.inject(Library).data.set(exportOf(1));
    TestBed.inject(Library).worksById.set(new Map([['1', work(1)]]));
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;

    const offered = element.querySelector('app-import-dialog');
    const bullets = [...offered!.querySelectorAll('.overview-issues li')].map((li) => li.textContent!.trim());
    expect(bullets).toEqual(['2 files are duplicates']);
    expect(element.querySelector('.import-issues-said')?.textContent?.trim()).toBe('2 files are duplicates');
  });

  it('offers to import works whose files have no index entry, once, when the library opens', async () => {
    localStorage.clear();
    libraryWithFiles(['works/1 Work 1 - Writer.html', 'works/999 Not Indexed - Writer.html']);
    TestBed.inject(Library).data.set(exportOf(1));
    TestBed.inject(Library).worksById.set(new Map([['1', work(1)]]));
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;

    const offered = element.querySelector('app-import-dialog');
    expect(offered?.textContent).toContain('1 file belongs to a work that has no index');
    expect(element.querySelector('.import-issues')?.textContent).toContain('Resolve issues found with import');
    // the reminder counts and words it as the window's own bullets do
    const bullets = [...offered!.querySelectorAll('.overview-issues li')].map((li) => li.textContent!.trim());
    expect(bullets).toEqual(['2 files have no date', '1 file belongs to a work that has no index']);
    expect(element.querySelector('.import-issues-said')?.textContent?.trim()).toBe(bullets.join('; '));

    offered!.querySelector<HTMLInputElement>('input[name="firstChoice"][value="later"]')!.click();
    await settled(fixture);
    Array.from(offered!.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Remind me later')!.click();
    await settled(fixture);
    expect(element.querySelector('app-import-dialog')).toBeNull();
    // the index changing again does not bring it back by itself on this visit
    TestBed.inject(Library).worksById.set(new Map([['1', work(1)]]));
    await settled(fixture);
    expect(element.querySelector('app-import-dialog')).toBeNull();
    // and the reminder goes with it, until the library is opened again
    expect(element.querySelector('.import-issues')).toBeNull();
  });

  it('does not offer an import while a run is going, and offers it once the run has ended', async () => {
    localStorage.clear();
    TestBed.inject(Jobs).activeRuns.set([going]);
    libraryWithFiles(['works/999 Not Indexed - Writer.html']);
    TestBed.inject(Library).data.set(exportOf(1));
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('app-import-dialog')).toBeNull();
    const notice = element.querySelector<HTMLButtonElement>('.import-issues button')!;
    expect(notice.disabled).toBe(true);
    expect(notice.title).toContain('active run is in progress');

    TestBed.inject(Jobs).activeRuns.set([]);
    await settled(fixture);
    expect(element.querySelector('app-import-dialog')).not.toBeNull();
  });

  it('offers undated files of works the index has, on the Works tab and by itself', async () => {
    localStorage.clear();
    libraryWithFiles(['works/1 Work 1 - Writer.html']);
    TestBed.inject(Library).data.set(exportOf(1));
    TestBed.inject(Library).worksById.set(new Map([['1', work(1)]]));
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.import-issues')?.textContent).toContain('1 file has no date');
    expect(element.querySelector('app-import-dialog')?.textContent).toContain('1 file has no date');
  });

  it('puts the reminder under the tabs and above what each tab shows, on every tab, until dismissed', async () => {
    localStorage.clear();
    libraryWithFiles(['works/999 Not Indexed - Writer.html']);
    TestBed.inject(Library).data.set(exportOf(1));
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;

    const issues = element.querySelector('.import-issues')!;
    const tabs = element.querySelector('nav.views')!;
    expect(tabs.compareDocumentPosition(issues) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(issues.compareDocumentPosition(element.querySelector('app-work-list')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (const [name, content] of [['Collections', 'app-collections-view'], ['History', 'app-history'], ['FAQ', 'app-faq'], ['User settings', 'app-user-settings']]) {
      tab(element, name)!.click();
      await fixture.whenStable();
      const shown = element.querySelector('.import-issues');
      expect(shown).not.toBeNull();
      expect(shown!.compareDocumentPosition(element.querySelector(content)!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }

    element.querySelector<HTMLButtonElement>('.import-issues-close')!.click();
    await fixture.whenStable();
    expect(element.querySelector('.import-issues')).toBeNull();
  });

  it('shows debug mode above everything, with a DEBUG tab, only once turned on', async () => {
    localStorage.clear();
    libraryWithFiles(['works/999 Not Indexed - Writer.html']);
    TestBed.inject(Library).data.set(exportOf(1));
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.debug-banner')).toBeNull();
    expect(tab(element, 'DEBUG')).toBeUndefined();

    TestBed.inject(DebugMode).set(true);
    await settled(fixture);
    const banner = element.querySelector('.debug-banner')!;
    expect(banner.textContent).toContain('Debug mode is on');
    expect(banner.compareDocumentPosition(element.querySelector('.import-issues')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    tab(element, 'DEBUG')!.click();
    await fixture.whenStable();
    expect(element.querySelector('app-debug-tab')).toBeTruthy();
  });

  it('leaves debug mode from its banner, moving off the DEBUG tab', async () => {
    localStorage.clear();
    TestBed.inject(DebugMode).set(true);
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;
    tab(element, 'DEBUG')!.click();
    await fixture.whenStable();

    element.querySelector<HTMLButtonElement>('.debug-leave button')!.click();
    await settled(fixture);
    expect(TestBed.inject(DebugMode).on()).toBe(false);
    expect(element.querySelector('.debug-banner')).toBeNull();
    expect(tab(element, 'DEBUG')).toBeUndefined();
    expect(element.querySelector('app-debug-tab')).toBeNull();
  });

  it('neither opens the window nor shows the reminder once told never to ask again', async () => {
    localStorage.clear();
    localStorage.setItem('ao3.importOfferOff', 'off');
    libraryWithFiles(['works/999 Not Indexed - Writer.html']);
    TestBed.inject(Library).data.set(exportOf(1));
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('app-import-dialog')).toBeNull();
    expect(element.querySelector('.import-issues')).toBeNull();
  });

  it('turns the window and the reminder off for good from its first page', async () => {
    localStorage.clear();
    libraryWithFiles(['works/999 Not Indexed - Writer.html']);
    TestBed.inject(Library).data.set(exportOf(1));
    const fixture = TestBed.createComponent(App);
    await settled(fixture);
    const element = fixture.nativeElement as HTMLElement;

    const offered = element.querySelector('app-import-dialog')!;
    offered.querySelector<HTMLInputElement>('input[name="firstChoice"][value="never"]')!.click();
    await settled(fixture);
    Array.from(offered.querySelectorAll('button')).find((b) => b.textContent?.trim() === 'Done')!.click();
    await settled(fixture);

    expect(element.querySelector('app-import-dialog')).toBeNull();
    expect(element.querySelector('.import-issues')).toBeNull();
    expect(localStorage.getItem('ao3.importOfferOff')).toBe('off');
  });

  // endregion
});
