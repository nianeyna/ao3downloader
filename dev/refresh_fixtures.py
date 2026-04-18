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


FIXTURES = [
    # HTML fixtures
    {"name": "unlockedWork.html",         "url": "/works/41822007",                 "type": "html"},
    {"name": "explicitWorkLoggedIn.html", "url": "/works/20907563?view_adult=true", "type": "html"},
    {"name": "lockedWorkLoggedOut.html",  "url": "/works/185710",                   "type": "html"},
    {"name": "multipleSeries.html",       "url": "/works/41214669",                 "type": "html"},
    {"name": "bookmarks.html",            "url": "/users/nianeyna/bookmarks",       "type": "html"},
    {"name": "deletedWork.html",          "url": "/works/99999999999",              "type": "html"},
    {"name": "hiddenWork.html",           "url": "/works/47308798",                 "type": "html"},
    # EPUB fixtures
    {"name": "epubTest.epub",             "url": "/works/23009290",                 "type": "epub"},
    {"name": "incompleteWork.epub",       "url": "/works/218676",                   "type": "epub"},
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


def download_html(session, fixture, fixtures_dir):
    """Download an HTML fixture."""

    url = strings.AO3_BASE_URL + fixture["url"]
    text = make_request(session, url).text
    path = os.path.join(fixtures_dir, fixture["name"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def download_epub(session, fixture, fixtures_dir):
    """Download an EPUB fixture by fetching the work page and following the download link."""

    work_url = strings.AO3_BASE_URL + fixture["url"]
    response = make_request(session, work_url)
    soup = BeautifulSoup(response.text, "html.parser")
    download_url = parse_soup.get_download_link(soup, "EPUB")
    epub_response = make_request(session, download_url)
    path = os.path.join(fixtures_dir, fixture["name"])
    with open(path, "wb") as f:
        f.write(epub_response.content)


def main():
    parser = argparse.ArgumentParser(description="Download fresh test fixtures from live AO3.")
    parser.add_argument("--fixtures-dir", default=os.path.join("test", "fixtures"),
                        help="directory to write fixtures to (default: test/fixtures)")
    parser.add_argument("--delay", type=int, default=5,
                        help="seconds to wait between requests (default: 5)")
    args = parser.parse_args()

    os.makedirs(args.fixtures_dir, exist_ok=True)

    session = requests.Session()
    failed = []
    succeeded = []

    for i, fixture in enumerate(FIXTURES):
        name = fixture["name"]
        print(f"[{i + 1}/{len(FIXTURES)}] {name}...")

        try:
            if fixture["type"] == "html":
                download_html(session, fixture, args.fixtures_dir)
            elif fixture["type"] == "epub":
                download_epub(session, fixture, args.fixtures_dir)
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
