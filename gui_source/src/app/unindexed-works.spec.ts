import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { readUnindexedFile, unindexedRows, LOOSE_PREFIX } from './unindexed-works';
import { WorksFile } from './library';
import { WorkList } from './work-list';
import { Bookmark } from './bookmarks';
import { Jobs } from './jobs';

/**
 * Files in works/ that no index entry matches are still listed, from what their names say -
 * one row per work number, with a button per format, dated as best the name or the file can.
 */

function file(name: string, modified: number | null = null): WorksFile {
  const format = name.split('.').pop()!.toLowerCase().replace('htm', 'html').replace('htmll', 'html') as WorksFile['format'];
  return { name, modified, format, copy: new File(['x'], name) };
}

const nothingIndexed = () => false;

describe('files no index entry matches', () => {
  // region reading one name

  it('reads the number, title, author and date of a name in the pattern', () => {
    expect(readUnindexedFile(file('123 A Title - Writer 2024-05-06.html'))).toMatchObject({
      key: '123', worknum: '123', title: 'A Title', author: 'Writer', date: '2024-05-06', dateFrom: 'name',
    });
  });

  it('guesses a date out of a name not written the apps way, and says it is a guess', () => {
    const read = readUnindexedFile(file('A Title - Writer - 123 (May 6 2024).epub'));
    expect(read.worknum).toBe('123');
    expect(read.date).toBe('2024-05-06');
    expect(read.dateFrom).toBe('guessed');
  });

  it('falls back to when the file last changed for a name with no date', () => {
    const read = readUnindexedFile(file('123 A Title - Writer.html', Date.UTC(2023, 2, 4, 12)));
    expect(read.date).toBe('2023-03-04');
    expect(read.dateFrom).toBe('file');
  });

  it('keeps a name with no work number by its own name', () => {
    const read = readUnindexedFile(file('Some Story.pdf'));
    expect(read.worknum).toBe('');
    expect(read.key).toBe(`${LOOSE_PREFIX}some story`);
    expect(read.title).toBe('Some Story');
  });

  // endregion

  // region grouping

  it('makes one row per work number, with every format it has', () => {
    const rows = unindexedRows([
      file('123 A Title - Writer 2024-05-06.html'),
      file('123 A Title - Writer 2024-05-06.pdf'),
      file('123 A Title - Writer 2024-05-06.epub'),
    ], nothingIndexed);
    expect(rows).toHaveLength(1);
    expect(Object.keys(rows[0].unindexed_files ?? {}).sort()).toEqual(['epub', 'html', 'pdf']);
    expect(rows[0].link).toBe('https://archiveofourown.org/works/123');
  });

  it('joins the formats of a name with no number by the name they share', () => {
    const rows = unindexedRows([file('Some Story.pdf'), file('Some Story.epub')], nothingIndexed);
    expect(rows).toHaveLength(1);
    expect(rows[0].link).toBe('');
  });

  it('leaves out a number the index has, which is Resolve issues to rename', () => {
    const rows = unindexedRows([file('123 Other Name.html'), file('456 New - Writer.html')], (id) => id === '123');
    expect(rows.map((r) => r.id)).toEqual(['456']);
  });

  it('takes the best date among a works files: written the apps way over a guess over a file time', () => {
    const rows = unindexedRows([
      file('123 A Title - Writer.html', Date.UTC(2025, 0, 1)),
      file('123 A Title - Writer 2024-05-06.pdf'),
    ], nothingIndexed);
    expect(rows[0].date_updated).toBe('2024-05-06');
    expect(rows[0].unindexed_date).toBe('name');
  });

  it('keeps the newer of two files in one format', () => {
    const newer = file('123 A Title - Writer 2024-05-06.html');
    const rows = unindexedRows([file('123 A Title - Writer 2020-01-01.html'), newer], nothingIndexed);
    expect(rows[0].unindexed_files?.html).toBe(newer.copy);
  });

  it('lists the rows newest first', () => {
    const rows = unindexedRows([
      file('1 Old - W 2020-01-01.html'), file('2 New - W 2025-01-01.html'),
    ], nothingIndexed);
    expect(rows.map((r) => r.id)).toEqual(['2', '1']);
  });

  // endregion

  // region in the listing

  async function listed(works: Bookmark[]): Promise<HTMLElement> {
    await TestBed.configureTestingModule({ imports: [WorkList] }).compileComponents();
    const fixture = TestBed.createComponent(WorkList);
    fixture.componentRef.setInput('works', works);
    fixture.componentRef.setInput('selectable', true);
    fixture.detectChanges();
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('shows a row with its name, a format button per file, and that it is not in the index', async () => {
    const rows = unindexedRows([
      file('123 A Title - Writer 2024-05-06.html'), file('123 A Title - Writer 2024-05-06.pdf'),
    ], nothingIndexed);
    const element = await listed(rows);
    expect(element.querySelector('.title')?.textContent).toContain('A Title');
    expect(element.querySelector('.badge.not-in-index')).not.toBeNull();
    expect(Array.from(element.querySelectorAll('button.format')).map((b) => b.textContent?.trim())).toEqual(['PDF']);
    expect(element.querySelector('.datetime')?.getAttribute('title')).toBe('The date in its file name');
    expect(element.querySelector('.download-now')?.textContent).toContain('download the latest version of this work');
    expect(element.querySelector('.resolve-now')?.textContent).toContain('Look up its index from AO3 here');
    expect(Array.from(element.querySelectorAll('.unindexed-files li')).map((li) => li.textContent?.trim()))
      .toEqual(['123 A Title - Writer 2024-05-06.html', '123 A Title - Writer 2024-05-06.pdf']);
  });

  it('says where a date came from when it is not written the apps way', async () => {
    const element = await listed(unindexedRows([
      file('A Title - Writer - 123 (May 6 2024).epub'), file('9 B - W.html', Date.UTC(2023, 2, 4)),
    ], nothingIndexed));
    const said = Array.from(element.querySelectorAll('.datetime')).map((d) => d.textContent?.trim());
    expect(said).toEqual(['2024-05-06 (best guess from filename)', '2023-03-04 (best guess from filedate)']);
  });

  it('asks for Resolve issues on its own work when its look-up link is pressed', async () => {
    const element = await listed(unindexedRows([file('123 A Title - Writer.html')], nothingIndexed));
    const jobs = TestBed.inject(Jobs);
    element.querySelector<HTMLButtonElement>('.resolve-now')!.click();
    expect(jobs.lookUpAsked()).toBe('123');
  });

  it('offers nothing to tick, hide or fetch for a file with no work number', async () => {
    const element = await listed(unindexedRows([file('Some Story.pdf')], nothingIndexed));
    expect(element.querySelector('.title')?.textContent).toContain('Some Story');
    expect(element.querySelector('input.pick')).toBeNull();
    expect(element.querySelector('.entry-actions')).toBeNull();
    expect(element.querySelector('.download-now')).toBeNull();
  });

  // endregion
});
