"""Tests for ao3downloader.server — the local helper behind the web ui.

Nothing here touches the network: the download work itself is the same code the console
menu runs, which is covered by the other suites. What matters here is the plumbing around
it - what gets requested, what gets reported, and what never leaves the machine.
"""

import contextlib
import inspect
import json
import os
import socket
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest

from source_code import exceptions, parse_text, progress, server, strings
from source_code.fileio import FileOps as RealFileOps
from source_code.storage import LocalStorage


@contextlib.contextmanager
def history_on_record(records):
    """The run history as these records, newest first, however a caller reads it - all at once,
    one at a time until it has what it wants, or one run by its id."""

    def find(_fileops, run_id):
        return next((r for r in records if str(r.get('id') or '') == run_id), None)

    with patch.object(server.runs, 'read_runs', return_value=records), \
         patch.object(server.runs, 'iter_runs', side_effect=lambda *a, **k: iter(records)), \
         patch.object(server.runs, 'find_run', side_effect=find):
        yield


def on_disk(fileops, root: str):
    """Give a mocked FileOps a real local library underneath: run records and index files are
    read and written through the storage layer now, so a mock needs the real methods for it."""

    fileops.storage = LocalStorage(root)
    for name in ('read_text', 'write_text', 'list_files', 'is_file', 'exists', 'same_file',
                 'describe'):
        method = getattr(RealFileOps, name)
        getattr(fileops, name).side_effect = (
            lambda *args, _method=method: _method(fileops, *args))
    return fileops



# region resolve_filetypes

def test_resolve_filetypes_always_adds_the_forced_types():
    assert sorted(server.resolve_filetypes([])) == sorted(server.FORCED_FILETYPES)


def test_resolve_filetypes_keeps_what_was_asked_for():
    result = server.resolve_filetypes(['EPUB'])

    assert 'EPUB' in result
    for forced in server.FORCED_FILETYPES:
        assert forced in result


def test_resolve_filetypes_does_not_duplicate_a_forced_type():
    result = server.resolve_filetypes([strings.AO3_DOWNLOAD_TYPE_METADATA, 'HTML', 'HTML'])

    assert result.count('HTML') == 1
    assert result.count(strings.AO3_DOWNLOAD_TYPE_METADATA) == 1


def test_resolve_filetypes_drops_anything_unrecognised():
    # the request is not to be trusted just because the ui locks the checkboxes
    result = server.resolve_filetypes(['EPUB', 'EXE', '../../etc/passwd'])

    assert 'EXE' not in result
    assert '../../etc/passwd' not in result
    assert 'EPUB' in result


def test_resolve_filetypes_handles_a_missing_list():
    assert sorted(server.resolve_filetypes(None)) == sorted(server.FORCED_FILETYPES)


def test_only_the_metadata_is_forced():
    # everything else costs a request per work, so a metadata-only run has to be possible:
    # indexing reads the listing pages, which is a twentieth of the requests
    assert server.FORCED_FILETYPES == [strings.AO3_DOWNLOAD_TYPE_METADATA]


def test_a_metadata_only_run_downloads_no_works():
    assert server.resolve_filetypes([]) == [strings.AO3_DOWNLOAD_TYPE_METADATA]


def test_html_is_offered_by_default_but_can_be_turned_off():
    assert 'HTML' in server.DEFAULT_FILETYPES
    assert 'HTML' not in server.FORCED_FILETYPES

# endregion


# region resolve_options

def test_resolve_options_defaults_match_the_console_defaults():
    assert server.resolve_options(None) == {
        'start': 1, 'pages': 0, 'series': False, 'images': False, 'workdates': False,
        'reindex': True, 'dates': False, 'order': '', 'recheck': False, 'skipLogin': False, 'dateFrom': '', 'dateTo': '',
        'overwrite': False, 'floorRun': '', 'nonBookmarks': False, 'resume': '', 'retryMode': '',
        'collectionWorks': False, 'subcollections': False, 'parentCollections': False,
        'replaceOutdated': False, 'indexOnly': [],
    }


def test_resolve_options_reads_what_was_asked_for():
    result = server.resolve_options(
        {'start': '5', 'pages': '8', 'series': True, 'images': True, 'workdates': True,
         'reindex': False, 'dates': True, 'order': 'bookmarked', 'dateFrom': '2026-01-01',
         'dateTo': '2026-06-30', 'overwrite': True, 'nonBookmarks': True,
         'collectionWorks': True, 'subcollections': True, 'parentCollections': True})

    assert result == {'start': 5, 'pages': 8, 'series': True, 'images': True,
                      'workdates': True, 'reindex': False, 'dates': True, 'order': 'bookmarked',
                      'recheck': False, 'skipLogin': False,
                      'dateFrom': '2026-01-01', 'dateTo': '2026-06-30',
                      'overwrite': True, 'floorRun': '', 'nonBookmarks': True,
                      'resume': '', 'retryMode': '', 'collectionWorks': True, 'subcollections': True,
                      'parentCollections': True, 'replaceOutdated': False, 'indexOnly': []}


def test_a_date_that_cannot_be_read_is_no_date_at_all():
    # get_date_stamp returns '' for anything it cannot parse, and an empty bound means
    # 'no limit that end' rather than a window nobody asked for
    result = server.resolve_options({'dates': True, 'dateFrom': 'last tuesday'})

    assert result['dateFrom'] == ''


def test_json_is_added_back_even_when_a_request_leaves_it_out():
    # the ui locks it on, but a request is not trusted to have honoured that
    assert server.resolve_filetypes(['HTML']) == ['HTML', 'JSON']


def test_a_run_that_will_not_index_is_not_given_json():
    # json *is* the index. adding it back to a run that reads no listing would report a
    # file type the run never writes, which is worse than not offering it
    assert server.resolve_filetypes(['HTML'], force=False) == ['HTML']
    assert server.resolve_filetypes(['HTML', 'JSON'], force=False) == ['HTML', 'JSON']


def test_a_run_indexes_unless_it_was_actually_told_not_to():
    # the dangerous default is the other way round: a run that quietly skipped indexing
    # would judge everything against however stale the index happened to be
    assert server.resolve_options({})['reindex'] is True
    assert server.resolve_options({'reindex': None})['reindex'] is True
    assert server.resolve_options({'reindex': False})['reindex'] is False


def test_a_work_link_is_accepted_as_a_link_or_as_a_bare_number():
    # pasting the number off the address bar is as natural as pasting the whole url
    assert server.work_link('1234567') == 'https://archiveofourown.org/works/1234567'
    assert server.work_link('https://archiveofourown.org/works/1234567') == \
        'https://archiveofourown.org/works/1234567'
    # a chapter link, or anything else with the work number in it, still names one work
    assert server.work_link('https://archiveofourown.org/works/1234567/chapters/86677150') \
        == 'https://archiveofourown.org/works/1234567'


@pytest.mark.parametrize('value', [
    '', '   ', None,
    'https://archiveofourown.org/series/12345',
    'https://archiveofourown.org/collections/somename',
    'https://archiveofourown.org/users/Someone/bookmarks',
    'https://example.com/works/1234567',
    'not a link at all',
])
def test_anything_that_is_not_one_work_is_refused(value):
    # refused before a run starts rather than after, so a typo is an answer not a failure
    assert server.work_link(value) is None


def test_what_to_do_about_undated_files_is_not_a_setting():
    # it is asked during the run, once the count is known, rather than guessed at up front
    assert 'refreshUndated' not in server.resolve_options({})
    assert 'stampUndated' not in server.resolve_options({})


@pytest.mark.parametrize('start', ['abc', None, '', {}, -5, 0])
def test_resolve_options_starts_at_the_first_page_on_junk(start):
    assert server.resolve_options({'start': start})['start'] == 1


def test_resolve_options_ignores_a_stop_that_comes_before_the_start():
    # asking for pages 5 to 2 would otherwise fetch nothing at all
    result = server.resolve_options({'start': 5, 'pages': 2})

    assert result['start'] == 5
    assert result['pages'] == 0


@pytest.mark.parametrize('pages', ['abc', None, '', {}, -5])
def test_resolve_options_falls_back_to_all_pages_on_junk(pages):
    # 0 is the console's wording for "every page"
    assert server.resolve_options({'pages': pages})['pages'] == 0

# endregion


# region LineStream

def test_line_stream_emits_complete_lines():
    seen = []
    stream = server.LineStream(seen.append)

    stream.write('first\nsecond\n')

    assert seen == ['first', 'second']


def test_line_stream_holds_a_partial_line_until_it_ends():
    seen = []
    stream = server.LineStream(seen.append)

    stream.write('half ')
    assert seen == []

    stream.write('a line\n')
    assert seen == ['half a line']


def test_line_stream_skips_blank_lines():
    seen = []
    stream = server.LineStream(seen.append)

    stream.write('one\n\n   \ntwo\n')

    assert seen == ['one', 'two']

# endregion


# region Job

def test_job_keeps_history_for_listeners_that_connect_late():
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    job.emit({'type': 'a'})
    job.emit({'type': 'b'})

    assert job.history == [{'type': 'a'}, {'type': 'b'}]


def test_job_finish_marks_done_and_closes_the_queue():
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    job.finish()

    assert job.done.is_set()
    # a None on the queue is what tells a listening stream to stop
    assert job.events.get() is None

# endregion


# region run_job

@pytest.fixture
def fake_environment(tmp_path, monkeypatch):
    """Patch out everything that would touch the disk or the network."""
    monkeypatch.chdir(tmp_path)

    fileops = on_disk(MagicMock(), str(tmp_path / 'my_downloads'))
    fileops.downloadfolder = str(tmp_path / 'my_downloads')
    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)

    with patch.object(server, 'FileOps', return_value=fileops), \
         patch.object(server, 'Repository', return_value=repo):
        yield {'fileops': fileops, 'repo': repo}


def _types(job: server.Job) -> list[str]:
    return [event['type'] for event in job.history]


def test_run_job_logs_in_and_reports_start_and_finish(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    with patch.object(server, 'run_bookmarks') as run:
        server.run_job(job, 'a-password')

    run.assert_called_once()
    fake_environment['repo'].login.assert_called_once_with('someone', 'a-password')
    assert _types(job)[0] == progress.STARTED
    assert _types(job)[-1] == progress.FINISHED
    assert job.done.is_set()


def test_run_job_reports_a_failure_instead_of_raising(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')
    fake_environment['repo'].login.side_effect = ValueError('invalid username or password')

    server.run_job(job, 'wrong')

    failures = [e for e in job.history if e['type'] == progress.FAILED]
    assert len(failures) == 1
    assert 'invalid username or password' in failures[0]['error']
    assert job.done.is_set()


def test_run_job_never_records_the_password(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')
    secret = 'hunter2-should-not-appear'
    fake_environment['repo'].login.side_effect = ValueError('login failed')

    server.run_job(job, secret)

    # not in the events, and not kept on the job either
    assert secret not in repr(job.history)
    assert secret not in repr(vars(job))


def test_run_job_routes_the_update_action(fake_environment):
    job = server.Job(server.ACTION_UPDATE, ['HTML'], 'someone')

    with patch.object(server, 'run_update') as run_update, \
         patch.object(server, 'run_bookmarks') as run_bookmarks:
        server.run_job(job, 'a-password')

    run_update.assert_called_once()
    run_bookmarks.assert_not_called()


def test_run_job_turns_printed_output_into_messages(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    with patch.object(server, 'run_bookmarks', side_effect=lambda *a: print('getting metadata')):
        server.run_job(job, 'a-password')

    messages = [e['text'] for e in job.history if e['type'] == progress.MESSAGE]
    assert 'getting metadata' in messages


def test_the_run_window_gets_each_line_without_the_time_the_history_file_keeps(fake_environment):
    # the window shows what is happening now, so a time on every line is only noise there;
    # the downloaded log is read later, and needs them
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    with patch.object(server, 'run_bookmarks', side_effect=lambda *a: print('getting metadata')):
        server.run_job(job, 'a-password')

    messages = [e['text'] for e in job.history if e['type'] == progress.MESSAGE]
    assert 'getting metadata' in messages
    assert not any(x.startswith('[') for x in messages)
    assert any(x.endswith('] getting metadata') for x in job.record.data['log'])


def test_a_force_stop_tells_the_run_window_without_a_time(tmp_path):
    job, fileops = a_stuck_run(tmp_path)

    server.force_stop(job)

    messages = [e['text'] for e in job.history if e['type'] == progress.MESSAGE]
    assert messages[-1] == strings.AO3_INFO_FORCE_STOPPED


def test_run_job_says_it_is_logging_in_before_it_tries(fake_environment):
    # logging in is the first thing a run does, and it is slow. without these lines the
    # modal opens on an empty log and looks like it has hung
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    with patch.object(server, 'run_bookmarks'):
        server.run_job(job, 'a-password')

    messages = [e['text'] for e in job.history if e['type'] == progress.MESSAGE]
    assert messages[:2] == ['logging in as someone', 'successfully logged in']


def test_run_job_does_not_say_it_logged_in_when_it_did_not(fake_environment):
    fake_environment['repo'].login.side_effect = Exception('invalid username or password')
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    server.run_job(job, 'a-password')

    messages = [e['text'] for e in job.history if e['type'] == progress.MESSAGE]
    assert 'logging in as someone' in messages
    assert 'successfully logged in' not in messages

# endregion


# region run_bookmarks / run_update

def test_run_bookmarks_targets_the_users_own_bookmarks_page(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, [strings.AO3_DOWNLOAD_TYPE_METADATA], 'Someone')
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.get_metadata.assert_called_once()
    # sorted by date bookmarked by name, not trusted to ao3's default: finding where a
    # resumed run stopped goes by that date
    assert ao3.get_metadata.call_args.args[0] == \
        'https://archiveofourown.org/users/Someone/bookmarks?' + strings.AO3_SORT_BY_BOOKMARKED


def test_run_bookmarks_keeps_json_away_from_the_downloader(fake_environment):
    # Ao3 would look for a JSON download link on every work and fail
    job = server.Job(server.ACTION_BOOKMARKS,
                     [strings.AO3_DOWNLOAD_TYPE_METADATA, 'EPUB'], 'Someone')

    with patch.object(server, 'Ao3') as ao3_class, \
         patch.object(server.shared, 'already_downloaded', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3_class.call_args.args[2] == ['EPUB']


def test_run_bookmarks_skips_works_already_downloaded(fake_environment):
    # this is what makes it "newly added" rather than "everything again"
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB', 'HTML'], 'Someone')
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=['already/1']) as visited:
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    visited.assert_called_once()
    assert ao3.download.call_args.args[1] == ['already/1']


def test_a_run_writing_no_index_still_skips_what_the_folder_already_holds(tmp_path, monkeypatch):
    # no json means no index and no plan, but the listing it walks still has to be told
    # what is here - read from the folder, not from the request log
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / 'library'
    (folder / 'works').mkdir(parents=True)
    (folder / 'works' / '111 One - A 2024-01-01.html').write_bytes(b'x')
    # a work left in the top level is not looked at - works live in works/ now
    (folder / '333 Three - C 2024-01-01.html').write_bytes(b'x')
    fileops = on_disk(MagicMock(), str(folder))
    fileops.downloadfolder = str(folder)
    fileops.worksfolder = str(folder / 'works')
    fileops.write_log({'link': 'https://archiveofourown.org/works/222', 'title': ['222 Two']})
    job = server.Job(server.ACTION_BOOKMARKS, ['HTML'], 'Someone')
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3):
        server.run_bookmarks(job, fileops, MagicMock(), MagicMock())

    assert ao3.download.call_args.args[1] == ['https://archiveofourown.org/works/111']


def test_run_job_routes_the_collections_action(fake_environment):
    job = server.Job(server.ACTION_COLLECTIONS, ['JSON'], 'Someone')

    with patch.object(server, 'run_collections') as run_collections, \
         patch.object(server, 'run_bookmarks') as run_bookmarks, \
         patch.object(server, 'run_update') as run_update:
        server.run_job(job, 'a-password')

    run_collections.assert_called_once()
    run_bookmarks.assert_not_called()
    run_update.assert_not_called()


def test_run_collections_targets_the_users_own_collections(fake_environment):
    job = server.Job(server.ACTION_COLLECTIONS, ['JSON'], 'Someone')
    ao3 = MagicMock()
    ao3.get_collections.return_value = [{'name': 'alpha'}]

    with patch.object(server, 'Ao3', return_value=ao3):
        server.run_collections(job, fake_environment['fileops'],
                               fake_environment['repo'], MagicMock())

    assert ao3.get_collections.call_args.args[0] == \
        'https://archiveofourown.org/users/Someone/collections'


def test_run_collections_downloads_no_works(fake_environment):
    # collections record work ids only; the works themselves come from the index
    job = server.Job(server.ACTION_COLLECTIONS, ['JSON', 'EPUB'], 'Someone')
    ao3 = MagicMock()
    ao3.get_collections.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3) as ao3_class:
        server.run_collections(job, fake_environment['fileops'],
                               fake_environment['repo'], MagicMock())

    assert ao3_class.call_args.args[2] == []
    ao3.download.assert_not_called()


def test_collections_is_an_accepted_action():
    assert server.ACTION_COLLECTIONS in server.ACTIONS


# region downloading from the index instead of crawling again

def _job_with(**options) -> server.Job:
    return server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone',
                      server.resolve_options(options))


RECORDS = [{'id': '111', 'link': 'https://archiveofourown.org/works/111'}]


def test_the_index_is_used_when_nothing_needs_the_work_page():
    assert server.can_use_index(_job_with(), RECORDS) is True


def test_there_is_nothing_to_work_from_without_an_index():
    # a run with json unticked has no record of the work numbers
    assert server.can_use_index(_job_with(), []) is False


def test_embedded_images_need_the_work_page():
    # the image links are on it, and nothing else lists them
    assert server.can_use_index(_job_with(images=True), RECORDS) is False


def test_walking_series_no_longer_needs_the_work_page():
    # series are walked from their own pages once indexing is over, and their works
    # downloaded from the index like any other - the long way round is not needed
    # a series is discovered through the work, not through the bookmarks index
    assert server.can_use_index(_job_with(series=True), RECORDS) is True


def test_run_bookmarks_downloads_from_the_index_when_it_can(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = RECORDS

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]), \
         patch.object(server, 'plan_refresh',
                      return_value={'stale': [], 'undated': [], 'superseded': {},
                                    'existing': {}}):
        server.run_bookmarks(job, fake_environment['fileops'],
                             fake_environment['repo'], MagicMock())

    ao3.download_indexed.assert_called_once()
    ao3.download.assert_not_called()


def test_run_bookmarks_reports_the_works_that_would_not_download(fake_environment):
    # a run that leaves gaps should name them, not leave it to be found in the log
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = RECORDS
    ao3.failures = [{'id': '111', 'link': 'https://archiveofourown.org/works/111',
                     'error': 'deleted'}]
    reported: list[dict] = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]), \
         patch.object(server, 'plan_refresh',
                      return_value={'stale': [], 'undated': [], 'superseded': {},
                                    'existing': {}}):
        server.run_bookmarks(job, fake_environment['fileops'],
                             fake_environment['repo'], reported.append)

    failures = [e for e in reported if e['type'] == progress.FAILURES]
    assert len(failures) == 1
    assert failures[0]['failures'][0]['id'] == '111'


def test_run_bookmarks_says_nothing_when_every_work_came_down(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = RECORDS
    ao3.failures = []
    reported: list[dict] = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]), \
         patch.object(server, 'plan_refresh',
                      return_value={'stale': [], 'undated': [], 'superseded': {},
                                    'existing': {}}):
        server.run_bookmarks(job, fake_environment['fileops'],
                             fake_environment['repo'], reported.append)

    assert not [e for e in reported if e['type'] == progress.FAILURES]


def test_run_bookmarks_walks_the_listing_when_images_were_asked_for(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'images': True}))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = RECORDS

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]), \
         patch.object(server, 'plan_refresh',
                      return_value={'stale': [], 'undated': [], 'superseded': {},
                                    'existing': {}}):
        server.run_bookmarks(job, fake_environment['fileops'],
                             fake_environment['repo'], MagicMock())

    ao3.download.assert_called_once()
    ao3.download_indexed.assert_not_called()

# endregion


# region stopping mid-run to ask a question

QUESTION = {'name': server.QUICK_QUESTION, 'count': 12, 'choices': list(server.QUICK_CHOICES)}
DEFAULT = {'choice': server.QUICK_FULL}


def a_job() -> server.Job:
    return server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone')


def test_a_question_gets_the_answer_that_comes_back():
    job = a_job()
    threading.Timer(
        0.05, lambda: job.reply({'choice': server.QUICK_SINCE_INDEX, 'date': ''})).start()

    answer = job.ask(QUESTION, DEFAULT)

    assert answer['choice'] == server.QUICK_SINCE_INDEX


def test_asking_tells_the_ui_what_is_being_asked():
    job = a_job()
    job.cancel.set()  # so the wait ends at once

    job.ask(QUESTION, DEFAULT)

    asked = [e for e in job.history if e['type'] == progress.QUESTION]
    assert asked[0]['count'] == 12
    assert asked[0]['choices'] == list(server.QUICK_CHOICES)


def test_a_stop_releases_a_run_waiting_on_a_question():
    # a run paused on a question the user walked away from still has to be stoppable
    job = a_job()
    job.cancel.set()

    assert job.ask(QUESTION, DEFAULT) == DEFAULT


def test_a_question_nobody_answers_gives_up_rather_than_waiting_for_ever(monkeypatch):
    # a tab closed without stopping the run must not leave this thread waiting on an
    # answer that can never arrive
    monkeypatch.setattr(server, 'ANSWER_TIMEOUT_SECONDS', 0)

    assert a_job().ask(QUESTION, DEFAULT) == DEFAULT


def test_the_default_is_always_the_option_that_changes_nothing():
    # whatever goes wrong, a run must not skip or delete anything on its own: the quick scan's
    # question reads the whole listing unless told otherwise
    assert DEFAULT['choice'] == server.QUICK_FULL


PER_WORK = {'name': server.INFERRED_DATE_QUESTION, 'scenario': 'ao3-unknown', 'count': 1,
            'choices': ['yes', 'no']}
KEEP = {'choice': 'no'}


def test_once_a_per_work_question_goes_unanswered_the_rest_are_not_waited_on(monkeypatch):
    # one a work: half an hour each would hold an unattended run for days
    monkeypatch.setattr(server, 'unsure_question_timeout_seconds', lambda: 0.01)
    job = a_job()
    job.unsure_timeout_minutes = None

    assert job.ask(PER_WORK, KEEP) == KEEP
    asked = len([e for e in job.history if e['type'] == progress.QUESTION])
    assert job.ask(PER_WORK, KEEP) == KEEP
    assert len([e for e in job.history if e['type'] == progress.QUESTION]) == asked


def test_ticking_always_means_nothing_to_a_question_asked_once():
    job = a_job()
    threading.Timer(0.05, lambda: job.reply({'choice': 'newest', 'always': True})).start()
    job.ask(QUESTION, DEFAULT)

    assert job.always_answers == {}


def answering(job_id, body) -> dict:
    sent: dict = {}
    handler = MagicMock()
    handler.read_json.return_value = body
    handler.send_json.side_effect = lambda status, b: sent.update(status=status, body=b)
    server.Handler.answer_job(handler, job_id)
    return sent


@contextlib.contextmanager
def registered(job: server.Job):
    with server.Handler.jobs_lock:
        server.Handler.jobs[job.id] = job
    try:
        yield job
    finally:
        with server.Handler.jobs_lock:
            server.Handler.jobs.pop(job.id, None)


def holding(job_id, hold: bool) -> dict:
    sent: dict = {}
    handler = MagicMock()
    handler.send_json.side_effect = lambda status, b: sent.update(status=status, body=b)
    server.Handler.hold_job(handler, job_id, hold)
    return sent


def test_pausing_a_run_only_sets_the_flag_the_run_reads():
    # the endpoint must answer at once rather than waiting for the run to reach a safe
    # point, or the browser would sit on a pending request for the length of a download
    with registered(a_job()) as job:
        sent = holding(job.id, True)

        assert sent['status'] == 202
        assert sent['body'] == {'paused': True}
        assert job.held.is_set()


def test_resuming_clears_it_again():
    with registered(a_job()) as job:
        holding(job.id, True)
        holding(job.id, False)

        assert not job.held.is_set()


def test_a_paused_run_can_still_be_stopped():
    # the two buttons must not be able to wedge each other: a run nobody resumes has to
    # still be stoppable, and the run itself notices the stop while it waits
    with registered(a_job()) as job:
        holding(job.id, True)
        job.cancel.set()

        assert job.cancel.is_set()
        assert job.held.is_set()


def test_resuming_a_run_nobody_paused_does_nothing_at_all():
    with registered(a_job()) as job:
        sent = holding(job.id, False)

        assert sent['status'] == 202
        assert not job.held.is_set()


def test_pausing_a_job_that_is_not_there_says_so():
    sent = holding('no-such-job', True)

    assert sent['status'] == 404


def test_a_new_run_does_not_start_out_paused():
    assert not a_job().held.is_set()


def test_an_answer_reaches_the_run_that_asked():
    with registered(a_job()) as job:
        sent = answering(job.id, {'choice': 'yes', 'date': '2024-06-01', 'always': True})

        assert sent['status'] == 202
        assert job.answer == {'choice': 'yes', 'date': '2024-06-01', 'always': True}


@pytest.mark.parametrize('choice', ['', None, 'delete everything', 'Stamp'])
def test_an_answer_that_is_not_one_of_the_choices_is_refused(choice):
    # a run waiting on an answer must not be handed something it cannot act on
    with registered(a_job()) as job:
        sent = answering(job.id, {'choice': choice})

        assert sent['status'] == 400
        assert not job.answered.is_set()


@pytest.mark.parametrize('given', ['not a date', '2024-13-45', 'today', None, ''])
def test_a_date_that_cannot_be_read_does_not_reach_the_run(given):
    # renaming a library after a half-understood date would be worse than doing nothing
    with registered(a_job()) as job:
        answering(job.id, {'choice': 'yes', 'date': given})

        assert job.answer['date'] == ''


def test_answering_a_job_that_is_gone_says_so():
    assert answering('no-such-job', {'choice': 'no'})['status'] == 404

# endregion


# region the settings a run will use

def test_read_settings_reports_what_the_run_will_actually_use(tmp_path):
    fileops = MagicMock()
    fileops.inifile = str(tmp_path / 'config' / 'settings.ini')
    fileops.downloadfolder = str(tmp_path / 'my_downloads')
    fileops.get_ini_value_integer.side_effect = lambda key, default: {
        strings.INI_WAIT_TIME: 15, strings.INI_NAME_LENGTH: 50,
        strings.INI_MAX_RETRIES: 0, strings.INI_MAX_TIMEOUTS: 3}[key]
    fileops.get_ini_value.return_value = strings.FILE_NAME_PATTERN
    fileops.get_ini_value_boolean.return_value = False

    result = server.read_settings(fileops)

    assert result['extraWaitTime'] == 15
    assert result['fileNameLength'] == 50
    # the whole breakdown, date included, since that is what a file actually looks like
    assert result['fileNamePattern'] == '{worknum} {title} - {author} {date}'


def test_read_settings_shows_the_naming_as_a_real_example(tmp_path):
    fileops = MagicMock()
    fileops.inifile = str(tmp_path / 'settings.ini')
    fileops.downloadfolder = 'downloads'
    fileops.get_ini_value_integer.side_effect = lambda key, default: (
        50 if key == strings.INI_NAME_LENGTH else 0)
    fileops.get_ini_value_boolean.return_value = False

    example = server.read_settings(fileops)['fileNameExample']

    assert parse_text.get_work_number_from_filename(example) == '1234567'
    assert parse_text.get_date_from_filename(example) == '2026-08-23'


def test_the_example_obeys_the_length_that_is_configured(tmp_path):
    # it is built through the real truncation, so a short limit shows a short name
    fileops = MagicMock()
    fileops.inifile = str(tmp_path / 'settings.ini')
    fileops.downloadfolder = 'downloads'
    fileops.get_ini_value_integer.side_effect = lambda key, default: (
        30 if key == strings.INI_NAME_LENGTH else 0)
    fileops.get_ini_value_boolean.return_value = False

    example = server.read_settings(fileops)['fileNameExample']

    # cut to the limit - a space left at the end of a shortened title or author is dropped too
    assert 28 <= len(os.path.splitext(example)[0]) <= 30
    # and the date is still the part that survives
    assert parse_text.get_date_from_filename(example) == '2026-08-23'


def test_read_settings_says_which_settings_file_is_in_force(tmp_path):
    # a helper left running from an earlier session is the usual reason settings look
    # ignored, so naming the file it read is what makes that visible
    fileops = on_disk(MagicMock(), 'downloads')
    fileops.inifile = str(tmp_path / 'config' / 'settings.ini')
    fileops.downloadfolder = 'downloads'
    fileops.get_ini_value_integer.return_value = 0
    fileops.get_ini_value.return_value = ''
    fileops.get_ini_value_boolean.return_value = False

    result = server.read_settings(fileops)

    assert result['file'] == os.path.abspath(str(tmp_path / 'config' / 'settings.ini'))
    # there is no download folder to report: the library is whichever one the page has open
    assert 'downloadFolder' not in result

# endregion


# region indexing one collection by link

def test_indexing_a_collection_by_link_is_an_accepted_action():
    assert server.ACTION_COLLECTION in server.ACTIONS
    # it is the one action that cannot work out its own link from the username
    assert server.ACTION_COLLECTION in server.ACTIONS_NEEDING_URL


def test_run_collection_indexes_the_link_it_was_given(fake_environment):
    job = server.Job(server.ACTION_COLLECTION, ['JSON'], 'Someone',
                     url='https://archiveofourown.org/collections/yuletide2024')
    ao3 = MagicMock()
    ao3.get_collection.return_value = [{'name': 'yuletide2024'}]

    with patch.object(server, 'Ao3', return_value=ao3):
        server.run_collection(job, fake_environment['fileops'],
                              fake_environment['repo'], MagicMock())

    assert ao3.get_collection.call_args.args[0] == \
        'https://archiveofourown.org/collections/yuletide2024'


def test_run_collection_downloads_no_works(fake_environment):
    job = server.Job(server.ACTION_COLLECTION, ['JSON'], 'Someone',
                     url='https://archiveofourown.org/collections/yuletide2024')
    ao3 = MagicMock()
    ao3.get_collection.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3) as constructor:
        server.run_collection(job, fake_environment['fileops'],
                              fake_environment['repo'], MagicMock())

    assert constructor.call_args.args[2] == []
    ao3.download.assert_not_called()


@pytest.mark.parametrize('url', [
    '',
    'https://example.com/collections/yuletide',
    'https://archiveofourown.org/users/Someone/collections',
    'https://archiveofourown.org/works/123',
])
def test_a_link_that_is_not_one_collection_is_refused_before_the_job_starts(url):
    # answering the request is more use than a job that starts and immediately fails
    sent = {}
    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {
        'action': server.ACTION_COLLECTION, 'username': 'Someone',
        'password': 'a-password', 'url': url}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)

    server.Handler.do_POST(handler)

    assert sent['status'] == 400
    assert 'collection' in sent['body']['error'].lower()


def started_options(action, asked, url=''):
    """Post a job and hand back the options the helper decided it would run with."""

    sent = {}
    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {
        'action': action, 'username': 'Someone', 'password': 'a-password',
        'filetypes': ['JSON', 'HTML'], 'options': asked, 'url': url}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)

    # each start on a helper running nothing: the thread is stubbed, so the run it registers
    # never ends, and the next start in the same test would be refused as a second run
    with patch.object(server.threading, 'Thread'), patch.dict(server.Handler.jobs, clear=True):
        server.Handler.do_POST(handler)

    assert sent['status'] == 202, sent
    return sent['body']['options']


@pytest.mark.parametrize('action', [server.ACTION_SYNC, server.ACTION_NEW,
                                    server.ACTION_UPDATE, server.ACTION_QUICK])
def test_a_run_that_does_not_offer_overwriting_cannot_be_told_to(action):
    # the ui never sends it, but the rule belongs at the boundary: a stray flag must not
    # make a routine run re-fetch a whole library
    assert started_options(action, {'overwrite': True})['overwrite'] is False


@pytest.mark.parametrize('action', [server.ACTION_BOOKMARKS, server.ACTION_CUSTOM])
def test_the_two_runs_that_offer_overwriting_are_taken_at_their_word(action):
    assert started_options(action, {'overwrite': True})['overwrite'] is True
    assert started_options(action, {'overwrite': False})['overwrite'] is False


def test_a_collection_link_deeper_than_the_dashboard_is_accepted():
    # whatever page of the collection was open when the link was copied
    assert parse_text.get_collection_name(
        'https://archiveofourown.org/collections/yuletide2024/works?page=2') == 'yuletide2024'

# endregion


INCOMPLETE = {'id': '111', 'link': 'https://archiveofourown.org/works/111',
              'title': 'A Fic', 'chapters_published': 3, 'chapters_total': None}
FINISHED = {'id': '222', 'link': 'https://archiveofourown.org/works/222',
            'title': 'Done', 'chapters_published': 5, 'chapters_total': 5}


KEEP_ANSWER = {'choice': 'no', 'date': ''}


def updating(ao3, index, **patches):
    """Run the update action with the index stubbed out, and nothing touching disk."""

    return [
        patch.object(server, 'Ao3', return_value=ao3),
        patch.object(server.shared, 'read_index', return_value=index),
        patch.object(server.shared, 'scan_downloaded_works',
                     return_value=patches.get('existing', {})),
        patch.object(server.shared, 'plan_downloads',
                     return_value=patches.get('plan',
                                              {'stale': [], 'undated': [], 'superseded': {}})),
        # a run asking about a file with no date waits for a reply, which would hang a test
        # that is not about the question. the ones that are drive Job.ask directly.
        patch.object(server.Job, 'ask', return_value=patches.get('answer', KEEP_ANSWER)),
    ]


def run_update_with(fake_environment, ao3, index, report=None, job=None, **patches):
    job = job or server.Job(server.ACTION_UPDATE, ['HTML'], 'Someone')
    with contextlib.ExitStack() as stack:
        for item in updating(ao3, index, **patches):
            stack.enter_context(item)
        server.run_update(job, fake_environment['fileops'], fake_environment['repo'],
                          report or MagicMock())


def test_run_update_works_from_the_index_not_from_the_files_on_disk(fake_environment):
    # nothing is parsed out of an ebook any more, and no listing is walked to find works
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    with patch.object(server.shared, 'get_files_of_type') as get_files:
        run_update_with(fake_environment, ao3, [INCOMPLETE])

    get_files.assert_not_called()
    ao3.download.assert_not_called()


def test_run_update_only_re_reads_the_works_the_index_calls_unfinished(fake_environment):
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE, FINISHED])

    asked = [call.args[0]['id'] for call in ao3.refresh_one.call_args_list]
    assert asked == ['111']


def test_run_update_asks_ao3_for_nothing_when_the_index_lists_nothing_unfinished(
        fake_environment):
    ao3 = MagicMock()
    ao3.failures = []

    run_update_with(fake_environment, ao3, [FINISHED])

    ao3.refresh_one.assert_not_called()
    ao3.download_one_indexed.assert_not_called()


def test_run_update_downloads_an_undated_copy_when_that_is_what_was_asked_for(
        fake_environment):
    # an undated file has no date to compare against, so nothing can judge it. the answer
    # to the per-work question decides
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(
        fake_environment, ao3, [INCOMPLETE],
        existing={'111': {'HTML': {'path': 'a.html', 'date': None}}},
        answer={'choice': 'yes', 'date': ''},
        plan={'stale': [], 'undated': ['https://archiveofourown.org/works/111'],
              'superseded': {}})

    fetched = ao3.download_one_indexed.call_args.args[0]
    assert fetched['id'] == '111'


def test_run_update_leaves_an_undated_copy_alone_when_that_is_what_was_asked_for(
        fake_environment):
    # keeping it is the default and the safe answer: an undated copy is left exactly as it is
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(
        fake_environment, ao3, [INCOMPLETE],
        existing={'111': {'HTML': {'path': 'a.html', 'date': None}}},
        plan={'stale': [], 'undated': ['https://archiveofourown.org/works/111'],
              'superseded': {}})

    ao3.download_one_indexed.assert_not_called()


def test_run_update_re_reads_the_index_even_for_works_it_will_not_download(
        fake_environment):
    # the index entry is rewritten for every unfinished fic; only the download is conditional
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE],
                    existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}})

    ao3.refresh_one.assert_called_once()
    ao3.download_one_indexed.assert_not_called()


def test_run_update_leaves_a_work_alone_when_nothing_about_it_moved(fake_environment):
    # a repeat run should cost the re-reads and nothing else
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE],
                    existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}})

    ao3.download_one_indexed.assert_not_called()


def test_run_update_downloads_a_work_it_has_no_copy_of(fake_environment):
    # unchanged, but missing from the folder entirely
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE], existing={})

    fetched = ao3.download_one_indexed.call_args.args[0]
    assert fetched['id'] == '111'


def test_run_update_finishes_one_fic_before_starting_the_next(fake_environment):
    # the whole point of the order here: a stopped run has completely finished every fic it
    # touched, rather than having half-finished all of them
    ao3 = MagicMock()
    order: list[str] = []
    ao3.refresh_one.side_effect = lambda record: (order.append('read ' + record['id'])
                                                  or record)
    ao3.download_one_indexed.side_effect = (
        lambda record, *a: order.append('fetch ' + record['id']))
    ao3.failures = []

    run_update_with(fake_environment, ao3,
                    [INCOMPLETE, {**INCOMPLETE, 'id': '333',
                                  'link': 'https://archiveofourown.org/works/333'}],
                    existing={})

    assert order == ['read 111', 'fetch 111', 'read 333', 'fetch 333']


def test_run_update_names_the_works_it_could_not_re_read(fake_environment):
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = [{'id': '111', 'link': 'https://archiveofourown.org/works/111',
                     'error': 'deleted'}]
    events: list[dict] = []

    run_update_with(fake_environment, ao3, [INCOMPLETE], report=events.append)

    assert [e for e in events if e['type'] == progress.FAILURES]


# region filling in formats a finished fic never had

def finished(work: str, title: str = 'Done') -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'title': title, 'chapters_published': 5, 'chapters_total': 5}


def filling(fake_environment, ao3, index, existing, skip=None, filetypes=('HTML',)):
    # filetypes defaults through a tuple rather than `or ['HTML']`, so a test passing an
    # empty list gets an empty list rather than the default back
    job = server.Job(server.ACTION_SYNC, ['HTML'], 'Someone')
    # the pass re-reads each fic before fetching it; unless a test says otherwise that
    # hands back what it was given, so the record reaching the download can be asserted on
    if ao3.refresh_one.side_effect is None:
        ao3.refresh_one.side_effect = lambda record: record
    with patch.object(server.shared, 'read_index', return_value=index), \
         patch.object(server.shared, 'scan_downloaded_works', return_value=existing):
        server.fill_missing_formats(job, fake_environment['fileops'], ao3,
                                    skip or set(), list(filetypes), MagicMock())


def test_a_finished_fic_missing_a_requested_format_is_fetched(fake_environment):
    # the case the other two passes leave behind: not new, so the newest-first walk never
    # reached it, and not unfinished, so the update pass ignored it
    ao3 = MagicMock()
    filling(fake_environment, ao3, [finished('111')], existing={})

    assert ao3.download_one_indexed.call_args.args[0]['id'] == '111'


def test_a_run_that_just_indexed_does_not_re_read_to_fill_a_gap(fake_environment):
    # it has had these entries off the listing seconds ago; asking again would cost a
    # request per fic to learn nothing
    ao3 = MagicMock()
    job = server.Job(server.ACTION_BOOKMARKS, ['HTML'], 'Someone')

    with patch.object(server.shared, 'read_index', return_value=[finished('111')]), \
         patch.object(server.shared, 'scan_downloaded_works', return_value={}):
        server.fill_missing_formats(job, fake_environment['fileops'], ao3, set(), ['HTML'],
                                    MagicMock(), reindex=False)

    ao3.refresh_one.assert_not_called()
    ao3.download_one_indexed.assert_called_once()


def test_a_gap_is_re_indexed_before_it_is_fetched(fake_environment):
    # the entry first, then the file. a file written from a stale entry carries a stale
    # date in its name, and that date is the whole of how a later run judges it
    ao3 = MagicMock()
    order: list[str] = []
    ao3.refresh_one.side_effect = lambda record: (order.append('index'), record)[1]
    ao3.download_one_indexed.side_effect = lambda *a: order.append('download')

    filling(fake_environment, ao3, [finished('111')], existing={})

    assert order == ['index', 'download']


def test_the_gap_download_uses_the_entry_as_it_now_stands(fake_environment):
    # not the one read off disk before the re-read, or the name would still be the old one
    ao3 = MagicMock()
    fresh = {**finished('111'), 'date_updated': '20 Dec 2026'}
    ao3.refresh_one.side_effect = lambda record: fresh

    filling(fake_environment, ao3, [finished('111')], existing={})

    assert ao3.download_one_indexed.call_args.args[0] is fresh


def test_a_gap_whose_fic_cannot_be_re_read_is_recorded_and_skipped(fake_environment):
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = Exception('deleted')

    filling(fake_environment, ao3, [finished('111')], existing={})

    ao3.download_one_indexed.assert_not_called()
    ao3.record_failure.assert_called_once()


def test_a_finished_fic_that_has_every_format_is_left_alone(fake_environment):
    ao3 = MagicMock()
    filling(fake_environment, ao3, [finished('111')],
            existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}})

    ao3.download_one_indexed.assert_not_called()


def test_only_the_formats_actually_missing_are_fetched(fake_environment):
    # rate limit is the scarce thing here: re-fetching a file already on disk spends a
    # request for nothing, and download_one_indexed takes whatever filetypes it is given
    ao3 = MagicMock()
    seen = []
    ao3.download_one_indexed.side_effect = lambda *a: seen.append(list(ao3.filetypes))

    filling(fake_environment, ao3, [finished('111')],
            existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}},
            filetypes=['HTML', 'PDF'])

    assert seen == [['PDF']]


def test_the_borrowed_downloader_is_handed_back_as_it_was(fake_environment):
    # the Ao3 belongs to the run, not to this pass; leaving it reconfigured would quietly
    # change what every later pass downloads
    ao3 = MagicMock()
    ao3.filetypes = ['HTML', 'PDF']

    filling(fake_environment, ao3, [finished('111')], existing={}, filetypes=['HTML', 'PDF'])

    assert ao3.filetypes == ['HTML', 'PDF']


def test_works_the_earlier_passes_handled_are_not_done_twice(fake_environment):
    ao3 = MagicMock()
    filling(fake_environment, ao3, [finished('111'), finished('222')], existing={},
            skip={'111'})

    assert [c.args[0]['id'] for c in ao3.download_one_indexed.call_args_list] == ['222']


def test_an_unfinished_fic_is_left_to_the_update_pass(fake_environment):
    # it has just been re-read and judged there; doing it again here would double the cost
    ao3 = MagicMock()
    filling(fake_environment, ao3, [INCOMPLETE], existing={})

    ao3.download_one_indexed.assert_not_called()


def test_filling_gaps_asks_ao3_for_nothing_when_no_formats_were_requested(fake_environment):
    ao3 = MagicMock()
    filling(fake_environment, ao3, [finished('111')], existing={}, filetypes=[])

    ao3.download_one_indexed.assert_not_called()

# endregion


# region the combined run

def test_a_combined_run_does_new_then_unfinished_then_the_gaps(fake_environment):
    # each pass covers what the one before it cannot, and the order is the whole design:
    # the gap check has to know what the first two already handled
    job = server.Job(server.ACTION_SYNC, ['JSON', 'HTML'], 'Someone')
    order: list[str] = []

    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server, 'index_new_bookmarks',
                      side_effect=lambda *a: order.append('new') or []), \
         patch.object(server, 'download_planned',
                      side_effect=lambda *a: order.append('download')), \
         patch.object(server, 'update_incomplete',
                      side_effect=lambda *a: order.append('update')), \
         patch.object(server, 'fill_missing_formats',
                      side_effect=lambda *a: order.append('gaps')):
        server.run_sync(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert order == ['new', 'download', 'update', 'gaps']


def test_a_combined_run_tells_the_gap_check_what_it_already_handled(fake_environment):
    job = server.Job(server.ACTION_SYNC, ['JSON', 'HTML'], 'Someone')

    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server, 'index_new_bookmarks', return_value=[finished('111')]), \
         patch.object(server, 'download_planned'), \
         patch.object(server, 'update_incomplete'), \
         patch.object(server, 'fill_missing_formats') as gaps:
        server.run_sync(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert gaps.call_args.args[3] == {'111'}


def test_a_combined_run_stops_where_it_was_cancelled(fake_environment):
    # a stop during the first pass must not start the next two
    job = server.Job(server.ACTION_SYNC, ['JSON', 'HTML'], 'Someone')

    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server, 'index_new_bookmarks',
                      side_effect=lambda *a: job.cancel.set() or []), \
         patch.object(server, 'download_planned'), \
         patch.object(server, 'update_incomplete') as update, \
         patch.object(server, 'fill_missing_formats') as gaps:
        server.run_sync(job, fake_environment['fileops'], fake_environment['repo'], None)

    update.assert_not_called()
    gaps.assert_not_called()


def test_a_new_bookmarks_run_stops_indexing_at_what_it_already_holds(fake_environment):
    job = server.Job(server.ACTION_NEW, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'indexed_work_ids', return_value={'111', '222'}), \
         patch.object(server, 'download_planned'):
        server.run_new(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.get_metadata.call_args.kwargs['known'] == {'111', '222'}
    assert ao3.get_metadata.call_args.args[0] == \
        'https://archiveofourown.org/users/Someone/bookmarks'


def test_a_custom_run_saves_images_only_when_asked(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = [finished('111')]

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'download_planned'), \
         patch.object(server, 'save_images') as images:
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    images.assert_not_called()


def test_a_custom_run_saves_images_after_the_files_are_down(fake_environment):
    # never instead of them, and never first: a work page fetched for pictures is the most
    # expendable request in the run, so it goes last
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'images': True}))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = [finished('111')]
    order: list[str] = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'download_planned',
                      side_effect=lambda *a: order.append('files')), \
         patch.object(server, 'save_images', side_effect=lambda *a: order.append('images')):
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert order == ['files', 'images']


def test_saving_images_asks_each_work_for_its_own_page(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.save_images_for.return_value = 2

    server.save_images(job, fake_environment['fileops'], ao3,
                       [finished('111'), finished('222')], MagicMock())

    assert [c.args[0]['id'] for c in ao3.save_images_for.call_args_list] == ['111', '222']


def test_a_work_page_that_will_not_load_costs_its_images_and_nothing_else(fake_environment):
    # this is the last thing a run does; losing a second copy of some pictures is not worth
    # ending it over
    job = server.Job(server.ACTION_CUSTOM, ['HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.save_images_for.side_effect = [Exception('gone'), 3]

    server.save_images(job, fake_environment['fileops'], ao3,
                       [finished('111'), finished('222')], MagicMock())

    assert ao3.save_images_for.call_count == 2
    ao3.record_failure.assert_called_once()


def test_saving_images_stops_when_the_run_is_cancelled(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['HTML'], 'Someone')
    job.cancel.set()
    ao3 = MagicMock()

    server.save_images(job, fake_environment['fileops'], ao3, [finished('111')], MagicMock())

    ao3.save_images_for.assert_not_called()


def test_a_custom_run_told_to_skip_indexing_reads_no_listing(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'reindex': False}))
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'read_index', return_value=[finished('111')]), \
         patch.object(server, 'download_planned') as download:
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.get_metadata.assert_not_called()
    assert [x['id'] for x in download.call_args.args[3]] == ['111']


# region looking every indexed work up on AO3 (`recheck`)

def test_a_custom_run_told_to_recheck_looks_every_indexed_work_up_dated_or_not(fake_environment):
    # no listing walked; every work in the index, the undated one too, goes through the
    # per-fic pass that re-reads it on AO3, rewrites its entry and judges its files by that
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'reindex': False, 'recheck': True}))
    ao3 = MagicMock()
    ao3.series_marked = {}
    undated = finished('222')
    undated.pop('date_updated', None)

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'read_index', return_value=[finished('111'), undated]), \
         patch.object(server, 'index_series_and_non_bookmarks', return_value=[]), \
         patch.object(server, 'download_planned') as planned, \
         patch.object(server, 'refresh_and_download') as pass_:
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.get_metadata.assert_not_called()
    planned.assert_not_called()
    assert sorted(x['id'] for x in pass_.call_args.args[3]) == ['111', '222']


def test_a_recheck_lists_its_own_steps():
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'reindex': False, 'recheck': True}))

    plan = dict(server.step_plan(job))

    assert list(plan) == ['login', 'index', 'read', 'series', 'check', 'update', 'fichub',
                          'cleanup', 'report']
    assert plan['read'] == strings.STEP_READ_RECHECK


@pytest.mark.parametrize('options', [
    {'recheck': True},                                     # indexing: the walk reads them
    {'reindex': False, 'recheck': True, 'dates': True},     # a window re-reads its own
])
def test_recheck_means_nothing_outside_a_custom_run_skipping_its_indexing(options):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options(options))

    assert not server.rechecks(job)


def test_a_recheck_keeps_json_and_leaves_non_bookmarks_to_itself():
    # it rewrites every entry it reads, so json stays; and it reads every non-bookmark anyway
    sent, [job], _ = start_request(server.ACTION_CUSTOM, '', reindex=False, recheck=True,
                                   nonBookmarks=True)

    assert 'JSON' in job.filetypes
    assert job.options['recheck'] is True
    assert job.options['nonBookmarks'] is False


def test_recheck_is_cleared_for_any_other_run():
    _, [job], _ = start_request(server.ACTION_CUSTOM, '', recheck=True)
    assert job.options['recheck'] is False

# endregion


def test_a_custom_run_indexes_by_default(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'download_planned'):
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.get_metadata.assert_called_once()


def test_one_fic_is_indexed_and_then_downloaded(fake_environment):
    job = server.Job(server.ACTION_WORK, ['JSON', 'HTML'], 'Someone', None,
                     'https://archiveofourown.org/works/111')
    ao3 = MagicMock()
    ao3.index_one_work.return_value = finished('111')

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'read_index', return_value=[]), \
         patch.object(server, 'download_planned') as download:
        server.run_work(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.index_one_work.call_args.args[0] == 'https://archiveofourown.org/works/111'
    assert [x['id'] for x in download.call_args.args[3]] == ['111']


def test_one_fic_already_indexed_is_handed_the_entry_it_has(fake_environment):
    # so the listing's tags, summary and bookmark fields survive a single-fic run
    job = server.Job(server.ACTION_WORK, ['JSON'], 'Someone', None,
                     'https://archiveofourown.org/works/111')
    ao3 = MagicMock()
    ao3.index_one_work.return_value = finished('111')
    held = {**finished('111'), 'summary': 'from the listing'}

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'indexed_entries', return_value={'111': held}) as found, \
         patch.object(server, 'download_planned'):
        server.run_work(job, fake_environment['fileops'], fake_environment['repo'], None)
        # handed over only once ao3 has shown the work, found by number
        found.assert_not_called()
        assert ao3.index_one_work.call_args.kwargs['find_existing']() == held
    assert found.call_args.args[2] == {'111'}


def test_one_fic_with_an_unusable_link_never_starts(fake_environment):
    job = server.Job(server.ACTION_WORK, ['JSON'], 'Someone', None, 'not a link')
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3):
        with pytest.raises(exceptions.InvalidLinkException):
            server.run_work(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.index_one_work.assert_not_called()

# endregion


# region the debug tool that skips a step

def test_one_press_skips_one_step():
    # cleared as it is read, or a single press would skip every step after it too
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone')
    job.skip.set()

    assert job.skipping() is True
    assert job.skipping() is False


def test_a_run_nobody_asked_to_skip_carries_on():
    assert server.Job(server.ACTION_SYNC, ['JSON'], 'Someone').skipping() is False


def test_skipping_abandons_the_update_pass_and_says_so(fake_environment):
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []
    job = server.Job(server.ACTION_UPDATE, ['HTML'], 'Someone')
    job.skip.set()
    events: list[dict] = []
    job.steps = server.Steps(events.append, server.step_plan(job))

    run_update_with(fake_environment, ao3, [INCOMPLETE, FINISHED], job=job)

    # nothing was done for the fic it was on...
    ao3.refresh_one.assert_not_called()
    # ...and the step says skipped, not done: it must not claim to have finished
    marks = [(e['id'], e['status']) for e in events if e['type'] == progress.STEP]
    assert ('update', progress.STEP_SKIPPED) in marks
    assert ('update', progress.STEP_DONE) not in marks


def test_skipping_abandons_the_gap_pass(fake_environment):
    ao3 = MagicMock()
    job = server.Job(server.ACTION_SYNC, ['HTML'], 'Someone')
    job.skip.set()
    events: list[dict] = []
    job.steps = server.Steps(events.append, server.step_plan(job))

    with patch.object(server.shared, 'read_index',
                      return_value=[finished('111'), finished('222')]), \
         patch.object(server.shared, 'scan_downloaded_works', return_value={}):
        server.fill_missing_formats(job, fake_environment['fileops'], ao3, set(), ['HTML'],
                                    MagicMock())

    ao3.download_one_indexed.assert_not_called()
    marks = [(e['id'], e['status']) for e in events if e['type'] == progress.STEP]
    assert ('gaps', progress.STEP_SKIPPED) in marks


def test_skipping_abandons_the_images_pass(fake_environment):
    ao3 = MagicMock()
    job = server.Job(server.ACTION_CUSTOM, ['HTML'], 'Someone',
                     server.resolve_options({'images': True}))
    job.skip.set()
    events: list[dict] = []
    job.steps = server.Steps(events.append, server.step_plan(job))

    server.save_images(job, fake_environment['fileops'], ao3, [finished('111')], MagicMock())

    ao3.save_images_for.assert_not_called()
    marks = [(e['id'], e['status']) for e in events if e['type'] == progress.STEP]
    assert ('images', progress.STEP_SKIPPED) in marks


def test_asking_an_unknown_job_to_skip_says_so():
    sent: dict = {}
    handler = MagicMock()
    handler.send_json.side_effect = lambda status, b: sent.update(status=status, body=b)

    server.Handler.skip_step(handler, 'no-such-job')

    assert sent['status'] == 404


def test_the_debug_panel_is_off_unless_settings_ini_turns_it_on(fake_environment):
    # it is for working on the app, not for using it, and skipping really does skip
    fileops = fake_environment['fileops']
    fileops.get_ini_value_boolean.return_value = False
    # read_settings builds the example file name, which does arithmetic on this
    fileops.get_ini_value_integer.return_value = 50

    assert server.read_settings(fileops)['debugTools'] is False

    fileops.get_ini_value_boolean.return_value = True
    assert server.read_settings(fileops)['debugTools'] is True

# endregion


# region a login that lapses mid-run

def test_a_lapsed_login_is_reported_as_such_rather_than_as_a_crash(fake_environment):
    # there is a specific thing to do about it, so it must not be left to be recognised
    # from the wording of an error message
    job = server.Job(server.ACTION_SYNC, ['JSON', 'HTML'], 'Someone')

    with patch.object(server, 'FileOps', return_value=fake_environment['fileops']), \
         patch.object(server, 'Repository'), \
         patch.object(server, 'run_sync',
                      side_effect=exceptions.SessionExpiredException('gone')):
        server.run_job(job, 'a-password')

    failed = [e for e in job.history if e['type'] == progress.FAILED][0]
    assert failed['sessionExpired'] is True


def test_an_ordinary_failure_is_not_flagged_as_a_lapsed_login(fake_environment):
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone')

    with patch.object(server, 'FileOps', return_value=fake_environment['fileops']), \
         patch.object(server, 'Repository'), \
         patch.object(server, 'run_sync', side_effect=Exception('something else')):
        server.run_job(job, 'a-password')

    failed = [e for e in job.history if e['type'] == progress.FAILED][0]
    assert failed['sessionExpired'] is False


def test_a_lapsed_login_ends_the_update_pass_rather_than_failing_every_fic(fake_environment):
    # the point of ending early: once the session is gone every restricted work fails the
    # same way, and a failure list of four hundred identical reasons says nothing
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = exceptions.SessionExpiredException('gone')

    with pytest.raises(exceptions.SessionExpiredException):
        server.update_one_work(ao3, INCOMPLETE, {}, ['HTML'], 50, False, 1, 3, None)

    ao3.record_failure.assert_not_called()


def test_unfinished_fics_are_done_most_recently_updated_first(fake_environment):
    # a run can be stopped, and where it got to should be the half worth having: the fics
    # ao3 touched last are the ones you are most likely waiting on
    job = server.Job(server.ACTION_UPDATE, ['JSON', 'HTML'], 'Someone')
    index = [dated('1', '01 Jan 2026'), dated('2', '01 Dec 2026'), dated('3', '01 Jun 2026')]

    with patch.object(server.shared, 'read_index', return_value=index), \
         patch.object(server.shared, 'incomplete_works', side_effect=lambda x: x), \
         patch.object(server, 'refresh_and_download') as pass_:
        server.update_incomplete(job, fake_environment['fileops'], MagicMock(),
                                 ['HTML'], MagicMock())

    assert [x['id'] for x in pass_.call_args.args[3]] == ['2', '3', '1']


def test_a_fic_this_run_just_indexed_is_not_read_again(fake_environment):
    # a listing blurb reports the same updated date a work page does, and the run wrote
    # this entry from one minutes ago. asking again spends a request to learn nothing
    ao3 = MagicMock()

    with patch.object(server.shared, 'plan_downloads',
                      return_value={'stale': [], 'undated': [], 'superseded': {},
                                    'existing': {}}):
        server.update_one_work(ao3, INCOMPLETE, {}, ['HTML'], 50, False, 1, 3, None,
                               already_fresh={str(INCOMPLETE['id'])})

    ao3.refresh_one.assert_not_called()


def test_a_fic_the_run_did_not_index_is_still_read_again(fake_environment):
    # an entry from an earlier run cannot say whether ao3 has moved on since
    ao3 = MagicMock()
    ao3.refresh_one.return_value = INCOMPLETE

    with patch.object(server.shared, 'plan_downloads',
                      return_value={'stale': [], 'undated': [], 'superseded': {},
                                    'existing': {}}):
        server.update_one_work(ao3, INCOMPLETE, {}, ['HTML'], 50, False, 1, 3, None,
                               already_fresh={'999999'})

    ao3.refresh_one.assert_called_once()


def test_a_date_window_does_not_re_read_the_fics_it_has_just_indexed(fake_environment):
    # the window walked the listing to find these, so every one of them was indexed moments
    # ago. re-reading them would be a second request per fic for the same information
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'dateFrom': '2026-01-01'}))
    ao3 = MagicMock()
    ao3.reindexed = {'1'}

    with patch.object(server, 'update_one_work') as one:
        one.return_value = 0
        server.refresh_and_download(job, fake_environment['fileops'], ao3,
                                    [dated('1', '01 Jun 2026')], [], MagicMock())

    assert one.call_args.kwargs['already_fresh'] == {'1'}


def test_a_run_that_indexed_nothing_re_reads_everything(fake_environment):
    # skip indexing, or an update run that walks no listing: there is nothing fresh, so
    # every fic has to be opened to find out where it stands
    job = server.Job(server.ACTION_UPDATE, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.reindexed = set()

    with patch.object(server, 'update_one_work') as one:
        one.return_value = 0
        server.refresh_and_download(job, fake_environment['fileops'], ao3,
                                    [dated('1', '01 Jun 2026')], [], MagicMock())

    assert one.call_args.kwargs['already_fresh'] == set()


def test_a_lapsed_login_ends_the_gap_pass_too(fake_environment):
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = exceptions.SessionExpiredException('gone')
    job = server.Job(server.ACTION_SYNC, ['HTML'], 'Someone')

    with patch.object(server.shared, 'read_index', return_value=[finished('111')]), \
         patch.object(server.shared, 'scan_downloaded_works', return_value={}):
        with pytest.raises(exceptions.SessionExpiredException):
            server.fill_missing_formats(job, fake_environment['fileops'], ao3, set(),
                                        ['HTML'], MagicMock())

# endregion


# region a quick scan

def test_a_quick_scan_indexes_back_to_the_last_completed_run(fake_environment):
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.runs, 'last_successful',
                      return_value={'started': '2026-09-01T12:00:00'}), \
         patch.object(server, 'download_planned'):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.get_metadata.call_args.kwargs['stop_before'] == '2026-09-01'


def quick_walks(fake_environment, floor, bookmarked=None, updated=None):
    """Run a quick scan and hand back each listing walk it made, in order."""

    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.side_effect = [bookmarked or [], updated or []]
    last = {'started': floor + 'T12:00:00'} if floor else None

    with patch.object(server, 'Ao3', return_value=ao3),          patch.object(server.runs, 'last_successful', return_value=last),          patch.object(server, 'download_planned') as planned:
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    return ao3.get_metadata.call_args_list, planned


def test_a_quick_scan_indexes_new_bookmarks_first_by_the_date_they_were_bookmarked(
        fake_environment):
    # the pass the updated-date walk cannot do: a fic bookmarked yesterday that ao3 last
    # updated years ago sits far below the floor on that listing and would never be reached
    walks, _ = quick_walks(fake_environment, '2026-09-01')

    first = walks[0]
    assert strings.AO3_SORT_BY_BOOKMARKED in first.args[0]
    assert first.kwargs['stop_before'] == '2026-09-01'
    assert first.kwargs['stop_on'] == 'bookmarked'


def test_a_quick_scan_then_indexes_what_ao3_has_changed_by_the_date_it_changed(
        fake_environment):
    # the stop rule is only sound on that order. the default listing is by date bookmarked
    # and jumps about by years, so this walk down an unsorted one would stop almost at once
    walks, _ = quick_walks(fake_environment, '2026-09-01')

    assert len(walks) == 2
    second = walks[1]
    assert strings.AO3_SORT_BY_UPDATED in second.args[0]
    assert second.kwargs['stop_before'] == '2026-09-01'
    assert second.kwargs.get('stop_on', 'updated') == 'updated'


def test_a_quick_scan_downloads_whatever_either_walk_found_once_each(fake_environment):
    # a fic new since the floor and also changed since it is found by both walks - that is
    # one download, not two
    walks, planned = quick_walks(
        fake_environment, '2026-09-01',
        bookmarked=[{'id': '1', 'link': 'l1'}, {'id': '2', 'link': 'l2'}],
        updated=[{'id': '2', 'link': 'l2'}, {'id': '3', 'link': 'l3'}])

    assert [x['id'] for x in planned.call_args.args[3]] == ['1', '2', '3']


def test_a_quick_scan_with_no_floor_reads_the_listing_once_not_twice(fake_environment):
    # with nothing to stop at, the bookmarked walk already read every bookmark, and a second
    # full walk would cost a request per 20 works to learn nothing new
    walks, _ = quick_walks(fake_environment, '')

    assert len(walks) == 1
    assert strings.AO3_SORT_BY_BOOKMARKED in walks[0].args[0]


def test_a_quick_scan_lists_both_walks_on_its_checklist():
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')

    plan = dict(server.step_plan(job))
    ids = [step for step, _ in server.step_plan(job)]
    assert ids.index('bookmarked') < ids.index('index') < ids.index('check')
    assert plan['bookmarked'] == strings.STEP_INDEX_BOOKMARKED_SINCE


def test_only_the_quick_scan_indexes_by_date_bookmarked():
    # the two-walk index belongs to the quick scan alone. every other run keeps the walk it
    # had, and a quick scan given a date range is the custom run's window, not this
    for action in server.ACTIONS:
        ids = plan_ids(action)
        if action == server.ACTION_QUICK:
            assert 'bookmarked' in ids
        else:
            assert 'bookmarked' not in ids, action
    # a quick scan given a date range keeps the two walks; only the custom run's window does not
    assert 'bookmarked' in plan_ids(server.ACTION_QUICK, options={'dates': True})
    assert 'bookmarked' not in plan_ids(server.ACTION_CUSTOM, options={'dates': True})


def test_a_custom_date_window_still_walks_only_by_date_updated(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'dateFrom': '2026-01-01'}))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3),          patch.object(server.shared, 'read_index', return_value=[]),          patch.object(server, 'refresh_and_download'):
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.get_metadata.call_count == 1
    call = ao3.get_metadata.call_args
    assert strings.AO3_SORT_BY_UPDATED in call.args[0]
    assert 'stop_on' not in call.kwargs


# region a quick scan told which earlier scan to measure back to

def history(*records):
    return [dict({'status': server.runs.STATUS_SUCCESS}, **r) for r in records]


def test_only_completed_scans_that_covered_everything_are_offered_as_floors(fake_environment):
    # offering a run that fails either test would let someone pick a floor with a hole behind it
    on_record = [
        {'id': 'scan', 'action': server.ACTION_BOOKMARKS, 'status': server.runs.STATUS_SUCCESS},
        {'id': 'quick', 'action': server.ACTION_QUICK, 'status': server.runs.STATUS_SUCCESS},
        {'id': 'windowed', 'action': server.ACTION_QUICK, 'status': server.runs.STATUS_SUCCESS,
         'options': {'dates': True}},
        {'id': 'stopped', 'action': server.ACTION_BOOKMARKS, 'status': server.runs.STATUS_STOPPED},
        {'id': 'sync', 'action': server.ACTION_SYNC, 'status': server.runs.STATUS_SUCCESS},
    ]

    with history_on_record(on_record):
        offered = [r['id'] for r in server.floor_runs(fake_environment['fileops'])]

    assert offered == ['scan', 'quick']


def test_a_chosen_scan_gives_the_day_it_started(fake_environment):
    on_record = history({'id': 'a', 'action': server.ACTION_BOOKMARKS,
                         'started': '2026-03-04T09:00:00'})

    with history_on_record(on_record):
        assert server.chosen_floor(fake_environment['fileops'], 'a') == '2026-03-04'
        # a run that is not a valid floor gives nothing, however it was named
        assert server.chosen_floor(fake_environment['fileops'], 'nope') == ''


def test_a_quick_scan_measures_back_to_the_scan_it_was_given(fake_environment):
    # the chosen scan wins over the latest one, and nothing is asked
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'floorRun': 'older'}))
    job.ask = MagicMock()
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []
    on_record = history(
        {'id': 'newer', 'action': server.ACTION_QUICK, 'started': '2026-09-01T12:00:00'},
        {'id': 'older', 'action': server.ACTION_BOOKMARKS, 'started': '2026-02-01T12:00:00'})

    with patch.object(server, 'Ao3', return_value=ao3),          history_on_record(on_record),          patch.object(server, 'download_planned'):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert all(c.kwargs['stop_before'] == '2026-02-01' for c in ao3.get_metadata.call_args_list)
    job.ask.assert_not_called()


def test_a_chosen_scan_that_has_since_gone_falls_back_to_the_usual_floor(fake_environment):
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'floorRun': 'deleted'}))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []
    on_record = history({'id': 'latest', 'action': server.ACTION_QUICK,
                         'started': '2026-09-01T12:00:00'})

    with patch.object(server, 'Ao3', return_value=ao3),          history_on_record(on_record),          patch.object(server, 'download_planned'):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.get_metadata.call_args_list[0].kwargs['stop_before'] == '2026-09-01'


def test_a_chosen_floor_is_checked_by_the_run_once_it_can_read_the_history(fake_environment):
    # the history is in the library, which only the page can reach - so the request cannot
    # judge the floor, and a run given one that does not qualify falls back and says so
    sent = {}
    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {
        'action': server.ACTION_QUICK, 'username': 'Someone', 'password': 'pw',
        'filetypes': ['JSON'], 'options': {'floorRun': 'made-up'}}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)

    with patch.object(server.threading, 'Thread'):
        server.Handler.do_POST(handler)

    assert sent['status'] == 202
    assert sent['body']['options']['floorRun'] == 'made-up'


def test_only_a_quick_scan_can_be_given_a_floor(fake_environment):
    with history_on_record([]):
        assert started_options(server.ACTION_BOOKMARKS, {'floorRun': 'anything'})['floorRun'] == ''

# endregion


def test_merging_walks_keeps_the_order_first_seen_and_the_newest_record():
    merged = server.merge_by_work(
        [{'id': '1', 'v': 'old'}, {'id': '2'}],
        [{'id': '1', 'v': 'new'}, {'id': '3'}])

    assert [x['id'] for x in merged] == ['1', '2', '3']
    assert merged[0]['v'] == 'new'


def test_a_quick_scan_with_no_completed_run_reads_everything(fake_environment):
    # the honest answer the first time, rather than a short walk from an invented date
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.runs, 'last_successful', return_value=None), \
         patch.object(server, 'download_planned'):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.get_metadata.call_args.kwargs['stop_before'] == ''


def test_the_first_quick_scan_indexes_and_downloads_everything(fake_environment):
    # the ui promises this, so it has to be true: with no completed run there is nothing to
    # measure back to, and the walk runs to the end of the listing
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    everything = [finished('111'), finished('222'), finished('333')]
    ao3.get_metadata.return_value = everything

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.runs, 'last_successful', return_value=None), \
         patch.object(server, 'download_planned') as download:
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    # nothing told the walk where to stop...
    assert ao3.get_metadata.call_args.kwargs['stop_before'] == ''
    # ...and every work it found went to the download
    assert [x['id'] for x in download.call_args.args[3]] == ['111', '222', '333']


def test_the_floor_ignores_runs_that_did_not_finish(fake_environment):
    # a stopped run may have given up before reaching works updated before it began
    with patch.object(server.runs, 'last_successful', return_value=None):
        assert server.quick_scan_floor(fake_environment['fileops']) == ''

    with patch.object(server.runs, 'last_successful',
                      return_value={'started': '2026-09-01T12:00:00'}):
        assert server.quick_scan_floor(fake_environment['fileops']) == '2026-09-01'


def test_a_quick_scan_indexes_then_downloads_and_stops_there(fake_environment):
    # no gap pass: that belongs to the combined run alone
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.side_effect = lambda *a, **k: order.append('index') or [finished('111')]
    order: list[str] = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.runs, 'last_successful', return_value=None), \
         patch.object(server, 'fill_missing_formats') as filling, \
         patch.object(server, 'download_planned',
                      side_effect=lambda *a: order.append('download')):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert order == ['index', 'download']
    filling.assert_not_called()


def test_one_fic_by_link_always_replaces_the_copy_you_have(fake_environment):
    # asking for one fic by hand and being told nothing happened because the copy looked
    # fine is not the answer anybody came for, and being wrong costs one request per format
    job = server.Job(server.ACTION_WORK, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({}), url='https://archiveofourown.org/works/111')
    assert job.options['overwrite'] is False

    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server.shared, 'read_index', return_value=[]), \
         patch.object(server, 'download_planned'), \
         patch.object(server, 'report_failures'):
        server.run_work(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert job.options['overwrite'] is True


def test_only_a_full_scan_or_a_plain_quick_scan_is_a_floor(fake_environment):
    # every other run covers part of the listing. one can finish perfectly while never
    # looking at a fic ao3 updated that day, and measuring back to it would skip that fic
    # permanently
    assert server.covered_the_whole_listing({'action': server.ACTION_BOOKMARKS}) is True
    assert server.covered_the_whole_listing({'action': server.ACTION_QUICK}) is True

    for action in (server.ACTION_SYNC, server.ACTION_NEW, server.ACTION_UPDATE,
                   server.ACTION_CUSTOM, server.ACTION_WORK, server.ACTION_COLLECTIONS):
        assert server.covered_the_whole_listing({'action': action}) is False, action


def test_a_quick_scan_over_a_date_range_is_not_a_floor_either():
    # it stops at the date the user picked rather than at the previous floor, so anything
    # older than that was never looked at - the same hole a half-covering run leaves
    assert server.covered_the_whole_listing(
        {'action': server.ACTION_QUICK, 'options': {'dates': True}}) is False
    assert server.covered_the_whole_listing(
        {'action': server.ACTION_QUICK, 'options': {'dates': False}}) is True


def test_the_floor_skips_finished_runs_that_were_not_scans(fake_environment):
    history = [{'status': server.runs.STATUS_SUCCESS, 'action': server.ACTION_SYNC,
                'started': '2026-09-10T12:00:00'},
               {'status': server.runs.STATUS_SUCCESS, 'action': server.ACTION_BOOKMARKS,
                'started': '2026-09-01T12:00:00'}]

    with history_on_record(history):
        assert server.quick_scan_floor(fake_environment['fileops']) == '2026-09-01'


# region a quick scan with an index but no run to measure from

def indexed(work: str, on: str) -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'last_indexed': on}


def test_the_index_offers_the_day_it_was_last_written():
    records = [indexed('1', '2026-09-01T10:00:00'), indexed('2', '2026-09-10T12:34:56'),
               indexed('3', '2026-08-01T09:00:00')]

    assert server.newest_indexed_on(records) == '2026-09-10'


def test_an_index_that_never_recorded_a_date_offers_nothing():
    assert server.newest_indexed_on([{'id': '1'}, {'id': '2', 'last_indexed': ''}]) == ''
    assert server.newest_indexed_on([]) == ''


def asked_quick(fake_environment, index, answer):
    """Drive a quick scan with no floor and an index in place, and answer what it asks."""

    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')
    asked: list[dict] = []
    # every test through here MUST stub this, or the run blocks for half an hour
    job.ask = lambda question, default: asked.append(question) or (answer or default)
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.runs, 'last_successful', return_value=None), \
         patch.object(server.shared, 'read_index', return_value=index), \
         patch.object(server, 'download_planned'):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    return asked, ao3


def test_a_quick_scan_with_an_index_but_no_floor_stops_and_asks(fake_environment):
    # reading the whole listing is hours on a large library, and an index already here may
    # be perfectly recent - built by an older version, a restored backup, a lost history
    asked, _ = asked_quick(fake_environment, [indexed('1', '2026-09-10T12:00:00')], None)

    assert len(asked) == 1
    assert asked[0]['name'] == server.QUICK_QUESTION
    assert asked[0]['date'] == '2026-09-10'
    assert asked[0]['count'] == 1


def test_answering_with_the_index_date_measures_back_to_it(fake_environment):
    _, ao3 = asked_quick(fake_environment, [indexed('1', '2026-09-10T12:00:00')],
                         {'choice': server.QUICK_SINCE_INDEX})

    assert ao3.get_metadata.call_args.kwargs['stop_before'] == '2026-09-10'


def test_answering_with_the_whole_listing_reads_everything(fake_environment):
    _, ao3 = asked_quick(fake_environment, [indexed('1', '2026-09-10T12:00:00')],
                         {'choice': server.QUICK_FULL})

    assert ao3.get_metadata.call_args.kwargs['stop_before'] == ''


def test_a_stop_or_a_closed_tab_reads_everything(fake_environment):
    # the default is the answer that cannot leave a gap: whatever goes wrong, a quick scan
    # must not quietly decide to look at less than it should
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')
    defaults: list[dict] = []
    job.ask = lambda question, default: defaults.append(default) or default
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.runs, 'last_successful', return_value=None), \
         patch.object(server.shared, 'read_index',
                      return_value=[indexed('1', '2026-09-10T12:00:00')]), \
         patch.object(server, 'download_planned'):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert defaults[0] == {'choice': server.QUICK_FULL}
    assert ao3.get_metadata.call_args.kwargs['stop_before'] == ''


def test_an_empty_index_is_not_worth_asking_about(fake_environment):
    asked, ao3 = asked_quick(fake_environment, [], None)

    assert asked == []
    assert ao3.get_metadata.call_args.kwargs['stop_before'] == ''


def test_a_run_that_has_a_floor_never_asks(fake_environment):
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')
    asked: list[dict] = []
    job.ask = lambda question, default: asked.append(question) or default
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.runs, 'last_successful',
                      return_value={'started': '2026-09-01T12:00:00'}), \
         patch.object(server.shared, 'read_index',
                      return_value=[indexed('1', '2026-09-10T12:00:00')]), \
         patch.object(server, 'download_planned'):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert asked == []
    assert ao3.get_metadata.call_args.kwargs['stop_before'] == '2026-09-01'


def test_what_was_chosen_goes_into_the_run_history(fake_environment):
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')
    job.ask = lambda question, default: {'choice': server.QUICK_SINCE_INDEX}
    job.record = MagicMock()
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.runs, 'last_successful', return_value=None), \
         patch.object(server.shared, 'read_index',
                      return_value=[indexed('1', '2026-09-10T12:00:00')]), \
         patch.object(server, 'download_planned'):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    saved = job.record.choice.call_args.args[0]
    assert saved['question'] == server.QUICK_QUESTION
    assert saved['choice'] == server.QUICK_SINCE_INDEX
    assert saved['date'] == '2026-09-10'

# endregion


def test_a_quick_scan_says_it_is_indexing_since_the_last_run():
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone')

    assert dict(server.step_plan(job))['index'] == strings.STEP_INDEX_SINCE


def test_a_quick_scan_given_a_date_range_uses_it_instead_of_the_last_run(fake_environment):
    # the two are the same mechanism given a different number; measuring back to both
    # would mean measuring back to neither
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'dateFrom': '2026-01-01'}))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.runs, 'last_successful',
                      return_value={'started': '2026-09-01T12:00:00'}) as floor, \
         patch.object(server.shared, 'read_index', return_value=[]), \
         patch.object(server, 'refresh_and_download'):
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.get_metadata.call_args.kwargs['stop_before'] == '2026-01-01'
    assert strings.AO3_SORT_BY_UPDATED in ao3.get_metadata.call_args.args[0]
    floor.assert_not_called()


def test_a_quick_scan_over_a_date_range_says_so_on_its_checklist():
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'dateFrom': '2026-01-01'}))

    plan = dict(server.step_plan(job))
    assert [step for step, _ in server.step_plan(job)] == [
        'login', 'bookmarked', 'index', 'series', 'check', 'download', 'fichub', 'cleanup', 'report']
    assert plan['bookmarked'] == strings.STEP_INDEX_BOOKMARKED_WINDOW
    assert plan['index'] == strings.STEP_INDEX_UPDATED_WINDOW


def windowed_quick(fake_environment, options, bookmarked, updated):
    job = server.Job(server.ACTION_QUICK, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options(dict(options, dates=True)))
    ao3 = MagicMock()
    ao3.get_metadata.side_effect = [bookmarked, updated]

    with patch.object(server, 'Ao3', return_value=ao3),          patch.object(server.runs, 'last_successful') as floor,          patch.object(server, 'download_planned') as planned:
        server.run_quick(job, fake_environment['fileops'], fake_environment['repo'], None)

    return ao3.get_metadata.call_args_list, planned, floor


def dated_work(work, bookmarked='', updated=''):
    return {'id': work, 'link': f'l{work}', 'date_bookmarked': bookmarked, 'date_updated': updated}


def test_a_quick_scan_date_range_walks_by_date_bookmarked_then_by_date_updated(
        fake_environment):
    # the same method as the ordinary quick scan, with the range's older end as the floor
    walks, _, floor = windowed_quick(
        fake_environment, {'dateFrom': '2026-01-01', 'dateTo': '2026-06-30'}, [], [])

    assert strings.AO3_SORT_BY_BOOKMARKED in walks[0].args[0]
    assert walks[0].kwargs['stop_before'] == '2026-01-01'
    assert walks[0].kwargs['stop_on'] == 'bookmarked'
    assert strings.AO3_SORT_BY_UPDATED in walks[1].args[0]
    assert walks[1].kwargs['stop_before'] == '2026-01-01'
    # the range replaces the last-run floor entirely
    floor.assert_not_called()


def test_each_walk_keeps_only_the_works_whose_own_date_is_in_range(fake_environment):
    # both walks start at the newest and read past the ceiling on the way down: what is
    # above it is indexed, but only works dated inside the range are downloaded
    _, planned, _ = windowed_quick(
        fake_environment, {'dateFrom': '2026-01-01', 'dateTo': '2026-06-30'},
        bookmarked=[dated_work('above', bookmarked='2026-09-01'),
                    dated_work('b-in', bookmarked='2026-03-01', updated='2019-01-01')],
        updated=[dated_work('also-above', updated='2026-08-01'),
                 dated_work('u-in', bookmarked='2020-01-01', updated='2026-02-01')])

    assert [x['id'] for x in planned.call_args.args[3]] == ['b-in', 'u-in']


def test_a_date_range_with_no_older_end_reads_once_and_picks_by_either_date(fake_environment):
    # nothing to stop at, so the first walk reads every bookmark - the updated-date half of
    # the range is then picked out of that same walk rather than walking the listing again
    walks, planned, _ = windowed_quick(
        fake_environment, {'dateTo': '2026-06-30'},
        bookmarked=[dated_work('new-bookmark', bookmarked='2026-09-01', updated='2026-09-01'),
                    dated_work('by-bookmark', bookmarked='2026-03-01', updated='2026-09-01'),
                    dated_work('by-update', bookmarked='2026-09-01', updated='2026-03-01')],
        updated=[])

    assert len(walks) == 1
    assert sorted(x['id'] for x in planned.call_args.args[3]) == ['by-bookmark', 'by-update']


# endregion


# region a run writes down what it did

def test_a_run_records_itself_as_it_starts_and_when_it_ends(fake_environment, tmp_path):
    fake_environment['fileops'].runsfolder = str(tmp_path / 'runs')
    job = server.Job(server.ACTION_SYNC, ['JSON', 'HTML'], 'Someone')

    with patch.object(server, 'FileOps', return_value=fake_environment['fileops']), \
         patch.object(server, 'Repository'), \
         patch.object(server, 'run_sync'):
        server.run_job(job, 'a-password')

    saved = list((tmp_path / 'runs').iterdir())
    assert len(saved) == 1
    record = json.loads(saved[0].read_text(encoding='utf-8'))
    assert record['status'] == server.runs.STATUS_SUCCESS
    assert record['action'] == server.ACTION_SYNC
    assert record['actionName'] == strings.ACTION_NAME_SYNC
    assert record['filetypes'] == ['JSON', 'HTML']


def test_a_run_records_the_settings_it_worked_from(fake_environment, tmp_path):
    # the panel in the modal shows these while the run works, and is gone afterwards. the
    # history file is where they survive
    fake_environment['fileops'].runsfolder = str(tmp_path / 'runs')
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone')
    ini = {'extraWaitTime': 15, 'file': 'C:\\app\\config\\settings.ini', 'maxRetries': 0}

    with patch.object(server, 'FileOps', return_value=fake_environment['fileops']), \
         patch.object(server, 'Repository'), \
         patch.object(server, 'read_settings', return_value=ini), \
         patch.object(server, 'run_sync'):
        server.run_job(job, 'a-password')

    saved = json.loads(list((tmp_path / 'runs').iterdir())[0].read_text(encoding='utf-8'))
    assert saved['settings'] == ini


def test_a_run_record_reads_its_issues_off_the_runs_downloader_at_every_save(fake_environment,
                                                                           tmp_path):
    # so a run killed partway keeps the failures it had met, not an empty list
    fake_environment['fileops'].runsfolder = str(tmp_path / 'runs')
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone')
    ao3 = MagicMock()

    def runner(job, *_):
        job.ao3 = ao3

    with patch.object(server, 'Repository'), patch.object(server, 'run_sync', runner):
        server.run_job(job, 'a-password')

    assert job.record.source() is ao3


def test_settings_that_cannot_be_read_do_not_take_the_run_down(fake_environment):
    # a note about the run is not worth failing a run that downloaded a library
    with patch.object(server, 'read_settings', side_effect=OSError('gone')):
        assert server.settings_for_record(fake_environment['fileops']) == {}


def test_a_run_that_never_reaches_the_login_leaves_no_history_file(fake_environment, tmp_path):
    # a history entry is a record of a run that tried to do something. everything before
    # the login is setup that cannot reach ao3, and a file written for one of those would
    # sit in the history for ever describing a run that never happened
    fake_environment['fileops'].runsfolder = str(tmp_path / 'runs')
    (tmp_path / 'runs').mkdir()
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone')

    with patch.object(server, 'FileOps', return_value=fake_environment['fileops']), \
         patch.object(server, 'Repository', side_effect=OSError('no helper')):
        server.run_job(job, 'a-password')

    assert list((tmp_path / 'runs').iterdir()) == []


def test_a_login_that_is_refused_is_still_written_down(fake_environment, tmp_path):
    # it got as far as asking ao3, so it happened - and a run that failed at the login is
    # exactly the kind the history is worth having
    fake_environment['fileops'].runsfolder = str(tmp_path / 'runs')
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone')
    repo = MagicMock()
    repo.__enter__ = lambda self: self
    repo.login.side_effect = Exception('bad password')

    with patch.object(server, 'FileOps', return_value=fake_environment['fileops']), \
         patch.object(server, 'Repository', return_value=repo):
        server.run_job(job, 'a-password')

    saved = list((tmp_path / 'runs').iterdir())
    assert len(saved) == 1
    assert json.loads(saved[0].read_text(encoding='utf-8'))['status'] == server.runs.STATUS_FAILED


def test_a_stopped_run_is_recorded_as_stopped_not_failed(fake_environment, tmp_path):
    # the user asked for it, and everything written stays written
    fake_environment['fileops'].runsfolder = str(tmp_path / 'runs')
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone')

    with patch.object(server, 'FileOps', return_value=fake_environment['fileops']), \
         patch.object(server, 'Repository'), \
         patch.object(server, 'run_sync', side_effect=lambda *a: job.cancel.set()):
        server.run_job(job, 'a-password')

    record = json.loads(next((tmp_path / 'runs').iterdir()).read_text(encoding='utf-8'))
    assert record['status'] == server.runs.STATUS_STOPPED


def test_a_failed_run_keeps_the_reason(fake_environment, tmp_path):
    fake_environment['fileops'].runsfolder = str(tmp_path / 'runs')
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone')

    with patch.object(server, 'FileOps', return_value=fake_environment['fileops']), \
         patch.object(server, 'Repository'), \
         patch.object(server, 'run_sync', side_effect=Exception('it broke')):
        server.run_job(job, 'a-password')

    record = json.loads(next((tmp_path / 'runs').iterdir()).read_text(encoding='utf-8'))
    assert record['status'] == server.runs.STATUS_FAILED
    assert record['error'] == 'it broke'


def test_a_run_that_could_not_write_its_record_still_finishes(fake_environment):
    # a history file is a convenience; a successful download must not be reported as failed
    # because a note about it could not be saved
    fake_environment['fileops'].runsfolder = '\0not a folder'
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone')

    with patch.object(server, 'FileOps', return_value=fake_environment['fileops']), \
         patch.object(server, 'Repository'), \
         patch.object(server, 'run_sync'):
        server.run_job(job, 'a-password')

    assert [e for e in job.history if e['type'] == progress.FINISHED]
    assert not [e for e in job.history if e['type'] == progress.FAILED]


def test_every_action_has_a_name_for_the_history():
    for action in server.ACTIONS:
        assert server.action_name(action) != action, action

# endregion


# region the checklist a run shows

def plan_ids(action, filetypes=('JSON', 'HTML'), options=None):
    job = server.Job(action, list(filetypes), 'Someone', server.resolve_options(options))
    return [step for step, _ in server.step_plan(job)]


def test_every_run_starts_by_logging_in_and_ends_by_reporting():
    for action in server.ACTIONS:
        ids = plan_ids(action)
        assert ids[0] == 'login', action
        assert ids[-1] == 'report', action


def test_the_combined_run_lists_its_three_passes_in_order():
    assert plan_ids(server.ACTION_SYNC) == [
        'login', 'index', 'series', 'check', 'download', 'update', 'gaps', 'fichub', 'cleanup', 'report']


def test_the_new_bookmarks_run_lists_only_the_pass_it_actually_does():
    # it is the combined run's first pass on its own, and `run_new` runs no gap pass - a
    # step on the checklist that nothing ever marks reads as one that silently failed
    assert plan_ids(server.ACTION_NEW) == [
        'login', 'index', 'series', 'check', 'download', 'fichub', 'cleanup', 'report']


def test_the_runs_that_only_fetch_new_bookmarks_say_so_on_the_download_step():
    # 'the works' on a run that covers what was added since last time reads as the library
    for action in (server.ACTION_NEW, server.ACTION_SYNC):
        job = server.Job(action, ['JSON', 'HTML'], 'Someone', server.resolve_options({}))
        assert dict(server.step_plan(job))['download'] == strings.STEP_DOWNLOAD_NEW, action

    scan = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone',
                      server.resolve_options({}))
    assert dict(server.step_plan(scan))['download'] == strings.STEP_DOWNLOAD


def test_a_scan_says_its_download_step_may_be_an_update():
    # it indexed first, so by the time the step runs it knows which copies ao3 has moved
    # past - those are replaced rather than skipped
    for action in (server.ACTION_BOOKMARKS, server.ACTION_QUICK, server.ACTION_CUSTOM):
        job = server.Job(action, ['JSON', 'HTML'], 'Someone', server.resolve_options({}))
        assert dict(server.step_plan(job))['download'] == strings.STEP_DOWNLOAD, action


def test_the_single_fic_run_promises_a_download_rather_than_a_maybe():
    # it always replaces what you have, so nothing about it is conditional
    job = server.Job(server.ACTION_WORK, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({}))

    assert dict(server.step_plan(job))['download'] == strings.STEP_DOWNLOAD_ONE


def test_only_the_combined_run_has_a_gap_pass():
    # it is the one workflow whose earlier passes deliberately leave works untouched - the
    # finished fics missing a format nobody asked for last time. every other run covers what
    # it covers in one go, so a second sweep would only re-attempt what just failed
    assert 'gaps' in plan_ids(server.ACTION_SYNC)
    for action in server.ACTIONS:
        if action == server.ACTION_SYNC: continue
        assert 'gaps' not in plan_ids(action), action
    assert 'gaps' not in plan_ids(server.ACTION_CUSTOM, options={'overwrite': True})
    assert 'gaps' not in plan_ids(server.ACTION_CUSTOM, options={'dates': True})


def test_an_update_run_reads_before_it_checks_before_it_updates():
    assert plan_ids(server.ACTION_UPDATE) == [
        'login', 'read', 'check', 'update', 'fichub', 'cleanup', 'report']


def test_a_metadata_only_run_lists_no_download_steps():
    # a checklist that lists work the run will not do is worse than none
    ids = plan_ids(server.ACTION_BOOKMARKS, filetypes=['JSON'])

    assert 'download' not in ids
    assert 'gaps' not in ids
    assert 'index' in ids


def test_a_custom_run_says_whether_it_is_indexing_or_reading_what_it_has():
    indexing = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                          server.resolve_options({}))
    reading = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                         server.resolve_options({'reindex': False}))

    assert dict(server.step_plan(indexing))['index'] == strings.STEP_INDEX_ALL
    assert dict(server.step_plan(reading))['index'] == strings.STEP_USE_INDEX


def test_only_a_custom_run_asked_for_images_lists_that_step():
    assert 'images' in plan_ids(server.ACTION_CUSTOM, options={'images': True})
    assert 'images' not in plan_ids(server.ACTION_CUSTOM)
    # a full scan does not offer images at all, so it never lists the step
    assert 'images' not in plan_ids(server.ACTION_BOOKMARKS, options={'images': True})


def test_the_checklist_goes_out_before_anything_happens():
    events: list[dict] = []
    server.Steps(events.append, [('login', 'Log in'), ('index', 'Index')])

    assert events[0]['type'] == progress.STEPS
    assert [x['id'] for x in events[0]['steps']] == ['login', 'index']


def test_each_change_of_step_is_its_own_event():
    events: list[dict] = []
    steps = server.Steps(events.append, [('index', 'Index')])

    steps.start('index')
    steps.done('index')

    changes = [(e['id'], e['status']) for e in events if e['type'] == progress.STEP]
    assert changes == [('index', progress.STEP_RUNNING), ('index', progress.STEP_DONE)]


def test_a_step_with_nothing_to_do_is_skipped_not_failed():
    # a run with no unfinished fics has not gone wrong
    events: list[dict] = []
    steps = server.Steps(events.append, [('update', 'Update')])

    steps.skip('update')

    assert events[-1]['status'] == progress.STEP_SKIPPED


def test_a_failure_blames_only_the_step_that_was_running():
    # the ones after it never started, and saying they failed would blame them for
    # something that happened before they were reached
    events: list[dict] = []
    steps = server.Steps(events.append, [('index', 'Index'), ('download', 'Download')])
    steps.start('index')

    steps.fail_current()

    failed = [e for e in events if e.get('status') == progress.STEP_FAILED]
    assert [e['id'] for e in failed] == ['index']


def test_a_failure_between_steps_blames_nothing():
    events: list[dict] = []
    steps = server.Steps(events.append, [('index', 'Index')])
    steps.start('index')
    steps.done('index')

    steps.fail_current()

    assert not [e for e in events if e.get('status') == progress.STEP_FAILED]


def test_a_run_nobody_is_watching_can_still_mark_its_steps():
    # every run function marks steps unconditionally; a job with no reporter must not care
    steps = server.Steps(None, [])
    steps.start('index')
    steps.done('index')
    steps.fail_current()


def test_a_fresh_job_already_has_somewhere_to_mark_steps():
    server.Job(server.ACTION_SYNC, ['JSON'], 'Someone').steps.start('index')

# endregion


# region a custom run over a window of time

def window(records, start='', end=''):
    return [x['id'] for x in server.works_updated_between(records, start, end)]


def test_a_window_takes_the_works_updated_inside_it():
    records = [dated('1', '01 Jan 2026'), dated('2', '15 Mar 2026'), dated('3', '01 Dec 2026')]

    assert window(records, '2026-02-01', '2026-06-30') == ['2']


def test_both_ends_of_a_window_are_inclusive():
    # a window of a single day is a real thing to ask for, and would otherwise take nothing
    records = [dated('1', '01 Feb 2026'), dated('2', '30 Jun 2026')]

    assert window(records, '2026-02-01', '2026-06-30') == ['2', '1']
    assert window([dated('1', '01 Feb 2026')], '2026-02-01', '2026-02-01') == ['1']


def test_one_end_of_a_window_means_no_limit_at_the_other():
    records = [dated('1', '01 Jan 2026'), dated('2', '01 Dec 2026')]

    assert window(records, start='2026-06-01') == ['2']
    assert window(records, end='2026-06-01') == ['1']


def test_a_work_with_no_readable_date_is_left_out_of_a_window():
    # it cannot be placed, and including it would make the window a lie
    records = [dated('1', ''), dated('2', '01 Mar 2026')]

    assert window(records, '2026-01-01', '2026-12-31') == ['2']


def test_a_window_comes_back_newest_first():
    records = [dated('1', '01 Jan 2026'), dated('2', '01 Jun 2026'), dated('3', '01 Mar 2026')]

    assert window(records, '2026-01-01', '2026-12-31') == ['2', '3', '1']


def run_window(fake_environment, options, index=None):
    """Drive a custom run over a window of time, and hand back the Ao3 it used."""

    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options(dict(options, dates=True)))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'read_index',
                      return_value=index if index is not None else []), \
         patch.object(server, 'refresh_and_download') as pass_:
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    return ao3, pass_


def test_a_date_window_indexes_down_to_its_older_end_first(fake_environment):
    # the window is judged on what the index records, so the index is brought up to date
    # before anything is chosen out of it
    ao3, pass_ = run_window(fake_environment, {'dateFrom': '2026-01-01'},
                            [dated('1', '01 Jun 2026')])

    link = ao3.get_metadata.call_args.args[0]
    assert strings.AO3_SORT_BY_UPDATED in link
    assert ao3.get_metadata.call_args.kwargs['stop_before'] == '2026-01-01'
    assert [x['id'] for x in pass_.call_args.args[3]] == ['1']


def test_the_newer_end_of_a_window_does_not_stop_the_walk(fake_environment):
    # the listing runs newest first, so the newer end is passed on the way down. only the
    # older end can stop the walk - stopping at the newer one would never reach the window
    ao3, _ = run_window(fake_environment,
                        {'dateFrom': '2026-01-01', 'dateTo': '2026-06-30'})

    assert ao3.get_metadata.call_args.kwargs['stop_before'] == '2026-01-01'


def test_a_window_with_no_older_end_reads_the_whole_listing(fake_environment):
    # there is nothing to stop at, and inventing a floor would leave works unseen
    ao3, _ = run_window(fake_environment, {'dateTo': '2026-06-30'})

    assert ao3.get_metadata.call_args.kwargs['stop_before'] == ''


def test_a_window_told_to_skip_indexing_walks_no_listing_at_all(fake_environment):
    # then it chooses from the index as it stands and re-reads each one; no scan to do
    ao3, pass_ = run_window(fake_environment,
                            {'dateFrom': '2026-01-01', 'reindex': False},
                            [dated('1', '01 Jun 2026')])

    ao3.get_metadata.assert_not_called()
    assert [x['id'] for x in pass_.call_args.args[3]] == ['1']


def test_a_metadata_free_window_walks_no_listing_either(fake_environment):
    # json is the index; a run that will not write one has nothing to index
    job = server.Job(server.ACTION_CUSTOM, ['HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'dateFrom': '2026-01-01'}))
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'read_index', return_value=[]), \
         patch.object(server, 'refresh_and_download'):
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.get_metadata.assert_not_called()


def test_a_page_limit_left_over_does_not_cut_a_windows_walk_short(fake_environment):
    # the page inputs are hidden once a window is chosen, but the run still carries them
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'dateFrom': '2026-01-01',
                                             'pages': 3, 'start': 5}))
    with patch.object(server, 'Ao3') as made, \
         patch.object(server.shared, 'read_index', return_value=[]):
        made.return_value.get_metadata.return_value = []
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert made.call_args.args[3] is None
    assert made.call_args.kwargs['start'] == 1


def test_a_date_window_with_nothing_in_it_is_an_answer_not_a_failure(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'dateFrom': '2026-01-01'}))
    events: list[dict] = []
    job.steps = server.Steps(events.append, server.step_plan(job))

    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server.shared, 'read_index', return_value=[]), \
         patch.object(server, 'refresh_and_download') as pass_:
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    pass_.assert_not_called()
    marks = [(e['id'], e['status']) for e in events if e['type'] == progress.STEP]
    assert ('update', progress.STEP_SKIPPED) in marks


def test_a_custom_run_given_pages_still_scans(fake_environment):
    # the two are alternatives: asking for pages must not quietly become a date window
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'pages': 3}))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'download_planned'):
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.get_metadata.assert_called_once()


# region a custom run's slice or range, read by date bookmarked or by date updated

def test_each_custom_shape_keeps_its_own_order_when_none_is_asked():
    # an older page, or a retry of an older run, sends no order: nothing changes for them
    pages = server.Job(server.ACTION_CUSTOM, ['JSON'], 'Someone', server.resolve_options({'pages': 3}))
    dates = server.Job(server.ACTION_CUSTOM, ['JSON'], 'Someone', server.resolve_options({'dates': True}))

    assert server.listing_order(pages) == 'bookmarked'
    assert server.listing_order(dates) == 'updated'


def test_an_order_that_is_not_one_is_not_kept():
    assert server.resolve_options({'order': 'kudos'})['order'] == ''


def walked_pages(fake_environment, options):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options(options))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []
    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'download_planned'):
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)
    return ao3.get_metadata.call_args.args[0]


def test_a_slice_of_pages_is_read_by_date_bookmarked_unless_asked_otherwise(fake_environment):
    assert strings.AO3_SORT_BY_BOOKMARKED in walked_pages(fake_environment, {'pages': 3})
    assert strings.AO3_SORT_BY_BOOKMARKED in walked_pages(fake_environment,
                                                          {'pages': 3, 'order': 'bookmarked'})


def test_a_slice_of_pages_can_be_read_by_date_updated(fake_environment):
    link = walked_pages(fake_environment, {'pages': 3, 'order': 'updated'})

    assert strings.AO3_SORT_BY_UPDATED in link
    assert strings.AO3_SORT_BY_BOOKMARKED not in link


def test_a_range_of_dates_bookmarked_walks_by_date_bookmarked_down_to_its_older_end(fake_environment):
    ao3, _ = run_window(fake_environment, {'dateFrom': '2026-01-01', 'order': 'bookmarked'})

    call = ao3.get_metadata.call_args
    assert strings.AO3_SORT_BY_BOOKMARKED in call.args[0]
    assert call.kwargs['stop_before'] == '2026-01-01'
    assert call.kwargs['stop_on'] == 'bookmarked'


def test_a_range_of_dates_bookmarked_picks_works_by_the_day_they_were_bookmarked(fake_environment):
    index = [
        dict(dated('in', '01 Jan 2020'), date_bookmarked='10 Mar 2026'),
        dict(dated('updated in range only', '10 Mar 2026'), date_bookmarked='01 Jan 2020'),
        dated('never bookmarked', '10 Mar 2026'),
    ]

    _, pass_ = run_window(fake_environment,
                          {'dateFrom': '2026-03-01', 'dateTo': '2026-03-31', 'order': 'bookmarked'},
                          index)

    assert [x['id'] for x in pass_.call_args.args[3]] == ['in']


def test_a_range_of_dates_bookmarked_says_so_on_its_checklist():
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'order': 'bookmarked'}))

    plan = dict(server.step_plan(job))

    assert plan['index'] == strings.STEP_INDEX_BOOKMARKED_WINDOW
    assert plan['read'] == strings.STEP_READ_BOOKMARKED_WINDOW

# endregion


def test_a_date_window_says_so_on_its_checklist():
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'dates': True}))

    ids = [step for step, _ in server.step_plan(job)]

    assert ids == ['login', 'index', 'read', 'series', 'check', 'update', 'fichub', 'cleanup', 'report']
    assert dict(server.step_plan(job))['read'] == strings.STEP_READ_WINDOW
    assert dict(server.step_plan(job))['index'] == strings.STEP_INDEX_WINDOW


def test_a_window_that_skips_indexing_still_lists_the_step_it_turned_off(fake_environment):
    # a step the user actively turned off is worth seeing struck through, where one this
    # workflow simply never had is only noise
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'reindex': False}))
    events: list[dict] = []
    job.steps = server.Steps(events.append, server.step_plan(job))

    assert [step for step, _ in server.step_plan(job)] == [
        'login', 'index', 'read', 'series', 'check', 'update', 'fichub', 'cleanup', 'report']

    ao3 = MagicMock()
    ao3.series_marked = {}
    with patch.object(server.shared, 'read_index', return_value=[]):
        server.run_custom_dates(job, fake_environment['fileops'], ao3, ['HTML'], None)

    ao3.get_metadata.assert_not_called()
    marks = [(e['id'], e['status']) for e in events if e['type'] == progress.STEP]
    assert ('index', progress.STEP_SKIPPED) in marks


def test_a_run_that_writes_no_index_lists_no_indexing_step():
    # nothing was turned off here - json is the index, and this run writes none
    job = server.Job(server.ACTION_CUSTOM, ['HTML'], 'Someone',
                     server.resolve_options({'dates': True, 'reindex': False}))

    assert 'index' not in [step for step, _ in server.step_plan(job)]

# endregion


# region the order works are worked through

def dated(work: str, updated: str) -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'title': work, 'date_updated': updated}


def test_the_most_recently_updated_fic_is_dealt_with_first():
    # a run can be stopped, and where it got to should be the half worth having
    records = [dated('1', '01 Jan 2020'), dated('2', '20 Dec 2026'), dated('3', '05 May 2024')]

    assert [x['id'] for x in server.newest_first(records)] == ['2', '3', '1']


def test_the_two_date_formats_ao3_writes_sort_together():
    # a listing writes '14 Dec 2024' and a work page writes '2024-12-14' for the same day
    records = [dated('1', '2024-12-14'), dated('2', '15 Dec 2024'), dated('3', '13 Dec 2024')]

    assert [x['id'] for x in server.newest_first(records)] == ['2', '1', '3']


def test_a_fic_with_no_usable_date_goes_last():
    # it cannot be placed, and guessing would put it at the front
    records = [dated('1', ''), dated('2', '01 Jan 2020'), {'id': '3', 'link': 'x'}]

    assert [x['id'] for x in server.newest_first(records)][0] == '2'


def test_ordering_keeps_every_record():
    records = [dated(str(n), '') for n in range(5)]

    assert len(server.newest_first(records)) == 5

# endregion


# region what happens to each format

LINK = 'https://archiveofourown.org/works/111'


def verdicts(existing, filetypes, superseded=None, capsys=None, overwrite=False):
    record = {'id': '111', 'link': LINK, 'title': 'A Fic'}
    plan = {'stale': [], 'undated': [], 'superseded': superseded or {},
            'overwrite': overwrite}
    wanted = server.say_what_each_format_needs(record, existing, filetypes, plan)
    said = capsys.readouterr().out if capsys else ''
    return wanted, said


def test_a_format_with_no_copy_is_named_and_fetched(capsys):
    wanted, said = verdicts({}, ['HTML', 'PDF'], capsys=capsys)

    assert wanted == ['HTML', 'PDF']
    assert 'no copy in HTML - downloading now' in said
    assert 'no copy in PDF - downloading now' in said


def test_an_outdated_format_says_which_one_it_is_replacing(capsys):
    existing = {'111': {'HTML': {'path': 'a.html', 'date': '2020-01-01'}}}

    wanted, said = verdicts(existing, ['HTML'], superseded={LINK: {'HTML': 'a.html'}},
                            capsys=capsys)

    assert wanted == ['HTML']
    assert 'outdated version in HTML - replacing now' in said


def test_a_format_replaced_on_request_does_not_claim_to_be_outdated(capsys):
    # most of what an overwrite replaces is perfectly current, and calling it outdated
    # would read as the version check having gone wrong
    existing = {'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}}

    wanted, said = verdicts(existing, ['HTML'], superseded={LINK: {'HTML': 'a.html'}},
                            capsys=capsys, overwrite=True)

    assert wanted == ['HTML']
    assert 'downloading HTML again at your request' in said
    assert 'outdated' not in said


def test_a_current_format_is_named_and_left(capsys):
    existing = {'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}}

    wanted, said = verdicts(existing, ['HTML'], capsys=capsys)

    assert wanted == []
    assert 'already have the current version in HTML' in said


def test_an_undated_format_says_it_cannot_be_judged(capsys):
    existing = {'111': {'HTML': {'path': 'a.html', 'date': None}}}

    wanted, said = verdicts(existing, ['HTML'], capsys=capsys)

    assert wanted == []
    assert 'has no date, so it cannot be judged' in said


def test_only_the_formats_that_need_it_are_fetched(capsys):
    # the point of doing this per format: a fic can be current in one and missing another,
    # and re-fetching the current one spends a request for nothing
    existing = {'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}}

    wanted, said = verdicts(existing, ['HTML', 'PDF'], capsys=capsys)

    assert wanted == ['PDF']
    assert 'already have the current version in HTML' in said
    assert 'no copy in PDF - downloading now' in said


def test_fetching_formats_leaves_the_downloader_as_it_was_found():
    ao3 = MagicMock()
    ao3.filetypes = ['HTML', 'PDF']
    seen = []
    ao3.download_one_indexed.side_effect = lambda *a: seen.append(list(ao3.filetypes))

    server.fetch_formats(ao3, {'id': '111'}, ['PDF'], 50, {}, 1, 1)

    assert seen == [['PDF']]
    assert ao3.filetypes == ['HTML', 'PDF']


def test_the_downloader_is_handed_back_even_when_a_download_raises():
    ao3 = MagicMock()
    ao3.filetypes = ['HTML']
    ao3.download_one_indexed.side_effect = Exception('no')

    with pytest.raises(Exception):
        server.fetch_formats(ao3, {'id': '111'}, ['PDF'], 50, {}, 1, 1)

    assert ao3.filetypes == ['HTML']

# endregion


# region naming what a run could not get

def test_skipped_bookmarks_are_listed_with_a_reason_each():
    # a count leaves no way to tell which bookmark was passed over or to go and look at it
    ao3 = MagicMock()
    ao3.failures = []
    ao3.skipped_works = [
        {'id': '12345', 'link': 'https://ao3/series/12345', 'error': 'a series'},
        {'id': None, 'link': '', 'error': 'the work has been deleted'},
    ]
    events: list[dict] = []

    server.report_failures(ao3, events.append)

    sent = [e for e in events if e['type'] == progress.SKIPPED]
    assert len(sent) == 1
    assert [x['error'] for x in sent[0]['skipped']] == ['a series', 'the work has been deleted']


def test_skipped_bookmarks_are_kept_apart_from_failed_downloads():
    # nothing went wrong with a skipped bookmark, and listing them together would make a
    # real failure look routine
    ao3 = MagicMock()
    ao3.skipped_works = [{'id': '1', 'link': 'a', 'error': 'a series'}]
    ao3.failures = [{'id': '2', 'link': 'b', 'error': 'timed out'}]
    events: list[dict] = []

    server.report_failures(ao3, events.append)

    assert [e['type'] for e in events] == [progress.SKIPPED, progress.FAILURES]


def test_nothing_is_reported_when_a_run_got_everything():
    ao3 = MagicMock()
    ao3.skipped_works = []
    ao3.failures = []
    events: list[dict] = []

    server.report_failures(ao3, events.append)

    assert events == []


@pytest.mark.parametrize('action', [
    server.ACTION_BOOKMARKS, server.ACTION_UPDATE, server.ACTION_COLLECTIONS,
    server.ACTION_COLLECTION, server.ACTION_NEW, server.ACTION_SYNC, server.ACTION_WORK,
    server.ACTION_CUSTOM,
])
def test_every_action_ends_by_saying_what_it_could_not_get(action):
    # every button, not most of them: a gap between what is bookmarked and what is on disk
    # is worth naming whichever run left it
    source = inspect.getsource(server.runners()[action])

    assert 'finish_run' in source, action
    # which cleans up first, so anything it could not remove is in the report
    finishing = inspect.getsource(server.finish_run)
    assert finishing.index('cleanup(') < finishing.index('report_failures(')


def test_a_metadata_only_run_still_says_what_it_skipped(fake_environment):
    # it downloads nothing, so this used to sit inside the download block and never run -
    # but indexing is exactly where skipped bookmarks are found
    job = server.Job(server.ACTION_BOOKMARKS, [strings.AO3_DOWNLOAD_TYPE_METADATA], 'Someone')
    ao3 = MagicMock()
    ao3.failures = []
    ao3.skipped_works = [{'id': None, 'link': '', 'error': 'the work has been deleted'}]
    events: list[dict] = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'],
                             events.append)

    assert [e for e in events if e['type'] == progress.SKIPPED]

# endregion


def test_run_bookmarks_indexes_every_bookmark_before_downloading_any(fake_environment):
    # the whole point of the order: an interrupted run still leaves a complete index
    job = server.Job(server.ACTION_BOOKMARKS,
                     [strings.AO3_DOWNLOAD_TYPE_METADATA, 'EPUB'], 'Someone')
    order = []
    ao3 = MagicMock()
    ao3.series_marked = {}
    ao3.get_metadata.side_effect = lambda *a, **k: order.append('metadata')
    ao3.download.side_effect = lambda *a: order.append('download')

    events = []
    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'],
                             events.append)

    assert order == ['metadata', 'download']
    phases = [e['name'] for e in events if e['type'] == progress.PHASE]
    assert phases == [progress.INDEXING, progress.DOWNLOADING]


def test_run_bookmarks_reports_only_indexing_when_json_is_the_only_type(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, [strings.AO3_DOWNLOAD_TYPE_METADATA], 'Someone')

    events = []
    ao3 = MagicMock()
    ao3.series_marked = {}
    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'],
                             events.append)

    phases = [e['name'] for e in events if e['type'] == progress.PHASE]
    assert phases == [progress.INDEXING]


def test_run_update_says_what_it_is_doing_at_each_step(fake_environment):
    # from the outside, 'reading the index' and 'checking what you have' look the same as a
    # stall, so each one says so before the per-fic work begins
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []
    events: list[dict] = []

    run_update_with(fake_environment, ao3, [INCOMPLETE], report=events.append,
                    plan={'stale': ['https://archiveofourown.org/works/111'],
                          'undated': [], 'superseded': {}})

    phases = [e['name'] for e in events if e['type'] == progress.PHASE]
    assert phases == [progress.SCANNING, progress.CHECKING_FILES, progress.UPDATING]


def test_run_update_says_it_is_reading_a_fic_before_it_goes_and_reads_it(
        fake_environment, capsys):
    # opening the fic page is the slow part, so the line has to come before the request,
    # not after it - otherwise the run looks stalled on the fic it has only just named
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE],
                    existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}})

    said = [x.strip() for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert said.index('reading latest index') == said.index('index updated') - 1
    assert said.index('[1 of 1] A Fic') == said.index('reading latest index') - 1


def test_run_update_names_each_fic_as_it_reaches_it(fake_environment):
    # one work event per fic, so the modal reads as a running account rather than a bar
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []
    events: list[dict] = []
    # the per-fic events go out through the Ao3 the run builds, not the run's own reporter
    ao3.progress = events.append

    run_update_with(fake_environment, ao3, [INCOMPLETE], report=events.append)

    works = [e for e in events if e['type'] == progress.WORK]
    assert [(e['title'], e['done'], e['total']) for e in works] == [('A Fic', 1, 1)]
    assert works[0]['phase'] == progress.UPDATING


def test_run_bookmarks_passes_the_chosen_options_through(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB', 'HTML'], 'Someone',
                     server.resolve_options({'pages': 3, 'series': True, 'images': True}))

    with patch.object(server, 'Ao3') as ao3_class, \
         patch.object(server.shared, 'already_downloaded', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    args = ao3_class.call_args.args
    assert args[3] == 3      # pages
    assert args[4] is True   # series
    assert args[5] is True   # images


def test_run_bookmarks_treats_page_zero_as_every_page(fake_environment):
    # Ao3 wants None for "no limit"; the console asks for 0
    job = server.Job(server.ACTION_BOOKMARKS, ['HTML'], 'Someone',
                     server.resolve_options({'pages': 0}))

    with patch.object(server, 'Ao3') as ao3_class, \
         patch.object(server.shared, 'already_downloaded', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3_class.call_args.args[3] is None


def test_run_bookmarks_asks_for_work_dates_when_requested(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, [strings.AO3_DOWNLOAD_TYPE_METADATA], 'Someone',
                     server.resolve_options({'workdates': True}))
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.get_metadata.call_args.args[1] is True


def test_run_bookmarks_skips_the_download_phase_once_cancelled(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS,
                     [strings.AO3_DOWNLOAD_TYPE_METADATA, 'EPUB'], 'Someone')
    ao3 = MagicMock()
    # metadata finishes, then the user hits stop
    ao3.get_metadata.side_effect = lambda *a, **k: job.cancel.set()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'already_downloaded', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.download.assert_not_called()


def test_run_update_does_not_download_once_cancelled(fake_environment):
    job = server.Job(server.ACTION_UPDATE, ['HTML'], 'Someone')
    job.cancel.set()
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE], job=job)

    ao3.refresh_one.assert_not_called()
    ao3.download_one_indexed.assert_not_called()


def test_run_job_reports_a_cancelled_finish_rather_than_a_failure(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone')

    with patch.object(server, 'run_bookmarks', side_effect=lambda *a: job.cancel.set()):
        server.run_job(job, 'a-password')

    finished = [e for e in job.history if e['type'] == progress.FINISHED]
    assert len(finished) == 1
    assert finished[0]['cancelled'] is True
    assert not [e for e in job.history if e['type'] == progress.FAILED]


def test_run_job_announces_the_chosen_filetypes_and_options(fake_environment):
    # the ui shows these back while the run is in progress
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB', 'HTML'], 'Someone',
                     server.resolve_options({'pages': 2, 'images': True}))

    with patch.object(server, 'run_bookmarks'):
        server.run_job(job, 'a-password')

    started = [e for e in job.history if e['type'] == progress.STARTED][0]
    assert started['filetypes'] == ['EPUB', 'HTML']
    assert started['options']['pages'] == 2
    assert started['options']['images'] is True


def test_run_update_downloads_a_copy_the_version_check_calls_out_of_date(fake_environment):
    # the copy is there in the format asked for, but ao3 now reports a later update than
    # the date the file carries
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(
        fake_environment, ao3, [INCOMPLETE],
        existing={'111': {'HTML': {'path': 'a.html', 'date': '2020-01-01'}}},
        plan={'stale': ['https://archiveofourown.org/works/111'], 'undated': [],
              'superseded': {'https://archiveofourown.org/works/111': {'HTML': 'a.html'}}})

    fetched = ao3.download_one_indexed.call_args.args[0]
    assert fetched['id'] == '111'
    # and the old file is handed over to be replaced only after the new one lands
    assert ao3.superseded == {'https://archiveofourown.org/works/111': {'HTML': 'a.html'}}

# endregion


# region only one helper at a time

def test_a_helper_that_is_actually_listening_is_noticed():
    # on windows SO_REUSEADDR lets a second process bind a port the first is listening on,
    # so binding cannot be relied on to fail. asking by connecting is what catches it.
    live = ThreadingHTTPServer((server.HOST, 0), server.Handler)
    thread = threading.Thread(target=live.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.already_listening(server.HOST, live.server_address[1]) is True
    finally:
        live.shutdown()
        live.server_close()


def test_a_port_with_nothing_on_it_is_free():
    spare = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    spare.bind((server.HOST, 0))
    port = spare.getsockname()[1]
    spare.close()

    assert server.already_listening(server.HOST, port, timeout=0.2) is False


def test_serve_gives_up_rather_than_starting_a_second_helper(capsys):
    with patch.object(server, 'already_listening', return_value=True):
        with pytest.raises(SystemExit):
            server.serve(port=4400)

    said = capsys.readouterr().out
    assert 'already listening' in said
    # the fix is to close the old one, so say so rather than leaving a bare stack trace
    assert 'earlier' in said


def test_serve_starts_when_the_port_is_free(capsys):
    # a port left in TIME_WAIT by a normal shutdown must not stop the next start
    httpd = MagicMock()
    with patch.object(server, 'already_listening', return_value=False), \
         patch.object(server, 'ThreadingHTTPServer', return_value=httpd):
        server.serve(port=4400)

    httpd.serve_forever.assert_called_once()

# endregion


# region telling a stale helper apart from a bad request

def test_an_unknown_action_names_what_this_helper_does_understand():
    sent = {}

    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {'action': 'collections'}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)

    # a helper from before collections existed, asked to index collections
    with patch.object(server, 'ACTIONS', ('bookmarks', 'update')):
        server.Handler.do_POST(handler)

    assert sent['status'] == 400
    error = sent['body']['error']
    assert 'collections' in error
    assert 'bookmarks' in error
    # the usual cause is an old helper, not a malformed request
    assert 'older code' in error

# endregion


# region the end-of-run report

def test_every_run_ends_by_reporting_any_failures():
    # every button, including a single fic by link, gets the step
    for action in server.ACTIONS:
        for dates in (False, True):
            job = MagicMock()
            job.action = action
            job.filetypes = ['JSON', 'HTML']
            job.options = {**server.resolve_options(None), 'dates': dates}
            plan = server.step_plan(job)
            assert plan[-1] == ('report', strings.STEP_REPORT), (action, dates)
    assert strings.STEP_REPORT == 'Report any failures'


def test_old_copies_that_would_not_go_are_reported_with_the_failures(capsys):
    ao3 = MagicMock()
    ao3.skipped_works = []
    ao3.failures = []
    ao3.kept_copies = [{'id': '1', 'link': 'l', 'file': 'f', 'old': 'o', 'error': 'e'}]
    events = []

    server.report_failures(ao3, events.append)

    assert {'type': progress.KEPT_COPIES, 'keptCopies': ao3.kept_copies} in events
    assert strings.AO3_INFO_KEPT_COPIES.format(1) in capsys.readouterr().out

# endregion


# region series marked for walkthrough

def series_step(marked: dict) -> tuple[list, list, MagicMock]:
    """Run the walkthrough step on its own, and hand back its checklist marks and output."""
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone')
    events: list[dict] = []
    job.steps = server.Steps(events.append, server.step_plan(job))
    ao3 = MagicMock()
    ao3.series_marked = marked
    ao3.walk_marked_series.return_value = [{'id': '9', 'link': 'https://archiveofourown.org/works/9'}]
    works = server.index_marked_series(job, ao3, None)
    marks = [(e['id'], e['status']) for e in events if e['type'] == progress.STEP]
    return works, marks, ao3


def test_a_run_with_no_series_marked_skips_the_walkthrough_step(capsys):
    # nothing to walk is not a failure, and is shown struck through rather than ticked
    works, marks, ao3 = series_step({})

    assert works == []
    assert marks == [('series', progress.STEP_SKIPPED)]
    ao3.walk_marked_series.assert_not_called()
    assert strings.AO3_INFO_SERIES_NONE in capsys.readouterr().out


def test_a_run_with_series_marked_walks_them_and_hands_their_works_on(capsys):
    works, marks, ao3 = series_step({'5': {'id': '5', 'title': 'S', 'bookmark': None}})

    ao3.walk_marked_series.assert_called_once()
    assert marks == [('series', progress.STEP_RUNNING), ('series', progress.STEP_DONE)]
    # the works it indexed go on to the download step
    assert [w['id'] for w in works] == ['9']
    assert strings.AO3_INFO_SERIES_STEP.format(1) in capsys.readouterr().out


def test_every_run_that_indexes_lists_the_walkthrough_step_after_indexing():
    for action in (server.ACTION_BOOKMARKS, server.ACTION_QUICK, server.ACTION_CUSTOM,
                   server.ACTION_WORK, server.ACTION_NEW, server.ACTION_SYNC):
        ids = plan_ids(action)
        assert 'series' in ids, action
        assert ids.index('series') < ids.index('check'), action
    # the update run indexes nothing, so it has nothing to mark
    assert 'series' not in plan_ids(server.ACTION_UPDATE)

# endregion


# region several fics, and skipping the login

def test_a_paste_of_links_and_numbers_is_read_whatever_separates_them():
    links, unknown = server.work_links(
        '123\nhttps://archiveofourown.org/works/456/chapters/9, 789; 123  '
        'https://archiveofourown.org/series/5\t1011')

    assert links == ['https://archiveofourown.org/works/123',
                     'https://archiveofourown.org/works/456',
                     'https://archiveofourown.org/works/789',
                     'https://archiveofourown.org/works/1011']
    assert unknown == ['https://archiveofourown.org/series/5']


def start_request(action, url='', username='Someone', password='a-password', **options):
    sent = {}
    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {'action': action, 'username': username,
                                      'password': password, 'filetypes': ['JSON', 'HTML'],
                                      'options': options, 'url': url}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)
    with patch.object(server.threading, 'Thread') as thread, \
         patch.dict(server.Handler.jobs, clear=True):
        server.Handler.do_POST(handler)
        jobs = list(server.Handler.jobs.values())
    return sent, jobs, thread


def test_several_fics_start_with_one_link_to_a_line():
    sent, [job], _ = start_request(server.ACTION_WORKS, '1, 2 2;3')

    assert sent['status'] == 202
    assert job.url == '\n'.join(f'https://archiveofourown.org/works/{n}' for n in (1, 2, 3))


def test_several_fics_name_what_in_the_paste_is_not_a_work():
    sent, jobs, _ = start_request(server.ACTION_WORKS, '1 not-a-fic 2')

    assert sent['status'] == 400
    assert 'not-a-fic' in sent['body']['error']
    assert jobs == []


def test_a_paste_with_nothing_in_it_is_refused():
    sent, _, _ = start_request(server.ACTION_WORKS, ' ,; ')
    assert sent['status'] == 400
    assert sent['body']['error'] == strings.ERROR_NO_WORK_LINKS


@pytest.mark.parametrize('action', [server.ACTION_WORK, server.ACTION_WORKS])
def test_a_fic_run_told_to_skip_the_login_needs_no_credentials_and_keeps_none(action):
    sent, [job], thread = start_request(action, '123', username='Someone', password='',
                                        skipLogin=True)

    assert sent['status'] == 202
    assert sent['body']['options']['skipLogin'] is True
    assert job.username == ''
    # the password handed to the run is empty, whatever the request carried
    assert thread.call_args.kwargs['args'][1] == ''


@pytest.mark.parametrize('action', server.USERNAME_ACTIONS)
def test_a_run_of_your_own_listing_told_to_skip_the_login_still_needs_a_username(action):
    sent, jobs, _ = start_request(action, username='', password='', skipLogin=True)
    assert sent['status'] == 400
    assert 'username' in sent['body']['error']
    assert jobs == []


@pytest.mark.parametrize('action', server.USERNAME_ACTIONS)
def test_a_run_of_your_own_listing_may_skip_the_login_and_keeps_only_the_username(action):
    sent, [job], thread = start_request(action, username='Someone', password='secret',
                                        skipLogin=True)
    assert sent['status'] == 202
    assert sent['body']['options']['skipLogin'] is True
    assert job.username == 'Someone'
    assert thread.call_args.kwargs['args'][1] == ''


def test_every_run_may_skip_the_login():
    for action in server.ACTIONS:
        link = 'https://archiveofourown.org/collections/Some_Collection' \
            if action == server.ACTION_COLLECTION else '123'
        sent, jobs, _ = start_request(action, link, username='Someone', password='',
                                      skipLogin=True)
        assert sent['status'] == 202, (action, sent['body'])
        assert jobs[0].options['skipLogin'] is True
        if action not in server.USERNAME_ACTIONS: assert jobs[0].username == ''


def test_a_run_told_to_skip_the_login_never_logs_in(fake_environment):
    job = server.Job(server.ACTION_WORK, ['JSON'], '', server.resolve_options({'skipLogin': True}),
                     url='https://archiveofourown.org/works/1')

    with patch.object(server, 'run_work') as run:
        server.run_job(job, '')

    run.assert_called_once()
    fake_environment['repo'].login.assert_not_called()
    assert fake_environment['repo'].logged_in is False
    login = [e for e in job.history if e['type'] == progress.STEP and e['id'] == 'login']
    assert [e['status'] for e in login] == [progress.STEP_SKIPPED]
    assert progress.AUTHENTICATED not in _types(job)
    assert _types(job)[-1] == progress.FINISHED


def test_a_failure_with_no_login_never_asks_whether_the_login_lapsed():
    from source_code.ao3 import Ao3
    repo = MagicMock()
    repo.logged_in = False
    ao3 = Ao3(repo, MagicMock(), ['HTML'], None, False, False)

    ao3.check_session()

    repo.still_logged_in.assert_not_called()


def test_several_fics_are_each_indexed_then_downloaded_and_one_ao3_will_not_show_is_passed_over(
        fake_environment):
    links = [f'https://archiveofourown.org/works/{n}' for n in (1, 2, 3)]
    job = server.Job(server.ACTION_WORKS, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({}), url='\n'.join(links))
    ao3 = MagicMock()
    ao3.failures = []

    def index(link, existing=None, find_existing=None):
        if link.endswith('/2'): raise exceptions.DeletedException('deleted')
        return {'id': link.rsplit('/', 1)[1], 'link': link}

    ao3.index_one_work.side_effect = index
    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'read_index', return_value=[]), \
         patch.object(server, 'index_marked_series', return_value=[]), \
         patch.object(server, 'download_planned') as downloaded, \
         patch.object(server, 'finish_run') as finished:
        server.run_works(job, fake_environment['fileops'], fake_environment['repo'], MagicMock())

    assert ao3.index_one_work.call_count == 3
    ao3.record_failure.assert_called_once()
    assert ao3.record_failure.call_args.args[0] == links[1]
    records = downloaded.call_args.args[3]
    assert [r['id'] for r in records] == ['1', '3']
    assert downloaded.call_args.kwargs['overwrite'] == [links[0], links[2]]
    # FicHub is asked about the failures once, at the end, not after each fic
    finished.assert_called_once()


def test_several_fics_have_their_own_checklist_wording():
    job = server.Job(server.ACTION_WORKS, ['JSON', 'HTML'], 'Someone', server.resolve_options({}))
    plan = dict(server.step_plan(job))
    assert plan['index'] == strings.STEP_INDEX_MANY
    assert plan['download'] == strings.STEP_DOWNLOAD_MANY

# endregion


# region force stop from the History tab

def a_stuck_run(tmp_path):
    from source_code import runs
    fileops = on_disk(MagicMock(), str(tmp_path / 'library'))
    # a real folder: left a mock, the record would be written under the working directory
    fileops.runsfolder = str(tmp_path / 'library' / 'runs')
    os.makedirs(fileops.runsfolder, exist_ok=True)
    job = server.Job(server.ACTION_WORK, ['JSON'], 'Someone', server.resolve_options({}),
                     url='https://archiveofourown.org/works/1')
    job.record = runs.RunRecord(fileops, job.id, job.action, 'Download/update a specific fic',
                                job.filetypes, job.options, username='Someone',
                                printed=['looking up work 1'])
    job.record.save()
    job.ao3 = MagicMock(failures=[{'id': '1', 'link': 'x', 'error': 'gone'}], skipped_works=[],
                        reindexed=set(), downloaded=set(), updated=set(), rescued=[],
                        kept_copies=[])
    return job, fileops


def test_a_force_stop_ends_a_stuck_run_at_once_with_its_log_and_issues(tmp_path):
    job, fileops = a_stuck_run(tmp_path)

    written = server.force_stop(job)

    assert job.done.is_set() and job.cancel.is_set()
    assert written['file'] == os.path.basename(job.record.path)
    data = written['data']
    assert data['status'] == 'stopped'
    assert data['error'] == strings.ERROR_FORCE_STOPPED
    assert data['finished']
    assert data['log'][-1].endswith('] ' + strings.AO3_INFO_FORCE_STOPPED)
    assert data['failures'] == [{'id': '1', 'link': 'x', 'error': 'gone'}]
    assert any(e['type'] == progress.FINISHED and e.get('forced') for e in job.history)


def test_a_thread_waking_after_a_force_stop_cannot_write_over_the_record(tmp_path):
    job, fileops = a_stuck_run(tmp_path)
    server.force_stop(job)
    on_disk_before = open(job.record.path, encoding='utf-8').read()

    # the stuck thread wakes and finishes the way a run ends
    server.close_record(job, 'success')

    assert open(job.record.path, encoding='utf-8').read() == on_disk_before


def test_a_force_stopped_run_frees_the_helper_for_the_next_one(tmp_path):
    job, _ = a_stuck_run(tmp_path)
    server.Handler.jobs[job.id] = job
    server.force_stop(job)

    sent, jobs, _ = start_request(server.ACTION_WORK, '2')
    assert sent['status'] == 202


def test_force_stopping_a_run_already_over_writes_nothing(tmp_path):
    job, _ = a_stuck_run(tmp_path)
    job.done.set()
    assert server.force_stop(job) is None


def test_the_force_stop_endpoint_answers_with_the_record_or_404(tmp_path):
    job, _ = a_stuck_run(tmp_path)
    sent = {}
    handler = MagicMock()
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)
    with patch.dict(server.Handler.jobs, {job.id: job}):
        server.Handler.force_stop_job(handler, job.id)
    assert sent['status'] == 200 and sent['body']['record']['data']['status'] == 'stopped'

    server.Handler.force_stop_job(handler, 'nope')
    assert sent['status'] == 404


def test_a_running_log_is_read_whole_from_the_helper_not_from_its_last_save(tmp_path):
    # the file is saved every two minutes; the helper's copy has every line said since
    job, _ = a_stuck_run(tmp_path)
    job.record.line('looking up work 2')
    sent = {}
    handler = MagicMock()
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)

    with patch.dict(server.Handler.jobs, {job.id: job}):
        server.Handler.send_live_record(handler, job.id)

    assert sent['status'] == 200
    log = sent['body']['record']['log']
    assert log[-1].endswith('] looking up work 2')
    on_disk = json.load(open(job.record.path, encoding='utf-8'))
    assert len(on_disk['log']) < len(log)
    # a copy: the run writing more does not change what was sent
    job.record.line('later')
    assert len(sent['body']['record']['log']) == len(log)

    server.Handler.send_live_record(handler, 'nope')
    assert sent['status'] == 404

# endregion


# region an overwriting run and a copy newer than what it would write

def a_newer_copy_plan(copies: dict, date='2026-04-27'):
    from source_code.actions import shared
    link = 'https://archiveofourown.org/works/1'
    records = [{'id': '1', 'link': link, 'date_updated': date}]
    existing = {'1': {fmt: {'path': f'works/1 A {d}.{fmt.lower()}', 'date': d}
                      for fmt, d in copies.items()}}
    plan = shared.plan_downloads(records, existing, list(copies), overwrite=True)
    return link, records, existing, plan


def answering_job(answer=None):
    job = server.Job(server.ACTION_WORK, ['EPUB'], 'Someone')
    asked = []

    def ask(question, default):
        asked.append((question, default))
        return dict(default) if answer is None else {'choice': answer}
    job.ask = ask
    return job, asked


def test_an_overwriting_run_asks_before_replacing_a_newer_copy_and_keeps_it_by_default():
    link, records, existing, plan = a_newer_copy_plan({'EPUB': '2026-05-10', 'HTML': '2026-01-01'})
    job, asked = answering_job()

    server.keep_newer_copies(job, records, existing, plan, ['EPUB', 'HTML'])

    question, default = asked[0]
    assert question['name'] == server.OVERWRITE_OLDER_QUESTION
    assert question['formats'] == ['EPUB'] and question['ids'] == ['1']
    assert question['date'] == '2026-04-27' and question['newer'] == '2026-05-10'
    assert default == {'choice': 'no'}
    # the newer epub is kept; the older html is still overwritten as asked
    assert plan['keep'] == {link: {'EPUB'}}
    assert list(plan['superseded'][link]) == ['HTML']
    assert link in plan['stale']


def test_the_overwrite_question_names_the_nominated_file_and_the_other_copies_it_keeps():
    link, records, existing, plan = a_newer_copy_plan({'EPUB': '2026-05-10'})
    existing['1']['EPUB']['older'] = [{'path': 'works/1 A copy.epub', 'date': None}]
    job, asked = answering_job()

    server.keep_newer_copies(job, records, existing, plan, ['EPUB'])

    question, _ = asked[0]
    assert question['fileNames'] == {'EPUB': '1 A 2026-05-10.epub'}
    assert question['otherFiles'] == {'EPUB': ['1 A copy.epub']}


def test_a_work_whose_every_copy_is_kept_is_not_downloaded_at_all():
    link, records, existing, plan = a_newer_copy_plan({'EPUB': '2026-05-10'})
    job, _ = answering_job('no')

    server.keep_newer_copies(job, records, existing, plan, ['EPUB'])

    assert link not in plan['superseded'] and link not in plan['stale']


def test_saying_yes_replaces_the_newer_copy_with_the_older_version():
    link, records, existing, plan = a_newer_copy_plan({'EPUB': '2026-05-10'})
    job, _ = answering_job('yes')

    server.keep_newer_copies(job, records, existing, plan, ['EPUB'])

    assert plan['keep'] == {} and list(plan['superseded'][link]) == ['EPUB']


@pytest.mark.parametrize('copy', ['2026-04-27', '2026-01-01'])
def test_a_copy_no_newer_than_the_version_is_overwritten_without_asking(copy):
    link, records, existing, plan = a_newer_copy_plan({'EPUB': copy})
    job, asked = answering_job()

    server.keep_newer_copies(job, records, existing, plan, ['EPUB'])

    assert asked == [] and list(plan['superseded'][link]) == ['EPUB']


def test_the_downloader_leaves_alone_a_format_it_was_told_to_keep(capsys):
    ao3 = server.Ao3(MagicMock(), MagicMock(), ['EPUB', 'HTML'], None, False, False)
    ao3.repo.download_file.return_value = b'x'
    link = 'https://archiveofourown.org/works/1'
    ao3.keep_formats = {link: {'EPUB'}}
    saved = []
    with patch.object(server.Ao3, 'save_download',
                      lambda self, link, filetype, name, content: saved.append(filetype)):
        ao3.download_one_indexed({'id': '1', 'link': link, 'title': 'A', 'authors': ['B'],
                                  'date_updated': '2026-04-27'}, 50, {}, 1, 1)

    assert saved == ['HTML']
    assert 'EPUB: keeping your newer copy' in capsys.readouterr().out

# endregion

