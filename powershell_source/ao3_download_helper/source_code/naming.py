"""How a downloaded work's file is named, and how a name is read back.

The pattern is settings.ini's `FileNamePattern`: the four parts a name is made of -
`{worknum}`, `{title}`, `{author}` and `{date}` - each exactly once, in any order, with any
separator between them. Everything that writes a work's file name builds it here
(`file_stem`), and everything that reads one back - which work a file is (`work_number`) and
which version it holds (`file_date`) - reads it here, so the two cannot drift apart. Keep in
step with the page's `naming.ts`.

Two things are never trimmed or optional: the work number, which is what pairs a file with
its index entry, and the date, which is the version the file holds. When a name is too long
the title and the author are shortened instead (`FileNameLength`).

The index's own json files are not named by this pattern: they are always
`{worknum} {title} - {author}` (`strings.FILE_NAME_PATTERN`), found by the number their name
starts with, and carry no date - an index file is a work's history, and a name that changed
with the pattern would orphan it.
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass

from source_code import strings

TOKENS = ('worknum', 'title', 'author', 'date')
DEFAULT = '{worknum} {title} - {author} {date}'
SEPARATOR_MAX = 10
# how short a name's title is cut before its author is touched, and the author before both are
TITLE_FLOOR = 20
AUTHOR_FLOOR = 10

_DATE = r'\d{4}-\d{2}-\d{2}'


@dataclass(frozen=True)
class Pattern:
    """A parsed pattern: the four tokens in order, and the separator before each but the first."""

    order: tuple[str, ...]
    separators: tuple[str, ...]   # separators[i] sits between order[i] and order[i + 1]

    @property
    def text(self) -> str:
        out = '{' + self.order[0] + '}'
        for sep, token in zip(self.separators, self.order[1:]):
            out += sep + '{' + token + '}'
        return out

    def separator_before(self, token: str) -> str:
        at = self.order.index(token)
        return self.separators[at - 1] if at > 0 else ''

    def separator_after(self, token: str) -> str:
        at = self.order.index(token)
        return self.separators[at] if at < len(self.separators) else ''


def parse(text: str) -> Pattern:
    """`text` as a pattern, or ValueError saying what is wrong with it."""

    text = str(text or '').strip()
    pieces = re.split(r'(\{[^{}]*\})', text)
    order: list[str] = []
    separators: list[str] = []
    if pieces and pieces[0]:
        raise ValueError('a file name pattern has to start with one of its parts, not with text')
    if pieces and pieces[-1]:
        raise ValueError('a file name pattern has to end with one of its parts, not with text')
    for at, piece in enumerate(pieces):
        if at % 2 == 1:
            name = piece[1:-1]
            if name not in TOKENS:
                raise ValueError(f'{piece} is not a part of a file name - use {", ".join("{" + x + "}" for x in TOKENS)}')
            if name in order:
                raise ValueError(f'{piece} appears more than once')
            order.append(name)
        elif 0 < at < len(pieces) - 1:
            if not piece:
                raise ValueError('every part needs a separator before the next one')
            if '{' in piece or '}' in piece:
                raise ValueError('a separator cannot hold { or }')
            if any(c in piece for c in strings.INVALID_FILENAME_CHARACTERS):
                raise ValueError(f"the separator '{piece}' holds a character a file name cannot")
            if re.search(r'\d', piece):
                raise ValueError(f"the separator '{piece}' holds a digit, which would be read as part of a number or a date")
            if len(piece) > SEPARATOR_MAX:
                raise ValueError(f'a separator is at most {SEPARATOR_MAX} characters')
            separators.append(piece)
    missing = [x for x in TOKENS if x not in order]
    if missing:
        raise ValueError('a file name pattern needs every part: ' + ', '.join('{' + x + '}' for x in missing) + ' missing')
    return Pattern(tuple(order), tuple(separators))


def check(text: str) -> str:
    """`text` as it is kept in settings.ini, or ValueError."""

    return parse(text).text


_active = parse(DEFAULT)


def active() -> Pattern:
    """The pattern names are built and read by now."""

    return _active


def use(text: str | None) -> Pattern:
    """Build and read names by `text` from now on - the default when it is empty or not a
    pattern, so a misspelt setting can never leave files unreadable."""

    global _active
    try:
        _active = parse(text) if text else parse(DEFAULT)
    except ValueError:
        _active = parse(DEFAULT)
    return _active


def _base(name: str) -> str:
    return os.path.splitext(str(name or '').replace('\\', '/').split('/')[-1])[0].strip()


def _clean(value: str) -> str:
    return str(value or '').translate({ord(c): None for c in strings.INVALID_FILENAME_CHARACTERS}).strip()


def _assemble(pattern: Pattern, values: dict[str, str]) -> str:
    """The parts present, joined by the separator before each - a part that is empty is left
    out with its own separator, so an anonymous work does not end in a dangling ' - '."""

    out = ''
    for token in pattern.order:
        value = values.get(token) or ''
        if not value: continue
        out += (pattern.separator_before(token) if out else '') + value
    return out


def file_stem(metadata: dict, date: str, maximum: int, pattern: Pattern | None = None) -> str:
    """A work's file name, without its extension: the pattern filled in from `metadata`
    (`worknum`, `title`, `author`) and `date` (YYYY-MM-DD, or '' for none), no longer than
    `maximum` (0 for no limit). Only as much as it takes to fit: the title first, down to
    `TITLE_FLOOR` characters; then the author, down to `AUTHOR_FLOOR`; then whichever of the
    two is longer. The number and the date are never shortened."""

    pattern = pattern or _active
    values = {
        'worknum': _clean(metadata.get('worknum')),
        'title': _clean(metadata.get('title')),
        'author': _clean(metadata.get('author')),
        'date': date if re.fullmatch(_DATE, str(date or '')) else '',
    }
    stem = _assemble(pattern, values)

    def shorten(part: str, floor: int) -> None:
        # one character at a time, only as far as the name needs, and never below the floor
        nonlocal stem
        while maximum > 0 and len(stem) > maximum and len(values[part]) > floor:
            values[part] = values[part][:-1].rstrip()
            stem = _assemble(pattern, values)

    # the title gives way first, down to TITLE_FLOOR; then the author, down to AUTHOR_FLOOR;
    # only then both, the longer first - a title is what a file is recognised by
    shorten('title', TITLE_FLOOR)
    shorten('author', AUTHOR_FLOOR)
    while maximum > 0 and len(stem) > maximum:
        longer = 'title' if len(values['title']) >= len(values['author']) else 'author'
        if len(values[longer]) <= 1:
            longer = 'author' if longer == 'title' else 'title'
            if len(values[longer]) <= 1: break
        values[longer] = values[longer][:-1].rstrip()
        stem = _assemble(pattern, values)
    return stem


def _regex(pattern: Pattern, dated: bool) -> re.Pattern:
    order = list(pattern.order)
    separators = list(pattern.separators)
    if not dated:
        at = order.index('date')
        # an undated name leaves the date out with the separator next to it
        separators.pop(at - 1 if at > 0 else 0)
        order.pop(at)
    groups = {'worknum': r'(?P<worknum>\d+)', 'date': rf'(?P<date>{_DATE})',
              'title': r'(?P<title>.*?)', 'author': r'(?P<author>.*?)'}
    out = groups[order[0]]
    for sep, token in zip(separators, order[1:]):
        out += re.escape(sep) + groups[token]
    return re.compile('^' + out + '$')


def read(name: str, pattern: Pattern | None = None) -> dict | None:
    """The parts a name holds when it is wholly in the pattern - `worknum`, `title`, `author`,
    and `date` ('' when the name is the pattern without one) - or None."""

    pattern = pattern or _active
    base = _base(name)
    for dated in (True, False):
        match = _regex(pattern, dated).match(base)
        if match:
            parts = match.groupdict()
            parts.setdefault('date', '')
            if parts['date'] and not _real(parts['date']): continue
            if not dated: _empty_part_before_date(parts, pattern)
            return parts
    return None


def _empty_part_before_date(parts: dict, pattern: Pattern) -> None:
    """A name with an empty part beside the date - an anonymous work's, `1 Title - 2026-08-02` -
    reads as the pattern without a date, its date taken for the author. When the part next to
    where the date goes is itself a real YYYY-MM-DD, it is the date, and the part is empty."""

    at = pattern.order.index('date')
    for side in (at - 1, at + 1):
        if 0 <= side < len(pattern.order):
            token = pattern.order[side]
            value = parts.get(token) or ''
            if re.fullmatch(_DATE, value) and _real(value):
                parts['date'] = value
                parts[token] = ''
                return


def _real(stamp: str) -> bool:
    try:
        datetime.date.fromisoformat(stamp)
        return True
    except ValueError:
        return False


def _sep_regex(sep: str) -> str:
    # the default's single space reads as any white space, as a name always has been read
    return r'\s' if sep.strip() == '' else re.escape(sep)


def file_date(name: str, pattern: Pattern | None = None) -> str | None:
    """The version a work's file holds: the date in its name where the pattern puts it,
    written YYYY-MM-DD, or None. A date written any other way, or anywhere else, is only ever
    a guess (`parse_text.infer_date_from_filename`)."""

    pattern = pattern or _active
    base = _base(name)
    order = pattern.order
    # the number and the date are what a run needs - the entry to find, and which version the
    # file holds - so where the pattern puts the date at the start or the end, it is read there
    # alone, whatever the title and author look like: an empty author, or a title with the
    # pattern's own separators in it, can never hide it or be taken for it
    if order[-1] == 'date':
        match = re.search(rf'(?:^|{_sep_regex(pattern.separator_before("date"))})({_DATE})$', base)
        return match.group(1) if match and _real(match.group(1)) else None
    if order[0] == 'date':
        match = re.match(rf'^({_DATE})(?:{_sep_regex(pattern.separator_after("date"))}|$)', base)
        return match.group(1) if match and _real(match.group(1)) else None
    # a date in the middle can only be found by reading the whole name
    parts = read(name, pattern)
    return (parts['date'] or None) if parts is not None else None


def number_span(name: str, pattern: Pattern | None = None) -> tuple[int, int] | None:
    """Where the work number sits in a name's base (no folder, no extension), or None."""

    pattern = pattern or _active
    base = _base(name)
    for dated in (True, False):
        match = _regex(pattern, dated).match(base)
        if match and (not match.groupdict().get('date') or _real(match.group('date'))):
            return match.span('worknum')
    order = [x for x in pattern.order if x != 'date']
    # as a name has always been read when the number leads: digits, then a separator - so a
    # title that merely starts with digits is not taken for a number
    if order[0] == 'worknum':
        after = pattern.separator_after('worknum')
        follows = r'[\s_.\-]' if after.strip() == '' else re.escape(after)
        match = re.match(rf'^(\d+)(?:{follows}|$)', base)
        return match.span(1) if match else None
    if order[-1] == 'worknum':
        # only after the separator the pattern puts before it, so 'Part 2' ending a title is
        # never read as work 2
        end = len(base)
        date = file_date(name, pattern)
        if date and pattern.order[-1] == 'date':
            end = base.rfind(date)
            end = len(base[:end].rstrip(pattern.separator_before('date')).rstrip())
        before = pattern.separator_before('worknum')
        match = re.search(rf'(?:^|{_sep_regex(before)})(\d+)$', base[:end])
        return match.span(1) if match else None
    return None


def work_number(name: str, pattern: Pattern | None = None) -> str | None:
    """The AO3 work number a work's file name holds where the pattern puts it, or None."""

    span = number_span(name, pattern)
    return _base(name)[span[0]:span[1]] if span else None


def example(maximum: int, pattern: Pattern | None = None) -> str:
    """The naming rule shown as an actual name, through the same trimming a download gets."""

    worknum, title, author, date = strings.FILE_NAME_EXAMPLE_PARTS
    return file_stem({'worknum': worknum, 'title': title, 'author': author}, date,
                     maximum, pattern) + '.html'
