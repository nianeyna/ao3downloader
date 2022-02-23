import ebooklib
import pdfquery
import xml.etree.ElementTree as ET
import ao3downloader.strings as strings

from bs4 import BeautifulSoup
from ebooklib import epub


def process_file(path: str, urls: list, filetype: str) -> None:
    '''add url of work to list if current version of work is incomplete'''

    if filetype == 'EPUB':
        book = epub.read_epub(path)
        preface = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))[0]
        content = preface.get_content().decode('utf-8')
        xml = ET.fromstring(content)
        href = get_work_link_epub(xml)
        stats = get_stats_epub(xml)
    elif filetype == 'HTML':
        with open(path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            href = get_work_link_html(soup)
            stats = get_stats_html(soup)
    elif filetype == 'PDF':
        pdf = pdfquery.PDFQuery(path, input_text_formatter='utf-8')
        if len(pdf._pages) >= 3:
            pdf.load(0, 1, 2) # load the first 3 pages. please god no one has a longer tag wall than that.
        else:
            pdf.load(0) # handle super short pdfs just in case
        href = get_work_link_pdf(pdf)
        stats = get_stats_pdf(pdf)
    else:
        raise ValueError('Invalid filetype argument: {}. Valid filetypes are '.format(filetype) + ','.join(strings.UPDATE_ACCEPTABLE_DOWNLOAD_TYPES))

    if href is None: return # if this isn't a work from ao3, return
    if stats is None: return # if we can't find the series metadata, return

    # if the series metadata does not contain the character "/", return
    # we assume that the "/" character represents chapter count
    index = stats.find('/')
    if index == -1: return

    # if the chapter counts do not match, we assume the work is incomplete
    totalchap = get_total_chapters(stats, index)
    currentchap = get_current_chapters(stats, index)

    # if the work is incomplete, add url to list
    if currentchap != totalchap:
        urls.append({'link': href, 'chapters': currentchap})


def get_work_link_epub(xml: ET.Element) -> str:
    # assumption: the xml does not contain any links to other works than the one we are interested in. 
    # since this file should not include user-generated html (such as summary) this should be safe.
    # that's a lot of shoulds but we'll let it go because I said so.
    for a in xml.iter('{http://www.w3.org/1999/xhtml}a'):
        href = a.get('href')
        if href and 'archiveofourown.org/works/' in href:
            return href
    return None


def get_stats_epub(xml: ET.Element) -> str:
    # ao3 stores chapter stats in a dd tag with class 'calibre5' for whatever reason.
    for dd in xml.iter('{http://www.w3.org/1999/xhtml}dd'):
        cls = dd.get('class')
        if cls and 'calibre5' in cls:
            return dd.text
    return None


def get_work_link_html(soup: BeautifulSoup) -> str:
    msg = soup.select('#preface .message a')
    if msg and len(msg) == 2:
        return msg[1].get('href')
    return None


def get_stats_html(soup: BeautifulSoup) -> str:
    stats = soup.select('#preface .meta .tags dd')
    for dd in stats:
        if 'Chapters: ' in dd.text:
            return dd.text
    return None


def get_work_link_pdf(pdf: pdfquery.PDFQuery) -> str:
    # assumption: work link is on the same line as preceding text. probably fine. ¯\_(ツ)_/¯
    # doing some weird string parsing here. considered taking a similar approach to the epub function
    # and parsing the xml tree for URIs. however that might break if someone linked another work in their summary.
    linktext = pdf.pq('LTTextLineHorizontal:contains("Posted originally on the Archive of Our Own at ")').text()
    workindex = linktext.find('/works/')
    endindex = linktext[workindex:].find('.')
    worknumber = linktext[workindex:workindex+endindex]
    return strings.AO3_BASE_URL + worknumber


def get_stats_pdf(pdf: pdfquery.PDFQuery) -> str:
    # assumption: chapter count is on same line as 'Chapters: '. reasonably safe because the 
    # preceding metadata is always going to be no longer than 'Published: yyyy-MM-dd Updated: yyyy-MM-dd '.
    # if someone puts 'Chapters: ' in their summary for some fool reason... I don't know, it might still work.
    return pdf.pq('LTTextLineHorizontal:contains("Chapters: ")').text()


def get_total_chapters(text: str, index: int) -> str:
    '''read characters after index until encountering a space.'''
    totalchap = ''
    for c in text[index+1:]:
        if c.isspace():
            break
        else:
            totalchap += c
    return totalchap


def get_current_chapters(text: str, index: int) -> str:
    ''' 
    reverse text before index, then read characters from beginning of reversed text 
    until encountering a space, then un-reverse the value you got. 
    we assume here that the text does not include unicode values.
    this should be safe because ao3 doesn't have localization... I think.
    '''
    currentchap = ''
    for c in reversed(text[:index]):
        if c.isspace():
            break
        else:
            currentchap += c
    currentchap = currentchap[::-1]
    return currentchap
