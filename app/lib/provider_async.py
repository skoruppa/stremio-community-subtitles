"""Asynchronous provider search using asyncio"""
import asyncio
import logging
import time

logger = logging.getLogger(__name__)


async def search_providers_parallel(user, active_providers, search_params, timeout=10.0):
    """
    Search multiple providers in parallel using asyncio.
    
    Returns:
        Dict mapping provider_name -> list of results
    """
    if not active_providers:
        return {}
    
    async def search_single_provider(provider):
        provider_start = time.time()
        try:
            async with asyncio.timeout(timeout):
                results = await provider.search(user=user, **search_params)
                elapsed = time.time() - provider_start
                logger.info(f"Provider {provider.name} search completed in {elapsed:.2f}s")
                return (provider.name, results)
        except asyncio.TimeoutError:
            elapsed = time.time() - provider_start
            logger.warning(f"Provider {provider.name} timeout after {elapsed:.2f}s")
            return (provider.name, [])
        except Exception as e:
            elapsed = time.time() - provider_start
            logger.warning(f"Provider {provider.name} failed after {elapsed:.2f}s: {e}", exc_info=True)
            return (provider.name, [])
    
    tasks = [search_single_provider(p) for p in active_providers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    results_by_provider = {}
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Provider exception: {result}")
            continue
        if isinstance(result, tuple) and len(result) == 2:
            provider_name, provider_results = result
            results_by_provider[provider_name] = provider_results
    
    return results_by_provider


async def search_providers_with_fallback(user, active_providers, search_params, timeout=10.0):
    """
    Search providers and return first successful result.
    
    Returns:
        First successful result or None
    """
    if not active_providers:
        return None
    
    async def search_single_provider(provider):
        try:
            async with asyncio.timeout(timeout):
                results = await provider.search(user=user, **search_params)
                return results if results else None
        except asyncio.TimeoutError:
            logger.warning(f"Provider {provider.name} timeout")
            return None
        except Exception as e:
            logger.warning(f"Provider {provider.name} failed: {e}")
            return None
    
    tasks = [search_single_provider(p) for p in active_providers]
    
    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
            if result:
                return result
        except Exception as e:
            logger.error(f"Provider exception: {e}")
            continue
    
    return None
