from unittest.mock import MagicMock

from ao3downloader.repo import Repository


def make_response(server='', content_type='text/html', url='https://archiveofourown.org/works/123', text=''):
    response = MagicMock()
    response.headers = {'Server': server, 'Content-Type': content_type}
    response.url = url
    response.text = text
    return response


def test_cloudflare_challenge_page():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>Just a moment...</title></head></html>')
    assert Repository.is_cloudflare_response(response) == True


def test_cloudflare_attention_required():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>Attention Required!</title></head></html>')
    assert Repository.is_cloudflare_response(response) == True


def test_cloudflare_access_denied():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>Access denied</title></head></html>')
    assert Repository.is_cloudflare_response(response) == True


def test_cloudflare_wrapper_div():
    response = make_response(
        server='cloudflare',
        text='<html><body><div id="cf-wrapper">challenge</div></body></html>')
    assert Repository.is_cloudflare_response(response) == True


def test_normal_ao3_page():
    response = make_response(
        server='Apache',
        text='<html><head><title>A Work - Chapter 1</title></head></html>')
    assert Repository.is_cloudflare_response(response) == False


def test_ao3_behind_cloudflare_but_normal_page():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>A Work - Chapter 1</title></head><body><div id="main"></div></body></html>')
    assert Repository.is_cloudflare_response(response) == False


def test_normal_download():
    response = make_response(
        server='cloudflare',
        content_type='application/epub+zip',
        url='https://archiveofourown.org/downloads/123/work.epub',
        text='')
    assert Repository.is_cloudflare_response(response) == False


def test_no_server_header():
    response = make_response(
        server='',
        text='<html><head><title>Just a moment...</title></head></html>')
    assert Repository.is_cloudflare_response(response) == False


def test_cloudflare_challenge_script():
    response = make_response(
        server='cloudflare',
        text='<html><head><title>Unknown Title</title></head>'
             '<body><script>window._cf_chl_opt = {cvId: "3"};</script></body></html>')
    assert Repository.is_cloudflare_response(response) == True
