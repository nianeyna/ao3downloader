import { ComponentFixture, TestBed } from '@angular/core/testing';
import { misnamedFiles } from './renames';
import { ImportDialog } from './import-dialog';
import { DatingResult, FoundFile, FoundWork, ImportRequest, SwapLeftover, swapLeftovers, unindexedWorks } from './imports';
import { Jobs } from './jobs';
import { VisitLog } from './visit-log';
import { Library } from './library';
import { DuplicateGroup, IMPORT_EXCLUDED_FILE, LibraryImports, duplicateGroups } from './imports';
import { Bookmark } from './bookmarks';
import { LibraryStore } from './library-store';
import { ChimePlayer } from './chime';

class MemoryStore implements LibraryStore {
  readonly label = 'memory';
  readonly renamed: [string, string][] = [];
  /** renames that fail, by the path they come from */
  readonly refuse = new Set<string>();
  /** renames held until let go, to look at the page while they run */
  hold: Promise<void> | null = null;
  async check() {}
  /** what `list` answers: the files already in the library */
  listed: string[] = [];
  async list() {
    return this.listed;
  }
  readonly written = new Map<string, string>();
  async read(path: string) {
    return this.written.get(path) ?? null;
  }
  async write(path: string, body: Response) {
    const text = await body.text();
    this.written.set(path, text);
    return text.length;
  }
  async size() {
    return null;
  }
  /** when each file last changed, by path; one not here cannot say */
  readonly changed = new Map<string, number>();
  async modified(path: string) {
    return this.changed.get(path) ?? null;
  }
  readonly deleted: string[] = [];
  async delete(path: string) {
    if (this.refuse.has(path)) throw new Error('refused');
    this.deleted.push(path);
  }
  async rename(from: string, to: string) {
    if (this.hold) await this.hold;
    if (this.refuse.has(from)) throw new Error(`${to} is already there`);
    this.renamed.push([from, to]);
  }
  async mkdir() {}
}

/** the helper's naming, standing in: a file of an indexed work gets that entry's name */
class FakeJobs extends Jobs {
  asked: unknown[] = [];
  override async fileNames(files: readonly { file: { name: string }; date: string; record?: object; parts?: object }[]) {
    this.asked.push(files);
    return files.map((x) => {
      const record = x.record as Bookmark | undefined;
      const parts = x.parts as { worknum: string; title: string; author: string } | undefined;
      const ext = x.file.name.slice(x.file.name.lastIndexOf('.'));
      const date = x.date ? ` ${x.date}` : '';
      if (record) return `${record.id} ${record.title} - ${record.authors?.[0]}${date}${ext}`;
      return parts ? `${parts.worknum} ${parts.title} - ${parts.author}${date}${ext}` : '';
    });
  }
}

let fixture: ComponentFixture<ImportDialog>;
let element: HTMLElement;
let store: MemoryStore;
let jobs: FakeJobs;
let closed: (DatingResult | null)[];
let started: { request: ImportRequest; dated: DatingResult | null }[];

const SOME = unindexedWorks(
  ['works/1 A - B 2024-01-01.html', 'works/2 C - D.html', 'works/2 C - D.pdf', 'works/3 E - F.epub'],
  new Set(),
);
const ALL_DATED = unindexedWorks(['works/1 A - B 2024-01-01.html'], new Set());
const INDEXED_UNDATED: FoundFile[] = [
  { id: '7', path: 'works/7 old name.html', name: '7 old name.html', format: 'html', date: '' },
];

beforeEach(() => {
  jobs = new FakeJobs();
  TestBed.configureTestingModule({ providers: [{ provide: Jobs, useValue: jobs }] });
});

async function open(
  works: FoundWork[] = SOME,
  busy = false,
  elsewhere: FoundFile[] = [],
  duplicates: DuplicateGroup[] = [],
) {
  fixture = TestBed.createComponent(ImportDialog);
  store = new MemoryStore();
  fixture.componentRef.setInput('works', works);
  fixture.componentRef.setInput('undatedElsewhere', elsewhere);
  fixture.componentRef.setInput('duplicates', duplicates);
  fixture.componentRef.setInput('store', store);
  fixture.componentRef.setInput('busy', busy);
  closed = [];
  started = [];
  fixture.componentInstance.closed.subscribe((x) => closed.push(x));
  fixture.componentInstance.start.subscribe((x) => started.push(x));
  await fixture.whenStable();
  element = fixture.nativeElement as HTMLElement;
}

function button(text: string): HTMLButtonElement | undefined {
  return Array.from(element.querySelectorAll('button')).find((b) => b.textContent?.trim() === text);
}

function primary(): HTMLButtonElement {
  return element.querySelector<HTMLButtonElement>('footer .button.primary')!;
}

function step(): string {
  return element.querySelector('.dialog')?.getAttribute('data-step') ?? '';
}

async function click(text: string) {
  // the first page's Continue waits for a choice: these walks repair
  if (step() === 'overview' && text === 'Continue') await pick('repair');
  button(text)!.click();
  await settle();
}

async function pick(choice: string) {
  element.querySelector<HTMLInputElement>(`input[name="firstChoice"][value="${choice}"]`)!.click();
  await fixture.whenStable();
}

async function settle() {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await fixture.whenStable();
  }
}

async function type(input: HTMLInputElement, value: string) {
  input.value = value;
  input.dispatchEvent(new Event('input'));
  await fixture.whenStable();
}

function row(path: string): HTMLTableRowElement {
  return element.querySelector<HTMLTableRowElement>(`tr[data-file="${path}"]`)!;
}

function dateBox(path: string): HTMLInputElement {
  return row(path).querySelector<HTMLInputElement>('input[type="date"]')!;
}

function skipBox(path: string): HTMLInputElement {
  return row(path).querySelector<HTMLInputElement>('input[type="checkbox"]')!;
}

/** on the dates page: ticks Skip on every file, then goes on with none dated */
async function skipDates() {
  await click('Skip remaining');
  await click('Skip this step');
}

function rowOrder(): string[] {
  return Array.from(element.querySelectorAll('tr[data-file]')).map((r) => r.getAttribute('data-file')!);
}

describe('ImportDialog', () => {
  // region the overview

  it('opens on an overview that says what was found, and lists nothing yet', async () => {
    await open();
    expect(step()).toBe('overview');
    // work 2's two undated files and work 3's one
    expect(element.querySelector('.overview-undated')?.textContent?.trim()).toBe('3 files have no date');
    expect(element.querySelector('.overview-heading')?.textContent).toContain('Issues found in import:');
    expect(element.querySelector('.overview-undated')?.textContent).toContain(
      'no date',
    );
    expect(element.querySelector('.overview-unindexed')?.textContent).toContain(
      '4 files belong to works that have no index',
    );
    expect(element.querySelector('tr[data-file]')).toBeNull();
    expect(element.textContent).not.toContain('1 A - B');
  });

  it('says only what applies', async () => {
    await open(ALL_DATED);
    expect(element.querySelector('.overview-undated')).toBeNull();
    expect(element.querySelector('.overview-unindexed')?.textContent?.trim()).toBe('1 file belongs to a work that has no index');
  });

  it('goes straight to the index question when no file needs a date', async () => {
    await open(ALL_DATED);
    await click('Continue');
    expect(step()).toBe('index');
  });

  it('goes from the dates to the formats when no work needs an index entry', async () => {
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    expect(step()).toBe('dates');
    await skipDates();
    expect(step()).toBe('formats');
  });

  it('renames and starts nothing while a run is going, and says why', async () => {
    await open(SOME, true);
    expect(element.querySelector('.busy-note')?.textContent).toContain('A run is in progress');
    expect(button('Continue')!.disabled).toBe(true);
  });

  it('asks what to do first, with Repair now ticked to begin with', async () => {
    await open();
    expect(button('Not now')).toBeUndefined();
    expect(element.querySelector('.dont-ask')).toBeNull();
    expect(element.querySelector<HTMLInputElement>('input[name="firstChoice"][value="repair"]')!.checked).toBe(true);
    expect(primary().textContent?.trim()).toBe('Continue');
    expect(primary().disabled).toBe(false);
    const labels = [...element.querySelectorAll('input[name="firstChoice"]')].map(
      (x) => x.closest('label')!.querySelector('span')!.childNodes[0].textContent!.trim(),
    );
    expect(labels).toEqual([
      'Repair now (recommended)',
      'Not now, remind me again next time I open my library',
      'No, do not ask me again for these files',
      'No, never ask me again',
    ]);

    for (const [choice, text] of [['repair', 'Continue'], ['later', 'Remind me later'], ['exclude', 'Done'], ['never', 'Done']]) {
      await pick(choice);
      expect(primary().disabled).toBe(false);
      expect(primary().textContent?.trim()).toBe(text);
    }
  });

  it('closes on Remind me later, having changed nothing', async () => {
    await open();
    await pick('later');
    await click('Remind me later');
    expect(closed).toEqual([null]);
    expect(store.renamed).toEqual([]);
    expect(store.written.size).toBe(0);
  });

  it('puts every file found on the files list on No, do not ask me again', async () => {
    await open(SOME, false, INDEXED_UNDATED);
    TestBed.inject(Library).store.set(store);
    const imports = TestBed.inject(LibraryImports);
    await pick('exclude');
    await click('Done');

    expect(closed).toEqual([null]);
    const written = JSON.parse(store.written.get(IMPORT_EXCLUDED_FILE)!);
    expect(written.excluded.map((x: { id: string; kind: string; files: string[] }) => [x.id, x.kind, x.files])).toEqual([
      ['1', 'files', ['1 A - B 2024-01-01.html']],
      ['2', 'files', ['2 C - D.html', '2 C - D.pdf']],
      ['3', 'files', ['3 E - F.epub']],
      ['7', 'files', ['7 old name.html']],
    ]);
    expect(imports.hasIssues()).toBe(false);
  });

  it('turns itself off for good on No, never ask me again', async () => {
    await open();
    const changed: boolean[] = [];
    fixture.componentInstance.askAgainChanged.subscribe((x) => changed.push(x));
    await pick('never');
    await click('Done');
    expect(changed).toEqual([false]);
    expect(closed).toEqual([null]);
  });

  it('cannot start repairing while a run is going, but can still be put off', async () => {
    await open(SOME, true);
    await pick('repair');
    expect(primary().disabled).toBe(true);
    await pick('later');
    expect(primary().disabled).toBe(false);
  });

  it('never says what comes after the formats page', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue');
    expect(element.textContent).not.toContain('Next you log in to AO3');
  });

  // endregion

  // region duplicates

  const DUPES = duplicateGroups([
    'works/7 Fic - W 2024-01-01.html',
    'works/7 fic old copy 2023-05-05.htm',
    'works/7 Fic - W 2024-01-01.pdf',
    'works/7 Fic - W (3 Feb 2024).pdf',
    'works/8 One 2022-02-02.epub',
    'works/8 Two 2022-03-03.epub',
    'works/8 Three 2021-01-01.epub',
  ]);

  function groupRow(key: string): HTMLTableRowElement {
    return element.querySelector<HTMLTableRowElement>(`tr[data-group="${key}"]`)!;
  }

  async function answerUndecided(how: string, opts: { keep?: string; others?: boolean } = {}) {
    const ask = element.querySelector('.undecided-ask')!;
    ask.querySelector<HTMLInputElement>(`input[name="askHow"][aria-label="${how}"]`)?.click();
    await fixture.whenStable();
    if (opts.keep) {
      ask.querySelector<HTMLInputElement>(`input[name="askPick"][aria-label="Keep ${opts.keep}"]`)!.click();
      await fixture.whenStable();
    }
    if (opts.others) {
      element.querySelector<HTMLButtonElement>('.answer-all')!.click();
      await fixture.whenStable();
    } else await click('Apply and carry on');
  }

  async function chooseIn(key: string, choice: string) {
    const select = groupRow(key).querySelector('select')!;
    select.value = choice;
    select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
  }

  it('lists the issues as bullets under one heading: duplicates, then dates, then index', async () => {
    await open(SOME, false, [], DUPES);
    expect(element.querySelector('.overview-heading')?.textContent?.trim()).toBe('Issues found in import:');
    expect([...element.querySelectorAll('.overview-issues li')].map((li) => li.textContent?.trim())).toEqual([
      '7 files are duplicates',
      '3 files have no date',
      '4 files belong to works that have no index',
    ]);
  });

  it('lists each work and format with more than one file, every file under it, kept to the most recent to begin with', async () => {
    await open([], false, [], DUPES);
    expect(element.querySelector('.overview-duplicates')?.textContent?.trim()).toBe('7 files are duplicates');
    await click('Continue');
    expect(step()).toBe('duplicates');
    expect([...element.querySelectorAll('tr[data-group]')].map((r) => r.getAttribute('data-group'))).toEqual([
      '7:html', '7:pdf', '8:epub',
    ]);
    expect(groupRow('8:epub').querySelectorAll('li')).toHaveLength(3);
    for (const key of ['7:html', '7:pdf', '8:epub']) {
      expect(groupRow(key).querySelector('select')!.value).toBe('recent');
    }
  });

  it('never shows the duplicates page when there are none', async () => {
    await open();
    await click('Continue');
    expect(step()).toBe('dates');
  });

  it('sets every row at once from the buttons at the top, each still changeable', async () => {
    await open([], false, [], DUPES);
    await click('Continue');
    expect(element.querySelector('select option[value="all"]')).toBeNull();
    for (const [label, value] of [['Mark all as Keep most recent', 'recent'],
                                  ["Mark all as I'll choose myself", 'choose'], ['Mark all as Skip', 'skip']]) {
      await click(label);
      expect([...element.querySelectorAll('tr[data-group] select')].map((x) => (x as HTMLSelectElement).value))
        .toEqual([value, value, value]);
    }
    await chooseIn('8:epub', 'recent');
    expect(groupRow('7:html').querySelector('select')!.value).toBe('skip');
  });

  it('keeps the most recent by the date in each name, removing the rest on a page with a bar', async () => {
    await open([], false, [], DUPES);
    await click('Continue');
    await chooseIn('7:pdf', 'skip');
    expect(groupRow('7:html').querySelector('li.newest')?.textContent).toContain('7 Fic - W 2024-01-01.html');
    await click('Continue');
    await settle();

    expect(step()).toBe('removing');
    expect(store.deleted.sort()).toEqual([
      'works/7 fic old copy 2023-05-05.htm',
      'works/8 One 2022-02-02.epub',
      'works/8 Three 2021-01-01.epub',
    ]);
    expect(element.querySelector('.removed-said')?.textContent).toContain('Removed 3 files');
    expect(element.querySelector('[role="progressbar"]')).toBeTruthy();
  });

  it('deletes nothing for a group whose newest cannot be told, and says so', async () => {
    await open([], false, [], DUPES);
    await click('Continue');
    await chooseIn('7:html', 'skip');
    await chooseIn('8:epub', 'skip');
    expect(groupRow('7:pdf').querySelector('.undecided-note')?.textContent).toContain("Can't tell which is newest");
    await click('Continue');
    await settle();
    // the removing page stops and asks; keeping all deletes nothing
    expect(element.querySelector('.undecided-ask')?.getAttribute('data-group')).toBe('7:pdf');
    await answerUndecided('Keep all of them');
    expect(store.deleted).toEqual([]);
    expect(element.querySelector('details.undecided summary')?.textContent).toContain('could not tell which file is most recent');
  });

  it('dings when the removing page stops to ask, and only then', async () => {
    const played: string[] = [];
    TestBed.inject(ChimePlayer).play = () => played.push('ding');
    await open([], false, [], DUPES);
    await click('Continue');
    await chooseIn('7:html', 'skip');
    await chooseIn('8:epub', 'skip');
    expect(played).toEqual([]);

    await click('Continue');
    await settle();
    expect(element.querySelector('.undecided-ask')).not.toBeNull();
    expect(played).toEqual(['ding']);
    await answerUndecided('Keep all of them');
    expect(played).toEqual(['ding']);
  });

  it('says Skip this step with every row skipped, Choose which to keep with one to choose, else Continue', async () => {
    await open([], false, [], DUPES);
    await click('Continue');
    expect(primary().textContent?.trim()).toBe('Continue');
    await click('Mark all as Skip');
    expect(primary().textContent?.trim()).toBe('Skip this step');
    await chooseIn('8:epub', 'recent');
    expect(primary().textContent?.trim()).toBe('Continue');
    await chooseIn('7:html', 'choose');
    expect(primary().textContent?.trim()).toBe('Choose which to keep');
  });

  it('keeps every skipped file, and asks again next time unless told not to', async () => {
    await open([], false, [], DUPES);
    TestBed.inject(Library).store.set(store);
    await click('Continue');
    const box = element.querySelector<HTMLInputElement>('input[name="rememberSkipped"]')!;
    expect(box.closest('label')!.textContent).toContain("Don't ask this again for skipped files");
    expect(box.closest('label')!.textContent).toContain('import-excluded.json');
    await click('Mark all as Skip');
    await click('Skip this step');
    await settle();
    expect(store.deleted).toEqual([]);
    expect(store.written.has(IMPORT_EXCLUDED_FILE)).toBe(false);
  });

  it("puts the list's skipped groups on the duplicates list when the box is ticked, and a sifted one told not to ask again", async () => {
    await open([], false, [], DUPES);
    TestBed.inject(Library).store.set(store);
    await click('Continue');
    await chooseIn('7:pdf', 'skip');
    await chooseIn('8:epub', 'choose');
    element.querySelector<HTMLInputElement>('input[name="rememberSkipped"]')!.click();
    await fixture.whenStable();
    await click('Choose which to keep');
    await skipThisOne(true);
    await click('Continue');
    await settle();
    const written = JSON.parse(store.written.get(IMPORT_EXCLUDED_FILE)!);
    expect(written.excluded.map((x: { id: string; kind: string; format: string }) => [x.id, x.kind, x.format])).toEqual([
      ['7', 'duplicates', 'pdf'],
      ['8', 'duplicates', 'epub'],
    ]);
    expect(written.excluded[1].files).toEqual(['8 One 2022-02-02.epub', '8 Three 2021-01-01.epub', '8 Two 2022-03-03.epub']);
    // the html's most recent kept, the older copy removed
    expect(store.deleted).toEqual(['works/7 fic old copy 2023-05-05.htm']);
  });

  const groupShown = () => element.querySelector('.choose')!.getAttribute('data-group');
  const radios = () => [...element.querySelectorAll<HTMLInputElement>('.choose-list li:not(.skip-this) input[type="radio"]')];
  async function skipThisOne(remember = false) {
    element.querySelector<HTMLInputElement>(remember ? '.skip-this.remember input' : '.skip-this:not(.remember) input')!.click();
    await fixture.whenStable();
    // the last one to sort shows the done note at once, with no entries left to move to
    if (button('Next entry')) await click('Next entry');
  }

  async function sortRest(choice: string) {
    element.querySelector<HTMLDetailsElement>('details.sort-rest')!.open = true;
    element.querySelector<HTMLInputElement>(`details.sort-rest input[aria-label="${choice}"]`)!.click();
    await fixture.whenStable();
    await click('Apply to the rest');
  }

  async function toSifting() {
    await open([], false, [], DUPES);
    await click('Continue');
    await click("Mark all as I'll choose myself");
    await click('Choose which to keep');
  }

  it('sifts one at a time, the top file picked to begin with, Continue held until every one is sorted', async () => {
    await toSifting();
    expect(step()).toBe('choose');
    expect(groupShown()).toBe('7:html');
    expect(element.textContent).toContain('1 of 3');
    // the most recent, at the top, is picked - but nothing counts as sorted yet
    expect(radios().map((r) => r.checked)).toEqual([true, false]);
    expect(element.textContent).toContain('3 still to sort');
    expect(primary().disabled).toBe(true);
    expect(button('Keep most recent for this one')).toBeUndefined();
    // the two skips are the last radios, below every file; previous and next entry are below that
    const items = [...element.querySelectorAll('.choose-list li')];
    expect(items.slice(-2).map((li) => li.textContent?.trim())).toEqual([
      'Skip for now', "Skip, and don't ask me again for this file",
    ]);
    expect(element.textContent).not.toContain('Or, skip this one');
    expect(button('Skip this one')).toBeUndefined();
    const nav = element.querySelector('.sift-nav')!;
    expect([...nav.querySelectorAll('button')].map((b) => b.textContent?.trim())).toEqual([
      'Previous entry', 'Next entry',
    ]);
    expect(element.querySelector('.choose-list')!.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const footer = element.querySelector('footer')!;
    expect([...footer.querySelectorAll(':scope > button')].map((b) => b.textContent?.trim())).toEqual(['Back', 'Continue']);
    // the rest sorted at once from the footer, above its buttons, closed to begin with
    const bulk = footer.querySelector<HTMLDetailsElement>(':scope > details.sort-rest')!;
    expect(footer.firstElementChild).toBe(bulk);
    expect(bulk.open).toBe(false);
    expect(bulk.querySelector('summary')!.textContent?.trim()).toBe('Sort any remaining in bulk');
    expect([...bulk.querySelectorAll('input[type="radio"]')].map((r) => r.getAttribute('aria-label'))).toEqual([
      'Skip for now', "Skip, don't ask again", 'Keep most recent',
    ]);
    expect(nav.compareDocumentPosition(bulk) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(button('Apply to the rest')!.disabled).toBe(true);
  });

  it('lists the files to choose from most recent first, undated last', async () => {
    await toSifting();
    await click('Next entry');
    await click('Next entry');
    expect(groupShown()).toBe('8:epub');
    expect(radios().map((r) => r.getAttribute('aria-label'))).toEqual([
      'Keep 8 Two 2022-03-03.epub',
      'Keep 8 One 2022-02-02.epub',
      'Keep 8 Three 2021-01-01.epub',
    ]);
    await click('Previous entry');
    expect(radios().map((r) => r.getAttribute('aria-label'))).toEqual([
      'Keep 7 Fic - W (3 Feb 2024).pdf',
      'Keep 7 Fic - W 2024-01-01.pdf',
    ]);
  });

  it('writes to no exclusion list and refreshes nothing as a sandbox, saying what it would have', async () => {
    await open(ALL_DATED, false, [], DUPES);
    fixture.componentRef.setInput('sandbox', true);
    TestBed.inject(Library).store.set(store);
    const noted: string[] = [];
    fixture.componentInstance.sandboxNoted.subscribe((x) => noted.push(x));
    await click('Continue');
    await click('Mark all as Skip');
    element.querySelector<HTMLInputElement>('input[name="rememberSkipped"]')!.click();
    await fixture.whenStable();
    await click('Skip this step');
    await settle();
    expect(store.written.size).toBe(0);
    expect(noted).toEqual(['duplicates list: 7:html, 7:pdf, 8:epub']);
  });

  it('takes the picked file on Next entry, and finishes with a done note once the last is sorted', async () => {
    await toSifting();
    radios()[1].click();
    await fixture.whenStable();
    await click('Next entry');
    expect(groupShown()).toBe('7:pdf');
    await skipThisOne();
    expect(groupShown()).toBe('8:epub');
    await click('Previous entry');
    expect(groupShown()).toBe('7:pdf');
    await click('Next entry');
    // the last one: Next entry keeps the top file, and there is nothing left to sort
    await click('Next entry');

    expect(element.querySelector('.sift-done')?.textContent).toContain('You are done - no more to sort');
    expect(element.querySelector('.sift-nav')).toBeNull();
    expect(element.querySelector('details.sort-rest')).toBeNull();
    expect(primary().disabled).toBe(false);
    await click('Continue');
    await settle();
    expect(store.deleted.sort()).toEqual([
      'works/7 Fic - W 2024-01-01.html',
      'works/8 One 2022-02-02.epub',
      'works/8 Three 2021-01-01.epub',
    ]);
  });

  it('goes back to the list, and coming forward opens on the first still to sort, new ones at the end', async () => {
    const more = duplicateGroups([...DUPES.flatMap((g) => g.files.map((f) => f.path)), 'works/9 a 2020-01-01.mobi', 'works/9 b 2021-01-01.mobi']);
    await open([], false, [], more);
    await click('Continue');
    await chooseIn('7:html', 'choose');
    await chooseIn('7:pdf', 'choose');
    await chooseIn('8:epub', 'choose');
    await click('Choose which to keep');
    await skipThisOne();
    expect(groupShown()).toBe('7:pdf');

    await click('Back');
    expect(step()).toBe('duplicates');
    // the list keeps to its own choices: nothing about what sifting decided
    expect(groupRow('7:html').textContent).not.toContain('Sorted:');
    await chooseIn('9:mobi', 'choose');
    await click('Choose which to keep');
    expect(groupShown()).toBe('7:pdf');
    expect(element.textContent).toContain('2 of 4');
    await click('Next entry');
    await click('Next entry');
    expect(groupShown()).toBe('9:mobi');
  });

  it('keeps what was decided for a group taken off and put back, in its own place', async () => {
    await toSifting();
    radios()[1].click();
    await fixture.whenStable();
    await click('Back');
    // decided, then changed to Skip on the list: out of the sift
    await chooseIn('7:html', 'skip');
    await click('Choose which to keep');
    expect(groupShown()).toBe('7:pdf');
    expect(element.textContent).toContain('1 of 2');

    // changed back: in its first place again, still decided as before
    await click('Back');
    await chooseIn('7:html', 'choose');
    await click('Choose which to keep');
    expect(groupShown()).toBe('7:pdf');
    expect(element.textContent).toContain('2 of 3');
    await click('Previous entry');
    expect(groupShown()).toBe('7:html');
    expect(radios().map((r) => r.checked)).toEqual([false, true]);
  });

  it('leaves the rest as they are on Skip for now in bulk, keeping what was sorted, and goes on only on Continue', async () => {
    await toSifting();
    TestBed.inject(Library).store.set(store);
    await click('Next entry');
    await sortRest('Skip for now');
    expect(step()).toBe('choose');
    expect(element.querySelector('.sift-done')).toBeTruthy();
    await click('Continue');
    await settle();
    expect(store.deleted).toEqual(['works/7 fic old copy 2023-05-05.htm']);
    expect(store.written.has(IMPORT_EXCLUDED_FILE)).toBe(false);
  });

  it("puts the rest on the duplicates list on Skip, don't ask again in bulk", async () => {
    await toSifting();
    TestBed.inject(Library).store.set(store);
    await click('Next entry');
    await sortRest("Skip, don't ask again");
    await click('Continue');
    await settle();
    const written = JSON.parse(store.written.get(IMPORT_EXCLUDED_FILE)!);
    expect(written.excluded.map((x: { id: string; format: string }) => `${x.id}:${x.format}`)).toEqual(['7:pdf', '8:epub']);
  });

  it('gives the rest their most recent on Keep most recent in bulk', async () => {
    await toSifting();
    await sortRest('Keep most recent');
    await click('Continue');
    await settle();
    await answerUndecided('Keep all of them');
    expect(store.deleted.sort()).toEqual([
      'works/7 fic old copy 2023-05-05.htm',
      'works/8 One 2022-02-02.epub',
      'works/8 Three 2021-01-01.epub',
    ]);
    // 7:pdf cannot be told, so it is left and said
    expect(element.querySelector('details.undecided')).toBeTruthy();
  });

  it('never offers a removed file for dating afterwards', async () => {
    const undated = duplicateGroups(['works/9 Copy - W.html', 'works/9 Copy - W 2020-01-01.html', 'works/9 Old - W 2019-01-01.html']);
    const works = [{ id: '9', files: undated[0].files }];
    await open(works, false, [], undated);
    await click('Continue');
    await click("Mark all as I'll choose myself");
    await click('Choose which to keep');
    // the most recent dated copy is at the top and picked; Next entry keeps it, and that is all
    const keep = element.querySelector<HTMLInputElement>('input[aria-label="Keep 9 Copy - W 2020-01-01.html"]')!;
    expect(keep.checked).toBe(true);
    await click('Next entry');
    await click('Continue');
    await settle();
    expect(store.deleted.sort()).toEqual(['works/9 Copy - W.html', 'works/9 Old - W 2019-01-01.html']);
    await click('Continue');
    expect(step()).toBe('index');
  });


  // the same date in both names, told apart - or not - by when each file last changed
  const TIED = duplicateGroups(['works/5 Tie - W 2023-03-03.mobi', 'works/5 Tie copy - W 2023-03-03.mobi']);
  const TIED_TIMES = {
    'works/5 Tie - W 2023-03-03.mobi': Date.UTC(2023, 2, 4),
    'works/5 Tie copy - W 2023-03-03.mobi': Date.UTC(2023, 5, 1),
  };

  // one dated the app's way, later than the other's guessed date: certain
  const LATER = duplicateGroups(['works/5 Tie - W 2023-03-03.mobi', 'works/5 Tie - W (1 Feb 2023).mobi']);

  async function openTied(times: Record<string, number>, groups = TIED) {
    await open([], false, [], groups);
    for (const [path, at] of Object.entries(times)) store.changed.set(path, at);
    // the times are asked of the library the window was given
    fixture.componentRef.setInput('store', null);
    await settle();
    fixture.componentRef.setInput('store', store);
    await settle();
  }

  it('breaks a shared newest date by when each file last changed - only a best guess, and still asked about', async () => {
    await openTied(TIED_TIMES);
    await click('Continue');
    await chooseIn('5:mobi', 'recent');
    expect(groupRow('5:mobi').querySelector('.undecided-note')).toBeTruthy();

    await chooseIn('5:mobi', 'choose');
    await click('Choose which to keep');
    // the later-changed file is the top radio, picked - but only our best guess
    expect(radios().map((r) => r.getAttribute('aria-label'))).toEqual([
      'Keep 5 Tie copy - W 2023-03-03.mobi',
      'Keep 5 Tie - W 2023-03-03.mobi',
    ]);
    expect(radios()[0].checked).toBe(true);
    expect(element.querySelector('.top-label')?.textContent?.trim()).toBe("This is our best guess for 'most recent'");
    // the change times are still shown
    expect(element.textContent).toContain('File metadata updated at 1 June 2023');
  });

  it('is sure of a file dated the app\'s way that is later than every other date, guessed or none', async () => {
    await open([], false, [], duplicateGroups(['works/6 A - W 2023-05-05.epub', 'works/6 A - W (4 Apr 2023).epub', 'works/6 A copy.epub']));
    await click('Continue');
    await chooseIn('6:epub', 'recent');
    expect(groupRow('6:epub').querySelector('.undecided-note')).toBeNull();
    await click('Continue');
    await settle();
    // nothing to ask: the certain newest is kept, the rest removed
    expect(element.querySelector('.undecided-ask')).toBeNull();
    expect(store.deleted.sort()).toEqual(['works/6 A - W (4 Apr 2023).epub', 'works/6 A copy.epub']);
  });

  it('stops and asks when a guessed date looks later than the one dated the app\'s way, and a best guess keeps the later', async () => {
    await open([], false, [], duplicateGroups(['works/6 A - W 2023-03-03.epub', 'works/6 A - W (4 Apr 2023).epub']));
    await click('Continue');
    await chooseIn('6:epub', 'recent');
    expect(groupRow('6:epub').querySelector('.undecided-note')).toBeTruthy();
    await click('Continue');
    await settle();
    expect(element.querySelector('.undecided-ask')?.getAttribute('data-group')).toBe('6:epub');
    expect(element.querySelector('.undecided-ask')?.textContent).toContain("we can't tell which of its 2");
    await answerUndecided('Make a best guess');
    expect(store.deleted).toEqual(['works/6 A - W 2023-03-03.epub']);
  });

  it('says above the top file that it is the most recent, and under each its name date and change time', async () => {
    await openTied({ 'works/5 Tie - W 2023-03-03.mobi': Date.UTC(2023, 2, 4) }, LATER);
    await click('Continue');
    await click("Mark all as I'll choose myself");
    await click('Choose which to keep');
    const items = [...element.querySelectorAll('.choose-list li:not(.skip-this)')];
    // the label comes before the file's name
    const top = items[0].querySelector('.top-label')!;
    expect(top.textContent?.trim()).toBe('Most recent');
    expect(top.compareDocumentPosition(items[0].querySelector('.file-name')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(items[1].querySelector('.top-label')).toBeNull();
    const notes = items.map((li) => [...li.querySelectorAll('.file-note')].map((n) => n.textContent?.trim()));
    expect(notes[0][0]).toBe('Filename dated 3 March 2023');
    expect(notes[1][0]).toBe('Filename dated 1 February 2023 (best guess)');
    expect(notes[0][1]).toMatch(/^File metadata updated at \S/);
    expect(notes[0]).toHaveLength(2);
  });

  it('marks a filename date read loosely out of a name as a best guess, and one written the app\'s way not', async () => {
    await open([], false, [], duplicateGroups(['works/6 A - W 2023-03-03.epub', 'works/6 A - W (4 Apr 2023).epub']));
    await click('Continue');
    await click("Mark all as I'll choose myself");
    await click('Choose which to keep');
    const notes = [...element.querySelectorAll('.choose-list li:not(.skip-this)')]
      .map((li) => li.querySelector('.file-note')?.textContent?.trim());
    expect(notes).toEqual(['Filename dated 4 April 2023 (best guess)', 'Filename dated 3 March 2023']);
  });

  it('holds Next entry until a file is picked or the set skipped, when no best guess picks one', async () => {
    // a second set, so the entry buttons stay once the first is sorted
    await open([], false, [], duplicateGroups(['works/6 A.html', 'works/6 B.html', 'works/7 C.html', 'works/7 D.html']));
    await click('Continue');
    await click("Mark all as I'll choose myself");
    await click('Choose which to keep');
    expect(button('Next entry')!.disabled).toBe(true);
    radios()[1].click();
    await fixture.whenStable();
    expect(button('Next entry')!.disabled).toBe(false);
  });

  it('offers no best guess where none can be made, starting on Choose individually', async () => {
    await open([], false, [], duplicateGroups(['works/6 A.html', 'works/6 B.html']));
    await click('Continue');
    await click('Mark all as Keep most recent');
    await click('Continue');
    await settle();
    const ask = element.querySelector('.undecided-ask')!;
    expect(ask.querySelector('.no-guess')).toBeTruthy();
    const guess = ask.querySelector<HTMLInputElement>('input[aria-label="Make a best guess"]')!;
    expect(guess.disabled).toBe(true);
    expect(ask.querySelector<HTMLInputElement>('input[aria-label="Choose individually"]')!.checked).toBe(true);
    // nothing to apply until a file is picked
    expect(button('Apply and carry on')!.disabled).toBe(true);
    await answerUndecided('Keep all of them');
    expect(store.deleted).toEqual([]);
  });

  it('stops again for a set no guess can be made for, after a best guess was applied to all remaining', async () => {
    const groups = duplicateGroups(['works/1 A 2024-01-01.html', 'works/1 A (2 Feb 2024).html',
      'works/2 B.html', 'works/2 B copy.html', 'works/3 C 2024-01-01.html', 'works/3 C (2 Feb 2024).html']);
    await open([], false, [], groups);
    await click('Continue');
    await click('Mark all as Keep most recent');
    await click('Continue');
    await settle();
    expect(element.querySelector('.undecided-ask')?.getAttribute('data-group')).toBe('1:html');
    await answerUndecided('Make a best guess', { others: true });
    await settle();
    // set 2 has no dates and no change times: asked again, saying why
    const ask = element.querySelector('.undecided-ask')!;
    expect(ask.getAttribute('data-group')).toBe('2:html');
    expect(ask.querySelector('.standing-interrupted')).toBeTruthy();
    expect(element.querySelector('.answer-all')).toBeNull();
    await answerUndecided('Keep all of them');
    await settle();
    // set 3 follows the best guess without asking
    expect(element.querySelector('.undecided-ask')).toBeNull();
    expect(store.deleted.sort()).toEqual(['works/1 A 2024-01-01.html', 'works/3 C 2024-01-01.html']);
  });

  it('makes a best guess from when each file last changed when no name has a date', async () => {
    await openTied({ 'works/6 A.html': Date.UTC(2023, 0, 1), 'works/6 B.html': Date.UTC(2023, 5, 1) },
      duplicateGroups(['works/6 A.html', 'works/6 B.html']));
    await click('Continue');
    await click("Mark all as I'll choose myself");
    await click('Choose which to keep');
    expect(radios()[0].getAttribute('aria-label')).toBe('Keep 6 B.html');
    expect(radios()[0].checked).toBe(true);
    expect(element.querySelector('.top-label')?.textContent?.trim()).toBe("This is our best guess for 'most recent'");
  });

  it('picks nothing and labels nothing when neither the names nor the change times tell the files apart', async () => {
    await openTied({});
    await click('Continue');
    await click("Mark all as I'll choose myself");
    await click('Choose which to keep');
    expect(element.querySelector('.sift-unsure')).toBeNull();
    expect(element.querySelector('.top-label')).toBeNull();
    expect(element.textContent).toContain('File metadata updated at: unknown');

    const undated = duplicateGroups(['works/6 A.html', 'works/6 B.html']);
    await open([], false, [], undated);
    await click('Continue');
    await click("Mark all as I'll choose myself");
    await click('Choose which to keep');
    // no date in any name, and no change times: nothing to call most recent, nothing picked
    expect(element.querySelector('.top-label')).toBeNull();
    expect(radios().some((r) => r.checked)).toBe(false);
    expect(element.querySelector('.no-guess')?.textContent).toContain("We can't tell which of these is most recent");
    expect(element.textContent).toContain('No date included in the filename');
  });

  it('puts the files in a pane of their own to scroll through when choosing on the removing page', async () => {
    const many = duplicateGroups(Array.from({ length: 12 }, (_, i) => `works/4 Copy ${i}.html`));
    await open([], false, [], many);
    await click('Continue');
    await click('Mark all as Keep most recent');
    await click('Continue');
    await settle();
    element.querySelector<HTMLInputElement>('input[name="askHow"][aria-label="Choose individually"]')!.click();
    await fixture.whenStable();
    const pane = element.querySelector('.undecided-ask .ask-files')!;
    expect(pane.querySelectorAll('input[name="askPick"]')).toHaveLength(12);
    expect(getComputedStyle(pane).overflowY).toBe('auto');
  });

  it('decides nothing while sifting: every file is still there until the removing page', async () => {
    await toSifting();
    radios()[1].click();
    await fixture.whenStable();
    await click('Next entry');
    await click('Back');
    expect(store.deleted).toEqual([]);
  });

  // three sets marked Keep most recent, none of which can be told
  const UNSURE = duplicateGroups([
    'works/1 A.html', 'works/1 A copy.html',
    'works/2 B.html', 'works/2 B copy.html',
    'works/3 C.html', 'works/3 C copy.html',
  ]);

  async function toUnsureRemoving(wait?: number) {
    await open([], false, [], UNSURE);
    // each copy changed after its original: what a best guess goes by, with no dates in the names
    for (const path of UNSURE.flatMap((g) => g.files.map((f) => f.path))) store.changed.set(path, path.includes('copy') ? 2 : 1);
    fixture.componentRef.setInput('store', null);
    await settle();
    fixture.componentRef.setInput('store', store);
    await settle();
    if (wait !== undefined) fixture.componentRef.setInput('answerWaitMs', wait);
    await click('Continue');
    await click('Mark all as Keep most recent');
    await click('Continue');
    await settle();
  }

  it('pauses the removing bar on a set it cannot tell and asks: choose, best guess or keep all', async () => {
    await toUnsureRemoving();
    expect(step()).toBe('removing');
    expect(element.querySelector('.removing-progress')?.textContent).toContain('waiting for your answer');
    const ask = element.querySelector('.undecided-ask')!;
    expect(ask.getAttribute('data-group')).toBe('1:html');
    expect([...ask.querySelectorAll('input[name="askHow"]')].map((r) => r.getAttribute('aria-label'))).toEqual([
      'Make a best guess', 'Choose individually', 'Keep all of them',
    ]);
    // a best guess is picked to begin with
    expect(ask.querySelector<HTMLInputElement>('input[aria-label="Make a best guess"]')!.checked).toBe(true);
    expect(element.querySelector('.answer-all')!.textContent).toContain('Apply to all remaining (2 more)');
    expect(ask.textContent).toContain('every file of this set is kept');
    // a best guess is picked to begin with, so either button can be pressed at once
    expect(button('Apply and carry on')!.disabled).toBe(false);

    // choosing shows the files as the sifting page does
    await answerUndecided('Choose individually', { keep: '1 A copy.html', others: false });
    expect(store.deleted).toEqual(['works/1 A.html']);
    // asked again for the next
    expect(element.querySelector('.undecided-ask')?.getAttribute('data-group')).toBe('2:html');
    await answerUndecided('Make a best guess', { others: false });
    // best guess: no dates - the file changed most recently
    expect(store.deleted).toContain('works/2 B.html');
    expect(element.querySelector('.undecided-ask')?.getAttribute('data-group')).toBe('3:html');
    // the last one: nothing more to apply it to, so no button for the rest
    expect(element.querySelector('.answer-all')).toBeNull();
    await answerUndecided('Keep all of them');
    await settle();
    expect(store.deleted.sort()).toEqual(['works/1 A.html', 'works/2 B.html']);
    expect(element.querySelector('details.guessed')?.textContent).toContain('2 B copy.html');
    expect(element.querySelector('details.undecided')?.textContent).toContain('Work 3');
  });

  it('follows an answer given for the others without asking again', async () => {
    await toUnsureRemoving();
    await answerUndecided('Make a best guess', { others: true });
    await settle();
    expect(element.querySelector('.undecided-ask')).toBeNull();
    expect(store.deleted.sort()).toEqual(['works/1 A.html', 'works/2 B.html', 'works/3 C.html']);
  });

  it('offers Apply to all remaining for a best guess or keeping all, never for choosing by hand', async () => {
    await toUnsureRemoving();
    const pick = async (how: string) => {
      element.querySelector<HTMLInputElement>(`.undecided-ask input[name="askHow"][aria-label="${how}"]`)!.click();
      await fixture.whenStable();
    };
    expect(element.querySelector('.answer-all')).not.toBeNull();
    await pick('Keep all of them');
    expect(element.querySelector('.answer-all')).not.toBeNull();
    await pick('Choose individually');
    expect(element.querySelector('.answer-all')).toBeNull();

    // chosen by hand, set by set: the next set asks again, with every choice
    await answerUndecided('Choose individually', { keep: '1 A.html' });
    const ask = element.querySelector('.undecided-ask')!;
    expect(ask.getAttribute('data-group')).toBe('2:html');
    expect(ask.querySelectorAll('input[name="askHow"]')).toHaveLength(3);
    expect(store.deleted).toEqual(['works/1 A copy.html']);
  });

  it('keeps every file of a set when no answer comes in time, then asks about the next', async () => {
    await toUnsureRemoving(40);
    expect(element.querySelector('.undecided-ask')?.getAttribute('data-group')).toBe('1:html');
    // each set waits its own time, and each is kept whole when it runs out
    await new Promise((resolve) => setTimeout(resolve, 300));
    await settle();
    expect(element.querySelector('.undecided-ask')).toBeNull();
    expect(store.deleted).toEqual([]);
    const kept = element.querySelector('details.undecided')!.textContent!;
    expect(kept.match(/\(no answer in time\)/g)).toHaveLength(3);
  });

  it('counts only what is left for dating after duplicates are removed', async () => {
    const files = ['works/9 Copy - W.html', 'works/9 Copy - W 2020-01-01.html', 'works/9 Other - W.pdf'];
    const found = unindexedWorks(files, new Set());
    await open(found, false, [], duplicateGroups(files));
    await click('Continue');
    await chooseIn('9:html', 'choose');
    await click('Choose which to keep');
    await click('Next entry');
    await click('Continue');
    await settle();
    expect(store.deleted).toEqual(['works/9 Copy - W.html']);
    await click('Continue');
    // the undated html went; only the pdf is left to date
    expect(rowOrder()).toEqual(['works/9 Other - W.pdf']);
  });

  it('says nothing about how long an import takes on its own pages - the run window does', async () => {
    const files = Array.from({ length: 30 }, (_, i) => `works/${800 + i} Fic ${i} - W 2024-01-01.html`);
    await open(unindexedWorks(files, new Set()));
    await click('Continue');
    expect(step()).toBe('index');
    expect(element.querySelector('.long-run-note')).toBeNull();
    element.querySelector<HTMLInputElement>('input[name="lookup"][value="yes"]')!.click();
    await fixture.whenStable();
    await click('Continue');
    expect(step()).toBe('formats');
    expect(element.querySelector('.long-run-note')).toBeNull();
  });

  it('lists the undated files by name; its button says Skip this step only with every file skipped, else Continue', async () => {
    await open();
    await click('Continue');
    expect(rowOrder()).toEqual(['works/2 C - D.html', 'works/2 C - D.pdf', 'works/3 E - F.epub']);
    expect(primary().textContent?.trim()).toBe('Continue');
    await click('Skip remaining');
    expect(primary().textContent?.trim()).toBe('Skip this step');
    await click('Untick Skip on all');
    expect(primary().textContent?.trim()).toBe('Continue');
    expect(row('works/2 C - D.html').querySelector('td.file-name')!.getAttribute('title')).toBe('2 C - D.html');

    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    expect(primary().textContent?.trim()).toBe('Continue');
  });

  it('renames a dated file on the index list as soon as it is renamed, so its work is not asked about again', async () => {
    const left: FoundFile = { id: '9', path: 'works/9 x.html', name: '9 x.html', format: 'html', date: '', unindexed: true };
    await open([], false, [left]);
    store.written.set(IMPORT_EXCLUDED_FILE, JSON.stringify({
      excluded: [{ id: '9', kind: 'index', files: ['9 x.html', '9 x 2024-01-01.pdf'] }],
    }));
    TestBed.inject(Library).store.set(store);
    await click('Continue');
    await type(dateBox('works/9 x.html'), '2024-02-03');
    await click('Continue');
    await settle();

    // written before the window is closed or anything else is chosen
    expect(step()).toBe('dating');
    expect(closed).toEqual([]);
    const written = JSON.parse(store.written.get(IMPORT_EXCLUDED_FILE)!);
    expect(written.excluded[0].files).toEqual(['9 x 2024-02-03.html', '9 x 2024-01-01.pdf']);
  });

  // region repairing from AO3

  function repairBox(path: string): HTMLInputElement {
    return row(path).querySelector<HTMLInputElement>('input[name="repair"]')!;
  }

  it('offers each undated file a third choice, Repair from AO3, which sets its date and Skip aside', async () => {
    await open();
    await click('Continue');
    expect(element.querySelector('table.dating thead')!.textContent).toContain('Repair from AO3');
    skipBox('works/2 C - D.html').click();
    await fixture.whenStable();
    repairBox('works/2 C - D.html').click();
    await fixture.whenStable();

    expect(repairBox('works/2 C - D.html').checked).toBe(true);
    expect(skipBox('works/2 C - D.html').checked).toBe(false);
    expect(dateBox('works/2 C - D.html').disabled).toBe(true);
    expect(row('works/2 C - D.html').classList).toContain('repaired');
    // a repaired row is answered: it is not among those still needing a date or a tick
    expect(row('works/2 C - D.html').classList).not.toContain('needs-answer');

    skipBox('works/2 C - D.html').click();
    await fixture.whenStable();
    expect(repairBox('works/2 C - D.html').checked).toBe(false);
  });

  it('repairs every row still without a date in one go, leaving the dated ones dated', async () => {
    await open();
    await click('Continue');
    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    await click('Repair remaining from AO3');

    expect(repairBox('works/2 C - D.html').checked).toBe(false);
    expect(repairBox('works/2 C - D.pdf').checked).toBe(true);
    expect(repairBox('works/3 E - F.epub').checked).toBe(true);
    expect(primary().disabled).toBe(false);
    expect(primary().textContent?.trim()).toBe('Continue');
  });

  it('asks how to repair on a page of its own: where AO3 has the work, overwrite and rename to begin with', async () => {
    await open();
    await click('Continue');
    await click('Repair remaining from AO3');
    expect(element.querySelector('input[name="repairAo3"]')).toBeNull();
    await click('Continue');
    expect(step()).toBe('repair');
    const ao3 = (value: string) => element.querySelector<HTMLInputElement>(`input[name="repairAo3"][value="${value}"]`)!;
    expect(ao3('overwrite').checked).toBe(true);
    expect(ao3('rename').closest('label')!.textContent).toContain('Only rename the file');
    expect(ao3('rename').closest('label')!.textContent?.replace(/\s+/g, ' ')).toContain(
      'renamed to include the date AO3 last updated the work. That date may not be the version your file actually holds.');
    expect(ao3('overwrite').closest('label')!.textContent).toContain('Overwrite and rename the file');
  });

  function fallback(value: string): HTMLInputElement {
    return element.querySelector<HTMLInputElement>(`input[name="repairFallback"][value="${value}"]`)!;
  }

  function tickBox(name: string): HTMLInputElement {
    return element.querySelector<HTMLInputElement>(`input[name="${name}"]`)!;
  }

  function answer(name: string): HTMLSelectElement | null {
    return element.querySelector<HTMLSelectElement>(`select[name="${name}"]`);
  }

  async function answerWith(name: string, value: string) {
    const select = answer(name)!;
    select.value = value;
    select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
  }

  it("warns of FicHub's cache, leaves the file as it is to begin with, and shows each choice's questions only under it", async () => {
    await open();
    await click('Continue');
    await click('Repair remaining from AO3');
    await click('Continue');

    expect(element.querySelector('.repair-warning')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'FicHub keeps cached copies, which may be older than the newest version on AO3.');
    expect(fallback('keep').checked).toBe(true);
    expect(fallback('rename').closest('label')!.textContent).toContain('Only rename the file');
    expect(fallback('replace').closest('label')!.textContent).toContain('Overwrite and rename the file');
    // nothing to answer while the file is left as it is
    expect(element.querySelector('.fichub-answers')).toBeNull();

    fallback('rename').click();
    await fixture.whenStable();
    expect(answer('renameOlder')!.closest('label')!.textContent).toContain(
      "Rename files that seem to have an older date than FicHub's?");
    expect(answer('renameUndated')!.closest('label')!.textContent).toContain(
      'Rename files that have no date that can be guessed?');
    expect([answer('renameOlder')!.value, answer('renameUndated')!.value]).toEqual(['yes', 'yes']);
    expect(answer('replaceOlder')).toBeNull();

    fallback('replace').click();
    await fixture.whenStable();
    expect(answer('renameOlder')).toBeNull();
    expect(answer('replaceOlder')!.closest('label')!.textContent).toContain(
      "Overwrite files that seem to have an older date than FicHub's?");
    expect(answer('replaceUndated')!.closest('label')!.textContent).toContain(
      'Overwrite files that have no date that can be guessed?');
    expect([answer('replaceOlder')!.value, answer('replaceUndated')!.value]).toEqual(['yes', 'no']);
  });

  it('hands the run only renaming where AO3 has the work, and the answers given for overwriting with FicHub', async () => {
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    await click('Repair remaining from AO3');
    await click('Continue');
    element.querySelector<HTMLInputElement>('input[name="repairAo3"][value="rename"]')!.click();
    fallback('replace').click();
    await fixture.whenStable();
    await answerWith('replaceOlder', 'no');
    await answerWith('replaceUndated', 'yes');
    await click('Continue');
    element.querySelector<HTMLInputElement>('input[name="updateFetch"][value="skip"]')?.click();
    await fixture.whenStable();
    await click('Continue');

    expect(started[0].request).toMatchObject({
      repairRenameOnly: true, repairFicHub: true, repairFicHubOlder: false, repairFicHubUndated: true,
    });
  });

  it("hands the run the files to repair by name, and their works only for that when they are not updated", async () => {
    await open();
    await click('Continue');
    await click('Skip remaining');
    repairBox('works/2 C - D.html').click();
    await fixture.whenStable();
    await click('Continue');
    fallback('replace').click();
    await fixture.whenStable();
    await click('Continue');
    // the index question, then the formats, skipped
    await click('Continue');
    element.querySelector<HTMLInputElement>('input[name="updateFetch"][value="skip"]')!.click();
    await fixture.whenStable();
    await click('Continue');

    const request = started[0].request;
    expect(request.repair).toEqual(['2 C - D.html']);
    expect(request.repairFicHub).toBe(true);
    expect(request.repairFicHubUndated).toBe(false);
    expect(request.repairFicHubRename).toBe(false);
    expect(request.links.split('\n').map((l) => l.split('/').pop())).toContain('2');
    expect(request.indexOnly).toContain('2');
  });

  it("hands the run the choice to name a file with FicHub's date instead", async () => {
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    await click('Repair remaining from AO3');
    await click('Continue');
    fallback('rename').click();
    await fixture.whenStable();
    await answerWith('renameUndated', 'no');
    await click('Continue');
    element.querySelector<HTMLInputElement>('input[name="updateFetch"][value="skip"]')?.click();
    await fixture.whenStable();
    await click('Continue');

    expect(started[0].request).toMatchObject({
      repairFicHub: false, repairFicHubRename: true, repairFicHubOlder: true, repairFicHubUndated: false,
    });
  });

  it("leaves a work out of the index question when a file of it is being repaired, since the repair indexes it", async () => {
    await open();
    await click('Continue');
    await click('Skip remaining');
    repairBox('works/2 C - D.html').click();
    await fixture.whenStable();
    await click('Continue');
    await click('Continue');

    expect(step()).toBe('index');
    const said = element.querySelector('section.body')!.textContent!.replace(/\s+/g, ' ');
    // works 1 and 3 are asked about; 2 is indexed by its repair
    expect(said).toContain('2 works have no index entry.');
    expect(said).toContain('1 more work has no index entry, but is indexed anyway: a file of it is being repaired from AO3.');
  });

  it('skips the index question when every work missing an entry is being repaired', async () => {
    await open(unindexedWorks(['works/2 C - D.html'], new Set()));
    await click('Continue');
    await click('Repair remaining from AO3');
    await click('Continue');
    await click('Continue');

    expect(step()).toBe('formats');
  });

  it('renames the files given a date before the repair page, which comes after them', async () => {
    await open();
    await click('Continue');
    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    await click('Repair remaining from AO3');
    await click('Continue');

    expect(step()).toBe('dating');
    expect(store.renamed).toEqual([['works/2 C - D.html', 'works/2 C - D 2024-05-06.html']]);
    await click('Continue');
    expect(step()).toBe('repair');
    // the dates are renamed now, so the repair page goes no further back
    expect(button('Back')).toBeUndefined();
    await click('Continue');
    expect(step()).toBe('index');
    await click('Back');
    expect(step()).toBe('repair');
  });

  describe('repairing from the FicFairy index first', () => {
    const indexed = () => TestBed.inject(Library).worksById.set(new Map([
      ['7', { id: '7', title: 'The Fic', authors: ['Writer'], date_updated: '14 Dec 2024' } as Bookmark]]));
    const indexFirst = () => element.querySelector<HTMLInputElement>('input[name="indexFirst"]')!;

    it('is offered off, and says how many files have a date in the index', async () => {
      indexed();
      await open([], false, INDEXED_UNDATED);
      await click('Continue');
      await click('Repair remaining from AO3');
      await click('Continue');

      expect(indexFirst().checked).toBe(false);
      const said = indexFirst().closest('label')!.textContent!.replace(/\s+/g, ' ');
      expect(said).toContain('Try to date the file from an existing FicFairy index?');
      expect(said).toContain('If there is no index, then it attempts to connect to AO3, and then FicHub instead.');
      expect(said).toContain('1 of the 1 file has a date in your index.');
    });

    it("renames a file with its index entry's date and sends AO3 nothing for it", async () => {
      indexed();
      await open([], false, INDEXED_UNDATED);
      await click('Continue');
      await click('Repair remaining from AO3');
      await click('Continue');
      indexFirst().click();
      await fixture.whenStable();
      await click('Continue');
      // nothing renamed until every question is answered: the formats page comes first
      expect(step()).toBe('formats');
      expect(store.renamed).toEqual([]);
      element.querySelector<HTMLInputElement>('input[name="updateFetch"][value="skip"]')?.click();
      await fixture.whenStable();
      primary().click();
      await settle();

      expect(step()).toBe('dating');
      expect(store.renamed).toEqual([['works/7 old name.html', 'works/7 The Fic - Writer 2024-12-14.html']]);
      expect(element.querySelector('.dated-said')!.textContent!.replace(/\s+/g, ' ')).toContain(
        'Dated 1 file from your FicFairy index.');
      // nothing left for a run: the window ends there
      expect(primary().textContent!.trim()).toBe('Done');
      await click('Done');
      expect(started).toEqual([]);
      expect(closed.length).toBe(1);
    });

    it('never renames over another file, and lists the clash', async () => {
      indexed();
      await open([], false, INDEXED_UNDATED);
      store.listed = ['works/7 The Fic - Writer 2024-12-14.html'];
      await click('Continue');
      await click('Repair remaining from AO3');
      await click('Continue');
      indexFirst().click();
      await fixture.whenStable();
      await click('Continue');
      element.querySelector<HTMLInputElement>('input[name="updateFetch"][value="skip"]')?.click();
      await fixture.whenStable();
      primary().click();
      await settle();

      expect(store.renamed).toEqual([]);
      const said = element.querySelector('.index-clashes')!.textContent!.replace(/\s+/g, ' ');
      expect(said).toContain('1 file failed to repair from your FicFairy index due to a name clash');
      expect(said).toContain('works/7 The Fic - Writer 2024-12-14.html is already taken');
    });

    it('sends the run, for AO3 then FicHub, only the files the index has no date for', async () => {
      indexed();
      await open(unindexedWorks(['works/2 C - D.html'], new Set()), false, INDEXED_UNDATED);
      await click('Continue');
      await click('Repair remaining from AO3');
      await click('Continue');
      indexFirst().click();
      await fixture.whenStable();
      await click('Continue');
      // work 2 is indexed by its repair, so there is no index page: straight to the formats
      expect(step()).toBe('formats');
      element.querySelector<HTMLInputElement>('input[name="updateFetch"][value="skip"]')!.click();
      await fixture.whenStable();
      await click('Continue');
      await settle();
      await click('Continue');

      expect(started[0].request.repair).toEqual(['2 C - D.html']);
      expect(started[0].request.links).toBe('https://archiveofourown.org/works/2');
    });
  });

  describe('skipping AO3 for files the index cannot date', () => {
    const indexed = () => TestBed.inject(Library).worksById.set(new Map([
      ['7', { id: '7', title: 'The Fic', authors: ['Writer'], date_updated: '14 Dec 2024' } as Bookmark]]));
    const box = () => element.querySelector<HTMLInputElement>('input[name="skipAo3Check"]');

    it('is offered only under the index choice, and hides the AO3 and FicHub choices', async () => {
      indexed();
      await open([], false, INDEXED_UNDATED);
      await click('Continue');
      await click('Repair remaining from AO3');
      await click('Continue');
      expect(box()).toBeNull();
      expect(element.querySelector('input[name="repairAo3"]')).not.toBeNull();

      element.querySelector<HTMLInputElement>('input[name="indexFirst"]')!.click();
      await fixture.whenStable();
      expect(box()!.checked).toBe(false);
      expect(box()!.closest('label')!.textContent).toContain('Skip any check from AO3 for remaining files');
      const hint = () => element.querySelector('.repair-index')!.textContent!.replace(/\s+/g, ' ');
      expect(hint()).toContain('If there is no index, then it attempts to connect to AO3, and then FicHub instead.');
      box()!.click();
      await fixture.whenStable();

      expect(hint()).toContain('If there is no index, the file is left as it is.');
      expect(hint()).not.toContain('attempts to connect to AO3');
      expect(element.querySelector('input[name="repairAo3"]')).toBeNull();
      expect(element.querySelector('input[name="repairFallback"]')).toBeNull();
    });

    it('sends the run none of the files the index has no date for', async () => {
      indexed();
      await open(unindexedWorks(['works/2 C - D.html'], new Set()), false, INDEXED_UNDATED);
      await click('Continue');
      await click('Repair remaining from AO3');
      await click('Continue');
      element.querySelector<HTMLInputElement>('input[name="indexFirst"]')!.click();
      await fixture.whenStable();
      box()!.click();
      await fixture.whenStable();
      await click('Continue');
      // work 2 is no longer indexed by a repair, so the index page asks about it
      expect(step()).toBe('index');
      element.querySelector<HTMLInputElement>('input[name="lookup"][value="later"]')!.click();
      await fixture.whenStable();
      await click('Continue');
      element.querySelector<HTMLInputElement>('input[name="updateFetch"][value="skip"]')?.click();
      await fixture.whenStable();
      primary().click();
      await settle();

      expect(store.renamed).toEqual([['works/7 old name.html', 'works/7 The Fic - Writer 2024-12-14.html']]);
      expect(primary().textContent!.trim()).toBe('Done');
      await click('Done');
      expect(started).toEqual([]);
    });
  });

  it('runs for a file to repair even with nothing else for a run to do', async () => {
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    repairBox('works/7 old name.html').click();
    await fixture.whenStable();
    await click('Continue');
    expect(step()).toBe('repair');
    await click('Continue');
    element.querySelector<HTMLInputElement>('input[name="updateFetch"][value="skip"]')?.click();
    await fixture.whenStable();
    await click('Continue');

    expect(started[0].request).toMatchObject({
      links: 'https://archiveofourown.org/works/7',
      repair: ['7 old name.html'],
      indexOnly: ['7'],
      filetypes: ['JSON'],
    });
  });

  // endregion

  it('puts only the skipped files on the dates list when told not to ask again', async () => {
    await open();
    TestBed.inject(Library).store.set(store);
    await click('Continue');
    const box = element.querySelector<HTMLInputElement>('input[name="rememberSkips"]')!;
    expect(box.closest('label')!.textContent).toContain("Don't ask this again for skipped files");
    expect(box.closest('label')!.textContent).toContain('import-excluded.json');
    // never ticked to begin with: going on the list is the reader's choice
    expect(box.checked).toBe(false);
    expect(element.querySelector('.remember-skips')!.compareDocumentPosition(element.querySelector('table.dating')!) &
      Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();

    row('works/2 C - D.pdf').querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
    row('works/3 E - F.epub').querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    box.click();
    await fixture.whenStable();
    await click('Continue');
    await settle();

    const written = JSON.parse(store.written.get(IMPORT_EXCLUDED_FILE)!);
    expect(written.excluded.map((x: { id: string; kind: string; files: string[] }) => [x.id, x.kind, x.files])).toEqual([
      ['2', 'dates', ['2 C - D.pdf']],
      ['3', 'dates', ['3 E - F.epub']],
    ]);
  });

  it('writes nothing for skipped files unless told not to ask again', async () => {
    await open();
    TestBed.inject(Library).store.set(store);
    await click('Continue');
    await click('Skip remaining');
    await click('Skip this step');
    expect(step()).toBe('index');
    expect(store.written.size).toBe(0);
  });

  it('holds Continue while a file has neither a date nor a Skip tick, highlighting it and saying why', async () => {
    await open();
    await click('Continue');
    expect(primary().disabled).toBe(true);
    expect(primary().getAttribute('title')).toBe('Give every file a date, or tick Skip or Repair from AO3');
    expect(element.querySelectorAll('tr.needs-answer')).toHaveLength(3);
    expect(element.querySelector('.needs-answer-note')?.textContent?.replace(/\s+/g, ' ')).toContain('3 files (highlighted above) have no date, Skip or Repair. Answer each, or use Bulk actions above.');

    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    skipBox('works/2 C - D.pdf').click();
    await fixture.whenStable();
    expect(row('works/2 C - D.html').classList).not.toContain('needs-answer');
    expect(row('works/2 C - D.pdf').classList).not.toContain('needs-answer');
    expect(element.querySelector('.needs-answer-note')?.textContent?.replace(/\s+/g, ' ')).toContain('1 file (highlighted above) has no date, Skip or Repair. Answer it, or use Bulk actions above.');
    expect(primary().disabled).toBe(true);

    // Skip remaining skips what is left, keeping the date and the skip given
    await click('Skip remaining');
    expect(element.querySelector('.needs-answer-note')).toBeNull();
    expect(skipBox('works/3 E - F.epub').checked).toBe(true);
    expect(dateBox('works/2 C - D.html').value).toBe('2024-05-06');
    expect(primary().disabled).toBe(false);
    expect(primary().textContent?.trim()).toBe('Continue');
  });

  it('greys a skipped row and its date, without striking it through', async () => {
    await open();
    await click('Continue');
    skipBox('works/2 C - D.pdf').click();
    await fixture.whenStable();
    expect(row('works/2 C - D.pdf').classList).toContain('skipped');
    expect(dateBox('works/2 C - D.pdf').disabled).toBe(true);
    expect(getComputedStyle(row('works/2 C - D.pdf').querySelector('td')!).textDecoration).not.toContain('line-through');
  });

  it('puts one date in the remaining rows only, leaving a skipped or dated row as it is', async () => {
    await open();
    await click('Continue');
    skipBox('works/2 C - D.pdf').click();
    await type(dateBox('works/3 E - F.epub'), '2023-03-03');
    expect(element.querySelector('input[name="bulkDate"]')).toBeNull();
    await click('Choose my own date...');
    await type(element.querySelector<HTMLInputElement>('input[name="bulkDate"]')!, '2024-01-31');
    await click('Use for remaining');
    // done, the date closes again
    expect(element.querySelector('input[name="bulkDate"]')).toBeNull();

    expect(dateBox('works/2 C - D.html').value).toBe('2024-01-31');
    expect(dateBox('works/2 C - D.pdf').value).toBe('');
    expect(dateBox('works/3 E - F.epub').value).toBe('2023-03-03');
    expect(skipBox('works/2 C - D.pdf').checked).toBe(true);
    expect(primary().textContent?.trim()).toBe('Continue');
  });

  it('keeps the bulk actions in a fold, says how many rows remain, and holds them once none do', async () => {
    await open();
    await click('Continue');
    const fold = element.querySelector<HTMLDetailsElement>('details.bulk-actions')!;
    expect(fold.open).toBe(false);
    expect(fold.querySelector('summary')?.textContent?.trim()).toBe('Bulk actions');
    const said = () => element.querySelector('.bulk-what')?.textContent?.replace(/\s+/g, ' ').trim();
    expect(said()).toBe('There are 3 remaining files that still need to be resolved.');
    await click('Skip remaining');
    expect(said()).toBe('There are 0 remaining files that still need to be resolved.');
    for (const label of ['Infer date for remaining', 'Skip remaining', 'Repair remaining from AO3', 'Choose my own date...']) {
      expect(button(label)!.disabled).toBe(true);
    }
  });

  it('chooses its own date in place, never in a window over this one, and Cancel closes it', async () => {
    await open();
    await click('Continue');
    await click('Choose my own date...');
    expect(element.querySelector('.bulk-actions .bulk-date input[name="bulkDate"]')).toBeTruthy();
    expect(element.querySelectorAll('.dialog')).toHaveLength(1);
    await click('Cancel');
    expect(element.querySelector('input[name="bulkDate"]')).toBeNull();
  });

  it('ticks Skip on every remaining row with Skip remaining', async () => {
    await open();
    await click('Continue');
    await click('Skip remaining');
    expect(rowOrder().every((p) => skipBox(p).checked)).toBe(true);
    expect(primary().textContent?.trim()).toBe('Skip this step');
    await click('Skip this step');
    expect(store.renamed).toEqual([]);
    expect(step()).toBe('index');
  });

  it('shows the files a page at a time or as one scrolling list, keeping what was set', async () => {
    const many = unindexedWorks(
      Array.from({ length: 30 }, (_, i) => `works/${100 + i} Fic ${String(i).padStart(2, '0')} - W.html`),
      new Set(),
    );
    await open(many);
    await click('Continue');
    expect(rowOrder()).toHaveLength(7);
    await type(dateBox('works/100 Fic 00 - W.html'), '2024-02-02');
    await click('Next');
    expect(rowOrder()).toHaveLength(7);
    expect(element.textContent).toContain('Page 2 of 5');

    await click('One scrolling list');
    expect(rowOrder()).toHaveLength(30);
    expect(dateBox('works/100 Fic 00 - W.html').value).toBe('2024-02-02');
    // back to pages, on the page it was on
    await click('Pages');
    expect(element.textContent).toContain('Page 2 of 5');
    await click('Previous');
    expect(dateBox('works/100 Fic 00 - W.html').value).toBe('2024-02-02');
  });

  // endregion

  // region inferring dates

  const MESSY = unindexedWorks(
    [
      'works/10 Zeta 20230115 - W.html',
      'works/11 Alpha - W (posted 03-04-2022).epub',
      'works/12 Beta - W.pdf',
      'works/13 Gamma 14 Dec 2021 - W.html',
      'works/20240304 Delta - W.html',
    ],
    new Set(),
  );

  it('reads dates out of the remaining names, whatever their form, and moves what it dated to the top in yellow', async () => {
    await open(MESSY);
    await click('Continue');
    skipBox('works/13 Gamma 14 Dec 2021 - W.html').click();
    await fixture.whenStable();
    await click('Infer date for remaining');

    // what it dated, by name; then the rest, by name
    expect(rowOrder()).toEqual([
      'works/10 Zeta 20230115 - W.html',
      'works/11 Alpha - W (posted 03-04-2022).epub',
      'works/12 Beta - W.pdf',
      'works/13 Gamma 14 Dec 2021 - W.html',
      'works/20240304 Delta - W.html',
    ]);
    expect(dateBox('works/10 Zeta 20230115 - W.html').value).toBe('2023-01-15');
    expect(dateBox('works/11 Alpha - W (posted 03-04-2022).epub').value).toBe('2022-03-04');
    // a skipped row is answered already: left as it is
    expect(dateBox('works/13 Gamma 14 Dec 2021 - W.html').value).toBe('');
    expect(skipBox('works/13 Gamma 14 Dec 2021 - W.html').checked).toBe(true);
    expect(row('works/13 Gamma 14 Dec 2021 - W.html').classList).not.toContain('inferred');
    // a work number is not a date
    expect(dateBox('works/20240304 Delta - W.html').value).toBe('');
    expect(row('works/10 Zeta 20230115 - W.html').classList).toContain('inferred');
    expect(element.querySelector('.infer-said')?.textContent).toContain('2 files were auto-dated');
    expect(primary().textContent?.trim()).toBe('Continue');
  });

  it('leaves a date given by hand as it is when inferring the remaining rows', async () => {
    await open(MESSY);
    await click('Continue');
    await type(dateBox('works/10 Zeta 20230115 - W.html'), '2020-02-02');
    await click('Infer date for remaining');
    expect(dateBox('works/10 Zeta 20230115 - W.html').value).toBe('2020-02-02');
    expect(row('works/10 Zeta 20230115 - W.html').classList).not.toContain('inferred');
  });

  it('takes the yellow off a row changed by hand, which stays where it is', async () => {
    await open(MESSY);
    await click('Continue');
    await click('Infer date for remaining');
    await type(dateBox('works/10 Zeta 20230115 - W.html'), '2023-01-20');
    expect(row('works/10 Zeta 20230115 - W.html').classList).not.toContain('inferred');
    expect(rowOrder()[0]).toBe('works/10 Zeta 20230115 - W.html');
  });

  it('says when it could date nothing', async () => {
    await open(unindexedWorks(['works/1 No Date Here - W.html'], new Set()));
    await click('Continue');
    await click('Infer date for remaining');
    expect(element.querySelector('.infer-said')?.textContent).toContain('Unable to auto-date any works');
  });

  it('holds Continue and its own button while it runs', async () => {
    await open(MESSY);
    await click('Continue');
    button('Infer date for remaining')!.click();
    fixture.detectChanges();
    expect(element.querySelector<HTMLButtonElement>('.button.infer')!.disabled).toBe(true);
    expect(element.querySelector('.button.infer .spinner')).not.toBeNull();
    expect(primary().disabled).toBe(true);
    await settle();
    expect(element.querySelector<HTMLButtonElement>('.button.infer')!.disabled).toBe(false);
    await click('Skip remaining');
    expect(primary().disabled).toBe(false);
  });

  // endregion

  // region dating

  it('renames on a page of its own, then says how many, with failures folded away', async () => {
    await open();
    await click('Continue');
    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    await type(dateBox('works/3 E - F.epub'), '2024-07-08');
    skipBox('works/2 C - D.pdf').click();
    await fixture.whenStable();
    store.refuse.add('works/3 E - F.epub');
    let letGo!: () => void;
    store.hold = new Promise<void>((resolve) => (letGo = resolve));
    primary().click();
    await settle();

    expect(step()).toBe('dating');
    expect(element.querySelector('.dating-progress')?.textContent).toContain('Dating files');
    expect(primary().disabled).toBe(true);
    expect(button('Back')).toBeUndefined();

    letGo();
    await settle();
    expect(element.querySelector('.dated-said')?.textContent).toContain('Dated 1 file');
    const failures = element.querySelector<HTMLDetailsElement>('details.dating-failures')!;
    expect(failures.open).toBe(false);
    expect(failures.textContent).toContain('works/3 E - F.epub');
    expect(store.renamed).toEqual([['works/2 C - D.html', 'works/2 C - D 2024-05-06.html']]);
    expect(primary().disabled).toBe(false);
    await click('Continue');
    expect(step()).toBe('index');
  });

  it('names a file of an indexed work from its entry, with the date given', async () => {
    TestBed.inject(Library).worksById.set(new Map([['7', { id: '7', title: 'The Fic', authors: ['Writer'] } as Bookmark]]));
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    await type(dateBox('works/7 old name.html'), '2024-02-03');
    primary().click();
    await settle();

    expect(store.renamed).toEqual([['works/7 old name.html', 'works/7 The Fic - Writer 2024-02-03.html']]);
  });

  it('stops renaming when closed part way, keeping what was renamed', async () => {
    await open();
    await click('Continue');
    await click('Skip remaining');
    for (const path of ['works/2 C - D.html', 'works/2 C - D.pdf']) {
      skipBox(path).click();
      await type(dateBox(path), '2024-05-06');
    }
    let letGo!: () => void;
    store.hold = new Promise<void>((resolve) => (letGo = resolve));
    primary().click();
    await settle();
    element.querySelector<HTMLButtonElement>('header .icon')!.click();
    letGo();
    await settle();

    expect(closed).toHaveLength(1);
    expect(store.renamed.length).toBeLessThanOrEqual(1);
  });

  // endregion

  // region the index and the formats

  // region files a download was left part-way through replacing

  async function openWithLeftovers(leftovers: SwapLeftover[], works: FoundWork[] = SOME) {
    fixture = TestBed.createComponent(ImportDialog);
    store = new MemoryStore();
    fixture.componentRef.setInput('works', works);
    fixture.componentRef.setInput('store', store);
    fixture.componentRef.setInput('leftovers', leftovers);
    closed = [];
    started = [];
    fixture.componentInstance.closed.subscribe((x) => closed.push(x));
    fixture.componentInstance.start.subscribe((x) => started.push(x));
    await fixture.whenStable();
    element = fixture.nativeElement as HTMLElement;
  }

  const LEFTOVERS = swapLeftovers([
    // set aside, the new copy never arrived: put back
    'works/1 A - B 2024-01-01.html.ficfairy-old', 'works/1 A - B 2024-01-01.html.ficfairy-new',
    // a new copy in place: yours is put back all the same
    'works/2 C - D 2024-01-01.pdf', 'works/2 C - D 2024-01-01.pdf.ficfairy-old',
    // an unfinished new copy beside your file
    'works/3 E - F 2024-01-01.epub', 'works/3 E - F 2024-01-01.epub.ficfairy-new',
  ]);

  it('counts the files left mid-download first among the issues', async () => {
    await openWithLeftovers(LEFTOVERS);
    expect(element.querySelector('.overview-leftovers')!.textContent!.trim())
      .toBe('3 files were left part-way through being replaced by an interrupted download');
  });

  it('always puts back a copy set aside, removing any new copy in its place, before anything else', async () => {
    await openWithLeftovers(LEFTOVERS);
    await click('Continue');
    expect(step()).toBe('leftovers');
    const said = element.querySelector('.leftovers')!.textContent!.replace(/\s+/g, ' ');
    expect(said).toContain('1 A - B 2024-01-01.html - your copy was set aside and the new one never arrived: it will be put back');
    expect(said).toContain('2 C - D 2024-01-01.pdf - your copy was set aside while a new one took its place: the new copy will be removed, in case it is damaged, and yours put back');
    expect(said).toContain('3 E - F 2024-01-01.epub - an unfinished new copy is beside it: it will be removed, and your file kept');

    await click('Put back and tidy up');
    await settle();
    expect(store.renamed).toEqual([
      ['works/1 A - B 2024-01-01.html.ficfairy-old', 'works/1 A - B 2024-01-01.html'],
      ['works/2 C - D 2024-01-01.pdf.ficfairy-old', 'works/2 C - D 2024-01-01.pdf'],
    ]);
    expect([...store.deleted].sort()).toEqual([
      'works/1 A - B 2024-01-01.html.ficfairy-new',
      'works/2 C - D 2024-01-01.pdf',
      'works/3 E - F 2024-01-01.epub.ficfairy-new',
    ]);
    expect(element.querySelector('.leftovers-said')!.textContent!.replace(/\s+/g, ' ')).toContain('Put back 2 files, removed 3.');
    expect(element.querySelector('.leftovers')).toBeNull();
    expect(TestBed.inject(VisitLog).text()).toContain('files left mid-download - put back 2, removed 3');
    await click('Continue');
    expect(step()).not.toBe('leftovers');
  });

  it('can pass them over, and closes when they were all there was', async () => {
    await openWithLeftovers(LEFTOVERS, []);
    await click('Continue');
    await click('Skip this step');
    expect(store.renamed).toEqual([]);
    expect(store.deleted).toEqual([]);
    expect(closed).toHaveLength(1);
  });

  // endregion

  // region opened from a work's 'Look up its index from AO3 here'

  async function openFor(work: string | string[], works: FoundWork[] = SOME, elsewhere: FoundFile[] = INDEXED_UNDATED,
                         ignored: FoundWork[] = []) {
    fixture = TestBed.createComponent(ImportDialog);
    store = new MemoryStore();
    fixture.componentRef.setInput('works', works);
    fixture.componentRef.setInput('ignored', ignored);
    fixture.componentRef.setInput('undatedElsewhere', elsewhere);
    fixture.componentRef.setInput('store', store);
    fixture.componentRef.setInput('lookUpWorks', Array.isArray(work) ? work : [work]);
    closed = [];
    started = [];
    fixture.componentInstance.closed.subscribe((x) => closed.push(x));
    fixture.componentInstance.start.subscribe((x) => started.push(x));
    await fixture.whenStable();
    element = fixture.nativeElement as HTMLElement;
  }

  it('opens straight on the index question, looking up just that work to begin with', async () => {
    await openFor('2');
    expect(step()).toBe('index');
    expect(TestBed.inject(VisitLog).text()).toContain('Resolve issues opened on the index question for 1 work(s)');
    expect(radio('lookupFor', 'this')!.checked).toBe(true);
    expect(radio('lookupFor', 'all')!.closest('label')!.textContent).toContain('(3)');
    await click('Continue');
    // the dates were passed over: only that work's index is in question
    expect(step()).toBe('formats');
    // there was no Yes to tick on the way here, so no pointing back to it
    expect(element.querySelector('.index-only-hint')).toBeNull();
    // only the look-up's own choices of which fics to update
    expect(radio('updateScope', 'all')).toBeNull();
    expect(radio('updateFor', 'this')!.checked).toBe(true);
    expect(radio('updateFor', 'all')!.closest('label')!.textContent).toContain('All fics with a missing index (3)');
    expect(radio('updateFor', 'ignored')).toBeNull();
    await choose('updateFetch', 'skip');
    await click('Continue');

    expect(started[0].request).toMatchObject({
      links: 'https://archiveofourown.org/works/2',
      indexOnly: ['2'],
      lookups: 1,
      scope: 'skip',
    });
  });

  it('says these works and these fics when opened for several ticked works', async () => {
    await openFor(['1', '3']);
    expect(radio('lookupFor', 'this')!.closest('label')!.textContent!.replace(/\s+/g, ' ')).toContain('Just for these works (2)');
    await click('Continue');
    expect(radio('updateFor', 'this')!.closest('label')!.textContent!.replace(/\s+/g, ' ')).toContain('Just these fics (2)');
    await choose('updateFetch', 'skip');
    await click('Continue');
    expect(started[0].request.links.split('\n').map((l) => l.split('/').pop()).sort()).toEqual(['1', '3']);
  });

  it('explains what an index entry is, and does not ask whether to fetch one - it is yes', async () => {
    await openFor('2');
    expect(element.querySelector('.index-count')!.textContent!.trim()).toBe('1 work has no index entry.');
    expect(element.querySelector('.index-about')!.textContent).toContain('title, author, summary, tags');
    expect(element.querySelector('.index-about')!.textContent).not.toContain('newer version');
    expect(radio('lookup', 'yes')).toBeNull();
  });

  it('updates every fic with a missing index when told to, looking each up too', async () => {
    await openFor('2', SOME, INDEXED_UNDATED, IGNORED);
    await click('Continue');
    expect(radio('updateFor', 'ignored')!.closest('label')!.textContent!.replace(/\s+/g, ' '))
      .toContain('All fics with a missing index, including any added to an ignore-list (4)');
    await choose('updateFor', 'all');
    await click('Continue');
    await click('Continue');

    const request = started[0].request;
    expect(request.links.split('\n').map((l) => l.split('/').pop()).sort()).toEqual(['1', '2', '3']);
    expect(request.indexOnly).toEqual([]);
    expect(request.scope).toBe('index');
  });

  it('looks up every work with no index entry when told to', async () => {
    await openFor('2');
    await choose('lookupFor', 'all');
    await click('Continue');
    await choose('updateFetch', 'skip');
    await click('Continue');

    expect(started[0].request.links.split('\n').map((l) => l.split('/').pop())).toEqual(['1', '2', '3']);
  });

  it('has no going back from its first page, the index question', async () => {
    await openFor('2');
    expect(button('Back')).toBeUndefined();
    await click('Continue');
    // the formats page still goes back to the index question
    await click('Back');
    expect(step()).toBe('index');
    expect(button('Back')).toBeUndefined();
  });

  const IGNORED = unindexedWorks(['works/9 Left Out - X.html'], new Set());

  it('looks up a work an exclusion list keeps out, when opened for it by name', async () => {
    await openFor('9', SOME, INDEXED_UNDATED, IGNORED);
    expect(step()).toBe('index');
    await click('Continue');
    await choose('updateFetch', 'skip');
    await click('Continue');

    expect(started[0].request).toMatchObject({ links: 'https://archiveofourown.org/works/9', indexOnly: ['9'] });
  });

  it('offers every missing index, ignored ones included, only when an exclusion list holds some', async () => {
    await openFor('2');
    expect(radio('lookupFor', 'ignored')).toBeNull();

    await openFor('2', SOME, INDEXED_UNDATED, IGNORED);
    const label = radio('lookupFor', 'ignored')!.closest('label')!.textContent!.replace(/\s+/g, ' ');
    expect(label).toContain('For all missing indexes, even if you added some to an ignore-list previously');
    expect(label).toContain('(4)');
    await choose('lookupFor', 'ignored');
    await click('Continue');
    await choose('updateFetch', 'skip');
    await click('Continue');

    expect(started[0].request.links.split('\n').map((l) => l.split('/').pop())).toEqual(['1', '2', '3', '9']);
  });

  it('opens at its start as ever for a work it does not offer', async () => {
    await openFor('99');
    expect(step()).toBe('overview');
  });

  // endregion

  it('asks about the index on a page of its own, then the formats on the next', async () => {
    await open(ALL_DATED);
    await click('Continue');
    expect(element.textContent).toContain('Fetch their index entries from AO3 now?');
    expect(element.textContent).not.toContain('File types');
    await click('Continue');
    expect(step()).toBe('formats');
    expect(element.textContent).not.toContain('File types');
    // replacing an outdated copy is what an update does, not a choice of its own
    expect(element.querySelector('input[name="replaceOutdated"]')).toBeNull();
    expect(element.querySelector('.fetch-hint')!.textContent!.trim()).toBe('This only updates files that have a date in their name. A file with no date in its name is kept as-is.');
    expect(element.querySelector('.index-only-hint')!.textContent!.replace(/\s+/g, ' ').trim()).toBe(
      'Only works with an index entry can be updated. If you are concerned that some works are missing indexes, go back to the previous step and tick Yes so they can be caught.');
    // the file types, and overwriting, are a page of their own after it
    await click('Continue');
    expect(step()).toBe('filetypes');
    expect(element.textContent).toContain('File types');
    expect(Array.from(element.querySelectorAll('.filetypes-hint')).map((p) => p.textContent!.replace(/\s+/g, ' ').trim())).toEqual([
      'Ticking a format here will check if a work is missing a copy in these formats, and download it if so.',
      'Files you already have downloaded will still be checked for a newer version - regardless of whether you tick any boxes below.',
    ]);
    expect(element.querySelector('input[name="overwrite"]')).not.toBeNull();
    await click('Back');
    expect(step()).toBe('formats');
  });

  function radio(name: string, value: string): HTMLInputElement | null {
    return element.querySelector<HTMLInputElement>(`input[name="${name}"][value="${value}"]`);
  }

  async function choose(name: string, value: string) {
    radio(name, value)!.click();
    await fixture.whenStable();
  }

  async function tick(name: string) {
    element.querySelector<HTMLInputElement>(`input[name="${name}"]`)!.click();
    await fixture.whenStable();
  }

  it('starts an import of every work found, with the formats ticked, replacing outdated copies', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue');
    expect(radio('updateScope', 'all')!.checked).toBe(true);
    await click('Continue');
    await tick('format-EPUB');
    await click('Continue');

    expect(started[0].request).toEqual({
      links: 'https://archiveofourown.org/works/1',
      count: 1,
      filetypes: ['JSON', 'EPUB'],
      replaceOutdated: true,
      overwrite: false,
      indexOnly: [],
      lookups: 1,
      scope: 'all',
      files: 1,
      repair: [],
      repairFicHub: false,
      repairFicHubOlder: true,
      repairFicHubUndated: false,
      repairFicHubRename: false,
      repairFicHubCheck: true,
      repairRenameOnly: false,
    });
  });

  it('takes every work found, however many', async () => {
    const many = unindexedWorks(
      Array.from({ length: 6_000 }, (_, n) => `works/${n + 1} A - B 2024-01-01.html`),
      new Set(),
    );
    await open(many);
    await click('Continue');
    await click('Continue');
    await click('Continue');
    await click('Continue');

    expect(started[0].request.count).toBe(6_000);
    expect(started[0].request.links.split('\n')).toHaveLength(6_000);
  });

  it('takes in the indexed works whose files were undated, for their formats and outdated copies', async () => {
    await open(ALL_DATED, false, INDEXED_UNDATED);
    await click('Continue');
    await skipDates();
    await click('Continue');
    await click('Continue');
    await click('Continue');
    expect(started[0].request.replaceOutdated).toBe(true);
    expect(started[0].request.links).toBe(
      'https://archiveofourown.org/works/1\nhttps://archiveofourown.org/works/7',
    );
  });

  it('never shows the index page when every work has an index entry: dating goes straight to the formats', async () => {
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    expect(step()).toBe('dates');
    await type(row('works/7 old name.html').querySelector<HTMLInputElement>('input[type="date"]')!, '2024-02-03');
    await click('Continue');
    expect(step()).toBe('dating');
    await click('Continue');
    expect(step()).toBe('formats');
    expect(element.textContent).not.toContain('Fetch their index entries');
    // and only the scopes that have works: no index issues to pick
    expect(radio('updateScope', 'index')).toBeNull();
    expect(radio('updateScope', 'dates')).toBeTruthy();

    // skipping the dates goes straight there too
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    await skipDates();
    expect(step()).toBe('formats');
  });

  it('never offers an update for the undated file of a work left out of the index question', async () => {
    const left: FoundFile = { ...INDEXED_UNDATED[0], id: '9', path: 'works/9 x.html', name: '9 x.html', unindexed: true };
    await open([], false, [left, ...INDEXED_UNDATED]);
    await click('Continue');
    await skipDates();
    expect(step()).toBe('formats');
    // work 7 only: work 9 has no index entry and is never looked up
    expect(element.querySelector('input[name="updateScope"][value="all"]')!.closest('label')!.textContent).toContain('(1)');
  });

  it('offers updating just the date issues or just the index issues only where there are some', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue');
    expect(radio('updateScope', 'all')).toBeTruthy();
    expect(radio('updateScope', 'dates')).toBeNull();
    expect(radio('updateScope', 'index')).toBeTruthy();
    expect(radio('updateFetch', 'skip')).toBeTruthy();

    await open(SOME);
    await click('Continue');
    await skipDates();
    await click('Continue');
    expect(radio('updateScope', 'dates')).toBeTruthy();
    expect(radio('updateScope', 'index')).toBeTruthy();
  });

  it('nests which fics to update under fetching the latest version, and comes back to the last one chosen', async () => {
    await open(SOME);
    await click('Continue');
    await skipDates();
    await click('Continue');
    expect(radio('updateFetch', 'fetch')!.checked).toBe(true);
    expect(radio('updateScope', 'all')!.closest('label')!.textContent).toContain('For all fics found to have issues in this import');
    await choose('updateScope', 'dates');
    await choose('updateFetch', 'skip');
    expect(radio('updateScope', 'dates')).toBeNull();
    await choose('updateFetch', 'fetch');
    expect(radio('updateScope', 'dates')!.checked).toBe(true);
  });

  it('downloads only for the works with date issues when told, still looking up the rest', async () => {
    await open(SOME);
    await click('Continue');
    await skipDates();
    await click('Continue');
    await choose('updateScope', 'dates');
    await click('Continue');
    await tick('format-EPUB');
    await click('Continue');

    const request = started[0].request;
    expect(request.links.split('\n').map((l) => l.split('/').pop())).toEqual(['1', '2', '3']);
    expect(request.indexOnly).toEqual(['1']);
    expect(request.scope).toBe('dates');
    expect(request.filetypes).toEqual(['JSON', 'EPUB']);
  });

  it('overwrites existing downloads only when told to', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue');
    await click('Continue');
    expect(element.querySelector('label.overwrite')!.textContent).toContain(
      'Check this if you are concerned about file integrity issues and would like to re-download each file again.');
    await tick('overwrite');
    await click('Continue');
    expect(started[0].request.overwrite).toBe(true);
  });

  it('hides the formats and replacing when the step is skipped, and does neither', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue');
    await click('Continue');
    await tick('format-EPUB');
    await click('Back');
    await choose('updateFetch', 'skip');
    expect(radio('updateScope', 'all')).toBeNull();
    expect(element.querySelector('input[name="format-EPUB"]')).toBeNull();
    await click('Continue');

    expect(started[0].request).toMatchObject({
      filetypes: ['JSON'],
      replaceOutdated: false,
      indexOnly: ['1'],
      lookups: 1,
      scope: 'skip',
    });
  });

  it('is done without a run when there is nothing for one to do', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await choose('lookup', 'later');
    // nothing left that could be updated, so the window ends here
    await click('Done');
    expect(started).toEqual([]);
    expect(closed).toEqual([null]);
  });

  it('runs whenever an update is chosen, with no format ticked, to replace outdated copies', async () => {
    await open(ALL_DATED, false, INDEXED_UNDATED);
    await click('Continue');
    await skipDates();
    await choose('lookup', 'later');
    await click('Continue');
    expect(primary().textContent?.trim()).toBe('Continue');
    await click('Continue');
    await click('Continue');
    expect(started[0].request).toMatchObject({
      links: 'https://archiveofourown.org/works/7',
      filetypes: ['JSON'],
      replaceOutdated: true,
      scope: 'all',
    });
  });

  it('never offers works again once told not to, writing them to the library', async () => {
    await open(ALL_DATED);
    TestBed.inject(Library).store.set(store);
    const imports = TestBed.inject(LibraryImports);
    imports.found.set(ALL_DATED);
    await click('Continue');
    await choose('lookup', 'never');
    await click('Done');
    await settle();

    expect(started).toEqual([]);
    expect(closed).toHaveLength(1);
    const written = JSON.parse(store.written.get(IMPORT_EXCLUDED_FILE)!);
    // the work, and the files that brought it here
    expect(written.excluded).toMatchObject([{ id: '1', kind: 'index', files: ['1 A - B 2024-01-01.html'] }]);
    expect(imports.found()).toEqual([]);
  });

  // endregion

  describe('renaming files named another way', () => {
    const MISNAMED = misnamedFiles([
      'works/My Fic - Author - 12345.epub',
      'works/Other - Writer - 678 (14 Dec 2024).html',
      'works/No number here.epub',
    ]);

    async function openNames(renameFrom: string[] = []) {
      await open([], false, [], []);
      fixture.componentRef.setInput('misnamed', MISNAMED);
      fixture.componentRef.setInput('renameFrom', renameFrom);
      await settle();
    }

    it('comes first, lists each format with its files, and names what it cannot read', async () => {
      await openNames();
      expect(element.querySelector('.overview-misnamed')?.textContent).toContain('2 files are named in a way this app cannot match to a work');
      await click('Continue');
      await settle();
      expect(step()).toBe('rename');
      expect([...element.querySelectorAll('.format-key')].map((x) => x.textContent)).toEqual([
        '{title} - {author} - {worknum}',
        '{title} - {author} - {worknum} ({date: D Mon YYYY})',
      ]);
      // the new name, as the helper makes it
      expect(element.querySelector('.becomes')?.textContent).toContain('12345 My Fic - Author.epub');
      expect(element.querySelector('details.unreadable summary')?.textContent).toContain('1 file has no work number');
      expect(primary().textContent?.trim()).toBe('Skip this step');
    });

    it('renames the files of the formats ticked, writing a date read from the name the app\'s way', async () => {
      await openNames();
      await click('Continue');
      await settle();
      element.querySelectorAll<HTMLInputElement>('.name-format input[type="checkbox"]')[1].click();
      await settle();
      expect(primary().textContent?.trim()).toBe('Rename 1 file');
      primary().click();
      await settle();
      expect(store.renamed).toEqual([['works/Other - Writer - 678 (14 Dec 2024).html', 'works/678 Other - Writer 2024-12-14.html']]);
      expect(step()).toBe('renaming');
      await click('Continue');
      expect(closed).toEqual([]);
    });

    describe('when the new name is already taken', () => {
      const TAKEN = 'works/12345 My Fic - Author.epub';
      const IMPORT = 'works/My Fic - Author - 12345.epub';

      async function renameFirstFormat() {
        await openNames();
        store.listed = [TAKEN];
        await click('Continue');
        await settle();
        element.querySelectorAll<HTMLInputElement>('.name-format input[type="checkbox"]')[0].click();
        await settle();
        primary().click();
        await settle();
      }

      function choiceBox(): HTMLSelectElement {
        return element.querySelector<HTMLSelectElement>('tr[data-group="12345:epub"] select')!;
      }

      it('renames nothing over it, and says the two go to the duplicates', async () => {
        await renameFirstFormat();
        expect(store.renamed).toEqual([]);
        expect(element.querySelector('.rename-failures')).toBeNull();
        expect(element.querySelector('.rename-clashes')?.textContent).toContain('1 file was not renamed');
        expect(element.querySelector('.rename-clashes')?.textContent).toContain('probably a second copy');
      });

      it('puts the file with the one already there as duplicates, with no note about the rename', async () => {
        await renameFirstFormat();
        await click('Continue');
        expect(step()).toBe('duplicates');
        expect(element.querySelector('tr[data-group="12345:epub"]')).not.toBeNull();
        expect(element.querySelector('tr[data-group="12345:epub"]')?.textContent).not.toContain('same name as another');
        expect(element.querySelector('tr[data-group="12345:epub"]')?.textContent).not.toContain('Not yet renamed');
      });

      it('can be skipped like any other set: both files kept, nothing renamed', async () => {
        await renameFirstFormat();
        await click('Continue');
        await click('Mark all as Skip');
        expect(choiceBox().value).toBe('skip');
        expect(primary().textContent?.trim()).toBe('Skip this step');
        primary().click();
        await settle();
        expect(store.deleted).toEqual([]);
        expect(store.renamed).toEqual([]);
      });

      it('skipped and not to be asked again, puts the held-back file on the files list too', async () => {
        await renameFirstFormat();
        TestBed.inject(Library).store.set(store);
        await click('Continue');
        await click('Mark all as Skip');
        element.querySelector<HTMLInputElement>('.remember-skipped-duplicates input')!.click();
        await settle();
        primary().click();
        await settle();
        const written = JSON.parse(store.written.get(IMPORT_EXCLUDED_FILE)!);
        const kinds = written.excluded.map((x: { kind: string; files: string[] }) => [x.kind, x.files]);
        // the duplicates list names both; the rename step reads only the files list for a file
        // whose number cannot be read from its name
        expect(kinds).toContainEqual(['duplicates', [IMPORT.split('/').pop(), TAKEN.split('/').pop()]]);
        expect(kinds).toContainEqual(['files', [IMPORT.split('/').pop()]]);
      });

      it('keeping the file being renamed deletes the other and gives the kept one its name', async () => {
        await renameFirstFormat();
        await click('Continue');
        await click('Continue');
        // neither name has a date the app wrote: asked, as for any set
        expect(step()).toBe('removing');
        expect(element.querySelector('.undecided-ask')).not.toBeNull();
        expect(element.querySelector('input[aria-label="Keep all of them"]')).not.toBeNull();
        element.querySelector<HTMLInputElement>('input[aria-label="Choose individually"]')!.click();
        await settle();
        element.querySelector<HTMLInputElement>(`input[aria-label="Keep ${IMPORT.split('/').pop()}"]`)!.click();
        await settle();
        await click('Apply and carry on');
        expect(store.deleted).toEqual([TAKEN]);
        expect(store.renamed).toEqual([[IMPORT, TAKEN]]);
        expect(element.querySelector('.clash-renamed')?.textContent).toContain('Renamed 1 kept file');
        await click('Continue');
        expect(closed).toEqual([]);
      });

      it('keeping the file already there deletes the one being renamed, and renames nothing', async () => {
        await renameFirstFormat();
        await click('Continue');
        await click('Continue');
        element.querySelector<HTMLInputElement>('input[aria-label="Choose individually"]')!.click();
        await settle();
        element.querySelector<HTMLInputElement>(`input[aria-label="Keep ${TAKEN.split('/').pop()}"]`)!.click();
        await settle();
        await click('Apply and carry on');
        expect(store.deleted).toEqual([IMPORT]);
        expect(store.renamed).toEqual([]);
      });

      it('offers the skips when sorting the set by hand, with no note about the rename', async () => {
        await renameFirstFormat();
        await click('Continue');
        choiceBox().value = 'choose';
        choiceBox().dispatchEvent(new Event('change'));
        await settle();
        await click('Choose which to keep');
        expect(step()).toBe('choose');
        expect(element.querySelector('.choose-list input[aria-label="Skip for now"]')).not.toBeNull();
        expect(element.querySelector('.choose-list')?.textContent).not.toContain('same name as another');
      });

      it('holds back two files that would both take one name, though nothing has it yet', async () => {
        await open([], false, [], []);
        fixture.componentRef.setInput('misnamed', misnamedFiles(['works/A - B - 5.html', 'works/A - B - 5 .html']));
        await settle();
        await click('Continue');
        await settle();
        for (const box of element.querySelectorAll<HTMLInputElement>('.name-format input[type="checkbox"]')) box.click();
        await settle();
        primary().click();
        await settle();
        expect(store.renamed).toEqual([]);
        expect(element.querySelector('.rename-clashes')?.textContent).toContain('2 files were not renamed');
        await click('Continue');
        expect(step()).toBe('duplicates');
        expect(element.querySelector('tr[data-group="5:html"]')).not.toBeNull();
      });
    });

    it('ticks to begin with the formats an old pattern left', async () => {
      await openNames(['{title} - {author} - {worknum}']);
      await click('Continue');
      await settle();
      const boxes = [...element.querySelectorAll<HTMLInputElement>('.name-format input[type="checkbox"]')];
      expect(boxes.map((b) => b.checked)).toEqual([true, false]);
    });
  });
});
