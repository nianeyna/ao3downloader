"""Tests for ao3downloader.ao3.Ao3 class."""

import os
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from source_code import exceptions, indexing, parse_soup, parse_text, strings
from source_code.ao3 import Ao3, was_bookmark
from source_code.fileio import FileOps
from source_code.repo import Repository
from source_code.storage import LocalStorage


WORK_URL = 'https://archiveofourown.org/works/123'
SERIES_URL = 'https://archiveofourown.org/series/456'
LISTING_URL = 'https://archiveofourown.org/users/test/bookmarks'


def make_ao3(
    filetypes: list[str] | None = None,
    pages: int = 0,
    series: bool = False,
    images: bool = False,
    mark: bool = False,
    debug: bool = False,
    start: int = 1,
) -> tuple[Ao3, MagicMock, MagicMock]:
    """Create an Ao3 instance with mocked dependencies.
    Returns (ao3, repo_mock, fileops_mock)."""
    repo = MagicMock(spec=Repository)
    fileops = MagicMock(spec=FileOps)
    # a real local folder underneath, for the tests that call FileOps' own methods on this
    fileops.storage = LocalStorage('downloads')
    fileops.get_ini_value_boolean.return_value = debug
    fileops.get_ini_value.return_value = strings.FILE_NAME_PATTERN
    fileops.get_ini_value_integer.return_value = strings.INI_DEFAULT_NAME_LENGTH
    # no index on disk yet, unless a test says otherwise
    fileops.load_json.return_value = None
    ao3 = Ao3(repo=repo, fileops=fileops, filetypes=filetypes or ['EPUB'],
              pages=pages, series=series, images=images, mark=mark, start=start)
    return ao3, repo, fileops


def get_soup_from_fixture(filename: str) -> BeautifulSoup:
    fixture_path = os.path.join(os.path.dirname(__file__), 'fixtures', filename + '.html')
    with open(fixture_path, encoding='utf-8') as f:
        return BeautifulSoup(f.read(), 'html.parser')


@contextmanager
def try_download_patches() -> Iterator[None]:
    """Patches proceed() and parse functions for try_download's main flow."""
    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_title', return_value=['My Work']), \
         patch('source_code.parse_soup.get_updated_date', return_value='14 Dec 2024'), \
         patch('source_code.parse_soup.get_download_link', return_value='https://ao3.org/dl/work.epub'), \
         patch('source_code.parse_soup.has_custom_skin', return_value=False), \
         patch('source_code.parse_soup.get_work_metadata_from_work', return_value={}), \
         patch('source_code.naming.file_stem', return_value='My Work'), \
         patch('source_code.parse_text.get_file_type', return_value='.epub'):
        yield


# region proceed() — locked/deleted/explicit gate
# Uses real fixture HTML to test the integration with parse_soup.

def test_proceed_locked_raises() -> None:
    ao3, _, _ = make_ao3()
    soup = get_soup_from_fixture('lockedWorkLoggedOut')
    with pytest.raises(exceptions.LockedException, match=strings.ERROR_LOCKED):
        ao3.proceed(soup)


def test_proceed_deleted_raises() -> None:
    ao3, _, _ = make_ao3()
    soup = get_soup_from_fixture('deletedWork')
    with pytest.raises(exceptions.DeletedException, match=strings.ERROR_DELETED):
        ao3.proceed(soup)


def test_proceed_hidden_raises() -> None:
    ao3, _, _ = make_ao3()
    soup = get_soup_from_fixture('hiddenWork')
    with pytest.raises(exceptions.HiddenException, match=strings.ERROR_HIDDEN):
        ao3.proceed(soup)


def test_proceed_explicit_follows_proceed_link() -> None:
    ao3, repo, _ = make_ao3()
    soup = get_soup_from_fixture('explicitWorkLoggedOut')
    new_soup = MagicMock()
    repo.get_soup.return_value = new_soup

    result = ao3.proceed(soup)

    repo.get_soup.assert_called_once_with('https://archiveofourown.org/works/35369560?view_adult=true')
    assert result is new_soup


def test_proceed_normal_returns_soup_unchanged() -> None:
    ao3, repo, _ = make_ao3()
    soup = get_soup_from_fixture('unlockedWork')

    result = ao3.proceed(soup)

    assert result is soup
    repo.get_soup.assert_not_called()


def test_proceed_locked_checked_before_deleted() -> None:
    """If both conditions match, locked takes priority over deleted."""
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_soup.is_locked', return_value=True), \
         patch('source_code.parse_soup.is_deleted', return_value=True):
        with pytest.raises(exceptions.LockedException):
            ao3.proceed(MagicMock())

# endregion

# region try_download() — core download logic

def test_try_download_happy_path() -> None:
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.get_book.return_value = b'epub content'

    with try_download_patches():
        log: dict[str, object] = {}
        result = ao3.try_download(WORK_URL, log, None)

    assert result is True
    # into works/, never the library's top level
    fileops.save_bytes.assert_called_once_with(
        os.path.join(strings.WORKS_FOLDER_NAME, 'My Work.epub'), b'epub content')
    assert log['title'] == ['My Work']
    assert log['workskin'] is False


def test_try_download_multiple_filetypes() -> None:
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF'])
    repo.get_book.return_value = b'content'

    with try_download_patches():
        with patch('source_code.parse_text.get_file_type', side_effect=['.epub', '.pdf']):
            result = ao3.try_download(WORK_URL, {}, None)

    assert result is True
    assert fileops.save_bytes.call_count == 2
    fileops.save_bytes.assert_any_call(
        os.path.join(strings.WORKS_FOLDER_NAME, 'My Work.epub'), b'content')
    fileops.save_bytes.assert_any_call(
        os.path.join(strings.WORKS_FOLDER_NAME, 'My Work.pdf'), b'content')


def test_try_download_chapters_no_update() -> None:
    """Current chapters == given chapters: no update needed, returns False."""
    ao3, _, fileops = make_ao3()

    with try_download_patches():
        with patch('source_code.parse_soup.get_current_chapters', return_value='5'):
            log: dict[str, object] = {}
            result = ao3.try_download(WORK_URL, log, '5')

    assert result is False
    fileops.save_bytes.assert_not_called()
    assert 'title' not in log  # returned before title was set


def test_try_download_chapters_fewer_than_given() -> None:
    """Current=3, given=5: still no update (3 <= 5)."""
    ao3, _, fileops = make_ao3()

    with try_download_patches():
        with patch('source_code.parse_soup.get_current_chapters', return_value='3'):
            result = ao3.try_download(WORK_URL, {}, '5')

    assert result is False
    fileops.save_bytes.assert_not_called()


def test_try_download_chapters_update_available() -> None:
    """Current=10, given=5: update available (10 > 5), downloads proceed."""
    ao3, repo, fileops = make_ao3()
    repo.get_book.return_value = b'content'

    with try_download_patches():
        with patch('source_code.parse_soup.get_current_chapters', return_value='10'):
            result = ao3.try_download(WORK_URL, {}, '5')

    assert result is True
    fileops.save_bytes.assert_called_once()


def test_try_download_images() -> None:
    ao3, repo, fileops = make_ao3(images=True)
    repo.get_book.side_effect = [b'epub', b'img1data', b'img2data']

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links',
                   return_value=['https://example.com/img1.png', 'https://example.com/img2.jpg']):
            ao3.try_download(WORK_URL, {}, None)

    assert fileops.save_bytes.call_count == 3  # work file + 2 images
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img000.png'), b'img1data')
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img001.jpg'), b'img2data')


def test_try_download_image_error_does_not_abort() -> None:
    """A failed image download is logged but doesn't stop remaining images."""
    ao3, repo, fileops = make_ao3(images=True)
    # First call: epub download. Second: img1 fails. Third: img2 succeeds.
    repo.get_book.side_effect = [b'epub', Exception('network error'), b'img2data']

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links',
                   return_value=['https://example.com/img1.png', 'https://example.com/img2.jpg']):
            result = ao3.try_download(WORK_URL, {}, None)

    assert result is True
    # img2 saved with counter=0 because img1's failure didn't increment counter
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img000.jpg'), b'img2data')
    # Error logged for the failed image
    error_log_calls = [c for c in fileops.write_log.call_args_list
                       if c[0][0].get('message') == strings.ERROR_IMAGE]
    assert len(error_log_calls) == 1


def test_try_download_image_relative_url_skipped() -> None:
    """A relative URL (starting with /) is skipped but remaining images are still downloaded."""
    ao3, repo, fileops = make_ao3(images=True)
    repo.get_book.side_effect = [b'epub', b'img1data', b'img3data']

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links',
                   return_value=['https://example.com/img1.png',
                                 '/relative/path.png',
                                 'https://example.com/img3.png']):
            ao3.try_download(WORK_URL, {}, None)

    # epub + img1 + img3; the relative URL is skipped
    assert repo.get_book.call_count == 3
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img000.png'), b'img1data')
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img001.png'), b'img3data')


def test_try_download_image_url_query_params_stripped() -> None:
    """Query params in image URL don't pollute the file extension."""
    ao3, repo, fileops = make_ao3(images=True)
    repo.get_book.side_effect = [b'epub', b'imgdata']

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links',
                   return_value=['https://example.com/img.png?token=abc123']):
            ao3.try_download(WORK_URL, {}, None)

    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img000.png'), b'imgdata')


def test_try_download_mark_as_read() -> None:
    ao3, repo, _ = make_ao3(mark=True)
    repo.get_book.return_value = b'content'
    soup = MagicMock()
    repo.get_soup.return_value = soup

    with try_download_patches():
        ao3.try_download(WORK_URL, {}, None)

    repo.mark_work_as_read.assert_called_once_with(soup, WORK_URL)


def test_try_download_mark_not_called_when_disabled() -> None:
    ao3, repo, _ = make_ao3(mark=False)
    repo.get_book.return_value = b'content'

    with try_download_patches():
        ao3.try_download(WORK_URL, {}, None)

    repo.mark_work_as_read.assert_not_called()


def test_try_download_images_not_fetched_when_disabled() -> None:
    ao3, repo, _ = make_ao3(images=False)
    repo.get_book.return_value = b'content'

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links') as mock_img:
            ao3.try_download(WORK_URL, {}, None)

    mock_img.assert_not_called()

# endregion

# region download_work() — try/except/else control flow
# The else block only runs when try completes without exception
# AND without a return statement.

def test_download_work_success_logs() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'try_download', return_value=True):
        log: dict[str, object] = {}
        ao3.download_work(WORK_URL, log, None)

    assert log['link'] == WORK_URL
    assert log['success'] is True
    fileops.write_log.assert_called_once_with(log)


def test_download_work_no_update_does_not_log() -> None:
    """When try_download returns False, the early return skips both
    the else block (success log) and the except block. No log at all."""
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'try_download', return_value=False):
        ao3.download_work(WORK_URL, {}, '5')

    fileops.write_log.assert_not_called()


def test_download_work_exception_logs_error() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'try_download', side_effect=exceptions.DeletedException('Deleted')):
        log: dict[str, object] = {}
        ao3.download_work(WORK_URL, log, None)

    assert log['success'] is False
    assert log['error'] == 'Deleted'
    fileops.write_log.assert_called_once()


def test_download_work_generic_exception_includes_stacktrace() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'try_download', side_effect=ValueError('unexpected')):
        log: dict[str, object] = {}
        ao3.download_work(WORK_URL, log, None)

    assert 'stacktrace' in log
    assert 'ValueError' in str(log['stacktrace'])


def test_download_work_ao3_exception_no_stacktrace() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'try_download', side_effect=exceptions.LockedException('Locked')):
        log: dict[str, object] = {}
        ao3.download_work(WORK_URL, log, None)

    assert 'stacktrace' not in log

# endregion

# region log_error() — stacktrace inclusion

def test_log_error_ao3_exception_no_stacktrace() -> None:
    ao3, _, fileops = make_ao3()
    log: dict[str, object] = {}
    ao3.log_error(log, exceptions.LockedException('test'))

    assert log == {'error': 'test', 'success': False}
    fileops.write_log.assert_called_once_with(log)


def test_log_error_generic_exception_includes_stacktrace() -> None:
    ao3, _, _ = make_ao3()
    log: dict[str, object] = {}
    try:
        raise ValueError('boom')
    except ValueError as e:
        ao3.log_error(log, e)

    assert log['error'] == 'boom'
    assert log['success'] is False
    assert 'ValueError' in str(log['stacktrace'])
    assert 'boom' in str(log['stacktrace'])


def test_log_error_preserves_existing_log_keys() -> None:
    ao3, _, _ = make_ao3()
    log: dict[str, object] = {'link': WORK_URL, 'title': ['My Work']}
    ao3.log_error(log, exceptions.DeletedException('gone'))

    assert log['link'] == WORK_URL
    assert log['title'] == ['My Work']
    assert log['error'] == 'gone'
    assert log['success'] is False

# endregion

# region download_recursive() — dispatch and deduplication

def test_download_recursive_work_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work', return_value=True), \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(WORK_URL, {}, [])

    assert mock_dl.call_args is not None
    args = mock_dl.call_args[0]
    assert args[0] == WORK_URL
    assert args[2] is None  # chapters


def test_download_recursive_series_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work', return_value=False), \
         patch('source_code.parse_text.is_series', return_value=True), \
         patch.object(Ao3, 'download_series') as mock_ds:
        ao3.download_recursive(SERIES_URL, {}, [])

    assert mock_ds.call_args is not None
    args = mock_ds.call_args[0]
    assert args[0] == SERIES_URL


def test_download_recursive_already_visited() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work') as mock_is_work:
        ao3.download_recursive(WORK_URL, {}, [WORK_URL])

    mock_is_work.assert_not_called()


def test_download_recursive_adds_to_visited() -> None:
    ao3, _, _ = make_ao3()
    visited: list[str] = []
    with patch('source_code.parse_text.is_work', return_value=True), \
         patch.object(Ao3, 'download_work'):
        ao3.download_recursive(WORK_URL, {}, visited)

    assert WORK_URL in visited


def test_download_recursive_invalid_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work', return_value=False), \
         patch('source_code.parse_text.is_series', return_value=False):
        with pytest.raises(exceptions.InvalidLinkException):
            ao3.download_recursive('https://example.com/fic/123', {}, [])


def test_download_recursive_listing_paginates() -> None:
    ao3, repo, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = LISTING_URL + '?page=2'

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', return_value=2), \
         patch('source_code.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_page_number', side_effect=[1, 2, 2]), \
         patch('source_code.parse_text.get_next_page', return_value=page2), \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(LISTING_URL, {}, [])

    assert mock_dl.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_recursive_listing_respects_page_limit() -> None:
    ao3, repo, _ = make_ao3(pages=2)
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = LISTING_URL + '?page=2'
    page3 = LISTING_URL + '?page=3'

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', return_value=5), \
         patch('source_code.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_page_number', side_effect=[1, 2, 2, 3]), \
         patch('source_code.parse_text.get_next_page', side_effect=[page2, page3]), \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(LISTING_URL, {}, [])

    assert mock_dl.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_recursive_mark_mode_refetches_same_url() -> None:
    """In mark mode, the same URL is re-fetched each iteration (no page increment).
    Breaks when total_pages drops to <= 1 (works disappear after being marked read)."""
    ao3, repo, _ = make_ao3(mark=True)
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    soup1 = MagicMock()
    soup2 = MagicMock()
    repo.get_soup.side_effect = [soup1, soup2]

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', side_effect=lambda s: 2 if s is soup1 else 1), \
         patch('source_code.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_next_page') as mock_next, \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(LISTING_URL, {}, [])

    mock_next.assert_not_called()
    assert mock_dl.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_recursive_mark_mode_breaks_on_none() -> None:
    """Mark mode also breaks when total_pages is None."""
    ao3, repo, _ = make_ao3(mark=True)
    work1 = 'https://archiveofourown.org/works/111'

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', return_value=None), \
         patch('source_code.parse_soup.get_work_and_series_urls', return_value=[work1]), \
         patch.object(Ao3, 'download_work'):
        ao3.download_recursive(LISTING_URL, {}, [])

    assert repo.get_soup.call_count == 1

# endregion

# region download_series()

def test_download_series_single_page() -> None:
    ao3, _, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_total_pages', return_value=None), \
         patch('source_code.parse_soup.get_work_urls', return_value=[work1, work2]), \
         patch('source_code.parse_text.get_page_number', return_value=1), \
         patch.object(Ao3, 'download_recursive') as mock_dr:
        ao3.download_series(SERIES_URL, {}, [])

    assert mock_dr.call_count == 2


def test_download_series_multi_page() -> None:
    ao3, repo, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = SERIES_URL + '?page=2'

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_total_pages', return_value=2), \
         patch('source_code.parse_soup.get_work_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_page_number', side_effect=[1, 2]), \
         patch('source_code.parse_text.get_next_page', return_value=page2), \
         patch.object(Ao3, 'download_recursive') as mock_dr:
        ao3.download_series(SERIES_URL, {}, [])

    assert mock_dr.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_series_calls_proceed() -> None:
    ao3, _, _ = make_ao3()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup) as mock_proceed, \
         patch('source_code.parse_soup.get_total_pages', return_value=None), \
         patch('source_code.parse_soup.get_work_urls', return_value=[]), \
         patch('source_code.parse_text.get_page_number', return_value=1):
        ao3.download_series(SERIES_URL, {}, [])

    mock_proceed.assert_called_once()


def test_download_series_exception_logs_with_series_link() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.side_effect = Exception('network error')

    log: dict[str, object] = {}
    ao3.download_series(SERIES_URL, log, [])

    assert log['link'] == SERIES_URL
    assert log['success'] is False
    assert log['error'] == 'network error'

# endregion

# region Entry points — download(), update(), update_series()

def test_download_creates_visited_list() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'download_recursive') as mock_dr:
        ao3.download(WORK_URL)

    assert mock_dr.call_args is not None
    args = mock_dr.call_args[0]
    assert isinstance(args[2], list)


def test_download_catches_exception() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'download_recursive', side_effect=Exception('boom')):
        ao3.download(WORK_URL)

    fileops.write_log.assert_called_once()
    assert fileops.write_log.call_args is not None
    log = fileops.write_log.call_args[0][0]
    assert log['success'] is False


def test_update_passes_chapters() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'download_work') as mock_dw:
        ao3.update(WORK_URL, '5')

    assert mock_dw.call_args is not None
    args = mock_dw.call_args[0]
    assert args[0] == WORK_URL
    assert args[2] == '5'


def test_update_catches_exception() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'download_work', side_effect=Exception('boom')):
        ao3.update(WORK_URL, '5')

    fileops.write_log.assert_called_once()
    assert fileops.write_log.call_args is not None
    log = fileops.write_log.call_args[0][0]
    assert log['success'] is False


def test_update_series_delegates() -> None:
    ao3, _, _ = make_ao3()
    visited = ['already']
    with patch.object(Ao3, 'download_series') as mock_ds:
        ao3.update_series(SERIES_URL, visited)

    assert mock_ds.call_args is not None
    args = mock_ds.call_args[0]
    assert args[0] == SERIES_URL


def test_update_series_catches_exception() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'download_series', side_effect=Exception('boom')):
        ao3.update_series(SERIES_URL, [])

    fileops.write_log.assert_called_once()
    assert fileops.write_log.call_args is not None
    log = fileops.write_log.call_args[0][0]
    assert log['success'] is False

# endregion

# region get_work_links_recursive()

def test_get_work_links_returns_collected_links() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'get_work_links_recursive') as mock_rec:
        def populate_links(links_list: dict[str, object], *args: object) -> None:
            links_list[WORK_URL] = None
        mock_rec.side_effect = populate_links
        result = ao3.get_work_links(LISTING_URL, False)

    assert result == {WORK_URL: None}


def test_get_work_links_catches_exception() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'get_work_links_recursive', side_effect=Exception('boom')):
        result = ao3.get_work_links(LISTING_URL, False)

    assert result == {}  # returns empty dict on error
    fileops.write_log.assert_called_once()
    assert fileops.write_log.call_args is not None
    log = fileops.write_log.call_args[0][0]
    assert log['success'] is False
    assert log['message'] == strings.ERROR_LINKS_LIST


def test_get_work_links_recursive_listing_paginates() -> None:
    ao3, repo, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = LISTING_URL + '?page=2'
    links_list: dict[str, object] = {}

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', return_value=2), \
         patch('source_code.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_page_number', side_effect=[1, 2, 2]), \
         patch('source_code.parse_text.get_next_page', return_value=page2):
        ao3.get_work_links_recursive(links_list, LISTING_URL, [], False)

    assert work1 in links_list
    assert work2 in links_list
    assert repo.get_soup.call_count == 2


def test_get_work_links_work_with_metadata() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {}
    soup = MagicMock()
    metadata_dict = {'title': 'My Work', 'author': 'Author'}

    with patch('source_code.parse_text.is_work', return_value=True), \
         patch('source_code.parse_soup.get_work_metadata_from_list', return_value=metadata_dict):
        ao3.get_work_links_recursive(links_list, WORK_URL, [], True, soup)

    assert links_list[WORK_URL] == metadata_dict


def test_get_work_links_work_without_metadata() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {}

    with patch('source_code.parse_text.is_work', return_value=True):
        ao3.get_work_links_recursive(links_list, WORK_URL, [], False)

    assert WORK_URL in links_list
    assert links_list[WORK_URL] is None


def test_get_work_links_duplicate_work_skipped() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {WORK_URL: None}

    with patch('source_code.parse_text.is_work', return_value=True), \
         patch('source_code.parse_soup.get_work_metadata_from_list') as mock_meta:
        ao3.get_work_links_recursive(links_list, WORK_URL, [], True)

    mock_meta.assert_not_called()


def test_get_work_links_series_collects_works() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {}
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', side_effect=lambda url: '/series/' in url), \
         patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_total_pages', return_value=None), \
         patch('source_code.parse_soup.get_work_urls', return_value=[work1, work2]), \
         patch('source_code.parse_text.get_page_number', return_value=1):
        ao3.get_work_links_recursive(links_list, SERIES_URL, [], False)

    assert work1 in links_list
    assert work2 in links_list


def test_get_work_links_duplicate_series_skipped() -> None:
    ao3, repo, _ = make_ao3()
    visited_series = [SERIES_URL]

    with patch('source_code.parse_text.is_work', return_value=False), \
         patch('source_code.parse_text.is_series', return_value=True):
        ao3.get_work_links_recursive({}, SERIES_URL, visited_series, False)

    repo.get_soup.assert_not_called()


def test_get_work_links_invalid_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work', return_value=False), \
         patch('source_code.parse_text.is_series', return_value=False):
        with pytest.raises(exceptions.InvalidLinkException):
            ao3.get_work_links_recursive({}, 'https://example.com/fic', [], False)

# endregion

# region get_metadata() — json export

def _blurb_html(worknum: str, bookmark_id: str | None = None) -> str:
    return (
        f'<li id="bookmark_{bookmark_id or worknum}" class="bookmark blurb group work-{worknum} user-1">'
        f'<div class="header module">'
        f'<h4 class="heading"><a href="/works/{worknum}">Work {worknum}</a> by '
        f'<a href="/users/a/pseuds/a" rel="author">A</a></h4>'
        f'<p class="datetime">01 Jan 2020</p></div>'
        f'<div class="user module group"><p class="datetime">02 Feb 2021</p></div></li>')


def _listing_soup(worknums: list[str], total_pages: int = 1, extra: str = '') -> BeautifulSoup:
    """A real bookmarks listing page, so the crawl exercises the actual blurb parsing."""
    blurbs = ''.join(_blurb_html(n) for n in worknums)
    pagination = ''
    if total_pages > 1:
        items = ''.join(f'<li>{i}</li>' for i in range(1, total_pages + 1))
        pagination = f'<ol class="pagination actions">{items}</ol>'
    return BeautifulSoup(
        f'<ol class="bookmark index group">{blurbs}{extra}</ol>{pagination}', 'html.parser')


def _work_soup(published: str = '01 Jan 2019', status: str = '05 May 2021') -> BeautifulSoup:
    stats = f'<dd class="published">{published}</dd>'
    if status: stats += f'<dd class="status">{status}</dd>'
    return BeautifulSoup(f'<dl class="stats">{stats}</dl>', 'html.parser')


def test_get_metadata_rejects_a_single_work_link() -> None:
    ao3, repo, _ = make_ao3()

    with pytest.raises(exceptions.InvalidLinkException):
        ao3.get_metadata(WORK_URL, False)

    repo.get_soup.assert_not_called()


def test_get_metadata_rejects_a_non_ao3_link() -> None:
    ao3, repo, _ = make_ao3()

    with pytest.raises(exceptions.InvalidLinkException):
        ao3.get_metadata('https://example.com/fic', False)

    repo.get_soup.assert_not_called()


def test_get_metadata_collects_every_work_on_the_page() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222']
    assert records[0]['link'] == 'https://archiveofourown.org/works/111'
    assert records[0]['date_bookmarked'] == '02 Feb 2021'
    assert repo.get_soup.call_count == 1


def _indexed(*names: str) -> list[str]:
    """Where save_metadata puts json files: the indexing subfolder of downloads."""
    return sorted(os.path.join(strings.INDEXING_FOLDER_NAME, name) for name in names)


def _saved(fileops) -> dict[str, dict]:
    """Filename -> document, for everything save_json was called with."""
    return {call.args[0]: call.args[1] for call in fileops.save_json.call_args_list}


def test_get_metadata_writes_one_file_per_work() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    ao3.get_metadata(LISTING_URL, False)

    saved = _saved(fileops)
    assert sorted(saved) == _indexed('111 Work 111 - A.json', '222 Work 222 - A.json')
    assert saved[_indexed('111 Work 111 - A.json')[0]]['id'] == '111'


def test_get_metadata_puts_json_in_the_indexing_subfolder() -> None:
    # keeps the downloads folder to actual works, with the index beside rather than among
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'])

    ao3.get_metadata(LISTING_URL, False)

    written = list(_saved(fileops))[0]
    assert os.path.dirname(written) == strings.INDEXING_FOLDER_NAME
    # the file name itself is unchanged, so it still matches its downloaded work
    assert os.path.basename(written) == '111 Work 111 - A.json'


def test_get_metadata_adds_a_reading_when_the_fic_has_changed() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'])
    # what a previous run left behind, with a different kudos count
    fileops.load_json.return_value = {
        'id': '111',
        indexing.LAST_INDEXED: '2020-01-01T00:00:00+00:00',
        indexing.INDEXES: [{indexing.INDEXED_ON: '2020-01-01T00:00:00+00:00',
                            'title': 'Work 111', 'kudos': 1}],
    }

    ao3.get_metadata(LISTING_URL, False)

    written = list(_saved(fileops).values())[0]
    assert len(written[indexing.INDEXES]) == 2
    assert written[indexing.LAST_INDEXED] == ao3.indexed_on


def test_get_metadata_only_restamps_a_fic_that_has_not_changed() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'])

    # index once, then feed that exact result back as what is already on disk
    ao3.get_metadata(LISTING_URL, False)
    first = list(_saved(fileops).values())[0]
    fileops.load_json.return_value = first
    fileops.save_json.reset_mock()
    repo.get_soup.return_value = _listing_soup(['111'])

    ao3.get_metadata(LISTING_URL, False)

    written = list(_saved(fileops).values())[0]
    assert len(written[indexing.INDEXES]) == 1
    # checked again, so the file says so even though nothing was added
    assert written[indexing.LAST_INDEXED] == ao3.indexed_on


def test_get_metadata_names_files_the_one_fixed_way() -> None:
    # the naming is not a setting any more: the work number has to lead so files can be
    # matched to their index entry, so an ini value must not be able to move it
    ao3, repo, fileops = make_ao3()
    fileops.get_ini_value.return_value = '{title}'
    repo.get_soup.return_value = _listing_soup(['111'])

    ao3.get_metadata(LISTING_URL, False)

    assert list(_saved(fileops)) == _indexed('111 Work 111 - A.json')


# region downloading from the index rather than crawling again

def _record(work: str, title: str = 'A Fic', updated: str = '14 Dec 2024') -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'title': title, 'authors': ['library_of_alexandria'], 'date_updated': updated}


def test_downloading_from_the_index_never_reads_a_listing_or_a_work_page():
    # this is the whole point: the index already holds every work number, and the download
    # link is determined by that number, so neither page has to be fetched
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111'), _record('222')])

    repo.get_soup.assert_not_called()
    assert repo.download_file.call_count == 2


def test_downloading_from_the_index_goes_straight_to_the_download_host():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111')])

    url = repo.download_file.call_args.args[0]
    assert url == 'https://download.archiveofourown.org/downloads/111/fic.epub'


def test_downloading_from_the_index_names_files_the_usual_way():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'
    # room for the whole name: this is about the usual naming, not about shortening
    fileops.get_ini_value_integer.return_value = 100

    ao3.download_indexed([_record('111', title='The Trees Are Burning')])

    written = fileops.save_bytes.call_args.args[0]
    assert written == os.path.join(strings.WORKS_FOLDER_NAME,
                                   '111 The Trees Are Burning - library_of_alexandria 2024-12-14.epub')


def test_downloading_from_the_index_skips_what_is_already_downloaded():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111'), _record('222')],
                         visited=['https://archiveofourown.org/works/111'])

    assert repo.download_file.call_count == 1
    assert repo.download_file.call_args.args[0].endswith('/222/fic.epub')


def test_downloading_from_the_index_fetches_each_format_once():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF'])
    repo.download_file.return_value = b'bytes'

    ao3.download_indexed([_record('111')])

    requested = sorted(call.args[0] for call in repo.download_file.call_args_list)
    assert requested == [
        'https://download.archiveofourown.org/downloads/111/fic.epub',
        'https://download.archiveofourown.org/downloads/111/fic.pdf',
    ]


def test_downloading_from_the_index_records_what_a_later_run_needs():
    # without the title and the updated date in the log, the next run cannot rebuild this
    # name and would fetch everything again
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111')])

    logged = fileops.write_log.call_args.args[0]
    assert logged['title'] == ['111 A Fic - library_of_alexandria']
    assert logged['updated'] == '14 Dec 2024'
    assert logged['success'] is True


def test_downloading_from_the_index_replaces_the_copy_it_supersedes():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'
    fileops.save_bytes.return_value = r'C:\d\111 A Fic - library_of_alexandria 2024-12-14.epub'
    fileops.saved_intact.return_value = True
    fileops.delete_file.return_value = True
    ao3.superseded = {'https://archiveofourown.org/works/111':
                      {'EPUB': r'C:\d\111 A Fic - library_of_alexandria 2020-01-01.epub'}}

    ao3.download_indexed([_record('111')])

    fileops.delete_file.assert_called_once_with(r'C:\d\111 A Fic - library_of_alexandria 2020-01-01.epub')


def test_one_work_that_will_not_download_does_not_end_the_run():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.side_effect = [
        exceptions.DownloadException('gone'), b'epub bytes']

    ao3.download_indexed([_record('111'), _record('222')])

    assert fileops.save_bytes.call_count == 1
    fileops.write_log.assert_called()


def test_downloading_from_the_index_stops_when_asked_to():
    stopped = {'value': False}
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    ao3.cancelled = lambda: stopped['value']

    def fetch(*args):
        stopped['value'] = True
        return b'epub bytes'

    repo.download_file.side_effect = fetch

    ao3.download_indexed([_record('111'), _record('222'), _record('333')])

    # the first work finishes, then the stop is noticed rather than working through the rest
    assert repo.download_file.call_count == 1


def test_a_record_with_no_work_number_is_skipped_rather_than_guessed_at():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])

    ao3.download_indexed([{'id': None, 'link': 'https://archiveofourown.org/works/1'}])

    repo.download_file.assert_not_called()


def _why(existing: dict, superseded: dict, forced=False) -> str:
    ao3, _, _ = make_ao3(filetypes=['HTML', 'PDF'])
    ao3.superseded = superseded
    records = [_record(w) for w in ('1', '2', '3', '4')]
    with patch('builtins.print') as said:
        ao3.say_why_downloading(records, existing, forced)
    return '\n'.join(str(c.args[0]) for c in said.call_args_list)


_HAVE = {'2': {'HTML': {}}, '3': {'HTML': {}}, '4': {'HTML': {}}}
_BEHIND = {'https://archiveofourown.org/works/2': {'HTML': 'old'},
           'https://archiveofourown.org/works/3': {'HTML': 'old'}}


def test_the_download_count_says_how_many_are_new_and_how_many_are_updates():
    said = _why(_HAVE, _BEHIND)

    assert strings.AO3_INFO_FROM_INDEX_NEW.format(1) in said
    assert strings.AO3_INFO_FROM_INDEX_UPDATING.format(2) in said
    # work 4 has its html and is only here for the pdf it lacks
    assert strings.AO3_INFO_FROM_INDEX_MISSING.format(1) in said


def test_a_kind_with_nothing_in_it_is_not_said():
    said = _why({}, {})
    assert said == strings.AO3_INFO_FROM_INDEX_NEW.format(4)


def test_copies_replaced_at_your_request_are_not_called_out_of_date():
    said = _why(_HAVE, _BEHIND, forced={'https://archiveofourown.org/works/2'})

    assert strings.AO3_INFO_FROM_INDEX_OVERWRITING.format(1) in said
    assert strings.AO3_INFO_FROM_INDEX_UPDATING.format(1) in said
    assert strings.AO3_INFO_FROM_INDEX_OVERWRITING.format(2) in _why(_HAVE, _BEHIND, True)

# endregion


# region re-reading one unfinished fic

def _unfinished(work: str = '111', published: int = 3) -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'title': 'A Fic', 'authors': ['library_of_alexandria'], 'summary': 'unchanged',
            'chapters_published': published, 'chapters_total': None,
            'date_updated': '01 Jan 2020', 'kudos': 10}


def _work_page(chapters: str = '9/?', updated: str = '2024-12-14') -> BeautifulSoup:
    return BeautifulSoup(
        f'<dl class="stats"><dd class="chapters">{chapters}</dd>'
        f'<dd class="words">5,688</dd><dd class="kudos">671</dd>'
        f'<dd class="status">{updated}</dd></dl>', 'html.parser')


def test_a_fic_is_re_read_from_its_own_link():
    # the index is the list; no listing is walked to find it
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        ao3.refresh_one(_unfinished('111'))

    repo.get_soup.assert_called_once_with('https://archiveofourown.org/works/111')


def test_re_reading_brings_the_chapter_count_up_to_date():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page(chapters='9/?')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        fresh = ao3.refresh_one(_unfinished(published=3))

    assert fresh['chapters_published'] == 9
    assert fresh['chapters_total'] is None


def test_re_reading_writes_the_updated_date_the_way_a_listing_would():
    # otherwise a bookmarks pass and an update pass rewrite each other forever
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page(updated='2024-12-14')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        fresh = ao3.refresh_one(_unfinished())

    assert fresh['date_updated'] == '14 Dec 2024'


def test_re_reading_leaves_alone_the_fields_a_work_page_says_differently():
    # tags, summary and the bookmark's own fields come from the listing; half-overwriting
    # them from a work page would fill the history with schema noise
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        fresh = ao3.refresh_one(_unfinished())

    assert fresh['summary'] == 'unchanged'
    assert fresh['authors'] == ['library_of_alexandria']


@pytest.mark.parametrize('known, page, expected', [
    (True, {'bookmarked': False}, True),        # your bookmark stays yours
    # an older entry that says nothing is not counted as yours: the page may say it is not
    (None, {'bookmarked': False}, False),
    (False, {'bookmarked': True}, True),        # found bookmarked, it becomes yours
    (False, {'bookmarked': False}, False),
])
def test_re_reading_never_demotes_a_known_bookmark(known, page, expected):
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page()
    record = _unfinished()
    if known is not None:
        record['bookmarked'] = known

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.ao3.bookmark_state', return_value=page):
        fresh = ao3.refresh_one(record)

    assert fresh.get('bookmarked') is expected


def test_re_reading_saves_the_entry_back_to_the_index():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        ao3.refresh_one(_unfinished())

    fileops.save_json.assert_called_once()
    written = fileops.save_json.call_args.args[1]
    assert written[indexing.INDEXES][-1]['chapters_published'] == 9


def test_a_page_that_cannot_be_read_raises_rather_than_writing_a_half_entry():
    # the caller turns this into a recorded failure; the entry it already had stays put
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = BeautifulSoup('<div></div>', 'html.parser')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_work_stats', return_value={'error': 'broken'}):
        with pytest.raises(exceptions.Ao3DownloaderException):
            ao3.refresh_one(_unfinished())

    fileops.save_json.assert_not_called()


def test_a_work_that_is_gone_raises_out_of_the_re_read():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = exceptions.DeletedException('deleted')

    with pytest.raises(exceptions.DeletedException):
        ao3.refresh_one(_unfinished())

# endregion


# region works that would not download

def test_a_work_that_fails_is_remembered_with_its_number():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.side_effect = exceptions.DownloadException('gone')

    ao3.download_indexed([_record('111')])

    assert ao3.failures == [{'id': '111',
                             'link': 'https://archiveofourown.org/works/111',
                             'error': 'EPUB: gone', 'reason': 'other'}]


def test_a_format_that_fails_does_not_stop_the_formats_after_it(capsys):
    # each format is a separate file at its own url; ao3 lacking the epub says nothing
    # about the pdf, which used to be abandoned without being asked for
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF', 'HTML'])
    repo.download_file.side_effect = lambda url, ft: (
        (_ for _ in ()).throw(exceptions.DownloadException('no epub')) if ft == 'EPUB'
        else b'file')

    ao3.download_indexed([_record('111')])

    assert [c.args[1] for c in repo.download_file.call_args_list] == ['EPUB', 'PDF', 'HTML']
    assert fileops.save_bytes.call_count == 2
    # still a failure, naming only the format that failed, and the work still counts as
    # downloaded for what did arrive
    assert ao3.failures[0]['error'] == 'EPUB: no epub'
    assert '111' in ao3.downloaded
    assert strings.INFO_FORMAT_FAILED.format('EPUB', 'no epub') in capsys.readouterr().out


def test_every_format_that_failed_is_named_in_the_one_failure():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF', 'HTML'])
    repo.download_file.side_effect = lambda url, ft: (
        b'file' if ft == 'HTML'
        else (_ for _ in ()).throw(exceptions.DownloadException(f'no {ft.lower()}')))

    ao3.download_indexed([_record('111')])

    assert ao3.failures[0]['error'] == 'EPUB: no epub; PDF: no pdf'


def test_a_work_with_a_failed_format_is_not_logged_as_fully_downloaded():
    # the log is what the long way round uses to skip works; a success there would mean the
    # missing format was never fetched again
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'HTML'])
    repo.download_file.side_effect = lambda url, ft: (
        b'file' if ft == 'HTML'
        else (_ for _ in ()).throw(exceptions.DownloadException('no epub')))

    ao3.download_indexed([_record('111')])

    assert not any(c.args[0].get('success') for c in fileops.write_log.call_args_list)


def test_a_stop_during_one_format_still_stops_the_rest():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF'])
    repo.download_file.side_effect = exceptions.CancelledException('stop')

    ao3.download_indexed([_record('111')])

    assert repo.download_file.call_count == 1
    assert ao3.failures == []


def test_a_work_is_only_listed_once_however_many_formats_failed():
    # a work that fails usually fails for every format, and the same number five times
    # over is worse than useless for feeding back in
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF', 'HTML'])
    repo.download_file.side_effect = exceptions.DownloadException('gone')

    ao3.download_indexed([_record('111')])

    assert [x['id'] for x in ao3.failures] == ['111']


def test_the_works_that_succeeded_are_not_listed():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.side_effect = [
        exceptions.DownloadException('gone'), b'epub bytes']

    ao3.download_indexed([_record('111'), _record('222')])

    assert [x['id'] for x in ao3.failures] == ['111']


def test_a_run_with_nothing_wrong_reports_no_failures():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111')])

    assert ao3.failures == []


def test_stopping_a_run_is_not_recorded_as_a_failed_work():
    # the work was never attempted; calling it failed would send you chasing nothing
    stopped = {'value': False}
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    ao3.cancelled = lambda: stopped['value']

    def fetch(*args):
        stopped['value'] = True
        return b'epub bytes'

    repo.download_file.side_effect = fetch

    ao3.download_indexed([_record('111'), _record('222')])

    assert ao3.failures == []


def test_the_long_way_round_records_failures_too():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])

    with patch.object(Ao3, 'try_download', side_effect=exceptions.DeletedException('deleted')):
        ao3.download_work(WORK_URL, {}, None)

    assert [x['id'] for x in ao3.failures] == ['123']

# endregion


# region progress over a slice of a listing

def test_progress_counts_the_whole_listing_when_the_run_covers_it() -> None:
    ao3, _, _ = make_ao3()

    assert ao3.page_progress(1, 80) == (1, 80)
    assert ao3.page_progress(80, 80) == (80, 80)


def test_progress_counts_only_the_pages_a_later_start_will_fetch() -> None:
    # pages 42 to 80 is 39 pages, and the first of them is the first page of the run -
    # reporting 42 of 80 would start the bar half full
    ao3, _, _ = make_ao3(start=42)

    assert ao3.page_progress(42, 80) == (1, 39)
    assert ao3.page_progress(80, 80) == (39, 39)


def test_progress_counts_only_as_far_as_the_stop_page() -> None:
    # pages 42 to 60 is 19 pages, not 39
    ao3, _, _ = make_ao3(start=42, pages=60)

    assert ao3.page_progress(42, 80) == (1, 19)
    assert ao3.page_progress(60, 80) == (19, 19)


def test_progress_reaches_the_end_exactly_at_the_last_page() -> None:
    ao3, _, _ = make_ao3(start=5, pages=9)

    done, of = ao3.page_progress(9, 80)

    assert done == of  # 100%, not more and not less


def test_progress_says_how_far_along_even_with_no_total_to_go_on() -> None:
    ao3, _, _ = make_ao3(start=3)

    assert ao3.page_progress(4, None) == (2, None)


def _finished_pages(events: list[dict]) -> list[dict]:
    """The 'this page is in' events, as opposed to the 'asking for it now' ones."""

    return [e for e in events if e['type'] == 'page' and not e.get('fetching')]


def test_get_metadata_reports_progress_within_the_slice_it_is_fetching() -> None:
    events: list[dict] = []
    ao3, repo, _ = make_ao3(start=3)
    ao3.progress = events.append
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=10)

    ao3.get_metadata(LISTING_URL, False)

    pages = _finished_pages(events)
    assert pages[0]['page'] == 1
    assert pages[0]['total'] == 8  # pages 3 to 10


def test_a_page_is_announced_before_it_is_asked_for() -> None:
    # the fetch is the slow part, so the ui has to be able to name the page in flight -
    # a caption written only once a page is in describes the wrong page for all of it
    events: list[dict] = []
    ao3, repo, _ = make_ao3()
    ao3.progress = events.append
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=2)

    ao3.get_metadata(LISTING_URL, False)

    kinds = [bool(e.get('fetching')) for e in events if e['type'] == 'page']
    # asked for, arrived, asked for, arrived
    assert kinds == [True, False, True, False]


def test_the_page_being_asked_for_carries_its_place_in_the_listing() -> None:
    events: list[dict] = []
    ao3, repo, _ = make_ao3()
    ao3.progress = events.append
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=2)

    ao3.get_metadata(LISTING_URL, False)

    asking = [e for e in events if e['type'] == 'page' and e.get('fetching')]
    # the total is read off the first page, so nothing knows it until that one is in
    assert (asking[0]['listingPage'], asking[0]['listingTotal']) == (1, None)
    assert (asking[1]['listingPage'], asking[1]['listingTotal']) == (2, 2)


def test_a_page_being_fetched_reports_no_works_yet() -> None:
    # it has not been read, so any count would be the previous page's
    events: list[dict] = []
    ao3, repo, _ = make_ao3()
    ao3.progress = events.append
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=1)

    ao3.get_metadata(LISTING_URL, False)

    asking = [e for e in events if e['type'] == 'page' and e.get('fetching')][0]
    assert 'works' not in asking


def test_get_metadata_also_reports_the_real_page_number_for_the_wording() -> None:
    # the bar measures the slice, but 'page 3 of 10' is the page you would go and look at,
    # so both sets of numbers are sent
    events: list[dict] = []
    ao3, repo, _ = make_ao3(start=3)
    ao3.progress = events.append
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=10)

    ao3.get_metadata(LISTING_URL, False)

    page = _finished_pages(events)[0]
    assert (page['listingPage'], page['listingTotal']) == (3, 10)
    assert (page['page'], page['total']) == (1, 8)


# region indexing only what is new

def test_indexing_stops_at_the_first_fic_already_held() -> None:
    # ao3 lists bookmarks newest first, so everything before the first familiar one is new
    # and everything after it has been seen. that is what makes one stop enough
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222', '333'], total_pages=9)

    records = ao3.get_metadata(LISTING_URL, False, known={'222'})

    assert [x['id'] for x in records] == ['111']
    # and it did not walk on into the rest of the listing
    assert repo.get_soup.call_count == 1


def test_the_works_ahead_of_a_familiar_one_are_still_written() -> None:
    # only the walking stops there; the new fics found before it are the point of the run
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'], total_pages=9)

    with patch.object(Ao3, 'save_metadata') as save:
        ao3.get_metadata(LISTING_URL, False, known={'222'})

    assert [c.args[0]['id'] for c in save.call_args_list] == ['111']


def test_a_listing_with_nothing_new_indexes_nothing() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'], total_pages=9)

    assert ao3.get_metadata(LISTING_URL, False, known={'111'}) == []


def test_without_a_known_set_the_whole_listing_is_walked() -> None:
    # the full scan must not quietly become a stop-at-the-first-familiar-one walk
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=3)

    records = ao3.get_metadata(LISTING_URL, False)

    assert repo.get_soup.call_count == 3
    assert len(records) == 1  # the same stub page each time, deduped

# endregion


# region noticing that the login has lapsed

def test_a_failed_download_asks_once_whether_the_login_is_still_good():
    ao3, repo, _ = make_ao3()
    repo.still_logged_in.return_value = True

    ao3.check_session()
    ao3.check_session()
    ao3.check_session()

    # once per run, not once per failure: it costs a request, and a lapsed session fails
    # every work after it
    assert repo.still_logged_in.call_count == 1


def test_a_lapsed_login_ends_the_run():
    ao3, repo, _ = make_ao3()
    repo.still_logged_in.return_value = False

    with pytest.raises(exceptions.SessionExpiredException):
        ao3.check_session()


def test_a_login_that_is_still_good_lets_the_run_carry_on():
    # the same failure a deleted work produces, so it must not end the run by itself
    ao3, repo, _ = make_ao3()
    repo.still_logged_in.return_value = True

    ao3.check_session()


def test_a_session_check_is_not_made_before_anything_has_failed():
    ao3, repo, _ = make_ao3()

    assert ao3.session_checked is False
    repo.still_logged_in.assert_not_called()

# endregion


# region indexing only what ao3 has touched lately

def _dated_listing(dates: list[str], total_pages: int = 9) -> BeautifulSoup:
    """A listing whose blurbs carry the dates given, in that order."""

    blurbs = ''.join(
        f'<li id="bookmark_{n}" class="bookmark blurb group work-{n}">'
        f'<div class="header module"><h4 class="heading"><a href="/works/{n}">W{n}</a> by '
        f'<a href="/users/a/pseuds/a" rel="author">A</a></h4>'
        f'<p class="datetime">{date}</p></div></li>'
        for n, date in enumerate(dates, start=100))
    items = ''.join(f'<li>{i}</li>' for i in range(1, total_pages + 1))
    return BeautifulSoup(
        f'<ol class="bookmark index group">{blurbs}</ol>'
        f'<ol class="pagination actions">{items}</ol>', 'html.parser')


def test_indexing_stops_at_the_first_work_older_than_the_floor() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _dated_listing(
        ['11 Sep 2026', '10 Sep 2026', '01 Jan 2020'])

    records = ao3.get_metadata(LISTING_URL, False, stop_before='2026-09-01')

    assert [x['id'] for x in records] == ['100', '101']
    assert repo.get_soup.call_count == 1


def test_a_work_updated_on_the_floor_date_is_still_indexed() -> None:
    # 'since the last run' includes the day it ran: a work updated that morning is newer
    # than a run that started that afternoon as far as this can tell
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _dated_listing(['01 Sep 2026', '31 Aug 2026'])

    records = ao3.get_metadata(LISTING_URL, False, stop_before='2026-09-01')

    assert [x['id'] for x in records] == ['100']


def test_without_a_floor_the_whole_listing_is_walked() -> None:
    # the first time there is no completed run to measure from, and a short walk down from
    # an invented date would be worse than an honest full one
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _dated_listing(['01 Jan 2020'], total_pages=3)

    ao3.get_metadata(LISTING_URL, False, stop_before='')

    assert repo.get_soup.call_count == 3


def test_a_work_with_no_readable_date_does_not_stop_the_walk() -> None:
    # it cannot be judged against the floor, and stopping on it would cut the run short
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _dated_listing(['', '11 Sep 2026'])

    records = ao3.get_metadata(LISTING_URL, False, stop_before='2026-09-01')

    assert [x['id'] for x in records] == ['100', '101']


def _bookmarked_listing(pairs: list[tuple[str, str]]) -> BeautifulSoup:
    """A listing whose blurbs carry (updated, bookmarked) dates, the way a bookmarks page does."""

    blurbs = ''.join(
        f'<li id="bookmark_{n}" class="bookmark blurb group work-{n}">'
        f'<div class="header module"><h4 class="heading"><a href="/works/{n}">W{n}</a> by '
        f'<a href="/users/a/pseuds/a" rel="author">A</a></h4>'
        f'<p class="datetime">{updated}</p></div>'
        f'<div class="user module group"><p class="datetime">{bookmarked}</p></div></li>'
        for n, (updated, bookmarked) in enumerate(pairs, start=100))
    return BeautifulSoup(
        f'<ol class="bookmark index group">{blurbs}</ol>'
        '<ol class="pagination actions"><li>1</li></ol>', 'html.parser')


def test_a_bookmarked_walk_stops_on_the_bookmark_date_not_the_update_date() -> None:
    # a fic bookmarked yesterday but last updated years ago is new to the library, and
    # stopping on its update date would throw it away
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _bookmarked_listing([
        ('01 Jan 2019', '12 Sep 2026'),   # old fic, new bookmark: kept
        ('11 Sep 2026', '01 Mar 2025'),   # bookmarked before the floor: the walk stops here
        ('10 Sep 2026', '01 Feb 2025'),
    ])

    records = ao3.get_metadata(LISTING_URL, False, stop_before='2026-09-01',
                               stop_on='bookmarked')

    assert [x['id'] for x in records] == ['100']


def test_an_updated_walk_still_stops_on_the_update_date() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _bookmarked_listing([
        ('11 Sep 2026', '01 Jan 2019'),   # changed since the floor, bookmarked long ago: kept
        ('01 Jan 2019', '12 Sep 2026'),   # updated before the floor: the walk stops here
    ])

    records = ao3.get_metadata(LISTING_URL, False, stop_before='2026-09-01')

    assert [x['id'] for x in records] == ['100']


def _page_lines(capsys) -> list[str]:
    return [line for line in capsys.readouterr().out.splitlines() if 'page' in line]


def test_a_walk_with_a_floor_never_claims_to_know_how_many_pages_it_will_read(capsys) -> None:
    # the floor ends it wherever the first older fic sits, so the listing's page count is not
    # the run's - 'finished page 1 of 3' on a walk that stops at page 1 promises two more pages
    events: list[dict] = []
    ao3, repo, _ = make_ao3()
    ao3.progress = events.append
    repo.get_soup.return_value = _dated_listing(['11 Sep 2026', '01 Jan 2020'], total_pages=3)

    ao3.get_metadata(LISTING_URL, False, stop_before='2026-09-01')

    lines = _page_lines(capsys)
    assert any(line.startswith('finished page 1.') for line in lines), lines
    assert not any(' of ' in line for line in lines), lines
    pages = [e for e in events if e['type'] == 'page']
    assert all(e['listingTotal'] is None and e['total'] is None for e in pages)


def test_a_walk_that_stops_at_a_known_fic_does_not_give_a_total_either(capsys) -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'], total_pages=9)

    ao3.get_metadata(LISTING_URL, False, known={'222'})

    assert not any(' of ' in line for line in _page_lines(capsys))


def test_a_walk_that_reads_the_whole_listing_still_says_of_how_many(capsys) -> None:
    # with nothing to stop it early, the page count really is how many pages it will read
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _dated_listing(['11 Sep 2026'], total_pages=2)

    ao3.get_metadata(LISTING_URL, False)

    lines = _page_lines(capsys)
    assert 'fetching page 2 of 2' in lines
    assert any(line.startswith('finished page 2 of 2.') for line in lines), lines


def test_a_floor_nothing_is_older_than_still_stops_at_the_end_of_the_listing() -> None:
    # the stop rule may simply never fire - every bookmark updated since the floor, or a
    # floor older than the whole library. running out of pages is the fallback, and without
    # it the walk would have no reason to end
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _dated_listing(['11 Sep 2026', '10 Sep 2026'], total_pages=3)

    records = ao3.get_metadata(LISTING_URL, False, stop_before='2020-01-01')

    # every page fetched, and then it stopped of its own accord
    assert repo.get_soup.call_count == 3
    assert [x['id'] for x in records] == ['100', '101']


def test_a_floor_nothing_is_older_than_stops_on_a_listing_of_one_page() -> None:
    # no pagination at all: `total_pages` is None, and that has to end the walk too
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _dated_listing(['11 Sep 2026'], total_pages=1)

    records = ao3.get_metadata(LISTING_URL, False, stop_before='2020-01-01')

    assert repo.get_soup.call_count == 1
    assert [x['id'] for x in records] == ['100']

# endregion


# region indexing one fic from its own page

def _work_page_soup() -> BeautifulSoup:
    return BeautifulSoup(
        '<div class="preface"><h2 class="title">A Fic</h2>'
        '<h3 class="byline">library_of_alexandria</h3></div>'
        '<dl class="stats"><dd class="chapters">3/?</dd><dd class="words">500</dd>'
        '<dd class="status">2024-12-14</dd></dl>', 'html.parser')


def test_a_fic_never_indexed_gets_an_entry_from_its_own_page() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page_soup()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        record = ao3.index_one_work('https://archiveofourown.org/works/111')

    assert record['id'] == '111'
    assert record['title'] == 'A Fic'
    assert record['authors'] == ['library_of_alexandria']
    assert record['chapters_published'] == 3
    fileops.save_json.assert_called_once()


def test_a_fic_already_indexed_keeps_what_the_listing_gave_it() -> None:
    # a work page cannot speak to tags, the summary or your own bookmark notes, so an
    # entry that has them must not be overwritten with a work page's idea of the fic
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _work_page_soup()
    existing = {'id': '111', 'link': 'https://archiveofourown.org/works/111',
                'title': 'A Fic', 'authors': ['library_of_alexandria'], 'summary': 'from the listing',
                'bookmark_notes': 'mine', 'chapters_published': 1}

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        record = ao3.index_one_work('https://archiveofourown.org/works/111', existing)

    assert record['summary'] == 'from the listing'
    assert record['bookmark_notes'] == 'mine'
    assert record['chapters_published'] == 3   # only the stats moved


def test_a_fic_whose_page_cannot_be_read_raises_rather_than_writing_a_stub() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = BeautifulSoup('<div></div>', 'html.parser')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_work_stats', return_value={'error': 'broken'}):
        with pytest.raises(exceptions.Ao3DownloaderException):
            ao3.index_one_work('https://archiveofourown.org/works/111')

    fileops.save_json.assert_not_called()


@pytest.mark.parametrize('existing, page, marked', [
    (None, {'bookmarked': False}, True),                       # new, not yours
    (None, {}, True),                                          # new, page could not say
    (None, {'bookmarked': True}, False),                       # new, but you bookmarked it
    ({'bookmarked': True}, {}, False),                         # already your bookmark
    ({}, {}, True),                                            # older entry: not counted as yours
    ({'bookmarked': True}, {'bookmarked': True}, False),       # your bookmark, fetched by link
    ({'bookmarked': True}, {}, False),                         # same, run without logging in
    ({'bookmarked': False}, {'bookmarked': False}, True),      # a collection's, fetched by link
    ({'bookmarked': True}, {'bookmarked': False}, False),      # your bookmark, page says not
])
def test_a_fic_fetched_by_link_is_marked_so_unless_it_is_your_bookmark(existing, page, marked) -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _work_page_soup()
    if existing is not None:
        existing = {'id': '111', 'link': 'https://archiveofourown.org/works/111',
                    'title': 'A Fic', 'authors': ['library_of_alexandria'], **existing}

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.ao3.bookmark_state', return_value=page):
        record = ao3.index_one_work('https://archiveofourown.org/works/111', existing)

    assert record.get('from_link') is (True if marked else None)
    if was_bookmark(existing):
        assert record.get('bookmarked') is not False      # a known bookmark is never demoted


def test_the_existing_entry_is_looked_for_only_once_ao3_has_shown_the_work() -> None:
    # the fic runs ask ao3 first: a fic ao3 will not show must not cost a read of the library
    ao3, repo, _ = make_ao3()
    repo.get_soup.side_effect = exceptions.Ao3DownException('down')
    find = MagicMock(return_value=None)
    with pytest.raises(exceptions.Ao3DownException):
        ao3.index_one_work('https://archiveofourown.org/works/111', find_existing=find)
    find.assert_not_called()

    repo.get_soup.side_effect = None
    repo.get_soup.return_value = _work_page_soup()
    find.return_value = {'id': '111', 'link': 'https://archiveofourown.org/works/111',
                         'title': 'A Fic', 'authors': ['library_of_alexandria'], 'summary': 'from the listing'}
    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        record = ao3.index_one_work('https://archiveofourown.org/works/111', find_existing=find)
    find.assert_called_once()
    assert record['summary'] == 'from the listing'

# endregion


def test_a_page_is_written_only_once_all_of_it_has_been_read() -> None:
    # a page is one unit of work: fetched, parsed, then saved. saving as each blurb was
    # parsed made a page half-written by definition, so a page abandoned partway - by a
    # pause, or anything else - left entries behind for a page that was never finished
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222', '333'])
    order: list[str] = []

    real_metadata = parse_soup.get_blurb_metadata
    with patch('source_code.parse_soup.get_blurb_metadata',
               side_effect=lambda b: (order.append('parsed'), real_metadata(b))[1]), \
         patch.object(Ao3, 'save_metadata', side_effect=lambda d: order.append('saved')):
        ao3.get_metadata(LISTING_URL, False)

    assert order == ['parsed', 'parsed', 'parsed', 'saved', 'saved', 'saved']


def test_a_page_says_it_is_being_fetched_before_the_request_goes_out(capsys) -> None:
    # fetching a page is the slow part, and a rate-limit break can add minutes to it. a log
    # that only reports finished pages sits unchanged through all of that, which reads as a
    # hang rather than as work in progress
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=3)

    ao3.get_metadata(LISTING_URL, False)

    said = [x.strip() for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert said[0] == 'fetching page 1'
    assert said[1].startswith('finished page 1 of 3')
    assert said[2] == 'fetching page 2 of 3'


def test_the_first_page_counts_towards_no_total_because_there_is_not_one_yet(capsys) -> None:
    # how many pages the listing has is only known once the first has come back, so that
    # line says 'fetching page 1' rather than inventing a total to count towards
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=1)

    ao3.get_metadata(LISTING_URL, False)

    assert 'fetching page 1\n' in capsys.readouterr().out


def test_the_page_a_run_ends_on_still_says_it_finished(capsys) -> None:
    # this line used to sit after the checks that end the loop, so the last page of a
    # listing was fetched, parsed and saved without ever reporting that it was done
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'], total_pages=3)

    ao3.get_metadata(LISTING_URL, False)

    # the same stub page comes back each time and dedupes, so the count stays put; what
    # matters here is that page 3 - the one the run ends on - reports at all
    assert 'finished page 3 of 3. 2 works so far' in capsys.readouterr().out


def test_a_one_page_listing_is_not_said_to_be_one_of_none(capsys) -> None:
    # a single page carries no pagination, so there is no total to count towards. it used
    # not to matter because this line was never reached on a last page at all
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=1)

    ao3.get_metadata(LISTING_URL, False)

    said = capsys.readouterr().out
    assert 'finished page 1. 1 works so far' in said
    assert 'None' not in said


def test_the_page_a_stop_limit_ends_on_still_says_it_finished(capsys) -> None:
    ao3, repo, _ = make_ao3(pages=2)
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=9)

    ao3.get_metadata(LISTING_URL, False)

    said = capsys.readouterr().out
    assert 'finished page 2 of 9' in said
    # and it stopped there rather than carrying on
    assert 'fetching page 3 of 9' not in said

# endregion


def test_get_metadata_begins_on_the_requested_page() -> None:
    ao3, repo, fileops = make_ao3(start=5)
    repo.get_soup.return_value = _listing_soup(['111'])

    ao3.get_metadata(LISTING_URL, False)

    assert repo.get_soup.call_args_list[0].args[0] == LISTING_URL + '?page=5'


def test_get_metadata_no_longer_records_a_place_in_the_listing() -> None:
    # the page sorts and filters for itself - by when each was bookmarked, by default
    ao3, repo, fileops = make_ao3(start=5)
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert all('position' not in r for r in records)
    assert all(r[strings.BOOKMARK_TYPE_FIELD] == strings.BOOKMARK_TYPE_WORK for r in records)


def test_get_metadata_still_records_the_listing_itself_as_the_source() -> None:
    # the page it started on is not the provenance; the listing is
    ao3, repo, fileops = make_ao3(start=3)
    repo.get_soup.return_value = _listing_soup(['111'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert records[0]['source'] == LISTING_URL


def test_get_metadata_records_the_listing_and_its_order() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222']
    # the source is the link that was asked for, not the last page walked to
    assert all(r['source'] == LISTING_URL for r in records)
    # when it was read is recorded in the file rather than on the record
    written = list(_saved(fileops).values())
    assert all(w[indexing.LAST_INDEXED] for w in written)


def test_get_metadata_writes_each_page_as_it_is_read() -> None:
    # the point of writing incrementally: a long run leaves usable output behind
    ao3, repo, fileops = make_ao3()
    written_before_second_page = []

    def pages(_url):
        if repo.get_soup.call_count == 2:
            written_before_second_page.append(fileops.save_json.call_count)
        return _listing_soup(['111'] if repo.get_soup.call_count == 1 else ['222'], total_pages=2)

    repo.get_soup.side_effect = pages

    ao3.get_metadata(LISTING_URL, False)

    assert written_before_second_page == [1]
    assert fileops.save_json.call_count == 2


def test_get_metadata_keeps_the_files_written_before_a_page_failed() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = [_listing_soup(['111'], total_pages=3), ValueError('connection reset')]

    ao3.get_metadata(LISTING_URL, False)

    assert list(_saved(fileops)) == _indexed('111 Work 111 - A.json')


def test_get_metadata_still_names_a_work_with_no_title_or_author() -> None:
    # whatever else is missing, the work number has to survive, or the file cannot be
    # matched back to anything
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = BeautifulSoup(
        '<ol class="bookmark index group">'
        '<li id="bookmark_1" class="bookmark blurb group work-111 user-1">'
        '<div class="header module"><h4 class="heading">'
        '<a href="/works/111"></a></h4></div></li></ol>', 'html.parser')

    ao3.get_metadata(LISTING_URL, False)

    written = list(_saved(fileops))[0]
    assert parse_text.get_work_number_from_filename(os.path.basename(written)) == '111'


def test_get_metadata_survives_an_unwritable_file() -> None:
    ao3, repo, fileops = make_ao3()
    fileops.save_json.side_effect = OSError('disk full')
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    records = ao3.get_metadata(LISTING_URL, False)

    # both were still parsed, and the failures were logged rather than ending the run
    assert len(records) == 2
    logged = [c.args[0] for c in fileops.write_log.call_args_list]
    assert sum(1 for x in logged if x.get('message') == strings.ERROR_METADATA_SAVE) == 2


def test_get_metadata_rewrites_files_after_work_dates_are_filled() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = [_listing_soup(['111']), _work_soup()]

    ao3.get_metadata(LISTING_URL, True)

    # once during the crawl, once with the dates in
    assert fileops.save_json.call_count == 2
    entries = fileops.save_json.call_args.args[1][indexing.INDEXES]
    # the second save replaces this run's reading rather than adding a second one
    assert len(entries) == 1
    assert entries[0]['date_created'] == '01 Jan 2019'


def test_get_metadata_stops_when_cancelled_and_keeps_what_it_saved() -> None:
    # stopping must not throw away pages already written
    ao3, repo, fileops = make_ao3()
    cancelled = {'value': False}
    ao3.cancelled = lambda: cancelled['value']

    def pages(_url):
        if repo.get_soup.call_count == 1:
            return _listing_soup(['111'], total_pages=5)
        cancelled['value'] = True
        return _listing_soup(['222'], total_pages=5)

    repo.get_soup.side_effect = pages

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222']
    assert sorted(_saved(fileops)) == _indexed('111 Work 111 - A.json', '222 Work 222 - A.json')
    # a stop is not an error
    logged = [c.args[0] for c in fileops.write_log.call_args_list]
    assert not any(x.get('message') == strings.ERROR_LINKS_LIST for x in logged)


def test_get_metadata_stops_before_the_first_page_when_already_cancelled() -> None:
    ao3, repo, fileops = make_ao3()
    ao3.cancelled = lambda: True

    records = ao3.get_metadata(LISTING_URL, False)

    assert records == []
    repo.get_soup.assert_not_called()


def test_add_work_dates_stops_when_cancelled() -> None:
    ao3, repo, _ = make_ao3()
    ao3.cancelled = lambda: True
    records = [{'link': WORK_URL, 'date_created': None, 'date_updated': '01 Jan 2020'}]

    ao3.add_work_dates(records)

    repo.get_soup.assert_not_called()
    assert records[0]['date_created'] is None


def test_download_stops_when_cancelled_without_logging_a_failure() -> None:
    ao3, repo, fileops = make_ao3()
    ao3.cancelled = lambda: True

    ao3.download(LISTING_URL, [])

    repo.get_soup.assert_not_called()
    logged = [c.args[0] for c in fileops.write_log.call_args_list]
    assert not any(x.get('success') is False for x in logged)


def test_check_cancelled_does_nothing_without_a_callback() -> None:
    # the console app passes none, and must be unaffected
    ao3, _, _ = make_ao3()

    assert ao3.cancelled is None
    ao3.check_cancelled()


def test_get_metadata_does_not_load_work_pages_by_default() -> None:
    # the whole point of reading the listing is one request per page, not per work
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222', '333'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert len(records) == 3
    assert repo.get_soup.call_count == 1
    assert all(r['date_created'] is None for r in records)


def test_get_metadata_paginates() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.side_effect = [
        _listing_soup(['111'], total_pages=2),
        _listing_soup(['222'], total_pages=2)]

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222']
    assert repo.get_soup.call_count == 2


def test_get_metadata_respects_page_limit() -> None:
    ao3, repo, _ = make_ao3(pages=2)
    repo.get_soup.side_effect = [
        _listing_soup(['111'], total_pages=5),
        _listing_soup(['222'], total_pages=5)]

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222']
    assert repo.get_soup.call_count == 2


def test_get_metadata_skips_bookmarks_that_are_not_works(capsys) -> None:
    series = ('<li id="bookmark_9" class="bookmark blurb group series-5 user-1">'
              '<h4 class="heading"><a href="/series/5">A Series</a></h4></li>')
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], extra=series)

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111']
    assert '1' in capsys.readouterr().out


def test_get_metadata_dedupes_a_bookmark_seen_on_two_pages() -> None:
    # works shift between pages while a long list is being read
    ao3, repo, _ = make_ao3()
    repo.get_soup.side_effect = [
        _listing_soup(['111', '222'], total_pages=2),
        _listing_soup(['222', '333'], total_pages=2)]

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222', '333']


def test_get_metadata_keeps_the_same_work_bookmarked_twice() -> None:
    # two pseuds of the same user can each bookmark one work; both are real bookmarks
    ao3, repo, _ = make_ao3()
    both = _blurb_html('111', bookmark_id='1') + _blurb_html('111', bookmark_id='2')
    repo.get_soup.return_value = BeautifulSoup(
        f'<ol class="bookmark index group">{both}</ol>', 'html.parser')

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '111']


def test_get_metadata_returns_partial_results_when_a_page_fails() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = [
        _listing_soup(['111'], total_pages=3),
        ValueError('connection reset')]

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111']
    assert fileops.write_log.called


def test_get_metadata_looks_up_work_dates_when_asked() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.side_effect = [_listing_soup(['111']), _work_soup()]

    records = ao3.get_metadata(LISTING_URL, True)

    assert records[0]['date_created'] == '01 Jan 2019'
    assert records[0]['date_updated'] == '05 May 2021'
    assert repo.get_soup.call_count == 2


def test_add_work_dates_keeps_listing_date_when_work_has_no_status() -> None:
    # single chapter works have no 'Updated' line, so the listing date is all there is
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _work_soup(status='')
    records = [{'link': WORK_URL, 'date_created': None, 'date_updated': '01 Jan 2020'}]

    ao3.add_work_dates(records)

    assert records[0]['date_created'] == '01 Jan 2019'
    assert records[0]['date_updated'] == '01 Jan 2020'


def test_add_work_dates_logs_and_continues_past_a_failed_work() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = [ValueError('boom'), _work_soup()]
    records = [
        {'link': WORK_URL, 'date_created': None, 'date_updated': '01 Jan 2020'},
        {'link': 'https://archiveofourown.org/works/222', 'date_created': None, 'date_updated': ''}]

    ao3.add_work_dates(records)

    assert records[0]['date_created'] is None
    assert records[1]['date_created'] == '01 Jan 2019'
    logged = [c.args[0] for c in fileops.write_log.call_args_list]
    assert any(x.get('message') == strings.ERROR_METADATA_WORK_DATES for x in logged)

# endregion

# region Constructor

def test_init_reads_debug_from_ini() -> None:
    ao3, _, fileops = make_ao3(debug=True)
    assert ao3.debug is True
    fileops.get_ini_value_boolean.assert_called_once_with(strings.INI_DEBUG_LOGGING, False)

# endregion


# region replacing the copy a download supersedes
#
# The risk here is losing a file the user has and we do not. Every one of these is about
# refusing to delete, so they matter more than the one case that does.

WORK = 'https://archiveofourown.org/works/123'


def superseding(old: str = r'C:\downloads\123 A 2024-01-01.html'):
    ao3, repo, fileops = make_ao3()
    ao3.superseded = {WORK: {'HTML': old}}
    fileops.saved_intact.return_value = True
    fileops.delete_file.return_value = True
    return ao3, fileops


def test_the_old_copy_goes_once_the_new_one_is_confirmed():
    ao3, fileops = superseding()

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 2048)

    fileops.saved_intact.assert_called_once_with(r'C:\downloads\123 A 2024-12-14.html', 2048)
    fileops.delete_file.assert_called_once_with(r'C:\downloads\123 A 2024-01-01.html')


def test_nothing_is_deleted_when_the_new_file_cannot_be_confirmed():
    # a download that failed, was cut short, or landed elsewhere must not take the old one
    ao3, fileops = superseding()
    fileops.saved_intact.return_value = False

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 2048)

    fileops.delete_file.assert_not_called()


def test_nothing_is_deleted_when_there_was_no_older_copy():
    ao3, repo, fileops = make_ao3()

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)

    fileops.delete_file.assert_not_called()


def test_a_different_file_type_is_never_the_one_removed():
    # the epub is out of date too, but this download was the html
    ao3, repo, fileops = make_ao3()
    ao3.superseded = {WORK: {'EPUB': r'C:\downloads\123 A 2024-01-01.epub'}}
    fileops.saved_intact.return_value = True

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)

    fileops.delete_file.assert_not_called()


def test_a_download_that_kept_its_name_deletes_nothing():
    # the write already replaced it in place; deleting would remove what was just saved
    same = r'C:\downloads\123 A 2024-01-01.html'
    ao3, fileops = superseding(same)

    ao3.replace_superseded(WORK, 'HTML', same, 10)

    fileops.delete_file.assert_not_called()


def test_the_same_file_reached_by_a_different_path_is_still_not_deleted():
    # built with os.path.join, not written as C:\ paths: `sub/..` is only resolved by the
    # running system's own rules, and a hosted helper runs on linux, so this has to hold there
    # too. a windows path on linux is one long file name, and the check would not be tested
    ao3, fileops = superseding(os.path.join('downloads', 'sub', '..', '123 A 2024-01-01.html'))

    ao3.replace_superseded(WORK, 'HTML', os.path.join('downloads', '123 A 2024-01-01.html'), 10)

    fileops.delete_file.assert_not_called()


def test_another_works_copy_is_never_touched():
    ao3, repo, fileops = make_ao3()
    ao3.superseded = {'https://archiveofourown.org/works/999':
                      {'HTML': r'C:\downloads\999 B 2024-01-01.html'}}
    fileops.saved_intact.return_value = True

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)

    fileops.delete_file.assert_not_called()


def test_a_download_still_counts_as_done_when_the_old_file_will_not_go():
    ao3, fileops = superseding()
    fileops.delete_file.return_value = False

    # the point is that this does not raise: the new file is saved either way
    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)


def test_a_failure_while_tidying_up_never_breaks_the_download():
    ao3, fileops = superseding()
    fileops.saved_intact.side_effect = OSError('disk went away')

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)

    fileops.write_log.assert_called()


def test_the_replacement_really_removes_the_file_on_disk(tmp_path):
    # the checks above are about refusing; this one proves the real thing works end to end
    ao3, repo, fileops = make_ao3()
    # the real disk checks, with logging still mocked
    fileops.saved_intact.side_effect = lambda p, n: FileOps.saved_intact(fileops, p, n)
    fileops.delete_file.side_effect = lambda p: FileOps.delete_file(fileops, p)

    old = tmp_path / '123 A 2024-01-01.html'
    new = tmp_path / '123 A 2024-12-14.html'
    old.write_bytes(b'old copy')
    new.write_bytes(b'the new copy')
    ao3.superseded = {WORK: {'HTML': str(old)}}

    ao3.replace_superseded(WORK, 'HTML', str(new), len(b'the new copy'))

    assert not old.exists()
    assert new.exists()


def test_a_truncated_new_file_leaves_the_old_one_where_it_is(tmp_path):
    ao3, repo, fileops = make_ao3()
    # the real disk checks, with logging still mocked
    fileops.saved_intact.side_effect = lambda p, n: FileOps.saved_intact(fileops, p, n)
    fileops.delete_file.side_effect = lambda p: FileOps.delete_file(fileops, p)

    old = tmp_path / '123 A 2024-01-01.html'
    new = tmp_path / '123 A 2024-12-14.html'
    old.write_bytes(b'old copy')
    new.write_bytes(b'half')
    ao3.superseded = {WORK: {'HTML': str(old)}}

    # says it should be 2048 bytes, but only 4 arrived
    ao3.replace_superseded(WORK, 'HTML', str(new), 2048)

    assert old.exists()

# endregion


# region every file a download writes is announced
#
# only a deleted older copy used to say anything, so a run fetching new formats looked idle

def saving_for_real(tmp_path):
    ao3, repo, fileops = make_ao3()
    fileops.downloadfolder = str(tmp_path)
    (tmp_path / strings.WORKS_FOLDER_NAME).mkdir(exist_ok=True)
    fileops.save_bytes.side_effect = lambda n, c: FileOps.save_bytes(fileops, n, c)
    fileops.is_file.side_effect = lambda p: FileOps.is_file(fileops, p)
    fileops.same_file.side_effect = lambda a, b: FileOps.same_file(fileops, a, b)
    fileops.saved_intact.side_effect = lambda p, n: FileOps.saved_intact(fileops, p, n)
    fileops.saved_problem.side_effect = lambda p, n: FileOps.saved_problem(fileops, p, n)
    fileops.delete_file.side_effect = lambda p: FileOps.delete_file(fileops, p)
    fileops.rename_file.side_effect = lambda a, b: FileOps.rename_file(fileops, a, b)
    fileops.exists.side_effect = lambda p: FileOps.exists(fileops, p)
    return ao3


def outdated_copy(ao3, tmp_path):
    old = tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-01-01.html'
    old.write_bytes(b'old')
    ao3.superseded = {WORK: {'HTML': str(old)}}
    return old


def shortened_on_disk(ao3):
    """A save that lands short, as a full disk or a sync tool grabbing the file would leave."""
    real = ao3.fileops.save_bytes.side_effect
    ao3.fileops.save_bytes.side_effect = lambda n, c: real(n, c[:2])


def test_a_format_arriving_for_the_first_time_says_new_download(tmp_path, capsys):
    ao3 = saving_for_real(tmp_path)

    ao3.save_download(WORK, 'PDF', '123 A 2024-12-14.pdf', b'new')

    assert strings.INFO_SAVED_NEW_COPY.format('123 A 2024-12-14.pdf') in capsys.readouterr().out
    assert ao3.updated == set()
    assert ao3.kept_copies == []


def test_an_outdated_copy_replaced_names_only_the_new_file_once(tmp_path, capsys):
    ao3 = saving_for_real(tmp_path)
    old = outdated_copy(ao3, tmp_path)

    ao3.save_download(WORK, 'HTML', '123 A 2024-12-14.html', b'new copy')

    out = capsys.readouterr().out
    assert out.count(strings.INFO_REPLACED_OLD_COPY.format('123 A 2024-12-14.html')) == 1
    assert '2024-01-01' not in out
    assert not old.exists()
    assert '123' in ao3.updated


def test_a_copy_overwritten_under_the_same_name_reads_the_same_as_a_replacement(tmp_path,
                                                                               capsys):
    ao3 = saving_for_real(tmp_path)
    (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.html').write_bytes(b'damaged')

    ao3.save_download(WORK, 'HTML', '123 A 2024-12-14.html', b'fresh')

    assert strings.INFO_REPLACED_OLD_COPY.format('123 A 2024-12-14.html') \
        in capsys.readouterr().out
    assert '123' in ao3.updated


def test_a_same_name_download_takes_the_place_of_the_old_copy_leaving_nothing_beside_it(tmp_path):
    ao3 = saving_for_real(tmp_path)
    (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.html').write_bytes(b'damaged')

    ao3.save_download(WORK, 'HTML', '123 A 2024-12-14.html', b'fresh')

    assert sorted(os.listdir(tmp_path / strings.WORKS_FOLDER_NAME)) == ['123 A 2024-12-14.html']
    assert (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.html').read_bytes() == b'fresh'


def test_a_same_name_download_that_lands_short_keeps_the_copy_it_would_have_replaced(tmp_path, capsys):
    ao3 = saving_for_real(tmp_path)
    (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.html').write_bytes(b'yours')
    shortened_on_disk(ao3)

    with pytest.raises(exceptions.SavedFileException):
        ao3.save_download(WORK, 'HTML', '123 A 2024-12-14.html', b'fresh and long')

    # the copy you had is untouched, and nothing half-written is left beside it
    assert sorted(os.listdir(tmp_path / strings.WORKS_FOLDER_NAME)) == ['123 A 2024-12-14.html']
    assert (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.html').read_bytes() == b'yours'
    assert 'the old copy still exists' in capsys.readouterr().out


def test_a_same_name_download_that_cannot_be_moved_into_place_puts_the_old_copy_back(tmp_path, capsys):
    ao3 = saving_for_real(tmp_path)
    (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.html').write_bytes(b'yours')
    real = ao3.fileops.rename_file.side_effect
    # the old copy moves aside, then the new one will not move into its name
    ao3.fileops.rename_file.side_effect = lambda a, b: False if a.endswith(strings.SWAP_NEW_SUFFIX) else real(a, b)

    with pytest.raises(exceptions.SavedFileException) as raised:
        ao3.save_download(WORK, 'HTML', '123 A 2024-12-14.html', b'fresh')

    assert sorted(os.listdir(tmp_path / strings.WORKS_FOLDER_NAME)) == ['123 A 2024-12-14.html']
    assert (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.html').read_bytes() == b'yours'
    assert 'your copy is kept as it was' in str(raised.value)


# 1. the new file is not on disk as it arrived

def test_a_short_replacement_is_removed_and_fails_the_work_leaving_the_old_copy(tmp_path,
                                                                                capsys):
    ao3 = saving_for_real(tmp_path)
    old = outdated_copy(ao3, tmp_path)
    shortened_on_disk(ao3)

    with pytest.raises(exceptions.SavedFileException) as raised:
        ao3.save_download(WORK, 'HTML', '123 A 2024-12-14.html', b'new copy')

    assert old.exists()
    assert not (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.html').exists()
    assert strings.INFO_DAMAGED_KEPT_OLD.format('123 A 2024-01-01.html') \
        in capsys.readouterr().out
    # the detail says exactly what was wrong, for the failure report
    assert strings.SAVED_WRONG_SIZE.format(8, 2) in str(raised.value)
    assert '123 A 2024-01-01.html' in str(raised.value)
    assert ao3.kept_copies == [] and '123' not in ao3.updated


def test_a_short_first_download_is_removed_too(tmp_path, capsys):
    # a first download can land short as easily as a replacement, and a short file named
    # as current would be called up to date by every later run
    ao3 = saving_for_real(tmp_path)
    shortened_on_disk(ao3)

    with pytest.raises(exceptions.SavedFileException):
        ao3.save_download(WORK, 'PDF', '123 A 2024-12-14.pdf', b'new copy')

    assert not (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.pdf').exists()
    assert strings.INFO_DAMAGED_REMOVED.format('123 A 2024-12-14.pdf') in capsys.readouterr().out


def test_a_file_that_vanished_after_saving_says_where_it_was_looked_for(tmp_path):
    ao3 = saving_for_real(tmp_path)
    real = ao3.fileops.save_bytes.side_effect

    def snatched(name, content):
        path = real(name, content)
        os.remove(path)   # a sync tool moving it away straight after
        return path
    ao3.fileops.save_bytes.side_effect = snatched

    with pytest.raises(exceptions.SavedFileException) as raised:
        ao3.save_download(WORK, 'PDF', '123 A 2024-12-14.pdf', b'new copy')

    assert 'could not be found at' in str(raised.value)


def test_a_damaged_file_that_will_not_delete_says_to_remove_it_by_hand(tmp_path):
    ao3 = saving_for_real(tmp_path)
    shortened_on_disk(ao3)
    ao3.fileops.delete_file.side_effect = lambda p: False

    with pytest.raises(exceptions.SavedFileException) as raised:
        ao3.save_download(WORK, 'PDF', '123 A 2024-12-14.pdf', b'new copy')

    assert strings.DAMAGED_NOT_REMOVED in str(raised.value)


def test_a_damaged_file_fails_the_work_without_asking_whether_the_login_lapsed(tmp_path):
    # a problem in the folder says nothing about ao3; the check would cost a request
    ao3 = saving_for_real(tmp_path)
    shortened_on_disk(ao3)
    ao3.repo.download_file.return_value = b'new copy'
    record = {'id': '123', 'link': WORK, 'title': 'A', 'date_updated': '2024-12-14'}
    ao3.filetypes = ['PDF']

    ao3.download_indexed([record])

    ao3.repo.still_logged_in.assert_not_called()
    assert ao3.failures[0]['id'] == '123'
    assert strings.SAVED_WRONG_SIZE.format(8, 2) in ao3.failures[0]['error']
    assert '123' not in ao3.downloaded


# 2. the older copy will not delete

def test_an_older_copy_that_would_not_delete_is_announced_and_listed(tmp_path, capsys):
    ao3 = saving_for_real(tmp_path)
    ao3.fileops.delete_file.side_effect = lambda p: False
    outdated_copy(ao3, tmp_path)

    ao3.save_download(WORK, 'HTML', '123 A 2024-12-14.html', b'new copy')

    assert strings.INFO_KEPT_OLD_COPY.format('123 A 2024-12-14.html') in capsys.readouterr().out
    assert ao3.kept_copies == [{'id': '123', 'link': WORK, 'file': '123 A 2024-12-14.html',
                                'old': '123 A 2024-01-01.html',
                                'error': strings.KEPT_NOT_DELETED.format(
                                    '123 A 2024-01-01.html')}]
    # not an update: the old copy is still sitting there
    assert '123' not in ao3.updated


# 3. checking the new file errors

def test_a_check_that_errors_leaves_everything_and_lists_why(tmp_path, capsys):
    ao3 = saving_for_real(tmp_path)
    old = outdated_copy(ao3, tmp_path)
    ao3.fileops.saved_intact.side_effect = OSError('drive went away')

    ao3.save_download(WORK, 'HTML', '123 A 2024-12-14.html', b'new copy')

    assert old.exists() and (tmp_path / strings.WORKS_FOLDER_NAME / '123 A 2024-12-14.html').exists()
    assert strings.INFO_UNCONFIRMED.format('123 A 2024-12-14.html') in capsys.readouterr().out
    assert 'drive went away' in ao3.kept_copies[0]['error']
    assert ao3.kept_copies[0]['old'] == '123 A 2024-01-01.html'


def test_a_check_that_errors_on_a_first_download_is_listed_the_same_way(tmp_path, capsys):
    ao3 = saving_for_real(tmp_path)
    ao3.fileops.saved_intact.side_effect = OSError('drive went away')

    ao3.save_download(WORK, 'PDF', '123 A 2024-12-14.pdf', b'new copy')

    assert strings.INFO_UNCONFIRMED.format('123 A 2024-12-14.pdf') in capsys.readouterr().out
    assert ao3.kept_copies[0]['old'] == ''


def test_both_download_paths_announce_what_they_save():
    # the indexed path and the work-page path each used to call save_bytes directly
    import inspect
    for method in (Ao3.download_one_indexed, Ao3.try_download):
        source = inspect.getsource(method)
        assert 'save_download(' in source and 'save_bytes(' not in source
# endregion


# region whether the fic is bookmarked

def _page_with_bookmark_button(text: str) -> BeautifulSoup:
    return BeautifulSoup(
        str(_work_page_soup()) +
        f'<ul><li class="bookmark"><a class="bookmark_form_placement_open" '
        f'href="#bookmark-form">{text}</a></li></ul>', 'html.parser')


def test_a_walk_down_your_own_bookmarks_marks_every_fic_bookmarked() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _dated_listing(['11 Sep 2026'], total_pages=1)

    records = ao3.get_metadata(LISTING_URL, False, own_bookmarks=True)

    assert records and all(x['bookmarked'] is True for x in records)


def test_a_walk_not_known_to_be_your_bookmarks_says_nothing_about_it() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _dated_listing(['11 Sep 2026'], total_pages=1)

    records = ao3.get_metadata(LISTING_URL, False)

    assert records and all('bookmarked' not in x for x in records)


def test_a_fic_indexed_from_its_own_page_is_bookmarked_when_it_says_edit_bookmark() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _page_with_bookmark_button('Edit Bookmark')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        record = ao3.index_one_work('https://archiveofourown.org/works/111')

    assert record['bookmarked'] is True


def test_a_single_fic_you_have_not_bookmarked_is_recorded_as_not_bookmarked() -> None:
    # the single-fic run: its own page says 'Bookmark' - you have none - so the entry says so
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _page_with_bookmark_button('Bookmark')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        record = ao3.index_one_work('https://archiveofourown.org/works/111')

    assert record['bookmarked'] is False
    # and a new entry made from a work page is typed like any other work
    assert record[strings.BOOKMARK_TYPE_FIELD] == strings.BOOKMARK_TYPE_WORK


def test_a_single_fic_run_keeps_a_known_bookmark_whatever_its_page_shows() -> None:
    # your AO3 bookmarks take precedence: a fic run never demotes one
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _page_with_bookmark_button('Bookmark')
    existing = {'id': '111', 'link': 'https://archiveofourown.org/works/111',
                'bookmarked': True, strings.BOOKMARK_TYPE_FIELD: strings.BOOKMARK_TYPE_WORK}

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        record = ao3.index_one_work('https://archiveofourown.org/works/111', existing)

    assert record['bookmarked'] is True
    assert 'from_link' not in record


def test_a_refreshed_fic_keeps_a_known_bookmark_whatever_its_page_shows() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _page_with_bookmark_button('Bookmark')
    existing = {'id': '111', 'link': 'https://archiveofourown.org/works/111',
                'bookmarked': True}

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        record = ao3.refresh_one(existing)

    assert record['bookmarked'] is True


def test_a_page_that_cannot_tell_leaves_the_field_as_it_was() -> None:
    # a work page with no bookmark button (logged out, say) must not unmark a fic a
    # bookmarks walk has already said is yours - and must not invent an answer for a new one
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _work_page_soup()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        kept = ao3.refresh_one({'id': '111', 'link': 'https://archiveofourown.org/works/111',
                                'bookmarked': True})
        fresh = ao3.index_one_work('https://archiveofourown.org/works/222')

    assert kept['bookmarked'] is True
    assert 'bookmarked' not in fresh

# endregion
