import xml.etree.ElementTree as ET

from urllib.parse import urlparse

from ao3downloader import parse_text


def get_bookmark_list(bookmark_xml: ET.Element, exclude_toread: bool) -> list[dict[str, str]]:
    bookmark_list = []
    for child in bookmark_xml:
        attributes = child.attrib
        # only include valid ao3 links
        link = attributes['href']
        if urlparse(link).hostname == 'archiveofourown.org' and (parse_text.is_work(link) or parse_text.is_series(link)):
            # if exclude_toread is true, only include read bookmarks
            if exclude_toread:
                if not 'toread' in attributes:
                    bookmark_list.append(attributes)          
            # otherwise include all valid bookmarks
            else:
                bookmark_list.append(attributes)
    return bookmark_list


def get_preface_path_epub(xml: ET.Element) -> str:
    # assumption: the preface is always the first item in the manifest with media-type 
    # application/xhtml+xml. should be fine unless ao3 drastically changes their epub format
    manifest = xml.find('{http://www.idpf.org/2007/opf}manifest')
    if manifest is None: return None
    for item in manifest.findall('{http://www.idpf.org/2007/opf}item'):
        if item.attrib.get('media-type') == 'application/xhtml+xml':
            return item.attrib.get('href')


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
