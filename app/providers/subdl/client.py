"""SubDL API client"""
import asyncio
import aiohttp
from quart import current_app
from ...version import USER_AGENT


class SubDLError(Exception):
    """SubDL API error"""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


async def search_subtitles(api_key, imdb_id=None, tmdb_id=None, film_name=None, languages=None, season=None, episode=None, type=None, file_name=None):
    """
    Search subtitles on SubDL
    
    API Docs: https://subdl.com/api-doc
    """
    if not api_key:
        raise SubDLError("API key required")
    
    base_url = "https://api.subdl.com/api/v1/subtitles"
    
    params = {'api_key': api_key,
              'subs_per_page': 30}
    if imdb_id:
        # SubDL uses imdb_id with 'tt' prefix
        params['imdb_id'] = imdb_id
    if tmdb_id:
        params['tmdb_id'] = tmdb_id
    if film_name:
        params['film_name'] = film_name
    if languages:
        # SubDL uses 2-letter codes
        params['languages'] = ','.join(languages)
    if season is not None:
        params['season_number'] = season
    if episode is not None:
        params['episode_number'] = episode
    if type:
        params['type'] = type  # 'movie' or 'tv'
    # SubDL doesn't support file_name parameter according to official docs
    # if file_name:
    #     params['file_name'] = file_name
    
    headers = {
        'User-Agent': USER_AGENT
    }
    
    try:
        current_app.logger.info(f"SubDL search with params: {params}")
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                response.raise_for_status()
                return await response.json()
    except aiohttp.ClientResponseError as e:
        error_msg = f"SubDL API error: {e.status}"
        try:
            error_data = await e.response.json()
            error_msg += f" - {error_data.get('message', await e.response.text())}"
        except:
            error_msg += f" - {await e.response.text()}"
        current_app.logger.error(f"{error_msg} | Request: {base_url} params={params}")
        raise SubDLError(error_msg, e.status)
    except aiohttp.ClientError as e:
        current_app.logger.error(f"SubDL request error: {e}")
        raise SubDLError(f"Request failed: {e}")


def get_download_url(api_key, subtitle_id):
    """
    Get download URL for a subtitle
    
    SubDL provides direct download URLs in search results
    """
    # SubDL returns download URLs directly in search results
    # This is just a placeholder - actual URL comes from search
    return f"https://dl.subdl.com{subtitle_id}"
