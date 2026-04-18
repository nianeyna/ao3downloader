"""Tests for ao3downloader.ao3.Ao3 class."""

import os
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from ao3downloader import exceptions, strings
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


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
) -> tuple[Ao3, MagicMock, MagicMock]:
    """Create an Ao3 instance with mocked dependencies.
    Returns (ao3, repo_mock, fileops_mock)."""
    repo = MagicMock(spec=Repository)
    fileops = MagicMock(spec=FileOps)
    fileops.get_ini_value_boolean.return_value = debug
    ao3 = Ao3(repo=repo, fileops=fileops, filetypes=filetypes or ['EPUB'],
              pages=pages, series=series, images=images, mark=mark)
    return ao3, repo, fileops


def get_soup_from_fixture(filename: str) -> BeautifulSoup:
    fixture_path = os.path.join(os.path.dirname(__file__), 'fixtures', filename + '.html')
    with open(fixture_path) as f:
        return BeautifulSoup(f.read(), 'html.parser')


@contextmanager
def try_download_patches() -> Iterator[None]:
    """Patches proceed() and parse functions for try_download's main flow."""
    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('ao3downloader.parse_soup.get_title', return_value=['My Work']), \
         patch('ao3downloader.parse_soup.get_download_link', return_value='https://ao3.org/dl/work.epub'), \
         patch('ao3downloader.parse_soup.has_custom_skin', return_value=False), \
         patch('ao3downloader.parse_text.get_valid_filename', return_value='My Work'), \
         patch('ao3downloader.parse_text.get_file_type', return_value='.epub'):
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
    with patch('ao3downloader.parse_soup.is_locked', return_value=True), \
         patch('ao3downloader.parse_soup.is_deleted', return_value=True):
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
    fileops.save_bytes.assert_called_once_with('My Work.epub', b'epub content')
    assert log['title'] == ['My Work']
    assert log['workskin'] is False


def test_try_download_multiple_filetypes() -> None:
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF'])
    repo.get_book.return_value = b'content'

    with try_download_patches():
        with patch('ao3downloader.parse_text.get_file_type', side_effect=['.epub', '.pdf']):
            result = ao3.try_download(WORK_URL, {}, None)

    assert result is True
    assert fileops.save_bytes.call_count == 2
    fileops.save_bytes.assert_any_call('My Work.epub', b'content')
    fileops.save_bytes.assert_any_call('My Work.pdf', b'content')


def test_try_download_chapters_no_update() -> None:
    """Current chapters == given chapters: no update needed, returns False."""
    ao3, _, fileops = make_ao3()

    with try_download_patches():
        with patch('ao3downloader.parse_soup.get_current_chapters', return_value='5'):
            log: dict[str, object] = {}
            result = ao3.try_download(WORK_URL, log, '5')

    assert result is False
    fileops.save_bytes.assert_not_called()
    assert 'title' not in log  # returned before title was set


def test_try_download_chapters_fewer_than_given() -> None:
    """Current=3, given=5: still no update (3 <= 5)."""
    ao3, _, fileops = make_ao3()

    with try_download_patches():
        with patch('ao3downloader.parse_soup.get_current_chapters', return_value='3'):
            result = ao3.try_download(WORK_URL, {}, '5')

    assert result is False
    fileops.save_bytes.assert_not_called()


def test_try_download_chapters_update_available() -> None:
    """Current=10, given=5: update available (10 > 5), downloads proceed."""
    ao3, repo, fileops = make_ao3()
    repo.get_book.return_value = b'content'

    with try_download_patches():
        with patch('ao3downloader.parse_soup.get_current_chapters', return_value='10'):
            result = ao3.try_download(WORK_URL, {}, '5')

    assert result is True
    fileops.save_bytes.assert_called_once()


def test_try_download_images() -> None:
    ao3, repo, fileops = make_ao3(images=True)
    repo.get_book.side_effect = [b'epub', b'img1data', b'img2data']

    with try_download_patches():
        with patch('ao3downloader.parse_soup.get_image_links',
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
        with patch('ao3downloader.parse_soup.get_image_links',
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
        with patch('ao3downloader.parse_soup.get_image_links',
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
        with patch('ao3downloader.parse_soup.get_image_links',
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
        with patch('ao3downloader.parse_soup.get_image_links') as mock_img:
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
    with patch('ao3downloader.parse_text.is_work', return_value=True), \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(WORK_URL, {}, [])

    assert mock_dl.call_args is not None
    args = mock_dl.call_args[0]
    assert args[0] == WORK_URL
    assert args[2] is None  # chapters


def test_download_recursive_series_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('ao3downloader.parse_text.is_work', return_value=False), \
         patch('ao3downloader.parse_text.is_series', return_value=True), \
         patch.object(Ao3, 'download_series') as mock_ds:
        ao3.download_recursive(SERIES_URL, {}, [])

    assert mock_ds.call_args is not None
    args = mock_ds.call_args[0]
    assert args[0] == SERIES_URL


def test_download_recursive_already_visited() -> None:
    ao3, _, _ = make_ao3()
    with patch('ao3downloader.parse_text.is_work') as mock_is_work:
        ao3.download_recursive(WORK_URL, {}, [WORK_URL])

    mock_is_work.assert_not_called()


def test_download_recursive_adds_to_visited() -> None:
    ao3, _, _ = make_ao3()
    visited: list[str] = []
    with patch('ao3downloader.parse_text.is_work', return_value=True), \
         patch.object(Ao3, 'download_work'):
        ao3.download_recursive(WORK_URL, {}, visited)

    assert WORK_URL in visited


def test_download_recursive_invalid_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('ao3downloader.parse_text.is_work', return_value=False), \
         patch('ao3downloader.parse_text.is_series', return_value=False):
        with pytest.raises(exceptions.InvalidLinkException):
            ao3.download_recursive('https://example.com/fic/123', {}, [])


def test_download_recursive_listing_paginates() -> None:
    ao3, repo, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = LISTING_URL + '?page=2'

    with patch('ao3downloader.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('ao3downloader.parse_text.is_series', return_value=False), \
         patch('ao3downloader.parse_soup.get_total_pages', return_value=2), \
         patch('ao3downloader.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('ao3downloader.parse_text.get_page_number', side_effect=[1, 2, 2]), \
         patch('ao3downloader.parse_text.get_next_page', return_value=page2), \
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

    with patch('ao3downloader.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('ao3downloader.parse_text.is_series', return_value=False), \
         patch('ao3downloader.parse_soup.get_total_pages', return_value=5), \
         patch('ao3downloader.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('ao3downloader.parse_text.get_page_number', side_effect=[1, 2, 2, 3]), \
         patch('ao3downloader.parse_text.get_next_page', side_effect=[page2, page3]), \
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

    with patch('ao3downloader.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('ao3downloader.parse_text.is_series', return_value=False), \
         patch('ao3downloader.parse_soup.get_total_pages', side_effect=lambda s: 2 if s is soup1 else 1), \
         patch('ao3downloader.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('ao3downloader.parse_text.get_next_page') as mock_next, \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(LISTING_URL, {}, [])

    mock_next.assert_not_called()
    assert mock_dl.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_recursive_mark_mode_breaks_on_none() -> None:
    """Mark mode also breaks when total_pages is None."""
    ao3, repo, _ = make_ao3(mark=True)
    work1 = 'https://archiveofourown.org/works/111'

    with patch('ao3downloader.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('ao3downloader.parse_text.is_series', return_value=False), \
         patch('ao3downloader.parse_soup.get_total_pages', return_value=None), \
         patch('ao3downloader.parse_soup.get_work_and_series_urls', return_value=[work1]), \
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
         patch('ao3downloader.parse_soup.get_total_pages', return_value=None), \
         patch('ao3downloader.parse_soup.get_work_urls', return_value=[work1, work2]), \
         patch('ao3downloader.parse_text.get_page_number', return_value=1), \
         patch.object(Ao3, 'download_recursive') as mock_dr:
        ao3.download_series(SERIES_URL, {}, [])

    assert mock_dr.call_count == 2


def test_download_series_multi_page() -> None:
    ao3, repo, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = SERIES_URL + '?page=2'

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('ao3downloader.parse_soup.get_total_pages', return_value=2), \
         patch('ao3downloader.parse_soup.get_work_urls', side_effect=[[work1], [work2]]), \
         patch('ao3downloader.parse_text.get_page_number', side_effect=[1, 2]), \
         patch('ao3downloader.parse_text.get_next_page', return_value=page2), \
         patch.object(Ao3, 'download_recursive') as mock_dr:
        ao3.download_series(SERIES_URL, {}, [])

    assert mock_dr.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_series_calls_proceed() -> None:
    ao3, _, _ = make_ao3()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup) as mock_proceed, \
         patch('ao3downloader.parse_soup.get_total_pages', return_value=None), \
         patch('ao3downloader.parse_soup.get_work_urls', return_value=[]), \
         patch('ao3downloader.parse_text.get_page_number', return_value=1):
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

    with patch('ao3downloader.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('ao3downloader.parse_text.is_series', return_value=False), \
         patch('ao3downloader.parse_soup.get_total_pages', return_value=2), \
         patch('ao3downloader.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('ao3downloader.parse_text.get_page_number', side_effect=[1, 2, 2]), \
         patch('ao3downloader.parse_text.get_next_page', return_value=page2):
        ao3.get_work_links_recursive(links_list, LISTING_URL, [], False)

    assert work1 in links_list
    assert work2 in links_list
    assert repo.get_soup.call_count == 2


def test_get_work_links_work_with_metadata() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {}
    soup = MagicMock()
    metadata_dict = {'title': 'My Work', 'author': 'Author'}

    with patch('ao3downloader.parse_text.is_work', return_value=True), \
         patch('ao3downloader.parse_soup.get_work_metadata_from_list', return_value=metadata_dict):
        ao3.get_work_links_recursive(links_list, WORK_URL, [], True, soup)

    assert links_list[WORK_URL] == metadata_dict


def test_get_work_links_work_without_metadata() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {}

    with patch('ao3downloader.parse_text.is_work', return_value=True):
        ao3.get_work_links_recursive(links_list, WORK_URL, [], False)

    assert WORK_URL in links_list
    assert links_list[WORK_URL] is None


def test_get_work_links_duplicate_work_skipped() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {WORK_URL: None}

    with patch('ao3downloader.parse_text.is_work', return_value=True), \
         patch('ao3downloader.parse_soup.get_work_metadata_from_list') as mock_meta:
        ao3.get_work_links_recursive(links_list, WORK_URL, [], True)

    mock_meta.assert_not_called()


def test_get_work_links_series_collects_works() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {}
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'

    with patch('ao3downloader.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('ao3downloader.parse_text.is_series', side_effect=lambda url: '/series/' in url), \
         patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('ao3downloader.parse_soup.get_total_pages', return_value=None), \
         patch('ao3downloader.parse_soup.get_work_urls', return_value=[work1, work2]), \
         patch('ao3downloader.parse_text.get_page_number', return_value=1):
        ao3.get_work_links_recursive(links_list, SERIES_URL, [], False)

    assert work1 in links_list
    assert work2 in links_list


def test_get_work_links_duplicate_series_skipped() -> None:
    ao3, repo, _ = make_ao3()
    visited_series = [SERIES_URL]

    with patch('ao3downloader.parse_text.is_work', return_value=False), \
         patch('ao3downloader.parse_text.is_series', return_value=True):
        ao3.get_work_links_recursive({}, SERIES_URL, visited_series, False)

    repo.get_soup.assert_not_called()


def test_get_work_links_invalid_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('ao3downloader.parse_text.is_work', return_value=False), \
         patch('ao3downloader.parse_text.is_series', return_value=False):
        with pytest.raises(exceptions.InvalidLinkException):
            ao3.get_work_links_recursive({}, 'https://example.com/fic', [], False)

# endregion

# region Constructor

def test_init_reads_debug_from_ini() -> None:
    ao3, _, fileops = make_ao3(debug=True)
    assert ao3.debug is True
    fileops.get_ini_value_boolean.assert_called_once_with(strings.INI_DEBUG_LOGGING, False)

# endregion
