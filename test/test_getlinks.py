"""Tests for ao3downloader.actions.getlinks — csv column filtering."""

from ao3downloader.actions import getlinks


# region remove_empty_optional_columns

def _row(**overrides) -> dict:
    row = {
        'title': 'Some Work',
        'series': [],
        'updated': '01 Jan 2020',
        'date_bookmarked': '',
        'bookmarker_tags': [],
        'bookmarker_notes': '',
        'last_visited': '',
        'times_visited': '',
        'link': 'https://archiveofourown.org/works/99',
    }
    row.update(overrides)
    return row


def test_removes_optional_columns_when_empty_for_all_rows():
    rows = [_row(), _row(title='Another Work')]

    getlinks.remove_empty_optional_columns(rows)

    for row in rows:
        for column in getlinks.OPTIONAL_COLUMNS:
            assert column not in row
    # non-optional columns are kept even when empty
    assert all(row['series'] == [] for row in rows)
    assert all(row['updated'] == '01 Jan 2020' for row in rows)


def test_keeps_optional_column_when_any_row_has_data():
    rows = [_row(), _row(bookmarker_tags=['good stuff'])]

    getlinks.remove_empty_optional_columns(rows)

    # a column with data in any row is kept in every row
    assert rows[0]['bookmarker_tags'] == []
    assert rows[1]['bookmarker_tags'] == ['good stuff']
    # while columns that are empty everywhere are still removed
    assert all('last_visited' not in row for row in rows)


def test_handles_error_rows():
    error_row = {'error': 'traceback', 'link': 'https://archiveofourown.org/works/1'}
    rows = [error_row, _row(date_bookmarked='18 May 2026')]

    getlinks.remove_empty_optional_columns(rows)

    assert rows[0] == {'error': 'traceback', 'link': 'https://archiveofourown.org/works/1'}
    assert rows[1]['date_bookmarked'] == '18 May 2026'
    assert 'bookmarker_tags' not in rows[1]

# endregion
