import pdfquery
from pyquery import PyQuery

from ao3downloader import exceptions, strings


def get_work_link_pdf(pdf: pdfquery.PDFQuery) -> str | None:
    # assumption: work link is on the same line as preceding text. probably fine. ¯\_(ツ)_/¯
    # doing some weird string parsing here. considered taking a similar approach to the epub function
    # and parsing the xml tree for URIs. however that might break if someone linked another work in their summary.
    linktext = str(get_pq(pdf)('LTTextLineHorizontal:contains("Posted originally on the Archive of Our Own at ")').text())
    workindex = linktext.find('/works/')
    endindex = linktext[workindex:].find('.')
    worknumber = linktext[workindex:workindex+endindex]
    if worknumber: return strings.AO3_BASE_URL + worknumber
    return None


def get_stats_pdf(pdf: pdfquery.PDFQuery) -> str | None:

    # assumption: the exact text 'Chapters:' only appears once in the intro
    # and this indicates the chapter count will be on this or the next line
    chapterquery = get_pq(pdf)('LTTextLineHorizontal:contains("Chapters:")')
    chapterstext = str(chapterquery.text()).strip()

    # if we couldn't find any chapter data, return nothing
    if chapterstext == '': return None

    # if the chapter data is all on this line, return it
    if (
        not chapterstext.find('/') == -1 and # chapter count exists on this line
        not chapterstext.endswith('/') # and it includes the remaining chapters
    ): return chapterstext

    # insert whitespace after colon if there wasn't any
    if chapterstext.endswith(':'): chapterstext = chapterstext + ' '

    # append the next line since (full) chapter count wasn't on the previous line
    chapterstext = chapterstext + str(chapterquery.next('LTTextLineHorizontal').text()).strip()

    return chapterstext


def get_series_pdf(pdf: pdfquery.PDFQuery) -> list[str]:
    links = map(lambda x: x.attrib['URI'] if 'URI' in x.attrib else '', get_pq(pdf)('Annot'))
    series = filter(lambda x: 'archiveofourown.org/series/' in x, links)
    return list(series)


def get_pq(pdf: pdfquery.PDFQuery) -> PyQuery:
    if pdf.pq is None:
        raise exceptions.PdfParsingException(strings.ERROR_PDF_PARSE)
    return pdf.pq
