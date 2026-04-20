"""Tests for ao3downloader.parse_pdf — PDF metadata extraction."""

import os
from unittest.mock import MagicMock

import pdfquery
import pytest

from ao3downloader import parse_pdf


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _load_pdf(name: str) -> pdfquery.PDFQuery:
    pdf = pdfquery.PDFQuery(os.path.join(FIXTURES_DIR, name))
    try:
        pdf.load(0, 1, 2)
    except StopIteration:
        pdf.load()
    return pdf


@pytest.fixture(scope='module')
def real_pdf() -> pdfquery.PDFQuery:
    return _load_pdf('pdfTest.pdf')


@pytest.fixture(scope='module')
def tag_wall_pdf() -> pdfquery.PDFQuery:
    return _load_pdf('tagWall.pdf')


@pytest.fixture(scope='module')
def work_in_series_pdf() -> pdfquery.PDFQuery:
    return _load_pdf('workInSeries.pdf')


def _fake_pdf(text_by_selector: dict) -> MagicMock:
    """Build a MagicMock PDFQuery whose `.pq(selector).text()` returns canned strings."""
    pdf = MagicMock()

    def _pq(selector):
        node = MagicMock()
        text = text_by_selector.get(selector, '')
        node.text.return_value = text
        node.strip = lambda: text.strip()
        # default next() returns empty
        nxt = MagicMock()
        nxt.text.return_value = ''
        node.next.return_value = nxt
        return node

    pdf.pq.side_effect = _pq
    return pdf


# region get_work_link_pdf

def test_get_work_link_pdf_extracts_url_from_real_fixture(real_pdf):
    assert parse_pdf.get_work_link_pdf(real_pdf) == 'https://archiveofourown.org/works/23009290'


def test_get_work_link_pdf_returns_none_when_marker_text_missing():
    pdf = _fake_pdf({})  # all selectors return empty text

    assert parse_pdf.get_work_link_pdf(pdf) is None

# endregion


# region get_stats_pdf

def test_get_stats_pdf_returns_chapters_when_on_same_line(real_pdf):
    assert parse_pdf.get_stats_pdf(real_pdf) == 'Published: 2020-03-04 Words: 4,559 Chapters: 1/1'


def test_get_stats_pdf_appends_next_line_for_multi_line_stats(tag_wall_pdf):
    result = parse_pdf.get_stats_pdf(tag_wall_pdf)

    assert result is not None
    assert 'Chapters:' in result
    assert '/' in result


def test_get_stats_pdf_inserts_space_after_colon_when_missing():
    pdf = MagicMock()
    node = MagicMock()
    node.text.return_value = 'Chapters:'
    nxt = MagicMock()
    nxt.text.return_value = '3/10'
    node.next.return_value = nxt
    pdf.pq.return_value = node

    result = parse_pdf.get_stats_pdf(pdf)

    assert result == 'Chapters: 3/10'


def test_get_stats_pdf_returns_none_when_text_empty():
    pdf = MagicMock()
    node = MagicMock()
    node.text.return_value = ''
    pdf.pq.return_value = node

    assert parse_pdf.get_stats_pdf(pdf) is None

# endregion


# region get_series_pdf

def test_get_series_pdf_returns_empty_when_no_series(real_pdf):
    assert parse_pdf.get_series_pdf(real_pdf) == []


def test_get_series_pdf_returns_series_from_work_in_series(work_in_series_pdf):
    series = parse_pdf.get_series_pdf(work_in_series_pdf)

    assert series
    assert all('archiveofourown.org/series/' in s for s in series)


def test_get_series_pdf_filters_non_series_annotations():
    """Guard against partial URIs: only /series/ links should pass the filter."""
    pdf = MagicMock()
    annots = [
        MagicMock(attrib={'URI': 'https://archiveofourown.org/works/111'}),
        MagicMock(attrib={'URI': 'https://archiveofourown.org/series/222'}),
        MagicMock(attrib={}),  # no URI
        MagicMock(attrib={'URI': 'https://example.com/unrelated'}),
    ]
    pdf.pq.return_value = annots

    assert parse_pdf.get_series_pdf(pdf) == ['https://archiveofourown.org/series/222']

# endregion
