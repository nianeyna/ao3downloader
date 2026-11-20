"""The release announcement: what is posted, that it always fits, and how each site is asked."""

import pytest

import announce

# region the committed note

def test_the_committed_release_note_fits_both_sites_whole_for_any_version():
    # the rule: every pull request writes .github/release-note.txt, and this is what stops one
    # that would be cut short - counted with the longest version a post could carry
    note = announce.read_note()
    assert note, 'write .github/release-note.txt - a line or two on what this change brings'
    assert announce.problems(announce.LONGEST_VERSION, note) == []

# endregion

# region what is posted

def test_x_ends_with_the_address_and_bluesky_with_words_that_open_it():
    assert announce.compose_x('1.2.3', 'Faster Dropbox.\n') == (
        'v1.2.3 is live \U0001FA84\nFaster Dropbox.\n'
        '\u21aa https://github.com/alexandria-p/FicFairy/releases/latest')
    assert announce.compose_bluesky('1.2.3', 'Faster Dropbox.\n') == (
        'v1.2.3 is live \U0001FA84\nFaster Dropbox.\n\u21aa Get it here\u2728')


def test_a_note_the_last_release_already_posted_is_not_posted_again():
    assert announce.note_for('Faster Dropbox.', 'Faster Dropbox.\n') == announce.FALLBACK_NOTE
    assert announce.note_for('', 'anything') == announce.FALLBACK_NOTE
    assert announce.note_for('Faster Dropbox.', 'Older note.') == 'Faster Dropbox.'


def test_x_counts_the_link_as_23_and_an_emoji_as_2():
    text = announce.compose_x('1.2.3', 'abc')
    # 'v1.2.3 is live ' 15 + wand 2 + newline + 'abc' + newline + arrow 2 + space + link 23
    assert announce.x_length(text) == 15 + 2 + 1 + 3 + 1 + 2 + 1 + 23
    # an emoji with a selector is 2, as X counts it
    assert announce.x_length('\u2764\uFE0F') == 2
    # one made of joined emoji is 2 to X; counted per part here - over, never under, so a note
    # that passes always fits
    assert announce.x_length('\U0001F469\u200D\U0001F4BB') >= 2


def test_a_note_too_long_for_either_site_is_refused_with_how_far_over_rather_than_cut():
    found = announce.problems('1.2.3', 'x' * 300)
    assert any('too long for X by' in p for p in found)
    assert any('too long for Bluesky by' in p for p in found)
    # with words in place of the address on Bluesky, X's 280 is the one that binds: the address
    # counts 23 there, and the arrow and the wand count 2 each
    assert announce.problems('1.2.3', 'x' * 235) == []
    assert [p for p in announce.problems('1.2.3', 'x' * 236) if 'X' in p]
    assert not [p for p in announce.problems('1.2.3', 'x' * 236) if 'Bluesky' in p]


def test_a_note_with_a_link_of_its_own_is_refused():
    assert announce.problems('1.2.3', 'see https://example.com')


def test_the_committed_check_fails_the_build_for_a_note_too_long(tmp_path, monkeypatch, capsys):
    note = tmp_path / 'release-note.txt'
    note.write_text('x' * 400, encoding='utf-8')
    monkeypatch.setattr(announce, 'NOTE_FILE', note)
    monkeypatch.setattr(announce, 'read_note', lambda path=note: note.read_text(encoding='utf-8'))
    assert announce.main(['check']) == 1
    assert 'too long' in capsys.readouterr().out

# endregion

# region posting

class Answer:
    def __init__(self, status, body=None, text=''):
        self.status_code = status
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


class Sites:
    """Stands in for requests.Session, answering Bluesky as it answers - and failing the test
    if anything reaches X, which nothing here may."""

    def __init__(self, bluesky_status=200):
        self.calls = []
        self.bluesky_status = bluesky_status

    def post(self, url, json=None, headers=None, timeout=None):
        assert 'x.com' not in url and 'twitter.com' not in url, url
        self.calls.append((url, json, headers or {}))
        if url.endswith('createSession'):
            return Answer(200, {'accessJwt': 'jwt', 'did': 'did:plc:me'})
        if url.endswith('createRecord'):
            return Answer(self.bluesky_status, {'uri': 'at://did:plc:me/app.bsky.feed.post/1'}, 'nope')
        raise AssertionError(url)


BLUESKY_SECRETS = {'BLUESKY_HANDLE': 'me.bsky.social', 'BLUESKY_APP_PASSWORD': 'app-password'}


def test_the_deploy_posts_to_bluesky_with_the_words_opening_the_latest_release():
    sites = Sites()
    note = 'Faster \U0001FA84 Dropbox.'
    assert announce.announce('1.2.3', note, BLUESKY_SECRETS, sites)

    record = next(body for url, body, _ in sites.calls if url.endswith('createRecord'))['record']
    assert record['text'] == announce.compose_bluesky('1.2.3', note)
    assert announce.RELEASE_LINK not in record['text']
    # placed by utf-8 bytes, past the four-byte emoji and the three-byte arrow
    facet = record['facets'][0]
    raw = record['text'].encode('utf-8')
    assert raw[facet['index']['byteStart']:facet['index']['byteEnd']].decode() == 'Get it here'
    assert facet['features'][0]['uri'] == announce.RELEASE_LINK


def test_without_bluesky_secrets_nothing_is_posted_and_nothing_fails(capsys):
    sites = Sites()
    assert announce.announce('1.2.3', 'Note.', {}, sites)
    assert sites.calls == []
    assert 'not posted to Bluesky' in capsys.readouterr().out


def test_x_is_never_posted_to_even_with_the_old_x_secrets_set():
    # Sites fails the test on any request to X
    sites = Sites()
    old = {'X_API_KEY': 'k', 'X_API_SECRET': 's', 'X_ACCESS_TOKEN': 't', 'X_ACCESS_SECRET': 'ts'}
    assert announce.announce('1.2.3', 'Note.', {**BLUESKY_SECRETS, **old}, sites)


def test_a_bluesky_failure_is_said_and_no_secret_is_printed(capsys):
    assert not announce.announce('1.2.3', 'Note.', BLUESKY_SECRETS, Sites(bluesky_status=500))
    out = capsys.readouterr().out
    assert 'bluesky: not posted' in out
    assert 'app-password' not in out

# endregion

# region a release left unannounced

def test_a_release_whose_note_is_no_post_is_not_posted_to_bluesky(capsys):
    sites = Sites()
    assert announce.announce('1.2.3', 'no-post', BLUESKY_SECRETS, sites)
    assert sites.calls == []
    assert 'not posted to Bluesky' in capsys.readouterr().out


def test_no_post_is_never_turned_into_the_fallback_note_and_posted():
    # the release before was unannounced too: the same note again must still post nothing
    note = announce.note_for('no-post\n', 'no-post')
    sites = Sites()
    assert announce.announce('1.2.3', note, BLUESKY_SECRETS, sites)
    assert sites.calls == []


def test_no_post_passes_the_check_and_the_preview_offers_no_x_link():
    assert announce.problems(announce.LONGEST_VERSION, 'no-post') == []
    shown = announce.preview_text('1.2.3', 'no-post')
    assert 'No posts for this release' in shown
    assert announce.X_INTENT_URL not in shown


def test_a_note_that_only_mentions_no_post_is_still_posted():
    sites = Sites()
    assert announce.announce('1.2.3', 'Releases can now be marked no-post.', BLUESKY_SECRETS, sites)
    assert any(url.endswith('createRecord') for url, _, _ in sites.calls)

# endregion

# region the merge preview

def test_the_preview_shows_both_posts_how_each_site_counts_them_and_the_link_that_posts_on_x():
    shown = announce.preview_text('1.2.3', 'Faster Dropbox.')
    assert announce.compose_x('1.2.3', 'Faster Dropbox.') in shown
    assert announce.compose_bluesky('1.2.3', 'Faster Dropbox.') in shown
    assert 'of 280' in shown and 'of 300' in shown
    assert announce.x_intent_link('1.2.3', 'Faster Dropbox.') in shown
    assert 'will not post' in announce.preview_text('1.2.3', 'x' * 300)
    assert 'x.com/intent' not in announce.preview_text('1.2.3', 'x' * 300)


def test_the_x_link_opens_x_with_the_whole_post_written_in():
    import urllib.parse
    link = announce.x_intent_link('1.2.3', 'Faster \U0001FA84 Dropbox & more.')
    assert link.startswith('https://x.com/intent/post?text=')
    assert ' ' not in link and '&more' not in link
    sent = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)['text'][0]
    assert sent == announce.compose_x('1.2.3', 'Faster \U0001FA84 Dropbox & more.')


def test_the_preview_shows_the_version_the_next_deploy_will_give(tmp_path):
    import subprocess
    run = lambda *a: subprocess.run(a, cwd=tmp_path, check=True, capture_output=True)
    run('git', 'init', '-q')
    run('git', '-c', 'user.email=a@b', '-c', 'user.name=a', 'commit', '-q', '--allow-empty', '-m', 'a')
    for tag in ('v1.9.0', 'v1.10.0', 'v1.2.0'):
        run('git', 'tag', tag)
    (tmp_path / 'VERSION').write_text('1.0.0\n', encoding='utf-8')
    assert announce.coming_version(tmp_path) == '1.10.1'
    # a VERSION above every release is the next version as it is, as the deploy takes it
    (tmp_path / 'VERSION').write_text('2.0.0\n', encoding='utf-8')
    assert announce.coming_version(tmp_path) == '2.0.0'


def test_the_release_description_opens_with_the_note_bluesky_was_given():
    body = announce.release_body('Faster Dropbox.\n')
    assert body.startswith("## What's new\n\nFaster Dropbox.\n")
    # a line under what's new, then the instructions under a heading of the same size
    whats_new, install = body.split('\n---\n', 1)
    assert 'Faster Dropbox.' in whats_new
    assert install.lstrip().startswith('## Installation instructions\n\n' + announce.INSTALL_NOTES)
    assert announce.INSTALL_NOTES not in whats_new


def test_a_release_not_announced_has_no_whats_new():
    for note in ('no-post', 'No-Post\n', ''):
        body = announce.release_body(note)
        assert "What's new" not in body
        assert '---' not in body
        assert body.strip() == ('## Installation instructions\n\n' + announce.INSTALL_NOTES).strip()


def test_release_notes_writes_the_description(tmp_path, monkeypatch):
    note_file = tmp_path / 'release-note.txt'
    note_file.write_text('Faster Dropbox.\n', encoding='utf-8')
    monkeypatch.setattr(announce, 'NOTE_FILE', note_file)
    monkeypatch.setattr(announce, 'read_note', lambda path=note_file: note_file.read_text().strip())
    monkeypatch.setattr(announce, 'previous_note', lambda version: '')
    out = tmp_path / 'notes.md'
    assert announce.main(['release-notes', '--version', '1.2.3', '--out', str(out)]) == 0
    assert out.read_text(encoding='utf-8') == announce.release_body('Faster Dropbox.')
