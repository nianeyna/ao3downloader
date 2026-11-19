import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VisitLog } from './visit-log';
import { Jobs } from './jobs';
import { Feedback, ISSUE_BODY_LIMIT, LOG_ATTACH_LIMIT, LOG_CUT_NOTE, VISIT_ATTACH_LIMIT, VISIT_CUT_NOTE, newestPart, Turnstile, USERNAME_REMOVED, issueLength, ISSUE_RESERVE, runSummary, logExcerpt, ZONE_REMOVED, PATH_REMOVED, failureReason, readLatestLog, redactLog } from './feedback';
import { DEFAULT_PAGE_CONFIG, HelperConnection } from './helper-connection';
import { Library } from './library';
import { DirectoryHandle } from './folder-store';
import { DropboxLibraryStore, LibraryStore, LocalLibraryStore } from './library-store';

const WORKER = 'https://feedback.example.workers.dev';

/** The bot-check widget, passing at once unless told not to */
class FakeTurnstile extends Turnstile {
  rendered = 0;
  resets = 0;
  removed: string[] = [];
  pass = true;
  /** set to stand for a widget that will not load - offline, or blocked */
  broken = false;
  private give: (token: string) => void = () => {};

  override async render(_element: HTMLElement, _siteKey: string, token: (value: string) => void): Promise<string> {
    this.rendered++;
    if (this.broken) throw new Error('could not load the bot check');
    this.give = token;
    if (this.pass) token(`token-${this.rendered}`);
    return `widget-${this.rendered}`;
  }

  override reset(_id: string): void {
    this.resets++;
    if (this.pass) this.give(`token-again-${this.resets}`);
  }

  override remove(id: string): void {
    this.removed.push(id);
  }
}

/** a library holding only run records */
function storeWith(files: Record<string, string>): LibraryStore {
  return {
    label: 'test',
    check: async () => {},
    list: async () => Object.keys(files),
    read: async (path: string) => files[path] ?? null,
    write: async () => 0,
    size: async () => null,
    delete: async () => {},
    rename: async () => {},
    mkdir: async () => {},
  };
}

function record(over: Record<string, unknown> = {}): string {
  return JSON.stringify({
    actionName: 'Quick scan',
    started: '2026-10-20T10:00:00',
    username: 'ReaderName',
    log: ['logging in as ReaderName', 'new download: 1 A.html'],
    ...over,
  });
}

let turnstile: FakeTurnstile;
let helper: HelperConnection;
let fixture: ComponentFixture<Feedback>;
let element: HTMLElement;

function answering(status: number, body: object) {
  const fetching = vi.fn(async (_url: unknown, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetching);
  return fetching;
}

async function settle() {
  for (let i = 0; i < 4; i++) {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  fixture.detectChanges();
}

async function make(feedbackUrl = WORKER) {
  helper.settings.set({ ...DEFAULT_PAGE_CONFIG, feedbackUrl, turnstileSiteKey: feedbackUrl ? '0x4AAA' : '' });
  fixture = TestBed.createComponent(Feedback);
  element = fixture.nativeElement as HTMLElement;
  await settle();
}

async function openForm() {
  (element.querySelector('.feedback-tab') as HTMLButtonElement).click();
  await settle();
}

async function fill(kind: 'general' | 'feature' | 'bug', message: string, name = '') {
  const select = element.querySelector('select[name="kind"]') as HTMLSelectElement;
  select.value = kind;
  select.dispatchEvent(new Event('change'));
  const text = element.querySelector('textarea') as HTMLTextAreaElement;
  text.value = message;
  text.dispatchEvent(new Event('input'));
  if (name) {
    const input = element.querySelector('input[name="name"]') as HTMLInputElement;
    input.value = name;
    input.dispatchEvent(new Event('input'));
  }
  await settle();
}

function sendButton(): HTMLButtonElement {
  return element.querySelector('button[type="submit"]') as HTMLButtonElement;
}

async function send() {
  element.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
  await settle();
}

async function tickLog() {
  const box = element.querySelector('input[name="attachLog"]') as HTMLInputElement;
  box.checked = true;
  box.dispatchEvent(new Event('change'));
  await settle();
}

function sentBody(fetching: ReturnType<typeof answering>): Record<string, unknown> {
  return JSON.parse(String(fetching.mock.calls[0][1]?.body));
}

describe('Feedback', () => {
  beforeEach(() => {
    localStorage.clear();
    turnstile = new FakeTurnstile();
    helper = new HelperConnection();
    TestBed.configureTestingModule({
      providers: [
        { provide: Turnstile, useValue: turnstile },
        { provide: HelperConnection, useValue: helper },
      ],
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('attaches what was done on this visit, with the username taken out, when ticked', async () => {
    localStorage.setItem('ao3.username', 'ReaderName');
    TestBed.inject(VisitLog).note('User settings: Saved: the Lavender palette, as ReaderName');
    await make();
    await openForm();
    const box = element.querySelector<HTMLInputElement>('input[name="attachVisit"]')!;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    await settle();
    const preview = element.querySelector('details.visit pre')?.textContent ?? '';
    expect(preview).toContain('Saved: the Lavender palette');
    expect(preview).not.toContain('ReaderName');
    localStorage.removeItem('ao3.username');
  });

  it('says at the bottom of the form that an attached log loses the AO3 username', async () => {
    await make();
    await openForm();
    const note = element.querySelector('.hint.privacy')?.textContent ?? '';
    expect(note).toContain('AO3');
    expect(note).toContain('username');
    expect(note).toContain('password');
    expect(note).toContain('IP address');
  });

  it('says the feedback is posted publicly, and where', async () => {
    await make();
    await openForm();
    const link = element.querySelector<HTMLAnchorElement>('.hint.public a');
    expect(link?.href).toBe('https://github.com/alexandria-p/ficfairy/issues/');
    expect(element.querySelector('.hint.public')?.textContent).toContain('posted publicly');
  });

  it('offers no tab on a copy built without the feedback service', async () => {
    await make('');
    expect(element.querySelector('.feedback-tab')).toBeNull();
  });

  it('opens the form from the tab, with the bot check in it', async () => {
    await make();
    expect(element.querySelector('[role="dialog"]')).toBeNull();

    await openForm();

    expect(element.querySelector('[role="dialog"]')).not.toBeNull();
    expect(turnstile.rendered).toBe(1);
    // nobody is asked how to be contacted: the issue is public
    expect(element.querySelector('input[type="email"]')).toBeNull();
  });

  it('cannot be sent without a message, or before the bot check passes', async () => {
    turnstile.pass = false;
    await make();
    await openForm();
    expect(sendButton().disabled).toBe(true);

    await fill('general', 'Love it');
    expect(sendButton().disabled).toBe(true);
  });

  it('sends the form to the feedback service, never the helper, and links the issue it made', async () => {
    const fetching = answering(201, { ok: true, number: 12, url: 'https://github.com/o/r/issues/12' });
    await make();
    await openForm();
    await fill('bug', 'The quick scan stopped', 'Sam');
    expect(sendButton().disabled).toBe(false);

    await send();

    expect(fetching.mock.calls[0][0]).toBe(WORKER);
    const body = sentBody(fetching);
    expect(body).toMatchObject({
      kind: 'bug',
      ratings: {},
      message: 'The quick scan stopped',
      name: 'Sam',
      log: '',
      // nothing is open in this spec; a folder's own name is never sent
      storage: 'no library open',
      turnstileToken: 'token-1',
    });
    const link = element.querySelector('a[href="https://github.com/o/r/issues/12"]');
    expect(link?.textContent).toContain('issue #12');
    expect(element.textContent).toContain('It may take up to a minute to');
    expect(element.querySelector('a[href*="label%3Afeedback"]')).not.toBeNull();
  });

  it('asks what kind of feedback it is from a dropdown, starting on general feedback', async () => {
    const fetching = answering(201, { ok: true, number: 4, url: 'https://github.com/o/r/issues/4' });
    await make();
    await openForm();
    const select = element.querySelector<HTMLSelectElement>('select[name="kind"]')!;
    expect([...select.options].map((o) => o.textContent?.trim())).toEqual(['General feedback', 'Feature suggestion', 'Bug report']);
    expect(select.value).toBe('general');

    // a message alone is enough: the kind is already chosen
    const text = element.querySelector('textarea') as HTMLTextAreaElement;
    text.value = 'Lovely';
    text.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    await send();
    expect(sentBody(fetching)).toMatchObject({ kind: 'general' });
  });

  it('sends only the quick questions answered, each by a word picked, folded away to begin with', async () => {
    const fetching = answering(201, { ok: true, number: 3, url: 'https://github.com/o/r/issues/3' });
    await make();
    await openForm();
    const fold = element.querySelector<HTMLDetailsElement>('details.quick-questions')!;
    expect(fold.open).toBe(false);
    expect(fold.querySelector('summary')?.textContent).toContain('(Optional) Quick questions about your experience');
    const choices = (key: string) => [...element.querySelectorAll<HTMLInputElement>(`[data-rating="${key}"] input[type="radio"]`)];
    const words = (key: string) => [...element.querySelectorAll(`[data-rating="${key}"] .rating-choices label`)].map((l) => l.textContent?.trim());
    expect(words('easy')).toEqual(['Very hard', 'Hard', 'Neutral', 'Easy', 'Very easy']);
    // nothing picked to begin with: every question unanswered
    expect(['easy', 'useful', 'confusing', 'complete'].every((k) => choices(k).every((c) => !c.checked))).toBe(true);
    expect(element.querySelector('[data-rating="easy"] .rating-said')?.textContent).toContain('Not answered');

    const pick = async (key: string, value: number) => {
      choices(key)[value - 1].click();
      await fixture.whenStable();
    };
    await pick('easy', 4);
    await pick('useful', 2);
    // the middle word is an answer like any other
    await pick('complete', 3);
    expect(element.querySelector('[data-rating="easy"]')!.classList).toContain('answered');
    element.querySelector<HTMLButtonElement>('[data-rating="useful"] .clear-rating')!.click();
    await fixture.whenStable();
    expect(element.querySelector('[data-rating="useful"] .rating-said')?.textContent).toContain('Not answered');
    expect(choices('useful').every((c) => !c.checked)).toBe(true);
    expect(fold.querySelector('summary')?.textContent).toContain('2 answered');

    await fill('feature', 'A dark mode please');
    await send();
    expect(sentBody(fetching)).toMatchObject({ kind: 'feature', ratings: { easy: 4, complete: 3 } });
  });

  it('says so when the bot check refuses it, keeps what was typed, and gets a fresh bot check', async () => {
    answering(403, { error: 'the bot check did not pass - try again' });
    await make();
    await openForm();
    await fill('general', 'Nice');

    await send();

    expect(element.textContent).toContain("Uh oh - we couldn't submit your feedback");
    expect(element.textContent).toContain('the bot check did not pass');
    expect((element.querySelector('textarea') as HTMLTextAreaElement).value).toBe('Nice');
    expect(turnstile.resets).toBe(1);
  });

  it('says so when the service cannot be reached at all', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    await make();
    await openForm();
    await fill('bug', 'Broken');

    await send();

    expect(element.textContent).toContain("Uh oh - we couldn't submit your feedback");
    expect(element.textContent).toContain('could not be reached');
    expect(sendButton().textContent).toContain('Send feedback');
  });

  it('does not try at all while offline', async () => {
    const fetching = answering(201, { ok: true, number: 1, url: 'https://github.com/o/r/issues/1' });
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    await make();
    await openForm();
    await fill('bug', 'Broken');

    await send();

    expect(fetching).not.toHaveBeenCalled();
    expect(element.textContent).toContain('offline');
    vi.restoreAllMocks();
  });

  it('links GitHub in a new tab with what was written filled in', async () => {
    answering(500, {});
    await make();
    await openForm();
    await fill('bug', 'The scan stopped\nat page 4');

    await send();

    const link = element.querySelector('a[href*="/issues/new?"]') as HTMLAnchorElement;
    expect(link.target).toBe('_blank');
    const query = new URL(link.href).searchParams;
    expect(query.get('title')).toBe('Bug report: The scan stopped');
    expect(query.get('body')).toBe('The scan stopped\nat page 4');
  });

  it('offers what was written as a text file, so nothing is lost', async () => {
    answering(502, { error: 'GitHub did not take it - try again in a minute' });
    let saved: Blob | null = null;
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      saved = blob as Blob;
      return 'blob:feedback';
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await make();
    await openForm();
    await fill('general', 'Lovely app', 'Sam');
    await send();

    const download = [...element.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Download what I wrote'),
    )!;
    download.click();

    const text = await (saved as unknown as Blob).text();
    expect(text).toContain('Kind: General feedback');
    expect(text).toContain('Name: Sam');
    expect(text).toContain('Lovely app');
    vi.restoreAllMocks();
  });

  it('offers the same way out when the bot check will not load', async () => {
    turnstile.broken = true;
    await make();
    await openForm();
    await fill('general', 'Hi');

    expect(element.textContent).toContain("Uh oh - we couldn't submit your feedback");
    expect(element.textContent).toContain('bot check would not load');
    expect(sendButton().disabled).toBe(true);
    expect(element.querySelector('a[href*="/issues/new?"]')).not.toBeNull();
  });

  it('closes on escape, taking the bot check down with it', async () => {
    await make();
    await openForm();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await settle();

    expect(element.querySelector('[role="dialog"]')).toBeNull();
    expect(turnstile.removed).toEqual(['widget-1']);
  });

  it('says whether the library is in Dropbox or on this computer, never the folder', async () => {
    const fetching = answering(201, { ok: true, number: 4, url: 'https://github.com/o/r/issues/4' });
    const local = new LocalLibraryStore({ name: 'Sams fics' } as unknown as DirectoryHandle);
    TestBed.inject(Library).store.set(local);
    await make();
    await openForm();
    await fill('general', 'Nice');
    await send();

    expect(sentBody(fetching)['storage']).toBe('a folder on this computer');
    expect(JSON.stringify(sentBody(fetching))).not.toContain('Sams fics');

    TestBed.inject(Library).store.set(Object.create(DropboxLibraryStore.prototype) as DropboxLibraryStore);
    expect((fixture.componentInstance as unknown as { storageKind(): string }).storageKind()).toBe('Dropbox');
  });

  it('offers to attach a log only with a library open', async () => {
    await make();
    await openForm();
    const box = element.querySelector('input[name="attachLog"]') as HTMLInputElement;
    expect(box.disabled).toBe(true);
    expect(element.textContent).toContain('Open your library');
  });

  it('attaches the latest run log with the AO3 username taken out, and shows it first', async () => {
    const fetching = answering(201, { ok: true, number: 3, url: 'https://github.com/o/r/issues/3' });
    TestBed.inject(Library).store.set(
      storeWith({
        'runs/2026-10-01T090000-a.json': record({ log: ['an older run'] }),
        'runs/2026-10-20T100000-b.json': record(),
      }),
    );
    await make();
    await openForm();
    await fill('bug', 'It failed');

    await tickLog();

    const preview = element.querySelector('.log pre')?.textContent ?? '';
    expect(preview).toContain('new download: 1 A.html');
    expect(preview).toContain(`logging in as ${USERNAME_REMOVED}`);
    expect(preview).not.toContain('ReaderName');
    expect(preview).not.toContain('an older run');

    await send();

    const log = String(sentBody(fetching)['log']);
    expect(log).toContain('# Quick scan');
    expect(log).not.toContain('ReaderName');
  });

  it('lets a run be chosen, holding Send while the runs are read and until one is chosen', async () => {
    const pending: ((paths: string[]) => void)[] = [];
    const listed = (paths: string[]) => pending.splice(0).forEach((resolve) => resolve(paths));
    const files: Record<string, string> = {
      'runs/20261020T100000Z-aaaa1111.json': record({ id: 'aaaa1111', action: 'quick', status: 'success', actionName: 'Quick scan' }),
      'runs/20261001T100000Z-bbbb2222.json': record({ id: 'bbbb2222', action: 'bookmarks', status: 'partial', started: '2026-10-01T10:00:00',
        actionName: 'Full scan', log: ['an older run, as ReaderName'] }),
    };
    TestBed.inject(Library).store.set({
      ...storeWith(files),
      list: () => new Promise<string[]>((resolve) => pending.push(resolve)),
    });
    await make();
    await openForm();
    await fill('general', 'Hi');
    await tickLog();
    const choose = element.querySelector<HTMLInputElement>('input[name="logChoice"][value="choose"]')!;
    choose.checked = true;
    choose.dispatchEvent(new Event('change'));
    await settle();

    expect(element.querySelector('.reading-runs')).not.toBeNull();
    expect(sendButton().disabled).toBe(true);

    listed(Object.keys(files));
    await settle();
    const pick = element.querySelector<HTMLSelectElement>('select.run-pick')!;
    expect(pick.options.length).toBe(3);
    expect(sendButton().disabled).toBe(true);

    pick.value = '20261001T100000Z-bbbb2222.json';
    pick.dispatchEvent(new Event('change'));
    await settle();
    const preview = element.querySelector('details.log pre')?.textContent ?? '';
    expect(preview).toContain('# Full scan');
    expect(preview).toContain('an older run');
    expect(preview).not.toContain('ReaderName');
    expect(sendButton().disabled).toBe(false);
  });

  it('stops reading the runs when the form is closed before they are read', async () => {
    let listed!: (paths: string[]) => void;
    const read = vi.fn(async () => record());
    TestBed.inject(Library).store.set({
      ...storeWith({}),
      list: () => new Promise<string[]>((resolve) => (listed = resolve)),
      read,
    });
    await make();
    await openForm();
    (element.querySelector('.dialog button.icon, button[aria-label="Close"]') as HTMLButtonElement).click();
    await settle();

    listed(['runs/20261020T100000Z-aaaa1111.json']);
    await settle();
    expect(read).not.toHaveBeenCalled();
  });

  it("reads a run still going from the helper, as History does - its file lags behind the window", async () => {
    TestBed.inject(Library).store.set(storeWith({
      'runs/20261020T100000Z-aaaa1111.json': record({ log: ['saved a while ago'] }),
    }));
    const jobs = TestBed.inject(Jobs);
    jobs.activeRuns.set([{ id: 'aaaa1111-full-id', action: 'import' } as never]);
    const live = vi.spyOn(jobs, 'liveRecord').mockResolvedValue(
      JSON.parse(record({ log: ['saved a while ago', 'stopping at your request...'] })));
    await make();
    await openForm();
    await tickLog();

    expect(live).toHaveBeenCalledWith('aaaa1111-full-id');
    const preview = element.querySelector('.log pre')?.textContent ?? '';
    expect(preview).toContain('stopping at your request...');
  });

  it('reads an ended run from its file, never asking the helper', async () => {
    TestBed.inject(Library).store.set(storeWith({
      'runs/20261020T100000Z-aaaa1111.json': record({ log: ['all saved'] }),
    }));
    const live = vi.spyOn(TestBed.inject(Jobs), 'liveRecord');
    await make();
    await openForm();
    await tickLog();

    expect(live).not.toHaveBeenCalled();
    expect(element.querySelector('.log pre')?.textContent).toContain('all saved');
  });

  it('shows a long run log trimmed to exactly what is sent, its heading kept, and says so', async () => {
    const fetching = answering(201, { ok: true, number: 6, url: 'https://github.com/o/r/issues/6' });
    const long = Array.from({ length: 2000 }, (_, i) => `line ${i} ${'x'.repeat(40)}`);
    TestBed.inject(Library).store.set(storeWith({ 'runs/20261020T100000Z-aaaa1111.json': record({ log: long }) }));
    await make();
    await openForm();
    await fill('bug', 'short');
    await tickLog();

    expect(element.querySelector('.log-cut')?.textContent).toContain('most recent part');
    expect(element.querySelector('.log-cut')?.textContent).toContain('Download log');
    const preview = element.querySelector('details.log pre')?.textContent ?? '';
    expect(preview.length).toBeLessThanOrEqual(LOG_ATTACH_LIMIT);
    expect(preview.startsWith('# Quick scan\nStatus:')).toBe(true);
    expect(preview).toContain('\nIssues: ');
    expect(preview).toContain(LOG_CUT_NOTE);
    expect(preview).toContain('line 1999');
    expect(preview).not.toContain('line 0 ');

    await send();
    expect(sentBody(fetching)['log']).toBe(preview);
  });

  it('holds Send while the message and both logs come to more than GitHub takes, and says by how much', async () => {
    const fetching = answering(201, { ok: true, number: 4, url: 'https://github.com/o/r/issues/4' });
    const long = Array.from({ length: 1500 }, (_, i) => `line ${i} ${'x'.repeat(40)}`);
    TestBed.inject(Library).store.set(storeWith({ 'runs/20261020T100000Z-aaaa1111.json': record({ log: long }) }));
    for (let i = 0; i < 800; i++) TestBed.inject(VisitLog).note(`step ${i} ${'z'.repeat(40)}`);
    await make();
    await openForm();
    await fill('bug', 'short');
    await tickLog();

    // the run log alone fits, and is attached whole as it will be sent
    expect(element.querySelector('.too-long')).toBeNull();
    expect(element.querySelector('.issue-size')?.textContent).toContain('of 65,536 characters');
    expect(element.querySelector('details.log pre')).not.toBeNull();
    expect(sendButton().disabled).toBe(false);

    // with the visit's log too it does not: still attachable, but Send is held
    const visit = element.querySelector('input[name="attachVisit"]') as HTMLInputElement;
    visit.checked = true;
    visit.dispatchEvent(new Event('change'));
    await settle();
    expect(element.querySelector('.too-long')?.textContent).toContain('characters too long to send');
    expect(element.querySelector('.too-long')?.textContent).toContain('History');
    expect(sendButton().disabled).toBe(true);
    await send();
    expect(fetching).not.toHaveBeenCalled();

    // untick it, and it can go
    visit.checked = false;
    visit.dispatchEvent(new Event('change'));
    await settle();
    expect(sendButton().disabled).toBe(false);
  });

  it('says when the feedback nears its limit, and when it reaches it', async () => {
    await make();
    await openForm();
    await fill('general', 'short');
    expect(element.querySelector('.message-count')).toBeNull();
    await fill('general', 'a'.repeat(4600));
    expect(element.querySelector('.message-count')?.textContent).toContain('4,600 of 5,000');
    await fill('general', 'a'.repeat(5000));
    expect(element.querySelector('.message-count.at-limit')?.textContent).toContain('reached the limit');
  });

  it('says when the name nears its limit, and when it reaches it', async () => {
    await make();
    await openForm();
    await fill('general', 'Hi', 'a'.repeat(50));
    expect(element.querySelector('.name-count')).toBeNull();
    await fill('general', 'Hi', 'a'.repeat(95));
    expect(element.querySelector('.name-count')?.textContent).toContain('95 of 100');
    await fill('general', 'Hi', 'a'.repeat(100));
    expect(element.querySelector('.name-count.at-limit')?.textContent).toContain('reached the limit');
    expect((element.querySelector('input[name="name"]') as HTMLInputElement).maxLength).toBe(100);
  });

  it('attaches only the last lines chosen, under the run\'s details, and counts them', async () => {
    const fetching = answering(201, { ok: true, number: 7, url: 'https://github.com/o/r/issues/7' });
    const long = Array.from({ length: 400 }, (_, i) => `line ${i}`);
    TestBed.inject(Library).store.set(storeWith({ 'runs/20261020T100000Z-aaaa1111.json': record({ log: long }) }));
    await make();
    await openForm();
    await fill('bug', 'short');
    await tickLog();
    const pick = element.querySelector<HTMLSelectElement>('select[name="logAmount"]')!;
    pick.value = '100';
    pick.dispatchEvent(new Event('change'));
    await settle();

    const preview = element.querySelector('details.log pre')?.textContent ?? '';
    expect(preview.startsWith('# Quick scan\nStatus:')).toBe(true);
    expect(preview).toContain(LOG_CUT_NOTE);
    expect(preview).toContain('line 399');
    expect(preview).toContain('line 300');
    expect(preview).not.toContain('line 299');
    expect(element.querySelector('.log-cut')).not.toBeNull();
    expect(element.querySelector('.issue-size')?.textContent).toContain((ISSUE_RESERVE + 'short'.length + preview.length).toLocaleString());

    await send();
    expect(sentBody(fetching)['log']).toBe(preview);
  });

  it('trims the logs to fit - the visit log first, the run\'s details kept - and then it can be sent', async () => {
    const fetching = answering(201, { ok: true, number: 8, url: 'https://github.com/o/r/issues/8' });
    const long = Array.from({ length: 1500 }, (_, i) => `line ${i} ${'x'.repeat(40)}`);
    TestBed.inject(Library).store.set(storeWith({ 'runs/20261020T100000Z-aaaa1111.json': record({ log: long }) }));
    for (let i = 0; i < 800; i++) TestBed.inject(VisitLog).note(`step ${i} ${'z'.repeat(40)}`);
    await make();
    await openForm();
    await fill('bug', 'm'.repeat(3000));
    await tickLog();
    const visit = element.querySelector('input[name="attachVisit"]') as HTMLInputElement;
    visit.checked = true;
    visit.dispatchEvent(new Event('change'));
    await settle();
    expect(sendButton().disabled).toBe(true);

    (element.querySelector('button.trim-to-fit') as HTMLButtonElement).click();
    await settle();

    expect(element.querySelector('.too-long')).toBeNull();
    expect(sendButton().disabled).toBe(false);
    expect(element.querySelector('.visit-cut')?.textContent).toContain('trimmed to fit');
    const runLog = element.querySelector('details.log:not(.visit) pre')?.textContent ?? '';
    expect(runLog.startsWith('# Quick scan\nStatus:')).toBe(true);
    expect(runLog).toContain('line 1499');

    await send();
    const sent = sentBody(fetching);
    expect(issueLength('m'.repeat(3000), String(sent['log']), String(sent['visit']))).toBeLessThanOrEqual(ISSUE_BODY_LIMIT);
    expect(String(sent['log']).startsWith('# Quick scan')).toBe(true);
    expect(String(sent['visit'])).toContain('step 799');
  });

  it('undoes trim to fit, and moves between amounts without losing a line', async () => {
    const long = Array.from({ length: 1500 }, (_, i) => `line ${i} ${'x'.repeat(40)}`);
    TestBed.inject(Library).store.set(storeWith({ 'runs/20261020T100000Z-aaaa1111.json': record({ log: long }) }));
    for (let i = 0; i < 800; i++) TestBed.inject(VisitLog).note(`step ${i} ${'z'.repeat(40)}`);
    await make();
    await openForm();
    await fill('bug', 'm'.repeat(3000));
    await tickLog();
    const visit = element.querySelector('input[name="attachVisit"]') as HTMLInputElement;
    visit.checked = true;
    visit.dispatchEvent(new Event('change'));
    await settle();
    const runLog = () => element.querySelector('details.log:not(.visit) pre')?.textContent ?? '';
    const visitLog = () => element.querySelector('details.log.visit pre')?.textContent ?? '';
    const before = [runLog(), visitLog()];

    (element.querySelector('button.trim-to-fit') as HTMLButtonElement).click();
    await settle();
    expect(visitLog().length).toBeLessThan(before[1].length);
    (element.querySelector('button.undo-trim') as HTMLButtonElement).click();
    await settle();
    expect([runLog(), visitLog()]).toEqual(before);
    expect(element.querySelector('button.undo-trim')).toBeNull();

    const pick = element.querySelector<HTMLSelectElement>('select[name="logAmount"]')!;
    for (const amount of ['100', '1000', 'most']) {
      pick.value = amount;
      pick.dispatchEvent(new Event('change'));
      await settle();
    }
    expect(runLog()).toBe(before[0]);
    pick.value = '1000';
    pick.dispatchEvent(new Event('change'));
    await settle();
    expect(runLog()).toContain('line 500 ');
  });

  it('takes the visit log once, as the form opens: what is previewed is what is sent', async () => {
    const fetching = answering(201, { ok: true, number: 9, url: 'https://github.com/o/r/issues/9' });
    const log = TestBed.inject(VisitLog);
    log.note('before the form opened');
    await make();
    await openForm();
    await fill('general', 'Hi');
    const visit = element.querySelector('input[name="attachVisit"]') as HTMLInputElement;
    visit.checked = true;
    visit.dispatchEvent(new Event('change'));
    await settle();
    log.note('after the form opened');
    await settle();
    const preview = element.querySelector('details.log.visit pre')?.textContent ?? '';
    expect(preview).toContain('before the form opened');
    expect(preview).not.toContain('after the form opened');

    await send();
    expect(sentBody(fetching)['visit']).toBe(preview);
  });

  it('attaches only the most recent part of a long visit log, and says so', async () => {
    const fetching = answering(201, { ok: true, number: 5, url: 'https://github.com/o/r/issues/5' });
    const visit = TestBed.inject(VisitLog);
    for (let i = 0; i < 1000; i++) visit.note(`step ${i} ${'z'.repeat(40)}`);
    await make();
    await openForm();
    await fill('general', 'Hi');
    const box = element.querySelector('input[name="attachVisit"]') as HTMLInputElement;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    await settle();

    expect(element.querySelector('.visit-cut')?.textContent).toContain('most recent part');
    expect(element.querySelector('.visit-cut')?.textContent).toContain('User settings');
    await send();
    const sent = String(sentBody(fetching)['visit']);
    expect(sent.length).toBeLessThanOrEqual(VISIT_ATTACH_LIMIT);
    expect(sent.startsWith(VISIT_CUT_NOTE)).toBe(true);
    expect(sent).toContain('step 999');
    expect(sent).not.toContain('step 0 ');
  });

  it('says so when the library has no run log to attach, and does not send without one', async () => {
    TestBed.inject(Library).store.set(storeWith({}));
    await make();
    await openForm();
    await fill('general', 'Hi');

    await tickLog();

    expect(element.textContent).toContain('no run log in this library');
    expect(sendButton().disabled).toBe(true);
  });
});

describe('newestPart', () => {
  it('keeps a short log whole, and a long one to its last whole lines', () => {
    expect(newestPart('a\nb', 100)).toEqual({ text: 'a\nb', cut: false });
    const long = Array.from({ length: 100 }, (_, i) => `line ${i}`).join('\n');
    const part = newestPart(long, 200);
    expect(part.cut).toBe(true);
    expect(part.text.length).toBeLessThanOrEqual(200);
    expect(part.text.split('\n')[1]).toMatch(/^line \d+$/);
    expect(part.text.endsWith('line 99')).toBe(true);
  });
});

describe('issueLength', () => {
  it('adds up the message, both logs and the reserve, against GitHub\'s limit', () => {
    expect(issueLength('hi', 'l'.repeat(60000), '')).toBe(ISSUE_RESERVE + 60002);
    expect(issueLength('m'.repeat(4000), 'l'.repeat(60000), '') > ISSUE_BODY_LIMIT).toBe(false);
    // a full message and a full run log are already over, once the reserve is kept
    expect(issueLength('m'.repeat(5000), 'l'.repeat(60000), '') > ISSUE_BODY_LIMIT).toBe(true);
    expect(ISSUE_BODY_LIMIT).toBe(65536);
  });
});

describe('logExcerpt', () => {
  const text = Array.from({ length: 10 }, (_, i) => `line ${i}`).join('\n');
  it('keeps the last lines asked for, saying earlier ones went', () => {
    expect(logExcerpt(text, 3, 1000, 'NOTE')).toEqual({ text: 'NOTE\nline 7\nline 8\nline 9', cut: true });
    expect(logExcerpt(text, 100, 1000, 'NOTE')).toEqual({ text, cut: false });
  });
  it('then keeps them to the room there is, from a whole line', () => {
    const part = logExcerpt(text, 'most', 25, 'NOTE');
    expect(part.cut).toBe(true);
    expect(part.text.length).toBeLessThanOrEqual(25);
    expect(part.text.endsWith('line 9')).toBe(true);
  });
});

describe('runSummary', () => {
  it('says what the run was and how it went, as History does', () => {
    const lines = runSummary({
      actionName: 'Full scan', status: 'partial', started: '2026-10-20T10:00:00+00:00', finished: '2026-10-20T11:00:00+00:00',
      filetypes: ['JSON', 'HTML'], reindexed: ['1', '2'], downloaded: ['1'], updated: [],
      failures: [{ id: '3', link: '', error: 'gone' }], skipped: [{ id: '4', link: '', error: 'series' }],
      log: ['a', 'b'], logTrimmed: 40,
    });
    expect(lines[0]).toBe('# Full scan');
    expect(lines).toContain('Status: partial');
    expect(lines).toContain('Finished: 2026-10-20T11:00:00+00:00');
    expect(lines).toContain('File types: JSON, HTML');
    expect(lines).toContain('Re-indexed 2, downloaded 1, updated 0');
    expect(lines).toContain('Issues: 1 could not be downloaded; 1 bookmarks that are not works');
    expect(lines).toContain('Log: 2 lines (40 earlier lines dropped by the run itself)');
  });
});

describe('failureReason', () => {
  it('names a timeout, an unreachable service, and passes the service\'s own words on', () => {
    expect(failureReason(new DOMException('t', 'TimeoutError'))).toContain('took too long');
    expect(failureReason(new TypeError('Failed to fetch'))).toContain('could not be reached');
    expect(failureReason(new Error('the message is empty'))).toBe('the message is empty');
  });
});

describe('redactLog', () => {
  it('takes out every username given, in any case, longest first', () => {
    expect(redactLog('Reader and reader and ReaderTwo', ['Reader', 'readertwo', ''])).toBe(
      `${USERNAME_REMOVED} and ${USERNAME_REMOVED} and ${USERNAME_REMOVED}`,
    );
  });

  it('treats a username as text, not a pattern', () => {
    expect(redactLog('a.b and axb', ['a.b'])).toBe(`${USERNAME_REMOVED} and axb`);
  });

  it('takes out anything that looks like a password', () => {
    expect(redactLog('password=hunter2 {"password": "x"}', [])).toBe(
      'password=[removed] {"password": [removed]}',
    );
  });

  it('takes out IP addresses, v4 and v6, and leaves times of day and versions alone', () => {
    expect(redactLog('from 203.0.113.7 and 2001:db8:85a3:0:0:8a2e:370:7334 and fe80::1', [])).toBe(
      'from [IP address removed] and [IP address removed] and [IP address removed]',
    );
    expect(redactLog('[2026-11-01 09:30:00 UTC] version 1.4.12', [])).toBe(
      '[2026-11-01 09:30:00 UTC] version 1.4.12',
    );
  });

  it('takes out email addresses', () => {
    expect(redactLog('mail me@example.com now', [])).toBe('mail [email removed] now');
  });

  it('takes out every file path whole, and leaves AO3 links and library names alone', () => {
    const log = [
      'could not save C:\\Users\\Jo Smith\\My Library\\works\\1 A.html: denied',
      'wrote /home/jo/lib/works/2 B.pdf',
      'copied \\\\nas\\share\\x.epub',
      'opened file:///C:/x.html',
      'see https://archiveofourown.org/works/123 and works/3 C - D 2026-10-01.html, page 3/80',
    ].join('\n');
    expect(redactLog(log, []).split('\n')).toEqual([
      `could not save ${PATH_REMOVED}: denied`,
      `wrote ${PATH_REMOVED}`,
      `copied ${PATH_REMOVED}`,
      `opened ${PATH_REMOVED}`,
      'see https://archiveofourown.org/works/123 and works/3 C - D 2026-10-01.html, page 3/80',
    ]);
  });

  it('takes out the AO3 time zone, but never UTC', () => {
    expect(redactLog("AO3's dates are read as dates in Australia/Brisbane", [], ['Australia/Brisbane'])).toBe(
      `AO3's dates are read as dates in ${ZONE_REMOVED}`,
    );
    expect(redactLog('read as dates in UTC', [], ['UTC'])).toBe('read as dates in UTC');
  });
});

describe('readLatestLog', () => {
  it('reads the newest run record, by name', async () => {
    const latest = await readLatestLog(
      storeWith({ 'runs/2026-10-20T1.json': record(), 'runs/2026-09-01T1.json': record({ actionName: 'Old' }) }),
    );
    expect(latest?.actionName).toBe('Quick scan');
    expect(latest?.username).toBe('ReaderName');
  });

  it('answers nothing for a library with no runs or a record that will not read', async () => {
    expect(await readLatestLog(storeWith({}))).toBeNull();
    expect(await readLatestLog(storeWith({ 'runs/x.json': 'not json' }))).toBeNull();
  });
});
