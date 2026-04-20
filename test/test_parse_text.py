import datetime
import os

import pytest

import ao3downloader.parse_text as parse_text


# region get_valid_filename

def test_get_valid_filename_no_directories():
    filename = ['valid filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == 'valid filename'


def test_get_valid_filename_one_directory():
    filename = ['valid', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('valid', 'filename')


def test_get_valid_filename_multiple_directories():
    filename = ['valid', 'directory', 'structure']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('valid', 'directory', 'structure')


def test_get_valid_filename_one_invalid_directory():
    filename = ['*', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == 'filename'


def test_get_valid_filename_multiple_invalid_directories():
    filename = ['*', '*', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == 'filename'


def test_get_valid_filename_valid_and_invalid_directories():
    filename = ['valid', '*', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('valid', 'filename')


def test_get_valid_filename_empty_directory():
    filename = ['valid', '', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('valid', 'filename')


def test_get_valid_filename_empty_string():
    filename = ['']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == ''


def test_get_valid_filename_whitespace():
    filename = ['   ']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == ''


def test_get_valid_filename_invalid_characters():
    filename = ['invalid', 'filename<>:"\|?*.']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('invalid', 'filename')


def test_get_valid_filename_maximum_length():
    filename = ['a' * 100]
    result = parse_text.get_valid_filename(filename, 50)
    assert result == 'a' * 50


def test_get_valid_filename_multiple_directories_maximum_length():
    filename = ['a' * 100, 'b' * 100]
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('a' * 50, 'b' * 50)

# endregion


# region get_pinboard_url

def test_get_pinboard_url_no_date():
    url = parse_text.get_pinboard_url('abc123', None)
    assert url == 'https://api.pinboard.in/v1/posts/all?auth_token=abc123'


def test_get_pinboard_url_pads_single_digit_month_and_day():
    url = parse_text.get_pinboard_url('abc123', datetime.datetime(2025, 3, 5))
    assert 'fromdt=2025-03-05T00:00:00Z' in url
    assert 'auth_token=abc123' in url


def test_get_pinboard_url_four_digit_year():
    url = parse_text.get_pinboard_url('tok', datetime.datetime(1999, 12, 31))
    assert 'fromdt=1999-12-31T00:00:00Z' in url


def test_get_pinboard_url_includes_token():
    url = parse_text.get_pinboard_url('my-secret-token', datetime.datetime(2020, 6, 15))
    assert 'auth_token=my-secret-token' in url

# endregion


# region get_file_type

@pytest.mark.parametrize('filetype, expected', [
    ('EPUB', '.epub'),
    ('PDF', '.pdf'),
    ('MOBI', '.mobi'),
    ('AZW3', '.azw3'),
    ('HTML', '.html'),
])
def test_get_file_type_lowercases_and_prefixes_dot(filetype, expected):
    assert parse_text.get_file_type(filetype) == expected

# endregion


# region get_work_number

@pytest.mark.parametrize('link, expected', [
    ('https://archiveofourown.org/works/12345', '12345'),
    ('https://archiveofourown.org/works/12345/', '12345'),
    ('https://archiveofourown.org/works/12345/chapters/67890', '12345'),
    ('https://archiveofourown.org/works/12345?view_adult=true', '12345'),
    ('/works/7', '7'),
])
def test_get_work_number_extracts_digits(link, expected):
    assert parse_text.get_work_number(link) == expected


def test_get_work_number_returns_none_when_missing():
    assert parse_text.get_work_number('https://archiveofourown.org/series/123') is None


def test_get_work_number_returns_none_when_no_digits_after():
    assert parse_text.get_work_number('https://archiveofourown.org/works/abc') is None

# endregion


# region get_series_number

@pytest.mark.parametrize('link, expected', [
    ('https://archiveofourown.org/series/789', '789'),
    ('https://archiveofourown.org/series/789/', '789'),
    ('https://archiveofourown.org/series/789?foo=bar', '789'),
])
def test_get_series_number_extracts_digits(link, expected):
    assert parse_text.get_series_number(link) == expected


def test_get_series_number_returns_none_for_work_url():
    assert parse_text.get_series_number('https://archiveofourown.org/works/123') is None

# endregion


# region is_work / is_series

def test_is_work_true():
    assert parse_text.is_work('https://archiveofourown.org/works/123') is True


def test_is_work_false():
    assert parse_text.is_work('https://archiveofourown.org/series/123') is False


def test_is_series_true():
    assert parse_text.is_series('https://archiveofourown.org/series/123') is True


def test_is_series_false():
    assert parse_text.is_series('https://archiveofourown.org/works/123') is False

# endregion


# region get_digits_after

def test_get_digits_after_stops_at_non_digit():
    assert parse_text.get_digits_after('/works/', '/works/42abc') == '42'


def test_get_digits_after_returns_none_when_test_absent():
    assert parse_text.get_digits_after('/works/', '/series/42') is None


def test_get_digits_after_returns_none_when_no_digits():
    assert parse_text.get_digits_after('/works/', '/works/abc') is None

# endregion


# region get_next_page

def test_get_next_page_adds_querystring_when_none_present():
    assert parse_text.get_next_page('https://example.com/foo') == 'https://example.com/foo?page=2'


def test_get_next_page_appends_to_existing_querystring():
    assert parse_text.get_next_page('https://example.com/foo?a=1') == 'https://example.com/foo?a=1&page=2'


def test_get_next_page_increments_existing_page_param():
    assert parse_text.get_next_page('https://example.com/foo?page=3') == 'https://example.com/foo?page=4'


def test_get_next_page_handles_9_to_10_boundary():
    # Catches a bug where get_num_from_link returns '1' instead of '9' if digit-range
    # extraction is off-by-one; replacing 'page=9' with 'page=10' should not touch 'page=99'.
    assert parse_text.get_next_page('https://example.com/foo?page=9') == 'https://example.com/foo?page=10'


def test_get_next_page_increments_multi_digit_page():
    assert parse_text.get_next_page('https://example.com/foo?page=99') == 'https://example.com/foo?page=100'

# endregion


# region get_page_number

def test_get_page_number_returns_1_when_no_page_param():
    assert parse_text.get_page_number('https://example.com/foo') == 1


def test_get_page_number_reads_existing_param():
    assert parse_text.get_page_number('https://example.com/foo?page=7') == 7


def test_get_page_number_reads_multi_digit():
    assert parse_text.get_page_number('https://example.com/foo?page=123&a=b') == 123

# endregion


# region chapters

def test_get_total_chapters_basic():
    text = 'Chapters: 3/10 Words: 5000'
    index = text.find('/')
    assert parse_text.get_total_chapters(text, index) == '10'


def test_get_current_chapters_basic():
    text = 'Chapters: 3/10 Words: 5000'
    index = text.find('/')
    assert parse_text.get_current_chapters(text, index) == '3'


def test_get_current_chapters_multi_digit():
    text = 'Chapters: 42/100 Words: 5000'
    index = text.find('/')
    assert parse_text.get_current_chapters(text, index) == '42'


def test_get_current_chapters_handles_index_0():
    # No characters before index 0, so we get an empty string back.
    assert parse_text.get_current_chapters('/10', 0) == ''

# endregion


# region get_payload

def test_get_payload_contains_expected_fields():
    payload = parse_text.get_payload('alice', 'hunter2', 'csrf-token')
    assert payload == {
        'user[login]': 'alice',
        'user[password]': 'hunter2',
        'user[remember_me]': '1',
        'authenticity_token': 'csrf-token',
    }

# endregion


# region get_title_dict

def test_get_title_dict_deduplicates_by_link():
    logs = [
        {'link': 'https://a/works/1', 'title': 'First'},
        {'link': 'https://a/works/1', 'title': 'Second'},
    ]
    result = parse_text.get_title_dict(logs)
    assert result == {'https://a/works/1': ['First']}


def test_get_title_dict_wraps_non_list_title_in_list():
    logs = [{'link': 'https://a/works/1', 'title': 'solo'}]
    result = parse_text.get_title_dict(logs)
    assert result == {'https://a/works/1': ['solo']}


def test_get_title_dict_preserves_list_titles():
    logs = [{'link': 'https://a/works/1', 'title': ['a', 'b']}]
    result = parse_text.get_title_dict(logs)
    assert result == {'https://a/works/1': ['a', 'b']}


def test_get_title_dict_ignores_entries_without_title_or_link():
    logs = [
        {'link': 'https://a/works/1'},
        {'title': 'orphan'},
        {'link': 'https://a/works/2', 'title': 'kept'},
    ]
    result = parse_text.get_title_dict(logs)
    assert result == {'https://a/works/2': ['kept']}

# endregion


# region get_unsuccessful_downloads

def test_get_unsuccessful_downloads_deduplicates():
    logs = [
        {'link': 'https://a/works/1', 'success': False},
        {'link': 'https://a/works/1', 'success': False},
        {'link': 'https://a/works/2', 'success': False},
    ]
    assert parse_text.get_unsuccessful_downloads(logs) == [
        'https://a/works/1', 'https://a/works/2',
    ]


def test_get_unsuccessful_downloads_ignores_success_entries():
    logs = [
        {'link': 'https://a/works/1', 'success': True},
        {'link': 'https://a/works/2', 'success': False},
    ]
    assert parse_text.get_unsuccessful_downloads(logs) == ['https://a/works/2']


def test_get_unsuccessful_downloads_ignores_entries_without_success_field():
    logs = [
        {'link': 'https://a/works/1'},
        {'link': 'https://a/works/2', 'success': False},
    ]
    assert parse_text.get_unsuccessful_downloads(logs) == ['https://a/works/2']


def test_get_unsuccessful_downloads_empty_list():
    assert parse_text.get_unsuccessful_downloads([]) == []

# endregion
