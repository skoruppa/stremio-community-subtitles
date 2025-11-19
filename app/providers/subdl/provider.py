"""SubDL provider implementation"""
from typing import List, Dict, Optional, Any
from flask_wtf import FlaskForm
from flask import current_app

from ..base import BaseSubtitleProvider, SubtitleResult, ProviderAuthError, ProviderSearchError, ProviderDownloadError
from . import client


class SubDLProvider(BaseSubtitleProvider):
    """SubDL.com subtitle provider"""
    
    name = 'subdl'
    display_name = 'SubDL'
    requires_auth = True  # Requires API key
    supports_search = True
    supports_hash_matching = False  # SubDL doesn't support hash matching
    can_return_ass = True  # SubDL returns ZIP files that may contain ASS
    
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
        
        try:
            results = client.search_subtitles(
                api_key=api_key,
                imdb_id=imdb_id,
                languages=subdl_languages,
                season=season,
                episode=episode,
                type=subdl_type
            )
            return self._parse_results(results)
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
    
    def get_settings_form(self) -> FlaskForm:
        """Get settings form (not used in new architecture)"""
        return None
    
    def get_settings_template(self) -> str:
        """Get settings template path"""
        return 'providers/subdl_form.html'
    
    def _convert_languages(self, languages: List[str]) -> List[str]:
        """Convert ISO 639-3 to ISO 639-1 for SubDL"""
        from iso639 import Lang
        
        converted = []
        for lang in languages:
            # Special cases
            if lang == 'pob':
                converted.append('pt')
            elif lang == 'por':
                converted.append('pt')
            else:
                try:
                    converted.append(Lang(lang).pt1)
                except KeyError:
                    current_app.logger.warning(f"Could not convert language {lang}")
                    # Try using first 2 letters as fallback
                    if len(lang) >= 2:
                        converted.append(lang[:2])
        
        return converted
    
    def _parse_results(self, api_response: Dict) -> List[SubtitleResult]:
        """Parse SubDL API response to SubtitleResult objects"""
        results = []
        
        if not api_response or not api_response.get('subtitles'):
            return results
        
        for item in api_response['subtitles']:
            # SubDL response structure
            subtitle_id = item.get('url') or item.get('download_url') or str(item.get('id', ''))
            
            if not subtitle_id:
                continue
            
            results.append(SubtitleResult(
                provider_name=self.name,
                subtitle_id=subtitle_id,  # Store download URL as ID
                language=item.get('language', ''),
                release_name=item.get('release_name') or item.get('name'),
                uploader=item.get('author') or item.get('uploader'),
                download_count=item.get('download_count'),
                rating=item.get('rating'),
                hearing_impaired=item.get('hi', False) or item.get('hearing_impaired', False),
                ai_translated=False,  # SubDL doesn't have AI translations
                fps=item.get('fps'),
                metadata={
                    'hash_match': False,  # SubDL doesn't support hash matching
                    'url': subtitle_id,
                    'season': item.get('season'),
                    'episode': item.get('episode')
                }
            ))
        
        return results
