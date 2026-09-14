"""Opt-in live check: python tests/smoke_thesubtitledb.py (one download)."""
import asyncio
from types import SimpleNamespace

import aiohttp

from test_thesubtitledb import module


async def main():
    provider = module.TheSubtitleDBProvider()
    user = SimpleNamespace(provider_credentials={'thesubtitledb': {'active': True}})
    for name, args in [
        ('movie', {'imdb_id': 'tt6751668'}),
        ('episode', {'imdb_id': 'tt0903747', 'season': 1, 'episode': 1}),
        ('title', {'query': 'Parasite', 'content_type': 'movie'}),
    ]:
        rows = await provider.search(user, languages=['eng'], **args)
        assert rows, f'No {name} results'
        assert all(row.language == 'eng' for row in rows)
        print(f'{name}: {len(rows)} English SRT results')
    url = await provider.get_download_url(user, rows[0].subtitle_id)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            content = await response.read()
            assert b'-->' in content, 'Expected subtitle timestamps'
            print(f'download: HTTP {response.status}, {len(content)} bytes, subtitle timestamps verified')


if __name__ == '__main__':
    asyncio.run(main())
