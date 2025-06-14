import os

import ao3downloader.parse_text as parse_text


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
