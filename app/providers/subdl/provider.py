"""SubDL provider implementation"""
from typing import List, Dict, Optional, Any
from flask import current_app

from ..base import BaseSubtitleProvider, SubtitleResult, ProviderAuthError, ProviderSearchError, ProviderDownloadError
from . import client


class SubDLProvider(BaseSubtitleProvider):
    """SubDL.com subtitle provider"""
    
    name = 'subdl'
    display_name = 'SubDL'
    badge_color = 'success'
    requires_auth = True  # Requires API key
    supports_search = True
    supports_hash_matching = False  # SubDL doesn't support hash matching
    can_return_ass = True  # SubDL returns ZIP files that may contain ASS
    has_additional_settings = True  # Has try_provide_ass setting
    
    def authenticate(self, user, credentials: Dict[str, str]) -> Dict[str, Any]:
        """Authenticate with SubDL (validate API key)"""
        api_key = credentials.get('api_key')
        
        if not api_key:
            raise ProviderAuthError("API key required", self.name)
        
        # Test API key with a simple search
        try:
            # Try searching for a known movie to validate key
            client.search_subtitles(api_key, imdb_id='tt0111161', languages=['en'])
            return {
                'api_key': api_key,
                'active': True
            }
        except client.SubDLError as e:
            raise ProviderAuthError(f"Invalid API key: {str(e)}", self.name, getattr(e, 'status_code', None))
    
    def logout(self, user) -> bool:
        """Logout from SubDL (just clear credentials)"""
        return True
    
    def is_authenticated(self, user) -> bool:
        """Check if user has valid SubDL API key"""
        creds = self.get_credentials(user)
        return bool(creds and creds.get('active') and creds.get('api_key'))
    
    def search(
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
        """Search SubDL"""
        if not self.is_authenticated(user):
            raise ProviderSearchError("Not authenticated", self.name)
        
        creds = self.get_credentials(user)
        api_key = creds['api_key']
        
        # SubDL doesn't support hash matching
        if video_hash and not imdb_id:
            current_app.logger.info("SubDL doesn't support hash-only search")
            return []
        
        # Convert languages to 2-letter codes
        subdl_languages = self._convert_languages(languages) if languages else None
        
        # Determine type
        subdl_type = None
        if content_type == 'movie':
            subdl_type = 'movie'
        elif content_type == 'series' or season is not None or episode is not None:
            subdl_type = 'tv'
        
        # Extract filename from kwargs
        file_name = kwargs.get('video_filename')
        
        try:
            results = client.search_subtitles(
                api_key=api_key,
                imdb_id=imdb_id,
                languages=subdl_languages,
                season=season,
                episode=episode,
                type=subdl_type,
                file_name=file_name
            )
            return self._parse_results(results, season=season, episode=episode)
        except client.SubDLError as e:
            raise ProviderSearchError(str(e), self.name, getattr(e, 'status_code', None))
    
    def get_download_url(self, user, subtitle_id: str) -> str:
        """Get download URL for SubDL subtitle"""
        if not self.is_authenticated(user):
            raise ProviderDownloadError("Not authenticated", self.name)
        
        # SubDL provides direct download URLs in search results
        # subtitle_id should be the full download URL
        if subtitle_id.startswith('http'):
            return subtitle_id
        
        # Fallback
        creds = self.get_credentials(user)
        return client.get_download_url(creds['api_key'], subtitle_id)
    
    def get_settings_template(self) -> str:
        """Get settings template path"""
        return 'providers/subdl_form.html'
    
    def _convert_languages(self, languages: List[str]) -> List[str]:
        """Convert ISO 639-3 to SubDL format"""
        subdl_map = {
            'ara': 'ar', 'pob': 'br_pt', 'dan': 'da', 'nld': 'nl', 'eng': 'en',
            'fas': 'fa', 'fin': 'fi', 'fre': 'fr', 'ind': 'id', 'ita': 'it',
            'nor': 'no', 'ron': 'ro', 'spa': 'es', 'swe': 'sv', 'vie': 'vi',
            'sqi': 'sq', 'ben': 'bn', 'bul': 'bg', 'mya': 'my', 'cat': 'ca',
            'zho': 'zh', 'hrv': 'hr', 'ces': 'cs', 'epo': 'eo', 'est': 'et',
            'deu': 'de', 'ell': 'el', 'heb': 'he', 'hin': 'hi', 'hun': 'hu',
            'isl': 'is', 'jpn': 'ja', 'kor': 'ko', 'lav': 'lv', 'lit': 'lt',
            'mkd': 'mk', 'msa': 'ms', 'pol': 'pl', 'por': 'pt', 'rus': 'ru',
            'srp': 'sr', 'slk': 'sk', 'slv': 'sl', 'tha': 'th', 'tur': 'tr',
            'ukr': 'uk', 'urd': 'ur'
        }
        return [subdl_map.get(lang, lang[:2] if len(lang) >= 2 else lang) for lang in languages]
    
    def _convert_from_provider_language(self, lang_code: str) -> str:
        """Convert SubDL format to ISO 639-3"""
        reverse_map = {
            'ar': 'ara', 'br_pt': 'pob', 'da': 'dan', 'nl': 'nld', 'en': 'eng',
            'fa': 'fas', 'fi': 'fin', 'fr': 'fre', 'id': 'ind', 'it': 'ita',
            'no': 'nor', 'ro': 'ron', 'es': 'spa', 'sv': 'swe', 'vi': 'vie',
            'sq': 'sqi', 'bn': 'ben', 'bg': 'bul', 'my': 'mya', 'ca': 'cat',
            'zh': 'zho', 'hr': 'hrv', 'cs': 'ces', 'eo': 'epo', 'et': 'est',
            'de': 'deu', 'el': 'ell', 'he': 'heb', 'hi': 'hin', 'hu': 'hun',
            'is': 'isl', 'ja': 'jpn', 'ko': 'kor', 'lv': 'lav', 'lt': 'lit',
            'mk': 'mkd', 'ms': 'msa', 'pl': 'pol', 'pt': 'por', 'ru': 'rus',
            'sr': 'srp', 'sk': 'slk', 'sl': 'slv', 'th': 'tha', 'tr': 'tur',
            'uk': 'ukr', 'ur': 'urd'
        }
        return reverse_map.get(lang_code.lower(), lang_code)
    
    def _parse_results(self, api_response: Dict, season: Optional[int] = None, episode: Optional[int] = None) -> List[SubtitleResult]:
        """Parse SubDL API response to SubtitleResult objects"""
        results = []
        
        if not api_response or not api_response.get('subtitles'):
            return results
        
        for item in api_response['subtitles']:
            # Filter by season/episode (only for series, not movies)
            item_season = item.get('season')
            item_episode = item.get('episode')
            episode_from = item.get('episode_from')
            episode_end = item.get('episode_end')
            
            # Skip filtering for movies (season=0 or None)
            if item_season and item_season > 0:
                # Skip if season doesn't match
                if season is not None and item_season != season:
                    continue
                
                # Skip if episode doesn't match (unless it's a full season pack)
                if episode is not None:
                    # Full season pack: episode_from is null and episode_end is 0
                    is_full_season = episode_from is None and episode_end == 0
                    
                    if not is_full_season:
                        # Check if our episode is in range
                        if episode_from is not None and episode_end is not None:
                            if not (episode_from <= episode <= episode_end):
                                continue
            
            # SubDL response structure
            subtitle_url = item.get('url')
            
            if not subtitle_url:
                continue
            
            lang_code = self._convert_from_provider_language(item.get('language', ''))
            
            results.append(SubtitleResult(
                provider_name=self.name,
                subtitle_id=subtitle_url,  # Store full download URL as ID
                language=lang_code,
                release_name=item.get('release_name') or item.get('name'),
                uploader=item.get('author') or item.get('uploader'),
                download_count=item.get('download_count'),
                rating=item.get('rating'),
                hearing_impaired=item.get('hi', False) or item.get('hearing_impaired', False),
                ai_translated=False,  # SubDL doesn't have AI translations
                fps=item.get('fps'),
                metadata={
                    'hash_match': False,  # SubDL doesn't support hash matching
                    'url': subtitle_url,
                    'season': item_season,
                    'episode': item_episode,
                    'episode_from': episode_from,
                    'episode_end': episode_end
                }
            ))
        
        return results
