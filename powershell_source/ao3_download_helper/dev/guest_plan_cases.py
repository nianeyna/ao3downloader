"""Write gui_source/src/app/guest-plan-cases.ts: the helper's own checklist for every run and
the choices that shape it, which guest mode's pretend runs (`guest-runs.ts`) must list too.

    uv run --no-sync python dev/guest_plan_cases.py

`test/test_guest_steps.py` fails while the file is not what this writes, so a change to
`server.step_plan` is noticed; `guest-runs.spec.ts` then holds `guestPlan` to the file.
"""

import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from source_code import server  # noqa: E402

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..',
                      'gui_source', 'src', 'app', 'guest-plan-cases.ts')

FILETYPES = (['JSON', 'HTML'], ['JSON'], ['HTML'])
# the choices step_plan reads, each on and off
CHOICES = ('collectionWorks', 'series', 'replaceOutdated', 'reindex', 'dates', 'images', 'nonBookmarks',
           'skipIndex', 'recheck')
# a choice whose 'on' sends a false option: a custom run told to skip its indexing
SENT_FALSE = {'skipIndex': 'reindex'}
ACTIONS = ('bookmarks', 'quick', 'custom', 'new', 'sync', 'update', 'work', 'works',
           'import', 'collections', 'collection')


def cases() -> list[dict]:
    found = []
    for action in ACTIONS:
        for filetypes in FILETYPES:
            for flags in itertools.product((False, True), repeat=len(CHOICES)):
                options = {name: on for name, on in zip(CHOICES, flags) if on}
                for choice, option in SENT_FALSE.items():
                    if options.pop(choice, False): options[option] = False
                job = server.Job(action, list(filetypes), 'Someone', server.resolve_options(options))
                found.append({'action': action, 'filetypes': filetypes, 'options': options,
                              'plan': [[step, label] for step, label in server.step_plan(job)]})
    # the same plan reached by several choice sets is one case: keep the first of each
    unique, seen = [], set()
    for case in found:
        key = json.dumps([case['action'], case['filetypes'], case['plan']])
        if key not in seen:
            seen.add(key)
            unique.append(case)
    return unique


def text() -> str:
    return ('// written by powershell_source/ao3_download_helper/dev/guest_plan_cases.py - do not edit.\n'
            '// the helper\'s own checklist (server.step_plan) for each run and the choices that shape\n'
            '// it: guest mode\'s pretend runs list the same (guest-runs.spec.ts, test_guest_steps.py)\n'
            'export const GUEST_PLAN_CASES: { action: string; filetypes: string[]; '
            'options: Record<string, boolean>; plan: [string, string][] }[] = '
            + json.dumps(cases(), indent=1) + ';\n')


if __name__ == '__main__':
    with open(TARGET, 'w', encoding='utf-8', newline='\n') as file:
        file.write(text())
    print(f'wrote {len(cases())} cases')
