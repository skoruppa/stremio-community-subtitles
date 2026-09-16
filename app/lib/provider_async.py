"""Asynchronous provider search using asyncio with result caching"""
import asyncio
import hashlib
import logging
import time
from dataclasses import asdict

try:
    import orjson
    def _json_dumps(obj):
        return orjson.dumps(obj, default=str).decode()
except ImportError:
    import json
    def _json_dumps(obj):
        return json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str)

logger = logging.getLogger(__name__)


def _make_provider_cache_key(provider_name: str, search_params: dict) -> str:
    """Build a deterministic cache key for provider search results.
    
    The key is based on provider name + search params that affect results
    (imdb_id, season, episode, languages, video_hash, content_type, query).
    User-specific data (tokens) is excluded — search results are the same
    for all users searching the same content.
    """
    key_parts = {
        'p': provider_name,
        'i': search_params.get('imdb_id') or '',
        'q': search_params.get('query') or '',
        's': search_params.get('season'),
        'e': search_params.get('episode'),
        'l': sorted(search_params.get('languages') or []),
        'h': search_params.get('video_hash') or '',
        't': search_params.get('content_type') or '',
    }
    raw = _json_dumps(key_parts)
    digest = hashlib.md5(raw.encode()).hexdigest()
    return f"prov:{provider_name}:{digest}"


def _serialize_results(results):
    """Serialize SubtitleResult list to JSON-safe dicts for Redis."""
    serialized = []
    for r in results:
        try:
            serialized.append(asdict(r))
        except Exception:
            serialized.append({
                'provider_name': r.provider_name,
                'subtitle_id': r.subtitle_id,
                'language': r.language,
                'release_name': r.release_name,
                'uploader': r.uploader,
                'download_count': r.download_count,
                'rating': r.rating,
                'hearing_impaired': r.hearing_impaired,
                'ai_translated': r.ai_translated,
                'fps': r.fps,
                'forced': r.forced,
                'metadata': r.metadata,
            })
    return serialized


def _deserialize_results(data):
    """Deserialize cached dicts back to SubtitleResult objects."""
    from ..providers.base import SubtitleResult
    results = []
    for d in data:
        results.append(SubtitleResult(**d))
    return results


async def search_providers_parallel(user, active_providers, search_params, timeout=10.0):
    """
    Search multiple providers in parallel using asyncio.
    Results are cached per-provider for 5 minutes in Redis to avoid
    redundant API calls for the same content across different users.
    
    Returns:
        Dict mapping provider_name -> list of SubtitleResult
    """
    if not active_providers:
        return {}

    from ..extensions import cache

    async def search_single_provider(provider):
        provider_start = time.time()

        # Check cache first
        cache_key = _make_provider_cache_key(provider.name, search_params)
        cached = await cache.get(cache_key)
        if cached is not None:
            elapsed = time.time() - provider_start
            logger.info(f"Provider {provider.name} cache hit ({elapsed:.3f}s)")
            return (provider.name, _deserialize_results(cached))

        # Cache miss — do the actual API call
        try:
            async with asyncio.timeout(timeout):
                results = await provider.search(user=user, **search_params)
                elapsed = time.time() - provider_start
                logger.info(f"Provider {provider.name} search completed in {elapsed:.2f}s")

                # Cache results for 5 minutes (300s)
                if results is not None:
                    await cache.set(cache_key, _serialize_results(results), timeout=300)

                return (provider.name, results)
        except asyncio.TimeoutError:
            elapsed = time.time() - provider_start
            logger.debug(f"Provider {provider.name} timeout after {elapsed:.2f}s")
            return (provider.name, [])
        except Exception as e:
            elapsed = time.time() - provider_start
            logger.debug(f"Provider {provider.name} failed after {elapsed:.2f}s: {e}")
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
            logger.debug(f"Provider {provider.name} timeout")
            return None
        except Exception as e:
            logger.debug(f"Provider {provider.name} failed: {e}")
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
