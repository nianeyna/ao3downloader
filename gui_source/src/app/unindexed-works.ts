/**
 * Files in `works/` that no index entry matches, shown in the Works tab anyway - with what can be
 * read off them, until Resolve issues looks them up on AO3 and gives them an entry.
 *
 * Nothing here is written anywhere, and nothing reaches AO3: every row is worked out afresh from
 * the files last listed (`Library.worksFiles`) and the index as last read (`Library.worksById`).
 *
 * - **One row per work**: the files of one work number - read where `FileNamePattern` puts it, or,
 *   for a name in some other form, at its start or end (`readOtherName`) - are one row, with a
 *   button per format. A name with no number at all is a row of its own, its formats joined by the
 *   name they share less the extension.
 * - **A number the index already has is left alone**: a file named another way for a work that is
 *   indexed is Resolve issues' to rename, not a second row for the same work.
 * - **The date is the version a file holds, as best it can be told**: the date written the app's
 *   way in its name, else one read loosely out of the name (*Infer date*), else when the file last
 *   changed - and the row says which (`unindexed_date`). Shown, never acted on.
 */

import { Injectable, computed, inject } from '@angular/core';
import { AO3_BASE_URL, Bookmark, dateFromFilename, placeholderWork, workIdFromFilename } from './bookmarks';
import { inferDate } from './imports';
import { LocalCopy, Library, OpenableFormat, WorksFile } from './library';
import { namePatternText, readName } from './naming';
import { readOtherName } from './renames';

/** where an unindexed row's date came from, worst last */
export type UnindexedDate = 'name' | 'guessed' | 'file' | '';

/** a row's key that is not a work number: a name with none, by the name its formats share */
export const LOOSE_PREFIX = 'file:';

interface Read {
  key: string;
  worknum: string;
  title: string;
  author: string;
  date: string;
  dateFrom: UnindexedDate;
}

/** what one file's name (and, failing that, the file itself) says about the work it holds */
export function readUnindexedFile(file: Pick<WorksFile, 'name' | 'modified'>): Read {
  const stem = file.name.replace(/\.[^.]*$/, '').trim();
  const inPattern = readName(file.name);
  const patternNumber = workIdFromFilename(file.name) ?? '';
  const other = patternNumber ? null : readOtherName(file.name);
  const worknum = patternNumber || other?.worknum || '';

  let date = dateFromFilename(file.name);
  let dateFrom: UnindexedDate = date ? 'name' : '';
  if (!date) {
    date = inferDate(file.name);
    if (date) dateFrom = 'guessed';
  }
  if (!date && file.modified) {
    date = new Date(file.modified).toISOString().slice(0, 10);
    dateFrom = 'file';
  }

  return {
    key: worknum || `${LOOSE_PREFIX}${stem.toLowerCase()}`,
    worknum,
    title: (inPattern?.title || other?.title || '').trim() || stem,
    author: (inPattern?.author || other?.author || '').trim(),
    date,
    dateFrom,
  };
}

/** the better of two dates for a row: one written the app's way beats a guess beats a file's */
const DATE_RANK: Record<UnindexedDate, number> = { name: 3, guessed: 2, file: 1, '': 0 };

/**
 * One row per work among the files no index entry matches: `indexed` says which work numbers
 * the index has. Rows come back newest first, by their date.
 */
export function unindexedRows(files: WorksFile[], indexed: (id: string) => boolean): Bookmark[] {
  const rows = new Map<string, { read: Read; files: Partial<Record<OpenableFormat, WorksFile>> }>();
  for (const file of files) {
    const read = readUnindexedFile(file);
    if (read.worknum && indexed(read.worknum)) continue;
    const row = rows.get(read.key);
    if (!row) {
      rows.set(read.key, { read, files: { [file.format]: file } });
      continue;
    }
    // the first name to say something keeps saying it; the best date wins, and of two equally
    // good ones the later
    if (!row.read.title || row.read.title === row.read.key) row.read.title = read.title;
    if (!row.read.author) row.read.author = read.author;
    if (DATE_RANK[read.dateFrom] > DATE_RANK[row.read.dateFrom] ||
        (DATE_RANK[read.dateFrom] === DATE_RANK[row.read.dateFrom] && read.date > row.read.date)) {
      row.read.date = read.date;
      row.read.dateFrom = read.dateFrom;
    }
    // of two files in one format, the newer version by its name, as everywhere else
    const held = row.files[file.format];
    if (!held || (dateFromFilename(file.name) || inferDate(file.name)) > (dateFromFilename(held.name) || inferDate(held.name))) {
      row.files[file.format] = file;
    }
  }

  return [...rows.values()]
    .map(({ read, files }) => {
      const base = placeholderWork(read.worknum || read.key);
      const entry: Bookmark = {
        ...base,
        placeholder: false,
        unindexed: true,
        unindexed_date: read.dateFrom,
        unindexed_files: Object.fromEntries(
          Object.entries(files).map(([format, file]) => [format, file!.copy]),
        ) as Partial<Record<OpenableFormat, LocalCopy>>,
        link: read.worknum ? `${AO3_BASE_URL}/works/${read.worknum}` : '',
        title: read.title,
        authors: read.author ? [read.author] : [],
        date_updated: read.date,
      };
      return entry;
    })
    .sort((a, b) => (b.date_updated || '').localeCompare(a.date_updated || ''));
}

@Injectable({ providedIn: 'root' })
export class UnindexedWorks {
  private readonly library = inject(Library);

  /** the rows, worked out again whenever the files, the index or the naming pattern change */
  readonly rows = computed(() => {
    namePatternText();
    // an external work's number is AO3's for something hosted elsewhere, never a work's
    const byId = this.library.worksById();
    return unindexedRows(this.library.worksFiles(), (id) => byId.has(id));
  });
}
