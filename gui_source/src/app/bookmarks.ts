import { fileDate, workNumber } from './naming';
import type { LocalCopy, OpenableFormat } from './library';

/**
 * Shapes and pure helpers for the json file written by ao3downloader's JSON download type.
 * Keep these in step with parse_soup.get_blurb_metadata and actions/ao3download.metadata_file.
 */

export interface WorkTags {
  rating: string;
  categories: string[];
  relationships: string[];
  characters: string[];
  additional: string[];
}

/** one reading of a bookmark, as stored in the file's history */
export interface BookmarkIndex {
  indexed_on: string;
  [field: string]: unknown;
}

/**
 * The `YYYY-MM-DD` a downloaded file's name holds where `FileNamePattern` puts the date - the
 * version of the work it holds - or '' when it has none. The same rule as the helper's
 * `parse_text.get_date_from_filename` (`naming.fileDate`).
 */
export function dateFromFilename(name: string): string {
  return fileDate(name);
}

/**
 * Whether one downloaded copy of a work is a newer version than another: by the date in
 * its name, an undated copy counting as the oldest - the same rule every run judges copies
 * by. Only when the dates are the same does the time the file was last changed decide.
 */
export function isNewerCopy(
  name: string,
  modified: number,
  than: { name: string; modified: number },
): boolean {
  const mine = dateFromFilename(name);
  const theirs = dateFromFilename(than.name);
  if (mine !== theirs) return mine > theirs;
  return modified > than.modified;
}

/** the helper's `BOOKMARK_TYPE_*` */
export type BookmarkType = 'individual work' | 'external work' | 'series bookmark';

/** what an entry is, reading an entry from before types were recorded as a work */
export function bookmarkTypeOf(record: Bookmark): BookmarkType {
  return record.bookmark_type ?? 'individual work';
}

/**
 * Whether an index entry is a work - something with a work number and a file to open.
 *
 * A bookmarked series and an external work have entries of their own, in folders inside
 * indexing/. A folder read through the File System Access API arrives flat, so this goes by
 * what the entry says, not where it was.
 */
export function isWorkEntry(record: Bookmark): boolean {
  return bookmarkTypeOf(record) === 'individual work';
}

/**
 * Whether an entry is one of your bookmarks: only one that says so (`bookmarked: true`).
 *
 * An entry that says nothing is not counted as one - at the owner's request: entries from
 * before `bookmarked` was recorded are marked by hand from the Works tab (Mark as bookmark,
 * `Library.setBookmarked`), or by the next walk of your AO3 bookmarks.
 */
export function isBookmarkEntry(record: Bookmark): boolean {
  return record.bookmarked === true;
}

/**
 * Where an entry in the listing came from, for the badge on it and the Origin filter:
 * - `bookmarks` - your own ao3 bookmarks (or an entry from before that was recorded, which
 *   came off them)
 * - `collection` - not bookmarked, but in a collection that was indexed
 * - `link` - indexed by the fic runs from its link or work number (`from_link`)
 * - `external` - imported from an external source: a file found in the library with no index
 *   entry, which an import run then indexed (`from_import`) - and **everything no workflow of
 *   ours accounts for**, the fallthrough: an entry known not to be your bookmark that no scan,
 *   collection or fic run brought in came into the library some other way. A fic FicHub supplied
 *   is *not* this unless nothing else says where it came from - it is wherever its run put it
 */
export type Origin = 'bookmarks' | 'collection' | 'external' | 'link';

export const ORIGINS: { origin: Origin; label: string; upcoming?: boolean }[] = [
  { origin: 'bookmarks', label: 'Your AO3 bookmarks' },
  { origin: 'collection', label: 'An AO3 collection' },
  { origin: 'external', label: 'Imported from an external source' },
  { origin: 'link', label: 'Downloaded by ID or URL' },
];

export function originOf(record: Bookmark): Origin {
  if (isBookmarkEntry(record)) return 'bookmarks';
  if ((record.from_collections ?? []).length) return 'collection';
  if (record.from_link && !record.from_import) return 'link';
  // imported, or in the library with nothing of ours to say how it came
  return 'external';
}

/**
 * Whether an entry is listed on the Bookmarks tab: every bookmark, and every other work in the
 * index - a fic downloaded by its link, one a collection brought in - marked with where it came
 * from, so the library on disk is all findable in one list.
 *
 * Two are still left to their cards rather than listed twice: a work in the index only because
 * a bookmarked series holds it (it is in the series' card), and a series you did not bookmark
 * (it is on the 'Part N of' line of the works in it).
 */
export function isListedEntry(record: Bookmark, inBookmarkedSeries: ReadonlySet<string> = new Set()): boolean {
  if (isBookmarkEntry(record)) return true;
  if (bookmarkTypeOf(record) === 'series bookmark') return false;
  // a bookmarked series listing it says so as surely as its own from_series does
  const viaSeries =
    (record.from_series ?? []).length > 0 || (!!record.id && inBookmarkedSeries.has(record.id));
  const viaCollection = (record.from_collections ?? []).length > 0;
  return !(viaSeries && !viaCollection);
}

/** one series a work is part of, as its entry records it */
export interface SeriesMembership {
  id: string;
  title: string;
  part: number | null;
}

/** whether a work, or a series, is finished - which the two record differently */
export function isEntryComplete(record: Bookmark): boolean {
  return bookmarkTypeOf(record) === 'series bookmark' ? !!record.complete : isComplete(record);
}

export interface Bookmark {
  /** provenance, written into every per-work file */
  source?: string;
  retrieved?: string;
  /** when the fic was last checked, whether or not anything had changed */
  last_indexed?: string;
  /** every reading kept for this fic, oldest first */
  indexes?: BookmarkIndex[];
  /**
   * What the bookmark is of. Entries from before this was recorded have none, and are
   * individual works.
   */
  bookmark_type?: BookmarkType;
  /** false for a work in the index only because a series you bookmarked holds it */
  bookmarked?: boolean;
  /** the bookmarked series, by id, a work was found through */
  from_series?: string[];
  /** the ao3 collections, by name, that hold it - set by a run's cleanup step */
  from_collections?: string[];
  /**
   * On an index reading made from the FicHub mirror rather than AO3 - a work AO3 would not
   * give a run - with the formats that came from it. A reading from AO3 never carries it.
   */
  retrieved_from?: { site: string; downloaded?: string[] };
  /** indexed by a fic run from its link or work number, when it was not your bookmark */
  from_link?: boolean;
  /** first indexed by an import, from a file already in the library - not your bookmark */
  from_import?: boolean;
  /** on a work: the series it is part of, and where in each */
  series?: SeriesMembership[];
  /** on a series: how many works it holds, whether it is finished, and which works */
  works?: number | null;
  complete?: boolean;
  work_ids?: string[];
  id: string | null;
  link: string | null;
  title: string;
  authors: string[];
  date_created: string | null;
  date_updated: string;
  fandoms: string[];
  warnings: string[];
  tags: WorkTags;
  summary: string;
  words: number | null;
  chapters_published: number | null;
  chapters_total: number | null;
  comments: number | null;
  kudos: number | null;
  bookmarks: number | null;
  hits: number | null;
  date_bookmarked: string;
  bookmark_notes: string;
  bookmark_tags: string[];
  bookmark_collections: string[];
  bookmark_private: boolean;
  bookmark_rec: boolean;
  /** present instead of the rest when a blurb could not be parsed */
  error?: string;
  /**
   * Set when this stands in for a work that is listed somewhere - a collection - but has
   * no entry in the index. Its number and link are all that is known about it.
   */
  placeholder?: boolean;
  /**
   * A file in `works/` no index entry matches, listed from what its name says
   * (`unindexed-works.ts`) - never written to the index.
   */
  unindexed?: boolean;
  /** where such a row's date came from: the name as the app writes it, a guess, or the file */
  unindexed_date?: 'name' | 'guessed' | 'file' | '';
  /** such a row's own files, a format each - it has no work number for `Library.copies` to know */
  unindexed_files?: Partial<Record<OpenableFormat, LocalCopy>>;
}

export interface BookmarksExport {
  source: string;
  retrieved: string;
  count: number;
  works: Bookmark[];
}

export const AO3_BASE_URL = 'https://archiveofourown.org';

/**
 * Turn one file's contents into a bookmark to display.
 *
 * A file keeps a history of readings, so the newest one is what to show, with the
 * identity at the root laid over it. Files written before that history existed are flat,
 * and are used as they are.
 */
export function flattenRecord(parsed: unknown): Bookmark | null {
  if (!parsed || typeof parsed !== 'object') return null;
  const record = parsed as Record<string, unknown>;

  const history = record['indexes'];
  if (Array.isArray(history)) {
    const latest = history[history.length - 1];
    if (!latest || typeof latest !== 'object') return null;
    // root last so identity wins: id, link, source and bookmark type are not versioned
    return { ...(latest as object), ...record } as unknown as Bookmark;
  }

  return record['id'] || record['title'] ? (record as unknown as Bookmark) : null;
}

/**
 * A stand-in for a work that something lists but the index has no entry for.
 *
 * A collection records the works it holds by work number alone, and a collection can hold
 * works you have never bookmarked. Rather than dropping those, they are shown with the one
 * thing that is known about them - the number - and a link to the work on ao3.
 */
export function placeholderExternal(id: string): Bookmark {
  return {
    ...placeholderWork(id),
    link: `${AO3_BASE_URL}/external_works/${id}`,
    title: `External work ${id}`,
    bookmark_type: 'external work',
  };
}

export function placeholderWork(id: string): Bookmark {
  return {
    placeholder: true,
    id,
    link: `${AO3_BASE_URL}/works/${id}`,
    title: `Work ${id}`,
    authors: [],
    date_created: null,
    date_updated: '',
    fandoms: [],
    warnings: [],
    tags: { rating: '', categories: [], relationships: [], characters: [], additional: [] },
    summary: '',
    words: null,
    chapters_published: null,
    chapters_total: null,
    comments: null,
    kudos: null,
    bookmarks: null,
    hits: null,
    date_bookmarked: '',
    bookmark_notes: '',
    bookmark_tags: [],
    bookmark_collections: [],
    bookmark_private: false,
    bookmark_rec: false,
  };
}

export type PageItem = number | 'gap';

/**
 * Page numbers to show, with gaps collapsed - 1 2 3 4 5 6 7 ... 79.
 * Keeps a window of `span` pages around the current one, always showing the first and last.
 */
export function pageItems(current: number, total: number, span = 7): PageItem[] {
  if (total < 1) return [];
  if (total <= span + 1) return range(1, total);

  const start = Math.max(1, Math.min(current - Math.floor(span / 2), total - span + 1));
  const end = Math.min(total, start + span - 1);

  const items: PageItem[] = [];
  if (start > 1) {
    items.push(1);
    if (start > 2) items.push('gap');
  }
  items.push(...range(start, end));
  if (end < total) {
    if (end < total - 1) items.push('gap');
    items.push(total);
  }
  return items;
}

function range(from: number, to: number): number[] {
  return Array.from({ length: to - from + 1 }, (_, i) => from + i);
}

/**
 * ao3downloader's default file name pattern is '{worknum} {title} - {author}', so a
 * downloaded work can be matched back to its metadata by the number it starts with.
 * Returns null for a file named some other way, which just means no local copy is linked.
 */
export function workIdFromFilename(name: string): string | null {
  // where `FileNamePattern` puts the number (`naming.workNumber`): for the default, digits at
  // the start followed by a separator, so '99 Red Balloons' is work 99 and '99Red Balloons' none
  return workNumber(name);
}

const MONTHS = [
  'jan', 'feb', 'mar', 'apr', 'may', 'jun',
  'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
];

/**
 * An AO3 date turned into `YYYY-MM-DD`, or '' when it is not one.
 *
 * AO3 writes the same date two ways - `14 Dec 2024` on a listing blurb, `2024-12-14` on a
 * work's own page - and an index holds whichever the run that wrote it saw. Comparing them
 * as plain strings would order a listing date by its day number, so both are normalised to
 * the form that sorts correctly.
 *
 * This is the browser's half of `parse_text.get_date_stamp`. Anything unrecognised comes
 * back empty rather than throwing: a filter must never be the reason a listing fails to
 * render, and a work with no readable date simply cannot be placed in a range.
 */
export function dateStamp(text: string): string {
  const value = (text ?? '').trim();
  if (!value) return '';

  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;

  const listing = /^(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})$/.exec(value);
  if (!listing) return '';

  const month = MONTHS.indexOf(listing[2].toLowerCase());
  if (month < 0) return '';
  return `${listing[3]}-${String(month + 1).padStart(2, '0')}-${listing[1].padStart(2, '0')}`;
}

/** 'https://archiveofourown.org/users/Someone/bookmarks' -> 'Someone' */
export function ownerFromSource(source: string): string {
  return /\/users\/([^/?#]+)/.exec(source ?? '')?.[1] ?? '';
}

export function authorLink(author: string): string {
  return `${AO3_BASE_URL}/users/${encodeURIComponent(author)}`;
}

/** ao3 shows '?' as the total for a work in progress, which the export stores as null. */
export function isComplete(work: Bookmark): boolean {
  return work.chapters_total !== null && work.chapters_published === work.chapters_total;
}

export function chapterCount(work: Bookmark): string {
  return `${work.chapters_published ?? '?'}/${work.chapters_total ?? '?'}`;
}

/** The export stores summaries and notes as plain text with blank lines between paragraphs. */
export function paragraphs(text: string): string[] {
  return (text ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/**
 * Colour band for the rating tile, mirroring ao3's own symbol colours.
 */
export function ratingClass(rating: string): string {
  const value = (rating ?? '').toLowerCase();
  if (value.includes('general')) return 'rating-general';
  if (value.includes('teen')) return 'rating-teen';
  if (value.includes('mature')) return 'rating-mature';
  if (value.includes('explicit')) return 'rating-explicit';
  return 'rating-none';
}

export function warningClass(warnings: string[]): string {
  const list = warnings ?? [];
  if (list.some((w) => w.toLowerCase().startsWith('no archive warnings'))) return 'warning-none';
  if (list.some((w) => w.toLowerCase().startsWith('choose not to use'))) return 'warning-maybe';
  return list.length > 0 ? 'warning-yes' : 'warning-none';
}
