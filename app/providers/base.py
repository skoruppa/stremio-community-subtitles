"""
Base abstract class for subtitle providers.
All subtitle providers (OpenSubtitles, SubDL, etc.) must inherit from this class.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass


@dataclass
class SubtitleResult:
    """Standardized subtitle result from any provider"""
    provider_name: str
    subtitle_id: str  # Provider's internal ID
    language: str
    release_name: Optional[str] = None
    uploader: Optional[str] = None
    download_count: Optional[int] = None
    rating: Optional[float] = None
    hearing_impaired: bool = False
    ai_translated: bool = False
    fps: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None  # Provider-specific metadata


class BaseSubtitleProvider(ABC):
    """
    Abstract base class for subtitle providers.
    
    Each provider must implement all abstract methods to integrate with the system.
    """
    
    # Provider metadata (must be set by subclass)
    name: str = None  # Internal name (e.g., 'opensubtitles', 'subdl')
    display_name: str = None  # Display name (e.g., 'OpenSubtitles', 'SubDL')
    badge_color: str = 'primary'  # Bootstrap color for badge (primary, success, warning, info, etc.)
    requires_auth: bool = True  # Does this provider require authentication?
    supports_search: bool = True  # Can search by IMDb ID, query, etc.
    supports_hash_matching: bool = True  # Can match by video file hash
    can_return_ass: bool = False  # Can return ASS/SSA format (e.g., from ZIP)
    has_additional_settings: bool = False  # Does provider have additional user settings?
    
    def __init__(self):
        """Initialize the provider. Validate that required metadata is set."""
        if not self.name or not self.display_name:
            raise ValueError(f"Provider must define 'name' and 'display_name'")
    
    # Authentication methods
    
    @abstractmethod
    def authenticate(self, user, credentials: Dict[str, str]) -> Dict[str, Any]:
        """
        Authenticate user with the provider.
        
        Args:
            user: User model instance
            credentials: Dict with provider-specific credentials
                        (e.g., {'username': '...', 'password': '...'} or {'api_key': '...'})
        
        Returns:
            Dict with authentication data to store in user.provider_credentials[provider_name]
            Example: {'token': '...', 'base_url': '...', 'expires_at': ...}
        
        Raises:
            ProviderAuthError: If authentication fails
        """
        pass
    
    @abstractmethod
    def logout(self, user) -> bool:
        """
        Logout user from the provider (if applicable).
        
        Args:
            user: User model instance
        
        Returns:
            True if successful
        """
        pass
    
    @abstractmethod
    def is_authenticated(self, user) -> bool:
        """
        Check if user is authenticated with this provider.
        
        Args:
            user: User model instance
        
        Returns:
            True if user has valid credentials
        """
        pass
    
    def get_credentials(self, user) -> Optional[Dict[str, Any]]:
        """
        Helper method to get user's credentials for this provider.
        
        Args:
            user: User model instance
        
        Returns:
            Dict with credentials or None if not authenticated
        """
        if not hasattr(user, 'provider_credentials') or not user.provider_credentials:
            return None
        return user.provider_credentials.get(self.name)
    
    def save_credentials(self, user, credentials: Dict[str, Any]):
        """
        Helper method to save credentials to user model.
        
        Args:
            user: User model instance
            credentials: Dict with credentials to save
        """
        if not hasattr(user, 'provider_credentials'):
            user.provider_credentials = {}
        if user.provider_credentials is None:
            user.provider_credentials = {}
        user.provider_credentials[self.name] = credentials
    
    # Search methods
    
    @abstractmethod
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
        """
        Search for subtitles.
        
        Args:
            user: User model instance
            imdb_id: IMDb ID (e.g., 'tt1234567')
            query: Text search query
            languages: List of language codes (e.g., ['eng', 'pol'])
            video_hash: Video file hash for matching
            season: Season number (for TV shows)
            episode: Episode number (for TV shows)
            content_type: 'movie' or 'series'
            **kwargs: Provider-specific parameters
        
        Returns:
            List of SubtitleResult objects
        
        Raises:
            ProviderError: If search fails
        """
        pass
    
    @abstractmethod
    def get_download_url(self, user, subtitle_id: str) -> Optional[str]:
        """
        Get direct download URL for a subtitle.
        
        Args:
            user: User model instance
            subtitle_id: Provider's subtitle ID
        
        Returns:
            Direct download URL (string) or None if provider requires download_subtitle() method
        
        Raises:
            ProviderError: If download URL cannot be obtained
        """
        pass
    
    def download_subtitle(self, user, subtitle_id: str) -> bytes:
        """
        Download subtitle content directly (for providers that don't provide URLs).
        
        This is optional - only implement if get_download_url() returns None.
        
        Args:
            user: User model instance
            subtitle_id: Provider's subtitle ID
        
        Returns:
            Subtitle file content as bytes
        
        Raises:
            ProviderDownloadError: If download fails
        """
        raise NotImplementedError(f"{self.name} does not implement download_subtitle()")
    
    # UI/Forms methods
    
    @abstractmethod
    def get_settings_template(self) -> str:
        """
        Get template path for provider settings card.
        
        Returns:
            Template path (e.g., 'providers/opensubtitles_settings.html')
        """
        pass
    
    # Optional: Provider-specific features
    
    def link_subtitle_to_hash(
        self,
        user,
        subtitle_id: str,
        video_hash: str,
        content_id: str
    ) -> bool:
        """
        Link a subtitle to a specific video hash (community linking feature).
        
        This is optional - not all providers may support this.
        
        Args:
            user: User model instance
            subtitle_id: Provider's subtitle ID
            video_hash: Video file hash
            content_id: Content ID (IMDb or Kitsu)
        
        Returns:
            True if successful, False if not supported
        """
        return False  # Default: not supported
    
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
