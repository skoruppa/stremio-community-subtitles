"""
Async base abstract class for subtitle providers.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class SubtitleResult:
    """Standardized subtitle result from any provider"""
    provider_name: str
    subtitle_id: str
    language: str
    release_name: Optional[str] = None
    uploader: Optional[str] = None
    download_count: Optional[int] = None
    rating: Optional[float] = None
    hearing_impaired: bool = False
    ai_translated: bool = False
    fps: Optional[float] = None
    forced: bool = False
    metadata: Optional[Dict[str, Any]] = None


class BaseSubtitleProvider(ABC):
    """Async base class for subtitle providers"""
    
    name: str = None
    display_name: str = None
    badge_color: str = 'primary'
    requires_auth: bool = True
    supports_search: bool = True
    supports_hash_matching: bool = True
    can_return_ass: bool = False
    has_additional_settings: bool = False
    supported_languages: List[str] = None
    
    def __init__(self):
        if not self.name or not self.display_name:
            raise ValueError(f"Provider must define 'name' and 'display_name'")
    
    @abstractmethod
    async def authenticate(self, user, credentials: Dict[str, str]) -> Dict[str, Any]:
        """Authenticate user with the provider (async)"""
        pass
    
    @abstractmethod
    async def logout(self, user) -> bool:
        """Logout user from the provider (async)"""
        pass
    
    @abstractmethod
    async def is_authenticated(self, user) -> bool:
        """Check if user is authenticated (async)"""
        pass
    
    async def get_credentials(self, user) -> Optional[Dict[str, Any]]:
        """Get user's credentials for this provider"""
        if not hasattr(user, 'provider_credentials') or not user.provider_credentials:
            return None
        return user.provider_credentials.get(self.name)
    
    async def save_credentials(self, user, credentials: Dict[str, Any]):
        """Save credentials to user model"""
        if not hasattr(user, 'provider_credentials'):
            user.provider_credentials = {}
        if user.provider_credentials is None:
            user.provider_credentials = {}
        user.provider_credentials[self.name] = credentials
    
    @abstractmethod
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
        """Search for subtitles (async)"""
        pass
    
    @abstractmethod
    async def get_download_url(self, user, subtitle_id: str) -> Optional[str]:
        """Get direct download URL for a subtitle (async)"""
        pass
    
    async def download_subtitle(self, user, subtitle_id: str) -> bytes:
        """Download subtitle content directly (async)"""
        raise NotImplementedError(f"{self.name} does not implement download_subtitle()")
    
    @abstractmethod
    def get_settings_template(self) -> str:
        """Get template path for provider settings card"""
        pass
    
    async def link_subtitle_to_hash(
        self,
        user,
        subtitle_id: str,
        video_hash: str,
        content_id: str
    ) -> bool:
        """Link a subtitle to a specific video hash"""
        return False
    
    def __repr__(self):
        return f"<{self.__class__.__name__} name='{self.name}'>"


class ProviderError(Exception):
    """Base exception for provider errors"""
    def __init__(self, message: str, provider_name: str = None, status_code: int = None):
        super().__init__(message)
        self.provider_name = provider_name
        self.status_code = status_code


class ProviderAuthError(ProviderError):
    """Exception for authentication errors"""
    pass


class ProviderSearchError(ProviderError):
    """Exception for search errors"""
    pass


class ProviderDownloadError(ProviderError):
    """Exception for download errors"""
    pass
