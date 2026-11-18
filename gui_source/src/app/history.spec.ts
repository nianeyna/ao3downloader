import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { History, LINKS_SHOWN } from './history';
import { ActiveRun, Jobs, RunHistory } from './jobs';
import { Library } from './library';
import { StorageChoice } from './storage-choice';

function aRun(over: Partial<RunHistory> = {}): RunHistory {
  return {
    file: '2026-09-13T120000-abc.json',
    id: 'abc',
    action: 'sync',
    actionName: 'Download new bookmarks and update incomplete fics',
    started: '2026-09-13T12:00:00',
    finished: '2026-09-13T12:30:00',
    status: 'success',
    filetypes: ['JSON', 'HTML'],
    options: { pages: 0, start: 1, series: false, images: false, reindex: true },
    reindexed: [],
    downloaded: [],
    updated: [],
    choices: [],
    failures: [],
    skipped: [],
    error: '',
    ...over,
  };
}

class FakeJobs extends Jobs {
  runs: RunHistory[] | null = [];
  /** the runs the helper says it is not working on - marked interrupted when settled */
  settles = 0;

  override async loadRuns(): Promise<RunHistory[] | null> {
    return this.runs;
  }

  override async refreshActiveRuns(): Promise<ActiveRun[] | null> {
    return this.activeRuns();
  }

  /** set to stand for a helper that does not answer, which settles nothing */
  leaveRunning = false;

  override async settleInterrupted(): Promise<number> {
    this.settles++;
    if (this.leaveRunning) return 0;
    const running = (this.runs ?? []).filter((run) => run.status === 'running');
    for (const run of running) run.status = 'interrupted';
    return running.length;
  }
}

let jobs: FakeJobs;
let fixture: ComponentFixture<History>;
let element: HTMLElement;

async function show(runs: RunHistory[] | null) {
  jobs.runs = runs;
  fixture = TestBed.createComponent(History);
  element = fixture.nativeElement as HTMLElement;
  // the history is read in a few awaited steps; wait for all of them, not just the first
  for (let tries = 0; tries < 10; tries++) {
    await fixture.whenStable();
    if (!element.textContent?.includes('Reading past runs')) break;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

/** a fold opened as a person opens one: its toggle is what draws the list inside */
async function openFold(fold: HTMLDetailsElement): Promise<void> {
  fold.open = true;
  fold.dispatchEvent(new Event('toggle'));
  await fixture.whenStable();
}

describe('History', () => {
  beforeEach(() => {
    jobs = new FakeJobs();
    TestBed.configureTestingModule({ providers: [{ provide: Jobs, useValue: jobs }] });
  });

  it('shows a bar while it reads past runs', async () => {
    let finish!: (runs: RunHistory[]) => void;
    vi.spyOn(jobs, 'loadRuns').mockReturnValue(new Promise((resolve) => (finish = resolve)));
    fixture = TestBed.createComponent(History);
    element = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    await fixture.whenStable().catch(() => undefined);
    fixture.detectChanges();
    expect(element.querySelector('app-progress-bar [role="progressbar"]')).not.toBeNull();
    expect(element.textContent).toContain('Reading past runs');
    finish([]);
    for (let i = 0; i < 5; i++) {
      await new Promise((resolve) => setTimeout(resolve, 0));
      await fixture.whenStable();
    }
    fixture.detectChanges();
    expect(element.querySelector('app-progress-bar')).toBeNull();
  });

  it('offers no refresh icon with no library open, or when the history could not be read', async () => {
    await show(null);
    expect(element.querySelector('.refresh-icon')).toBeNull();
    expect(element.querySelector('.meta-line')).toBeNull();
  });

  it('shows no bar of its own while the library is being read - one bar at a time', async () => {
    let finish!: (runs: RunHistory[]) => void;
    vi.spyOn(jobs, 'loadRuns').mockReturnValue(new Promise((resolve) => (finish = resolve)));
    TestBed.inject(Library).loading.set(true);
    fixture = TestBed.createComponent(History);
    element = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
    expect(element.querySelector('app-progress-bar')).toBeNull();

    TestBed.inject(Library).loading.set(false);
    fixture.detectChanges();
    expect(element.querySelector('app-progress-bar')?.textContent).toContain('Reading past runs');
    finish([]);
  });

  it('says it lists only the most recent runs, in an (i) beside the heading', async () => {
    await show([]);
    expect(element.querySelector('h2 .history-limit')?.textContent).toContain('100 most recent runs');
  });

  it('shows the list it read last when opened again, and reads anew only on Refresh or a run', async () => {
    TestBed.inject(Library).store.set({} as never);
    const read = vi.spyOn(jobs, 'loadRuns');
    await show([aRun()]);
    expect(read).toHaveBeenCalledTimes(1);
    expect(element.querySelector('.meta-line')?.textContent).toContain('List refreshed');

    fixture.destroy();
    await show([aRun(), aRun({ id: 'def', file: 'b.json' })]);
    expect(read).toHaveBeenCalledTimes(1);
    expect(element.querySelectorAll('.run:not(.run-active)').length).toBe(1);

    element.querySelector<HTMLButtonElement>('.refresh-icon')!.click();
    await show(jobs.runs);
    expect(read).toHaveBeenCalledTimes(2);

    jobs.forgetHistory();
    fixture.destroy();
    await show(jobs.runs);
    expect(read).toHaveBeenCalledTimes(3);
  });

  it('says its Refresh reads the run history from Dropbox, while the library is there', async () => {
    TestBed.inject(Library).store.set({} as never);
    TestBed.inject(StorageChoice).chosen.set('dropbox');
    await show([aRun()]);
    const icon = element.querySelector<HTMLButtonElement>('.refresh-icon')!;
    expect(icon.getAttribute('aria-label')).toBe('Refresh the list from Dropbox');
    expect(icon.getAttribute('title')).toContain('from Dropbox');

    TestBed.inject(StorageChoice).chosen.set('local');
    fixture.detectChanges();
    expect(icon.getAttribute('aria-label')).toBe('Refresh the list');
  });

  it('says so plainly when nothing has been recorded yet', async () => {
    await show([]);

    expect(element.textContent).toContain('No runs recorded yet');
    expect(element.querySelector('.run')).toBeNull();
  });

  it('tells no library open apart from an empty history', async () => {
    // the history is read out of the library, so without one there is nothing to read -
    // which is not the same as a library nothing has been run in yet
    await show(null);

    expect(element.textContent).toContain('Open a library');
    expect(element.textContent).not.toContain('No runs recorded yet');
  });

  it('names the button that was pressed and how the run ended', async () => {
    await show([aRun()]);

    expect(element.querySelector('.run-name')?.textContent).toContain(
      'Download new bookmarks and update incomplete fics',
    );
    expect(element.querySelector('.run-status')?.textContent?.trim()).toBe('Finished');
    expect(element.querySelector('.run')?.className).toContain('run-success');
  });

  it('calls a run that never reported finishing interrupted', async () => {
    // the record is written when a run starts, so no ending is the evidence - once the
    // helper confirms it is not still working on it
    await show([aRun({ status: 'running', finished: null })]);
    await fixture.whenStable();
    fixture.detectChanges();

    expect(jobs.settles).toBe(1);
    expect(element.querySelector('.run-status')?.textContent?.trim()).toBe('Interrupted');
    expect(element.textContent).toContain('never reported finishing');
  });

  it('does not ask the helper about runs when none is left running', async () => {
    await show([aRun()]);
    expect(jobs.settles).toBe(0);
  });

  it('offers to resume an unfinished scan, and says where it got to', async () => {
    const emitted: string[] = [];
    await show([aRun({ action: 'quick', status: 'stopped',
                       progress: { step: 'download', stepLabel: 'Download or update works' } })]);
    fixture.componentInstance.resume.subscribe((id) => emitted.push(id));

    expect(element.textContent).toContain('Got as far as: Download or update works');
    const button = element.querySelector<HTMLButtonElement>('.run-corner button.retry')!;
    expect(button.disabled).toBe(false);
    button.click();
    expect(emitted).toEqual(['abc']);
  });

  it('offers Retry on a custom run over a slice too - the run window says what it can do', async () => {
    await show([aRun({ action: 'custom', status: 'failed', progress: {},
                       options: { pages: 5, start: 1 } })]);

    const button = element.querySelector<HTMLButtonElement>('.run-corner button.retry')!;
    expect(button.textContent?.trim()).toBe('Retry');
    expect(button.disabled).toBe(false);
  });

  it('offers Retry on every run that has ended - finished and failed ones, fic runs too', async () => {
    await show([
      aRun({ action: 'quick' }),
      aRun({ id: 'x', file: 'x.json', status: 'failed' }),
      aRun({ id: 'w', file: 'w.json', action: 'works', status: 'partial',
             url: 'https://archiveofourown.org/works/1' }),
    ]);

    expect(Array.from(element.querySelectorAll('button')).filter((b) => b.textContent?.includes('Retry')).length).toBe(3);
  });

  it('offers no Retry on a run still going - it is paused and resumed in its own window', async () => {
    jobs.activeRuns.set([{ ...going, id: 'abc' }]);
    // the helper is still running it, so it is not settled as interrupted
    jobs.leaveRunning = true;
    await show([aRun({ status: 'running', finished: null })]);

    expect(Array.from(element.querySelectorAll('button')).filter((b) => b.textContent?.includes('Retry')).length).toBe(0);
  });

  it('links a retry and the run it retried, both ways', async () => {
    await show([
      aRun({ id: 'later', file: 'b.json', action: 'quick', started: '2026-09-14T09:00:00',
             resumes: 'abc', baseline: '2026-09-13T12:01:00' }),
      aRun({ action: 'quick', status: 'interrupted', resumedBy: 'later', progress: {} }),
    ]);

    const said = (element.textContent ?? '').replace(/\s+/g, ' ');
    expect(said).toContain('A retry of the run from');
    expect(said).toContain('Retried by the run from');
  });

  it('does not call a stopped run a failure', async () => {
    await show([aRun({ status: 'stopped' })]);

    expect(element.querySelector('.run-status')?.textContent?.trim()).toBe('Stopped');
  });

  it('shows why a failed run failed', async () => {
    await show([aRun({ status: 'failed', error: 'invalid username or password' })]);

    expect(element.querySelector('.run-error')?.textContent).toContain('invalid username');
  });

  it('shows the file types and only the options that were actually set', async () => {
    await show([
      aRun({ options: { pages: 3, start: 5, series: true, images: false, reindex: false } }),
    ]);

    const said = element.querySelector('.run-settings')?.textContent ?? '';
    expect(said).toContain('JSON, HTML');
    expect(said).toContain('no reindexing');
    expect(said).toContain('up to page 3');
    expect(said).toContain('from page 5');
    expect(said).toContain('all works from encountered series');
    // an option left off is not listed at all
    expect(said).not.toContain('save images');
  });

  it('names the AO3 account each run logged in as', async () => {
    await show([aRun({ username: 'Someone' }), aRun({ file: 'older.json', id: 'older' })]);

    const entries = element.querySelectorAll('.run-settings');
    expect(entries[0].textContent).toContain('AO3 account');
    expect(entries[0].querySelector('.run-account')?.textContent).toBe('Someone');
    // a run recorded before accounts were kept says nothing rather than a blank
    expect(entries[1].textContent).not.toContain('AO3 account');
  });

  it('collapses the fic lists and says how many are in each', async () => {
    // a run that touched a thousand works would otherwise bury the next one
    await show([
      aRun({ reindexed: ['111', '222'], downloaded: ['111'], updated: ['333'] }),
    ]);

    const groups = Array.from(element.querySelectorAll('.ids')).map((d) => ({
      open: (d as HTMLDetailsElement).open,
      summary: d.querySelector('summary')?.textContent?.replace(/\s+/g, ' ').trim(),
    }));

    expect(groups.every((g) => !g.open)).toBe(true);
    expect(groups.map((g) => g.summary)).toEqual([
      'Re-indexed 2',
      'Downloaded 1',
      'Updated 1',
    ]);
  });

  it('links each work number to the work on AO3', async () => {
    await show([aRun({ downloaded: ['1234567'] })]);
    await openFold(element.querySelector<HTMLDetailsElement>('details.ids')!);

    expect(element.querySelector('.id-list a')?.getAttribute('href')).toBe(
      'https://archiveofourown.org/works/1234567',
    );
  });

  it('draws a folded list of works only once it is opened - a run can touch any number', async () => {
    await show([aRun({ downloaded: Array.from({ length: 2_000 }, (_, n) => String(n + 1)) })]);
    const fold = element.querySelector<HTMLDetailsElement>('details.ids')!;

    expect(fold.querySelector('summary')?.textContent).toContain('2,000');
    expect(fold.querySelectorAll('.id-list li').length).toBe(0);
    await openFold(fold);
    expect(fold.querySelectorAll('.id-list li').length).toBe(2_000);
  });

  it("shows a few links as they are, and folds a run's many links away", async () => {
    const links = (n: number) => Array.from({ length: n }, (_, i) => `https://archiveofourown.org/works/${i + 1}`).join('\n');
    await show([aRun({ url: links(LINKS_SHOWN) })]);
    expect(element.querySelectorAll('.run-link a').length).toBe(LINKS_SHOWN);
    expect(element.querySelector('details.run-links')).toBeNull();

    await show([aRun({ url: links(2_000) })]);
    const fold = element.querySelector<HTMLDetailsElement>('details.run-links')!;
    expect(element.querySelector('.run-link')).toBeNull();
    expect(fold.querySelector('summary')?.textContent?.replace(/\s+/g, ' ')).toContain('Works asked for 2,000');
    expect(fold.querySelectorAll('li').length).toBe(0);
    await openFold(fold);
    expect(fold.querySelectorAll('li').length).toBe(2_000);
  });

  it('leaves out a fic list that is empty', async () => {
    await show([aRun({ downloaded: ['111'] })]);

    const summaries = Array.from(element.querySelectorAll('.ids summary')).map((s) =>
      s.textContent?.trim().split(/\s+/)[0],
    );
    expect(summaries).toEqual(['Downloaded']);
  });

  it('keeps what could not be fetched apart from what was never a work', async () => {
    await show([
      aRun({
        failures: [{ id: '111', link: 'https://ao3/works/111', error: 'timed out' }],
        skipped: [{ id: null, link: '', title: 'Gone', error: 'the work has been deleted' }],
      }),
    ]);

    expect(element.querySelector('.ids.failed summary')?.textContent).toContain(
      'Could not be fetched',
    );
    expect(element.textContent).toContain('Not works');
    expect(element.textContent).toContain('the work has been deleted');
  });

  it('records what was decided about undated files', async () => {
    // so a library renamed months ago can be explained
    await show([
      aRun({
        choices: [
          { at: '2026-09-13T12:05:00', question: 'undated', choice: 'stamp',
            date: '2024-06-01', count: 12 },
        ],
      }),
    ]);

    const said = element.querySelector('.run-choices')?.textContent ?? '';
    expect(said).toContain('12');
    expect(said).toContain('stamp');
    expect(said).toContain('2024-06-01');
  });

  it('names the undated works and every file given a date', async () => {
    await show([
      aRun({
        choices: [
          { at: '2026-09-13T12:05:00', question: 'undated', choice: 'stamp',
            date: '2024-06-01', count: 1, files: 2, works: ['111'],
            renamed: [
              { id: '111', from: '111 A - B.html', to: '111 A - B 2024-06-01.html' },
              { id: '111', from: '111 A - B.pdf', to: '111 A - B 2024-06-01.pdf' },
            ] },
        ],
      }),
    ]);

    const said = element.querySelector('.run-choices')?.textContent ?? '';
    // works and files counted apart, so two formats of one work do not read as a miscount
    expect(said).toMatch(/1\s+undated\s+work\s*\(2 files\)/);
    expect(said).toContain('Works without a date');
    expect(element.querySelector('.run-choices a')?.getAttribute('href')).toContain('/works/111');
    expect(said).toContain('Files given a date');
    expect(said).toContain('111 A - B 2024-06-01.pdf');
  });

  it('lists the old copies that could not be deleted, with both file names', async () => {
    await show([
      aRun({
        keptCopies: [
          { id: '123', link: 'https://archiveofourown.org/works/123', error: 'locked',
            file: '123 A - B 2026-09-14.html', old: '123 A - B 2026-01-01.html' },
        ],
      }),
    ]);

    const said = element.querySelector('.run')?.textContent ?? '';
    expect(said).toContain('Downloaded, but needs checking by hand');
    expect(said).toContain('123 A - B 2026-09-14.html');
    expect(said).toContain('123 A - B 2026-01-01.html');
  });

  it('lists the older copies a run removed, and the ones it marked but left', async () => {
    await show([
      aRun({
        choices: [{ at: '2026-09-13T12:05:00', question: 'duplicates', choice: 'newest',
                    count: 2, files: 3 }],
        removals: [
          { id: '111', filetype: 'PDF', file: '111 A 2024-01-01.pdf',
            keeping: '111 A 2025-06-01.pdf', status: 'removed' },
          { id: '222', filetype: 'PDF', file: '222 B.pdf', keeping: '222 B 2025-06-01.pdf',
            status: 'kept', error: 'the file could not be deleted' },
          // a run that died before cleaning up never got to say so
          { id: '333', filetype: 'PDF', file: '333 C.pdf', keeping: '333 C 2025-06-01.pdf',
            status: 'pending' },
        ],
      }),
    ]);

    const said = element.querySelector('.run')?.textContent ?? '';
    expect(said).toContain('keep only the newest');
    expect(said).toContain('Older copies removed');
    expect(said).toContain('111 A 2024-01-01.pdf');
    expect(said).toContain('Marked for removal, still there');
    expect(said).toContain('the file could not be deleted');
    expect(said).toContain('the run ended before its cleanup step');
  });

  it('says whether a run tried FicHub, and lists what came from it', async () => {
    await show([
      aRun({
        choices: [{ at: '2026-09-13T12:05:00', question: 'fichub', choice: 'yes', count: 2,
                    works: ['75354806', '1'] }],
        rescued: [{ id: '75354806', link: 'https://archiveofourown.org/works/75354806',
                    title: 'Wolfbird', downloaded: ['EPUB', 'HTML'] }],
      }),
    ]);

    const said = element.querySelector('.run')?.textContent ?? '';
    expect(said).toContain('AO3 would not give us 2 works');
    expect(said).toContain('to try FicHub');
    expect(said).toContain('Fetched from FicHub instead of AO3');
    expect(said).toContain('Wolfbird');
    expect(said).toContain('EPUB, HTML');
  });

  it('describes the quick scan question as what it was, not as undated files', async () => {
    await show([
      aRun({
        choices: [
          { at: '2026-09-13T12:05:00', question: 'quick-floor', choice: 'full', count: 40 },
        ],
      }),
    ]);

    const said = element.querySelector('.run-choices')?.textContent ?? '';
    expect(said).not.toContain('undated');
    expect(said).toContain('the whole listing');
  });

  it('lists the questions a run asked, each with how it was answered', async () => {
    await show([
      aRun({
        choices: [
          { at: '2026-09-13T12:05:00', question: 'unindexed-copy', choice: 'no', count: 1,
            works: ['1'], formats: ['EPUB'], recommended: 'yes', source: 'AO3', how: 'timed-out',
            replaced: [] },
          { at: '2026-09-13T12:05:30', question: 'unindexed-copy', choice: 'recommended', count: 1,
            works: ['2'], formats: ['PDF', 'HTML'], recommended: 'recommended', source: 'FicHub',
            how: 'answered', replaced: ['PDF'] },
          { at: '2026-09-13T12:06:00', question: 'fichub', choice: 'yes', count: 2, how: 'answered' },
          // from before the record kept how
          { at: '2026-09-13T12:07:00', question: 'quick-floor', choice: 'full', count: 40 },
        ],
      }),
    ]);

    const block = element.querySelector('.run-choices')!;
    expect(block.querySelector('.choices-head')?.textContent).toContain('Questions asked');
    const said = block.textContent ?? '';
    expect(said).toContain('Work 1 had no index entry');
    expect(said).toContain('recommended: yes');
    expect(said).toContain('to keep the copy');
    expect(said).toContain('recommended: some');
    expect(said).toContain('to replace only PDF');
    const hows = Array.from(block.querySelectorAll('.how')).map((x) => x.textContent?.trim());
    expect(hows).toEqual(['Nobody answered in time, so it took the default.', 'You answered.',
                          'You answered.']);
  });

  it('lists a question about a file with no date, naming the file, its dates and the answer', async () => {
    await show([
      aRun({
        choices: [
          { at: '2026-09-13T12:05:00', question: 'inferred-date', scenario: 'ao3-older', choice: 'yes',
            count: 1, works: ['75354806'], formats: ['EPUB'], source: 'AO3', recommended: 'yes',
            fileNames: ['75354806 Wolfbird (14 Dec 2024).epub'], fileDates: { EPUB: '2024-12-14' },
            date: '2026-04-27', how: 'answered' },
          { at: '2026-09-13T12:06:00', question: 'inferred-date', scenario: 'fichub-unknown', choice: 'no',
            count: 1, works: ['75354806'], formats: ['HTML'], source: 'FicHub', recommended: 'no',
            fileNames: ['75354806 Wolfbird.html'], fileDates: { HTML: '' }, date: '2026-04-27',
            how: 'always' },
        ],
      }),
    ]);

    const said = (element.querySelector('.run-choices')?.textContent ?? '').replace(/\s+/g, ' ');
    expect(said).toContain('75354806 Wolfbird (14 Dec 2024).epub');
    expect(said).toContain('looked dated 14 December 2024 (a guess)');
    expect(said).toContain("AO3's version was dated 27 April 2026");
    expect(said).toContain('We recommended replacing it');
    expect(said).toContain("to replace it with AO3's version");
    expect(said).toContain('No date could be read from its name');
    expect(said).toContain('to keep it');
    expect(said).toContain('you chose to always answer this case this way');
  });

  it('lists every run it was given', async () => {
    await show([aRun({ file: 'a.json' }), aRun({ file: 'b.json' })]);

    expect(element.querySelectorAll('.run').length).toBe(2);
  });

  // region the run going now

  const going: ActiveRun = {
    id: 'job-7', action: 'quick', actionName: 'Quick Scan', background: true,
    started: '2026-09-28T10:00:00', paused: false, step: 'Index bookmarks added since your last run',
  };

  it('pins the run going now above the history, saying where it has got to', async () => {
    jobs.activeRuns.set([going]);
    await show([aRun()]);

    const pinned = element.querySelector('[data-active-run]')!;
    expect(element.querySelector('.run')).toBe(pinned);
    expect(pinned.textContent).toContain('Quick Scan');
    expect(pinned.textContent).toContain('In progress - running');
    expect(pinned.textContent).toContain('in the background');
    expect(pinned.textContent).toContain('Index bookmarks added since your last run');
  });

  it('says a paused run is paused', async () => {
    jobs.activeRuns.set([{ ...going, paused: true }]);
    await show([]);

    expect(element.querySelector('[data-active-run]')?.textContent).toContain('In progress - paused');
  });

  it('offers to view a background run\'s progress', async () => {
    jobs.activeRuns.set([going]);
    await show([]);
    const viewed = vi.fn();
    fixture.componentInstance.viewProgress.subscribe(viewed);

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.trim() === 'View progress')!.click();

    expect(viewed).toHaveBeenCalledWith(going);
  });

  it('does not offer to view a run that is not in the background', async () => {
    // it needs the page that started it, which is where its progress is
    jobs.activeRuns.set([{ ...going, background: false }]);
    await show([]);

    const pinned = element.querySelector('[data-active-run]')!;
    expect(pinned.textContent).not.toContain('View progress');
    expect(pinned.textContent).toContain('only in the window that started it');
  });

  it('force stops a run that will not stop, after saying what that means', async () => {
    jobs.activeRuns.set([{ ...going, background: false }]);
    const forced = vi.spyOn(jobs, 'forceStop').mockImplementation(async () => {
      jobs.activeRuns.set([]);
      jobs.runs = [aRun({ id: 'job-7', status: 'stopped', error: 'Force stopped from the History tab' })];
    });
    await show([aRun({ id: 'job-7', status: 'running' })]);
    const button = (text: string) =>
      Array.from(element.querySelectorAll('button')).find((b) => b.textContent?.trim() === text);

    button('Force stop')!.click();
    await fixture.whenStable();
    const confirm = element.querySelector('.force-stop-confirm')?.textContent ?? '';
    expect(confirm).toContain('without waiting for it to reach a safe point');
    expect(confirm).toContain('already saved is kept');
    expect(forced).not.toHaveBeenCalled();

    button('Force stop')!.click();
    for (let i = 0; i < 5; i++) {
      await fixture.whenStable();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }

    expect(forced).toHaveBeenCalledWith('job-7', null);
    expect(element.querySelector('[data-active-run]')).toBeNull();
    expect(element.querySelector('.run')?.textContent).toContain('Stopped');
  });

  it('keeps the run going when the force stop is called off, and says why one failed', async () => {
    jobs.activeRuns.set([going]);
    vi.spyOn(jobs, 'forceStop').mockRejectedValue(new Error('the helper would not stop it (500)'));
    await show([]);
    const button = (text: string) =>
      Array.from(element.querySelectorAll('button')).find((b) => b.textContent?.trim() === text);

    button('Force stop')!.click();
    await fixture.whenStable();
    button('Keep it running')!.click();
    await fixture.whenStable();
    expect(element.querySelector('.force-stop-confirm')).toBeNull();

    button('Force stop')!.click();
    await fixture.whenStable();
    button('Force stop')!.click();
    for (let i = 0; i < 5; i++) {
      await fixture.whenStable();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    expect(element.querySelector('.force-stop-confirm .error')?.textContent).toContain('would not stop it');
  });

  it('pins nothing when no run is going', async () => {
    await show([aRun()]);
    expect(element.querySelector('[data-active-run]')).toBeNull();
  });

  it('marks a run from the history as having been in the background', async () => {
    await show([aRun({ background: true })]);
    expect(element.querySelector('.run-status')?.textContent).toContain('background');
  });

  // endregion

  // region the issues file, for any run

  it('offers every run with issues its issues as a file, saying how many', async () => {
    await show([
      aRun({ failures: [{ id: '1', link: 'l', error: 'gone' }],
             skipped: [{ id: '2', link: 'm', error: 'a series' }] }),
      aRun({ file: 'b.json', id: 'b' }),
    ]);

    const buttons = Array.from(element.querySelectorAll('button')).filter(
      (b) => b.textContent?.includes('Download issues'),
    );
    expect(buttons).toHaveLength(1);
    expect(buttons[0].textContent).toContain('(2)');
  });

  it('saves the same report the run window used to, headed with the run', async () => {
    // caught where the browser would be handed the file
    let saved: Blob | null = null;
    let name = '';
    const created = vi.fn((blob: Blob) => {
      saved = blob;
      return 'blob:report';
    });
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      name = this.download;
    });
    await show([aRun({ id: 'abcdef123', failures: [{ id: '1', link: 'l', error: 'gone' }] })]);

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('Download issues'))!.click();

    const text = await saved!.text();
    expect(text).toContain('# Issues from Download new bookmarks and update incomplete fics');
    expect(text).toContain('## 1 work that could not be downloaded');
    expect(text).toContain('1\tl\tgone');
    expect(name).toBe('run-issues-2026-09-13-abcdef12.txt');
    click.mockRestore();
  });

  // endregion

  // region abandoned runs

  it('calls a run the helper ended for being left paused abandoned, and offers to retry it', async () => {
    await show([aRun({ action: 'quick', actionName: 'Quick Scan', status: 'abandoned',
                       progress: { step: 'index', stepLabel: 'Index bookmarks' } })]);

    expect(element.querySelector('.run-status')?.textContent).toContain('Abandoned');
    expect(element.textContent).toContain('left paused, so the helper ended it');
    expect(Array.from(element.querySelectorAll('button')).some(
      (b) => b.textContent?.includes('Retry'))).toBe(true);
  });

  it('puts Retry in the accent colour under the status pill, top right', async () => {
    await show([aRun({ status: 'failed' })]);
    const corner = element.querySelector('.run-head .run-corner')!;
    expect(corner.firstElementChild?.classList).toContain('run-status');
    expect(corner.lastElementChild?.classList).toContain('retry');
    expect(corner.lastElementChild?.classList).toContain('primary');
  });

  it('offers Retry on an abandoned run of any workflow', async () => {
    await show([aRun({ action: 'sync', status: 'abandoned' })]);
    expect(element.querySelector('.run-corner button.retry')?.textContent).toContain('Retry');
  });

  it('says when a paused run in progress will be abandoned', async () => {
    jobs.activeRuns.set([{ ...going, paused: true, abandonsAt: '2026-09-28T13:10:00' }]);
    await show([]);

    const expected = new Date('2026-09-28T13:10:00')
      .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    expect(element.querySelector('[data-active-run]')?.textContent).toContain(
      `Abandoned at ${expected} unless resumed`);
  });

  // endregion

  // region the log, and runs the helper has not confirmed

  it('offers the log of any run that kept one', async () => {
    await show([aRun({ logLines: 12 }), aRun({ file: 'b.json', id: 'b', logLines: 0 })]);

    const buttons = Array.from(element.querySelectorAll('button')).filter(
      (b) => b.textContent?.includes('Download log'),
    );
    expect(buttons).toHaveLength(1);
  });

  it('saves the log read back out of the run\'s own file, saying what was dropped', async () => {
    let saved: Blob | null = null;
    let name = '';
    Object.assign(URL, { createObjectURL: vi.fn((blob: Blob) => ((saved = blob), 'blob:x')),
                         revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      name = this.download;
    });
    const read = vi.fn(async () => JSON.stringify({
      log: ['logging in as Someone', 'new download: 1 A.html'], logTrimmed: 3,
    }));
    TestBed.inject(Library).store.set({ read } as never);
    await show([aRun({ id: 'abcdef123', file: 'r.json', logLines: 2 })]);

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('Download log'))!.click();
    await fixture.whenStable();

    expect(read).toHaveBeenCalledWith('runs/r.json');
    const text = await saved!.text();
    expect(text).toContain('# Download new bookmarks and update incomplete fics, started');
    expect(text).toContain('the first 3 lines were dropped');
    expect(text.trim().split('\n').slice(-2)).toEqual(['logging in as Someone', 'new download: 1 A.html']);
    expect(name).toBe('run-log-2026-09-13-abcdef12.txt');
    click.mockRestore();
  });

  it('puts what the run was asked to do, and the settings it ran under, above its log', async () => {
    let saved: Blob | null = null;
    Object.assign(URL, { createObjectURL: vi.fn((blob: Blob) => ((saved = blob), 'blob:x')),
                         revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const read = vi.fn(async () => JSON.stringify({
      username: 'Someone',
      url: 'https://archiveofourown.org/works/1\nhttps://archiveofourown.org/works/2',
      filetypes: ['HTML', 'JSON'],
      options: { reindex: false, skipLogin: true },
      settings: { file: '/x/settings.ini', extraWaitTime: 5, maxRetries: 30 },
      background: true,
      log: ['[2026-10-30 14:47:47 UTC] looking up work 1'],
    }));
    TestBed.inject(Library).store.set({ read } as never);
    await show([aRun({ file: 'r.json', logLines: 1 })]);

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('Download log'))!.click();
    await fixture.whenStable();

    const text = await saved!.text();
    for (const line of [
      '# Links (2):',
      '#   https://archiveofourown.org/works/2',
      '# File types: HTML, JSON',
      '# Options: no reindexing',
      '# Ran in the background',
      '# Run options:',
      '#   skipLogin: true',
      '# settings.ini:',
      '#   extraWaitTime: 5',
      '#   maxRetries: 30',
    ]) {
      expect(text.split('\n')).toContain(line);
    }
    // neither the account nor where settings.ini is: a log gets passed around
    expect(text).not.toContain('AO3 account');
    expect(text).not.toContain('/x/settings.ini');
    // the settings come before the log, and the log is still last
    expect(text.indexOf('maxRetries')).toBeLessThan(text.indexOf('looking up work 1'));
    expect(text.trim().split('\n').at(-1)).toBe('[2026-10-30 14:47:47 UTC] looking up work 1');
    click.mockRestore();
  });

  async function logSaved(live: Record<string, unknown> | null): Promise<string> {
    let saved: Blob | null = null;
    Object.assign(URL, { createObjectURL: vi.fn((blob: Blob) => ((saved = blob), 'blob:x')),
                         revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const read = vi.fn(async () => JSON.stringify({ log: ['[2026-10-31 09:00:00 UTC] saved line'] }));
    TestBed.inject(Library).store.set({ read } as never);
    jobs.leaveRunning = true;
    jobs.activeRuns.set([{
      id: 'job-7', action: 'quick', actionName: 'Quick Scan', background: false,
      started: '2026-10-31T09:00:00', paused: false, step: '',
    }]);
    const asked = vi.spyOn(jobs, 'liveRecord').mockResolvedValue(live);
    await show([aRun({ id: 'job-7', file: 'r.json', status: 'running', finished: null, logLines: 1 })]);

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('Download log'))!.click();
    await fixture.whenStable();

    expect(asked).toHaveBeenCalledWith('job-7');
    click.mockRestore();
    return saved!.text();
  }

  it('takes a running run\'s log from the helper, which has every line the window shows', async () => {
    const text = await logSaved({
      log: ['[2026-10-31 09:00:00 UTC] saved line', '[2026-10-31 09:00:30 UTC] not saved yet'],
    });
    expect(text.trim().split('\n').at(-1)).toBe('[2026-10-31 09:00:30 UTC] not saved yet');
  });

  it('falls back to the run\'s file when the helper does not have the run', async () => {
    const text = await logSaved(null);
    expect(text.trim().split('\n').at(-1)).toBe('[2026-10-31 09:00:00 UTC] saved line');
  });

  it('does not call a run running when the helper has not said it is', async () => {
    jobs.leaveRunning = true;
    await show([aRun({ status: 'running', finished: null })]);
    // settleInterrupted is stubbed to leave it, as when the helper does not answer
    expect(element.querySelector('.run-status')?.textContent).toContain('not confirmed');
  });

  it('names a run going on another helper as such', async () => {
    jobs.leaveRunning = true;
    await show([aRun({ status: 'running', finished: null, helper: 'https://elsewhere.example' })]);
    expect(element.querySelector('.run-status')?.textContent).toContain('Running on another helper');
  });

  // endregion

  // region collection runs

  it('shows the link a collection run was pointed at, and what it was asked to do', async () => {
    await show([aRun({ action: 'collection', url: 'https://archiveofourown.org/collections/x',
                       options: { collectionWorks: true } })]);

    expect(element.querySelector('.run-link')?.textContent).toContain('collections/x');
    expect(element.textContent).toContain('indexed and downloaded the works in them');
  });

  it('offers no Run again on any run', async () => {
    await show([aRun({ action: 'collections' }), aRun({ file: 'b', id: 'b', action: 'work' }),
                aRun({ file: 'c', id: 'c', action: 'bookmarks', status: 'stopped' })]);

    const buttons = Array.from(element.querySelectorAll('button')).map((b) => b.textContent?.trim());
    expect(buttons).not.toContain('Run again');
  });

  it('offers Retry on an unfinished collection run', async () => {
    const emitted: string[] = [];
    await show([aRun({ action: 'collection', status: 'interrupted', progress: {},
                       url: 'https://archiveofourown.org/collections/x' })]);
    fixture.componentInstance.resume.subscribe((id) => emitted.push(id));

    const button = element.querySelector<HTMLButtonElement>('.run-corner button.retry')!;
    expect(button.textContent?.trim()).toBe('Retry');
    button.click();
    expect(emitted).toEqual(['abc']);
  });

  it('calls a run whose indexing broke off partly finished, and says exactly where it stopped', async () => {
    await show([aRun({ action: 'bookmarks', status: 'partial', indexFailures: [{
      kind: 'listing', walk: 'all', sort: 'bookmarked', firstPage: 1, lastPage: 12,
      failedPage: 13, totalPages: 80, works: 240, reachedBookmarked: '2023-05-01',
      error: 'the page would not load',
    }] })]);

    expect(element.querySelector('.run-status')?.textContent?.trim()).toBe('Partly Finished');
    // folded to begin with, saying only how many places, and drawn only once opened
    const gaps = element.querySelector<HTMLDetailsElement>('details.index-gaps')!;
    expect(gaps.open).toBe(false);
    expect(gaps.textContent?.replace(/\s+/g, ' ').trim()).toBe('Indexing did not finish (1 place)');
    gaps.open = true;
    gaps.dispatchEvent(new Event('toggle'));
    fixture.detectChanges();
    const said = (gaps.textContent ?? '').replace(/\s+/g, ' ');
    expect(said).toContain('Indexing did not finish');
    expect(said).toContain('Your bookmarks stopped at page 13 of 80: the page would not load.');
    expect(said).toContain('Pages 1 to 12 were indexed (240 works).');
    expect(said).toContain('reached works bookmarked on 2023-05-01');
    // and it is one of the run's issues
    expect(element.querySelector('.run-issues')?.textContent).toContain('Download issues (1)');
  });

  // endregion
});
