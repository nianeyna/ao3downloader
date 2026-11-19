"""Importing works whose files were found in a library with no index entry (`ACTION_IMPORT`).

The page finds them, offers to date the undated ones, and asks which formats to add and
whether to replace outdated copies; the run then indexes each from ao3, marks it imported,
and fetches only what it was told to - never overwriting a copy that is current.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from source_code import exceptions, server, strings
from source_code.ao3 import Ao3

from test.test_ao3 import _work_page_soup, make_ao3
from test.test_server import start_request


def link(n) -> str:
    return f'https://archiveofourown.org/works/{n}'


@pytest.fixture
def library(fake_fileops):
    for name in (strings.INDEXING_FOLDER_NAME, strings.WORKS_FOLDER_NAME):
        os.makedirs(os.path.join(fake_fileops.downloadfolder, name), exist_ok=True)
    return fake_fileops


def a_copy(library, name: str) -> None:
    with open(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME, name), 'wb') as f:
        f.write(b'<html>an old copy</html>')


def importing(library, monkeypatch, filetypes, replace=False, updated='2026-05-01',
              index_only=(), repair=(), replacing=None, **options):
    """Run an import over works 1 and 2, AO3 saying each was last updated on `updated`;
    answers what was fetched, by work."""

    def index_one_work(self, url, existing=None, find_existing=None):
        work = url.rsplit('/', 1)[-1]
        record = {'id': work, 'link': url, 'title': f'Fic {work}', 'authors': ['Someone'],
                  'date_updated': updated, strings.FROM_IMPORT_FIELD: True}
        self.reindexed.add(work)
        return record

    fetched: dict[str, list[str]] = {}

    def download_one_indexed(self, record, *args, **kwargs):
        kept = self.keep_formats.get(record['link']) or set()
        current = self.current_formats(record)
        fetched[record['id']] = [x for x in self.wanted_formats(record)
                                 if x.upper() not in kept and x.upper() not in current]
        if replacing is not None:
            replacing[record['id']] = dict(self.superseded.get(record['link']) or {})

    monkeypatch.setattr(Ao3, 'index_one_work', index_one_work)
    monkeypatch.setattr(Ao3, 'download_one_indexed', download_one_indexed)
    monkeypatch.setattr(server, 'finish_run', MagicMock())
    job = server.Job(server.ACTION_IMPORT, filetypes, '',
                     server.resolve_options({'replaceOutdated': replace,
                                             'indexOnly': list(index_only),
                                             'repair': list(repair), **options}),
                     url=f'{link(1)}\n{link(2)}')
    job.ask = MagicMock(side_effect=AssertionError('an import asked a question'))
    server.run_import(job, library, MagicMock(), MagicMock())
    return job, fetched


# region starting one

def test_an_import_takes_the_works_found_one_link_to_a_line():
    sent, [job], _ = start_request(server.ACTION_IMPORT, '1 2 3', username='', password='',
                                   skipLogin=True)

    assert sent['status'] == 202
    assert job.url == '\n'.join(link(n) for n in (1, 2, 3))


def test_an_import_with_nothing_found_is_refused():
    sent, jobs, _ = start_request(server.ACTION_IMPORT, ' ')
    assert sent['status'] == 400
    assert sent['body']['error'] == strings.ERROR_NO_IMPORT_WORKS
    assert jobs == []


def test_an_import_takes_far_more_works_than_several_fics_do():
    many = ' '.join(str(n) for n in range(1, server.MAX_WORK_LINKS + 2))
    sent, _, _ = start_request(server.ACTION_IMPORT, many)
    assert sent['status'] == 202
    sent, _, _ = start_request(server.ACTION_WORKS, many)
    assert sent['status'] == 400


def test_an_import_takes_any_number_of_works():
    many = ' '.join(str(n) for n in range(1, 20_002))
    sent, _, _ = start_request(server.ACTION_IMPORT, many)
    assert sent['status'] == 202


def test_replacing_outdated_copies_is_the_imports_option_alone():
    sent, [job], _ = start_request(server.ACTION_IMPORT, '1', replaceOutdated=True)
    assert job.options['replaceOutdated'] is True
    sent, [job], _ = start_request(server.ACTION_WORKS, '1', replaceOutdated=True)
    assert job.options['replaceOutdated'] is False


def test_an_import_needs_no_username_without_a_login():
    assert server.ACTION_IMPORT not in server.USERNAME_ACTIONS
    sent, [job], _ = start_request(server.ACTION_IMPORT, '1', username='Someone', password='',
                                   skipLogin=True)
    assert sent['status'] == 202
    assert job.username == ''

# endregion


# region what it does

def test_an_import_has_its_own_checklist_with_no_series_walk():
    job = server.Job(server.ACTION_IMPORT, ['JSON', 'HTML'], '', server.resolve_options({}))
    plan = dict(server.step_plan(job))
    assert plan['index'] == strings.STEP_INDEX_IMPORT
    assert plan['download'] == strings.STEP_DOWNLOAD_IMPORT
    assert 'series' not in plan
    assert list(plan)[-1] == 'report'


def test_an_import_that_only_indexes_downloads_nothing():
    job = server.Job(server.ACTION_IMPORT, ['JSON'], '', server.resolve_options({}))
    plan = dict(server.step_plan(job))
    assert 'download' not in plan


def test_an_import_fetches_only_the_formats_missing_and_keeps_an_outdated_copy(library, monkeypatch):
    # dated before ao3's latest version, so outdated - kept all the same, as told
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.html')

    job, fetched = importing(library, monkeypatch, ['JSON', 'HTML', 'EPUB'])

    assert fetched['1'] == ['EPUB']
    assert fetched['2'] == ['HTML', 'EPUB']
    assert job.options['overwrite'] is False


def test_an_import_with_every_format_held_fetches_nothing_for_that_work(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'])

    assert '1' not in fetched


def test_an_import_told_to_replaces_an_outdated_copy(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], replace=True)

    assert fetched['1'] == ['HTML']


def test_an_import_told_to_overwrite_fetches_a_current_copy_again(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2026-05-01.html')

    job, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], replace=True, overwrite=True)

    assert fetched['1'] == ['HTML']
    assert job.options['overwrite'] is True


def test_an_import_not_told_to_overwrite_keeps_a_current_copy(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2026-05-01.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], replace=True)

    assert '1' not in fetched


def test_an_import_overwriting_still_keeps_a_file_with_no_date_in_its_name(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], replace=True, overwrite=True)

    assert fetched.get('1', []) == []


def test_overwriting_is_offered_to_an_import_and_not_to_several_fics_by_request():
    sent, [job], _ = start_request(server.ACTION_IMPORT, '1', overwrite=True)
    assert job.options['overwrite'] is True
    sent, [job], _ = start_request(server.ACTION_QUICK, '', overwrite=True)
    assert job.options['overwrite'] is False


def test_replacing_with_no_format_added_replaces_only_the_formats_a_work_has(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.pdf')

    job, fetched = importing(library, monkeypatch, ['JSON'], replace=True)

    assert fetched['1'] == ['PDF']
    assert fetched.get('2', []) == []
    assert 'download' in dict(server.step_plan(job))


def test_replacing_with_a_format_added_still_gives_every_work_that_format(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.pdf')

    _, fetched = importing(library, monkeypatch, ['JSON', 'EPUB'], replace=True)

    assert sorted(fetched['1']) == ['EPUB', 'PDF']
    assert fetched['2'] == ['EPUB']


def test_works_an_import_only_indexes_get_no_format(library, monkeypatch, capsys):
    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], index_only=['2'])

    assert fetched['1'] == ['HTML']
    assert '2' not in fetched
    assert strings.AO3_INFO_IMPORT_INDEX_ONLY.format(1) in capsys.readouterr().out


def test_only_an_import_may_name_works_to_index_only():
    sent, [job], _ = start_request(server.ACTION_IMPORT, '1 2', indexOnly=['2', 'x'])
    assert job.options['indexOnly'] == ['2']
    sent, [job], _ = start_request(server.ACTION_WORKS, '1 2', indexOnly=['2'])
    assert job.options['indexOnly'] == []


def test_an_import_never_replaces_a_current_copy_even_when_told_to_replace_outdated_ones(
        library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2026-05-01.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], replace=True)

    assert '1' not in fetched


def test_an_import_leaves_an_undated_copy_alone_without_asking(library, monkeypatch, capsys):
    # the page offered to date it before the run; left undated there, it stays so
    a_copy(library, '1 Fic 1 - Someone.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], replace=True)

    assert '1' not in fetched
    assert strings.AO3_INFO_IMPORT_UNDATED_KEPT in capsys.readouterr().out


def test_an_import_says_it_is_keeping_the_copies_you_have(library, monkeypatch, capsys):
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.html')

    importing(library, monkeypatch, ['JSON', 'HTML', 'EPUB'])

    assert strings.AO3_INFO_IMPORT_KEEPING in capsys.readouterr().out


def test_a_work_ao3_will_not_show_is_a_failure_of_that_work_alone(library, monkeypatch):
    def index_one_work(self, url, existing=None, find_existing=None):
        if url.endswith('/1'): raise exceptions.DeletedException('deleted')
        return {'id': '2', 'link': url, 'date_updated': '2026-05-01'}

    monkeypatch.setattr(Ao3, 'index_one_work', index_one_work)
    monkeypatch.setattr(server, 'download_planned', MagicMock())
    monkeypatch.setattr(server, 'finish_run', MagicMock())
    job = server.Job(server.ACTION_IMPORT, ['JSON', 'HTML'], '', server.resolve_options({}),
                     url=f'{link(1)}\n{link(2)}')

    server.run_import(job, library, MagicMock(), MagicMock())

    assert [x['link'] for x in job.ao3.failures] == [link(1)]
    records = server.download_planned.call_args.args[3]
    assert [r['id'] for r in records] == ['2']
    assert server.download_planned.call_args.kwargs['keep_existing'] is True
    server.finish_run.assert_called_once()

# endregion


# region where it says the work came from

@pytest.mark.parametrize('existing, page, marked', [
    (None, {'bookmarked': False}, True),                       # not yours
    (None, {}, True),                                          # the page could not say
    (None, {'bookmarked': True}, False),                       # it is your bookmark
])
def test_a_work_an_import_indexes_is_marked_imported_unless_it_is_your_bookmark(existing, page, marked):
    ao3, repo, _ = make_ao3()
    ao3.origin_field = strings.FROM_IMPORT_FIELD
    repo.get_soup.return_value = _work_page_soup()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.ao3.bookmark_state', return_value=page):
        record = ao3.index_one_work(link(111), existing)

    assert record.get(strings.FROM_IMPORT_FIELD) is (True if marked else None)
    # not 'downloaded by its link': nobody asked for it by one
    assert strings.FROM_LINK_FIELD not in record


def test_from_import_is_an_identity_field_kept_through_every_later_reading():
    from source_code import indexing
    first = indexing.merge(None, {'id': '1', 'link': 'l', 'title': 'A', 'from_import': True}, 't1')
    later = indexing.merge(first, {'id': '1', 'link': 'l', 'title': 'B'}, 't2')
    assert indexing.flatten(later)['from_import'] is True
    assert all('from_import' not in reading for reading in later['indexes'])


def test_an_imports_retry_of_its_failures_is_still_an_import():
    job = server.Job(server.ACTION_IMPORT, ['JSON'], '', server.resolve_options({}))
    earlier = {'id': 'r1', 'action': server.ACTION_IMPORT, 'status': 'partial',
               'filetypes': ['JSON'], 'options': {}, 'url': f'{link(1)}\n{link(2)}',
               'failures': [{'id': '1', 'link': link(1), 'error': 'gone'},
                            {'id': '2', 'link': link(2), 'error': 'gone'}]}
    job.options['resume'], job.options['retryMode'] = 'r1', server.RETRY_FAILED
    with patch.object(server.runs, 'find_run', return_value=earlier), \
         patch.object(server, 'retry_progress', return_value={}), \
         patch.object(server, 'retry_problem', return_value=''):
        server.prepare_resume(job, MagicMock())
    assert job.action == server.ACTION_IMPORT
    assert job.url == f'{link(1)}\n{link(2)}'


def test_an_import_can_carry_on_fic_by_fic_like_several_fics():
    record = {'id': 'r1', 'action': server.ACTION_IMPORT, 'status': 'stopped',
              'url': link(1), 'progress': {}, 'options': {}}
    choices = server.retry_choices(record, set())
    assert [m['mode'] for m in choices['modes']] == [
        server.RETRY_TOP, server.RETRY_DOWNLOADS, server.RETRY_FAILED]

# endregion


# region naming files from their index entries

ENTRY = {'id': '1', 'link': link(1), 'title': 'The Fic', 'authors': ['Writer']}


def test_a_dated_file_of_an_indexed_work_is_named_from_its_entry_with_the_date_given():
    names = server.file_names_for([
        {'name': '1 old name.pdf', 'date': '2024-05-06', 'record': ENTRY},
        {'name': '9 Kept From Years Ago - Another.html', 'date': '2019-08-14'},
        {'name': '9 notes.txt', 'date': '2019-08-14'},
        {'name': '9 x.html', 'date': 'not a date'},
    ], 200)
    assert names == ['1 The Fic - Writer 2024-05-06.pdf',
                     '9 Kept From Years Ago - Another 2019-08-14.html', '', '']


def test_the_page_can_ask_for_the_names_dating_gives():
    sent = {}
    handler = MagicMock()
    handler.path = '/api/file-names'
    handler.admitted.return_value = True
    handler.read_json.return_value = {'files': [{'name': '1 x.html', 'date': '2024-01-02',
                                                 'record': ENTRY}]}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)
    server.Handler.do_POST(handler)
    assert sent == {'status': 200, 'body': {'names': ['1 The Fic - Writer 2024-01-02.html']}}


def test_an_import_renames_its_works_files_to_match_their_new_entries_keeping_their_own_dates(
        library, capsys):
    a_copy(library, '1 2020-01-01 old fic name 2024-05-06.pdf')
    a_copy(library, '1 old fic name.html')
    a_copy(library, '1 The Fic - Writer 2023-02-02.epub')
    a_copy(library, '2 Someone Else.html')

    renamed = server.name_files_from_index(library, [ENTRY])

    assert renamed == 2
    assert sorted(os.listdir(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME))) == [
        '1 The Fic - Writer 2023-02-02.epub',
        '1 The Fic - Writer 2024-05-06.pdf',
        '1 The Fic - Writer.html',
        '2 Someone Else.html',
    ]
    assert 'renamed to match its index entry' in capsys.readouterr().out


def test_an_undated_file_left_undated_by_dating_is_named_from_its_new_entry_without_the_entrys_date(
        library):
    # dating was skipped for it, then its work was looked up: the entry it now has knows when
    # AO3 last updated the work, but the file may hold an older version, so that date is no
    # part of its name
    a_copy(library, '1 old fic name.html')
    entry = {**ENTRY, 'date_updated': '2025-09-30'}

    assert server.name_files_from_index(library, [entry]) == 1
    assert os.listdir(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME)) == ['1 The Fic - Writer.html']


def test_a_file_an_import_renames_keeps_its_place_on_every_exclusion_list(library, capsys):
    import json
    a_copy(library, '1 old fic name.html')
    a_copy(library, '1 old fic name 2024-05-06.pdf')
    excluded = {'excluded': [
        {'id': '1', 'kind': 'dates', 'files': ['1 old fic name.html']},
        {'id': '1', 'kind': 'files', 'files': ['1 old fic name 2024-05-06.pdf', '1 gone.epub']},
        {'id': '9', 'kind': 'index', 'files': ['9 other.html']},
        {'id': '1', 'kind': 'duplicates', 'format': 'html', 'files': ['1 old fic name.html', '1 copy.html']},
    ]}
    with open(os.path.join(library.downloadfolder, strings.IMPORT_EXCLUDED_FILE_NAME), 'w') as f:
        json.dump(excluded, f)

    server.name_files_from_index(library, [ENTRY])

    with open(os.path.join(library.downloadfolder, strings.IMPORT_EXCLUDED_FILE_NAME)) as f:
        after = json.load(f)['excluded']
    assert [e['files'] for e in after] == [
        ['1 The Fic - Writer.html'],
        ['1 The Fic - Writer 2024-05-06.pdf', '1 gone.epub'],
        ['9 other.html'],
        ['1 The Fic - Writer.html', '1 copy.html'],
    ]
    assert strings.AO3_INFO_IMPORT_EXCLUDED_RENAMED.format(3, 'files') in capsys.readouterr().out


def test_an_import_with_no_exclusion_list_writes_none(library):
    a_copy(library, '1 old fic name.html')
    server.name_files_from_index(library, [ENTRY])
    assert not os.path.exists(os.path.join(library.downloadfolder, strings.IMPORT_EXCLUDED_FILE_NAME))


def test_an_import_never_renames_a_file_over_another(library, capsys):
    a_copy(library, '1 old.html')
    a_copy(library, '1 The Fic - Writer.html')

    assert server.name_files_from_index(library, [ENTRY]) == 0
    assert '1 old.html' in os.listdir(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME))
    assert 'left as it is' in capsys.readouterr().out


def test_a_work_already_indexed_is_not_marked_imported_by_an_import():
    ao3, repo, _ = make_ao3()
    ao3.origin_field = strings.FROM_IMPORT_FIELD
    repo.get_soup.return_value = _work_page_soup()
    existing = {'id': '111', 'link': link(111), 'title': 'A Fic', 'authors': ['library_of_alexandria'],
                'bookmarked': False}

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.ao3.bookmark_state', return_value={'bookmarked': False}):
        record = ao3.index_one_work(link(111), existing)

    assert strings.FROM_IMPORT_FIELD not in record

# endregion


# region repairing files from AO3

def test_only_an_import_may_name_files_to_repair_and_only_work_files_by_name():
    sent, [job], _ = start_request(server.ACTION_IMPORT, '1 2', repair=[
        '1 Fic.html', '2 Fic.pdf', 'works/1 Fic.html', 'no number.html', '1 Fic.txt', 5])
    assert job.options['repair'] == ['1 Fic.html', '2 Fic.pdf']
    sent, [job], _ = start_request(server.ACTION_WORKS, '1', repair=['1 Fic.html'])
    assert job.options['repair'] == []


def test_ficHubs_part_in_a_repair_needs_files_to_repair_and_the_first_agreement():
    _, [job], _ = start_request(server.ACTION_IMPORT, '1', repairFicHub=True,
                                repairFicHubUndated=True)
    assert job.options['repairFicHub'] is False
    assert job.options['repairFicHubUndated'] is False
    _, [job], _ = start_request(server.ACTION_IMPORT, '1', repair=['1 Fic.html'],
                                repairFicHubUndated=True)
    assert job.options['repairFicHubUndated'] is False
    _, [job], _ = start_request(server.ACTION_IMPORT, '1', repair=['1 Fic.html'],
                                repairFicHub=True, repairFicHubUndated=True)
    assert (job.options['repairFicHub'], job.options['repairFicHubUndated']) == (True, True)
    # naming with FicHub's date takes the same answer
    _, [job], _ = start_request(server.ACTION_IMPORT, '1', repair=['1 Fic.html'],
                                repairFicHubRename=True, repairFicHubUndated=True)
    assert job.options['repairFicHubUndated'] is True


def test_naming_with_fichubs_date_is_a_repairs_other_answer_to_ao3_failing():
    _, [job], _ = start_request(server.ACTION_IMPORT, '1', repairFicHubRename=True)
    assert job.options['repairFicHubRename'] is False
    _, [job], _ = start_request(server.ACTION_IMPORT, '1', repair=['1 Fic.html'],
                                repairFicHubRename=True)
    assert job.options['repairFicHubRename'] is True
    # FicHub's copy replacing the file wins over naming it: one answer, never both
    _, [job], _ = start_request(server.ACTION_IMPORT, '1', repair=['1 Fic.html'],
                                repairFicHub=True, repairFicHubRename=True)
    assert (job.options['repairFicHub'], job.options['repairFicHubRename']) == (True, False)


def test_an_import_that_repairs_files_downloads_even_with_no_format_asked_for():
    job = server.Job(server.ACTION_IMPORT, ['JSON'], '',
                     server.resolve_options({'repair': ['1 Fic.html']}))
    assert 'download' in dict(server.step_plan(job))


def test_a_file_chosen_to_repair_is_replaced_from_ao3_though_an_import_keeps_undated_copies(
        library, monkeypatch, capsys):
    a_copy(library, '1 Fic 1 - Someone.html')
    replacing: dict = {}

    _, fetched = importing(library, monkeypatch, ['JSON'], repair=['1 Fic 1 - Someone.html'],
                           replacing=replacing)

    assert fetched['1'] == ['HTML']
    assert os.path.basename(replacing['1']['HTML']) == '1 Fic 1 - Someone.html'
    # a work with no file of the format is not given one: the import asked for no HTML
    assert not fetched.get('2')
    out = capsys.readouterr().out
    assert strings.AO3_INFO_IMPORT_REPAIRING.format(1) in out
    assert strings.AO3_INFO_IMPORT_UNDATED_KEPT not in out


def test_a_file_not_chosen_to_repair_is_kept_beside_one_that_is(library, monkeypatch, capsys):
    a_copy(library, '1 Fic 1 - Someone.html')
    a_copy(library, '2 Fic 2 - Someone.html')

    _, fetched = importing(library, monkeypatch, ['JSON'], repair=['1 Fic 1 - Someone.html'])

    assert fetched['1'] == ['HTML']
    assert not fetched.get('2')
    assert strings.AO3_INFO_IMPORT_UNDATED_KEPT in capsys.readouterr().out


def test_a_work_only_looked_up_is_still_downloaded_for_a_file_to_repair(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone.pdf')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], index_only=['1', '2'],
                           repair=['1 Fic 1 - Someone.pdf'])

    assert fetched['1'] == ['PDF']
    assert '2' not in fetched


def test_repairing_one_format_leaves_the_works_other_copies_as_an_import_would(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone.html')
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.epub')

    _, fetched = importing(library, monkeypatch, ['JSON', 'EPUB'], repair=['1 Fic 1 - Someone.html'])

    # the outdated epub is kept - the import was not told to replace outdated copies
    assert fetched['1'] == ['HTML']


def test_a_file_already_dated_has_nothing_to_repair(library, monkeypatch, capsys):
    a_copy(library, '1 Fic 1 - Someone 2026-05-01.html')

    _, fetched = importing(library, monkeypatch, ['JSON'], repair=['1 Fic 1 - Someone.html'])

    assert not fetched.get('1')
    assert strings.AO3_INFO_REPAIR_NOTHING.format('HTML', '1') in capsys.readouterr().out


def repair_job(**options) -> server.Job:
    return server.Job(server.ACTION_IMPORT, ['JSON'], '', server.resolve_options(options))


UNDATED = {'1': {'HTML': {'path': '/lib/works/1 Fic.html', 'date': None}}}


@pytest.mark.parametrize('name, fichub_date, undated_too, taken', [
    # FicHub's copy as new as, or newer than, the date guessed from the name: taken
    ('1 Fic (3 March 2024).html', '2024-03-03', False, True),
    ('1 Fic (3 March 2024).html', '2025-01-01', False, True),
    # older than the guess: your file is kept
    ('1 Fic (3 March 2024).html', '2024-03-02', False, False),
    # no date to guess: only when the reader agreed to that too
    ('1 Fic.html', '2024-03-02', False, False),
    ('1 Fic.html', '2024-03-02', True, True),
    # FicHub gives no date: nothing to compare, so kept
    ('1 Fic (3 March 2024).html', '', True, False),
])
def test_ficHub_repairs_a_file_only_on_the_rule_agreed_to_before_the_run(
        name, fichub_date, undated_too, taken):
    job = repair_job(repair=[name], repairFicHub=True, repairFicHubUndated=undated_too)
    allowed = server.fichub_repairs(job, '1', UNDATED, {'date_updated': fichub_date}, ['HTML'])
    assert allowed == ({'HTML': '/lib/works/1 Fic.html'} if taken else {})


def test_ficHub_repairs_nothing_unless_the_reader_agreed_to_it(capsys):
    job = repair_job(repair=['1 Fic.html'])
    assert server.fichub_repairs(job, '1', UNDATED, {'date_updated': '2030-01-01'}, ['HTML']) == {}
    assert strings.AO3_INFO_REPAIR_FICHUB_OFF.format('HTML', '1', '1 Fic.html') in capsys.readouterr().out


def test_ficHub_leaves_a_file_ao3_already_repaired():
    job = repair_job(repair=['1 Fic.html'], repairFicHub=True, repairFicHubUndated=True)
    dated = {'1': {'HTML': {'path': '/lib/works/1 Fic 2026-01-01.html', 'date': '2026-01-01'}}}
    assert server.fichub_repairs(job, '1', dated, {'date_updated': '2030-01-01'}, ['HTML']) == {}


def test_an_import_keeping_your_copies_still_asks_ficHub_for_a_format_to_repair():
    have = {'1': {'HTML': {'path': 'x', 'date': None}, 'EPUB': {'path': 'y', 'date': None}}}
    assert server.fichub_formats_for('1', ['HTML', 'EPUB'], have, set(), True,
                                     repairing={'HTML'}) == ['HTML']

# endregion


# region repairing by name alone

def works_files(library) -> list[str]:
    return sorted(os.listdir(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME)))


def test_only_renaming_names_the_file_with_ao3s_date_and_downloads_nothing_for_it(
        library, monkeypatch, capsys):
    a_copy(library, '1 Fic 1 - Someone.html')

    _, fetched = importing(library, monkeypatch, ['JSON'], repair=['1 Fic 1 - Someone.html'],
                           repairRenameOnly=True)

    assert not fetched.get('1')
    assert works_files(library) == ['1 Fic 1 - Someone 2026-05-01.html']
    out = capsys.readouterr().out
    assert strings.AO3_INFO_IMPORT_RENAMING.format(1) in out
    assert "with AO3's date (1 May 2026)" in out


def test_only_renaming_never_renames_over_another_file(library, monkeypatch, capsys):
    a_copy(library, '1 Fic 1 - Someone.html')
    a_copy(library, '1 Fic 1 - Someone 2026-05-01.html')

    job, _ = importing(library, monkeypatch, ['JSON'], repair=['1 Fic 1 - Someone.html'],
                       repairRenameOnly=True)

    assert works_files(library) == ['1 Fic 1 - Someone 2026-05-01.html', '1 Fic 1 - Someone.html']
    assert 'is already taken by another file' in capsys.readouterr().out
    assert job.ao3.repair_clashes == [{
        'id': '1', 'link': link(1), 'format': 'HTML', 'file': '1 Fic 1 - Someone.html',
        'wanted': '1 Fic 1 - Someone 2026-05-01.html', 'site': strings.SOURCE_AO3}]


def test_a_repair_from_ao3_that_would_land_on_another_files_name_is_not_done(
        library, monkeypatch, capsys):
    a_copy(library, '1 Fic 1 - Someone.html')
    a_copy(library, '1 Fic 1 - Someone 2026-05-01.html')
    replacing: dict = {}

    job, fetched = importing(library, monkeypatch, ['JSON'], repair=['1 Fic 1 - Someone.html'],
                             replacing=replacing)

    # nothing fetched for it, nothing replaced: both files stay as they are
    assert not fetched.get('1')
    assert not (replacing.get('1') or {}).get('HTML')
    assert works_files(library) == ['1 Fic 1 - Someone 2026-05-01.html', '1 Fic 1 - Someone.html']
    assert 'is already taken by another file' in capsys.readouterr().out
    assert [x['file'] for x in job.ao3.repair_clashes] == ['1 Fic 1 - Someone.html']
    assert job.ao3.repair_clashes[0]['site'] == strings.SOURCE_AO3


def test_a_run_ends_by_listing_the_repairs_a_name_clash_stopped(capsys):
    ao3 = MagicMock()
    ao3.failures, ao3.skipped_works, ao3.kept_copies, ao3.fichub_older = [], [], [], []
    ao3.repair_clashes = [{'id': '1', 'link': link(1), 'format': 'HTML', 'file': 'a.html',
                           'wanted': 'b.html', 'site': strings.SOURCE_FICHUB}]
    report = MagicMock()

    server.report_failures(ao3, report)

    assert strings.AO3_INFO_REPAIR_CLASHES.format(1) in capsys.readouterr().out
    [sent] = [c.args[0] for c in report.call_args_list if c.args[0]['type'] == 'repairClashes']
    assert sent['repairClashes'] == ao3.repair_clashes


@pytest.mark.parametrize('replace', [False, True])
def test_a_work_only_renamed_and_also_updated_is_fetched_only_in_the_formats_it_lacks(
        library, monkeypatch, replace):
    # Repair from AO3 as *only rename*, and the same work updated for its date issue: the file
    # is named with AO3's date first, so the update sees it as current and fetches only what
    # the work has no file of - the renamed file is never downloaded again
    a_copy(library, '1 Fic 1 - Someone.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'EPUB'], replace=replace,
                           repair=['1 Fic 1 - Someone.html'], repairRenameOnly=True)

    assert fetched['1'] == ['EPUB']
    assert '1 Fic 1 - Someone 2026-05-01.html' in works_files(library)


def test_only_renaming_is_a_repairs_alone():
    _, [job], _ = start_request(server.ACTION_IMPORT, '1', repairRenameOnly=True)
    assert job.options['repairRenameOnly'] is False
    _, [job], _ = start_request(server.ACTION_IMPORT, '1', repair=['1 Fic.html'], repairRenameOnly=True)
    assert job.options['repairRenameOnly'] is True


def test_the_guessed_date_rule_for_fichub_is_on_unless_the_page_turns_it_off():
    assert server.resolve_options({})['repairFicHubCheck'] is True
    assert server.resolve_options({'repairFicHubCheck': False})['repairFicHubCheck'] is False


def test_ficHub_without_the_guessed_date_rule_replaces_every_file_to_repair(capsys):
    job = repair_job(repair=['1 Fic (3 March 2030).html'], repairFicHub=True, repairFicHubCheck=False)
    allowed = server.fichub_repairs(job, '1', UNDATED, {'date_updated': '2024-01-01'}, ['HTML'])
    assert allowed == {'HTML': '/lib/works/1 Fic.html'}
    assert 'as you chose for every file' in capsys.readouterr().out

# endregion
