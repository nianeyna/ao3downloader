import os
import shutil

import mobi
import pytest
from bs4 import BeautifulSoup

import ao3downloader.parse_soup as parse_soup
from ao3downloader import strings


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


@pytest.fixture(scope='module')
def mobi_test_soup():
    """Extract mobiTest.mobi once per module and return the parsed HTML soup."""
    tempdir, filepath = mobi.extract(os.path.join(FIXTURES_DIR, 'mobiTest.mobi'))
    try:
        with open(filepath, encoding='utf-8') as f:
            yield BeautifulSoup(f, 'html.parser')
    finally:
        shutil.rmtree(tempdir)


@pytest.fixture(scope='module')
def work_in_series_mobi_soup():
    """Extract workInSeries.mobi once per module and return the parsed HTML soup."""
    tempdir, filepath = mobi.extract(os.path.join(FIXTURES_DIR, 'workInSeries.mobi'))
    try:
        with open(filepath, encoding='utf-8') as f:
            yield BeautifulSoup(f, 'html.parser')
    finally:
        shutil.rmtree(tempdir)


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


# region get_mark_as_read_link
# todo: real fixtures

def test_get_mark_as_read_link_returns_full_url_when_present():
    html = f'<li class="mark"><a href="/works/1/mark_as_read">{strings.AO3_MARK_READ}</a></li>'
    soup = BeautifulSoup(html, 'html.parser')

    result = parse_soup.get_mark_as_read_link(soup)

    assert result == strings.AO3_BASE_URL + '/works/1/mark_as_read'


def test_get_mark_as_read_link_returns_none_when_missing():
    soup = BeautifulSoup('<html></html>', 'html.parser')
    assert parse_soup.get_mark_as_read_link(soup) is None

# endregion


# region has_custom_skin

def test_has_custom_skin_true(fixture_soup):
    assert parse_soup.has_custom_skin(fixture_soup('unlockedWork')) is True


def test_has_custom_skin_false(fixture_soup):
    assert parse_soup.has_custom_skin(fixture_soup('unlockedWorkNoSkin')) is False

# endregion


# region work metadata

def test_get_work_metadata_from_work_returns_expected_keys(fixture_soup, snapshot):
    soup = fixture_soup('unlockedWork')
    link = 'https://archiveofourown.org/works/12345678'

    metadata = parse_soup.get_work_metadata_from_work(soup, link)

    assert metadata == snapshot


def test_get_work_metadata_from_list_returns_error_field_on_malformed_blurb():
    # no <li class="work-N"> present — blurb is None so .find will raise
    soup = BeautifulSoup('<html></html>', 'html.parser')

    result = parse_soup.get_work_metadata_from_list(soup, 'https://archiveofourown.org/works/1')

    assert 'error' in result

# endregion


# region is_hidden

def test_is_hidden_true(fixture_soup):
    assert parse_soup.is_hidden(fixture_soup('hiddenWork')) is True


def test_is_hidden_false(fixture_soup):
    assert parse_soup.is_hidden(fixture_soup('unlockedWork')) is False

# endregion


# region HTML format helpers
# todo: real fixtures

def test_get_work_link_html_returns_second_preface_link():
    html = (
        '<div id="preface">'
        '<p class="message">'
        '<a href="https://example.com/other">first</a>'
        '<a href="https://archiveofourown.org/works/42">second</a>'
        '</p></div>'
    )
    soup = BeautifulSoup(html, 'html.parser')

    assert parse_soup.get_work_link_html(soup) == 'https://archiveofourown.org/works/42'


def test_get_work_link_html_returns_none_when_not_two_links():
    html = (
        '<div id="preface">'
        '<p class="message">'
        '<a href="https://archiveofourown.org/works/42">only</a>'
        '</p></div>'
    )
    soup = BeautifulSoup(html, 'html.parser')

    assert parse_soup.get_work_link_html(soup) is None


def test_get_stats_html_finds_chapters_dd():
    html = (
        '<div id="preface"><div class="meta"><dl class="tags">'
        '<dd>Published: 2024</dd>'
        '<dd>Chapters: 3/10</dd>'
        '</dl></div></div>'
    )
    soup = BeautifulSoup(html, 'html.parser')

    assert 'Chapters: 3/10' in parse_soup.get_stats_html(soup)


def test_get_stats_html_returns_none_when_not_found():
    html = (
        '<div id="preface"><div class="meta"><dl class="tags">'
        '<dd>Published: 2024</dd>'
        '</dl></div></div>'
    )
    soup = BeautifulSoup(html, 'html.parser')

    assert parse_soup.get_stats_html(soup) is None


def test_get_series_html_returns_series_links():
    html = (
        '<div id="preface"><div class="meta"><dl class="tags">'
        '<dd><a href="https://archiveofourown.org/series/1">one</a></dd>'
        '<dd><a href="https://archiveofourown.org/works/999">work</a></dd>'
        '<dd><a href="https://archiveofourown.org/series/2">two</a></dd>'
        '</dl></div></div>'
    )
    soup = BeautifulSoup(html, 'html.parser')

    assert parse_soup.get_series_html(soup) == [
        'https://archiveofourown.org/series/1',
        'https://archiveofourown.org/series/2',
    ]


def test_get_series_html_returns_empty_when_no_series():
    html = '<div id="preface"><div class="meta"><dl class="tags"></dl></div></div>'
    soup = BeautifulSoup(html, 'html.parser')

    assert parse_soup.get_series_html(soup) == []

# endregion


# region MOBI format helpers

def test_get_work_link_mobi_finds_archiveofourown_works_link(mobi_test_soup):
    link = parse_soup.get_work_link_mobi(mobi_test_soup)

    assert link is not None
    assert 'archiveofourown.org/works/' in link


def test_get_work_link_mobi_returns_none_when_no_match():
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    assert parse_soup.get_work_link_mobi(soup) is None


def test_get_stats_mobi_finds_blockquote_chapters(mobi_test_soup):
    stats = parse_soup.get_stats_mobi(mobi_test_soup)

    assert stats is not None
    assert 'Chapters:' in stats


def test_get_stats_mobi_returns_none_when_missing():
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    assert parse_soup.get_stats_mobi(soup) is None


def test_get_series_mobi_returns_series_from_work_in_series(work_in_series_mobi_soup):
    series = parse_soup.get_series_mobi(work_in_series_mobi_soup)

    assert series
    assert all('archiveofourown.org/series/' in s for s in series)


def test_get_series_mobi_returns_empty_when_work_has_no_series(mobi_test_soup):
    assert parse_soup.get_series_mobi(mobi_test_soup) == []


def test_get_series_mobi_returns_empty_when_label_missing():
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    assert parse_soup.get_series_mobi(soup) == []

# endregion
