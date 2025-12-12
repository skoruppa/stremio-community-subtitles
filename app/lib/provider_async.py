"""Asynchronous provider search utilities"""
from flask import current_app
import gc

try:
    from gevent import spawn, joinall, Timeout
    from gevent.event import AsyncResult
    GEVENT_AVAILABLE = True
except ImportError:
    GEVENT_AVAILABLE = False
    from concurrent.futures import ThreadPoolExecutor, as_completed


def search_providers_parallel(user, active_providers, search_params, timeout=10):
    use_gevent = GEVENT_AVAILABLE and current_app.config.get('USE_GEVENT', True)
    if use_gevent:
        return _search_providers_parallel_gevent(user, active_providers, search_params, timeout)
    else:
        return _search_providers_parallel_threads(user, active_providers, search_params, timeout)


def _search_providers_parallel_gevent(user, active_providers, search_params, timeout=10):
    """
    Search multiple providers in parallel using gevent greenlets.
    
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
    
    results_by_provider = {}
    
    if not active_providers:
        return results_by_provider
    
    app = current_app._get_current_object()
    user_id = user.id
    
    def search_single_provider(provider, result_container):
        with app.app_context():
            try:
                with Timeout(timeout):
                    thread_user = db.session.get(User, user_id)
                    results = provider.search(user=thread_user, **search_params)
                    result_container.set((provider.name, results))
            except Timeout:
                app.logger.warning(f"Provider {provider.name} timeout")
                result_container.set((provider.name, []))
            except Exception as e:
                app.logger.warning(f"Provider {provider.name} search failed: {e}")
                result_container.set((provider.name, []))
            finally:
                db.session.remove()
    
    # Spawn greenlets for each provider
    greenlets = []
    result_containers = []
    
    for provider in active_providers:
        result_container = AsyncResult()
        result_containers.append(result_container)
        greenlet = spawn(search_single_provider, provider, result_container)
        greenlets.append(greenlet)
    
    # Wait for all with timeout
    joinall(greenlets, timeout=timeout)
    
    # Collect results
    for result_container in result_containers:
        if result_container.ready():
            provider_name, results = result_container.get()
            results_by_provider[provider_name] = results
    
    gc.collect()
    return results_by_provider


def _search_providers_parallel_threads(user, active_providers, search_params, timeout=5):
    """Fallback to threads for development/debug mode"""
    from ..models import User
    from .. import db
    
    results_by_provider = {}
    
    if not active_providers:
        return results_by_provider
    
    app = current_app._get_current_object()
    user_id = user.id
    
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
        future_to_provider = {executor.submit(search_single_provider, p): p for p in active_providers}
        
        for future in as_completed(future_to_provider, timeout=timeout):
            try:
                provider_name, results = future.result(timeout=1)
                results_by_provider[provider_name] = results
            except Exception as e:
                provider = future_to_provider[future]
                app.logger.warning(f"Provider {provider.name} timeout: {e}")
                results_by_provider[provider.name] = []
    
    gc.collect()
    return results_by_provider


def search_providers_with_fallback(user, active_providers, search_params, timeout=10):
    use_gevent = GEVENT_AVAILABLE and current_app.config.get('USE_GEVENT', True)
    if use_gevent:
        return _search_providers_with_fallback_gevent(user, active_providers, search_params, timeout)
    else:
        return _search_providers_with_fallback_threads(user, active_providers, search_params, timeout)


def _search_providers_with_fallback_gevent(user, active_providers, search_params, timeout=10):
    """
    Search providers in parallel and return first successful result.
    Used for hash matching and best match scenarios.
    
    Returns:
        First successful result or None
    """
    from ..models import User
    from .. import db
    
    if not active_providers:
        return None
    
    app = current_app._get_current_object()
    user_id = user.id
    first_result = AsyncResult()
    
    def search_single_provider(provider):
        with app.app_context():
            try:
                with Timeout(timeout):
                    thread_user = db.session.get(User, user_id)
                    results = provider.search(user=thread_user, **search_params)
                    if results and not first_result.ready():
                        first_result.set(results)
            except Timeout:
                app.logger.warning(f"Provider {provider.name} timeout")
            except Exception as e:
                app.logger.warning(f"Provider {provider.name} search failed: {e}")
            finally:
                db.session.remove()
    
    # Spawn greenlets for each provider
    greenlets = [spawn(search_single_provider, provider) for provider in active_providers]
    
    # Wait for first result or timeout
    try:
        result = first_result.get(timeout=timeout)
        gc.collect()
        return result
    except Timeout:
        pass
    
    # Wait for remaining greenlets to finish
    joinall(greenlets, timeout=0.1)
    
    gc.collect()
    return None


def _search_providers_with_fallback_threads(user, active_providers, search_params, timeout=10):
    """Thread-based fallback implementation"""
    from ..models import User
    from .. import db
    
    if not active_providers:
        return None
    
    app = current_app._get_current_object()
    user_id = user.id
    
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
        future_to_provider = {executor.submit(search_single_provider, p): p for p in active_providers}
        
        for future in as_completed(future_to_provider, timeout=timeout):
            try:
                results = future.result(timeout=1)
                if results:
                    gc.collect()
                    return results
            except Exception as e:
                provider = future_to_provider[future]
                app.logger.warning(f"Provider {provider.name} error: {e}")
    
    gc.collect()
    return None
