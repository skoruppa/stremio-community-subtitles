import themoviedb
import kitsu # Import kitsu library
import asyncio # Import asyncio
from flask import current_app
from kitsu.models import Title

from ..extensions import cache

tmdb_api = themoviedb.tmdb.TMDb()


def _get_tmdb_metadata(content_id, content_type): # Renamed to _get_tmdb_metadata
    """
    Fetches metadata from TMDB based on IMDb ID extracted from content_id.
    Handles movies (tt...) and series (tt...:s:e or tt...:s).
    Returns a dictionary with 'title', 'poster_url', 'year', 'season', 'episode', 'id', 'id_type',
    or None if not found/not IMDb/API key missing.
    """
    tmdb_key = current_app.config.get('TMDB_KEY')
    if not tmdb_key or 'YOUR_TMDB_API_KEY' in tmdb_key:
        current_app.logger.warning("TMDB API Key not configured.")
        return None

    if not content_id or not content_id.startswith('tt'):
        current_app.logger.info(f"Content ID {content_id} is not an IMDb ID. Skipping TMDB lookup.")
        return None  # Not an IMDb ID

    tmdb_api.key = tmdb_key
    tmdb_api.language = 'en'
    tmdb_api.adult = False

    parts = content_id.split(':')
    imdb_id = parts[0]
    season_num = None
    episode_num = None
    metadata = {
        'title': None,
        'poster_url': None,
        'year': None,
        'season': None,
        'episode': None,
        'id': imdb_id,
        'id_type': 'imdb'
    }

    try:
        find_results = tmdb_api.find().by_imdb(imdb_id)

        if content_type == 'movie' and find_results.movie_results:
            movie_info = find_results.movie_results[0]
            metadata['title'] = movie_info.title
            metadata['year'] = movie_info.release_date.year
            if movie_info.poster_url():
                metadata['poster_url'] = movie_info.poster_url()
            return metadata

        elif content_type == 'series' and find_results.tv_results:
            series_info = find_results.tv_results[0]
            metadata['title'] = series_info.name
            metadata['year'] = series_info.first_air_date.year
            if series_info.poster_url():
                metadata['poster_url'] = series_info.poster_url()

            if len(parts) >= 2:
                try:
                    season_num = int(parts[1])
                except ValueError:
                    pass
            if len(parts) == 3:
                try:
                    episode_num = int(parts[2])
                except ValueError:
                    pass
            elif len(parts) == 2:  # Handle ttID:S format -> assume season 1
                season_num = 1
                episode_num = int(parts[1])

            metadata['season'] = season_num
            metadata['episode'] = episode_num

            if season_num is not None and episode_num is not None and series_info.id:
                try:
                    tmdb_series_id = series_info.id
                    episode_info = tmdb_api.episode(tmdb_series_id, season_num, episode_num).details()
                    episode_title = episode_info.name
                    if episode_title:
                        metadata['title'] = f"{metadata['title']} S{season_num:02d}E{episode_num:02d} - {episode_title}"
                except Exception as ep_e:
                    current_app.logger.warning(
                        f"Could not fetch TMDB episode info for {imdb_id} S{season_num}E{episode_num}: {ep_e}")

            return metadata

        else:
            current_app.logger.warning(f"TMDB Find found no matching {content_type} for IMDb ID: {imdb_id}")
            return None

    except Exception as e:
        current_app.logger.error(f"Error fetching TMDB metadata for {content_id}: {e}")
        return None


async def _get_kitsu_metadata(content_id): # Changed to async def
    """
    Fetches metadata from Kitsu based on Kitsu ID extracted from content_id.
    Handles anime (kitsu:ID) and specific episodes (kitsu:ID:EPISODE_NUM).
    Returns a dictionary with 'title', 'poster_url', 'year', 'season', 'episode', 'id', 'id_type',
    or None if not found/API error.
    """

    if not content_id or not content_id.startswith('kitsu:'):
        current_app.logger.info(f"Content ID {content_id} is not a Kitsu ID. Skipping Kitsu lookup.")
        return None

    parts = content_id.split(':')
    if len(parts) < 2:
        current_app.logger.warning(f"Invalid Kitsu ID format: {content_id}")
        return None

    try:
        kitsu_anime_id = parts[1]
        episode_num_str = parts[2] if len(parts) > 2 else None
        episode_num = int(episode_num_str) if episode_num_str and episode_num_str.isdigit() else None
    except ValueError:
        current_app.logger.warning(f"Invalid episode number in Kitsu ID: {content_id}")
        return None

    metadata = {
        'title': None,
        'poster_url': None,
        'year': None,
        'season': None,  # Kitsu doesn't typically use seasons like TMDB
        'episode': None,
        'id': kitsu_anime_id,
        'id_type': 'kitsu'
    }

    client = None
    try:
        client = kitsu.Client()
        anime = await client.get_anime(kitsu_anime_id)

        if not anime:
            current_app.logger.warning(f"Kitsu anime not found for ID: {kitsu_anime_id}")
            return None

        if anime.canonical_title:
            metadata['title'] = anime.canonical_title
        elif anime.title:
            if anime.title.en_jp:
                metadata['title'] = anime.title.en_jp
            elif anime.title.en:
                metadata['title'] = anime.title.en

        if anime.poster_image("large"):
            metadata['poster_url'] = anime.poster_image("large")
        elif anime.poster_image("original"):
            metadata['poster_url'] = anime.poster_image("original")

        if anime.start_date:
            try:
                if hasattr(anime.start_date, 'year'):
                    metadata['year'] = anime.start_date.year
                elif isinstance(anime.start_date, str):
                    metadata['year'] = int(anime.start_date.split('-')[0])
            except (ValueError, IndexError, AttributeError) as e:
                current_app.logger.warning(f"Could not parse year from Kitsu start_date ('{anime.start_date}'): {e}")

        if episode_num is not None:
            metadata['episode'] = episode_num
            episodes_data = await anime.episodes
            if episodes_data:
                episode_data = next((item for item in episodes_data if item.episode_number == episode_num), None)
                ep_title = None
                if not episode_data:
                    ep_title = ''
                else:
                    if episode_data.canonical_title:
                        ep_title = episode_data.canonical_title
                    elif episode_data.title:
                        if episode_data.title.en_jp:
                            ep_title = episode_data.title.en_jp
                        elif episode_data.title.en:
                            ep_title = episode_data.title.en

                if ep_title and ep_title.lower() != metadata['title'].lower():
                    metadata['title'] = f"{metadata['title']} - Ep {episode_num} - {ep_title}"
                else:
                    metadata['title'] = f"{metadata['title']} - Episode {episode_num}"
            else:
                metadata['title'] = f"{metadata['title']} - Episode {episode_num}"
        
        return metadata

    except Exception as e:
        current_app.logger.error(f"Error fetching Kitsu metadata for {content_id}: {e}")
        return None
    finally:
        if client and hasattr(client, 'close'):
            await client.close()


@cache.memoize(timeout=86400)
def get_metadata(content_id, content_type=None):
    """
    Public dispatcher function to fetch metadata from various sources.
    :param content_id: The ID of the content (e.g., 'tt12345', 'kitsu:123', 'kitsu:123:1').
    :param content_type: Type of content, primarily for TMDB ('movie', 'series').
    :return: Metadata dictionary or None.
    """
    if content_id and content_id.startswith('tt'):
        if not content_type:
            current_app.logger.warning(f"content_type not provided for TMDB ID {content_id}. Cannot determine if movie or series.")
            return None
        return _get_tmdb_metadata(content_id, content_type)
    elif content_id and content_id.startswith('kitsu:'):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(_get_kitsu_metadata(content_id))
    else:
        current_app.logger.info(f"Unsupported content_id format: {content_id}")
        return None
