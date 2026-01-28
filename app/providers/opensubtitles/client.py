import asyncio
import aiohttp
import time
from quart import current_app
import functools # Import functools for lru_cache
import datetime # Import datetime for cache expiration
from ...version import USER_AGENT

# Global base URL for non-authenticated or initial calls like login
GLOBAL_OS_BASE_URL = "https://api.opensubtitles.com/api/v1"

# Custom decorator for time-based LRU cache
def timed_lru_cache(seconds: int, maxsize: int = 128):
    def wrapper_cache(func):
        func = functools.lru_cache(maxsize=maxsize)(func)
        func.expiration = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)

        @functools.wraps(func)
        def wrapped_func(*args, **kwargs):
            if datetime.datetime.utcnow() >= func.expiration:
                func.cache_clear()
                func.expiration = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
            return func(*args, **kwargs)
        return wrapped_func
    return wrapper_cache


def _get_api_key():
    """Safely get API key with proper error handling"""
    api_key = current_app.config.get('OPENSUBTITLES_API_KEY')
    if not api_key:
        raise ValueError("OPENSUBTITLES_API_KEY not found in configuration")
    return api_key


class OpenSubtitlesError(Exception):
    """Custom exception for OpenSubtitles API errors."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


# Modified for aiohttp - returns response data directly
async def make_request_with_retry(request_func, max_retries=3, retry_delay=1.0):
    """
    Makes an HTTP request with retry logic for 5xx server errors.

    Args:
        request_func (callable): Function that makes the HTTP request (should return aiohttp.ClientResponse)
        max_retries (int): Maximum number of retry attempts (default: 2)
        retry_delay (float): Delay in seconds between retries (default: 1.0)

    Returns:
        aiohttp.ClientResponse: The successful response

    Raises:
        aiohttp.ClientResponseError: For non-5xx HTTP errors or after max retries
        aiohttp.ClientError: For other request errors
    """
    last_exception = None

    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            data = await request_func()
            # request_func now handles raise_for_status() and returns data
            return data

        except aiohttp.ClientResponseError as e:
            # For 5xx server errors, retry
            if 500 <= e.status < 600 and attempt < max_retries:
                current_app.logger.warning(
                    f"OpenSubtitles API returned {e.status} server error "
                    f"(attempt {attempt + 1}/{max_retries + 1}). "
                    f"Retrying in {retry_delay} seconds..."
                )
                await asyncio.sleep(retry_delay)
                last_exception = e
                continue
            # For other HTTP errors, raise immediately
            raise

        except aiohttp.ClientError as e:
            last_exception = e
            # For network errors, also retry
            if attempt < max_retries:
                current_app.logger.warning(
                    f"OpenSubtitles API request failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Retrying in {retry_delay} seconds..."
                )
                await asyncio.sleep(retry_delay)
                continue
            else:
                # Re-raise the last exception if we've exhausted retries
                raise

    # This should never be reached, but just in case
    if last_exception:
        raise last_exception


async def login(username, password, user=None):
    """
    Logs in to OpenSubtitles.
    API Documentation: https://opensubtitles.stoplight.io/docs/opensubtitles-api/c2NoOjQ4MTA4NzYz-login
    Args:
        username (str): OpenSubtitles username.
        password (str): OpenSubtitles password.
        user (User, optional): The user object. If provided, the user's personal API key will be prioritized.
    Returns:
        dict: Contains token, user info, and base_url from OpenSubtitles.
    Raises:
        OpenSubtitlesError: If API key is missing, login fails, or API returns an error.
    """
    if not username or not password:
        raise OpenSubtitlesError("Username and password are required for login.")

    try:
        api_key = _get_api_key()
    except (ValueError, RuntimeError) as e:
        current_app.logger.error(f"API key error: {e}")
        raise OpenSubtitlesError(f"Configuration error: {e}")

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

    async def make_request():
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{GLOBAL_OS_BASE_URL}/login", headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status()
                return await response.json()

    try:
        current_app.logger.info(f"Attempting OpenSubtitles login for user: {username}")
        data = await make_request_with_retry(make_request)

        if 'token' not in data or 'base_url' not in data:
            current_app.logger.error(f"OpenSubtitles login response missing token or base_url: {data}")
            raise OpenSubtitlesError("Login failed: Invalid response from OpenSubtitles.")

        current_app.logger.info(
            f"OpenSubtitles login successful for user: {data.get('user', {}).get('username', username)}. Base URL: {data['base_url']}")
        return data
    except aiohttp.ClientResponseError as e:
        error_message = f"API error: {e.status} - {e.message}"
        
        # Log as warning for client errors (4xx), error for server errors (5xx)
        if 400 <= e.status < 500:
            current_app.logger.warning(f"OpenSubtitles API HTTP error during login: {error_message} | username={username}")
        else:
            current_app.logger.error(f"OpenSubtitles API HTTP error during login: {error_message} | username={username}")
        raise OpenSubtitlesError(error_message, status_code=e.status)
    except aiohttp.ClientError as e:
        current_app.logger.error(f"OpenSubtitles API request error during login: {e}")
        raise OpenSubtitlesError(f"Request failed during login: {e}")
    except ValueError as e:  # Includes JSONDecodeError
        current_app.logger.error(f"OpenSubtitles API JSON decode error during login: {e}")
        raise OpenSubtitlesError(f"Failed to decode API response during login: {e}")


async def logout(token, user):
    """
    Logs out from OpenSubtitles using the user-specific token and base_url from the user object.
    API Documentation: Uses the base_url from login response.
    Args:
        token (str): User's OpenSubtitles JWT token.
        user (User): The user object containing the base_url and API key.
    Returns:
        dict: JSON response from the API, or True if successful with no body.
    Raises:
        OpenSubtitlesError: If API key, token, or base_url are missing/invalid, or API returns an error.
    """
    if not token or not user or not hasattr(user, 'opensubtitles_base_url') or not user.opensubtitles_base_url:
        current_app.logger.error("OpenSubtitles logout: Token, user object, and user's base_url are required.")
        raise OpenSubtitlesError("Token, user object, and user's base_url are required for logout.")

    try:
        api_key = _get_api_key()
    except (ValueError, RuntimeError) as e:
        current_app.logger.error(f"API key error: {e}")
        raise OpenSubtitlesError(f"Configuration error: {e}")

    headers = {
        'Api-Key': api_key,
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'User-Agent': USER_AGENT
    }

    async def make_request():
        async with aiohttp.ClientSession() as session:
            async with session.delete(f"https://{user.opensubtitles_base_url}/api/v1/logout", headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status()
                try:
                    return await response.json()
                except ValueError:
                    return {"status": "success", "message": "Logout successful"}

    try:
        current_app.logger.info(f"Attempting OpenSubtitles logout using base_url: {user.opensubtitles_base_url}")
        data = await make_request_with_retry(make_request)
        current_app.logger.info("OpenSubtitles logout successful.")
        return data
    except aiohttp.ClientResponseError as e:
        error_message = f"API error: {e.status} - {e.message}"
        current_app.logger.error(f"OpenSubtitles API HTTP error during logout: {error_message}")
        raise OpenSubtitlesError(error_message, status_code=e.status)
    except aiohttp.ClientError as e:
        current_app.logger.error(f"OpenSubtitles API request error during logout: {e}")
        raise OpenSubtitlesError(f"Request failed during logout: {e}")


async def search_subtitles(imdb_id=None, query=None, languages=None, moviehash=None,
                     season_number=None, episode_number=None, type=None, user=None):
    """
    Searches for subtitles on OpenSubtitles. Requires user authentication.
    Args:
        imdb_id (int, optional): IMDb ID of the content.
        query (str, optional): Search query.
        languages (str, optional): Comma-separated language codes (e.g., "en,fr").
        moviehash (str, optional): Movie hash for file-based matching.
        season_number (int, optional): Season number for TV shows.
        episode_number (int, optional): Episode number for TV shows.
        type (str, optional): Content type ('movie' or 'episode').
        user (User): The user object containing the token, base_url, and API key.
    """

    if not user or not hasattr(user, 'opensubtitles_token') or not user.opensubtitles_token or \
            not hasattr(user, 'opensubtitles_base_url') or not user.opensubtitles_base_url:
        current_app.logger.error("OpenSubtitles search: user object with token and base_url is required.")
        raise OpenSubtitlesError(
            "User authentication (user object with token and base_url) is required for searching subtitles.")

    try:
        api_key = _get_api_key()
    except (ValueError, RuntimeError) as e:
        current_app.logger.error(f"API key error: {e}")
        raise OpenSubtitlesError(f"Configuration error: {e}")

    headers = {
        'Api-Key': api_key,
        'Authorization': f'Bearer {user.opensubtitles_token}',  # Read token from user object
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

    async def make_request():
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://{user.opensubtitles_base_url}/api/v1/subtitles", headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status()
                return await response.json()

    try:
        current_app.logger.info(
            f"Searching OpenSubtitles (authenticated) at {user.opensubtitles_base_url}/api/v1/subtitles with params: {params}")
        data = await make_request_with_retry(make_request)
        return data
    except aiohttp.ClientResponseError as e:
        error_message = f"API error: {e.status} - {e.message}"
        current_app.logger.error(f"OpenSubtitles API HTTP error during authenticated search: {error_message} | Request params: {params}")
        raise OpenSubtitlesError(error_message, status_code=e.status)
    except aiohttp.ClientError as e:
        current_app.logger.error(f"OpenSubtitles API request error during authenticated search: {e}")
        raise OpenSubtitlesError(f"Request failed during authenticated search: {e}")
    except ValueError as e:
        current_app.logger.error(f"OpenSubtitles API JSON decode error during authenticated search: {e}")
        raise OpenSubtitlesError(f"Failed to decode API response during authenticated search: {e}")


async def request_download_link(file_id, user=None):
    """
    Requests a download link for a specific subtitle file_id. Requires user authentication.
    Args:
        file_id (int): The OpenSubtitles file ID.
        user (User): The user object containing the base_url and API key.
    """
    if not file_id:
        raise OpenSubtitlesError("file_id is required for download request.")

    if not user or not hasattr(user, 'opensubtitles_token') or not user.opensubtitles_token or \
            not hasattr(user, 'opensubtitles_base_url') or not user.opensubtitles_base_url:
        current_app.logger.error("OpenSubtitles download request: user object with token and base_url is required.")
        raise OpenSubtitlesError(
            "User authentication (user object with token and base_url) is required for download request.")

    try:
        api_key = _get_api_key()
    except (ValueError, RuntimeError) as e:
        current_app.logger.error(f"API key error: {e}")
        raise OpenSubtitlesError(f"Configuration error: {e}")

    headers = {
        'Api-Key': api_key,
        'Authorization': f'Bearer {user.opensubtitles_token}',
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'User-Agent': USER_AGENT
    }

    payload = {
        'file_id': file_id,
        'sub_format': 'webvtt'
    }

    async def make_request():
        async with aiohttp.ClientSession() as session:
            async with session.post(f"https://{user.opensubtitles_base_url}/api/v1/download", headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status()
                return await response.json()

    try:
        current_app.logger.info(
            f"Requesting OpenSubtitles download link (authenticated) for file_id: {file_id} at {user.opensubtitles_base_url}/api/v1/download")
        data = await make_request_with_retry(make_request)
        return data
    except aiohttp.ClientResponseError as e:
        error_message = f"API error: {e.status} - {e.message}"
        
        # Log as warning for client errors (4xx), error for server errors (5xx)
        if 400 <= e.status < 500:
            current_app.logger.warning(f"OpenSubtitles API HTTP error during authenticated download request: {error_message} | file_id: {file_id}")
        else:
            current_app.logger.error(f"OpenSubtitles API HTTP error during authenticated download request: {error_message} | file_id: {file_id}")
        raise OpenSubtitlesError(error_message, status_code=e.status)
    except aiohttp.ClientError as e:
        current_app.logger.error(f"OpenSubtitles API request error during authenticated download request: {e}")
        raise OpenSubtitlesError(f"Request failed during authenticated download request: {e}")
    except ValueError as e:
        current_app.logger.error(f"OpenSubtitles API JSON decode error during authenticated download request: {e}")
        raise OpenSubtitlesError(f"Failed to decode API response during authenticated download request: {e}")
