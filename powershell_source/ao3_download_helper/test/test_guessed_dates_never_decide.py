"""A date guessed from a file's name is never taken as the truth.

Only a date written the app's way - a space, then YYYY-MM-DD, ending the name
(`parse_text.get_date_from_filename`, the page's `dateFromFilename`) - says which version a file
holds. Anything read more loosely (`parse_text.infer_date_from_filename`, the page's `inferDate`)
is a guess: it may be shown to the reader, labelled as a guess, and used to word a recommendation
they then choose on - but nothing may decide, replace, delete or rank on it unasked.

The unindexed-copy question once read guessed dates and called them the date in the file's name,
from reaching for the loose reader where only the strict one belongs. These tests hold every place
a guess may be read to a short list, so a new one has to be argued for here, by name, rather than
slip in. Resolve issues is the one place guesses are read on purpose - it is the reader's own tool
for sorting and dating their files - and its readers are listed below as such.
"""

import ast
import os
import re

HELPER = os.path.join(os.path.dirname(__file__), '..', 'source_code')
PAGE = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'gui_source', 'src', 'app')

# every function allowed to read a guessed date, and why it is safe there
HELPER_ALLOWED = {
    # asks per file, says "(a guess)", defaults to keeping the file
    'ask_about_unsure_copies',
    # asks per work, says which dates are guesses, defaults to keeping every copy
    'ask_about_unindexed_copies',
    # picks only which copy of a format the run compares against (the nominated file for
    # comparison) when none is dated the app's way - and a copy not dated so is always asked
    # about, never replaced unasked
    'nomination_key',
    # Resolve issues' *Repair from AO3*, when AO3 fails: FicHub replaces a file the reader chose
    # to repair only if its copy is as new as the date guessed from the file's name - a rule the
    # reader agreed to, knowing it is a guess, before the run started. Off unless they did
    'fichub_repairs',
    # the same agreement for *Only rename the file* from FicHub: a file is named with FicHub's date
    # only when that is not older than the date guessed from its name, if the reader asked for that
    'rename_with_date',
}
PAGE_ALLOWED = {
    # Resolve issues' *Infer date* button: fills the dating page for the reader to check
    ('import-dialog.ts', 'inferDates'),
    # shows a file's name as dated X while sifting duplicates - words only
    ('import-dialog.ts', 'dateIn'),
    # orders a duplicate set for the reader to pick from, and is the removing page's best
    # guess only when the reader chose *Make a best guess*
    ('imports.ts', 'byRecency'),
    # Resolve issues' *Keep most recent*: a guessed date only ever stops it - one as late as the
    # certain newest means it cannot tell, and the removing step asks. Resolve issues' alone
    ('imports.ts', 'newestOf'),
    # the date a file's name carries, certain or guessed, for `byRecency`'s order above
    ('imports.ts', 'nameDate'),
    # the Works tab's row for a file no index entry matches: the date shown on it, said to be a
    # guess (`unindexed_date`); nothing is replaced, renamed or fetched on it
    ('unindexed-works.ts', 'readUnindexedFile'),
    # which of two such files in one format that row's button opens - it opens, never removes
    ('unindexed-works.ts', 'unindexedRows'),
}


def helper_files() -> list[str]:
    found = []
    for folder, _, names in os.walk(HELPER):
        if '__pycache__' in folder: continue
        found += [os.path.join(folder, n) for n in sorted(names) if n.endswith('.py')]
    return found


def helper_callers() -> set[tuple[str, str]]:
    found = set()
    for path in helper_files():
        name = os.path.relpath(path, HELPER)
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            for node in ast.walk(function):
                if isinstance(node, ast.Call) and getattr(node.func, 'attr', getattr(node.func, 'id', '')) \
                        == 'infer_date_from_filename':
                    found.add((name, function.name))
    return found


DEFINITION = re.compile(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)|'
                        r'^\s*(?:protected|private|public)\s+(?:async\s+)?(\w+)\s*\(')


def page_callers() -> set[tuple[str, str]]:
    found = set()
    for name in sorted(os.listdir(PAGE)):
        if not name.endswith('.ts') or name.endswith('.spec.ts'): continue
        with open(os.path.join(PAGE, name), encoding='utf-8') as f:
            lines = f.read().splitlines()
        current = ''
        for line in lines:
            match = DEFINITION.match(line)
            if match: current = match.group(1) or match.group(2)
            if 'inferDate(' in line and 'function inferDate(' not in line:
                found.add((name, current))
    return found


def test_the_helper_reads_a_guessed_date_only_where_it_asks_the_reader():
    callers = helper_callers()
    assert callers, 'the guessed-date reader has moved - update this test'
    assert {function for _, function in callers} <= HELPER_ALLOWED, callers


def test_the_page_reads_a_guessed_date_only_to_show_it_or_when_the_reader_asks():
    callers = page_callers()
    assert callers, 'the guessed-date reader has moved - update this test'
    assert callers <= PAGE_ALLOWED, callers
