"""
MIT License

Copyright (c) 2021-present MrArkon

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

import aiohttp

from .errors import BadRequest, HTTPException, NotFound
from .models import Anime, Manga

__all__ = ("Client",)
__log__: logging.Logger = logging.getLogger(__name__)

BASE = "https://kitsu.io/api/edge"


class Client:
    """User client used to interact with the Kitsu API"""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        self._session: aiohttp.ClientSession = session or aiohttp.ClientSession()

    def __repr__(self) -> str:
        return "<kitsu.Client>"

    async def _get(self, url: str, **kwargs: Any) -> Any:
        """Performs a GET request to the Kitsu API"""

        headers = kwargs.pop("headers", {})

        headers["Accept"] = "application/vnd.api+json"
        headers["Content-Type"] = "application/vnd.api+json"
        headers["User-Agent"] = "Kitsu.py (https://github.com/MrArkon/kitsu.py)"
        kwargs["headers"] = headers

        __log__.debug("Request Headers: %s", headers)
        __log__.debug("Request URL: %s", url)

        async with self._session.get(url=url, **kwargs) as response:
            data = await response.json()

            if response.status == 200:
                return data

            if response.status == 400:
                raise BadRequest(response, data["errors"][0]["detail"])
            if response.status == 404:
                raise NotFound(response, data["errors"][0]["detail"])

            raise HTTPException(response, await response.text(), response.status)

    async def _insert_filters(self, filters: dict, params: dict) -> None:
        # Credit to @Dymattic for this piece of code.
        for filter_name, filter_value in filters.items():
            param_name = f"filter[{filter_name}]"
            params[param_name] = filter_value

    async def get_anime(self, anime_id: int) -> Anime:
        """
        Fetch the information of an anime using its ID

        Parameters
        ----------
        anime_id: int
            The ID of the Anime on kitsu.io

        Returns
        -------
        :class:`Anime`
        """
        data = await self._get(url=f"{BASE}/anime/{anime_id}")
        return Anime(data["data"], self._session)

    async def search_anime(self, query: str = "", limit: int = 1, **filters) -> List[Anime]:
        """
        Search for an Anime with its name or filters

        Parameters
        ----------
        query: str, default: ""
            The query you want to search with
        limit: int, default: 1
            Limits the number of animes returned
        **filters: dict, optional
            The possible filters are: season, season_year, streamers & age_rating

        Returns
        -------
        List[:class:`Anime`]
        """
        params = {"page[limit]": str(limit)}

        if query != "":
            params["filter[text]"] = query

        await self._insert_filters(filters, params)

        data = await self._get(url=f"{BASE}/anime", params=params)
        return [Anime(payload, self._session) for payload in data["data"]]

    async def trending_anime(self) -> List[Anime]:
        """
        Fetch trending animes

        Returns
        -------
        List[:class:`Anime`]
        """
        data = await self._get(f"{BASE}/trending/anime")
        return [Anime(payload, self._session) for payload in data["data"]]

    async def get_manga(self, manga_id: int) -> Manga:
        """
        Fetch the information of a manga using its ID

        Parameters
        ----------
        manga_id: int
            The ID of the manga on kitsu.io

        Returns
        -------
        :class:`Anime`
        """
        data = await self._get(url=f"{BASE}/manga/{manga_id}")
        return Manga(data["data"], self._session)

    async def search_manga(self, query: str = "", limit: int = 1, **filters) -> List[Manga]:
        """
        Search for a Manga with its Name or Filters

        Parameters
        ----------
        query: str, default: ""
            The query you want to search with
        limit: int, default: 1
            Limits the number of mangas returned
        **filters: dict, optional
            The possible filters are: season, season_year, streamers & age_rating

        Returns
        -------
        List[:class:`Manga`]
        """
        params = {"page[limit]": str(limit)}

        if query != "":
            params["filter[text]"] = query

        await self._insert_filters(filters, params)

        data = await self._get(url=f"{BASE}/manga", params=params)

        return [Manga(payload, self._session) for payload in data["data"]]

    async def trending_manga(self) -> List[Manga]:
        """
        Fetch trending Mangas

        Returns
        -------
        List[:class:`Manga`]
        """
        data = await self._get(f"{BASE}/trending/manga")
        return [Manga(payload, self._session) for payload in data["data"]]

    async def close(self) -> None:
        """Closes the internal HTTP session"""
        return await self._session.close()
