import os

from bs4 import BeautifulSoup

import ao3downloader.parse_soup as parse_soup


def test_get_work_urls(snapshot):
    soup = get_soup_from_fixture('bookmarks')
    work_urls = parse_soup.get_work_urls(soup)
    assert work_urls == snapshot


def test_get_series_urls_bookmarks(snapshot):
    soup = get_soup_from_fixture('bookmarks')
    series_urls = parse_soup.get_series_urls(soup, False)
    assert series_urls == snapshot


def test_get_series_urls_all(snapshot):
    soup = get_soup_from_fixture('bookmarks')
    series_urls = parse_soup.get_series_urls(soup, True)
    assert series_urls == snapshot


def test_is_locked_true():
    soup = get_soup_from_fixture('lockedWorkLoggedOut')
    assert parse_soup.is_locked(soup) == True


def test_is_locked_false():
    soup = get_soup_from_fixture('lockedWorkLoggedIn')
    assert parse_soup.is_locked(soup) == False


def test_is_deleted_true():
    soup = get_soup_from_fixture('deletedWork')
    assert parse_soup.is_deleted(soup) == True


def test_is_deleted_false():
    soup = get_soup_from_fixture('unlockedWork')
    assert parse_soup.is_deleted(soup) == False


def test_is_explict_true():
    soup = get_soup_from_fixture('explicitWorkLoggedOut')
    assert parse_soup.is_explicit(soup) == True


def test_is_explict_false():
    soup = get_soup_from_fixture('explicitWorkLoggedIn')
    assert parse_soup.is_explicit(soup) == False


def get_soup_from_fixture(filename: str) -> BeautifulSoup:
    fixture_path = os.path.join(os.path.dirname(__file__), 'fixtures', filename + '.html')
    with open(fixture_path) as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
    return soup
