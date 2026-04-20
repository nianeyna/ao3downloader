"""Download fresh test fixtures from live AO3.

Used by the validate-fixtures GitHub Actions workflow to detect
when AO3's HTML structure changes in ways that affect parsing.
Only works for logged-out pages that do not require fresh cookies.
"""

import argparse
import os
import sys
from time import sleep

import requests
from bs4 import BeautifulSoup

from ao3downloader import parse_soup, strings
from ao3downloader.repo import Repository
from ao3downloader.parse_text import get_work_number


FIXTURES = [
    {"name": "unlockedWork.html",         "url": "/works/41822007",                 "type": "page"},
    {"name": "unlockedWorkNoSkin.html",   "url": "/works/23009290",                 "type": "page"},
    {"name": "explicitWorkLoggedIn.html", "url": "/works/20907563?view_adult=true", "type": "page"},
    {"name": "lockedWorkLoggedOut.html",  "url": "/works/185710",                   "type": "page"},
    {"name": "multipleSeries.html",       "url": "/works/41214669",                 "type": "page"},
    {"name": "bookmarks.html",            "url": "/users/nianeyna/bookmarks",       "type": "page"},
    {"name": "deletedWork.html",          "url": "/works/99999999999",              "type": "page"},
    {"name": "hiddenWork.html",           "url": "/works/47308798",                 "type": "page"},
    {"name": "epubTest.epub",             "url": "/works/23009290",                 "type": "book"},
    {"name": "pdfTest.pdf",               "url": "/works/23009290",                 "type": "book"},
    {"name": "mobiTest.mobi",             "url": "/works/23009290",                 "type": "book"},
    {"name": "azw3Test.azw3",             "url": "/works/23009290",                 "type": "book"},
    {"name": "htmlTest.html",             "url": "/works/23009290",                 "type": "book"},
    {"name": "incompleteWork.epub",       "url": "/works/218676",                   "type": "book"},
    {"name": "incompleteWork.pdf",        "url": "/works/218676",                   "type": "book"},
    {"name": "incompleteWork.mobi",       "url": "/works/218676",                   "type": "book"},
    {"name": "incompleteWork.azw3",       "url": "/works/218676",                   "type": "book"},
    {"name": "incompleteWork.html",       "url": "/works/218676",                   "type": "book"},
    {"name": "workInSeries.epub",         "url": "/works/334557",                   "type": "book"},
    {"name": "workInSeries.pdf",          "url": "/works/334557",                   "type": "book"},
    {"name": "workInSeries.mobi",         "url": "/works/334557",                   "type": "book"},
    {"name": "workInSeries.azw3",         "url": "/works/334557",                   "type": "book"},
    {"name": "workInSeries.html",         "url": "/works/334557",                   "type": "book"},
    {"name": "tagWall.pdf",               "url": "/works/20907563?view_adult=true", "type": "book"},
]

IGNORED_SELECTORS = [
    '[name="csrf-token"]',
    '[name="authenticity_token"]',
    '[aria-hidden="true"]',
    '#site_search_tooltip',
    '.kudos',
    '.hits',
    '.bookmarks',
    '.status',
    '.stats',
    'script',
]

USER_AGENT = "ao3downloader-ci (+https://github.com/nianeyna/ao3downloader)"
TIMEOUT = 60
MAX_RETRIES = 10


def make_request(session, url):
    """Make a request with retry logic for errors, 5xx, 429, and cloudflare responses."""

    for attempt in range(MAX_RETRIES + 1):
        delay = 0.1 * (2 ** attempt)

        try:
            response = session.get(url, headers={"user-agent": USER_AGENT}, timeout=TIMEOUT)
        except requests.RequestException as e:
            if attempt < MAX_RETRIES:
                print(f"  {e.__class__.__name__}, retrying in {delay:.1f}s...")
                sleep(delay)
                continue
            raise

        if response.status_code in Repository.retry_statuses:
            if attempt < MAX_RETRIES:
                print(f"  got {response.status_code}, retrying in {delay:.1f}s...")
                sleep(delay)
                continue
            raise Exception(f"got {response.status_code} after {MAX_RETRIES} retries")

        if response.status_code == 429:
            try:
                pause_time = int(response.headers["retry-after"])
            except (KeyError, ValueError):
                pause_time = 300
            if pause_time <= 0:
                pause_time = 300
            print(f"  rate limited, waiting {pause_time}s...")
            sleep(pause_time)
            continue

        if Repository.is_cloudflare_response(response):
            if attempt < MAX_RETRIES:
                print(f"  cloudflare response, retrying in {delay:.1f}s...")
                sleep(delay)
                continue
            raise Exception(f"cloudflare response after {MAX_RETRIES} retries")

        return response

    raise Exception(f"exhausted all {MAX_RETRIES} retries")


def fetch_work_page(session, url_path: str, cache: dict[str, requests.Response]) -> requests.Response:
    """Fetch a work page, caching the response so each unique URL is fetched at most once."""

    if url_path not in cache:
        cache[url_path] = make_request(session, strings.AO3_BASE_URL + url_path)
    return cache[url_path]


def download_html(session, fixture, fixtures_dir, only_new, page_cache: dict[str, requests.Response]):
    """Download an HTML fixture."""

    path = os.path.join(fixtures_dir, fixture["name"])
    if only_new and os.path.exists(path):
        print('fixture already exists, skipping')
        return
    text = fetch_work_page(session, fixture["url"], page_cache).text
    if (fixture['type'] == 'page' and not meaningful_change(text, path)):
        print(f'no meaningful changes in {fixture["name"]}, skipping')
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def ebook_current_path(fixtures_dir: str, fixture: dict) -> str:
    """Compute the current-file path for an ebook fixture: ebook/<work_id>/current/<name>."""

    return os.path.join(fixtures_dir, 'ebook', get_work_number(fixture['url']),
                        'current', fixture['name'])


def meaningful_change(text, path):
    if not os.path.exists(path):
        return True
    with open(path, 'r', encoding='utf-8') as f:
        existing = f.read()
    old_soup = BeautifulSoup(existing, 'html.parser')
    new_soup = BeautifulSoup(text, 'html.parser')

    def strip(soup):
        for selector in IGNORED_SELECTORS:
            for element in soup.select(selector):
                element.decompose()

    strip(old_soup)
    strip(new_soup)
    return str(old_soup) != str(new_soup)


def download_book(session, fixture, fixtures_dir, only_new,
                  page_cache: dict[str, requests.Response],
                  soup_cache: dict[str, BeautifulSoup]):
    """Download an ebook fixture by fetching the work page and following the download link.

    Ebook fixtures live in `ebook/<work_id>/current/<name>`. If the freshly-downloaded
    bytes match the existing current file, skip writing (keeps git diff clean for
    byte-identical refreshes). On meaningful changes the CI workflow decides whether
    to archive the prior version — this function only writes the new `current/` file.
    """

    path = ebook_current_path(fixtures_dir, fixture)
    if only_new and os.path.exists(path):
        print('fixture already exists, skipping')
        return
    url_path = fixture["url"]
    if url_path not in soup_cache:
        response = fetch_work_page(session, url_path, page_cache)
        soup_cache[url_path] = BeautifulSoup(response.text, "html.parser")
    soup = soup_cache[url_path]
    ext = os.path.splitext(fixture['name'])[1].upper()[1:]
    download_url = parse_soup.get_download_link(soup, ext)
    book_response = make_request(session, download_url)
    new_bytes = book_response.content
    if os.path.exists(path):
        with open(path, "rb") as f:
            existing_bytes = f.read()
        if existing_bytes == new_bytes:
            print(f'no changes in {fixture["name"]}, skipping')
            return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(new_bytes)


def main():
    parser = argparse.ArgumentParser(description="Download fresh test fixtures from live AO3.")
    parser.add_argument("--fixtures-dir", default=os.path.join("test", "fixtures"),
                        help="directory to write fixtures to (default: test/fixtures)")
    parser.add_argument("--delay", type=int, default=5,
                        help="seconds to wait between requests (default: 5)")
    parser.add_argument("--only-new", type=bool, default=False,
                        help="whether to only download fixtures that don't exist yet (default: false)")
    args = parser.parse_args()

    os.makedirs(args.fixtures_dir, exist_ok=True)

    session = requests.Session()
    page_cache: dict[str, requests.Response] = {}
    soup_cache: dict[str, BeautifulSoup] = {}
    failed = []
    succeeded = []

    for i, fixture in enumerate(FIXTURES):
        name = fixture["name"]
        print(f"[{i + 1}/{len(FIXTURES)}] {name}...")

        try:
            if fixture["type"] == "page":
                download_html(session, fixture, args.fixtures_dir, args.only_new, page_cache)
            else:
                download_book(session, fixture, args.fixtures_dir, args.only_new, page_cache, soup_cache)
            succeeded.append(name)
            print(f"  ok")
        except Exception as e:
            failed.append(name)
            print(f"  FAILED: {e}")

        if i < len(FIXTURES) - 1:
            sleep(args.delay)

    print()
    print(f"{len(succeeded)} succeeded, {len(failed)} failed")
    if failed:
        print(f"failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
