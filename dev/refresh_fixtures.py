"""Download fresh test fixtures from live AO3.

Used by the validate-fixtures GitHub Actions workflow to detect
when AO3's HTML structure changes in ways that affect parsing.

Fixtures tagged "login": True are fetched in a second pass using an
authenticated session (credentials from the AO3_USERNAME / AO3_PASSWORD
environment variables, supplied as GitHub secrets for the CI test account).
Logged-out fixtures still refresh with no credentials, so the script remains
usable for a logged-out-only refresh when no credentials are provided.
"""

import argparse
import os
import sys
from time import sleep

import requests
from bs4 import BeautifulSoup

from ao3downloader import exceptions, parse_soup, strings
from ao3downloader.repo import Repository
from ao3downloader.parse_text import get_work_number, get_payload


class RefreshAbortedException(Exception):
    """Raised when the runner itself appears to be blocked, making further requests pointless."""


FIXTURES = [
    # # currently has to be updated manually - the refresh script never picks up the gate page, for some reason
    # {"name": "explicitWorkLoggedOut.html", "url": "/works/20907563",                   "type": "page"},

    # logged-out pages
    {"name": "bookmarks.html",             "url": "/users/ao3downloader_ci/bookmarks", "type": "page"},
    {"name": "deletedWork.html",           "url": "/works/99999999999",                "type": "page"},
    {"name": "hiddenWork.html",            "url": "/works/47308798",                   "type": "page"},
    {"name": "lockedWorkLoggedOut.html",   "url": "/works/185710",                     "type": "page"},
    {"name": "multipleSeries.html",        "url": "/works/41214669",                   "type": "page"},
    {"name": "unlockedWork.html",          "url": "/works/41822007",                   "type": "page"},
    {"name": "unlockedWorkNoSkin.html",    "url": "/works/23009290",                   "type": "page"},

    # logged-out ebooks
    {"name": "incompleteWork.epub",        "url": "/works/218676",                     "type": "book"},
    {"name": "incompleteWork.pdf",         "url": "/works/218676",                     "type": "book"},
    {"name": "incompleteWork.mobi",        "url": "/works/218676",                     "type": "book"},
    {"name": "incompleteWork.azw3",        "url": "/works/218676",                     "type": "book"},
    {"name": "incompleteWork.html",        "url": "/works/218676",                     "type": "book"},
    {"name": "workInSeries.epub",          "url": "/works/334557",                     "type": "book"},
    {"name": "workInSeries.pdf",           "url": "/works/334557",                     "type": "book"},
    {"name": "workInSeries.mobi",          "url": "/works/334557",                     "type": "book"},
    {"name": "workInSeries.azw3",          "url": "/works/334557",                     "type": "book"},
    {"name": "workInSeries.html",          "url": "/works/334557",                     "type": "book"},
    {"name": "tagWall.pdf",                "url": "/works/20907563",                   "type": "book"},
    {"name": "epubTest.epub",              "url": "/works/23009290",                   "type": "book"},
    {"name": "pdfTest.pdf",                "url": "/works/23009290",                   "type": "book"},
    {"name": "mobiTest.mobi",              "url": "/works/23009290",                   "type": "book"},
    {"name": "azw3Test.azw3",              "url": "/works/23009290",                   "type": "book"},
    {"name": "htmlTest.html",              "url": "/works/23009290",                   "type": "book"},

    # logged-in pages
    # explicitWorkLoggedIn.html requires test account to have show adult content without warning setting enabled
    {"name": "explicitWorkLoggedIn.html",  "url": "/works/20907563",                               "type": "page", "login": True},
    {"name": "lockedWorkLoggedIn.html",    "url": "/works/185710",                                 "type": "page", "login": True}, 
    {"name": "markedForLater.html",        "url": "/works/66326125",                               "type": "page", "login": True},
    {"name": "markedForLaterList.html",    "url": "/users/ao3downloader_ci/readings?show=to-read", "type": "page", "login": True},
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
    '.menu',
    'script',
]

USER_AGENT = "ao3downloader-ci (+https://github.com/nianeyna/ao3downloader)"
TIMEOUT = 60
MAX_RETRIES = 10
CLOUDFLARE_ABORT_THRESHOLD = 3
CLOUDFLARE_DIAGNOSTIC_HEADERS = ("cf-ray", "cf-mitigated", "server")


def cloudflare_diagnostics(response: requests.Response) -> str:
    """Summarize identifying headers from a challenge response."""

    present = [f"{name}={response.headers[name]}" for name in CLOUDFLARE_DIAGNOSTIC_HEADERS
               if name in response.headers]
    return ", ".join(present) if present else "no cloudflare headers present"


def make_request(session, url, method="GET", data=None):
    """Make a request with retry logic for errors, 5xx, 429, and cloudflare responses."""

    for attempt in range(MAX_RETRIES + 1):
        delay = 0.1 * (2 ** attempt)

        try:
            response = session.request(method, url, data=data,
                                       headers={"user-agent": USER_AGENT}, timeout=TIMEOUT)
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
            diagnostics = cloudflare_diagnostics(response)
            if attempt < MAX_RETRIES:
                print(f"  cloudflare response ({diagnostics}), retrying in {delay:.1f}s...")
                sleep(delay)
                continue
            raise exceptions.CloudflareException(
                f"cloudflare response after {MAX_RETRIES} retries ({diagnostics})")

        return response

    raise Exception(f"exhausted all {MAX_RETRIES} retries")


def login(session, username, password):
    """Authenticate the session against AO3 so login-gated fixtures can be fetched.

    Reuses the same parsing helpers as Repository.login so the token extraction and
    logged-in detection stay single-sourced. Raises if credentials are rejected.
    """

    soup = BeautifulSoup(make_request(session, strings.AO3_LOGIN_URL).text, "html.parser")
    token = parse_soup.get_login_token(soup)
    payload = get_payload(username, password, token)
    response = make_request(session, strings.AO3_LOGIN_URL, method="POST", data=payload)
    if not parse_soup.is_logged_in(BeautifulSoup(response.text, "html.parser")):
        raise Exception("AO3 login failed - check the AO3_USERNAME / AO3_PASSWORD secrets "
                        "and that the CI account credentials are valid")


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


def ebook_current_path(fixtures_dir: str, fixture: dict[str, str]) -> str:
    """Compute the current-file path for an ebook fixture: ebook/<work_id>/current/<name>."""

    work_id = str(get_work_number(fixture["url"]))
    return os.path.join(fixtures_dir, "ebook", work_id, "current", fixture["name"])


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


def process_fixtures(fixtures, session, args, failed: list[str], succeeded: list[str]):
    """Download a group of fixtures with the given session, recording outcomes.

    Each group gets its own caches so the same work URL can be fetched in both a
    logged-out and a logged-in pass without one pass returning the other's cached page.

    Raises RefreshAbortedException after CLOUDFLARE_ABORT_THRESHOLD consecutive
    cloudflare-blocked fixtures. Each blocked fixture already represents 10 straight
    challenge responses, so at that point the runner itself is presumed blocked and
    attempting the rest would just push the job into its timeout.
    """

    page_cache: dict[str, requests.Response] = {}
    soup_cache: dict[str, BeautifulSoup] = {}
    consecutive_cloudflare = 0

    for i, fixture in enumerate(fixtures):
        name = fixture["name"]
        print(f"[{i + 1}/{len(fixtures)}] {name}...")

        try:
            if fixture["type"] == "page":
                download_html(session, fixture, args.fixtures_dir, args.only_new, page_cache)
            else:
                download_book(session, fixture, args.fixtures_dir, args.only_new, page_cache, soup_cache)
            succeeded.append(name)
            consecutive_cloudflare = 0
            print(f"  ok")
        except exceptions.CloudflareException as e:
            failed.append(name)
            consecutive_cloudflare += 1
            print(f"  FAILED: {e}")
            if consecutive_cloudflare >= CLOUDFLARE_ABORT_THRESHOLD:
                raise RefreshAbortedException(
                    f"{consecutive_cloudflare} fixtures in a row got cloudflare challenges "
                    "on every attempt - the runner appears to be blocked")
        except Exception as e:
            failed.append(name)
            consecutive_cloudflare = 0
            print(f"  FAILED: {e}")

        if i < len(fixtures) - 1:
            sleep(args.delay)


def main():
    parser = argparse.ArgumentParser(description="Download fresh test fixtures from live AO3.")
    parser.add_argument("--fixtures-dir", default=os.path.join("test", "fixtures"),
                        help="directory to write fixtures to (default: test/fixtures)")
    parser.add_argument("--delay", type=int, default=5,
                        help="seconds to wait between requests (default: 5)")
    parser.add_argument("--only-new", action="store_true",
                        help="only download fixtures that don't exist yet")
    parser.add_argument("--require-login", action="store_true",
                        help="fail if the login-gated fixtures cannot be refreshed "
                             "because of missing credentials. Used by CI.")
    args = parser.parse_args()

    os.makedirs(args.fixtures_dir, exist_ok=True)

    logged_out = [f for f in FIXTURES if not f.get("login")]
    logged_in = [f for f in FIXTURES if f.get("login")]
    failed: list[str] = []
    succeeded: list[str] = []

    try:
        # phase 1: logged-out fixtures
        process_fixtures(logged_out, requests.Session(), args, failed, succeeded)

        # phase 2: logged-in fixtures, with a separate session so the locked/explicit work
        # URLs can be fetched logged in (content) as well as logged out (gate page) above.
        if logged_in:
            username = os.environ.get("AO3_USERNAME")
            password = os.environ.get("AO3_PASSWORD")
            if username and password:
                print()
                print(f"logging in as {username}...")
                session = requests.Session()
                try:
                    login(session, username, password)
                    print("  ok")
                except Exception as e:
                    print(f"  FAILED: {e}")
                    failed.extend(f["name"] for f in logged_in)
                else:
                    process_fixtures(logged_in, session, args, failed, succeeded)
            elif args.require_login:
                print()
                print("ERROR: --require-login was set but AO3_USERNAME / AO3_PASSWORD are not set")
                failed.extend(f["name"] for f in logged_in)
            else:
                print()
                print("no credentials provided, skipping logged-in fixtures: "
                      + ", ".join(f["name"] for f in logged_in))
    except RefreshAbortedException as e:
        attempted = set(succeeded) | set(failed)
        skipped = [f["name"] for f in FIXTURES if f["name"] not in attempted]
        print()
        print(f"ABORTED: {e}")
        if skipped:
            print(f"not attempted: {', '.join(skipped)}")

    print()
    print(f"{len(succeeded)} succeeded, {len(failed)} failed")
    if failed:
        print(f"failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
