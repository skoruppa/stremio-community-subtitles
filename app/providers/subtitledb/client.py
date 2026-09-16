"""TheSubtitleDB.org API client

Free, API-key-less subtitle provider.
Rate limit: 150 downloads/hour per IP.
Docs: https://thesubtitledb.org
"""
import aiohttp
from quart import current_app
from ...version import USER_AGENT

BASE_URL = "https://api.thesubtitledb.org/v1"


class SubtitleDBError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


async def search_by_imdb(imdb_id, language=None, season=None, episode=None,
                         limit=20, offset=0, fmt=None):
    """Search subtitles by IMDb ID.
    
    Args:
        imdb_id: IMDb ID with 'tt' prefix (e.g. 'tt0111161')
        language: 2-letter language code (e.g. 'en')
        season: Season number for TV shows
        episode: Episode number for TV shows
        limit: Results per page (1-100, default 20)
        offset: Pagination offset
        fmt: Subtitle format filter ('srt', 'ass', etc.)
    """
    # Build URL path
    # Strip 'tt' prefix — API expects numeric IMDB id
    imdb_num = imdb_id.lstrip('t')
    path = f"/by-imdb/{imdb_id}"
    if season is not None:
        path += f"/season/{season}"
        if episode is not None:
            path += f"/episode/{episode}"

    return await _request(path, language=language, limit=limit,
                          offset=offset, fmt=fmt)


async def search_by_tmdb(tmdb_id, language=None, season=None, episode=None,
                         limit=20, offset=0, fmt=None):
    """Search subtitles by TMDB ID."""
    path = f"/by-tmdb/{tmdb_id}"
    if season is not None:
        path += f"/season/{season}"
        if episode is not None:
            path += f"/episode/{episode}"

    return await _request(path, language=language, limit=limit,
                          offset=offset, fmt=fmt)


def get_download_url(subtitle_id):
    """Get direct download URL for a subtitle (302 redirect to file)."""
    return f"https://api.thesubtitledb.org/get/{subtitle_id}"


async def _request(path, language=None, limit=20, offset=0, fmt=None):
    """Make a request to TheSubtitleDB API."""
    params = {}
    if language:
        params['lang'] = language
    if limit != 20:
        params['limit'] = limit
    if offset:
        params['offset'] = offset
    if fmt:
        params['format'] = fmt

    url = f"{BASE_URL}{path}"
    headers = {'User-Agent': USER_AGENT}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, headers=headers,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as response:
                if response.status == 404:
                    return None
                if response.status == 429:
                    raise SubtitleDBError("Rate limited", 429)
                response.raise_for_status()
                return await response.json()
    except aiohttp.ClientResponseError as e:
        raise SubtitleDBError(f"API error: {e.status}", e.status)
    except aiohttp.ClientError as e:
        raise SubtitleDBError(f"Request failed: {e}")
