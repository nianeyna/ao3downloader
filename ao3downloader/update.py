import mobi
import ebooklib
import os
import pdfquery
import shutil

import xml.etree.ElementTree as ET
import ao3downloader.strings as strings

from bs4 import BeautifulSoup
from ebooklib import epub


def process_file(path: str, filetype: str, update: bool=True, update_series: bool=False) -> dict:
    '''add url of work to list if current version of work is incomplete'''

    if filetype == 'EPUB':
        xml = get_epub_preface(path)
        href = get_work_link_epub(xml)
        stats = get_stats_epub(xml)
        if update_series: series = get_series_epub(xml)

    elif filetype == 'HTML':
        with open(path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            href = get_work_link_html(soup)
            stats = get_stats_html(soup)
            if update_series: series = get_series_html(soup)

    elif filetype == 'AZW3':
        tempdir, filepath = mobi.extract(path)
        try:
            if os.path.splitext(filepath)[1].upper()[1:] != 'EPUB':
                # assuming all AO3 AZW3 files are packaged in the same way (why wouldn't they be?) 
                # we can take this as an indication that the source of this file was not AO3
                return None
            # the extracted epub is formatted the same way as the regular epubs, yay
            xml = get_epub_preface(filepath)
            href = get_work_link_epub(xml)
            stats = get_stats_epub(xml)
            if update_series: series = get_series_epub(xml)
        finally:
            # putting this in a finally block *should* ensure that 
            # I never accidentally leave temp files lying around
            # (unless mobi somehow messes up which I can't control)
            shutil.rmtree(tempdir) 

    elif filetype == 'MOBI':
        tempdir, filepath = mobi.extract(path)
        try:
            if os.path.splitext(filepath)[1].upper()[1:] != 'HTML':
                return None
            with open(filepath, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
                href = get_work_link_mobi(soup)
                stats = get_stats_mobi(soup)
                if update_series: series = get_series_mobi(soup)
        finally:
            shutil.rmtree(tempdir)

    elif filetype == 'PDF':
        pdf = pdfquery.PDFQuery(path, input_text_formatter='utf-8')
        try:
            pdf.load(0, 1, 2) # load the first 3 pages. please god no one has a longer tag wall than that.
        except StopIteration:
            pdf.load() # handle pdfs with fewer than 3 pages
        href = get_work_link_pdf(pdf)
        stats = get_stats_pdf(pdf)
        if update_series: series = get_series_pdf(pdf)

    else:
        raise ValueError('Invalid filetype argument: {}. Valid filetypes are '.format(filetype) + ','.join(strings.UPDATE_ACCEPTABLE_FILE_TYPES))

    # done with format-specific parsing, now we can proceed in the same way for all
    if href is None: return None # if this isn't a work from ao3, return
    
    # if we don't care whether the fic is incomplete, just return the work link
    if not update: return {'link': href}

    # if this is a series update, return the series links if any were found
    if update_series: return {'link': href, 'series': series} if series else None

    # otherwise continue checking for incomplete fics
    if stats is None: return None # if we can't find the series metadata, return

    # if the series metadata does not contain the character "/", return
    # we assume that the "/" character represents chapter count
    index = stats.find('/')
    if index == -1: return None

    # if the chapter counts do not match, we assume the work is incomplete
    totalchap = get_total_chapters(stats, index)
    currentchap = get_current_chapters(stats, index)

    # if the work is incomplete, return the info
    if currentchap != totalchap:
        return {'link': href, 'chapters': currentchap}


def get_epub_preface(path: str) -> ET.Element:
    book = epub.read_epub(path)
    preface = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))[0]
    content = preface.get_content().decode('utf-8')
    return ET.fromstring(content)


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


def get_series_epub(xml: ET.Element) -> list[str]:
    series = []
    for a in xml.iter('{http://www.w3.org/1999/xhtml}a'):
        href = a.get('href')
        if href and 'archiveofourown.org/series/' in href:
            series.append(href)
    return series


def get_work_link_html(soup: BeautifulSoup) -> str:
    msg = soup.select('#preface .message a')
    if msg and len(msg) == 2: # there should be exactly two links in here
        return msg[1].get('href') # we want the second one
    return None


def get_stats_html(soup: BeautifulSoup) -> str:
    stats = soup.select('#preface .meta .tags dd')
    for dd in stats:
        if 'Chapters: ' in dd.text:
            return dd.text
    return None


def get_series_html(soup: BeautifulSoup) -> list[str]:
    series = []
    links = soup.select('#preface .meta .tags dd a')
    for link in links:
        href = link.get('href')
        if href and 'archiveofourown.org/series/' in href:
            series.append(href)
    return series


def get_work_link_mobi(soup: BeautifulSoup) -> str:
    # it's ok if there are other work links in the file, because the relevant one will always be the first to appear
    # can't use a more specific selector because the html that comes out of the mobi parser is poorly formatted rip me
    link = soup.find('a', href=lambda x: x and 'archiveofourown.org/works/' in x)
    if link: return link.get('href')
    return None


def get_stats_mobi(soup: BeautifulSoup) -> str:
    stats = soup.find('blockquote', string=lambda x: x and 'Chapters: ' in x)
    if stats: return stats.text
    return None


def get_series_mobi(soup: BeautifulSoup) -> list[str]:
    series = []
    tag = soup.find('p', string=lambda x: x and x == 'Series:')
    if tag:
        block = tag.find_next_sibling('blockquote')
        if block:
            links = block.find_all('a', href=lambda x: x and 'archiveofourown.org/series/' in x)
            for link in links:
                series.append(link.get('href'))
    return series


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


def get_series_pdf(pdf: pdfquery.PDFQuery) -> list[str]:
    links = map(lambda x: x.attrib['URI'] if 'URI' in x.attrib else '', pdf.pq('Annot'))
    series = filter(lambda x: 'archiveofourown.org/series/' in x, links)
    return list(series)


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
