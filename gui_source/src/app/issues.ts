import { FicHubOlder, IndexGap, RepairClash, RunHistory, WorkFailure } from './jobs';
import { writtenDate } from './preferences';

/** everything a run reported that needs a person's attention, by kind */
export interface RunIssues {
  /** where indexing broke off - a listing, a collection, or a fic's own page */
  indexGaps?: IndexGap[];
  /** works that should have downloaded and did not */
  failures: WorkFailure[];
  /** new copies downloaded where the older copy could not be deleted, or was not confirmed */
  keptCopies: WorkFailure[];
  /** older copies marked for removal that are still there */
  notRemoved: WorkFailure[];
  /** bookmarks that were never works */
  skipped: WorkFailure[];
  /** formats taken from FicHub that may be older cached copies */
  fichubOlder?: FicHubOlder[];
  /** files Resolve issues asked to repair, not repaired: the name each would get is taken */
  repairClashes?: RepairClash[];
}

/** how many entries there are across every kind */
export function issueCount(issues: RunIssues): number {
  return (
    (issues.indexGaps?.length ?? 0) +
    issues.failures.length +
    issues.keptCopies.length +
    issues.notRemoved.length +
    issues.skipped.length +
    (issues.fichubOlder?.length ?? 0) +
    (issues.repairClashes?.length ?? 0)
  );
}

/**
 * A run's issues as its history file records them.
 *
 * The history file is written as the run goes, so this works for any run the History tab
 * lists - one that finished with the page shut, one from months ago, one that was
 * interrupted. An older copy still `pending` belongs to a run that never reached its cleanup
 * step, which is itself the reason it is still there.
 */
export function issuesOf(run: RunHistory): RunIssues {
  return {
    indexGaps: run.indexFailures ?? [],
    failures: run.failures ?? [],
    keptCopies: run.keptCopies ?? [],
    notRemoved: (run.removals ?? [])
      .filter((x) => x.status !== 'removed')
      .map((x) => ({
        id: x.id,
        link: '',
        file: x.file,
        old: x.keeping,
        error:
          x.error ?? (x.status === 'pending' ? 'the run ended before its cleanup step' : ''),
      })),
    skipped: run.skipped ?? [],
    fichubOlder: run.fichubOlder ?? [],
    repairClashes: run.repairClashes ?? [],
  };
}

/** each format FicHub gave a work: one you had no file of, or one that replaced yours */
export function fichubOlderFormats(item: FicHubOlder): string {
  const taken = item.formats.map((f) => `${f} (you had no file)`);
  const replaced = Object.entries(item.replaced ?? {}).map(([f, date]) =>
    `${f} (replaced yours, ${date ? `dated ${writtenDate(date)}` : 'with no date in its name'})`);
  return [...taken, ...replaced].join(', ');
}

/** a repair a name clash stopped, in words */
export function repairClashWords(item: RepairClash): string {
  return `${item.format}: failed to repair from ${item.site} due to a name clash - ` +
    `${item.wanted} is already another file, so ${item.file} was kept as it is`;
}

/** formats taken from an older FicHub copy, in words: which, FicHub's date, and the last
 *  known update date we have, and where that date is from */
export function fichubOlderWords(item: FicHubOlder): string {
  const from = item.latestFrom ? `, from your ${item.latestFrom}` : '';
  return `${item.title ? item.title + ' - ' : ''}${fichubOlderFormats(item)}: FicHub's copy is dated ` +
    `${writtenDate(item.fichub)}, older than the last known update date we have ` +
    `(${writtenDate(item.latest)}${from}) - it may be an older cached copy`;
}

/**
 * Every issue, as the one text file that gets saved.
 *
 * One file with a heading per kind rather than a file per list: the lists answer different
 * questions and stay apart on screen, but somebody saving them wants the whole account of
 * the run in one place. A kind with nothing in it gets no heading at all.
 */
export function issuesReport(issues: RunIssues, heading = 'Issues from this run', when = new Date()): string {
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const clean = (text: string | undefined) => (text ?? '').replace(/\s+/g, ' ');
  const lines = [`# ${heading}`, `# ${when.toISOString()}`, '# rows are tab separated'];
  const section = (title: string, columns: string, rows: string[]) => {
    if (!rows.length) return;
    lines.push('', `## ${title}`, `# ${columns}`, ...rows);
  };

  section(
    plural(issues.indexGaps?.length ?? 0, 'place indexing did not finish',
      'places indexing did not finish'),
    'what, where it stopped, how far it got',
    (issues.indexGaps ?? []).map((gap) => clean(describeGap(gap))),
  );
  section(
    plural(issues.failures.length, 'work that could not be downloaded',
      'works that could not be downloaded'),
    'work id, link, reason',
    issues.failures.map((row) => [row.id ?? '', row.link ?? '', clean(row.error)].join('\t')),
  );
  section(
    plural(issues.keptCopies.length,
      'new copy downloaded that needs checking by hand',
      'new copies downloaded that need checking by hand'),
    'work id, link, new file, older copy still on disk (if any), reason',
    issues.keptCopies.map((row) =>
      [row.id ?? '', row.link ?? '', row.file ?? '', row.old ?? '', clean(row.error)].join('\t'),
    ),
  );
  section(
    plural(issues.notRemoved.length,
      'older copy marked for removal that is still there',
      'older copies marked for removal that are still there'),
    'work id, older copy, newest copy (kept), reason',
    issues.notRemoved.map((row) =>
      [row.id ?? '', row.file ?? '', row.old ?? '', clean(row.error)].join('\t'),
    ),
  );
  section(
    plural(issues.skipped.length, 'bookmark that is not a work', 'bookmarks that are not works'),
    'work or series id, link, reason',
    issues.skipped.map((row) => [row.id ?? '', row.link ?? '', clean(row.error)].join('\t')),
  );
  section(
    plural(issues.fichubOlder?.length ?? 0,
      'work given a format from FicHub that may be an older cached copy',
      'works given a format from FicHub that may be an older cached copy'),
    'work id, link, formats (you had no file, or one it replaced), FicHub\'s date, last known update date, where that date is from',
    (issues.fichubOlder ?? []).map((row) =>
      [row.id, row.link, fichubOlderFormats(row), row.fichub, row.latest,
        row.latestFrom ? `your ${row.latestFrom}` : 'the index'].join('\t'),
    ),
  );
  section(
    plural(issues.repairClashes?.length ?? 0,
      'file that failed to repair due to a name clash',
      'files that failed to repair due to a name clash'),
    'work id, link, format, from, your file (kept), the name it would have been given (already taken)',
    (issues.repairClashes ?? []).map((row) =>
      [row.id, row.link, row.format, row.site, row.file, row.wanted].join('\t'),
    ),
  );
  return lines.join('\n') + '\n';
}

/**
 * Exactly where indexing broke off, in words: which listing or collection, the pages read, the
 * page that failed, and how far back in date the listing got - the helper's
 * `describe_listing_gap`, said the same way so the History card and the issues file agree with
 * the run's own window.
 */
/** why something failed, in words: the recorded reason, then the error itself */
export function failureWords(failed: { reason?: string; status?: number; error?: string }): string {
  const error = failed.error ?? '';
  const words =
    failed.reason === 'maintenance' ? 'AO3 was down for maintenance'
    : failed.reason === 'status' && failed.status ? `AO3 answered with status ${failed.status}`
    : failed.reason === 'connection' ? 'AO3 could not be reached'
    : failed.reason === 'no-data' ? 'the page AO3 served had nothing on it that could be read'
    : '';
  if (!words) return error;
  return error && error !== words ? `${words} (${error})` : words;
}

export function describeGap(gap: IndexGap): string {
  if (gap.kind === 'work') {
    return `Work ${gap.id}: its page on AO3 could not be read, so it was not indexed - ${failureWords(gap)}.`;
  }
  const walk = gap.walk === 'bookmarked' ? ' sorted by date bookmarked'
    : gap.walk === 'updated' ? ' sorted by date updated' : '';
  const where = gap.kind === 'collection'
    ? `The ${gap.items ?? 'works'} of collection ${gap.collection}`
    : `Your bookmarks${walk}`;
  const total = gap.totalPages ? ` of ${gap.totalPages}` : '';
  const read = gap.lastPage
    ? `Pages ${gap.firstPage ?? 1} to ${gap.lastPage} were indexed (${gap.works ?? 0} works).`
    : 'No page was indexed before it.';
  const date = gap.sort === 'updated' ? gap.reachedUpdated : gap.reachedBookmarked;
  const kind = gap.sort === 'updated' ? 'updated' : 'bookmarked';
  const reached = gap.lastPage && date
    ? ` The last page read reached works ${kind} on ${date}; anything ${kind} before that was not reached.`
    : '';
  return `${where} stopped at page ${gap.failedPage}${total}: ${failureWords(gap)}. ${read}${reached}`;
}

/**
 * Hand the text over as a file the browser saves.
 *
 * Done in the page rather than by the helper: it is a few lines the browser can save
 * directly, so it needs neither a round trip nor a second thing that writes to disk.
 */
export function saveText(text: string, name: string): void {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${name}.txt`;
  link.click();
  // the save has its own copy once started, so the handle can go
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** one kind of trouble an earlier attempt ran into: a sentence, and the first few cases */
export interface AttemptIssue {
  summary: string;
  details: string[];
  /** how many cases there were beyond the ones in `details` */
  more: number;
}

/** how many cases of each kind the retry page names before saying how many more */
export const ATTEMPT_ISSUES_SHOWN = 5;

/**
 * What went wrong on a run, for the retry page - so whoever retries it knows what the retry
 * is up against before choosing how. Read from the run's own record, as History reads it:
 * how it ended, where its indexing broke off, what it could not download, and what it left
 * to check by hand. Bookmarks that were never works are left out - retrying cannot change
 * them. Empty when the record holds nothing that went wrong.
 */
export function attemptIssues(run: RunHistory): AttemptIssue[] {
  const found: AttemptIssue[] = [];
  const plural = (n: number, one: string, many: string) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
  const add = <T>(summary: string, items: T[], say: (item: T) => string) => {
    found.push({
      summary,
      details: items.slice(0, ATTEMPT_ISSUES_SHOWN).map(say),
      more: Math.max(0, items.length - ATTEMPT_ISSUES_SHOWN),
    });
  };
  const ending: Partial<Record<RunHistory['status'], string>> = {
    failed: 'It failed',
    stopped: 'It was stopped before it finished',
    interrupted: 'It was interrupted - the helper went away before it finished',
    abandoned: 'It was abandoned after being left paused',
  };
  const ended = ending[run.status];
  if (ended || run.error) {
    const why = run.error ? (ended ? `${ended}: ${run.error}` : run.error) : `${ended}.`;
    found.push({ summary: why, details: [], more: 0 });
  }
  const issues = issuesOf(run);
  const gaps = issues.indexGaps ?? [];
  if (gaps.length) {
    add(`Its indexing broke off in ${plural(gaps.length, 'place', 'places')}.`, gaps, describeGap);
  }
  if (issues.failures.length) {
    add(
      `${plural(issues.failures.length, 'work', 'works')} could not be downloaded.`,
      issues.failures,
      (x) => `${x.id ? `Work ${x.id}` : x.link}: ${failureWords(x)}`,
    );
  }
  if (issues.keptCopies.length) {
    add(
      `${plural(issues.keptCopies.length, 'copy needs', 'copies need')} checking by hand.`,
      issues.keptCopies,
      (x) => `${x.file ?? x.id ?? x.link}: ${x.error}`,
    );
  }
  if (issues.notRemoved.length) {
    add(
      `${plural(issues.notRemoved.length, 'older copy was', 'older copies were')} not removed.`,
      issues.notRemoved,
      (x) => `${x.file ?? x.id}${x.error ? `: ${x.error}` : ''}`,
    );
  }
  return found;
}
