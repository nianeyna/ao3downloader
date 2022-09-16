import pdfquery

from ao3downloader import strings


def get_work_link_pdf(pdf: pdfquery.PDFQuery) -> str:
    # assumption: work link is on the same line as preceding text. probably fine. ¯\_(ツ)_/¯
    # doing some weird string parsing here. considered taking a similar approach to the epub function
    # and parsing the xml tree for URIs. however that might break if someone linked another work in their summary.
    linktext = pdf.pq('LTTextLineHorizontal:contains("Posted originally on the Archive of Our Own at ")').text()
    workindex = linktext.find('/works/')
    endindex = linktext[workindex:].find('.')
    worknumber = linktext[workindex:workindex+endindex]
    if worknumber: return strings.AO3_BASE_URL + worknumber
    return None


def get_stats_pdf(pdf: pdfquery.PDFQuery) -> str:
    # assumption: chapter count is on same line as 'Chapters: '. reasonably safe because the 
    # preceding metadata is always going to be no longer than 'Published: yyyy-MM-dd Updated: yyyy-MM-dd '.
    # if someone puts 'Chapters: ' in their summary for some fool reason... I don't know, it might still work.
    return pdf.pq('LTTextLineHorizontal:contains("Chapters: ")').text()


def get_series_pdf(pdf: pdfquery.PDFQuery) -> list[str]:
    links = map(lambda x: x.attrib['URI'] if 'URI' in x.attrib else '', pdf.pq('Annot'))
    series = filter(lambda x: 'archiveofourown.org/series/' in x, links)
    return list(series)
