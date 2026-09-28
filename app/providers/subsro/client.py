"""Subs.ro API client

API docs: https://api.subs.ro/v1.0
Requires an API key passed via X-Subs-Api-Key header.
Download endpoint returns a binary archive (ZIP/RAR).
"""
import aiohttp
from quart import current_app
from ...version import USER_AGENT

BASE_URL = "https://api.subs.ro/v1.0"


class SubsRoError(Exception):
    """Subs.ro API error"""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _headers(api_key: str) -> dict:
    return {
        "X-Subs-Api-Key": api_key,
        "User-Agent": USER_AGENT,
    }


async def search_by_imdb(api_key: str, imdb_id: str, language: str = None) -> list:
    """Search subtitles by IMDb ID.

    Returns list of SubtitleItem dicts from the API.
    """
    url = f"{BASE_URL}/search/imdbid/{imdb_id}"
    params = {}
    if language:
        params["language"] = language

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_headers(api_key), params=params,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 400:
                    return []
                resp.raise_for_status()
                data = await resp.json()
                return data.get("items", [])
    except aiohttp.ClientResponseError as e:
        current_app.logger.error(f"Subs.ro search error: {e.status} | imdb={imdb_id}")
        raise SubsRoError(f"Search failed: {e.status}", e.status)
    except aiohttp.ClientError as e:
        current_app.logger.error(f"Subs.ro request error: {e}")
        raise SubsRoError(f"Request failed: {e}")


async def search_by_title(api_key: str, title: str, language: str = None) -> list:
    """Search subtitles by title string."""
    import urllib.parse
    encoded_title = urllib.parse.quote(title, safe="")
    url = f"{BASE_URL}/search/title/{encoded_title}"
    params = {}
    if language:
        params["language"] = language

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_headers(api_key), params=params,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 400:
                    return []
                resp.raise_for_status()
                data = await resp.json()
                return data.get("items", [])
    except aiohttp.ClientResponseError as e:
        current_app.logger.error(f"Subs.ro title search error: {e.status} | title={title}")
        raise SubsRoError(f"Title search failed: {e.status}", e.status)
    except aiohttp.ClientError as e:
        current_app.logger.error(f"Subs.ro request error: {e}")
        raise SubsRoError(f"Request failed: {e}")


async def download_subtitle(api_key: str, subtitle_id: int) -> bytes:
    """Download subtitle archive by ID.

    Returns raw bytes of the archive (ZIP or RAR).
    """
    url = f"{BASE_URL}/subtitle/{subtitle_id}/download"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_headers(api_key),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 404:
                    raise SubsRoError(f"Subtitle {subtitle_id} not found", 404)
                resp.raise_for_status()
                return await resp.read()
    except aiohttp.ClientResponseError as e:
        current_app.logger.error(f"Subs.ro download error: {e.status} | id={subtitle_id}")
        raise SubsRoError(f"Download failed: {e.status}", e.status)
    except aiohttp.ClientError as e:
        current_app.logger.error(f"Subs.ro download request error: {e}")
        raise SubsRoError(f"Download request failed: {e}")
