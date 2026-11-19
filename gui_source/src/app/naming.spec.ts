import { afterEach, describe, expect, it } from 'vitest';
import { dateFromFilename, workIdFromFilename } from './bookmarks';
import { inferDate } from './imports';
import { DEFAULT_NAME_PATTERN, activePattern, parsePattern, patternText, readName, useNamePattern } from './naming';

const AO3_ORDER = '{title} - {author} - {worknum} {date}';

describe('the file name pattern', () => {
  afterEach(() => useNamePattern(DEFAULT_NAME_PATTERN));

  it('takes every order of the four parts, with any separators', () => {
    for (const text of [DEFAULT_NAME_PATTERN, AO3_ORDER, '{date}_{worknum}_{author}_{title}']) {
      const parsed = parsePattern(text);
      expect(typeof parsed).not.toBe('string');
      expect(patternText(parsed as never)).toBe(text);
    }
  });

  it('refuses a pattern names could not be read by, as the helper does', () => {
    expect(parsePattern('{worknum} {title} - {author}')).toContain('needs every part');
    expect(parsePattern('{worknum}{title} - {author} {date}')).toContain('needs a separator');
    expect(parsePattern('{worknum} {title} 2 {author} {date}')).toContain('digit');
    expect(parsePattern('{worknum} {title} : {author} {date}')).toContain('cannot');
  });

  it('falls back to the default for a setting that is not a pattern', () => {
    useNamePattern('{title}');
    expect(patternText(activePattern())).toBe(DEFAULT_NAME_PATTERN);
  });

  it('reads the number and the certain date where the default puts them, as names always were', () => {
    expect(workIdFromFilename('12345678 My Fic - Author 2026-05-10.epub')).toBe('12345678');
    expect(dateFromFilename('12345678 My Fic - Author 2026-05-10.epub')).toBe('2026-05-10');
    expect(workIdFromFilename('99Red Balloons.html')).toBeNull();
  });

  it("reads a name with no author before its date as dated, not as an author called the date, as the helper does", () => {
    // an anonymous work's file, its author left empty with the separator kept
    const name = '11418339 Luke Skywalker 19 Full human - 2026-08-02.html';
    expect(dateFromFilename(name)).toBe('2026-08-02');
    expect(readName(name)).toEqual({ worknum: '11418339', title: 'Luke Skywalker 19 Full human', author: '', date: '2026-08-02' });
    expect(dateFromFilename('1 A - 2026-02-31.html')).toBe('');
    expect(readName('1 A - Author.html')?.author).toBe('Author');
  });

  it('reads the number and the date whatever the title and author look like, as the helper does', () => {
    for (const name of ['7 Title only 2026-08-02.html', '7 Title - With - Dashes - 2026-08-02.html',
      '7 Title - Author - Someone Else 2026-08-02.epub', '7 - 2026-08-02.html']) {
      expect(workIdFromFilename(name)).toBe('7');
      expect(dateFromFilename(name)).toBe('2026-08-02');
    }
  });

  it('reads them wherever another pattern puts them', () => {
    useNamePattern(AO3_ORDER);
    const name = 'My Fic - Author - 12345678 2026-05-10.epub';
    expect(workIdFromFilename(name)).toBe('12345678');
    expect(dateFromFilename(name)).toBe('2026-05-10');
    expect(readName(name)).toEqual({ worknum: '12345678', title: 'My Fic', author: 'Author', date: '2026-05-10' });
    // the old way of naming is not a work's file under this pattern until it is renamed
    expect(workIdFromFilename('12345678 My Fic - Author 2026-05-10.epub')).toBeNull();
  });

  it('never reads a number at the end as a guessed date', () => {
    useNamePattern(AO3_ORDER);
    expect(inferDate('My Fic - Author - 20240304.epub')).toBe('');
    expect(inferDate('My Fic - Author (4 Mar 2024) - 12345678.epub')).toBe('2024-03-04');
  });
});
