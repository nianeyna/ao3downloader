/**
 * How a downloaded work's file is named, and read back - the page's half of the helper's
 * `naming.py`; keep the two in step.
 *
 * The pattern is settings.ini's `FileNamePattern`, sent with the helper's config: `{worknum}`,
 * `{title}`, `{author}` and `{date}`, each once, in any order, with a separator between each.
 * Which work a file is (`workNumber`) and which version it holds (`fileDate`, the date where the
 * pattern puts it, written YYYY-MM-DD) are read by it everywhere in the page. The page never
 * builds a work's name itself - the helper does (`POST /api/file-names`), so the rules cannot
 * drift.
 */

import { signal } from '@angular/core';

export const NAME_TOKENS = ['worknum', 'title', 'author', 'date'] as const;
export type NameToken = (typeof NAME_TOKENS)[number];
export const DEFAULT_NAME_PATTERN = '{worknum} {title} - {author} {date}';
/** the names AO3's own site gives a download - Title - Author - 12345678 - with the date added */
export const AO3_NAME_PATTERN = '{title} - {author} - {worknum} {date}';
export const SEPARATOR_MAX = 10;
/** what a file name cannot hold - the helper's `INVALID_FILENAME_CHARACTERS` */
const INVALID = /[<>:"/\\|?*.\u0000-\u001f]/;

const DATE = '\\d{4}-\\d{2}-\\d{2}';

export interface NamePattern {
  order: NameToken[];
  /** `separators[i]` sits between `order[i]` and `order[i + 1]` */
  separators: string[];
}

export function patternText(pattern: NamePattern): string {
  let out = `{${pattern.order[0]}}`;
  pattern.separators.forEach((sep, i) => (out += sep + `{${pattern.order[i + 1]}}`));
  return out;
}

/** `text` as a pattern, or the reason it is not one - the helper's rules exactly */
export function parsePattern(text: string): NamePattern | string {
  const pieces = String(text ?? '').trim().split(/(\{[^{}]*\})/);
  const order: NameToken[] = [];
  const separators: string[] = [];
  if (pieces[0]) return 'a file name pattern has to start with one of its parts, not with text';
  if (pieces[pieces.length - 1]) return 'a file name pattern has to end with one of its parts, not with text';
  for (let at = 0; at < pieces.length; at++) {
    const piece = pieces[at];
    if (at % 2 === 1) {
      const name = piece.slice(1, -1) as NameToken;
      if (!NAME_TOKENS.includes(name)) return `${piece} is not a part of a file name`;
      if (order.includes(name)) return `${piece} appears more than once`;
      order.push(name);
    } else if (at > 0 && at < pieces.length - 1) {
      if (!piece) return 'every part needs a separator before the next one';
      if (/[{}]/.test(piece)) return 'a separator cannot hold { or }';
      if (INVALID.test(piece)) return `the separator '${piece}' holds a character a file name cannot`;
      if (/\d/.test(piece)) return `the separator '${piece}' holds a digit, which would be read as part of a number or a date`;
      if (piece.length > SEPARATOR_MAX) return `a separator is at most ${SEPARATOR_MAX} characters`;
      separators.push(piece);
    }
  }
  const missing = NAME_TOKENS.filter((x) => !order.includes(x));
  if (missing.length) return `a file name pattern needs every part: ${missing.map((x) => `{${x}}`).join(', ')} missing`;
  return { order, separators };
}

function orDefault(text: string | null | undefined): NamePattern {
  const parsed = text ? parsePattern(text) : null;
  return parsed && typeof parsed !== 'string' ? parsed : (parsePattern(DEFAULT_NAME_PATTERN) as NamePattern);
}

let active: NamePattern = orDefault(DEFAULT_NAME_PATTERN);

/**
 * The pattern in force, as text - a signal, so whatever was worked out from file names (the
 * library's copies, Resolve issues' check) is worked out again when the helper's config brings
 * a different one: the library can be read before the config arrives.
 */
export const namePatternText = signal(patternText(active));

/** the pattern names are read by now */
export function activePattern(): NamePattern {
  return active;
}

/** read names by `text` from now on - the default when it is empty or not a pattern */
export function useNamePattern(text: string | null | undefined): NamePattern {
  active = orDefault(text);
  const now = patternText(active);
  if (now !== namePatternText()) namePatternText.set(now);
  return active;
}

function base(name: string): string {
  return (String(name ?? '').split(/[\\/]/).pop() ?? '').replace(/\.[^.]*$/, '').trim();
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function regex(pattern: NamePattern, dated: boolean): RegExp {
  const order = [...pattern.order];
  const separators = [...pattern.separators];
  if (!dated) {
    const at = order.indexOf('date');
    // an undated name leaves the date out with the separator next to it
    separators.splice(at > 0 ? at - 1 : 0, 1);
    order.splice(at, 1);
  }
  const groups: Record<NameToken, string> = {
    worknum: '(?<worknum>\\d+)',
    date: `(?<date>${DATE})`,
    title: '(?<title>.*?)',
    author: '(?<author>.*?)',
  };
  let out = groups[order[0]];
  separators.forEach((sep, i) => (out += escape(sep) + groups[order[i + 1]]));
  return new RegExp(`^${out}$`, 'd');
}

function real(stamp: string): boolean {
  const [y, m, d] = stamp.split('-').map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

export interface NameParts {
  worknum: string;
  title: string;
  author: string;
  date: string;
}

/** the parts a name holds when it is wholly in the pattern, or null */
export function readName(name: string, pattern: NamePattern = active): NameParts | null {
  const b = base(name);
  for (const dated of [true, false]) {
    const match = regex(pattern, dated).exec(b);
    if (!match?.groups) continue;
    const date = match.groups['date'] ?? '';
    if (date && !real(date)) continue;
    const parts: NameParts = { worknum: match.groups['worknum'], title: match.groups['title'], author: match.groups['author'], date };
    if (!dated) emptyPartBeforeDate(parts, pattern);
    return parts;
  }
  return null;
}

/**
 * A name with an empty part beside the date - an anonymous work's, `1 Title - 2026-08-02` - reads
 * as the pattern without a date, its date taken for the author. When the part next to where the
 * date goes is itself a real YYYY-MM-DD, it is the date, and the part is empty. The helper's
 * `_empty_part_before_date`.
 */
function emptyPartBeforeDate(parts: NameParts, pattern: NamePattern): void {
  const at = pattern.order.indexOf('date');
  for (const side of [at - 1, at + 1]) {
    if (side < 0 || side >= pattern.order.length) continue;
    const token = pattern.order[side] as Exclude<NameToken, 'date'>;
    const value = parts[token] ?? '';
    if (/^\d{4}-\d{2}-\d{2}$/.test(value) && real(value)) {
      parts.date = value;
      parts[token] = '';
      return;
    }
  }
}

function sepRegex(sep: string): string {
  // the default's single space reads as any white space, as a name always has been read
  return sep.trim() === '' ? '\\s' : escape(sep);
}

function separatorBefore(pattern: NamePattern, token: NameToken): string {
  const at = pattern.order.indexOf(token);
  return at > 0 ? pattern.separators[at - 1] : '';
}

function separatorAfter(pattern: NamePattern, token: NameToken): string {
  const at = pattern.order.indexOf(token);
  return at < pattern.separators.length ? pattern.separators[at] : '';
}

/**
 * A name in `pattern` from its parts - as the helper's `file_stem` writes one, less its
 * shortening. Undated leaves the date out with the separator beside it.
 */
export function nameFrom(pattern: NamePattern, parts: NameParts, dated = true): string {
  const order = [...pattern.order];
  const separators = [...pattern.separators];
  if (!dated) {
    const at = order.indexOf('date');
    separators.splice(at > 0 ? at - 1 : 0, 1);
    order.splice(at, 1);
  }
  let out = parts[order[0]];
  separators.forEach((sep, i) => (out += sep + parts[order[i + 1]]));
  return out;
}

/** the version a work's file holds - the date where the pattern puts it - or '' */
export function fileDate(name: string, pattern: NamePattern = active): string {
  const b = base(name);
  // the number and the date are what a run needs - the entry to find, and which version the file
  // holds - so where the pattern puts the date at the start or the end it is read there alone,
  // whatever the title and author look like (the helper's `file_date`)
  let match: RegExpExecArray | null = null;
  if (pattern.order[pattern.order.length - 1] === 'date') {
    match = new RegExp(`(?:^|${sepRegex(separatorBefore(pattern, 'date'))})(${DATE})$`).exec(b);
    return match && real(match[1]) ? match[1] : '';
  }
  if (pattern.order[0] === 'date') {
    match = new RegExp(`^(${DATE})(?:${sepRegex(separatorAfter(pattern, 'date'))}|$)`).exec(b);
    return match && real(match[1]) ? match[1] : '';
  }
  // a date in the middle can only be found by reading the whole name
  return readName(name, pattern)?.date ?? '';
}

/** where the work number sits in a name's base (no folder, no extension), or null */
export function numberSpan(name: string, pattern: NamePattern = active): [number, number] | null {
  const b = base(name);
  for (const dated of [true, false]) {
    const match = regex(pattern, dated).exec(b);
    if (!match?.indices?.groups) continue;
    const date = match.groups?.['date'];
    if (date && !real(date)) continue;
    const span = match.indices.groups['worknum'];
    if (span) return [span[0], span[1]];
  }
  const order = pattern.order.filter((x) => x !== 'date');
  // the number has to be followed by a separator, so a title that merely starts with digits
  // ('99 Red Balloons' is a work number, '99Red Balloons' is not) isn't mistaken for one
  if (order[0] === 'worknum') {
    const after = separatorAfter(pattern, 'worknum');
    const follows = after.trim() === '' ? '[\\s_.-]' : escape(after);
    const match = new RegExp(`^(\\d+)(?:${follows}|$)`).exec(b);
    return match ? [0, match[1].length] : null;
  }
  if (order[order.length - 1] === 'worknum') {
    // only after the separator the pattern puts before it, so 'Part 2' ending a title is never
    // read as work 2
    let end = b.length;
    const date = fileDate(name, pattern);
    if (date && pattern.order[pattern.order.length - 1] === 'date') {
      end = b.slice(0, b.lastIndexOf(date)).replace(new RegExp(`(?:${escape(separatorBefore(pattern, 'date'))})$`), '').trimEnd().length;
    }
    const head = b.slice(0, end);
    const match = new RegExp(`(?:^|${sepRegex(separatorBefore(pattern, 'worknum'))})(\\d+)$`).exec(head);
    return match ? [head.length - match[1].length, head.length] : null;
  }
  return null;
}

/** the AO3 work number a work's file name holds where the pattern puts it, or null */
export function workNumber(name: string, pattern: NamePattern = active): string | null {
  const span = numberSpan(name, pattern);
  return span ? base(name).slice(span[0], span[1]) : null;
}
