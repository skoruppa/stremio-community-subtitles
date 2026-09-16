"""TheSubtitleDB.org provider implementation

Free, no-auth subtitle provider. Rate limit: 150 downloads/hour per IP.
Download URLs are returned as redirects — Stremio/Nuvio fetches directly.
"""
from typing import List, Dict, Optional, Any
from quart import current_app
from iso639 import Lang

from ..base import BaseSubtitleProvider, SubtitleResult, ProviderSearchError, ProviderDownloadError
from . import client


# Map ISO 639-3 (our internal) → SubtitleDB 2-letter codes
# SubtitleDB uses ISO 639-1 with a few custom codes:
#   pb = Portuguese (Brazilian), zt = Chinese (Traditional), ze = Chinese (bilingual)
_TO_SUBTITLEDB = {
    'pob': 'pb',
    'por': 'pt',
    'zho': 'zh',
    'zht': 'zt',
}

# Reverse: SubtitleDB → ISO 639-3
_FROM_SUBTITLEDB = {
    'pb': 'pob',
    'pt': 'por',
    'zh': 'zho',
    'zt': 'zht',
    'ze': 'zho',
}


class SubtitleDBProvider(BaseSubtitleProvider):
    """TheSubtitleDB.org — free, API-key-less subtitle provider"""

    name = 'subtitledb'
    display_name = 'TheSubtitleDB'
    badge_color = 'info'
    requires_auth = False
    supports_search = True
    supports_hash_matching = False
    can_return_ass = True  # API supports format filter

    async def authenticate(self, user, credentials: Dict[str, str]) -> Dict[str, Any]:
        """No authentication needed — just mark as active."""
        return {'active': True}

    async def logout(self, user) -> bool:
        creds = await self.get_credentials(user)
        if creds:
            creds['active'] = False
            await self.save_credentials(user, creds)
        return True

    async def is_authenticated(self, user) -> bool:
        """Always usable — no auth required. Just check if user enabled it."""
        creds = await self.get_credentials(user)
        return bool(creds and creds.get('active'))

    async def search(
        self,
        user,
        imdb_id: Optional[str] = None,
        query: Optional[str] = None,
        languages: Optional[List[str]] = None,
        video_hash: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        content_type: Optional[str] = None,
        **kwargs
    ) -> List[SubtitleResult]:
        """Search TheSubtitleDB for subtitles.
        
        Tries IMDb ID first, falls back to TMDB ID via metadata lookup."""
        if not imdb_id:
            return []

        results = []

        for lang_code in (languages or ['eng']):
            sdb_lang = self._to_provider_language(lang_code)
            if not sdb_lang:
                continue

            try:
                # Try IMDb first
                data = await client.search_by_imdb(
                    imdb_id=imdb_id,
                    language=sdb_lang,
                    season=season,
                    episode=episode,
                    limit=30,
                )

                # Fallback to TMDB if IMDb returned nothing
                if not data or not self._has_items(data):
                    tmdb_id = await self._resolve_tmdb_id(imdb_id, season, episode, content_type)
                    if tmdb_id:
                        data = await client.search_by_tmdb(
                            tmdb_id=tmdb_id,
                            language=sdb_lang,
                            season=season,
                            episode=episode,
                            limit=30,
                        )

                if not data:
                    continue

                items = []
                subtitles_block = data.get('subtitles')
                if subtitles_block and subtitles_block.get('items'):
                    items = subtitles_block['items']

                for item in items:
                    results.append(SubtitleResult(
                        provider_name=self.name,
                        subtitle_id=str(item['id']),
                        language=lang_code,
                        release_name=item.get('release_name') or f"SubtitleDB {item['id']}",
                        uploader=None,
                        download_count=None,
                        rating=None,
                        hearing_impaired=item.get('hearing_impaired', False),
                        ai_translated=False,
                        fps=item.get('fps'),
                        forced=False,
                        metadata={
                            'format': item.get('format'),
                            'encoding': item.get('encoding'),
                            'cues': item.get('cues'),
                            'bytes': item.get('bytes'),
                            'download_url': item.get('download_url'),
                        }
                    ))

            except client.SubtitleDBError as e:
                if e.status_code == 429:
                    current_app.logger.debug(f"SubtitleDB rate limited for {imdb_id}")
                    break
                current_app.logger.debug(f"SubtitleDB search error for {imdb_id}: {e}")
            except Exception as e:
                current_app.logger.debug(f"SubtitleDB search failed: {e}")

        return results

    async def get_download_url(self, user, subtitle_id: str) -> Optional[str]:
        """Return download URL — Stremio/Nuvio follows the redirect itself."""
        return client.get_download_url(subtitle_id)

    def get_settings_template(self) -> str:
        return 'providers/subtitledb_form.html'

    def _to_provider_language(self, lang_code: str) -> Optional[str]:
        """Convert ISO 639-3 to SubtitleDB 2-letter code."""
        if lang_code in _TO_SUBTITLEDB:
            return _TO_SUBTITLEDB[lang_code]
        try:
            return Lang(lang_code).pt1
        except (KeyError, AttributeError):
            current_app.logger.debug(f"SubtitleDB: cannot convert language {lang_code}")
            return None

    def _from_provider_language(self, lang_code: str) -> str:
        """Convert SubtitleDB 2-letter code to ISO 639-3."""
        if lang_code in _FROM_SUBTITLEDB:
            return _FROM_SUBTITLEDB[lang_code]
        try:
            return Lang(lang_code).pt3
        except (KeyError, AttributeError):
            return lang_code

    @staticmethod
    def _has_items(data: dict) -> bool:
        """Check if API response contains subtitle items."""
        subs = data.get('subtitles')
        return bool(subs and subs.get('items'))

    @staticmethod
    async def _resolve_tmdb_id(imdb_id, season, episode, content_type) -> Optional[int]:
        """Resolve TMDB ID from IMDb ID via cached metadata lookup."""
        try:
            from ...lib.metadata import get_metadata
            content_id = imdb_id
            if season and episode:
                content_id = f"{imdb_id}:{season}:{episode}"
            elif episode:
                content_id = f"{imdb_id}:{episode}"
            metadata = await get_metadata(content_id, content_type)
            if metadata and metadata.get('tmdb_id'):
                return metadata['tmdb_id']
        except Exception:
            pass
        return None
