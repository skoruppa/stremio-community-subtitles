"""OpenSubtitles provider implementation"""
from typing import List, Dict, Optional, Any
from flask import current_app
from iso639 import Lang

from ..base import BaseSubtitleProvider, SubtitleResult, ProviderAuthError, ProviderSearchError, ProviderDownloadError
from . import client as opensubtitles_client


class OpenSubtitlesProvider(BaseSubtitleProvider):
    """OpenSubtitles.com subtitle provider"""
    
    name = 'opensubtitles'
    display_name = 'OpenSubtitles.com'
    badge_color = 'warning'
    requires_auth = True
    supports_search = True
    supports_hash_matching = True
    
    def authenticate(self, user, credentials: Dict[str, str]) -> Dict[str, Any]:
        """Authenticate with OpenSubtitles"""
        username = credentials.get('username')
        password = credentials.get('password')
        
        if not username or not password:
            raise ProviderAuthError("Username and password required", self.name)
        
        try:
            result = opensubtitles_client.login(username, password, user)
            return {
                'token': result['token'],
                'base_url': result['base_url'],
                'active': True,
                'username': username
            }
        except opensubtitles_client.OpenSubtitlesError as e:
            raise ProviderAuthError(str(e), self.name, getattr(e, 'status_code', None))
    
    def logout(self, user) -> bool:
        """Logout from OpenSubtitles"""
        creds = self.get_credentials(user)
        if not creds:
            return True
        
        try:
            # Create temporary user object with old-style attributes for backward compatibility
            class TempUser:
                def __init__(self, token, base_url):
                    self.opensubtitles_token = token
                    self.opensubtitles_base_url = base_url
            
            temp_user = TempUser(creds['token'], creds['base_url'])
            opensubtitles_client.logout(creds['token'], temp_user)
            return True
        except Exception as e:
            current_app.logger.error(f"OpenSubtitles logout error: {e}")
            return False
    
    def is_authenticated(self, user) -> bool:
        """Check if user has valid OpenSubtitles credentials"""
        creds = self.get_credentials(user)
        return bool(creds and creds.get('active') and creds.get('token') and creds.get('base_url'))
    
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
        """Search OpenSubtitles"""
        if not self.is_authenticated(user):
            raise ProviderSearchError("Not authenticated", self.name)
        
        creds = self.get_credentials(user)
        
        # Convert languages to OpenSubtitles format
        os_languages = self._convert_languages(languages) if languages else None
        
        # Build search params
        search_params = {}
        if imdb_id:
            search_params['imdb_id'] = imdb_id
        if query:
            search_params['query'] = query
        if os_languages:
            search_params['languages'] = os_languages
        if video_hash:
            search_params['moviehash'] = video_hash
        if season is not None:
            search_params['season_number'] = season
        if episode is not None:
            search_params['episode_number'] = episode
        if content_type:
            search_params['type'] = 'episode' if content_type == 'series' else content_type
        
        # Create temp user for backward compatibility
        class TempUser:
            def __init__(self, token, base_url):
                self.opensubtitles_token = token
                self.opensubtitles_base_url = base_url
        
        temp_user = TempUser(creds['token'], creds['base_url'])
        
        try:
            results = opensubtitles_client.search_subtitles(**search_params, user=temp_user)
            return self._parse_results(results)
        except opensubtitles_client.OpenSubtitlesError as e:
            raise ProviderSearchError(str(e), self.name, getattr(e, 'status_code', None))
    
    def get_download_url(self, user, subtitle_id: str) -> str:
        """Get download URL for OpenSubtitles subtitle"""
        if not self.is_authenticated(user):
            raise ProviderDownloadError("Not authenticated", self.name)
        
        creds = self.get_credentials(user)
        
        # Create temp user
        class TempUser:
            def __init__(self, token, base_url):
                self.opensubtitles_token = token
                self.opensubtitles_base_url = base_url
        
        temp_user = TempUser(creds['token'], creds['base_url'])
        
        try:
            result = opensubtitles_client.request_download_link(int(subtitle_id), temp_user)
            return result.get('link')
        except opensubtitles_client.OpenSubtitlesError as e:
            raise ProviderDownloadError(str(e), self.name, getattr(e, 'status_code', None))
    
    def get_settings_template(self) -> str:
        """Get settings template path"""
        return 'providers/opensubtitles_form.html'
    
    def _convert_languages(self, languages: List[str]) -> str:
        """Convert ISO 639-3 to ISO 639-1 for OpenSubtitles"""
        converted = []
        for lang in languages:
            if lang == 'pob':
                converted.append('pt-br')
            elif lang == 'por':
                converted.append('pt-pt')
            else:
                try:
                    converted.append(Lang(lang).pt1)
                except KeyError:
                    current_app.logger.warning(f"Could not convert language {lang}")
                    converted.append(lang)
        return ','.join(converted)
    
    def _convert_from_provider_language(self, lang_code: str) -> str:
        """Convert OpenSubtitles ISO 639-1 to ISO 639-3"""
        if lang_code.lower() == 'pt-br':
            return 'pob'
        elif lang_code.lower() == 'pt-pt':
            return 'por'
        elif len(lang_code) == 2:
            try:
                return Lang(lang_code).pt3
            except KeyError:
                current_app.logger.warning(f"Could not convert language {lang_code} to ISO 639-3")
                return lang_code
        return lang_code
    
    def _parse_results(self, api_response: Dict) -> List[SubtitleResult]:
        """Parse OpenSubtitles API response to SubtitleResult objects"""
        results = []
        
        if not api_response or not api_response.get('data'):
            return results
        
        for item in api_response['data']:
            attrs = item.get('attributes', {})
            files = attrs.get('files', [])
            
            if not files:
                continue
            
            file_info = files[0]
            file_id = file_info.get('file_id')
            
            if not file_id:
                continue
            
            # Convert language from ISO 639-1 to ISO 639-3
            lang_code = attrs.get('language', '')
            lang_code = self._convert_from_provider_language(lang_code)
            
            results.append(SubtitleResult(
                provider_name=self.name,
                subtitle_id=str(file_id),
                language=lang_code,
                release_name=file_info.get('file_name'),
                uploader=attrs.get('uploader', {}).get('name'),
                download_count=attrs.get('download_count'),
                rating=attrs.get('ratings'),
                hearing_impaired=attrs.get('hearing_impaired', False),
                ai_translated=attrs.get('ai_translated', False) or attrs.get('machine_translated', False),
                fps=attrs.get('fps'),
                metadata={
                    'hash_match': attrs.get('moviehash_match', False),
                    'url': attrs.get('url'),
                    'original_file_id': file_id
                }
            ))
        
        return results
