"""FicHub: asked at the end of a run for the works ao3 would not give us.

The fixture is FicHub's real answer for 75354806, Wolfbird - a work ao3 no longer serves -
as it came back from https://fichub.net/api/v0/epub?q=https://archiveofourown.org/works/75354806.
"""

import io
import json
import os
import zipfile
from unittest.mock import MagicMock

import pytest

from source_code import exceptions, fichub, indexing, server, strings
from source_code.ao3 import Ao3


FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'fichub', 'wolfbird.json')
LINK = 'https://archiveofourown.org/works/75354806'


def wolfbird() -> dict:
    with open(FIXTURE, encoding='utf-8') as f:
        return json.load(f)


def answering(status: int = 200, body=None, content: bytes = b'', content_type: str = ''):
    response = MagicMock()
    response.status_code = status
    response.content = content
    response.headers = {'Content-Type': content_type}
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    repo = MagicMock()
    repo.my_request.return_value = response
    return repo


# region what FicHub says, read into the index's shape

def test_a_work_fichub_has_becomes_an_entry_shaped_as_a_listing_shapes_one():
    entry = fichub.entry_from(wolfbird(), LINK)

    assert entry['id'] == '75354806'
    assert entry['link'] == LINK
    assert entry['title'] == 'Wolfbird'
    assert entry['authors'] == ['OpalApparition']
    # written the way a listing writes dates, or the next ao3 pass would rewrite them
    assert entry['date_updated'] == '27 Apr 2026'
    assert entry['date_created'] == '05 Dec 2025'
    assert (entry['chapters_published'], entry['chapters_total']) == (14, None)
    assert entry['words'] == 180137
    assert (entry['kudos'], entry['comments'], entry['bookmarks'], entry['hits']) == \
        (46052, 21360, 16962, 1976720)
    assert entry['fandoms'][0] == 'Heated Rivalry (TV)'
    assert entry['warnings'] == ['No Archive Warnings Apply']
    assert entry['tags']['rating'] == 'Explicit'
    assert entry['tags']['categories'] == ['M/M']
    assert 'Shane Hollander/Ilya Rozanov' in entry['tags']['relationships']
    assert 'Hayden Pike' in entry['tags']['characters']
    assert 'Aftercare' in entry['tags']['additional']
    assert entry['summary'].startswith('Shane Hollander is hockey’s closeted golden boy')
    assert '\n' in entry['summary']  # one line per paragraph, as a listing's summary is
    assert entry[strings.BOOKMARK_TYPE_FIELD] == strings.BOOKMARK_TYPE_WORK
    # FicHub cannot know whether you bookmarked it, so it says nothing either way
    assert strings.BOOKMARKED_FIELD not in entry
    assert 'bookmark_notes' not in entry


def test_an_entry_already_indexed_keeps_its_own_fields_and_takes_the_stats():
    existing = {'id': '75354806', 'link': LINK, 'title': 'Wolfbird', 'authors': ['OpalApparition'],
                'chapters_published': 12, 'chapters_total': None, 'words': 150000,
                'date_updated': '01 Mar 2026', 'bookmarked': True, 'bookmark_notes': 'mine',
                'summary': 'what the listing said',
                'tags': {'rating': '', 'categories': [], 'relationships': [], 'characters': [],
                         'additional': []}}

    entry = fichub.entry_from(wolfbird(), LINK, existing)

    assert entry['bookmarked'] is True
    assert entry['bookmark_notes'] == 'mine'
    assert entry['summary'] == 'what the listing said'
    assert entry['chapters_published'] == 14
    assert entry['date_updated'] == '27 Apr 2026'
    # an entry made from a work page has no tags; FicHub fills what it left blank
    assert entry['tags']['rating'] == 'Explicit'

# endregion

# region asking FicHub

def test_fichub_is_asked_by_the_works_link():
    repo = answering(body=wolfbird())
    assert fichub.lookup(repo, LINK)['meta']['title'] == 'Wolfbird'
    repo.my_request.assert_called_once_with(
        'GET', 'https://fichub.net/api/v0/epub?q=https%3A%2F%2Farchiveofourown.org%2Fworks%2F75354806')


@pytest.mark.parametrize('repo', [
    answering(status=404),
    answering(body=ValueError('not json')),
    answering(body={'err': 1, 'msg': 'not found'}),
    answering(body=['not', 'an', 'answer']),
    answering(body={**wolfbird(), 'meta': {**wolfbird()['meta'],
                                           'source': 'https://archiveofourown.org/works/1'}}),
])
def test_anything_but_an_answer_about_this_work_is_a_failure(repo):
    with pytest.raises(exceptions.FicHubException):
        fichub.lookup(repo, LINK)


def test_a_format_is_fetched_from_fichub_itself():
    repo = answering(content=b'epub bytes', content_type='application/epub+zip')
    assert fichub.download(repo, wolfbird(), 'EPUB') == b'epub bytes'
    url = repo.my_request.call_args[0][1]
    assert url.startswith('https://fichub.net/cache/epub/4g7sxdaj/')


def test_a_link_to_anywhere_but_fichub_is_not_followed():
    answer = {**wolfbird(), 'urls': {'epub': 'https://elsewhere.example/file.epub'}}
    repo = answering(content=b'x')
    with pytest.raises(exceptions.FicHubException):
        fichub.download(repo, answer, 'EPUB')
    repo.my_request.assert_not_called()


def test_a_format_fichub_does_not_make_is_a_clear_failure():
    with pytest.raises(exceptions.FicHubException, match='AZW3'):
        fichub.download(answering(), wolfbird(), 'AZW3')


def test_a_page_arriving_for_an_epub_is_not_saved_as_one():
    repo = answering(content=b'<html>', content_type='text/html; charset=utf-8')
    with pytest.raises(exceptions.FicHubException):
        fichub.download(repo, wolfbird(), 'EPUB')


def test_html_sent_as_a_zip_is_taken_out_of_it():
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, 'w') as archive:
        archive.writestr('Wolfbird.html', '<html>the work</html>')
    repo = answering(content=packed.getvalue(), content_type='application/zip')
    assert fichub.download(repo, wolfbird(), 'HTML') == b'<html>the work</html>'

# endregion

# region the step at the end of every run

def test_every_workflow_tries_fichub_just_before_the_cleanup():
    for action in server.ACTIONS:
        for dates in (False, True):
            job = server.Job(action, ['JSON', 'HTML'], 'Someone',
                             server.resolve_options({'dates': dates, 'reindex': True}))
            steps = [step for step, _ in server.step_plan(job)]
            assert steps[-3:] == ['fichub', 'cleanup', 'report'], action


def test_only_ao3_works_with_a_number_are_offered_to_fichub():
    ao3 = MagicMock()
    ao3.failures = [
        {'id': '1', 'link': 'https://archiveofourown.org/works/1', 'error': 'gone'},
        {'id': None, 'link': '', 'error': 'deleted, no number'},
        {'id': None, 'link': 'https://elsewhere.example/story', 'error': 'external'},
        {'id': None, 'link': 'https://archiveofourown.org/series/5', 'error': 'a series'},
    ]
    assert [x['id'] for x in server.fichub_candidates(ao3)] == ['1']


@pytest.fixture
def library(fake_fileops):
    for name in (strings.INDEXING_FOLDER_NAME, strings.WORKS_FOLDER_NAME):
        os.makedirs(os.path.join(fake_fileops.downloadfolder, name), exist_ok=True)
    return fake_fileops


def a_run(library, filetypes, failures, answer='yes', background=False):
    job = server.Job(server.ACTION_BOOKMARKS, filetypes, 'Someone', background=background)
    asked = []

    def ask(question, default):
        asked.append((question, default))
        return {'choice': answer} if answer else dict(default)

    if not background: job.ask = ask
    ao3 = Ao3(MagicMock(), library, [x for x in filetypes if x != 'JSON'], None, False, False)
    ao3.failures = failures
    return job, ao3, asked


def index_files(library) -> list[str]:
    return sorted(os.listdir(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)))


def work_files(library) -> list[str]:
    return sorted(os.listdir(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME)))


def ao3_failed() -> list[dict]:
    return [{'id': '75354806', 'link': LINK, 'error': 'not a work file (404)'}]


@pytest.mark.fichub
def test_a_work_ao3_would_not_give_us_is_indexed_and_downloaded_from_fichub(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: f'{filetype} from fichub'.encode())
    job, ao3, asked = a_run(library, ['JSON', 'EPUB', 'HTML'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    question, default = asked[0]
    assert question['name'] == server.FICHUB_QUESTION
    assert question['count'] == 1 and question['ids'] == ['75354806']
    assert default == {'choice': server.FICHUB_YES}

    # named as any download is: number, title, author, and the date ao3 last updated it
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub',
                                   '75354806 Wolfbird - OpalApparition 2026-04-27.html']
    [name] = index_files(library)
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME, name),
              encoding='utf-8') as f:
        entry = indexing.flatten(json.load(f))
    assert entry['title'] == 'Wolfbird'
    assert entry[strings.RETRIEVED_FROM_FIELD] == {'site': 'fichub', 'downloaded': ['EPUB', 'HTML']}

    assert ao3.failures == []
    assert ao3.rescued == [{'id': '75354806', 'link': LINK, 'title': 'Wolfbird',
                            'downloaded': ['EPUB', 'HTML']}]
    assert '75354806' in ao3.downloaded


@pytest.mark.fichub
def test_fichub_reads_only_the_failed_works_entries_never_the_whole_index(library, monkeypatch):
    # in Dropbox every entry is a download of its own; reading them all to find one took a
    # run thirteen minutes before FicHub was even asked
    def whole_index(fileops):
        raise AssertionError('the whole index was read')
    monkeypatch.setattr(server.shared, 'read_index', whole_index)
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    for number in ('75354806', '1', '2'):
        with open(os.path.join(folder, f'{number} Some Title - Someone.json'), 'w', encoding='utf-8') as f:
            json.dump({'id': number, 'link': f'https://archiveofourown.org/works/{number}',
                       'title': 'Some Title', 'bookmarked': True}, f)
    read = []
    load = library.load_json
    monkeypatch.setattr(library, 'load_json', lambda path: read.append(path) or load(path))
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: b'from fichub')
    job, ao3, _ = a_run(library, ['JSON', 'HTML'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert [os.path.basename(x) for x in read if x.endswith('.json')][0] == \
        '75354806 Some Title - Someone.json'
    assert not any(os.path.basename(x).startswith(('1 ', '2 ')) for x in read)
    assert ao3.failures == []


# region FicHub never changes whether a fic is your bookmark

def indexed_as(library, bookmark: dict) -> None:
    # dated before FicHub's copy (2026-04-27), so FicHub's reading is written
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, '75354806 Wolfbird - OpalApparition.json'), 'w', encoding='utf-8') as f:
        # versioned, as every entry written since the history began is: the bookmark lives in
        # the newest reading, not at the root
        json.dump({'id': '75354806', 'link': LINK, 'source': 'https://archiveofourown.org/users/Example_Reader/bookmarks',
                   'indexes': [{'indexed_on': '2026-03-02', 'title': 'Wolfbird',
                                'authors': ['OpalApparition'], 'date_updated': '01 Mar 2026',
                                **bookmark}]}, f)


def entry_now(library) -> dict:
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME,
                           '75354806 Wolfbird - OpalApparition.json'), encoding='utf-8') as f:
        return indexing.flatten(json.load(f))


BOOKMARK_STATES = [
    {'bookmarked': True, 'bookmark_notes': 'mine', 'bookmark_tags': ['comfort'],
     'date_bookmarked': '02 Mar 2026', 'bookmark_rec': True},
    {'bookmarked': False},
    {},
]


@pytest.mark.fichub
@pytest.mark.parametrize('bookmark', BOOKMARK_STATES, ids=['bookmarked', 'not-bookmarked', 'unknown'])
@pytest.mark.parametrize('read_first', [True, False], ids=['entry-read', 'entry-unreadable'])
@pytest.mark.parametrize('action', [server.ACTION_BOOKMARKS, server.ACTION_WORK])
def test_a_fichub_reading_keeps_the_bookmark_the_index_already_had(library, monkeypatch, bookmark,
                                                                   read_first, action):
    # FicHub cannot know whether you bookmarked a fic. the entry handed to it is read at the
    # start of the step; one that would not read then must still keep its bookmark when the
    # FicHub reading is written into its file
    indexed_as(library, bookmark)
    if not read_first:
        monkeypatch.setattr(server, 'indexed_entries', lambda ao3, fileops, works, stop=None: {})
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'from fichub')
    job, ao3, _ = a_run(library, ['JSON', 'HTML'], ao3_failed())
    job.action = action

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    entry = entry_now(library)
    assert entry[strings.RETRIEVED_FROM_FIELD]['site'] == 'fichub'
    assert ao3.failures == []
    for field in strings.BOOKMARK_OWN_FIELDS:
        if field in bookmark: assert entry[field] == bookmark[field], field
        else: assert field not in entry, field


@pytest.mark.fichub
def test_fichub_reads_each_works_entry_in_its_turn_and_a_stop_ends_it_between_works(
        library, monkeypatch):
    # with AO3 down every work of a long import is here: reading every entry up front held the
    # step silent, and past a stop, for as long as that took
    failures = [{'id': str(n), 'link': f'https://archiveofourown.org/works/{n}', 'error': 'down'}
                for n in (1, 2, 3)]
    job, ao3, _ = a_run(library, ['JSON', 'HTML'], failures)
    read: list[set] = []
    rescued: list[str] = []

    def entries(ao3, fileops, works, stop=None):
        read.append(set(works))
        if len(read) == 2: job.cancel.set()
        return {}

    monkeypatch.setattr(server, 'indexed_entries', entries)
    monkeypatch.setattr(server, 'rescue_one',
                        lambda ao3, failure, *a, **k: rescued.append(failure['id']))

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert read == [{'1'}, {'2'}]
    assert rescued == ['1']


def test_keep_own_bookmark_takes_the_files_bookmark_over_the_documents():
    from source_code.ao3 import keep_own_bookmark
    on_disk = {'id': '1', 'indexes': [{'indexed_on': 'a', 'bookmarked': False}]}
    kept = keep_own_bookmark({'id': '1', 'title': 'T', 'bookmarked': True, 'bookmark_notes': 'x'},
                             on_disk)
    assert kept == {'id': '1', 'title': 'T', 'bookmarked': False}
    assert keep_own_bookmark({'id': '1', 'bookmarked': True}, None) == {'id': '1'}
    # how it came in may go alongside a bookmark: the page lists it as a bookmark all the same
    bookmark = {'id': '1', 'indexes': [{'indexed_on': 'a', 'bookmarked': True}]}
    kept = keep_own_bookmark({'id': '1', strings.FROM_LINK_FIELD: True}, bookmark)
    assert kept == {'id': '1', strings.FROM_LINK_FIELD: True, 'bookmarked': True}

# endregion


# region FicHub's copy older than the index

def indexed_newer_than_fichub(library) -> None:
    # FicHub's fixture says 2026-04-27; the index says the work moved on since
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, '75354806 Wolfbird - OpalApparition.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '75354806', 'link': LINK, 'title': 'Wolfbird',
                   'date_updated': '10 May 2026', 'tags': {'additional': ['mine']}}, f)


def a_copy(library, name: str) -> None:
    with open(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME, name), 'w') as f:
        f.write('what you had')


def index_text(library) -> str:
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME,
                           '75354806 Wolfbird - OpalApparition.json'), encoding='utf-8') as f:
        return f.read()


@pytest.mark.fichub
def test_an_older_fichub_copy_never_replaces_a_file_newer_than_it(library, monkeypatch, capsys):
    indexed_newer_than_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-05-10.epub')
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-04-27.html')
    a_copy(library, '75354806 Wolfbird - OpalApparition.pdf')
    fetched = []
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: fetched.append(filetype) or b'old')
    # nobody answers: FicHub is tried, and the undated file is kept
    job, ao3, asked = a_run(library, ['JSON', 'EPUB', 'HTML', 'PDF'], ao3_failed(), answer=None)
    before = index_text(library)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    # newer than FicHub's copy, the same, and undated: all kept, judged by their own names
    assert fetched == []
    assert [q['name'] for q, _ in asked] == [server.FICHUB_QUESTION,
                                             server.INFERRED_DATE_QUESTION]
    assert asked[1][0]['formats'] == ['PDF'] and asked[1][1] == {'choice': 'no'}
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.html',
                                   '75354806 Wolfbird - OpalApparition 2026-05-10.epub',
                                   '75354806 Wolfbird - OpalApparition.pdf']
    assert index_text(library) == before
    assert 'older version' in ao3.failures[0]['error']
    out = capsys.readouterr().out
    assert ("FicHub's copy of work 75354806 was last updated 27 April 2026, older than the last known update date we have "
            "(10 May 2026)") in out
    assert 'judged against it' not in out
    assert "EPUB: yours (2026-05-10) is newer than FicHub's copy - keeping it" in out
    assert "HTML: yours is the same version as FicHub's (2026-04-27) - keeping it" in out
    assert "PDF: no date can be read from your file's name, so we cannot tell which is newer" in out
    assert 'PDF: keeping your copy' in out


@pytest.mark.fichub
def test_an_older_fichub_copy_replaces_a_file_older_still_without_asking(library, monkeypatch, capsys):
    # your file says 1 Jan; FicHub has 27 Apr; the index says AO3 moved on to 10 May. FicHub's
    # copy is behind AO3's, but newer than what you have
    indexed_newer_than_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-01-01.html')
    fetched = []
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: fetched.append(filetype) or b'newer than yours')
    job, ao3, asked = a_run(library, ['JSON', 'HTML'], ao3_failed())
    before = index_text(library)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == ['HTML']
    assert [q['name'] for q, _ in asked] == [server.FICHUB_QUESTION]
    # named with FicHub's own date; the older copy gone; the index still AO3's newer reading
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.html']
    assert index_text(library) == before
    assert ao3.failures == [] and ao3.rescued[0]['downloaded'] == ['HTML']
    assert ("HTML: FicHub's copy (2026-04-27) is newer than yours (2026-01-01), though older "
            "than the last known update date we have - replacing it") in capsys.readouterr().out


@pytest.mark.fichub
@pytest.mark.parametrize('answer, replaced', [('no', False), (None, False), ('yes', True)])
def test_an_overwriting_run_asks_before_replacing_your_copy_with_an_older_fichub_one(
        library, monkeypatch, answer, replaced):
    indexed_newer_than_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-05-10.epub')
    fetched = []
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: fetched.append(filetype) or b'old')
    job, ao3, asked = a_run(library, ['JSON', 'EPUB'], ao3_failed())
    job.options['overwrite'] = True
    before = index_text(library)

    def ask(question, default):
        asked.append((question, default))
        if question['name'] == server.OVERWRITE_OLDER_QUESTION and answer is None:
            return dict(default)       # nobody answered: the default
        return {'choice': answer if question['name'] == server.OVERWRITE_OLDER_QUESTION else 'yes'}
    job.ask = ask

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    question, default = asked[-1]
    assert question['name'] == server.OVERWRITE_OLDER_QUESTION
    assert question['formats'] == ['EPUB']
    assert question['date'] == '2026-04-27' and question['newer'] == '2026-05-10'
    assert default == {'choice': 'no'}
    if replaced:
        assert fetched == ['EPUB']
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']
    else:
        assert fetched == []
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-05-10.epub']
        assert 'older version' in ao3.failures[0]['error']
    # whatever the answer, the index already says more than FicHub does
    assert index_text(library) == before


@pytest.mark.fichub
def test_a_format_you_have_none_of_is_taken_from_an_older_fichub_unasked_and_warned_about(
        library, monkeypatch, capsys):
    indexed_newer_than_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-05-10.epub')
    fetched = []
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: fetched.append(filetype) or b'old')
    job, ao3, asked = a_run(library, ['JSON', 'EPUB', 'HTML'], ao3_failed())
    before = index_text(library)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    # nothing asked but whether to try FicHub at all
    assert [q['name'] for q, _ in asked] == [server.FICHUB_QUESTION]
    # only the missing format, named with FicHub's own (older) date, never the index's
    assert fetched == ['HTML']
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.html',
                                   '75354806 Wolfbird - OpalApparition 2026-05-10.epub']
    # the index already says more than FicHub does, so it is left as it was
    assert index_text(library) == before
    assert ao3.failures == []
    assert ao3.rescued[0]['downloaded'] == ['HTML']
    # warned as it happens, and kept for the end of the run
    assert [(x['id'], x['formats'], x['fichub'], x['latest']) for x in ao3.fichub_older] == \
        [('75354806', ['HTML'], '2026-04-27', '2026-05-10')]
    out = capsys.readouterr().out
    assert 'older than the last known update date we have (10 May 2026' in out
    assert 'may be an older cached copy' in out


def indexed_as_fichub(library) -> None:
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, '75354806 Wolfbird - OpalApparition.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '75354806', 'link': LINK, 'title': 'Wolfbird', 'date_updated': '27 Apr 2026'}, f)


@pytest.mark.fichub
def test_an_older_fichub_copy_that_replaces_an_older_file_of_yours_is_warned_about_too(
        library, monkeypatch, capsys):
    indexed_newer_than_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-04-01.epub')
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'old')
    job, ao3, asked = a_run(library, ['JSON', 'EPUB', 'HTML'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    # nothing asked: your 1 April file is older than FicHub's 27 April copy
    assert [q['name'] for q, _ in asked] == [server.FICHUB_QUESTION]
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub',
                                   '75354806 Wolfbird - OpalApparition 2026-04-27.html']
    # both are listed at the end: the html you had none of, the epub that replaced yours
    [older] = ao3.fichub_older
    assert older['formats'] == ['HTML'] and older['replaced'] == {'EPUB': '2026-04-01'}
    assert older['fichub'] == '2026-04-27' and older['latest'] == '2026-05-10'
    out = capsys.readouterr().out
    assert ("the EPUB of work 75354806 from FicHub, dated 27 April 2026, replaced your copy "
            "(dated 1 April 2026) - but it is still older than the last known update date we have "
            "(10 May 2026)") in out


@pytest.mark.fichub
def test_a_fichub_copy_older_than_another_of_your_files_is_warned_about(library, monkeypatch):
    # the index is no newer than FicHub, but your epub's name says a later version exists
    indexed_as_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-05-10.epub')
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'old')
    job, ao3, asked = a_run(library, ['JSON', 'HTML'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert [q['name'] for q, _ in asked] == [server.FICHUB_QUESTION]
    assert '75354806 Wolfbird - OpalApparition 2026-04-27.html' in work_files(library)
    assert [(x['formats'], x['latest'], x['latestFrom']) for x in ao3.fichub_older] == \
        [(['HTML'], '2026-05-10', 'EPUB')]


@pytest.mark.fichub
def test_a_guessed_date_in_another_file_s_name_never_raises_the_warning(library, monkeypatch):
    indexed_as_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition (10 May 2026).epub')
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'new')
    job, ao3, asked = a_run(library, ['JSON', 'HTML'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert '75354806 Wolfbird - OpalApparition 2026-04-27.html' in work_files(library)
    assert ao3.fichub_older == []


@pytest.mark.fichub
def test_a_fichub_copy_as_new_as_everything_known_is_not_warned_about(library, monkeypatch):
    indexed_as_fichub(library)
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'new')
    job, ao3, _ = a_run(library, ['JSON', 'HTML'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert ao3.fichub_older == []


@pytest.mark.fichub
def test_the_end_of_the_run_lists_the_older_fichub_copies(library, monkeypatch):
    indexed_newer_than_fichub(library)
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'old')
    job, ao3, _ = a_run(library, ['JSON', 'HTML'], ao3_failed())
    server.rescue_with_fichub(job, library, ao3, MagicMock())
    events = []
    monkeypatch.setattr(server.progress, 'report',
                        lambda report, kind, **data: events.append((kind, data)))

    server.report_failures(ao3, MagicMock())

    assert (server.progress.FICHUB_OLDER, {'fichubOlder': ao3.fichub_older}) in events
    record = server.runs.RunRecord(MagicMock(), 'abcdef123456', 'quick', 'Quick scan', ['JSON'], {})
    record.collect(ao3)
    assert record.data['fichubOlder'] == ao3.fichub_older


def test_a_page_from_before_still_sending_the_retired_question_is_not_refused():
    assert server.background_answers({'fichub-outdated': {'choice': 'no'}}) == {}
    assert server.run_question_settings({'fichub-outdated': 'no'}, None) == ({}, None)
    assert server.question_timeouts({'fichub-outdated': 5}) == {}


@pytest.mark.fichub
def test_a_background_run_takes_an_older_fichub_copy_without_asking(library, monkeypatch, capsys):
    indexed_newer_than_fichub(library)
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'old')
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed(), background=True)
    before = index_text(library)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']
    assert index_text(library) == before


@pytest.mark.fichub
def test_a_fichub_copy_as_new_as_the_index_is_taken_as_before(library, monkeypatch):
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, '75354806 Wolfbird - OpalApparition.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '75354806', 'link': LINK, 'title': 'Wolfbird', 'date_updated': '27 Apr 2026'}, f)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-01-01.epub')
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'new')
    job, ao3, asked = a_run(library, ['JSON', 'EPUB'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert [q['name'] for q, _ in asked] == [server.FICHUB_QUESTION]
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']

# endregion


@pytest.mark.fichub
@pytest.mark.parametrize('action, marked', [(server.ACTION_WORK, True),
                                            (server.ACTION_WORKS, True),
                                            (server.ACTION_BOOKMARKS, False)])
def test_a_fic_run_s_fichub_entry_is_marked_downloaded_by_link(library, monkeypatch, action, marked):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'x')
    job, ao3, _ = a_run(library, ['JSON'], ao3_failed())
    job.action = action

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    [name] = index_files(library)
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME, name),
              encoding='utf-8') as f:
        entry = indexing.flatten(json.load(f))
    assert entry.get('from_link') is (True if marked else None)


# region FicHub in each workflow

def entry_of(library) -> dict:
    [name] = index_files(library)
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME, name),
              encoding='utf-8') as f:
        return indexing.flatten(json.load(f))


def fichub_serving(monkeypatch) -> list[str]:
    fetched: list[str] = []
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: fetched.append(filetype) or f'{filetype}'.encode())
    return fetched


@pytest.mark.fichub
@pytest.mark.parametrize('action, origin', [
    (server.ACTION_WORK, 'from_link'),
    (server.ACTION_WORKS, 'from_link'),
    (server.ACTION_QUICK, None),
    (server.ACTION_BOOKMARKS, None),
    (server.ACTION_IMPORT, 'from_import'),
])
def test_every_fic_and_scan_workflow_indexes_and_downloads_what_ao3_would_not_from_fichub(
        library, monkeypatch, action, origin):
    fetched = fichub_serving(monkeypatch)
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed())
    job.action = action

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == ['EPUB']
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']
    entry = entry_of(library)
    assert entry['title'] == 'Wolfbird'
    assert entry[strings.RETRIEVED_FROM_FIELD]['site'] == 'fichub'
    for field in ('from_link', 'from_import'):
        assert entry.get(field) is (True if field == origin else None)
    assert ao3.failures == [] and [x['id'] for x in ao3.rescued] == ['75354806']


def an_import(library, filetypes, **options):
    job, ao3, _ = a_run(library, filetypes, ao3_failed())
    job.action = server.ACTION_IMPORT
    job.options.update(options)
    return job, ao3


@pytest.mark.fichub
def test_a_work_an_import_only_looks_up_is_indexed_from_fichub_and_nothing_downloaded(
        library, monkeypatch, capsys):
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON', 'EPUB', 'HTML'], indexOnly=['75354806'])

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == []
    assert work_files(library) == []
    assert entry_of(library).get('from_import') is True
    assert ao3.failures == []
    assert 'nothing downloaded from FicHub' in capsys.readouterr().out


@pytest.mark.fichub
def test_an_imports_work_with_no_index_entry_at_all_is_taken_from_fichub_without_asking(
        library, monkeypatch, capsys):
    fetched = fichub_serving(monkeypatch)
    job, ao3, asked = a_run(library, ['JSON'], ao3_failed(), answer='no')
    job.action = server.ACTION_IMPORT
    job.options.update(indexOnly=['75354806'])

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    # a cached copy is better than no entry: not asked, and taken even with 'no' as the answer
    assert asked == []
    assert fetched == []
    assert entry_of(library)[strings.RETRIEVED_FROM_FIELD]['site'] == 'fichub'
    assert 'had no index entry at all' in capsys.readouterr().out


@pytest.mark.fichub
def test_an_imports_work_already_indexed_is_still_asked_about_before_fichub(library, monkeypatch):
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, '75354806 Wolfbird - OpalApparition.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '75354806', 'link': LINK, 'title': 'Wolfbird', 'date_updated': '2026-04-27'}, f)
    fetched = fichub_serving(monkeypatch)
    job, ao3, asked = a_run(library, ['JSON', 'EPUB'], ao3_failed(), answer='no')
    job.action = server.ACTION_IMPORT

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert [q['name'] for q, _ in asked] == ['fichub']
    assert fetched == []
    assert [x['id'] for x in ao3.failures] == ['75354806']


@pytest.mark.fichub
def test_an_import_not_replacing_outdated_copies_keeps_yours_and_fetches_only_what_is_missing(
        library, monkeypatch):
    a_copy(library, '75354806 Wolfbird - OpalApparition 2020-01-01.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON', 'EPUB', 'HTML'], replaceOutdated=False)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == ['HTML']
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2020-01-01.epub',
                                   '75354806 Wolfbird - OpalApparition 2026-04-27.html']


@pytest.mark.fichub
def test_an_import_replacing_outdated_copies_lets_fichub_replace_an_older_one(library, monkeypatch):
    a_copy(library, '75354806 Wolfbird - OpalApparition 2020-01-01.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON', 'EPUB'], replaceOutdated=True)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == ['EPUB']
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']


@pytest.mark.fichub
def test_an_import_replacing_outdated_copies_never_replaces_an_undated_one_from_fichub(
        library, monkeypatch):
    # with no date in its name it cannot be judged outdated: it is kept, and not fetched again
    a_copy(library, '75354806 Wolfbird - OpalApparition.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON', 'EPUB', 'HTML'], replaceOutdated=True)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == ['HTML']
    assert '75354806 Wolfbird - OpalApparition.epub' in work_files(library)


@pytest.mark.fichub
@pytest.mark.parametrize('name, agreed, replaced', [
    # FicHub's copy (27 April 2026) is newer than the date guessed from the name: replaced
    ('75354806 Wolfbird (1 May 2025).epub', True, True),
    # older than the guess: kept
    ('75354806 Wolfbird (1 May 2027).epub', True, False),
    # FicHub not agreed to: kept, however new its copy
    ('75354806 Wolfbird (1 May 2025).epub', False, False),
])
def test_an_imports_file_to_repair_is_replaced_from_fichub_only_on_the_rule_agreed_to(
        library, monkeypatch, name, agreed, replaced):
    a_copy(library, name)
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON'], repair=[name], repairFicHub=agreed)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    if replaced:
        assert fetched == ['EPUB']
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']
    else:
        assert fetched == []
        # kept, named from the entry as an import names every file - without FicHub's date
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition.epub']


@pytest.mark.fichub
def test_an_imports_file_to_repair_can_instead_be_named_with_fichubs_date_keeping_its_contents(
        library, monkeypatch, capsys):
    a_copy(library, '75354806 Wolfbird.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON'], repair=['75354806 Wolfbird.epub'],
                         repairFicHubRename=True, repairFicHubUndated=True)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    # nothing downloaded: the same file, named as its entry names it with FicHub's date
    assert fetched == []
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']
    with open(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME,
                           '75354806 Wolfbird - OpalApparition 2026-04-27.epub'), 'rb') as f:
        assert f.read() == b'what you had'
    assert "with FicHub's date (27 April 2026)" in capsys.readouterr().out


@pytest.mark.fichub
@pytest.mark.parametrize('name, check, renamed', [
    # FicHub's copy (27 April 2026) is not older than the guess: named with it
    ('75354806 Wolfbird (1 May 2025).epub', True, True),
    # older than the guess: kept as it is, with the rule on
    ('75354806 Wolfbird (1 May 2027).epub', True, False),
    # ...and named all the same with the rule off
    ('75354806 Wolfbird (1 May 2027).epub', False, True),
    # no date to guess: named, rule or not
    ('75354806 Wolfbird.epub', True, True),
])
def test_naming_with_fichubs_date_keeps_to_the_guessed_date_only_when_asked(
        library, monkeypatch, name, check, renamed):
    a_copy(library, name)
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON'], repair=[name], repairFicHubRename=True,
                         repairFicHubCheck=check, repairFicHubUndated=True)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == []
    if renamed:
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']
    else:
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition.epub']


@pytest.mark.fichub
@pytest.mark.parametrize('name, older, undated, renamed', [
    # a name that looks no newer than FicHub's copy: renamed only when that answer is yes
    ('75354806 Wolfbird (1 May 2025).epub', True, False, True),
    ('75354806 Wolfbird (1 May 2025).epub', False, True, False),
    # no date to guess: renamed only when that answer is yes
    ('75354806 Wolfbird.epub', True, False, False),
    ('75354806 Wolfbird.epub', False, True, True),
    # a name that looks newer than FicHub's copy: never, whatever the answers
    ('75354806 Wolfbird (1 May 2027).epub', True, True, False),
])
def test_naming_with_fichubs_date_follows_the_two_answers_given(
        library, monkeypatch, name, older, undated, renamed):
    a_copy(library, name)
    fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON'], repair=[name], repairFicHubRename=True,
                         repairFicHubOlder=older, repairFicHubUndated=undated)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert (work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']) is renamed


@pytest.mark.fichub
@pytest.mark.parametrize('older, replaced', [(True, True), (False, False)])
def test_overwriting_with_fichubs_copy_follows_the_answer_for_a_name_that_looks_older(
        library, monkeypatch, older, replaced):
    a_copy(library, '75354806 Wolfbird (1 May 2025).epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON'], repair=['75354806 Wolfbird (1 May 2025).epub'],
                         repairFicHub=True, repairFicHubOlder=older)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert (fetched == ['EPUB']) is replaced


@pytest.mark.fichub
def test_naming_a_file_with_fichubs_date_never_renames_over_another(library, monkeypatch, capsys):
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-04-27.epub')
    a_copy(library, '75354806 Wolfbird.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON'], repair=['75354806 Wolfbird.epub'],
                         repairFicHubRename=True, repairFicHubUndated=True)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == []
    assert len(work_files(library)) == 2
    assert '75354806 Wolfbird - OpalApparition 2026-04-27.epub' in work_files(library)
    assert 'is already taken by another file' in capsys.readouterr().out
    assert [(x['file'], x['site']) for x in ao3.repair_clashes] == [
        ('75354806 Wolfbird.epub', strings.SOURCE_FICHUB)]


@pytest.mark.fichub
def test_a_repair_from_fichub_that_would_land_on_another_files_name_is_not_done(
        library, monkeypatch, capsys):
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-04-27.epub')
    a_copy(library, '75354806 Wolfbird (1 May 2025).epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON'], repair=['75354806 Wolfbird (1 May 2025).epub'],
                         repairFicHub=True)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == []
    assert len(work_files(library)) == 2
    assert 'is already taken by another file' in capsys.readouterr().out
    assert [(x['file'], x['site']) for x in ao3.repair_clashes] == [
        ('75354806 Wolfbird (1 May 2025).epub', strings.SOURCE_FICHUB)]


@pytest.mark.fichub
def test_a_work_only_looked_up_gets_nothing_from_fichub_but_its_file_to_repair(library, monkeypatch):
    a_copy(library, '75354806 Wolfbird.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON', 'HTML'], indexOnly=['75354806'],
                         repair=['75354806 Wolfbird.epub'], repairFicHub=True,
                         repairFicHubUndated=True)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert fetched == ['EPUB']
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']


@pytest.mark.fichub
def test_an_import_names_its_files_from_a_fichub_entry_keeping_each_files_own_date_or_none(
        library, monkeypatch):
    a_copy(library, '75354806 saved long ago.html')
    a_copy(library, '75354806 saved long ago 2019-08-14.pdf')
    fichub_serving(monkeypatch)
    job, ao3 = an_import(library, ['JSON', 'HTML', 'PDF'], indexOnly=['75354806'])

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    # named as the entry names the work - but never given FicHub's date: the files hold
    # whatever version they hold
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2019-08-14.pdf',
                                   '75354806 Wolfbird - OpalApparition.html']


@pytest.mark.fichub
def test_a_scan_never_renames_files_from_a_fichub_entry(library, monkeypatch):
    a_copy(library, '75354806 saved long ago.html')
    fichub_serving(monkeypatch)
    job, ao3, _ = a_run(library, ['JSON'], ao3_failed())
    job.action = server.ACTION_QUICK

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert work_files(library) == ['75354806 saved long ago.html']

# endregion


@pytest.mark.fichub
def test_a_work_neither_ao3_nor_fichub_has_stays_a_failure_naming_both(library, monkeypatch):
    def nowhere(repo, link):
        raise exceptions.FicHubException('FicHub could not find it (not found)')

    monkeypatch.setattr(server.fichub, 'lookup', nowhere)
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    [failure] = ao3.failures
    assert failure['error'] == 'AO3: not a work file (404) | FicHub: FicHub could not find it (not found)'
    assert failure['fichub'] == 'FicHub could not find it (not found)'
    assert ao3.rescued == []
    assert work_files(library) == [] and index_files(library) == []


@pytest.mark.fichub
def test_a_format_fichub_cannot_give_leaves_the_work_failed_but_keeps_what_came(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: fichub.download(MagicMock(), answer, filetype)
                        if filetype == 'AZW3' else b'epub')
    job, ao3, _ = a_run(library, ['JSON', 'EPUB', 'AZW3'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']
    [failure] = ao3.failures
    assert 'AZW3' in failure['fichub']
    [name] = index_files(library)
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME, name),
              encoding='utf-8') as f:
        assert indexing.flatten(json.load(f))[strings.RETRIEVED_FROM_FIELD]['downloaded'] == ['EPUB']


@pytest.mark.fichub
def test_saying_no_leaves_the_failures_as_they_were(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', MagicMock())
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed(), answer='no')

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    server.fichub.lookup.assert_not_called()
    assert ao3.failures == ao3_failed()


@pytest.mark.fichub
def test_a_background_run_tries_fichub_without_asking(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'epub')
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed(), background=True)
    job.emit = MagicMock()

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert ao3.failures == [] and len(ao3.rescued) == 1
    assert not any(c.args and c.args[0].get('type') == 'question' for c in job.emit.call_args_list)


@pytest.mark.fichub
def test_a_run_with_nothing_failed_never_asks(library):
    job, ao3, asked = a_run(library, ['JSON', 'EPUB'], [])
    job.steps = MagicMock()

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert asked == []
    job.steps.skip.assert_called_once_with('fichub')


@pytest.mark.fichub
def test_a_metadata_only_run_indexes_from_fichub_and_downloads_nothing(library, monkeypatch):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', MagicMock())
    job, ao3, _ = a_run(library, ['JSON'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    server.fichub.download.assert_not_called()
    assert len(index_files(library)) == 1 and work_files(library) == []
    assert ao3.failures == []


def test_a_later_reading_from_ao3_does_not_carry_the_fichub_mark(library):
    ao3 = Ao3(MagicMock(), library, [], None, False, False)
    record = {**fichub.entry_from(wolfbird(), LINK),
              strings.RETRIEVED_FROM_FIELD: {'site': 'fichub', 'downloaded': []}}
    ao3.save_metadata(record, from_mirror=True)
    ao3.indexed_on = 'later'
    # an ao3 pass carries the whole record forward, as `refresh_one` does
    ao3.save_metadata({**record, 'kudos': 50000})

    [name] = index_files(library)
    with open(os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME, name),
              encoding='utf-8') as f:
        saved = json.load(f)
    first, latest = saved[indexing.INDEXES]
    assert first[strings.RETRIEVED_FROM_FIELD]['site'] == 'fichub'
    assert strings.RETRIEVED_FROM_FIELD not in latest


def test_a_single_fic_ao3_will_not_show_is_handed_to_fichub_rather_than_ending_the_run(
        library, monkeypatch):
    ao3 = MagicMock()
    ao3.failures = []
    ao3.index_one_work.side_effect = exceptions.DeletedException('deleted')
    ao3.record_failure.side_effect = lambda link, e: ao3.failures.append(
        {'id': '75354806', 'link': link, 'error': str(e)})
    monkeypatch.setattr(server, 'Ao3', MagicMock(return_value=ao3))
    monkeypatch.setattr(server.shared, 'read_index', lambda fileops: [])
    finished = MagicMock()
    monkeypatch.setattr(server, 'finish_run', finished)
    job = server.Job(server.ACTION_WORK, ['JSON', 'EPUB'], 'Someone',
                     server.resolve_options({}), url='75354806')

    server.run_work(job, library, MagicMock(), MagicMock())

    finished.assert_called_once()
    assert ao3.failures[0]['id'] == '75354806'

# endregion


def a_fic_page(monkeypatch, shown: set[str]):
    """Stand AO3 in for the fic runs: the works in `shown` have a page, every other is down.
    Each existing entry handed over is kept by work number."""

    given = {}

    def index_one_work(self, link, existing=None, find_existing=None):
        work = link.rsplit('/', 1)[-1]
        print(f'(ao3 asked about {work})')
        if work not in shown: raise exceptions.Ao3DownException('AO3 is down')
        given[work] = find_existing() if find_existing else existing
        raise exceptions.DeletedException('stop here')
    monkeypatch.setattr(server.Ao3, 'index_one_work', index_one_work)
    monkeypatch.setattr(server, 'finish_run', MagicMock())
    return given


def an_index_file(library, number: str, title: str) -> None:
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, f'{number} {title} - Someone.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': number, 'link': f'https://archiveofourown.org/works/{number}',
                   'title': title}, f)


@pytest.mark.parametrize('action, url', [
    (server.ACTION_WORK, '75354806'),
    (server.ACTION_WORKS, 'https://archiveofourown.org/works/75354806\nhttps://archiveofourown.org/works/2'),
])
def test_a_fic_run_finds_its_fics_entries_by_number_never_reading_the_whole_index(
        library, monkeypatch, action, url):
    # in Dropbox every entry is a download of its own, and reading them all held 'looking
    # up work' for minutes before ao3 was asked anything
    def whole_index(fileops):
        raise AssertionError('the whole index was read')
    monkeypatch.setattr(server.shared, 'read_index', whole_index)
    an_index_file(library, '75354806', 'Title 75354806')
    an_index_file(library, '1', 'Title 1')
    given = a_fic_page(monkeypatch, {'75354806', '2'})
    job = server.Job(action, ['JSON', 'HTML'], 'Someone', server.resolve_options({}), url=url)

    (server.run_work if action == server.ACTION_WORK else server.run_works)(
        job, library, MagicMock(), MagicMock())

    assert given['75354806']['title'] == 'Title 75354806'
    if action == server.ACTION_WORKS: assert given['2'] is None


def test_a_fic_run_asks_ao3_first_then_looks_for_its_index_file(library, monkeypatch, capsys):
    an_index_file(library, '75354806', 'Wolfbird')
    a_fic_page(monkeypatch, {'75354806', '1'})

    for url in ('75354806', '1'):
        job = server.Job(server.ACTION_WORK, ['JSON'], 'Someone', server.resolve_options({}), url=url)
        server.run_work(job, library, MagicMock(), MagicMock())
    lines = capsys.readouterr().out.splitlines()

    said = [x for x in lines if 'index file' in x or 'on AO3' in x or x.startswith('(ao3')]
    assert said == [
        'looking up work 75354806 on AO3',
        '(ao3 asked about 75354806)',
        'looking for an existing index file for work 75354806...',
        'found the index file for work 75354806: 75354806 Wolfbird - Someone.json',
        'looking up work 1 on AO3',
        '(ao3 asked about 1)',
        'looking for an existing index file for work 1...',
        'no index file for work 1 yet - a new one will be made',
    ]


def test_a_fic_ao3_will_not_show_never_reads_the_library(library, monkeypatch, capsys):
    # straight on to FicHub at the end: nothing to save, so nothing to look for
    read = []
    load = library.load_json
    monkeypatch.setattr(library, 'load_json', lambda path: read.append(path) or load(path))
    an_index_file(library, '75354806', 'Wolfbird')
    a_fic_page(monkeypatch, set())
    job = server.Job(server.ACTION_WORKS, ['JSON'], 'Someone', server.resolve_options({}),
                     url=LINK + '\nhttps://archiveofourown.org/works/2')

    server.run_works(job, library, MagicMock(), MagicMock())

    assert not [x for x in read if 'indexing' in str(x)]
    assert 'index file' not in capsys.readouterr().out
    assert [x['id'] for x in job.ao3.failures] == ['75354806', '2']


def test_several_fics_each_ask_ao3_then_look_for_their_own_index_file(library, monkeypatch, capsys):
    an_index_file(library, '75354806', 'Wolfbird')
    a_fic_page(monkeypatch, {'75354806', '2'})
    job = server.Job(server.ACTION_WORKS, ['JSON'], 'Someone', server.resolve_options({}),
                     url=LINK + '\nhttps://archiveofourown.org/works/2')

    server.run_works(job, library, MagicMock(), MagicMock())
    said = [x for x in capsys.readouterr().out.splitlines()
            if 'index file' in x or 'on AO3' in x]

    assert said == [
        'fic 1 of 2: looking up work 75354806 on AO3',
        'looking for an existing index file for work 75354806...',
        'found the index file for work 75354806: 75354806 Wolfbird - Someone.json',
        'fic 2 of 2: looking up work 2 on AO3',
        'looking for an existing index file for work 2...',
        'no index file for work 2 yet - a new one will be made',
    ]


@pytest.mark.fichub
def test_fichub_says_what_it_is_about_to_do_before_each_thing(library, monkeypatch, capsys):
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download', lambda repo, answer, filetype: b'bytes')
    job, ao3, _ = a_run(library, ['JSON', 'EPUB'], ao3_failed())

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    said = [x.strip() for x in capsys.readouterr().out.splitlines() if x.strip()]
    order = [
        'trying FicHub for 1 works: 75354806',
        f'FicHub 1 of 1: asking FicHub about work 75354806 ({LINK})...',
        'FicHub has work 75354806: Wolfbird',
        'fetching EPUB of work 75354806 from FicHub...',
        'writing the index entry for work 75354806 from what FicHub says...',
        'index updated for work 75354806 from FicHub',
    ]
    places = [said.index(line) for line in order]
    assert places == sorted(places)


def test_a_fic_run_names_the_work_whose_index_it_did_or_did_not_update(library, monkeypatch, capsys):
    ao3 = MagicMock()
    ao3.failures = []
    ao3.reindexed = {'1'}
    ao3.index_one_work.side_effect = lambda link, existing=None, find_existing=None: (
        {'id': link.rsplit('/', 1)[1], 'link': link} if not link.endswith('/2')
        else (_ for _ in ()).throw(exceptions.DeletedException('deleted')))
    monkeypatch.setattr(server, 'Ao3', MagicMock(return_value=ao3))
    monkeypatch.setattr(server.shared, 'read_index', lambda fileops: [])
    monkeypatch.setattr(server, 'index_marked_series', lambda *a: [])
    monkeypatch.setattr(server, 'download_planned', MagicMock())
    monkeypatch.setattr(server, 'finish_run', MagicMock())
    links = [f'https://archiveofourown.org/works/{n}' for n in (1, 2, 3)]
    job = server.Job(server.ACTION_WORKS, ['JSON'], 'Someone', server.resolve_options({}),
                     url='\n'.join(links))

    server.run_works(job, library, MagicMock(), MagicMock())

    said = capsys.readouterr().out
    assert 'index updated for work 1' in said
    # ao3 would not show it
    assert 'index not updated for work 2' in said
    # read, but its entry was not written - a save that failed is not claimed
    assert 'index not updated for work 3' in said


# region an undated file and FicHub

def indexed_as_new_as_fichub(library) -> None:
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, '75354806 Wolfbird - OpalApparition.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '75354806', 'link': LINK, 'title': 'Wolfbird',
                   'date_updated': '27 Apr 2026'}, f)


@pytest.mark.fichub
@pytest.mark.parametrize('answer, replaced', [('no', False), (None, False), ('yes', True)])
def test_fichub_asks_before_replacing_a_file_with_no_date_in_its_name(
        library, monkeypatch, answer, replaced):
    # FicHub's copy is as new as the index: the AO3 rules, but an undated file is asked about,
    # and kept unless you say otherwise
    indexed_as_new_as_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3, asked = a_run(library, ['JSON', 'EPUB'], ao3_failed(), answer=answer)
    if answer == 'no':
        # FicHub itself is still tried: only the undated question is answered no
        job.ask = lambda q, d: (asked.append((q, d)) or
                                ({'choice': 'no'} if q['name'] == server.INFERRED_DATE_QUESTION
                                 else {'choice': 'yes'}))

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    names = [q['name'] for q, _ in asked]
    assert names == [server.FICHUB_QUESTION, server.INFERRED_DATE_QUESTION]
    question, default = asked[1]
    assert question['ids'] == ['75354806'] and question['formats'] == ['EPUB']
    assert default == {'choice': 'no'}
    assert fetched == (['EPUB'] if replaced else [])
    files = work_files(library)
    assert ('75354806 Wolfbird - OpalApparition.epub' in files) is not replaced


@pytest.mark.fichub
def test_fichub_asks_about_an_undated_file_on_a_run_that_overwrites_too(library, monkeypatch):
    indexed_as_new_as_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3, asked = a_run(library, ['JSON', 'EPUB'], ao3_failed(), answer=None)
    job.options['overwrite'] = True

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    question, default = asked[-1]
    assert question['name'] == server.INFERRED_DATE_QUESTION
    # FicHub's copy may be an older cached one: keeping yours is recommended, overwriting or not
    assert question['recommended'] == 'no' and 'older cached one' in question['reasons']['EPUB']
    # nobody answered: kept
    assert fetched == []


@pytest.mark.fichub
@pytest.mark.parametrize('answer, replaced', [(None, False), ('yes', True)])
def test_an_overwriting_run_asks_before_fichub_replaces_a_file_dated_after_its_copy(
        library, monkeypatch, answer, replaced):
    # FicHub's copy is as new as the index (27 April 2026), and your epub, named the app's way,
    # is dated after it: overwriting would go backwards, so it is asked about - kept by default
    indexed_as_new_as_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-05-01.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3, asked = a_run(library, ['JSON', 'EPUB'], ao3_failed(), answer=answer)
    job.options['overwrite'] = True

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    question, default = asked[-1]
    assert question['name'] == server.OVERWRITE_OLDER_QUESTION and question['formats'] == ['EPUB']
    assert default == {'choice': 'no'}
    assert fetched == (['EPUB'] if replaced else [])


@pytest.mark.fichub
def test_an_overwriting_run_lets_fichub_replace_a_file_of_the_same_date_unasked(library, monkeypatch):
    indexed_as_new_as_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-04-27.epub')
    fetched = fichub_serving(monkeypatch)
    job, ao3, asked = a_run(library, ['JSON', 'EPUB'], ao3_failed(), answer=None)
    job.options['overwrite'] = True

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert [q['name'] for q, _ in asked] == [server.FICHUB_QUESTION]
    assert fetched == ['EPUB']


@pytest.mark.fichub
def test_an_older_fichub_copy_asks_before_replacing_an_undated_file(library, monkeypatch):
    indexed_newer_than_fichub(library)
    a_copy(library, '75354806 Wolfbird - OpalApparition.html')
    fetched = []
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: fetched.append(filetype) or b'from fichub')
    job, ao3, asked = a_run(library, ['JSON', 'HTML'], ao3_failed())
    before = index_text(library)

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    assert [q['name'] for q, _ in asked] == [server.FICHUB_QUESTION, server.INFERRED_DATE_QUESTION]
    assert fetched == ['HTML']
    assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.html']
    assert index_text(library) == before

# endregion
