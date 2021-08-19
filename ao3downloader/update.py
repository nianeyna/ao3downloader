import xml.etree.ElementTree as ET

import ebooklib
from ebooklib import epub


def process_epub(path, urls):
    '''add url of work to list if current version of work is incomplete'''

    # get front matter of epub in xml format
    book = epub.read_epub(path)
    preface = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))[0]
    content = preface.get_content().decode('utf-8')
    xml = ET.fromstring(content)

    # if this isn't a work from ao3, return
    href = get_work_link(xml)
    if href is None: return

    # if we can't find the series metadata, return
    stats = get_calibre5_content(xml)
    if stats is None: return

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


def get_work_link(xml):
    ''' 
    we assume that the xml does not contain any links to other works than the one we are interested in. 
    since this file should not include user-generated html (such as summary) this should be safe.
    that's a lot of shoulds but we'll let it go because I said so.
    '''
    for a in xml.iter('{http://www.w3.org/1999/xhtml}a'):
        href = a.get('href')
        if href and 'archiveofourown.org/works/' in href:
            return href
    return None


def get_calibre5_content(xml):
    '''ao3 stores chapter stats in a dd tag with class 'calibre5' for whatever reason.'''
    for dd in xml.iter('{http://www.w3.org/1999/xhtml}dd'):
        cls = dd.get('class')
        if cls and 'calibre5' in cls:
            return dd.text
    return None


def get_total_chapters(text, index):
    '''read characters after index until encountering a space.'''
    totalchap = ''
    for c in text[index+1:]:
        if c.isspace():
            break
        else:
            totalchap += c
    return totalchap


def get_current_chapters(text, index):
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
