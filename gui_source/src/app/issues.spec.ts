import { describe, expect, it } from 'vitest';
import { describeGap, failureWords, fichubOlderWords, issueCount, issuesOf, issuesReport, repairClashWords } from './issues';
import { RunHistory } from './jobs';

function aRun(over: Partial<RunHistory> = {}): RunHistory {
  return {
    file: 'a.json', id: 'a', action: 'sync', actionName: 'Sync', started: '', finished: null,
    status: 'success', filetypes: [], options: {}, reindexed: [], downloaded: [], updated: [],
    choices: [], failures: [], skipped: [], error: '', ...over,
  };
}

describe('issuesOf', () => {
  it('reads every kind of issue out of a run\'s history file', () => {
    const found = issuesOf(aRun({
      failures: [{ id: '1', link: 'l', error: 'gone' }],
      skipped: [{ id: '2', link: 'm', error: 'a series' }],
      keptCopies: [{ id: '3', link: 'n', error: 'locked', file: 'new', old: 'old' }],
      removals: [
        { id: '4', filetype: 'HTML', file: '4 old.html', keeping: '4 new.html', status: 'removed' },
        { id: '5', filetype: 'HTML', file: '5 old.html', keeping: '5 new.html', status: 'kept',
          error: 'in use' },
      ],
    }));

    expect(issueCount(found)).toBe(4);
    // only the ones still there are issues
    expect(found.notRemoved).toEqual([
      { id: '5', link: '', file: '5 old.html', old: '5 new.html', error: 'in use' },
    ]);
  });

  it('says why an older copy a run never got round to is still there', () => {
    // a record still saying pending is a run that ended before its cleanup step
    const found = issuesOf(aRun({ removals: [
      { id: '6', filetype: 'HTML', file: '6 old.html', keeping: '6 new.html', status: 'pending' },
    ] }));

    expect(found.notRemoved[0].error).toContain('before its cleanup step');
  });

  it('copes with a history file from before any of these were recorded', () => {
    const old = aRun();
    delete (old as Partial<RunHistory>).keptCopies;
    expect(issueCount(issuesOf(old))).toBe(0);
  });
});

describe('issuesReport', () => {
  it('leaves out a kind with nothing in it', () => {
    const report = issuesReport(issuesOf(aRun({ failures: [{ id: '1', link: 'l', error: 'x' }] })));
    expect(report.split('\n').filter((x) => x.startsWith('## '))).toEqual([
      '## 1 work that could not be downloaded',
    ]);
  });
});

describe('why something failed, in words', () => {
  it('names maintenance, a status, a connection and an empty page', () => {
    expect(failureWords({ reason: 'maintenance', error: 'ao3 is down' }))
      .toBe('AO3 was down for maintenance (ao3 is down)');
    expect(failureWords({ reason: 'status', status: 404, error: 'Request failed with status code 404' }))
      .toBe('AO3 answered with status 404 (Request failed with status code 404)');
    expect(failureWords({ reason: 'connection', error: '' })).toBe('AO3 could not be reached');
    expect(failureWords({ reason: 'no-data', error: 'x' }))
      .toBe('the page AO3 served had nothing on it that could be read (x)');
  });

  it('falls back to the error itself for anything else, and for older records', () => {
    expect(failureWords({ reason: 'other', error: 'odd' })).toBe('odd');
    expect(failureWords({ error: 'odd' })).toBe('odd');
  });

  it('says why a listing stopped', () => {
    expect(describeGap({ kind: 'listing', failedPage: 3, error: 'e', reason: 'status', status: 403 }))
      .toContain('stopped at page 3: AO3 answered with status 403');
  });
});

describe('older FicHub copies', () => {
  const run = {
    fichubOlder: [{ id: '75354806', link: 'https://archiveofourown.org/works/75354806', title: 'Wolfbird',
      formats: ['HTML'], replaced: { EPUB: '2026-04-01' }, fichub: '2026-04-27', latest: '2026-05-10', latestFrom: '' }],
  } as unknown as RunHistory;

  it('counts as an issue, and gets a section of its own in the issues file', () => {
    const issues = issuesOf(run);
    expect(issueCount(issues)).toBe(1);
    const report = issuesReport(issues, 'Issues', new Date('2026-11-08T00:00:00Z'));
    expect(report).toContain('## 1 work given a format from FicHub that may be an older cached copy');
    expect(report).toContain('75354806\thttps://archiveofourown.org/works/75354806\tHTML (you had no file), EPUB (replaced yours, dated 1 April 2026)\t2026-04-27\t2026-05-10\tthe index');
  });

  it('is said in words with both dates', () => {
    expect(fichubOlderWords(run.fichubOlder![0])).toBe(
      "Wolfbird - HTML (you had no file), EPUB (replaced yours, dated 1 April 2026): FicHub's copy is dated 27 April 2026, older than the last known update date we have (10 May 2026) - it may be an older cached copy");
  });
});

describe('repairs a name clash stopped', () => {
  const run = {
    repairClashes: [{ id: '1', link: 'https://archiveofourown.org/works/1', format: 'HTML', site: 'FicHub',
      file: '1 Fic - Someone.html', wanted: '1 Fic - Someone 2026-05-01.html' }],
  } as unknown as RunHistory;

  it('counts as an issue, and gets a section of its own in the issues file', () => {
    const issues = issuesOf(run);
    expect(issueCount(issues)).toBe(1);
    const report = issuesReport(issues, 'Issues', new Date('2026-11-08T00:00:00Z'));
    expect(report).toContain('## 1 file that failed to repair due to a name clash');
    expect(report).toContain('1\thttps://archiveofourown.org/works/1\tHTML\tFicHub\t1 Fic - Someone.html\t1 Fic - Someone 2026-05-01.html');
  });

  it('says where the repair was from, and which name was taken', () => {
    expect(repairClashWords(run.repairClashes![0])).toBe(
      'HTML: failed to repair from FicHub due to a name clash - 1 Fic - Someone 2026-05-01.html is already another file, so 1 Fic - Someone.html was kept as it is');
  });
});
