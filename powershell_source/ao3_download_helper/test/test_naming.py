"""A work's file is named, and read back, by settings.ini's FileNamePattern.

Its four parts - {worknum}, {title}, {author}, {date} - are each there once, in any order, with
a separator between each. The number pairs a file with its index entry and the date is the
version it holds, so neither is ever trimmed: the title and the author are shortened instead.
"""

import os

import pytest

from source_code import naming, parse_text, server, settings_file, strings
from source_code.actions import shared

AO3_ORDER = '{title} - {author} - {worknum} {date}'
META = {'worknum': '12345678', 'title': 'My Favorite Fic', 'author': 'AuthorName'}

# region what a pattern may be

@pytest.mark.parametrize('text', [
    naming.DEFAULT,
    AO3_ORDER,
    '{date}_{worknum}_{author}_{title}',
    '{worknum} ~ {title} by {author} ({date}',
])
def test_every_order_of_the_four_parts_is_a_pattern(text):
    assert naming.parse(text).text == text


@pytest.mark.parametrize('text, problem', [
    ('{worknum} {title} - {author}', 'needs every part'),
    ('{worknum} {title} - {author} {date} {title}', 'more than once'),
    ('{worknum}{title} - {author} {date}', 'needs a separator'),
    ('{worknum} {title} - {fandom} {date}', 'not a part'),
    ('Fic {worknum} {title} - {author} {date}', 'start with one of its parts'),
    ('{worknum} {title} - {author} {date}.', 'end with one of its parts'),
    ('{worknum} {title} 2 {author} {date}', 'digit'),
    ('{worknum} {title} : {author} {date}', 'cannot'),
    ('{worknum} {title} ------------ {author} {date}', 'at most'),
])
def test_a_pattern_the_app_could_not_read_names_by_is_refused(text, problem):
    with pytest.raises(ValueError, match=problem):
        naming.parse(text)


def test_a_misspelt_setting_leaves_the_default_rather_than_unreadable_names():
    assert naming.use('{worknum} {title}').text == naming.DEFAULT


def test_settings_ini_never_takes_a_pattern_it_could_not_read():
    setting = {'key': strings.INI_NAME_PATTERN, 'kind': settings_file.TEXT}
    assert settings_file.checked_value(setting, AO3_ORDER) == AO3_ORDER
    with pytest.raises(ValueError):
        settings_file.checked_value(setting, '{title} {date}')

# endregion

# region names written

def test_the_default_names_a_work_as_it_always_has():
    assert naming.file_stem(META, '2026-05-10', 0) == '12345678 My Favorite Fic - AuthorName 2026-05-10'
    assert naming.file_stem(META, '', 0) == '12345678 My Favorite Fic - AuthorName'


def test_a_work_is_named_in_the_patterns_order():
    pattern = naming.parse(AO3_ORDER)
    assert naming.file_stem(META, '2026-05-10', 0, pattern) == \
        'My Favorite Fic - AuthorName - 12345678 2026-05-10'


def test_an_empty_part_is_left_out_with_its_separator():
    assert naming.file_stem({**META, 'author': ''}, '2026-05-10', 0) == '12345678 My Favorite Fic 2026-05-10'


def parts_of(stem):
    title, author = stem[len('12345678 '):-len(' 2026-05-10')].split(' - ')
    return title, author


def test_a_long_title_is_shortened_only_as_far_as_the_name_needs_and_the_author_is_kept():
    stem = naming.file_stem({**META, 'title': 'T' * 40, 'author': 'Author'}, '2026-05-10', 50)
    # 8 + 1 + title + 3 + 6 + 1 + 10 = 50 leaves the title 21
    assert len(stem) == 50 and parts_of(stem) == ('T' * 21, 'Author')


def test_the_author_gives_way_only_once_the_title_is_down_to_20_and_only_as_far_as_needed():
    # 8 + 1 + 20 + 3 + 15 + 1 + 10 = 58: the author loses 3 to fit 55
    stem = naming.file_stem({**META, 'title': 'T' * 40, 'author': 'A' * 15}, '2026-05-10', 55)
    assert len(stem) == 55 and parts_of(stem) == ('T' * 20, 'A' * 12)


def test_with_both_at_their_floors_and_still_too_long_the_longer_gives_way():
    # at 20 and 10 the name is 53; the title, the longer, loses 3 more to fit 50
    stem = naming.file_stem({**META, 'title': 'T' * 40, 'author': 'A' * 15}, '2026-05-10', 50)
    assert len(stem) == 50 and parts_of(stem) == ('T' * 17, 'A' * 10)


def test_below_both_floors_the_longer_gives_way_and_the_number_and_date_never_do():
    stem = naming.file_stem({**META, 'title': 'T' * 80, 'author': 'A' * 40}, '2026-05-10', 40)
    assert len(stem) <= 40
    assert stem.startswith('12345678 ') and stem.endswith(' 2026-05-10')
    title, author = parts_of(stem)
    assert len(title) <= 20 and len(author) <= 10

# endregion

# region names read back

@pytest.mark.parametrize('text', [naming.DEFAULT, AO3_ORDER, '{date}_{worknum}_{author}_{title}'])
def test_a_name_written_by_a_pattern_is_read_back_by_it(text):
    naming.use(text)
    name = naming.file_stem(META, '2026-05-10', 0) + '.epub'

    assert parse_text.get_work_file_number(name) == '12345678'
    assert parse_text.get_date_from_filename(name) == '2026-05-10'
    # undated, the number is still read and there is no date
    undated = naming.file_stem(META, '', 0) + '.epub'
    assert parse_text.get_work_file_number(undated) == '12345678'
    assert parse_text.get_date_from_filename(undated) is None


def test_a_name_with_no_author_before_its_date_has_that_date_not_an_author_called_it():
    # an anonymous work's file, its author left empty with the separator kept
    name = '11418339 Luke Skywalker 19 Full human - 2026-08-02.html'
    assert parse_text.get_date_from_filename(name) == '2026-08-02'
    assert naming.read(name) == {'worknum': '11418339', 'title': 'Luke Skywalker 19 Full human',
                                 'author': '', 'date': '2026-08-02'}
    # only a real date: anything else is still the author
    assert parse_text.get_date_from_filename('1 A - 2026-02-31.html') is None
    assert naming.read('1 A - Author.html')['author'] == 'Author'


@pytest.mark.parametrize('name', [
    '7 Title only 2026-08-02.html',
    '7 Title - With - Dashes - 2026-08-02.html',
    '7 Title - Author - Someone Else 2026-08-02.epub',
    '7 - 2026-08-02.html',
])
def test_the_number_and_the_date_are_read_whatever_the_title_and_author_look_like(name):
    # the number finds the entry and the date says which version the file holds - the title and
    # author never decide whether either is read
    assert parse_text.get_work_file_number(name) == '7'
    assert parse_text.get_date_from_filename(name) == '2026-08-02'


def test_a_name_in_another_order_is_not_a_work_until_renamed():
    naming.use(AO3_ORDER)
    # named the old way: the number leads, where this pattern does not put it
    assert parse_text.get_work_file_number('12345678 My Favorite Fic - AuthorName 2026-05-10.epub') is None


def test_a_date_written_another_way_is_only_ever_a_guess_whatever_the_pattern():
    naming.use(AO3_ORDER)
    name = 'My Favorite Fic - AuthorName - 12345678 (10 May 2026).epub'
    assert parse_text.get_date_from_filename(name) is None
    assert parse_text.infer_date_from_filename(name) == '2026-05-10'


def test_a_number_at_the_end_is_never_read_as_a_guessed_date():
    naming.use('{title} - {author} - {worknum} {date}')
    assert parse_text.infer_date_from_filename('Fic - A - 20240304.epub') == ''


def test_the_index_files_names_always_start_with_the_number():
    naming.use(AO3_ORDER)
    assert parse_text.get_work_number_from_filename('12345678 My Favorite Fic - AuthorName.json') == '12345678'


def test_a_scan_of_the_library_reads_works_by_the_pattern(fake_fileops):
    naming.use(AO3_ORDER)
    works = os.path.join(fake_fileops.downloadfolder, strings.WORKS_FOLDER_NAME)
    os.makedirs(works, exist_ok=True)
    for name in ('My Favorite Fic - AuthorName - 12345678 2026-05-10.epub',
                 '12345678 My Favorite Fic - AuthorName 2026-01-01.epub'):
        open(os.path.join(works, name), 'w').close()

    found = shared.scan_downloaded_works(fake_fileops.downloadfolder, ['EPUB'])

    # only the file named by the pattern is a copy of the work, and its date is certain
    assert found['12345678']['EPUB']['date'] == '2026-05-10'
    assert not found['12345678']['EPUB'].get('older')

# endregion

# region the page and the helper agree

def test_the_page_is_told_the_pattern_and_names_files_by_it(tmp_path, monkeypatch):
    ini = tmp_path / 'settings.ini'
    ini.write_text('[settings]\nFileNamePattern=' + AO3_ORDER + '\nFileNameLength=0\n')
    fileops = server.FileOps()
    monkeypatch.setattr(fileops, 'inifile', str(ini))

    assert server.read_settings(fileops)['fileNamePattern'] == AO3_ORDER
    # a file with no index entry, dated from the page with the parts it read from the name
    assert server.file_names_for([{'name': 'whatever.html', 'date': '2026-05-10',
                                   'parts': {'worknum': '1', 'title': 'T', 'author': 'A'}}], 0) == \
        ['T - A - 1 2026-05-10.html']

# endregion
