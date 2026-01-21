"""Napisy24 provider implementation"""
from typing import List, Dict, Optional, Any

from ..base import BaseSubtitleProvider, SubtitleResult, ProviderAuthError, ProviderSearchError, ProviderDownloadError
from . import client


class Napisy24Provider(BaseSubtitleProvider):
    """Napisy24.pl subtitle provider (Polish only)"""
    
    name = 'napisy24'
    display_name = 'Napisy24'
    badge_color = 'danger'
    requires_auth = False
    supports_search = True
    supports_hash_matching = True
    can_return_ass = False
    has_additional_settings = False
    supported_languages = ['pol']
    
    def authenticate(self, user, credentials: Dict[str, str]) -> Dict[str, Any]:
        """No authentication needed for Napisy24"""
        return {'active': True}
    
    def logout(self, user) -> bool:
        """Logout (no-op for Napisy24)"""
        return True
    
    def is_authenticated(self, user) -> bool:
        """Check if provider is active"""
        creds = self.get_credentials(user)
        return creds is not None and creds.get('active', False)
    
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
        """Search Napisy24"""
        if not self.is_authenticated(user):
            raise ProviderSearchError("Not authenticated", self.name)
        
        # Filter by language
        if languages and 'pol' not in languages:
            return []
        
        results = []
        
        # Try hash matching first
        if video_hash:
            video_filename = kwargs.get('video_filename', '')
            video_size = kwargs.get('video_size', '')
            hash_result = client.search_by_hash(video_hash, str(video_size), video_filename)
            if hash_result:
                results.append(SubtitleResult(
                    provider_name=self.name,
                    subtitle_id=hash_result['id'],
                    language='pol',
                    release_name=hash_result['release'],
                    fps=hash_result.get('fps'),
                    metadata={'hash_match': True}
                ))
                return results
        
        # Fallback to IMDb and title search
        if imdb_id or query:
            seen_ids = set()
            
            # Try IMDb search
            if imdb_id:
                try:
                    imdb_results = client.search_by_imdb(
                        imdb_id=imdb_id,
                        season=season,
                        episode=episode,
                        filename=kwargs.get('video_filename')
                    )
                    for item in imdb_results:
                        if item['id'] not in seen_ids:
                            seen_ids.add(item['id'])
                            results.append(SubtitleResult(
                                provider_name=self.name,
                                subtitle_id=item['id'],
                                language='pol',
                                release_name=item['release'],
                                uploader=item.get('author'),
                                fps=item.get('fps')
                            ))
                except client.Napisy24Error:
                    pass
            
            # Try title search
            search_title = query
            if not search_title and imdb_id:
                # Try to get title from metadata
                try:
                    from ...lib.metadata import get_metadata
                    # Reconstruct content_id
                    content_id = imdb_id
                    if season and episode:
                        content_id = f"{imdb_id}:{season}:{episode}"
                    elif episode:
                        content_id = f"{imdb_id}:{episode}"
                    
                    metadata = get_metadata(content_id, content_type)
                    if metadata and metadata.get('title'):
                        search_title = metadata['title']
                except:
                    pass
            
            if search_title:
                try:
                    import re
                    # Remove S01E01 pattern and everything after it
                    search_title = re.split(r'\s+S\d+E\d+', search_title, flags=re.IGNORECASE)[0].strip()
                    
                    title_results = client.search_by_title(
                        title=search_title,
                        season=season,
                        episode=episode,
                        filename=kwargs.get('video_filename')
                    )
                    for item in title_results:
                        if item['id'] not in seen_ids:
                            seen_ids.add(item['id'])
                            results.append(SubtitleResult(
                                provider_name=self.name,
                                subtitle_id=item['id'],
                                language='pol',
                                release_name=item['release'],
                                uploader=item.get('author'),
                                fps=item.get('fps')
                            ))
                except:
                    pass
        
        return results
    
    def get_download_url(self, user, subtitle_id: str) -> Optional[str]:
        """Napisy24 requires direct download"""
        return None
    
    def download_subtitle(self, user, subtitle_id: str) -> bytes:
        """Download subtitle from Napisy24"""
        if not self.is_authenticated(user):
            raise ProviderDownloadError("Not authenticated", self.name)
        
        try:
            return client.download_subtitle(subtitle_id)
        except client.Napisy24Error as e:
            raise ProviderDownloadError(str(e), self.name, getattr(e, 'status_code', None))
    
    def get_settings_template(self) -> str:
        """Get settings template path"""
        return 'providers/napisy24_settings.html'
