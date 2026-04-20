"""Tests for ao3downloader.parse_xml — pinboard bookmarks and epub preface parsing."""

import os
import xml.etree.ElementTree as ET
import zipfile

import pytest

from ao3downloader import parse_xml

from test.conftest import ebook_fixtures


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
PINBOARD_PATH = os.path.join(FIXTURES_DIR, 'pinboard.xml')

OPF_NS = '{http://www.idpf.org/2007/opf}'
XHTML_NS = '{http://www.w3.org/1999/xhtml}'


def _load_epub_preface(epub_path: str) -> ET.Element:
    """Extract the preface XHTML element tree from a real AO3 epub."""
    with zipfile.ZipFile(epub_path) as zf:
        with zf.open('content.opf') as of:
            opf = ET.parse(of).getroot()
        preface_path = parse_xml.get_preface_path_epub(opf)
        with zf.open(preface_path) as pf:
            return ET.parse(pf).getroot()


def _ids(paths):
    return [os.path.basename(p) for p in paths]


# region get_bookmark_list

def _load_pinboard_root() -> ET.Element:
    return ET.parse(PINBOARD_PATH).getroot()


def test_get_bookmark_list_includes_ao3_works_and_series_when_exclude_toread_false():
    root = _load_pinboard_root()

    bookmarks = parse_xml.get_bookmark_list(root, exclude_toread=False)
    hrefs = [b['href'] for b in bookmarks]

    assert 'https://archiveofourown.org/works/111' in hrefs
    assert 'https://archiveofourown.org/works/222' in hrefs
    assert 'https://archiveofourown.org/series/333' in hrefs
    assert 'https://archiveofourown.org/works/444' in hrefs


def test_get_bookmark_list_excludes_non_ao3_hosts():
    root = _load_pinboard_root()

    bookmarks = parse_xml.get_bookmark_list(root, exclude_toread=False)
    hrefs = [b['href'] for b in bookmarks]

    assert 'https://fanfiction.net/s/123/1/Fic' not in hrefs


def test_get_bookmark_list_excludes_ao3_urls_that_are_not_work_or_series():
    root = _load_pinboard_root()

    bookmarks = parse_xml.get_bookmark_list(root, exclude_toread=False)
    hrefs = [b['href'] for b in bookmarks]

    assert 'https://archiveofourown.org/users/someuser' not in hrefs


def test_get_bookmark_list_excludes_toread_when_flag_true():
    root = _load_pinboard_root()

    bookmarks = parse_xml.get_bookmark_list(root, exclude_toread=True)
    hrefs = [b['href'] for b in bookmarks]

    assert 'https://archiveofourown.org/works/111' in hrefs
    assert 'https://archiveofourown.org/series/333' in hrefs
    # toread="yes" entries are excluded
    assert 'https://archiveofourown.org/works/222' not in hrefs
    assert 'https://archiveofourown.org/works/444' not in hrefs


def test_get_bookmark_list_includes_toread_when_flag_false():
    root = _load_pinboard_root()

    bookmarks = parse_xml.get_bookmark_list(root, exclude_toread=False)
    hrefs = [b['href'] for b in bookmarks]

    assert 'https://archiveofourown.org/works/222' in hrefs
    assert 'https://archiveofourown.org/works/444' in hrefs

# endregion


# region get_preface_path_epub

def _opf_xml(items_xml: str) -> ET.Element:
    """Minimal OPF skeleton wrapping the given <item> xml."""
    return ET.XML(
        '<package xmlns="http://www.idpf.org/2007/opf">'
        '<manifest>' + items_xml + '</manifest>'
        '</package>'
    )


def test_get_preface_path_epub_returns_first_xhtml_item():
    xml = _opf_xml(
        '<item id="css" href="style.css" media-type="text/css"/>'
        '<item id="preface" href="preface.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>'
    )

    assert parse_xml.get_preface_path_epub(xml) == 'preface.xhtml'


def test_get_preface_path_epub_returns_none_when_manifest_missing():
    xml = ET.XML('<package xmlns="http://www.idpf.org/2007/opf"></package>')

    assert parse_xml.get_preface_path_epub(xml) is None


def test_get_preface_path_epub_returns_none_when_no_xhtml_items():
    xml = _opf_xml(
        '<item id="css" href="style.css" media-type="text/css"/>'
    )

    assert parse_xml.get_preface_path_epub(xml) is None


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.epub'),
                         ids=_ids(ebook_fixtures('23009290', '.epub')))
def test_get_preface_path_epub_on_real_fixture(path):
    with zipfile.ZipFile(path) as zf:
        opf_name = next(n for n in zf.namelist() if n.endswith('.opf'))
        with zf.open(opf_name) as f:
            opf_xml = ET.parse(f).getroot()

    preface = parse_xml.get_preface_path_epub(opf_xml)
    assert preface is not None
    assert preface.endswith('.xhtml') or preface.endswith('.html')

# endregion


# region get_work_link_epub

@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.epub'),
                         ids=_ids(ebook_fixtures('23009290', '.epub')))
def test_get_work_link_epub_on_real_fixture(path):
    preface = _load_epub_preface(path)
    link = parse_xml.get_work_link_epub(preface)

    assert link is not None
    assert 'archiveofourown.org/works/' in link


def test_get_work_link_epub_returns_none_when_no_ao3_link():
    xml = ET.XML(
        '<body xmlns="http://www.w3.org/1999/xhtml">'
        '<a href="https://example.com/foo">link</a>'
        '</body>'
    )

    assert parse_xml.get_work_link_epub(xml) is None


def test_get_work_link_epub_returns_first_match():
    xml = ET.XML(
        '<body xmlns="http://www.w3.org/1999/xhtml">'
        '<a href="https://archiveofourown.org/works/111">first</a>'
        '<a href="https://archiveofourown.org/works/222">second</a>'
        '</body>'
    )

    assert parse_xml.get_work_link_epub(xml) == 'https://archiveofourown.org/works/111'

# endregion


# region get_stats_epub

@pytest.mark.parametrize('path', ebook_fixtures('218676', '.epub'),
                         ids=_ids(ebook_fixtures('218676', '.epub')))
def test_get_stats_epub_on_real_fixture(path):
    preface = _load_epub_preface(path)
    stats = parse_xml.get_stats_epub(preface)

    assert stats is not None
    assert 'Chapters:' in stats


def test_get_stats_epub_returns_none_when_missing():
    xml = ET.XML(
        '<body xmlns="http://www.w3.org/1999/xhtml">'
        '<dl><dd class="other">irrelevant</dd></dl>'
        '</body>'
    )

    assert parse_xml.get_stats_epub(xml) is None

# endregion


# region get_series_epub

@pytest.mark.parametrize('path', ebook_fixtures('334557', '.epub'),
                         ids=_ids(ebook_fixtures('334557', '.epub')))
def test_get_series_epub_returns_series_from_work_in_series(path):
    preface = _load_epub_preface(path)
    series = parse_xml.get_series_epub(preface)

    assert series
    assert all('archiveofourown.org/series/' in s for s in series)


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.epub'),
                         ids=_ids(ebook_fixtures('23009290', '.epub')))
def test_get_series_epub_returns_empty_on_work_with_no_series(path):
    preface = _load_epub_preface(path)
    assert parse_xml.get_series_epub(preface) == []


def test_get_series_epub_returns_empty_list_on_minimal_xml():
    xml = ET.XML(
        '<body xmlns="http://www.w3.org/1999/xhtml">'
        '<a href="https://archiveofourown.org/works/111">work</a>'
        '</body>'
    )

    assert parse_xml.get_series_epub(xml) == []

# endregion
