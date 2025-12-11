"""Asynchronous provider search utilities"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app
import gc


def search_providers_parallel(user, active_providers, search_params, timeout=5):
    """
    Search multiple providers in parallel using threads.
    
    Args:
        user: User object
        active_providers: List of provider instances
        search_params: Dict with search parameters (imdb_id, video_hash, languages, etc.)
        timeout: Timeout in seconds for each provider
    
    Returns:
        Dict mapping provider_name -> list of results
    """
    from ..models import User
    from .. import db
    import time
    
    results_by_provider = {}
    
    if not active_providers:
        return results_by_provider
    
    app = current_app._get_current_object()
    user_id = user.id
    start_time = time.time()
    
    def search_single_provider(provider):
        with app.app_context():
            try:
                thread_user = db.session.get(User, user_id)
                results = provider.search(user=thread_user, **search_params)
                return (provider.name, results)
            except Exception as e:
                app.logger.warning(f"Provider {provider.name} search failed: {e}")
                return (provider.name, [])
            finally:
                db.session.remove()
    
    with ThreadPoolExecutor(max_workers=min(len(active_providers), 3)) as executor:
        future_to_provider = {
            executor.submit(search_single_provider, provider): provider 
            for provider in active_providers
        }
        
        for future in as_completed(future_to_provider, timeout=timeout):
            if time.time() - start_time > timeout:
                break
            try:
                provider_name, results = future.result(timeout=0.5)
                results_by_provider[provider_name] = results
            except Exception as e:
                provider = future_to_provider[future]
                app.logger.warning(f"Provider {provider.name} timeout or error: {e}")
                results_by_provider[provider.name] = []
        
        # Cancel remaining futures
        for future in future_to_provider:
            future.cancel()
    
    gc.collect()
    return results_by_provider


def search_providers_with_fallback(user, active_providers, search_params, timeout=5):
    """
    Search providers in parallel and return first successful result.
    Used for hash matching and best match scenarios.
    
    Returns:
        First successful result or None
    """
    from ..models import User
    from .. import db
    import time
    
    if not active_providers:
        return None
    
    app = current_app._get_current_object()
    user_id = user.id
    start_time = time.time()
    
    def search_single_provider(provider):
        with app.app_context():
            try:
                thread_user = db.session.get(User, user_id)
                results = provider.search(user=thread_user, **search_params)
                return results if results else None
            except Exception as e:
                app.logger.warning(f"Provider {provider.name} search failed: {e}")
                return None
            finally:
                db.session.remove()
    
    with ThreadPoolExecutor(max_workers=min(len(active_providers), 3)) as executor:
        future_to_provider = {
            executor.submit(search_single_provider, provider): provider 
            for provider in active_providers
        }
        
        for future in as_completed(future_to_provider, timeout=timeout):
            if time.time() - start_time > timeout:
                break
            try:
                results = future.result(timeout=0.5)
                if results:
                    # Cancel remaining futures
                    for f in future_to_provider:
                        f.cancel()
                    gc.collect()
                    return results
            except Exception as e:
                provider = future_to_provider[future]
                app.logger.warning(f"Provider {provider.name} error: {e}")
        
        # Cancel remaining futures
        for f in future_to_provider:
            f.cancel()
    
    gc.collect()
    return None
