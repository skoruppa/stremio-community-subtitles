import requests
from flask import current_app

BASE_URL = "https://api.opensubtitles.com/api/v1"

class OpenSubtitlesError(Exception):
    """Custom exception for OpenSubtitles API errors."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code

def _get_api_key():
    """Retrieves the OpenSubtitles API key from app config."""
    api_key = current_app.config.get('OPEN_SUBTITLES_API_KEY')
    if not api_key:
        current_app.logger.error("OpenSubtitles API key is not configured.")
        raise OpenSubtitlesError("OpenSubtitles API key is missing in configuration.")
    return api_key

def search_subtitles(imdb_id=None, query=None, languages=None, moviehash=None, season_number=None, episode_number=None, type=None):
    """
    Searches for subtitles on OpenSubtitles.
    API Documentation: https://opensubtitles.stoplight.io/docs/opensubtitles-api/c2NoOjQ4MTA4NzY2-search-for-subtitles

    Args:
        imdb_id (str, optional): IMDB ID of the movie or episode.
        query (str, optional): Movie or series name.
        languages (str, optional): Comma-separated list of language codes (e.g., 'en,es').
        moviehash (str, optional): Hash of the video file.
        season_number (int, optional): Season number for series.
        episode_number (int, optional): Episode number for series.
        type (str, optional): 'movie' or 'episode'.

    Returns:
        dict: The JSON response from the API containing subtitle data.
              Returns None if the API key is missing or if there's a request error.
    
    Raises:
        OpenSubtitlesError: If API key is missing or API returns an error.
    """
    try:
        api_key = _get_api_key()
    except OpenSubtitlesError as e:
        # Logged in _get_api_key, re-raise or handle as per application flow
        raise  # Or return None / empty dict if preferred for non-critical failures

    headers = {
        'Api-Key': api_key,
        'Content-Type': 'application/json', # Though for GET it's not strictly needed for body
        'Accept': 'application/json'
    }
    
    params = {}
    if imdb_id:
        params['imdb_id'] = imdb_id
    if query:
        params['query'] = query
    if languages:
        params['languages'] = languages
    if moviehash:
        params['moviehash'] = moviehash
    if season_number is not None:
        params['season_number'] = season_number
    if episode_number is not None:
        params['episode_number'] = episode_number
    if type:
        params['type'] = type
        
    if not params:
        current_app.logger.warning("OpenSubtitles search called with no parameters.")
        return {"data": [], "message": "No search parameters provided."} # Or raise error

    try:
        current_app.logger.info(f"Searching OpenSubtitles with params: {params}")
        response = requests.get(f"{BASE_URL}/subtitles", headers=headers, params=params, timeout=15)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"OpenSubtitles API HTTP error during search: {e.response.status_code} - {e.response.text}")
        raise OpenSubtitlesError(f"API error: {e.response.status_code} - {e.response.text}", status_code=e.response.status_code)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"OpenSubtitles API request error during search: {e}")
        raise OpenSubtitlesError(f"Request failed: {e}")
    except ValueError as e: # Includes JSONDecodeError
        current_app.logger.error(f"OpenSubtitles API JSON decode error during search: {e}")
        raise OpenSubtitlesError(f"Failed to decode API response: {e}")


def request_download_link(file_id):
    """
    Requests a download link for a specific subtitle file_id.
    API Documentation: https://opensubtitles.stoplight.io/docs/opensubtitles-api/c2NoOjQ4MTA4NzY5-request-download

    Args:
        file_id (int): The ID of the file to download.

    Returns:
        dict: The JSON response from the API containing download link and details.
              Returns None if API key is missing or request error.
              
    Raises:
        OpenSubtitlesError: If API key is missing or API returns an error.
    """
    try:
        api_key = _get_api_key()
    except OpenSubtitlesError as e:
        raise

    headers = {
        'Api-Key': api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    payload = {
        'file_id': file_id
    }

    try:
        current_app.logger.info(f"Requesting OpenSubtitles download link for file_id: {file_id}")
        response = requests.post(f"{BASE_URL}/download", headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        current_app.logger.error(f"OpenSubtitles API HTTP error during download request: {e.response.status_code} - {e.response.text}")
        # Try to parse error message from OpenSubtitles if available
        try:
            error_data = e.response.json()
            message = error_data.get("message", e.response.text)
        except ValueError:
            message = e.response.text
        raise OpenSubtitlesError(f"API error: {e.response.status_code} - {message}", status_code=e.response.status_code)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"OpenSubtitles API request error during download request: {e}")
        raise OpenSubtitlesError(f"Request failed: {e}")
    except ValueError as e: # Includes JSONDecodeError
        current_app.logger.error(f"OpenSubtitles API JSON decode error during download request: {e}")
        raise OpenSubtitlesError(f"Failed to decode API response: {e}")
