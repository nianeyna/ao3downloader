"""Tests for ao3downloader.update — process_file across all supported formats."""

import os
import shutil
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch

import pytest

from ao3downloader import update


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


# region EPUB

def test_process_file_epub_incomplete_work(snapshot):
    path = os.path.join(FIXTURES_DIR, 'incompleteWork.epub')
    assert update.process_file(path, 'EPUB') == snapshot


def test_process_file_epub_complete_work():
    path = os.path.join(FIXTURES_DIR, 'epubTest.epub')
    assert update.process_file(path, 'EPUB') is None


def test_process_file_epub_work_in_series_returns_series():
    path = os.path.join(FIXTURES_DIR, 'workInSeries.epub')

    result = update.process_file(path, 'EPUB', update_series=True)

    assert result is not None
    assert 'link' in result
    assert 'archiveofourown.org/works/' in result['link']
    assert result['series']
    assert all('archiveofourown.org/series/' in s for s in result['series'])


def test_get_epub_preface(snapshot):
    path = os.path.join(FIXTURES_DIR, 'epubTest.epub')
    xml = update.get_epub_preface(path)
    assert ET.tostring(xml, encoding='unicode') == snapshot


def test_get_epub_preface_returns_none_on_bad_zip(tmp_path):
    bogus = tmp_path / 'not-a-zip.epub'
    bogus.write_bytes(b'not a zip file')

    assert update.get_epub_preface(str(bogus)) is None


def test_get_epub_preface_returns_none_on_missing_file(tmp_path):
    assert update.get_epub_preface(str(tmp_path / 'missing.epub')) is None


def test_get_epub_preface_returns_none_when_preface_path_missing(tmp_path):
    # minimal epub-like zip with content.opf but no xhtml item in manifest
    zp = tmp_path / 'no_preface.epub'
    with zipfile.ZipFile(zp, 'w') as zf:
        zf.writestr(
            'content.opf',
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            '<item id="css" href="style.css" media-type="text/css"/>'
            '</manifest></package>'
        )

    assert update.get_epub_preface(str(zp)) is None

# endregion


# region HTML

def test_process_file_html_complete_work():
    path = os.path.join(FIXTURES_DIR, 'htmlTest.html')
    assert update.process_file(path, 'HTML') is None


def test_process_file_html_incomplete_work(snapshot):
    path = os.path.join(FIXTURES_DIR, 'incompleteWork.html')
    assert update.process_file(path, 'HTML') == snapshot


def test_process_file_html_update_false_returns_link():
    path = os.path.join(FIXTURES_DIR, 'htmlTest.html')

    result = update.process_file(path, 'HTML', update=False)

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']


def test_process_file_html_work_in_series_returns_series():
    path = os.path.join(FIXTURES_DIR, 'workInSeries.html')

    result = update.process_file(path, 'HTML', update_series=True)

    assert result is not None
    assert result['series']
    assert all('archiveofourown.org/series/' in s for s in result['series'])


def test_process_file_html_update_series_returns_none_for_solo_work():
    path = os.path.join(FIXTURES_DIR, 'htmlTest.html')
    # solo work, update_series=True, no series found → None
    assert update.process_file(path, 'HTML', update_series=True) is None

# endregion


# region MOBI

def test_process_file_mobi_complete_work_returns_none():
    path = os.path.join(FIXTURES_DIR, 'mobiTest.mobi')
    assert update.process_file(path, 'MOBI') is None


def test_process_file_mobi_incomplete_work(snapshot):
    path = os.path.join(FIXTURES_DIR, 'incompleteWork.mobi')
    assert update.process_file(path, 'MOBI') == snapshot


def test_process_file_mobi_update_false_returns_link():
    path = os.path.join(FIXTURES_DIR, 'mobiTest.mobi')

    result = update.process_file(path, 'MOBI', update=False)

    assert result is not None
    assert 'archiveofourown.org/works/' in result['link']


def test_process_file_mobi_work_in_series_returns_series():
    path = os.path.join(FIXTURES_DIR, 'workInSeries.mobi')

    result = update.process_file(path, 'MOBI', update_series=True)

    assert result is not None
    assert result['series']
    assert all('archiveofourown.org/series/' in s for s in result['series'])


def test_process_file_mobi_returns_none_when_extracted_file_not_html(monkeypatch, tmp_path):
    extract_dir = tmp_path / 'extracted'
    extract_dir.mkdir()
    not_html = extract_dir / 'book.pdf'
    not_html.write_bytes(b'')

    monkeypatch.setattr('ao3downloader.update.mobi.extract',
                        lambda path: (str(extract_dir), str(not_html)))

    assert update.process_file('whatever.mobi', 'MOBI') is None
    assert not extract_dir.exists()

# endregion


# region AZW3

def test_process_file_azw3_delegates_to_epub_parser(monkeypatch, tmp_path):
    # use the real epub fixture as the "extracted" file
    extract_dir = tmp_path / 'extracted'
    extract_dir.mkdir()
    extracted_epub = extract_dir / 'book.epub'
    shutil.copyfile(os.path.join(FIXTURES_DIR, 'incompleteWork.epub'), extracted_epub)

    monkeypatch.setattr('ao3downloader.update.mobi.extract',
                        lambda path: (str(extract_dir), str(extracted_epub)))

    result = update.process_file('whatever.azw3', 'AZW3')

    # incompleteWork.epub should yield a dict with 'link' and 'chapters'
    assert result is not None
    assert 'link' in result
    # finally cleanup
    assert not extract_dir.exists()


def test_process_file_azw3_returns_none_when_extracted_file_not_epub(monkeypatch, tmp_path):
    extract_dir = tmp_path / 'extracted'
    extract_dir.mkdir()
    not_epub = extract_dir / 'book.mobi'
    not_epub.write_bytes(b'')

    monkeypatch.setattr('ao3downloader.update.mobi.extract',
                        lambda path: (str(extract_dir), str(not_epub)))

    assert update.process_file('whatever.azw3', 'AZW3') is None
    assert not extract_dir.exists()

# endregion


# region PDF

def test_process_file_pdf_complete_work_returns_none():
    path = os.path.join(FIXTURES_DIR, 'pdfTest.pdf')
    assert update.process_file(path, 'PDF') is None


def test_process_file_pdf_incomplete_work(snapshot):
    path = os.path.join(FIXTURES_DIR, 'incompleteWork.pdf')
    assert update.process_file(path, 'PDF') == snapshot


def test_process_file_pdf_update_false_returns_link():
    path = os.path.join(FIXTURES_DIR, 'pdfTest.pdf')

    result = update.process_file(path, 'PDF', update=False)

    assert result == {'link': 'https://archiveofourown.org/works/23009290'}


def test_process_file_pdf_work_in_series_returns_series():
    path = os.path.join(FIXTURES_DIR, 'workInSeries.pdf')

    result = update.process_file(path, 'PDF', update_series=True)

    assert result is not None
    assert result['series']
    assert all('archiveofourown.org/series/' in s for s in result['series'])

# endregion


# region invalid filetype

def test_process_file_invalid_filetype_raises_valueerror(tmp_path):
    with pytest.raises(ValueError):
        update.process_file(str(tmp_path / 'x'), 'RTF')

# endregion
