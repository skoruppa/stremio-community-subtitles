"""SubDL API client"""
import requests
from flask import current_app


class SubDLError(Exception):
    """SubDL API error"""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def search_subtitles(api_key, imdb_id=None, languages=None, season=None, episode=None, type=None, file_name=None):
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
    if languages:
        # SubDL uses 2-letter codes
        params['languages'] = ','.join(languages)
    if season is not None:
        params['season_number'] = season
    if episode is not None:
        params['episode_number'] = episode
    if type:
        params['type'] = type  # 'movie' or 'tv'
    if file_name:
        params['file_name'] = file_name
    
    headers = {
        'User-Agent': 'StremioCommunitySubtitlesAddon/1.0.0'
    }
    
    try:
        current_app.logger.info(f"SubDL search with params: {params}")
        response = requests.get(base_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        error_msg = f"SubDL API error: {e.response.status_code}"
        try:
            error_data = e.response.json()
            error_msg += f" - {error_data.get('message', e.response.text)}"
        except:
            error_msg += f" - {e.response.text}"
        current_app.logger.error(error_msg)
        raise SubDLError(error_msg, e.response.status_code)
    except requests.exceptions.RequestException as e:
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
