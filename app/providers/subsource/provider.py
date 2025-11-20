from typing import List, Optional
from flask import current_app
from ..base import BaseSubtitleProvider, SubtitleResult, ProviderAuthError, ProviderDownloadError
from .client import SubSourceClient


# Language mapping: ISO 639-3 -> SubSource language names
LANGUAGE_MAP = {
    'eng': 'english',
    'pol': 'polish',
    'spa': 'spanish',
    'fre': 'french',
    'ger': 'german',
    'ita': 'italian',
    'por': 'portuguese',
    'rus': 'russian',
    'ara': 'arabic',
    'chi': 'chinese',
    'jpn': 'japanese',
    'kor': 'korean',
    'tur': 'turkish',
    'dut': 'dutch',
    'swe': 'swedish',
    'nor': 'norwegian',
    'dan': 'danish',
    'fin': 'finnish',
    'cze': 'czech',
    'hun': 'hungarian',
    'rum': 'romanian',
    'gre': 'greek',
    'heb': 'hebrew',
    'tha': 'thai',
    'vie': 'vietnamese',
}


class SubSourceProvider(BaseSubtitleProvider):
    name = 'subsource'
    display_name = 'SubSource'
    badge_color = 'primary'
    requires_auth = True
    supports_search = True
    supports_hash_matching = False
    can_return_ass = True
    has_additional_settings = True
    
    def authenticate(self, user, credentials: dict) -> dict:
        """Authenticate with SubSource API"""
        api_key = credentials.get('api_key', '').strip()
        
        if not api_key:
            raise ProviderAuthError("API key is required")
        
        # Test API key
        try:
            client = SubSourceClient(api_key)
            # Try a simple search to validate key
            client.search_movie('tt0111161')
            
            return {
                'api_key': api_key,
                'active': True
            }
        except Exception as e:
            current_app.logger.error(f"SubSource auth failed: {e}")
            raise ProviderAuthError(f"Invalid API key: {str(e)}")
    
    def logout(self, user) -> None:
        """Logout from SubSource"""
        creds = self.get_credentials(user)
        if creds:
            creds['active'] = False
            creds['api_key'] = None
            self.save_credentials(user, creds)
    
    def is_authenticated(self, user) -> bool:
        """Check if user is authenticated"""
        creds = self.get_credentials(user)
        return creds and creds.get('active') and creds.get('api_key')
    
    def search(self, user, imdb_id: str = None, languages: List[str] = None, 
               season: int = None, episode: int = None, **kwargs) -> List[SubtitleResult]:
        """Search for subtitles"""
        if not imdb_id:
            return []
        
        creds = self.get_credentials(user)
        if not creds or not creds.get('api_key'):
            raise ProviderAuthError("Not authenticated")
        
        try:
            client = SubSourceClient(creds['api_key'])
            
            # Search for movie/series
            movie = client.search_movie(imdb_id, season=season)
            if not movie:
                return []
            
            movie_id = movie['movieId']
            results = []
            
            # Get subtitles for each language with pagination
            for lang_code in (languages or ['eng']):
                subsource_lang = LANGUAGE_MAP.get(lang_code)
                if not subsource_lang:
                    continue
                
                page = 1
                max_pages = 3  # Limit to first 3 pages
                
                while page <= max_pages:
                    response = client.get_subtitles(movie_id, subsource_lang, page=page, limit=20)
                    
                    if not response.get('success') or not response.get('data'):
                        break
                    
                    for sub in response['data']:
                        release_info = ' '.join(sub.get('releaseInfo', []))
                        commentary = sub.get('commentary', '')
                        
                        # Filter by episode if provided
                        if episode:
                            import re
                            text_to_check = f"{release_info} {commentary}".lower()
                            
                            # Check for exact episode match with word boundaries
                            episode_patterns = [
                                rf'\bep{episode:03d}\b',  # Ep101
                                rf'\bep{episode:02d}\b',  # Ep01
                                rf'\bep{episode}\b',  # Ep1
                                rf'\bepisode\s+{episode}\b',  # Episode 101
                                rf'\b-\s*{episode:03d}\b',  # - 101
                                rf'\b{episode:03d}\b',  # 101 (standalone)
                                rf'\b{episode:02d}\b',  # 01 (standalone)
                            ]
                            
                            exact_match = any(re.search(pattern, text_to_check) for pattern in episode_patterns)
                            
                            if not exact_match:
                                # Check if it's in a range (e.g., "Ep1-100", "101-148")
                                range_patterns = [
                                    r'ep?(\d+)-(\d+)',  # Ep1-100, 1-100
                                    r'(\d+)\s*-\s*(\d+)',  # "101 - 148"
                                ]
                                in_range = False
                                for pattern in range_patterns:
                                    for match in re.finditer(pattern, text_to_check):
                                        start = int(match.group(1))
                                        end = int(match.group(2))
                                        if start <= episode <= end:
                                            in_range = True
                                            break
                                    if in_range:
                                        break
                                
                                if not in_range:
                                    continue  # Skip this subtitle
                        
                        # Build uploader name
                        uploader = None
                        if sub.get('contributors'):
                            uploader = sub['contributors'][0].get('displayname')
                        
                        # Calculate rating (good / total)
                        rating = 0.0
                        rating_data = sub.get('rating', {})
                        if rating_data.get('total', 0) > 0:
                            rating = rating_data.get('good', 0) / rating_data['total']
                        
                        results.append(SubtitleResult(
                            subtitle_id=str(sub['subtitleId']),
                            release_name=release_info or f"SubSource {sub['subtitleId']}",
                            language=lang_code,
                            uploader=uploader,
                            rating=rating,
                            download_count=sub.get('downloads', 0),
                            hearing_impaired=sub.get('hearingImpaired', False),
                            ai_translated=False,
                            provider_name=self.name,
                            metadata={
                                'movie_id': movie_id,
                                'files': sub.get('files', 1),
                                'framerate': sub.get('framerate'),
                                'production_type': sub.get('productionType'),
                                'release_type': sub.get('releaseType'),
                                'commentary': sub.get('commentary')
                            }
                        ))
                    
                    # Check if there are more pages
                    pagination = response.get('pagination', {})
                    if page >= pagination.get('pages', 1):
                        break
                    
                    page += 1
            
            return results
            
        except Exception as e:
            current_app.logger.error(f"SubSource search failed: {e}")
            raise
    
    def get_download_url(self, user, subtitle_id: str) -> str:
        """SubSource doesn't provide direct URLs, must use download_subtitle() method"""
        # Return None to indicate that download must be handled via download_subtitle()
        return None
    
    def download_subtitle(self, user, subtitle_id: str) -> bytes:
        """Download subtitle ZIP file"""
        creds = self.get_credentials(user)
        if not creds or not creds.get('api_key'):
            raise ProviderAuthError("Not authenticated")
        
        try:
            client = SubSourceClient(creds['api_key'])
            return client.download_subtitle(int(subtitle_id))
        except Exception as e:
            current_app.logger.error(f"SubSource download failed: {e}")
            raise ProviderDownloadError(f"Failed to download subtitle: {str(e)}")
    
    def get_settings_template(self) -> str:
        """Get settings template path"""
        return 'providers/subsource_form.html'
