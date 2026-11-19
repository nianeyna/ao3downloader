/**
 * Works whose files are in the library with no index entry - downloaded some other way, or
 * kept from before the index existed - found so they can be imported.
 *
 * A file counts when it is in `works/`, is one of the formats a run downloads, and its name
 * starts with a work number (`workIdFromFilename`, the rule every file is paired to the index
 * by). Its work is unindexed when the index holds no entry with that number.
 *
 * Importing one is two things, both asked about first (`ImportDialog`):
 * - **dating** an undated file - giving its name the ` YYYY-MM-DD` it should end in, the
 *   version it holds - which the page does itself, by renaming it. A run can only judge a
 *   dated copy against AO3's version, and leaves an undated one alone;
 * - **the import run** (`import`), which indexes each work from AO3, marks it imported, and
 *   fetches the formats asked for.
 */

import { Injectable, computed, inject, signal } from '@angular/core';
import { dateFromFilename, workIdFromFilename } from './bookmarks';
import { numberSpan } from './naming';
import { Misnamed, misnamedFiles } from './renames';
import { WORKS_FOLDER } from './library-setup';
import { Library, OpenableFormat, OPENABLE_FORMATS } from './library';
import { DropboxLibraryStore, LibraryStore } from './library-store';
import { DropboxError } from './dropbox';
import { VisitLog } from './visit-log';

/** one file in `works/` named for a work */
export interface FoundFile {
  /** the work number its name starts with */
  id: string;
  /** its path in the library, `works/<name>` */
  path: string;
  name: string;
  format: OpenableFormat;
  /** the `YYYY-MM-DD` its name ends in, or '' when it has none */
  date: string;
  /**
   * a file of a work with no index entry that is not offered for the index question - its
   * work was excluded from it - so it is offered for dating only, never looked up
   */
  unindexed?: boolean;
  /** on the dates list: never offered for dating, though its work may still be asked about */
  noDating?: boolean;
}

/** a work in the library with no index entry, and its files */
export interface FoundWork {
  id: string;
  files: FoundFile[];
}

/** which of the downloaded formats a file name is, if any */
export function formatOf(name: string): OpenableFormat | null {
  const ext = /\.([a-z0-9]+)$/i.exec(name)?.[1]?.toLowerCase();
  if (ext === 'htm') return 'html';
  return (OPENABLE_FORMATS as string[]).includes(ext ?? '') ? (ext as OpenableFormat) : null;
}

/**
 * The works among `paths` (library paths, as `LibraryStore.list` gives them) with no entry in
 * `indexed`, each with its files - by work number, smallest first, so a list reads in order.
 * Only files directly in `works/`, which is the one place a run looks for them.
 */
export function unindexedWorks(paths: Iterable<string>, indexed: ReadonlySet<string>): FoundWork[] {
  return byWork(workFiles(paths).filter((f) => !indexed.has(f.id)));
}

/**
 * The files of works the index **does** have whose names carry no date. A run cannot tell
 * whether AO3 has a newer version of one, and stops to ask about it - so they are offered for
 * dating up front too, beside the unindexed works.
 */
export function undatedIndexedFiles(paths: Iterable<string>, indexed: ReadonlySet<string>): FoundFile[] {
  return byWork(workFiles(paths).filter((f) => indexed.has(f.id) && !f.date)).flatMap((w) => w.files);
}

/** every file directly in works/ that is one of the formats a run downloads, named for a work */
function workFiles(paths: Iterable<string>): FoundFile[] {
  const found: FoundFile[] = [];
  for (const raw of paths) {
    const path = raw.replace(/^\/+/, '');
    const parts = path.split('/');
    if (parts.length !== 2 || parts[0].toLowerCase() !== WORKS_FOLDER) continue;
    const name = parts[1];
    const format = formatOf(name);
    const id = workIdFromFilename(name);
    if (!format || !id) continue;
    found.push({ id, path, name, format, date: dateFromFilename(name) });
  }
  return found;
}

/** files grouped by work - by work number, smallest first, so a list reads in order */
function byWork(files: FoundFile[]): FoundWork[] {
  const works = new Map<string, FoundFile[]>();
  for (const file of files) works.set(file.id, [...(works.get(file.id) ?? []), file]);
  return [...works.entries()]
    .sort(([a], [b]) => a.length - b.length || a.localeCompare(b))
    .map(([id, list]) => ({ id, files: list.sort((a, b) => a.name.localeCompare(b.name)) }));
}

/** the files among these works with no date in their name */
/**
 * What the import has to resolve, counted in files - the one count the reminder above the tabs
 * and the import window's own overview both give, so the two can never disagree.
 */
/**
 * What a download replacing a file of the same name leaves behind if the app stops part-way
 * (the helper's `Ao3.swap_in`): the new file written beside yours, and yours moved aside while the
 * new one goes in. Names nothing reads as a work, so nothing else ever sees them.
 */
export const SWAP_NEW_SUFFIX = '.ficfairy-new';
export const SWAP_OLD_SUFFIX = '.ficfairy-old';

/** one file a swap was part-way through, and what is beside it */
export interface SwapLeftover {
  /** the file's own name, which the swap was putting the new copy into */
  path: string;
  /** your copy, moved aside */
  old?: string;
  /** the new copy, written beside it */
  fresh?: string;
  /** whether a file is at `path` now */
  inPlace: boolean;
}

/**
 * Every file in `works/` a swap was left part-way through. **Your copy set aside is always put
 * back** under its own name (`restore`) - a new copy in its place is removed first, since it may
 * not be whole - and a new copy beside your file is removed. A new copy with nothing whole beside
 * it is left alone: it may be all there is.
 */
export function swapLeftovers(paths: Iterable<string>): SwapLeftover[] {
  const all = [...paths];
  const present = new Set(all.map((p) => p.toLowerCase()));
  const found = new Map<string, SwapLeftover>();
  for (const path of all) {
    const old = path.endsWith(SWAP_OLD_SUFFIX);
    if (!old && !path.endsWith(SWAP_NEW_SUFFIX)) continue;
    const base = path.slice(0, -(old ? SWAP_OLD_SUFFIX : SWAP_NEW_SUFFIX).length);
    const entry = found.get(base) ?? { path: base, inPlace: present.has(base.toLowerCase()) };
    if (old) entry.old = path;
    else entry.fresh = path;
    found.set(base, entry);
  }
  return [...found.values()].filter((e) => e.old || e.inPlace).sort((a, b) => a.path.localeCompare(b.path));
}

/** what tidying one leftover does: put your set-aside copy back, or only remove an unfinished new one */
export function leftoverAction(leftover: SwapLeftover): 'restore' | 'tidy' {
  return leftover.old ? 'restore' : 'tidy';
}

export interface ImportIssueCounts {
  /** files left part-way through being replaced by a download */
  leftoverFiles?: number;
  /** files named in a way the app cannot match to a work */
  misnamedFiles: number;
  /** files in a set of two or more of one work in one format */
  duplicateFiles: number;
  /** files with no date in their name that dating would offer */
  undatedFiles: number;
  /** files of works with no index entry */
  unindexedFiles: number;
}

export function importIssueCounts(
  works: FoundWork[],
  undatedElsewhere: FoundFile[],
  duplicates: DuplicateGroup[],
  misnamed: readonly { files: unknown[] }[] = [],
  leftovers: readonly SwapLeftover[] = [],
): ImportIssueCounts {
  return {
    leftoverFiles: leftovers.length,
    misnamedFiles: misnamed.reduce((n, f) => n + f.files.length, 0),
    duplicateFiles: duplicates.reduce((n, g) => n + g.files.length, 0),
    undatedFiles: undatedFiles(works).length + undatedElsewhere.length,
    unindexedFiles: works.reduce((n, w) => n + w.files.length, 0),
  };
}

export interface ImportIssueLine {
  kind: 'leftovers' | 'misnamed' | 'duplicates' | 'undated' | 'unindexed';
  text: string;
}

/** the overview's lines, in its order: names, duplicates, then dates, then index */
export function importIssueLines(counts: ImportIssueCounts): ImportIssueLine[] {
  const n = (x: number) => x.toLocaleString();
  const lines: ImportIssueLine[] = [];
  if (counts.leftoverFiles) {
    lines.push({ kind: 'leftovers',
      text: `${n(counts.leftoverFiles)} ${counts.leftoverFiles === 1 ? 'file was' : 'files were'} left part-way through being replaced by an interrupted download` });
  }
  if (counts.misnamedFiles) {
    lines.push({ kind: 'misnamed',
      text: `${n(counts.misnamedFiles)} ${counts.misnamedFiles === 1 ? 'file is' : 'files are'} named in a way this app cannot match to a work` });
  }
  if (counts.duplicateFiles) {
    lines.push({ kind: 'duplicates',
      text: `${n(counts.duplicateFiles)} ${counts.duplicateFiles === 1 ? 'file is a duplicate' : 'files are duplicates'}` });
  }
  if (counts.undatedFiles) {
    lines.push({ kind: 'undated',
      text: `${n(counts.undatedFiles)} ${counts.undatedFiles === 1 ? 'file has' : 'files have'} no date` });
  }
  if (counts.unindexedFiles) {
    lines.push({ kind: 'unindexed',
      text: `${n(counts.unindexedFiles)} ${counts.unindexedFiles === 1 ? 'file belongs to a work that has' : 'files belong to works that have'} no index` });
  }
  return lines;
}

export function undatedFiles(works: FoundWork[]): FoundFile[] {
  return works.flatMap((w) => w.files.filter((f) => !f.date && !f.noDating));
}

/** whether a typed date is one a file can be named with: a real `YYYY-MM-DD` */
export function isFileDate(date: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return false;
  const at = new Date(`${date}T00:00:00Z`);
  return !Number.isNaN(at.getTime()) && at.toISOString().slice(0, 10) === date;
}

/**
 * The name a file takes once given `date`: the date added at the end, before the extension,
 * as every download is named (`{work} {title} - {author} YYYY-MM-DD.ext`). Whatever else the
 * name holds - a date written another way included - is kept as it was.
 */
export function datedName(name: string, date: string): string {
  const dot = name.lastIndexOf('.');
  const stem = (dot > 0 ? name.slice(0, dot) : name).trimEnd();
  const ext = dot > 0 ? name.slice(dot) : '';
  return `${stem} ${date}${ext}`;
}

/** what dating some files did: the renames made, and the ones that could not be */
export interface DatingResult {
  renamed: { from: string; to: string }[];
  failed: { path: string; error: string }[];
}

/** one file to rename: where it is now, and the name it takes */
export interface Rename {
  path: string;
  to: string;
}

/**
 * Rename each file to its new name, in place. One that will not rename - a file already there
 * by the new name, or the library out of reach - is noted and the rest carry on; a rename never
 * writes over another file (`LibraryStore.rename` refuses to). `stopped` is asked before each
 * one, so closing the window part way through stops there: what was renamed stays renamed.
 */
export async function dateFiles(
  store: LibraryStore,
  renames: readonly Rename[],
  progress: (done: number, total: number) => void = () => undefined,
  stopped: () => boolean = () => false,
  result: DatingResult = { renamed: [], failed: [] },
  pause: (ms: number) => Promise<void> = wait,
): Promise<DatingResult> {
  for (const [index, { path, to }] of renames.entries()) {
    if (stopped()) break;
    if (to === path) {
      progress(index + 1, renames.length);
      continue;
    }
    try {
      await patiently(() => store.rename(path, to), stopped, pause);
      result.renamed.push({ from: path, to });
    } catch (error) {
      result.failed.push({ path, error: error instanceof Error ? error.message : String(error) });
    }
    progress(index + 1, renames.length);
  }
  return result;
}

/**
 * Two or more files of one work in one format - by the work number a name starts with and its
 * extension (`.htm` is html), however the rest is written. `key` is `<id>:<format>`.
 */
export interface DuplicateGroup {
  key: string;
  id: string;
  format: OpenableFormat;
  /** by name */
  files: FoundFile[];
}

export function duplicateKey(id: string, format: string): string {
  return `${id}:${format}`;
}

/** the work-and-format groups among these paths that hold more than one file */
export function duplicateGroups(paths: Iterable<string>): DuplicateGroup[] {
  const groups = new Map<string, FoundFile[]>();
  for (const file of workFiles(paths)) {
    const key = duplicateKey(file.id, file.format);
    groups.set(key, [...(groups.get(key) ?? []), file]);
  }
  return [...groups.entries()]
    .filter(([, files]) => files.length > 1)
    .map(([key, files]) => ({
      key,
      id: files[0].id,
      format: files[0].format,
      files: files.sort((a, b) => a.name.localeCompare(b.name)),
    }))
    .sort((a, b) => a.id.length - b.id.length || a.id.localeCompare(b.id) || a.format.localeCompare(b.format));
}

/** when each file was last changed, by path, in ms - as far as the library could say */
export type ModifiedTimes = Readonly<Record<string, number>>;

/**
 * The most recent file of a group, when it is certain: a file dated the app's way (` YYYY-MM-DD`
 * ending its name, `dateFromFilename`) whose date is later than every other file's - certain or
 * read loosely out of the name (`inferDate`). Files with no date in their names do not stand in
 * its way. Null - *can't tell* - when no file is dated the app's way, when another file's
 * guessed date is as late or later, or when two certain dates share the newest day. When each
 * file was last changed is shown beside it, but never decides anything here. Nothing is deleted
 * on a guess unless the person asks for one (`bestGuessOf`).
 *
 * **Resolve issues' duplicates only.** It reads dates the way *Infer date* does, which is right
 * here - the reader is sorting their own files and is shown every file's date - and wrong
 * anywhere else: a run judges a file only by a date written the app's way (the helper's
 * `get_date_from_filename`). Never use it to judge a version outside Resolve issues;
 * `test_guessed_dates_never_decide.py` holds every reader of a guessed date to a list.
 */
export function newestOf(group: DuplicateGroup): FoundFile | null {
  const certain = group.files.map((file) => ({ file, date: dateFromFilename(file.name) })).filter((x) => x.date);
  if (!certain.length) return null;
  const top = certain.reduce((a, b) => (b.date > a.date ? b : a));
  if (certain.filter((x) => x.date === top.date).length > 1) return null;
  const rivals = group.files.filter((f) => f !== top.file).map((f) => inferDate(f.name)).filter(Boolean);
  return rivals.some((date) => date >= top.date) ? null : top.file;
}

/** the date a file's name carries, certain or guessed - '' for none */
function nameDate(file: FoundFile): string {
  return dateFromFilename(file.name) || inferDate(file.name);
}

/**
 * A group's files, the likeliest most recent first: by the date in each name, certain or
 * guessed (undated last); a certain date before a guessed one of the same day; then by when each
 * file was last changed, the later first (unknown last); then by name, only to keep the order
 * steady. The top one is the hand-sifting page's first radio, and the removing page's best guess
 * - when `bestGuessOf` says it can be told apart from the next.
 */
export function byRecency(group: DuplicateGroup, modified: ModifiedTimes = {}): FoundFile[] {
  return [...group.files].sort((a, b) => rankOrder(a, b, modified) || a.name.localeCompare(b.name));
}

/** the order `byRecency` ranks two files in, or 0 when nothing tells them apart */
function rankOrder(a: FoundFile, b: FoundFile, modified: ModifiedTimes): number {
  const da = nameDate(a);
  const db = nameDate(b);
  if (da && db && da !== db) return da > db ? -1 : 1;
  if (!!da !== !!db) return da ? -1 : 1;
  const ca = !!dateFromFilename(a.name);
  const cb = !!dateFromFilename(b.name);
  if (ca !== cb) return ca ? -1 : 1;
  const ma = modified[a.path];
  const mb = modified[b.path];
  if (ma !== undefined && mb !== undefined && ma !== mb) return mb - ma;
  return 0;
}

/**
 * Our best guess at the most recent file: the top of `byRecency`, or null when nothing tells it
 * apart from the next - the same date in their names (or none) and no change time to choose by,
 * or the same one. A name is never a tiebreak here.
 */
export function bestGuessOf(group: DuplicateGroup, modified: ModifiedTimes = {}): FoundFile | null {
  const [top, next] = byRecency(group, modified);
  if (!top) return null;
  return next && rankOrder(top, next, modified) === 0 ? null : top;
}

/**
 * When each of these files was last changed, as far as the library can say - read a few at a
 * time, so a Dropbox library is not asked about hundreds at once. A file it cannot say for is
 * left out, and counts as unknown; one whose asking failed is also handed to `failed`, so the
 * caller can say why rather than leave every file quietly unknown.
 */
export async function modifiedTimes(
  store: LibraryStore,
  paths: readonly string[],
  failed: (error: unknown) => void = () => {},
): Promise<Record<string, number>> {
  const times: Record<string, number> = {};
  if (!store.modified) return times;
  const queue = [...paths];
  const worker = async () => {
    for (let path = queue.shift(); path !== undefined; path = queue.shift()) {
      try {
        const at = await store.modified!(path);
        if (at) times[path] = at;
      } catch (error) {
        // unknown, which only means it cannot break a tie - but said, through `failed`
        failed(error);
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(6, queue.length) }, worker));
  return times;
}

/** what removing duplicates did: what went, and what would not */
export interface RemovingResult {
  removed: string[];
  failed: { path: string; error: string }[];
}

/**
 * Delete these files, one at a time, saying how far it has got. `stopped` is asked before each
 * one, so closing the window part way stops there: what was deleted stays deleted.
 */
export async function removeFiles(
  store: LibraryStore,
  paths: readonly string[],
  progress: (done: number, total: number) => void = () => undefined,
  stopped: () => boolean = () => false,
  result: RemovingResult = { removed: [], failed: [] },
  pause: (ms: number) => Promise<void> = wait,
): Promise<RemovingResult> {
  for (const [index, path] of paths.entries()) {
    if (stopped()) break;
    try {
      await patiently(() => store.delete(path), stopped, pause);
      result.removed.push(path);
    } catch (error) {
      result.failed.push({ path, error: error instanceof Error ? error.message : String(error) });
    }
    progress(index + 1, paths.length);
  }
  return result;
}

/** how many times one file is tried when Dropbox keeps asking us to slow down */
export const SLOW_DOWN_TRIES = 5;

/**
 * How long Dropbox asked us to wait before trying again, in seconds, or null when the error is
 * not Dropbox asking us to slow down. That is a 429 (`Retry-After` when it gave one, else 0), or
 * a write refused because too many came at once (`too_many_write_operations`, a 409).
 */
export function slowDownSeconds(error: unknown): number | null {
  if (!(error instanceof DropboxError)) return null;
  if (error.status === 429) return error.retryAfter ?? 0;
  return /too_many_(write_operations|requests)/.test(error.summary) ? 0 : null;
}

/**
 * Do one library write, trying it again when Dropbox asks us to slow down - deleting or renaming
 * thousands of duplicates one after another runs into Dropbox's limit on writes, and a file it
 * turned away is not one that failed. Waits as long as Dropbox said, else 1, 2, 4, 8 seconds;
 * gives up after `SLOW_DOWN_TRIES`, or at once when stopped. Anything else is thrown as it came.
 */
export async function patiently<T>(
  act: () => Promise<T>,
  stopped: () => boolean = () => false,
  pause: (ms: number) => Promise<void> = wait,
): Promise<T> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await act();
    } catch (error) {
      const seconds = slowDownSeconds(error);
      if (seconds === null || attempt >= SLOW_DOWN_TRIES || stopped()) throw error;
      await pause(Math.max(seconds, 2 ** (attempt - 1)) * 1000);
      if (stopped()) throw error;
    }
  }
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** a file to be given a date, with the index entry of its work when there is one */
export interface ToDate {
  file: FoundFile;
  date: string;
  record?: object;
}

/**
 * The new name of each file given a date. A file whose work is indexed is named from that entry,
 * as a download names it, carrying the date given (`ask`: the helper's `POST /api/file-names`,
 * which builds names with the very code a download uses); one with no entry - or when the
 * helper cannot be asked - keeps its name with the date added at the end (`datedName`).
 */
export async function renamesFor(
  files: readonly ToDate[],
  ask: (files: readonly ToDate[]) => Promise<string[] | null> = async () => null,
): Promise<Rename[]> {
  let names: string[] | null = null;
  try {
    names = await ask(files);
  } catch {
    names = null;
  }
  return files.map((item, index) => {
    const named = names?.[index];
    const name = named || datedName(item.file.name, item.date);
    const folder = item.file.path.slice(0, item.file.path.length - item.file.name.length);
    return { path: item.file.path, to: folder + name };
  });
}

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

/** the years a date in a file name can plausibly be: AO3 opened in 2008, fanfic predates it */
function plausible(year: number): boolean {
  return year >= 1990 && year <= new Date().getUTCFullYear() + 1;
}

function stamp(year: number, month: number, day: number): string {
  const date = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  return plausible(year) && isFileDate(date) ? date : '';
}

/**
 * The ways a date is written in file names, tried in this order - the first that gives a real
 * day wins. Day-first and month-first both write `03-04-2024` (and `2024-03-04`), so
 * month-first (the US way, and what most tools write) is tried first; a first number over 12
 * can only be a day, so that date is read day-first.
 */
const DATE_PATTERNS: { pattern: RegExp; read: (m: RegExpExecArray) => string }[] = [
  // 2024-03-04, 2024_03_04, 2024.03.04, 2024/03/04, 2024 03 04 - month-first, then day-first
  { pattern: /(?<!\d)(\d{4})[-_. /](\d{1,2})[-_. /](\d{1,2})(?!\d)/, read: (m) => stamp(+m[1], +m[2], +m[3]) || stamp(+m[1], +m[3], +m[2]) },
  // 20240304 - month-first, then day-first
  { pattern: /(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)/, read: (m) => stamp(+m[1], +m[2], +m[3]) || stamp(+m[1], +m[3], +m[2]) },
  // 03-04-2024 as month-first, then day-first
  { pattern: /(?<!\d)(\d{1,2})[-_. /](\d{1,2})[-_. /](\d{4})(?!\d)/, read: (m) => stamp(+m[3], +m[1], +m[2]) || stamp(+m[3], +m[2], +m[1]) },
  // 14 Dec 2024, 14 December 2024, 14-Dec-2024
  { pattern: /(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[-_. ]+([a-z]{3,9})\.?[-_., ]+(\d{4})(?!\d)/i, read: (m) => monthDate(m[3], m[2], m[1]) },
  // Dec 14 2024, December 14, 2024
  { pattern: /(?<![a-z])([a-z]{3,9})\.?[-_. ]+(\d{1,2})(?:st|nd|rd|th)?,?[-_. ]+(\d{4})(?!\d)/i, read: (m) => monthDate(m[3], m[1], m[2]) },
  // 2024 Dec 14
  { pattern: /(?<!\d)(\d{4})[-_. ]+([a-z]{3,9})\.?[-_. ]+(\d{1,2})(?!\d)/i, read: (m) => monthDate(m[1], m[2], m[3]) },
];

function monthDate(year: string, month: string, day: string): string {
  const index = MONTHS.indexOf(month.slice(0, 3).toLowerCase());
  return index < 0 ? '' : stamp(+year, index + 1, +day);
}

/** how each of `DATE_PATTERNS` writes a date, said for the reader */
const DATE_STYLES = ['YYYY-MM-DD', 'YYYYMMDD', 'MM-DD-YYYY', 'D Mon YYYY', 'Mon D YYYY', 'YYYY Mon D'];

export interface FoundDate {
  /** the date, YYYY-MM-DD */
  date: string;
  /** where it is written in the text given, and how long */
  index: number;
  length: number;
  /** how it is written, said for the reader: `D Mon YYYY` */
  style: string;
}

/** the first date written in `text` any of the ways in `DATE_PATTERNS`, where it is, or null */
export function findDate(text: string): FoundDate | null {
  for (const [at, { pattern, read }] of DATE_PATTERNS.entries()) {
    const global = new RegExp(pattern.source, pattern.flags.includes('g') ? pattern.flags : pattern.flags + 'g');
    for (let m = global.exec(text); m; m = global.exec(text)) {
      const date = read(m);
      if (date) return { date, index: m.index, length: m[0].length, style: DATE_STYLES[at] };
    }
  }
  return null;
}

/**
 * A date read out of a file's name, written any of the ways in `DATE_PATTERNS` and anywhere in
 * the name - or '' when there is none. The work number the name starts with is left out, so a
 * work numbered 20240304 is not read as a date.
 */
export function inferDate(name: string): string {
  const base = name.replace(/\.[^.]*$/, '');
  // the work number is left out wherever the pattern puts it. A slash here is part of a date
  // ('2024/03/04'), never a folder, so it is not let split the name
  const span = numberSpan(base.replace(/[\\/]/g, ' '));
  const rest = span ? `${base.slice(0, span[0])} ${base.slice(span[1])}` : base;
  for (const { pattern, read } of DATE_PATTERNS) {
    const global = new RegExp(pattern.source, pattern.flags.includes('g') ? pattern.flags : pattern.flags + 'g');
    for (let m = global.exec(rest); m; m = global.exec(rest)) {
      const date = read(m);
      if (date) return date;
    }
  }
  return '';
}

function baseName(path: string): string {
  return path.split('/').pop() ?? path;
}

/** the links an import run is started with, one to a line, as the helper keeps them */
export function importLinks(works: FoundWork[]): string {
  return works.map((w) => `https://archiveofourown.org/works/${w.id}`).join('\n');
}

/**
 * Which of the works found are updated - given the formats picked, and their outdated copies
 * replaced: every one with an issue, only those with undated files, only those with no index
 * entry, or none (`skip`).
 */
export type UpdateScope = 'all' | 'dates' | 'index' | 'skip';

/** what the import window hands the run window to start */
export interface ImportRequest {
  /** the works' links, one to a line */
  links: string;
  count: number;
  /** JSON, and whichever formats to fetch for works without them */
  filetypes: string[];
  replaceOutdated: boolean;
  /** *Overwrite existing downloads*: every dated copy of the works updated fetched again, current or not */
  overwrite?: boolean;
  /** the works among `links` only looked up for their index entry - nothing downloaded */
  indexOnly: string[];
  /** how many of the works are looked up for a missing index entry */
  lookups: number;
  /** which works the formats and replacing are for */
  scope: UpdateScope;
  /** how many files the works hold, as far as the window found - copies a replacing run may fetch again */
  files?: number;
  /**
   * Files with no date in their names to replace with AO3's latest version, by name - chosen on
   * the dating page (*Repair from AO3*). The helper finds each by its work and format.
   */
  repair?: string[];
  /** agreed before the run: FicHub may repair a file AO3 would not give, when its copy is as new
   * as a date guessed from the file's name */
  repairFicHub?: boolean;
  /** for either FicHub choice: a file whose name looks dated no later than FicHub's copy is
   *  repaired (on unless sent false) */
  repairFicHubOlder?: boolean;
  /** agreed too: FicHub may repair one whose name has no date to guess */
  repairFicHubUndated?: boolean;
  /** instead: a file AO3 would not give is kept and named with FicHub's date, never over another */
  repairFicHubRename?: boolean;
  /** FicHub's choice keeps to the date guessed from each file's name (on unless sent false) */
  repairFicHubCheck?: boolean;
  /** where AO3 has the work, the file is only named with AO3's date - nothing downloaded */
  repairRenameOnly?: boolean;
}

/**
 * Over this many requests to AO3 (`importRequests`), the run window says an import may take a
 * long time and to leave the window open: every request is paced.
 */
export const LONG_IMPORT_REQUESTS = 20;

/**
 * A rough count of the requests an import makes: one per work looked up for its index entry, one
 * per file to repair,
 * one per other format per work updated, and - when replacing outdated copies - one per file
 * it holds, at most. Rough by design: a format already on disk, or a copy that is current, costs
 * nothing.
 */
export function importRequests(request: ImportRequest): number {
  // a file to repair is one request of its own, beside its work's lookup
  const lookups = (request.lookups ?? 0) + (request.repair?.length ?? 0);
  if (request.scope === 'skip') return lookups;
  const updated = Math.max(0, request.count - (request.indexOnly?.length ?? 0));
  const formats = (request.filetypes ?? []).filter((f) => f.toUpperCase() !== 'JSON').length;
  const replacing = request.replaceOutdated ? (request.files ?? 0) : 0;
  return lookups + updated * formats + replacing;
}

/**
 * What never to offer again, at the top of the library, so a library in Dropbox leaves the
 * same out on every device. The page reads and writes it; the helper only renames names in it. Three lists:
 *
 * - **files** (`kind: 'files'`, *No, do not ask me again for these files*): left out of
 *   everything - never counted, never listed, never a reason to offer the window;
 * - **index** (`kind: 'index'`, *No, and do not ask again for these works*): a work with no
 *   index entry, and the files it had then. It is not asked about again **while its files are
 *   still exactly those**; a file added since asks again. Its undated files are still offered
 *   for dating, and renaming one renames it here too (`LibraryImports.renamed`);
 * - **dates** (`kind: 'dates'`, *Don't ask this again for skipped files*): undated files never
 *   offered for dating again, by name. Each still counts for its work's index question.
 *
 * A file renamed - by dating here, or by an import naming files from their new entries (the
 * helper's `follow_renames_in_exclusions`) - is renamed on every list it is on.
 */
export const IMPORT_EXCLUDED_FILE = 'import-excluded.json';

export interface Excluded {
  /** file names left out of everything */
  files: Set<string>;
  /** by work number: the file names it had when it was left out of the index question */
  index: Map<string, Set<string>>;
  /** file names never offered for dating */
  dates: Set<string>;
  /** by `<id>:<format>`: the file names a group of duplicates had when kept as it was */
  duplicates: Map<string, Set<string>>;
}

/** one line of the excluded file */
interface ExcludedEntry {
  id: string;
  kind?: 'files' | 'index' | 'dates' | 'duplicates';
  /** a duplicates entry's format */
  format?: string;
  files?: string[];
  excluded_on?: string;
}

function excludedEntries(text: string | null): ExcludedEntry[] {
  try {
    const parsed = JSON.parse(text ?? '') as { excluded?: unknown };
    return Array.isArray(parsed?.excluded)
      ? (parsed.excluded as ExcludedEntry[]).filter((x) => x && /^\d+$/.test(String(x.id ?? '')))
      : [];
  } catch {
    return [];
  }
}

function excludedOf(entries: ExcludedEntry[]): Excluded {
  const excluded: Excluded = { files: new Set(), index: new Map(), dates: new Set(), duplicates: new Map() };
  for (const entry of entries) {
    const names = (entry.files ?? []).map(String);
    if (entry.kind === 'files') for (const name of names) excluded.files.add(name);
    else if (entry.kind === 'dates') for (const name of names) excluded.dates.add(name);
    else if (entry.kind === 'duplicates') {
      const key = duplicateKey(String(entry.id), String(entry.format ?? ''));
      excluded.duplicates.set(key, new Set([...(excluded.duplicates.get(key) ?? []), ...names]));
    } else {
      const id = String(entry.id);
      excluded.index.set(id, new Set([...(excluded.index.get(id) ?? []), ...names]));
    }
  }
  return excluded;
}

/** what the excluded file leaves out; anything unreadable is nothing */
export function readExcludedFile(text: string | null): Excluded {
  return excludedOf(excludedEntries(text));
}

/** whether a group of duplicates is still kept as it was: every file it has now was recorded */
export function duplicatesExcluded(group: DuplicateGroup, excluded: Excluded): boolean {
  const recorded = excluded.duplicates.get(group.key);
  return !!recorded && group.files.every((f) => recorded.has(f.name));
}

/** whether a work is still left out of the index question: every file it has now was recorded */
export function indexExcluded(work: FoundWork, excluded: Excluded): boolean {
  const recorded = excluded.index.get(work.id);
  return !!recorded && work.files.every((f) => recorded.has(f.name));
}


/**
 * The library's unindexed works, kept current: worked out again whenever the index changes
 * (a read, a refresh, a run's changes taken in) - one listing of `works/`, nothing read.
 */
@Injectable({ providedIn: 'root' })
export class LibraryImports {
  private readonly library = inject(Library);
  private readonly visit = inject(VisitLog);
  readonly found = signal<FoundWork[]>([]);
  /** files a download replacing them was left part-way through - tidied first of all */
  readonly leftovers = signal<SwapLeftover[]>([]);
  /**
   * Works with no index entry that the exclusion lists keep out of `found` - every file on the
   * files list, or the work on the index list. Offered only when asked for by name: a work's own
   * *Look up its index from AO3 here*, which can also take every one of them along.
   */
  readonly ignoredIndex = signal<FoundWork[]>([]);
  /** files of indexed works with no date in their name */
  readonly undatedIndexed = signal<FoundFile[]>([]);
  /** whether anything was found to resolve: works with no index entry, or undated files */
  /** works with more than one file in one format */
  readonly duplicates = signal<DuplicateGroup[]>([]);
  /** files named another way than the app's pattern, by the format they are named in */
  readonly misnamed = signal<Misnamed>({ formats: [], unreadable: [] });
  readonly hasIssues = computed(
    () => this.found().length > 0 || this.undatedIndexed().length > 0 || this.duplicates().length > 0 ||
      this.leftovers().length > 0 ||
      this.misnamed().formats.length > 0,
  );
  /** the store the last check was of, so a check of a library since closed is dropped */
  readonly checkedStore = signal<LibraryStore | null>(null);
  /** a check is going: the Works and Collections buttons wait for it, as the offer does */
  readonly checking = signal(false);
  /**
   * the excluded file's lines, as each library has them - read once per listing, so a run that
   * renamed files (and so changed the file) is read again once the page takes its changes in
   */
  private readonly entriesBy = new WeakMap<LibraryStore, { entries: ExcludedEntry[]; listedAt: Date | null }>();
  private generation = 0;

  private async entries(store: LibraryStore): Promise<ExcludedEntry[]> {
    const listedAt = this.library.listedAt();
    const cached = this.entriesBy.get(store);
    if (cached && cached.listedAt === listedAt) return cached.entries;
    let entries: ExcludedEntry[];
    try {
      entries = excludedEntries(await store.read(IMPORT_EXCLUDED_FILE));
    } catch {
      entries = cached?.entries ?? [];
    }
    this.entriesBy.set(store, { entries, listedAt });
    return entries;
  }

  private async save(store: LibraryStore, entries: ExcludedEntry[]): Promise<void> {
    await store.write(IMPORT_EXCLUDED_FILE, new Response(JSON.stringify({ excluded: entries }, null, 2) + '\n'));
    this.entriesBy.set(store, { entries, listedAt: this.library.listedAt() });
  }

  /**
   * Never count or offer these files again (*No, do not ask me again for these files*). The
   * files themselves are left as they are.
   */
  async excludeFiles(files: FoundFile[]): Promise<void> {
    await this.addFiles('files', files);
  }

  /**
   * Never offer these undated files for dating again (*Don't ask this again for skipped
   * files*). Their works are still asked about; the files are left as they are.
   */
  async excludeDating(files: FoundFile[]): Promise<void> {
    await this.addFiles('dates', files);
  }

  private async addFiles(kind: 'files' | 'dates', files: FoundFile[]): Promise<void> {
    const store = this.library.store();
    if (!store || !files.length) return;
    const entries = await this.entries(store);
    const before = excludedOf(entries)[kind];
    const today = new Date().toISOString().slice(0, 10);
    const byWork = new Map<string, string[]>();
    for (const file of files) {
      if (before.has(file.name)) continue;
      byWork.set(file.id, [...(byWork.get(file.id) ?? []), file.name]);
    }
    const added: ExcludedEntry[] = [...byWork].map(([id, names]) => ({ id, kind, files: names, excluded_on: today }));
    if (added.length) await this.save(store, [...entries, ...added]);
    await this.check();
  }

  /**
   * Do not ask about these works' index entries again while their files stay as they are
   * (*No, and do not ask again for these works*) - each recorded with the files it has now.
   */
  async excludeFromIndex(works: FoundWork[]): Promise<void> {
    const store = this.library.store();
    if (!store || !works.length) return;
    const ids = new Set(works.map((w) => w.id));
    const today = new Date().toISOString().slice(0, 10);
    // a work asked about again (it gained a file) is recorded afresh, with every file it has
    const kept = (await this.entries(store)).filter((e) => e.kind === 'files' || !ids.has(String(e.id)));
    const added: ExcludedEntry[] = works.map((w) => ({
      id: w.id,
      kind: 'index',
      files: w.files.map((f) => f.name),
      excluded_on: today,
    }));
    await this.save(store, [...kept, ...added]);
    await this.check();
  }

  /** whether this library's exclusion lists hold anything at all */
  async hasExclusions(): Promise<boolean> {
    const store = this.library.store();
    return !!store && (await this.entries(store)).length > 0;
  }

  /**
   * Empty every exclusion list - files, index and dates - so everything found is offered again.
   * The files themselves are untouched; only the list is emptied.
   */
  async resetExclusions(): Promise<void> {
    const store = this.library.store();
    if (!store) throw new Error('open a library first');
    await this.save(store, []);
    await this.check();
  }

  /**
   * Keep these groups of duplicates as they are (*Keep all*, or more than one kept by hand) and
   * do not ask about them again while their files stay as they are - each recorded with the
   * files it keeps.
   */
  async excludeDuplicates(groups: { group: DuplicateGroup; kept: FoundFile[] }[]): Promise<void> {
    const store = this.library.store();
    if (!store || !groups.length) return;
    const keys = new Set(groups.map((g) => g.group.key));
    const today = new Date().toISOString().slice(0, 10);
    const kept = (await this.entries(store)).filter(
      (e) => e.kind !== 'duplicates' || !keys.has(duplicateKey(String(e.id), String(e.format ?? ''))),
    );
    const added: ExcludedEntry[] = groups.map(({ group, kept: files }) => ({
      id: group.id,
      kind: 'duplicates',
      format: group.format,
      files: files.map((f) => f.name),
      excluded_on: today,
    }));
    await this.save(store, [...kept, ...added]);
  }

  /** files renamed by dating: the exclusion list follows them, so a dated file is not a new one */
  async renamed(renames: readonly { from: string; to: string }[]): Promise<void> {
    const store = this.library.store();
    if (!store || !renames.length) return;
    const names = new Map(renames.map((r) => [baseName(r.from), baseName(r.to)]));
    const entries = await this.entries(store);
    let changed = false;
    const next = entries.map((entry) => {
      const files = (entry.files ?? []).map((name) => {
        const to = names.get(name);
        if (to) changed = true;
        return to ?? name;
      });
      return { ...entry, files };
    });
    if (changed) await this.save(store, next).catch(() => undefined);
  }

  /**
   * Nothing found, and any check still going thrown away: for while the library is being read
   * or set up. Checked against a half-read index, every file would look unindexed.
   */
  forget(): void {
    this.generation++;
    this.found.set([]);
    this.ignoredIndex.set([]);
    this.undatedIndexed.set([]);
    this.duplicates.set([]);
    this.misnamed.set({ formats: [], unreadable: [] });
    this.leftovers.set([]);
    this.checkedStore.set(null);
    this.checking.set(false);
  }

  async check(): Promise<void> {
    const store = this.library.store();
    const generation = ++this.generation;
    if (!store) {
      this.found.set([]);
    this.ignoredIndex.set([]);
      this.undatedIndexed.set([]);
      this.duplicates.set([]);
      this.misnamed.set({ formats: [], unreadable: [] });
      this.leftovers.set([]);
    this.leftovers.set([]);
      this.checkedStore.set(null);
      return;
    }
    const indexed = new Set(this.library.worksById().keys());
    this.checking.set(true);
    try {
      // a Dropbox check just had works/ - its listing is taken rather than asking again
      const reused = this.library.takeWorksListing(store);
      const listed = reused?.paths ?? (await store.list(WORKS_FOLDER, false));
      this.visit.note(
        reused
          ? `Resolve issues check: used the works/ listing the Dropbox check just had (${listed.length} files, ` +
            (reused.fromCache ? "from this browser's cache brought up to date" : 'fetched from Dropbox') + ')'
          : `Resolve issues check: listed works/ from ${store instanceof DropboxLibraryStore ? 'Dropbox' : 'the library'} (${listed.length} files)`,
      );
      const excluded = excludedOf(await this.entries(store));
      if (generation !== this.generation || store !== this.library.store()) return;
      // files left out of everything are gone before anything is counted
      const paths = listed.filter((p) => !excluded.files.has(baseName(p)));
      // files on the dates list are never offered for dating, but still count for their work
      const unindexed = unindexedWorks(paths, indexed).map((w) => ({
        ...w,
        files: w.files.map((f) => (excluded.dates.has(f.name) ? { ...f, noDating: true } : f)),
      }));
      const asked = unindexed.filter((w) => !indexExcluded(w, excluded));
      // a work left out of the index question still has its undated files to date
      const notAsked = unindexed
        .filter((w) => indexExcluded(w, excluded))
        .flatMap((w) => w.files.filter((f) => !f.date).map((f) => ({ ...f, unindexed: true })));
      this.found.set(asked);
      const askedIds = new Set(asked.map((w) => w.id));
      this.ignoredIndex.set(unindexedWorks(listed, indexed).filter((w) => !askedIds.has(w.id)));
      this.undatedIndexed.set(
        [...undatedIndexedFiles(paths, indexed), ...notAsked].filter((f) => !excluded.dates.has(f.name)),
      );
      this.duplicates.set(duplicateGroups(paths).filter((g) => !duplicatesExcluded(g, excluded)));
      this.misnamed.set(misnamedFiles(paths));
      // never on any exclusion list: a file set aside mid-swap is always put right
      this.leftovers.set(swapLeftovers(listed));
      this.checkedStore.set(store);
    } catch {
      // the library could not be listed: whatever was found before is kept until it can
    } finally {
      // only the newest check says it is over - an older one thrown away says nothing
      if (generation === this.generation) this.checking.set(false);
    }
  }
}
