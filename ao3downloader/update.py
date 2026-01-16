import os
import shutil
import xml.etree.ElementTree as ET
import zipfile

import mobi
import pdfquery
from bs4 import BeautifulSoup

from ao3downloader import parse_pdf, parse_soup, parse_text, parse_xml, strings


def process_file(path: str, filetype: str, update: bool=True, update_series: bool=False) -> dict:
    """
    given an input work, checks if it's incomplete then returns the work link and number of downloaded chapters if it is
    in the case of series updates, the function instead returns the series link(s) that the input work is in
    """

    # Retrieve information from an EPUB file
    if filetype == 'EPUB':
        xml = get_epub_preface(path)
        # if the preface is not found at the expected location, we assume this is not an AO3 epub and skip it
        if xml is None: return None

        # get either the series information, or the work stats (depending on the function inputs)
        href = parse_xml.get_work_link_epub(xml)
        if update_series: series = parse_xml.get_series_epub(xml)
        else: stats = parse_xml.get_stats_epub(xml)

    # Retrieve information from an HTML file
    elif filetype == 'HTML':
        with open(path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')

            # get either the series information, or the work stats (depending on the function inputs)
            href = parse_soup.get_work_link_html(soup)
            if update_series: series = parse_soup.get_series_html(soup)
            else: stats = parse_soup.get_stats_html(soup)

    # Retrieve information from an AZW3 file
    elif filetype == 'AZW3':
        tempdir, filepath = mobi.extract(path)
        try:
            if os.path.splitext(filepath)[1].upper()[1:] != 'EPUB':
                # assuming all AO3 AZW3 files are packaged in the same way (why wouldn't they be?) 
                # we can take this as an indication that the source of this file was not AO3
                return None

            # the extracted epub is formatted the same way as the regular epubs, yay
            xml = get_epub_preface(filepath)
            if xml is None: return None

            # get either the series information, or the work stats (depending on the function inputs)
            href = parse_xml.get_work_link_epub(xml)
            if update_series: series = parse_xml.get_series_epub(xml)
            else: stats = parse_xml.get_stats_epub(xml)

        finally:
            # putting this in a finally block *should* ensure that 
            # I never accidentally leave temp files lying around
            # (unless mobi somehow messes up which I can't control)
            shutil.rmtree(tempdir) 

    # Retrieve information from a MOBI file
    elif filetype == 'MOBI':
        tempdir, filepath = mobi.extract(path)
        try:
            if os.path.splitext(filepath)[1].upper()[1:] != 'HTML':
                return None
            with open(filepath, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')

                # get either the series information, or the work stats (depending on the function inputs)
                href = parse_soup.get_work_link_mobi(soup)
                if update_series: series = parse_soup.get_series_mobi(soup)
                else: stats = parse_soup.get_stats_mobi(soup)

        finally:
            shutil.rmtree(tempdir)

    # Retrieve information from a PDF
    elif filetype == 'PDF':
        pdf = pdfquery.PDFQuery(path, input_text_formatter='utf-8')
        try:
            pdf.load(0, 1, 2) # load the first 3 pages. please god no one has a longer tag wall than that.
        except StopIteration:
            pdf.load() # handle pdfs with fewer than 3 pages

        # get either the series information, or the work stats (depending on the function inputs)
        href = parse_pdf.get_work_link_pdf(pdf)
        if update_series: series = parse_pdf.get_series_pdf(pdf)
        else: stats = parse_pdf.get_stats_pdf(pdf)

    else:
        raise ValueError('Invalid filetype argument: {}. Valid filetypes are '.format(filetype) + ','.join(strings.UPDATE_ACCEPTABLE_FILE_TYPES))

    # done with format-specific parsing, now we can proceed in the same way for all filetypes
    if href is None: return None # if this isn't a work from ao3, return
    
    # if we don't care whether the fic is incomplete, just return the work link
    # TODO: check why this is the case; it might be easier and faster to return nothing here
    if not update: return {'link': href}

    # if this is a series update, return the series links if any were found
    if update_series: return {'link': href, 'series': series} if series else None

    if stats is None: return None # if we can't find the series metadata, return

    # if the metadata does not contain the character "/", return
    # we assume that the "/" character represents chapter count
    index = stats.find('/')
    if index == -1: return None

    # if the chapter counts do not match, we assume the work is incomplete
    # we're assuming that AO3 is being reasonable with their chapter counts, and currentchap !> totalchap
    totalchap = parse_text.get_total_chapters(stats, index)
    currentchap = parse_text.get_current_chapters(stats, index)

    # if the work is incomplete, return the info
    if currentchap != totalchap:
        return {'link': href, 'chapters': currentchap}

    # we shouldn't make it here in the function, but just to be safe:
    return None


def get_epub_preface(path: str) -> ET.Element:
    """retrieve the story's preface from the epub file and return the file's root element for later use"""
    try:
        with zipfile.ZipFile(path, 'r') as zf:
            with zf.open('content.opf') as of: 
                opf = ET.parse(of).getroot()
                preface_path = parse_xml.get_preface_path_epub(opf)
                if preface_path is None: return None
                with zf.open(preface_path) as doc: 
                    return ET.parse(doc).getroot()
    except (zipfile.BadZipFile, FileNotFoundError):
        return None
