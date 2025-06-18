import xml.etree.ElementTree as ET

from ao3downloader import update


def test_process_file_epub_incomplete_work(snapshot):
    path = 'test/fixtures/incompleteWork.epub'
    result = update.process_file(path, 'EPUB')
    assert result == snapshot


def test_process_file_epub_complete_work():
    path = 'test/fixtures/epubTest.epub'
    result = update.process_file(path, 'EPUB')
    assert result == None


def test_get_epub_preface(snapshot):
    path = 'test/fixtures/epubTest.epub'
    xml = update.get_epub_preface(path)
    result = ET.tostring(xml, encoding='unicode')
    assert result == snapshot
