"""Napisy24 API client"""
import asyncio
import aiohttp
import re
from lxml import etree
import xml.etree.ElementTree as ET
from quart import current_app


class Napisy24Error(Exception):
    """Napisy24 API error"""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


async def search_by_hash(filehash, filesize, filename, api_user="subliminal", api_password="lanimilbus"):
    """Search subtitles by video file hash"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("http://napisy24.pl/run/CheckSubAgent.php", data={
                'postAction': 'CheckSub',
                'ua': api_user,
                'ap': api_password,
                'fh': filehash,
                'fs': filesize,
                'n24pref': 1,
                'fn': filename or ""
            }, headers={"User-Agent": "Subliminal"}, timeout=aiohttp.ClientTimeout(total=10)) as response:
                
                if response.status != 200:
                    return None
                
                content = await response.read()
                try:
                    response_text, response_data = content.split(b'||', 1)
                except ValueError:
                    return None
                
                if not response_text.startswith(b"OK-2"):
                    return None
                
                match = re.search(rb"fps:([\d.]+)", response_text)
                fps = float(match.group(1)) if match else None
                sub_id = int(re.search(rb"lp:([\d.]+)", response_text).group(1))
                
                return {
                    'id': str(sub_id),
                    'fps': fps,
                    'release': filename or 'Hash match'
                }
    except Exception as e:
        current_app.logger.error(f"Napisy24 hash search error: {e} | hash={filehash}, size={filesize}, filename={filename}")
        raise Napisy24Error(f"Hash search failed: {e}")


async def search_by_title(title, season=None, episode=None, filename=None):
    """Search subtitles by title"""
    try:
        # Build search query
        search_query = title
        if season and episode:
            search_query = f"{title} {season}x{episode:02d}"
        
        url = f"http://napisy24.pl/libs/webapi.php?title={search_query}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return []
                text = await response.text()
                if text == 'brak wynikow':
                    return []
                return _parse_xml_response(text, season, episode, filename)
    except Exception as e:
        current_app.logger.error(f"Napisy24 title search error: {e} | title={title}, season={season}, episode={episode}")
        raise Napisy24Error(f"Title search failed: {e}")


async def search_by_imdb(imdb_id, season=None, episode=None, filename=None):
    """Search subtitles by IMDb ID"""
    try:
        url = f"http://napisy24.pl/libs/webapi.php?imdb={imdb_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return []
                text = await response.text()
                if text == 'brak wynikow':
                    return []
                return _parse_xml_response(text, season, episode, filename)
    except Exception as e:
        current_app.logger.error(f"Napisy24 IMDb search error: {e} | imdb_id={imdb_id}, season={season}, episode={episode}")
        raise Napisy24Error(f"IMDb search failed: {e}")


def _parse_xml_response(response_text, season=None, episode=None, filename=None):
    """Parse XML response from Napisy24 API"""
    try:
        subtitles = []
        response_text = response_text.strip()
        
        # Clean XML
        xml_decl_match = re.match(r"<\?xml.*?\?>", response_text)
        if xml_decl_match:
            response_text = response_text[xml_decl_match.end():].strip()
        
        response_text = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<subtitles>{response_text}</subtitles>"
        response_text = response_text.replace('<br>', '')
        
        parser = etree.XMLParser(recover=True, encoding='utf-8')
        root = ET.fromstring(response_text, parser=parser)
        
        for subtitle in root.findall("subtitle"):
            # Filter by language - only Polish
            language_el = subtitle.find("language")
            if language_el is not None and language_el.text and language_el.text.lower() != 'pl':
                continue
            
            sub_id = subtitle.find("id").text
            try:
                fps = float(subtitle.find("fps").text.replace(",", "."))
            except (AttributeError, ValueError):
                fps = None
            
            release_el = subtitle.find("release")
            release = release_el.text if release_el is not None else 'unknown'
            
            author_el = subtitle.find("author")
            author = author_el.text if author_el is not None and author_el.text else None
            
            subSeason = subtitle.find("season")
            subSeason = int(subSeason.text) if subSeason is not None and subSeason.text else None
            subEpisode = subtitle.find("episode")
            subEpisode = int(subEpisode.text) if subEpisode is not None and subEpisode.text else None
            
            # Filter by episode if needed
            if episode is not None:
                # Skip if season doesn't match
                if subSeason is not None and season is not None and subSeason != season:
                    continue
                # Skip if episode doesn't match
                if subEpisode is not None and subEpisode != episode:
                    continue
            
            # Exact filename match
            if filename and release and release in filename[:-4]:
                return [{
                    'id': sub_id,
                    'fps': fps,
                    'release': release,
                    'author': author
                }]
            
            subtitles.append({
                'id': sub_id,
                'fps': fps,
                'release': release,
                'author': author
            })
        
        return subtitles
    except Exception as e:
        current_app.logger.error(f"Napisy24 XML parse error: {e}")
        raise Napisy24Error(f"XML parse failed: {e}")


async def download_subtitle(subtitle_id):
    """Download subtitle by ID"""
    try:
        url = f"http://napisy24.pl/run/pages/download.php?napisId={subtitle_id}&typ=sr"
        headers = {"Referer": "http://napisy24.pl/"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    raise Napisy24Error(f"Download failed with status {response.status}", response.status)
                return await response.read()
    except Exception as e:
        current_app.logger.error(f"Napisy24 download error: {e} | subtitle_id={subtitle_id}")
        raise Napisy24Error(f"Download failed: {e}")
