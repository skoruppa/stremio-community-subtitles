"""
Provider Registry - Central registry for all subtitle providers.
"""
from typing import Dict, List, Optional
from .base import BaseSubtitleProvider


class ProviderRegistry:
    """
    Singleton registry for managing subtitle providers.
    
    Usage:
        # Register a provider
        ProviderRegistry.register(OpenSubtitlesProvider)
        
        # Get a provider
        provider = ProviderRegistry.get('opensubtitles')
        
        # Get all providers
        all_providers = ProviderRegistry.get_all()
        
        # Get active providers for user
        active = ProviderRegistry.get_active_for_user(user)
    """
    
    _providers: Dict[str, BaseSubtitleProvider] = {}
    _initialized = False
    
    @classmethod
    def register(cls, provider_class: type) -> BaseSubtitleProvider:
        """
        Register a provider class.
        
        Args:
            provider_class: Class inheriting from BaseSubtitleProvider
        
        Returns:
            Instantiated provider
        
        Raises:
            ValueError: If provider with same name already registered
        """
        if not issubclass(provider_class, BaseSubtitleProvider):
            raise TypeError(f"{provider_class} must inherit from BaseSubtitleProvider")
        
        provider = provider_class()
        
        if provider.name in cls._providers:
            raise ValueError(f"Provider '{provider.name}' is already registered")
        
        cls._providers[provider.name] = provider
        return provider
    
    @classmethod
    def get(cls, name: str) -> Optional[BaseSubtitleProvider]:
        """
        Get a provider by name.
        
        Args:
            name: Provider name (e.g., 'opensubtitles')
        
        Returns:
            Provider instance or None if not found
        """
        return cls._providers.get(name)
    
    @classmethod
    def get_all(cls, user=None, filter_by_language: bool = True) -> List[BaseSubtitleProvider]:
        """
        Get all registered providers.
        
        Args:
            user: User model instance (optional, for language filtering)
            filter_by_language: If True and user provided, filter by user's preferred languages
        
        Returns:
            List of all provider instances
        """
        providers = list(cls._providers.values())
        
        if user and filter_by_language and hasattr(user, 'preferred_languages') and user.preferred_languages:
            filtered = []
            for provider in providers:
                # If provider supports all languages or user has at least one matching language
                if provider.supported_languages is None:
                    filtered.append(provider)
                elif any(lang in provider.supported_languages for lang in user.preferred_languages):
                    filtered.append(provider)
            return filtered
        
        return providers
    
    @classmethod
    async def get_active_for_user(cls, user) -> List[BaseSubtitleProvider]:
        """
        Get all providers that are authenticated/active for a user.
        
        Args:
            user: User model instance
        
        Returns:
            List of active provider instances
        """
        import asyncio
        active_providers = []
        for provider in cls._providers.values():
            if await provider.is_authenticated(user):
                active_providers.append(provider)
        return active_providers
    
    @classmethod
    def get_by_auth_requirement(cls, requires_auth: bool) -> List[BaseSubtitleProvider]:
        """
        Get providers filtered by authentication requirement.
        
        Args:
            requires_auth: True for providers requiring auth, False for public
        
        Returns:
            List of matching provider instances
        """
        return [
            provider for provider in cls._providers.values()
            if provider.requires_auth == requires_auth
        ]
    
    @classmethod
    def clear(cls):
        """Clear all registered providers (mainly for testing)."""
        cls._providers.clear()
        cls._initialized = False
    
    @classmethod
    def initialize_providers(cls):
        """
        Initialize all providers. Should be called once during app startup.
        
        This method imports and registers all available providers.
        """
        if cls._initialized:
            return
        
        # Import and register providers
        try:
            from .opensubtitles.provider import OpenSubtitlesProvider
            cls.register(OpenSubtitlesProvider)
        except ImportError as e:
            # Log but don't fail - provider might not be implemented yet
            import logging
            logging.warning(f"Could not load OpenSubtitlesProvider: {e}")
        
        try:
            from .subdl import SubDLProvider
            cls.register(SubDLProvider)
        except ImportError as e:
            import logging
            logging.warning(f"Could not load SubDLProvider: {e}")
        except Exception as e:
            import logging
            logging.error(f"Error loading SubDLProvider: {e}", exc_info=True)
        
        try:
            from .subsource import SubSourceProvider
            cls.register(SubSourceProvider)
        except ImportError as e:
            import logging
            logging.warning(f"Could not load SubSourceProvider: {e}")
        except Exception as e:
            import logging
            logging.error(f"Error loading SubSourceProvider: {e}", exc_info=True)
        
        try:
            from .napisy24.provider import Napisy24Provider
            cls.register(Napisy24Provider)
        except ImportError as e:
            import logging
            logging.warning(f"Could not load Napisy24Provider: {e}")
        except Exception as e:
            import logging
            logging.error(f"Error loading Napisy24Provider: {e}", exc_info=True)
        
        # Add more providers here as they are implemented
        
        cls._initialized = True
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if registry has been initialized."""
        return cls._initialized


def init_providers(app=None):
    """
    Initialize provider registry. Call this from app factory.
    
    Args:
        app: Flask app instance (optional, for future use)
    """
    ProviderRegistry.initialize_providers()
    
    if app:
        app.logger.info(f"Initialized {len(ProviderRegistry.get_all())} subtitle providers")
