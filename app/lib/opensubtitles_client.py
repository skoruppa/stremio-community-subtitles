import requests
from flask import current_app

# Global base URL for non-authenticated or initial calls like login
GLOBAL_OS_BASE_URL = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "StremioCommunitySubtitlesAddon/1.0.0"  # As required by OpenSubtitles API


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


def login(username, password):
    """
    Logs in to OpenSubtitles.
    API Documentation: https://opensubtitles.stoplight.io/docs/opensubtitles-api/c2NoOjQ4MTA4NzYz-login
    Returns:
        dict: Contains token, user info, and base_url from OpenSubtitles.
    Raises:
        OpenSubtitlesError: If API key is missing, login fails, or API returns an error.
    """
    try:
        api_key = _get_api_key()
    except OpenSubtitlesError:
        raise

    headers = {
        'Api-Key': api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': USER_AGENT
    }
    payload = {
        'username': username,
        'password': password
    }

    try:
        current_app.logger.info(f"Attempting OpenSubtitles login for user: {username}")
        response = requests.post(f"{GLOBAL_OS_BASE_URL}/login", headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()

        if 'token' not in data or 'base_url' not in data:
            current_app.logger.error(f"OpenSubtitles login response missing token or base_url: {data}")
            raise OpenSubtitlesError("Login failed: Invalid response from OpenSubtitles.")

        current_app.logger.info(
            f"OpenSubtitles login successful for user: {data.get('user', {}).get('username', username)}. Base URL: {data['base_url']}")
        return data
    except requests.exceptions.HTTPError as e:
        error_message = f"API error: {e.response.status_code}"
        try:
            # Try to get the error message from the HTML body if it's a 403 from Varnish/OpenSubtitles
            if e.response.status_code == 403 and "User-Agent" in e.response.text:
                # Extract the specific message if possible, or use a generic one
                start_marker = "<h1>Error 403 "
                end_marker = "</h1>"
                start_index = e.response.text.find(start_marker)
                if start_index != -1:
                    start_index += len(start_marker)
                    end_index = e.response.text.find(end_marker, start_index)
                    if end_index != -1:
                        error_message += f" - {e.response.text[start_index:end_index]}"
                    else:
                        error_message += f" - {e.response.text}"  # Fallback to full text
                else:
                    error_message += f" - {e.response.text}"  # Fallback to full text
            else:
                error_data = e.response.json()
                error_message += f" - {error_data.get('message', e.response.text)}"
        except ValueError:  # If error response is not JSON or parsing HTML failed
            error_message += f" - {e.response.text}"
        current_app.logger.error(f"OpenSubtitles API HTTP error during login: {error_message}")
        raise OpenSubtitlesError(error_message, status_code=e.response.status_code)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"OpenSubtitles API request error during login: {e}")
        raise OpenSubtitlesError(f"Request failed during login: {e}")
    except ValueError as e:  # Includes JSONDecodeError
        current_app.logger.error(f"OpenSubtitles API JSON decode error during login: {e}")
        raise OpenSubtitlesError(f"Failed to decode API response during login: {e}")


def logout(token, user_base_url):
    """
    Logs out from OpenSubtitles using the user-specific token and base_url.
    API Documentation: Uses the base_url from login response.
    Args:
        token (str): User's OpenSubtitles JWT token.
        base_url (str): User's OpenSubtitles base API URL.
    Returns:
        dict: JSON response from the API, or True if successful with no body.
    Raises:
        OpenSubtitlesError: If API key, token, or base_url are missing/invalid, or API returns an error.
    """
    try:
        api_key = _get_api_key()
    except OpenSubtitlesError:
        raise

    if not token or not user_base_url:
        current_app.logger.error("OpenSubtitles logout: Token and base_url are required.")
        raise OpenSubtitlesError("Token and base_url are required for logout.")

    headers = {
        'Api-Key': api_key,
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'User-Agent': USER_AGENT
        # Content-Type might not be needed if no JSON body is sent for logout
    }

    try:
        current_app.logger.info(f"Attempting OpenSubtitles logout using base_url: {user_base_url}")
        response = requests.delete(f"https://{user_base_url}/api/v1/logout", headers=headers,
                                 timeout=15)  # No JSON body for logout
        response.raise_for_status()
        current_app.logger.info("OpenSubtitles logout successful.")
        try:
            return response.json()
        except ValueError:
            return {"status": "success", "message": "Logout successful"}
    except requests.exceptions.HTTPError as e:
        error_message = f"API error: {e.response.status_code}"
        try:
            error_data = e.response.json()
            error_message += f" - {error_data.get('message', e.response.text)}"
        except ValueError:
            error_message += f" - {e.response.text}"
        current_app.logger.error(f"OpenSubtitles API HTTP error during logout: {error_message}")
        raise OpenSubtitlesError(error_message, status_code=e.response.status_code)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"OpenSubtitles API request error during logout: {e}")
        raise OpenSubtitlesError(f"Request failed during logout: {e}")


def search_subtitles(imdb_id=None, query=None, languages=None, moviehash=None,
                     season_number=None, episode_number=None, type=None,
                     user_token=None, user_base_url=None):
    """
    Searches for subtitles on OpenSubtitles. Requires user authentication.
    """
    try:
        api_key = _get_api_key()
    except OpenSubtitlesError:
        raise

    if not user_token or not user_base_url:
        current_app.logger.error("OpenSubtitles search: user_token and user_base_url are required.")
        raise OpenSubtitlesError("User authentication (token and base_url) is required for searching subtitles.")

    headers = {
        'Api-Key': api_key,
        'Accept': '*/*',
        'User-Agent': USER_AGENT
    }

    params = {}
    if imdb_id: params['imdb_id'] = imdb_id
    if query: params['query'] = query
    if languages: params['languages'] = languages
    if moviehash: 
        params['moviehash'] = moviehash
        params['moviehash_match'] = 'include'
    if season_number is not None: params['season_number'] = season_number
    if episode_number is not None: params['episode_number'] = episode_number
    if type: params['type'] = type

    if not any(params.values()):
        current_app.logger.warning("OpenSubtitles search called with no effective search parameters.")
        raise OpenSubtitlesError("No search criteria provided for subtitle search.")

    try:
        current_app.logger.info(
            f"Searching OpenSubtitles (authenticated) at {user_base_url}/api/v1/subtitles with params: {params}")
        response = requests.get(f"https://{user_base_url}/api/v1/subtitles", headers=headers, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        error_message = f"API error: {e.response.status_code}"
        try:
            error_data = e.response.json()
            error_message += f" - {error_data.get('message', e.response.text)}"
        except ValueError:
            error_message += f" - {e.response.text}"
        current_app.logger.error(f"OpenSubtitles API HTTP error during authenticated search: {error_message}")
        raise OpenSubtitlesError(error_message, status_code=e.response.status_code)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"OpenSubtitles API request error during authenticated search: {e}")
        raise OpenSubtitlesError(f"Request failed during authenticated search: {e}")
    except ValueError as e:
        current_app.logger.error(f"OpenSubtitles API JSON decode error during authenticated search: {e}")
        raise OpenSubtitlesError(f"Failed to decode API response during authenticated search: {e}")


def request_download_link(file_id, user_token=None, user_base_url=None):
    """
    Requests a download link for a specific subtitle file_id. Requires user authentication.
    """
    try:
        api_key = _get_api_key()
    except OpenSubtitlesError:
        raise

    if not user_token or not user_base_url:
        current_app.logger.error("OpenSubtitles download request: user_token and user_base_url are required.")
        raise OpenSubtitlesError("User authentication (token and base_url) is required for download requests.")

    headers = {
        'Api-Key': api_key,
        'Authorization': f'Bearer {user_token}',
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'User-Agent': USER_AGENT
    }

    payload = {
        'file_id': file_id
    }

    try:
        current_app.logger.info(
            f"Requesting OpenSubtitles download link (authenticated) for file_id: {file_id} at {user_base_url}/api/v1/download")
        response = requests.post(f"https://{user_base_url}/api/v1/download", headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        error_message = f"API error: {e.response.status_code}"
        try:
            error_data = e.response.json()
            message = error_data.get("message", e.response.text)
            error_message += f" - {message}"
        except ValueError:
            error_message += f" - {e.response.text}"
        current_app.logger.error(f"OpenSubtitles API HTTP error during authenticated download request: {error_message}")
        raise OpenSubtitlesError(error_message, status_code=e.response.status_code)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"OpenSubtitles API request error during authenticated download request: {e}")
        raise OpenSubtitlesError(f"Request failed during authenticated download request: {e}")
    except ValueError as e:
        current_app.logger.error(f"OpenSubtitles API JSON decode error during authenticated download request: {e}")
        raise OpenSubtitlesError(f"Failed to decode API response during authenticated download request: {e}")
