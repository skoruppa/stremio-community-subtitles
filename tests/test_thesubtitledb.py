"""Provider contract tests, runnable without starting Quart or a database.

Run: python -m unittest discover -s tests
"""
import asyncio
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web


# Load the real provider under an isolated package, avoiding app factory imports.
ROOT = Path(__file__).resolve().parents[1]
package = ModuleType('_scs_provider_tests')
package.__path__ = [str(ROOT / 'app')]
sys.modules[package.__name__] = package
module = importlib.import_module('_scs_provider_tests.providers.thesubtitledb.provider')
base = importlib.import_module('_scs_provider_tests.providers.base')


def bundle(items=None, total=None):
    # Shape verified against /v1/by-imdb/tt6751668?lang=en&limit=1.
    if items is None:
        items = [{'id': 8819453, 'language': 'en', 'format': 'srt',
                  'release_name': '[DWA][English] Parasite (Uncut) - VIU',
                  'hearing_impaired': False, 'fps': 23.976}]
    return {'title': {'imdb': 'tt6751668'}, 'subtitles': {
        'items': items, 'total': len(items) if total is None else total}}


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = module.TheSubtitleDBProvider()
        self.user = SimpleNamespace(provider_credentials={'thesubtitledb': {'active': True}})

    async def test_activation_and_logout(self):
        user = SimpleNamespace(provider_credentials=None)
        self.assertFalse(await self.provider.is_authenticated(user))
        await self.provider.save_credentials(user, await self.provider.authenticate(user, {}))
        self.assertTrue(await self.provider.is_authenticated(user))
        await self.provider.logout(user)
        self.assertFalse(await self.provider.is_authenticated(user))
        with self.assertRaises(base.ProviderAuthError):
            await self.provider.search(user, imdb_id='tt6751668')

    async def test_movie_mapping(self):
        with patch.object(self.provider, '_lookup', AsyncMock(return_value=bundle())) as lookup:
            rows = await self.provider.search(self.user, imdb_id='tt6751668', languages=['eng'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].subtitle_id, '8819453')
        self.assertEqual(rows[0].language, 'eng')
        self.assertEqual(rows[0].fps, 23.976)
        self.assertEqual(lookup.call_args.args[1], '/by-imdb/tt6751668')
        self.assertEqual(lookup.call_args.args[2]['lang'], 'en')
        self.assertEqual(lookup.call_args.args[2]['format'], 'srt')

    async def test_episode_and_specials(self):
        with patch.object(self.provider, '_lookup', AsyncMock(return_value=bundle())) as lookup:
            await self.provider.search(self.user, imdb_id='tt0903747', season=0, episode=1)
        self.assertEqual(lookup.call_args.args[1], '/by-imdb/tt0903747/season/0/episode/1')

    async def test_title_resolves_before_episode_lookup(self):
        with patch.object(self.provider, '_lookup', AsyncMock(return_value=bundle())) as lookup:
            await self.provider.search(self.user, query='Parasite', content_type='series', season=1, episode=2)
        self.assertEqual(lookup.call_args_list[0].args[1], '/by-title')
        self.assertEqual(lookup.call_args_list[0].args[2]['type'], 'tv')
        self.assertEqual(lookup.call_args_list[1].args[1], '/by-imdb/tt6751668/season/1/episode/2')

    async def test_language_conversion_and_filtering(self):
        for source, target in [('eng', 'en'), ('fre', 'fr'), ('ger', 'de'), ('pob', 'pb'), ('por', 'pt')]:
            self.assertEqual(module.language_code(source), target)
        mixed = bundle([{'id': 1, 'language': 'pb', 'format': 'srt'},
                        {'id': 2, 'language': 'pt', 'format': 'srt'},
                        {'id': 3, 'language': 'pb', 'format': 'ass'}])
        with patch.object(self.provider, '_lookup', AsyncMock(return_value=mixed)) as lookup:
            rows = await self.provider.search(self.user, imdb_id='tt6751668', languages=['pob'])
        self.assertEqual([r.language for r in rows], ['pob'])
        self.assertEqual(lookup.call_args.args[2]['lang'], 'pb')

    async def test_pagination_is_bounded_and_deduplicated(self):
        with patch.object(self.provider, '_lookup', AsyncMock(return_value=bundle(total=1000))) as lookup:
            rows = await self.provider.search(self.user, imdb_id='tt6751668')
        self.assertEqual(len(rows), 1)
        self.assertEqual([c.args[2]['offset'] for c in lookup.call_args_list], [0, 100, 200])

    async def test_invalid_requests_do_not_call_api(self):
        with patch.object(self.provider, '_lookup', AsyncMock()) as lookup:
            for kwargs in [{}, {'imdb_id': '../../other'},
                           {'imdb_id': 'tt1', 'episode': 1},
                           {'imdb_id': 'tt1', 'season': -1},
                           {'imdb_id': 'tt1', 'languages': ['invalid']}]:
                self.assertEqual(await self.provider.search(self.user, **kwargs), [])
        lookup.assert_not_called()

    async def test_missing_title(self):
        with patch.object(self.provider, '_lookup', AsyncMock(return_value=None)):
            self.assertEqual(await self.provider.search(self.user, imdb_id='tt1'), [])
            self.assertEqual(await self.provider.search(self.user, query='missing'), [])

    async def test_timeout_is_provider_error(self):
        with patch.object(self.provider, '_lookup', AsyncMock(side_effect=asyncio.TimeoutError)):
            with self.assertRaises(base.ProviderSearchError):
                await self.provider.search(self.user, imdb_id='tt1')

    async def test_download_url_rejects_arbitrary_urls(self):
        self.assertEqual(await self.provider.get_download_url(self.user, '8819453'),
                         'https://api.thesubtitledb.org/get/8819453')
        for value in ['https://example.com', '../123', '1?x=2', '0']:
            with self.assertRaises(base.ProviderDownloadError):
                await self.provider.get_download_url(self.user, value)

    async def test_real_http_transport(self):
        async def handler(request):
            self.assertEqual(request.headers['User-Agent'], module.USER_AGENT)
            if request.match_info['id'] == 'tt404':
                return web.Response(status=404)
            if request.match_info['id'] == 'tt429':
                return web.Response(status=429)
            return web.json_response(bundle())

        app = web.Application()
        app.router.add_get('/v1/by-imdb/{id}', handler)
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            port = runner.addresses[0][1]
            with patch.object(module, 'API_BASE', f'http://127.0.0.1:{port}'):
                self.assertEqual(len(await self.provider.search(self.user, imdb_id='tt1')), 1)
                self.assertEqual(await self.provider.search(self.user, imdb_id='tt404'), [])
                with self.assertRaises(base.ProviderSearchError) as error:
                    await self.provider.search(self.user, imdb_id='tt429')
                self.assertEqual(error.exception.status_code, 429)
        finally:
            await runner.cleanup()


if __name__ == '__main__':
    unittest.main()
