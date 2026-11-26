import os
import shutil
from contextlib import contextmanager
from datetime import datetime

import mobi
import pytest
from bs4 import BeautifulSoup, Tag

import ao3downloader.parse_soup as parse_soup
import ao3downloader.parse_text as parse_text
from ao3downloader import strings

from test.conftest import ebook_fixtures


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
EBOOK_DIR = os.path.join(FIXTURES_DIR, 'ebook')


def _ids(paths):
    return [os.path.basename(p) for p in paths]


@contextmanager
def _extracted_mobi_soup(path: str):
    """Context manager that extracts a mobi and yields its html as BeautifulSoup."""
    tempdir, filepath = mobi.extract(path)
    try:
        with open(filepath, encoding='utf-8') as f:
            yield BeautifulSoup(f, 'html.parser')
    finally:
        shutil.rmtree(tempdir)


def _load_ebook_html(path: str) -> BeautifulSoup:
    with open(path, encoding='utf-8') as f:
        return BeautifulSoup(f, 'html.parser')


def test_get_work_urls(fixture_soup, snapshot):
    soup = fixture_soup('bookmarks')
    work_urls = parse_soup.get_work_urls(soup)
    assert work_urls == snapshot


def test_get_series_urls_bookmarks(fixture_soup, snapshot):
    soup = fixture_soup('bookmarks')
    series_urls = parse_soup.get_series_urls(soup, False)
    assert series_urls == snapshot


def test_get_series_urls_all(fixture_soup, snapshot):
    soup = fixture_soup('bookmarks')
    series_urls = parse_soup.get_series_urls(soup, True)
    assert series_urls == snapshot


def test_is_locked_true(fixture_soup):
    soup = fixture_soup('lockedWorkLoggedOut')
    assert parse_soup.is_locked(soup) == True


def test_is_locked_false(fixture_soup):
    soup = fixture_soup('lockedWorkLoggedIn')
    assert parse_soup.is_locked(soup) == False


def test_is_deleted_true(fixture_soup):
    soup = fixture_soup('deletedWork')
    assert parse_soup.is_deleted(soup) == True


def test_is_deleted_false(fixture_soup):
    soup = fixture_soup('unlockedWork')
    assert parse_soup.is_deleted(soup) == False


def test_is_explicit_true(fixture_soup):
    soup = fixture_soup('explicitWorkLoggedOut')
    assert parse_soup.is_explicit(soup) == True


def test_is_explicit_false(fixture_soup):
    soup = fixture_soup('explicitWorkLoggedIn')
    assert parse_soup.is_explicit(soup) == False


def test_get_title(fixture_soup, snapshot):
    soup = fixture_soup('unlockedWork')
    link = 'https://archiveofourown.org/works/12345678'
    pattern = (
        'id:{worknum} '
        'title:{title} '
        'author:{author} '
        'fandom:{fandom} '
        'pairing:{pairing} '
        'rating:{rating} '
        'warning:{warning} '
        'category:{category} '
        'words:{words} '
        'chapters:{chapters} '
        'language:{language} '
        'published:{published} '
        'updated:{updated} '
        'series_title:{series_title} '
        'series_index:{series_index}'
    )
    assert parse_soup.get_title(soup, link, pattern) == snapshot


def test_get_title_multiple_series(fixture_soup, snapshot):
    soup = fixture_soup('multipleSeries')
    link = 'https://archiveofourown.org/works/12345678'
    pattern = '{series_title} {series_index} {fandom}'
    assert parse_soup.get_title(soup, link, pattern) == snapshot


def test_get_total_pages(fixture_soup, snapshot):
    soup = fixture_soup('bookmarks')
    assert parse_soup.get_total_pages(soup) == snapshot


def test_get_total_pages_no_pagination(fixture_soup):
    soup = fixture_soup('unlockedWork')
    assert parse_soup.get_total_pages(soup) is None


def test_get_total_pages_empty_pagination():
    soup = BeautifulSoup('<ol class="pagination"></ol>', 'html.parser')
    assert parse_soup.get_total_pages(soup) is None


def test_get_total_pages_only_prev_next():
    soup = BeautifulSoup(
        '<ol class="pagination">'
        '<li><a rel="previous">← Previous</a></li>'
        '<li><a rel="next">Next →</a></li>'
        '</ol>',
        'html.parser')
    assert parse_soup.get_total_pages(soup) is None


def test_get_total_pages_single_page():
    soup = BeautifulSoup(
        '<ol class="pagination">'
        '<li><em class="current">1</em></li>'
        '</ol>',
        'html.parser')
    assert parse_soup.get_total_pages(soup) == 1


# region get_login_token

def test_get_login_token_extracts_value_from_real_login_page(fixture_soup):
    soup = fixture_soup('lockedWorkLoggedOut')

    token = parse_soup.get_login_token(soup)

    # token is a non-empty string; exact value rotates when fixtures are refreshed
    assert isinstance(token, str)
    assert token
    assert not token.isspace()


def test_get_login_token_raises_when_form_missing():
    soup = BeautifulSoup('<html><head><title>A page</title></head></html>', 'html.parser')

    with pytest.raises(Exception, match='A page'):
        parse_soup.get_login_token(soup)


def test_get_login_token_raises_when_token_field_missing():
    soup = BeautifulSoup('<form id="new_user"></form>', 'html.parser')

    with pytest.raises(Exception):
        parse_soup.get_login_token(soup)


def test_get_login_token_raises_when_token_value_empty():
    soup = BeautifulSoup(
        '<form id="new_user">'
        '<input name="authenticity_token" value=""/>'
        '</form>', 'html.parser')

    with pytest.raises(Exception):
        parse_soup.get_login_token(soup)

# endregion


# region get_mark_read_token

def test_get_mark_read_token_returns_value_from_marked_for_later_page(fixture_soup):
    soup = fixture_soup('markedForLater')

    token = parse_soup.get_mark_read_token(soup)

    assert isinstance(token, str)
    assert token
    assert not token.isspace()


def test_get_mark_read_token_returns_none_when_actions_missing():
    soup = BeautifulSoup('<html></html>', 'html.parser')
    assert parse_soup.get_mark_read_token(soup) is None


def test_get_mark_read_token_returns_none_when_mark_li_missing():
    soup = BeautifulSoup(
        '<ul class="work navigation actions"></ul>', 'html.parser')
    assert parse_soup.get_mark_read_token(soup) is None


def test_get_mark_read_token_returns_none_when_form_missing():
    soup = BeautifulSoup(
        '<ul class="work navigation actions"><li class="mark"></li></ul>',
        'html.parser')
    assert parse_soup.get_mark_read_token(soup) is None

# endregion


# region get_image_links

def test_get_image_links_extracts_src_from_workskin(fixture_soup):
    # all locked works have 'lockblue' relative img link
    # relative links will be stripped out later by the 
    # download logic, but the soup logic should return them
    soup = fixture_soup('lockedWorkLoggedIn')

    links = parse_soup.get_image_links(soup)

    assert links
    assert all(isinstance(href, str) and href for href in links)


def test_get_image_links_skips_img_without_src():
    soup = BeautifulSoup(
        '<div id="workskin"><img src="a.png"/><img/></div>', 'html.parser')
    assert parse_soup.get_image_links(soup) == ['a.png']


def test_get_image_links_returns_empty_when_no_workskin(fixture_soup):
    soup = fixture_soup('bookmarks')
    assert parse_soup.get_image_links(soup) == []


def test_get_image_links_returns_empty_when_workskin_has_no_images(fixture_soup):
    soup = fixture_soup('unlockedWork')
    assert parse_soup.get_image_links(soup) == []

# endregion


# region has_custom_skin

def test_has_custom_skin_true(fixture_soup):
    assert parse_soup.has_custom_skin(fixture_soup('unlockedWork')) is True


def test_has_custom_skin_false(fixture_soup):
    assert parse_soup.has_custom_skin(fixture_soup('unlockedWorkNoSkin')) is False

# endregion


# region work metadata

def _list_metadata(fixture_soup, fixture: str, worknum: str) -> dict:
    soup = fixture_soup(fixture)
    return parse_soup.get_work_metadata_from_list(soup, f'https://archiveofourown.org/works/{worknum}')


def _assert_reading_history_format(result: dict) -> None:
    # last_visited and times_visited change whenever the fixtures are refreshed,
    # so assert only that they are a valid AO3 date and a number
    datetime.strptime(result['last_visited'], '%d %b %Y')
    assert result['times_visited'].isdigit()


def _assert_bookmark_date_format(result: dict) -> None:
    # ao3 renders the bookmark date inside a fragment cache that is not keyed
    # on time zone, so the displayed day can shift when the cache regenerates -
    # assert only that it is a valid AO3 date
    datetime.strptime(result['date_bookmarked'], '%d %b %Y')


def test_get_work_metadata_from_work_returns_expected_keys(fixture_soup, snapshot):
    soup = fixture_soup('unlockedWork')
    link = 'https://archiveofourown.org/works/12345678'

    metadata = parse_soup.get_work_metadata_from_work(soup, link)

    assert metadata == snapshot


def test_get_work_metadata_from_work_updated_uses_status_date_when_present(fixture_soup):
    soup = fixture_soup('multipleSeries')

    metadata = parse_soup.get_work_metadata_from_work(soup, 'https://archiveofourown.org/works/41214669')

    assert metadata['updated'] == '2023-08-10'
    assert metadata['updated'] != metadata['published']


def test_get_work_metadata_from_work_updated_falls_back_to_published(fixture_soup):
    # ao3 omits the status date for '1/1' works, so the published date is
    # the closest available value (and the one listing blurbs display)
    soup = fixture_soup('unlockedWork')

    metadata = parse_soup.get_work_metadata_from_work(soup, 'https://archiveofourown.org/works/41822007')

    assert metadata['updated'] == metadata['published']
    assert metadata['updated'] != ''


def test_get_work_metadata_from_list_returns_error_field_on_malformed_blurb():
    # no <li class="work-N"> present — blurb is None so .find will raise
    soup = BeautifulSoup('<html></html>', 'html.parser')

    result = parse_soup.get_work_metadata_from_list(soup, 'https://archiveofourown.org/works/1')

    assert 'error' in result


def test_get_work_metadata_from_list_does_not_leak_from_other_blurbs(fixture_soup):
    # bookmarks.html contains many works; metadata must come from the requested
    # blurb only, not from tags collected across the whole index page. this blurb
    # has no series, bookmarker's tags, or notes while its neighbors have all three.
    result = _list_metadata(fixture_soup, 'bookmarks', '66326125')

    assert 'error' not in result
    assert result['title'] == 'Being An Account of An Abduction, and Its Aftermath'
    assert result['fandoms'] == ['Final Fantasy XIV']
    assert result['relationships'] == ['Honoroit Banlardois/Emmanellain de Fortemps']
    assert result['characters'] == ['Emmanellain de Fortemps', 'Honoroit Banlardois']
    # Tags that belong to other bookmarks in the fixture must NOT leak in.
    assert 'Pon Farr' not in result['tags']
    assert 'Mind Meld' not in result['tags']
    assert result['series'] == []
    assert result['updated'] == '09 Jun 2025'
    _assert_bookmark_date_format(result)
    assert result['bookmarker_tags'] == []
    assert result['bookmarker_notes'] == ''
    # bookmark listings have no reading history data
    assert result['last_visited'] == ''
    assert result['times_visited'] == ''


def test_get_work_metadata_from_list_series_and_bookmarker_tags(fixture_soup):
    result = _list_metadata(fixture_soup, 'bookmarks', '34816549')

    assert result['series'] == ['Part 1 of MXTX - Retellings', 'Part 1 of No Paths Are Bound + Extras']
    assert result['updated'] == '08 Sep 2022'
    _assert_bookmark_date_format(result)
    assert result['bookmarker_tags'] == ['long work']
    assert result['bookmarker_notes'] == ''


def test_get_work_metadata_from_list_bookmarker_notes(fixture_soup):
    result = _list_metadata(fixture_soup, 'bookmarks', '42461841')

    assert result['bookmarker_notes'].strip() == '<p>This bookmark has a note!</p>'
    assert result['bookmarker_tags'] == []
    assert result['updated'] == '18 Oct 2022'
    _assert_bookmark_date_format(result)


def test_get_work_metadata_from_list_marked_for_later(fixture_soup):
    result = _list_metadata(fixture_soup, 'markedForLaterList', '66326125')

    _assert_reading_history_format(result)
    assert result['updated'] == '09 Jun 2025'
    assert result['series'] == []
    # reading history listings have no bookmark data
    assert result['date_bookmarked'] == ''
    assert result['bookmarker_tags'] == []
    assert result['bookmarker_notes'] == ''


def test_get_work_metadata_from_list_marked_for_later_does_not_leak_from_other_blurbs(fixture_soup):
    result = _list_metadata(fixture_soup, 'markedForLaterList', '334557')

    assert result['series'] == ["Part 1 of Watches 'Verse"]
    _assert_reading_history_format(result)
    assert result['updated'] == '06 Feb 2012'


@pytest.mark.parametrize('fixture,worknum', [
    ('bookmarks', '66326125'),
    ('bookmarks', '34816549'),
    ('markedForLaterList', '334557'),
])
def test_get_work_metadata_from_list_returns_same_keys_for_all_listing_types(fixture_soup, fixture, worknum):
    # the csv column headers are derived from these keys, so they must be
    # identical for every work regardless of listing type
    result = _list_metadata(fixture_soup, fixture, worknum)

    assert list(result.keys()) == [
        'title', 'author', 'summary', 'fandoms', 'warnings', 'characters',
        'relationships', 'tags', 'words', 'rating', 'chapters', 'categories',
        'complete', 'series', 'updated', 'date_bookmarked', 'bookmarker_tags',
        'bookmarker_notes', 'last_visited', 'times_visited']


def test_get_work_metadata_from_list_plain_listing_sets_empty_optional_fields():
    # plain listings (search results, tag pages) have no bookmark or reading history data
    html = (
        '<li class="work blurb group work-99" id="work_99">'
        '<div class="header module">'
        '<h4 class="heading"><a href="/works/99">Some Work</a></h4>'
        '<p class="datetime">01 Jan 2020</p>'
        '</div></li>')
    soup = BeautifulSoup(html, 'html.parser')

    result = parse_soup.get_work_metadata_from_list(soup, 'https://archiveofourown.org/works/99')

    assert 'error' not in result
    assert result['updated'] == '01 Jan 2020'
    assert result['series'] == []
    assert result['date_bookmarked'] == ''
    assert result['bookmarker_tags'] == []
    assert result['bookmarker_notes'] == ''
    assert result['last_visited'] == ''
    assert result['times_visited'] == ''

# endregion


# region download link construction from blurbs

def _work_blurb(fixture_soup, fixture: str, worknum: str):
    blurb = parse_soup.get_work_blurb(fixture_soup(fixture), f'https://archiveofourown.org/works/{worknum}')
    assert blurb is not None
    return blurb


def _blurb_metadata(fixture_soup, fixture: str, worknum: str) -> dict:
    blurb = _work_blurb(fixture_soup, fixture, worknum)
    return parse_soup.get_work_metadata_from_blurb(blurb, f'https://archiveofourown.org/works/{worknum}')


def test_get_work_blurb_finds_the_requested_blurb(fixture_soup):
    blurb = _work_blurb(fixture_soup, 'bookmarks', '66326125')

    assert blurb.select('h4.heading a')[0].get('href') == '/works/66326125'


def test_get_work_blurb_returns_none_when_absent(fixture_soup):
    soup = fixture_soup('bookmarks')

    assert parse_soup.get_work_blurb(soup, 'https://archiveofourown.org/works/999999999999') is None


def test_get_work_blurb_returns_none_for_non_work_link(fixture_soup):
    soup = fixture_soup('bookmarks')

    assert parse_soup.get_work_blurb(soup, 'https://archiveofourown.org/series/123') is None


@pytest.mark.parametrize('fixture', ['bookmarks', 'markedForLaterList'])
def test_get_blurb_updated_timestamp_is_unix_timestamp(fixture_soup, fixture):
    # the timestamp value changes whenever the fixtures are refreshed, so assert
    # only the format here - accuracy is covered by the constructed link test below
    timestamp = parse_soup.get_blurb_updated_timestamp(_work_blurb(fixture_soup, fixture, '66326125'))

    assert timestamp is not None
    assert timestamp.isdigit()


def test_get_blurb_updated_timestamp_none_when_comment_missing():
    # subscription listings (and any other listing without full blurbs) have no updated_at comment
    html = (
        '<li class="work blurb group work-99" id="work_99">'
        '<div class="header module">'
        '<h4 class="heading"><a href="/works/99">Some Work</a></h4>'
        '</div></li>')
    blurb = BeautifulSoup(html, 'html.parser').find('li')

    assert isinstance(blurb, Tag)
    assert parse_soup.get_blurb_updated_timestamp(blurb) is None


def test_get_blurb_updated_timestamp_ignores_visible_text():
    # the timestamp must come from an html comment, never from displayed text
    html = (
        '<li class="work blurb group work-99" id="work_99">'
        '<div class="header module">updated_at=999'
        '<h4 class="heading"><a href="/works/99">Some Work</a></h4>'
        '</div></li>')
    blurb = BeautifulSoup(html, 'html.parser').find('li')

    assert isinstance(blurb, Tag)
    assert parse_soup.get_blurb_updated_timestamp(blurb) is None


@pytest.mark.parametrize('fixture', ['bookmarks', 'markedForLaterList'])
def test_get_work_metadata_from_blurb_matches_work_page(fixture_soup, fixture):
    # the two metadata sources must produce identical values so that filenames never
    # depend on which one was used - otherwise already-downloaded works would stop
    # being recognized. markedForLater is the work page for a work that also appears
    # as a blurb in both listing fixtures.
    link = 'https://archiveofourown.org/works/66326125'
    work_metadata = parse_soup.get_work_metadata_from_work(fixture_soup('markedForLater'), link)
    blurb_metadata = _blurb_metadata(fixture_soup, fixture, '66326125')

    assert blurb_metadata == {key: work_metadata[key] for key in blurb_metadata}
    # the keys blurbs cannot provide must be exactly the hardcoded fallback token list
    assert set(work_metadata) - set(blurb_metadata) == set(strings.AO3_WORK_PAGE_ONLY_TOKENS)


@pytest.mark.skipif(not os.path.exists(os.path.join(FIXTURES_DIR, 'incompleteWorkPage.html')),
                    reason='run dev/refresh_fixtures.py --only-new to download the incompleteWorkPage fixture')
def test_get_work_metadata_from_blurb_matches_work_page_with_status_date(fixture_soup):
    # complements the test above, which covers a '1/1' work whose work page has no
    # status date: 218676 is a chaptered wip, so this proves that a real status date
    # equals the reformatted blurb datetime across the two metadata sources
    link = 'https://archiveofourown.org/works/218676'
    work_metadata = parse_soup.get_work_metadata_from_work(fixture_soup('incompleteWorkPage'), link)
    blurb_metadata = _blurb_metadata(fixture_soup, 'bookmarks', '218676')

    assert work_metadata['updated'] != work_metadata['published']
    assert blurb_metadata == {key: work_metadata[key] for key in blurb_metadata}


def test_get_work_metadata_from_blurb_multiple_series(fixture_soup):
    result = _blurb_metadata(fixture_soup, 'bookmarks', '34816549')

    assert result['series_title'] == 'MXTX - Retellings, No Paths Are Bound + Extras'
    assert result['series_index'] == '1, 1'


def test_get_work_metadata_from_blurb_updated_is_in_work_page_format(fixture_soup):
    # multichapter work whose blurb datetime is a real last-updated date;
    # the raw blurb text is '08 Sep 2022'
    result = _blurb_metadata(fixture_soup, 'bookmarks', '34816549')

    assert result['updated'] == '2022-09-08'


def test_constructed_download_link_matches_work_page_link(fixture_soup):
    # end to end: a download link constructed purely from listing blurb data must
    # exactly match the real link scraped from the work page. because this runs
    # against freshly refreshed fixtures in ci, it is the canary for ao3-side
    # changes to the download filename logic or the updated_at comment.
    link = 'https://archiveofourown.org/works/66326125'
    blurb = _work_blurb(fixture_soup, 'markedForLaterList', '66326125')
    metadata = parse_soup.get_work_metadata_from_blurb(blurb, link)
    timestamp = parse_soup.get_blurb_updated_timestamp(blurb)
    assert timestamp is not None
    slug = parse_text.get_download_slug(metadata['title'], metadata['worknum'])

    constructed = parse_text.get_download_url(metadata['worknum'], slug, 'EPUB', timestamp)

    assert constructed == parse_soup.get_download_link(fixture_soup('markedForLater'), 'EPUB')


@pytest.mark.parametrize('fixture, worknum', [
    ('unlockedWork', '41822007'),
    ('multipleSeries', '41214669'),
])
def test_download_slug_matches_work_page_link(fixture_soup, fixture, worknum):
    # additional canary coverage for differently shaped titles: the slug computed
    # from the work title must appear in the real scraped download link
    link = f'https://archiveofourown.org/works/{worknum}'
    soup = fixture_soup(fixture)
    metadata = parse_soup.get_work_metadata_from_work(soup, link)
    slug = parse_text.get_download_slug(metadata['title'], worknum)

    assert f'/downloads/{worknum}/{slug}.epub' in parse_soup.get_download_link(soup, 'EPUB')

# endregion


# region is_hidden

def test_is_hidden_true(fixture_soup):
    assert parse_soup.is_hidden(fixture_soup('hiddenWork')) is True


def test_is_hidden_false(fixture_soup):
    assert parse_soup.is_hidden(fixture_soup('unlockedWork')) is False

# endregion


# region HTML format helpers

@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.html'),
                         ids=_ids(ebook_fixtures('23009290', '.html')))
def test_get_work_link_html_on_real_fixture(path):
    link = parse_soup.get_work_link_html(_load_ebook_html(path))

    assert link is not None
    assert 'archiveofourown.org/works/' in link


def test_get_work_link_html_returns_none_when_not_two_links():
    html = (
        '<div id="preface">'
        '<p class="message">'
        '<a href="https://archiveofourown.org/works/42">only</a>'
        '</p></div>'
    )
    soup = BeautifulSoup(html, 'html.parser')

    assert parse_soup.get_work_link_html(soup) is None


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.html'),
                         ids=_ids(ebook_fixtures('23009290', '.html')))
def test_get_stats_html_on_real_fixture(path):
    stats = parse_soup.get_stats_html(_load_ebook_html(path))

    assert stats is not None
    assert 'Chapters:' in stats


def test_get_stats_html_returns_none_when_not_found():
    html = (
        '<div id="preface"><div class="meta"><dl class="tags">'
        '<dd>Published: 2024</dd>'
        '</dl></div></div>'
    )
    soup = BeautifulSoup(html, 'html.parser')

    assert parse_soup.get_stats_html(soup) is None


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.html'),
                         ids=_ids(ebook_fixtures('334557', '.html')))
def test_get_series_html_on_work_in_series(path):
    series = parse_soup.get_series_html(_load_ebook_html(path))

    assert series
    assert all('archiveofourown.org/series/' in s for s in series)


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.html'),
                         ids=_ids(ebook_fixtures('23009290', '.html')))
def test_get_series_html_returns_empty_on_work_with_no_series(path):
    assert parse_soup.get_series_html(_load_ebook_html(path)) == []

# endregion


# region MOBI format helpers

@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.mobi'),
                         ids=_ids(ebook_fixtures('23009290', '.mobi')))
def test_get_work_link_mobi_finds_archiveofourown_works_link(path):
    with _extracted_mobi_soup(path) as soup:
        link = parse_soup.get_work_link_mobi(soup)

    assert link is not None
    assert 'archiveofourown.org/works/' in link


def test_get_work_link_mobi_returns_none_when_no_match():
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    assert parse_soup.get_work_link_mobi(soup) is None


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.mobi'),
                         ids=_ids(ebook_fixtures('23009290', '.mobi')))
def test_get_stats_mobi_finds_blockquote_chapters(path):
    with _extracted_mobi_soup(path) as soup:
        stats = parse_soup.get_stats_mobi(soup)

    assert stats is not None
    assert 'Chapters:' in stats


def test_get_stats_mobi_returns_none_when_missing():
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    assert parse_soup.get_stats_mobi(soup) is None


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.mobi'),
                         ids=_ids(ebook_fixtures('334557', '.mobi')))
def test_get_series_mobi_returns_series_from_work_in_series(path):
    with _extracted_mobi_soup(path) as soup:
        series = parse_soup.get_series_mobi(soup)

    assert series
    assert all('archiveofourown.org/series/' in s for s in series)


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.mobi'),
                         ids=_ids(ebook_fixtures('23009290', '.mobi')))
def test_get_series_mobi_returns_empty_when_work_has_no_series(path):
    # mobiTest.mobi is of a solo work with no series
    with _extracted_mobi_soup(path) as soup:
        assert parse_soup.get_series_mobi(soup) == []


def test_get_series_mobi_returns_empty_when_label_missing():
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    assert parse_soup.get_series_mobi(soup) == []

# endregion
