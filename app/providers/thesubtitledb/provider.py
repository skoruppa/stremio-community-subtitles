"""Keyless TheSubtitleDB integration using its public v1 lookup endpoints."""
import asyncio
import re

import aiohttp
from iso639 import Lang
from iso639.exceptions import InvalidLanguageValue

from ..base import (
    BaseSubtitleProvider, SubtitleResult, ProviderAuthError,
    ProviderSearchError, ProviderDownloadError,
)
from ...version import USER_AGENT


API_BASE = 'https://api.thesubtitledb.org'


def language_code(code):
    """Convert SCS language codes to TSDB's single-language filter."""
    if code == 'pob':
        return 'pb'
    try:
        return Lang(code).pt1 or None
    except (KeyError, TypeError, InvalidLanguageValue):
        return None


class TheSubtitleDBProvider(BaseSubtitleProvider):
    name = 'thesubtitledb'
    display_name = 'TheSubtitleDB'
    badge_color = 'info'
    requires_auth = False
    supports_hash_matching = False  # TSDB infohash is not an OpenSubtitles file hash.

    async def authenticate(self, user, credentials):
        return {'active': True}

    async def logout(self, user):
        await self.save_credentials(user, {'active': False})
        return True

    async def is_authenticated(self, user):
        credentials = await self.get_credentials(user)
        return bool(credentials and credentials.get('active'))

    async def _lookup(self, session, path, params):
        async with session.get(API_BASE + '/v1' + path, params=params) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            data = await response.json()
            if not isinstance(data, dict):
                raise ValueError('Invalid lookup response')
            return data

    async def search(self, user, imdb_id=None, query=None, languages=None,
                     video_hash=None, season=None, episode=None,
                     content_type=None, **kwargs):
        if not await self.is_authenticated(user):
            raise ProviderAuthError('TheSubtitleDB is not active', self.name)
        if not imdb_id and not query:
            return []
        if imdb_id and not re.fullmatch(r'tt\d+', imdb_id):
            return []
        # Never return a whole show's files for a request lacking its season.
        if episode is not None and season is None:
            return []
        if any(value is not None and (not isinstance(value, int) or value < 0)
               for value in (season, episode)):
            return []
        requested = [(code, language_code(code)) for code in (languages or ['eng'])]
        requested = list(dict.fromkeys((code, lang) for code, lang in requested if lang))
        if not requested:
            return []
        results, seen = [], set()
        try:
            async with aiohttp.ClientSession(
                headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as session:
                if not imdb_id:
                    params = {'q': query, 'limit': 1}
                    if content_type in ('movie', 'series'):
                        params['type'] = 'tv' if content_type == 'series' else 'movie'
                    match = await self._lookup(session, '/by-title', params)
                    imdb_id = (match or {}).get('title', {}).get('imdb')
                    if not imdb_id or not re.fullmatch(r'tt\d+', imdb_id):
                        return []
                path = '/by-imdb/' + imdb_id
                if season is not None:
                    path += f'/season/{season}'
                    if episode is not None:
                        path += f'/episode/{episode}'
                for code, lang in requested:
                    for offset in range(0, 300, 100):
                        data = await self._lookup(session, path, {
                            'lang': lang, 'format': 'srt', 'sort': 'downloads',
                            'limit': 100, 'offset': offset,
                        })
                        if data is None:
                            break
                        page = data.get('subtitles', {})
                        items = page.get('items', [])
                        for item in items:
                            subtitle_id = str(item.get('id', ''))
                            if (not re.fullmatch(r'[1-9]\d*', subtitle_id)
                                    or subtitle_id in seen
                                    or item.get('language') != lang
                                    or item.get('format') != 'srt'):
                                continue
                            seen.add(subtitle_id)
                            results.append(SubtitleResult(
                                provider_name=self.name, subtitle_id=subtitle_id,
                                language=code, release_name=item.get('release_name'),
                                hearing_impaired=bool(item.get('hearing_impaired')),
                                fps=item.get('fps'), download_count=item.get('downloads'),
                            ))
                        if not items or offset + len(items) >= page.get('total', 0):
                            break
            return results
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderSearchError(
                f'TheSubtitleDB search failed: {exc}', self.name,
                status_code=getattr(exc, 'status', None),
            ) from exc

    async def get_download_url(self, user, subtitle_id):
        if not await self.is_authenticated(user):
            raise ProviderAuthError('TheSubtitleDB is not active', self.name)
        if not re.fullmatch(r'[1-9]\d*', str(subtitle_id)):
            raise ProviderDownloadError('Invalid TheSubtitleDB subtitle ID', self.name)
        # Construct a trusted URL, rather than persisting an arbitrary upstream URL.
        return f'{API_BASE}/get/{subtitle_id}'

    def get_settings_template(self):
        return 'providers/thesubtitledb_form.html'
