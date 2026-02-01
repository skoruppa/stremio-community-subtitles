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

from datetime import datetime
from typing import Dict, List, Literal, Optional
from urllib.parse import urlparse

import aiohttp
from dateutil.parser import isoparse

__all__ = ("Anime", "Manga")

HEADERS: dict = {
    "Accept": "application/vnd.api+json",
    "Content-Type": "application/vnd.api+json",
    "User-Agent": "Kitsu.py (https://github.com/MrArkon/kitsu.py)",
}


class Category:
    """
    Represents a category of an Anime/Manga

    Attributes
    ----------
    id: str
        The UUID of the category on kitsu
    title: str
        The title of the category
    description: str
        The description of the category
    total_media_count: str
        The total media count of the category
    nsfw: bool
        If the category is NSFW(Not safe for work/18+)
    """

    __slots__ = ("id", "title", "description", "total_media_count", "nsfw", "_data")

    def __init__(self, data: dict) -> None:
        self._data = data

        self.id: str = self._data["id"]
        self.title: str = self._data["attributes"]["title"]
        self.description: str = self._data["attributes"]["description"]
        self.total_media_count: str = self._data["attributes"]["totalMediaCount"]
        self.nsfw: bool = self._data["attributes"]["nsfw"]

    def __repr__(self) -> str:
        return f"<Category id={self.id} title='{self.title}'>"

    def __str__(self) -> str:
        return self.title

    @property
    def created_at(self) -> Optional[datetime]:
        """
        The time when this category was added on Kitsu

        Returns
        -------
        Optional[datetime]
        """
        try:
            return isoparse(self._data["attributes"]["createdAt"])
        except (KeyError, TypeError):
            return None

    @property
    def updated_at(self) -> Optional[datetime]:
        """
        The last time this category was updated on Kitsu

        Returns
        -------
        Optional[datetime]
        """
        try:
            return isoparse(self._data["attributes"]["updatedAt"])
        except (KeyError, TypeError):
            return None


class StreamingLink:
    """
    Represents the streaming link for an Anime

    Attributes
    ----------
    id: str
        The UUID of the streaming link on kitsu
    subs: list
        The subs available on this streaming link
    dubs: list
        The dubs available on this streaming link
    """

    __slots__ = ("id", "subs", "dubs", "_data")

    def __init__(self, data: dict) -> None:
        self._data = data

        self.id: str = self._data["id"]
        self.subs: List[str] = self._data["attributes"]["subs"]
        self.dubs: List[str] = self._data["attributes"]["dubs"]

    @property
    def title(self) -> Optional[str]:
        """
        The title of the streaming link

        Returns
        -------
        Optional[str]
        """
        try:
            _parsed_url = urlparse(self.url).hostname.split(".")
            if _parsed_url[0] not in ["www", "beta"]:
                return _parsed_url[0].capitalize()
            else:
                return _parsed_url[1].capitalize()
        except:
            return None

    @property
    def url(self) -> str:
        """
        The url to the streaming link

        Returns
        -------
        str
        """
        _url: str = self._data["attributes"]["url"]
        if _url.startswith(("http://", "https://")):
            return _url
        else:
            return "https://" + _url

    @property
    def created_at(self) -> Optional[datetime]:
        """
        The time when this link was added on Kitsu

        Returns
        -------
        Optional[datetime]
        """
        try:
            return isoparse(self._data["attributes"]["createdAt"])
        except (KeyError, TypeError):
            return None

    @property
    def updated_at(self) -> Optional[datetime]:
        """
        The last time this streaming link was updated on Kitsu.

        Returns
        -------
        Optional[datetime]
        """
        try:
            return isoparse(self._data["attributes"]["updatedAt"])
        except (KeyError, TypeError):
            return None


class Episode:
    """
    Represents an episode of an Anime

    Attributes
    ----------
    id: str
        The UUID of the Episode on kitsu
    canonical_title: str
        The canonical title of the episode
    synopsis: str
        The synopsis/description of the episode
    season_number: str
        The season number this episode belongs to
    episode_number: str
        The number of the episode
    air_date: str
        The date on which this episode was aired
    """

    __slots__ = ("id", "type", "canonical_title", "synopsis", "season_number", "episode_number", "air_date", "_data")

    def __init__(self, data: dict) -> None:
        self._data = data

        self.id: str = self._data["id"]
        self.type: str = self._data["type"]
        self.canonical_title: str = self._data["attributes"]["canonicalTitle"]
        self.synopsis: str = self._data["attributes"]["synopsis"]
        self.season_number: str = self._data["attributes"]["seasonNumber"]
        self.episode_number: str = self._data["attributes"]["number"]
        self.air_date: str = self._data["attributes"]["airdate"]

    @property
    def title(self) -> Optional[Title]:
        """
        The titles of the episode in different languages. Other languages will be listed if they exist.

        Returns
        -------
        Optional[:class:`Title`]
        """
        try:
            return Title(self._data["attributes"]["titles"])
        except (KeyError, TypeError):
            return None

    @property
    def created_at(self) -> Optional[datetime]:
        """
        When this episode was added on Kitsu

        Returns
        -------
        Optional[datetime]
        """
        try:
            return isoparse(self._data["attributes"]["createdAt"])
        except (KeyError, TypeError):
            return None

    @property
    def updated_at(self) -> Optional[datetime]:
        """
        The last time this episode was updated on Kitsu

        Returns
        -------
        Optional[datetime]
        """
        try:
            return isoparse(self._data["attributes"]["updatedAt"])
        except (KeyError, TypeError):
            return None

    def thumbnail(
        self, _type: Optional[Literal["tiny", "small", "medium", "large", "original"]] = "original"
    ) -> Optional[str]:
        """
        The url to the thumbnail of this episode

        Returns
        -------
        Optional[str]
        """
        try:
            return self._data["attributes"]["thumbnail"].get(_type, None)
        except AttributeError:
            return None


class Title:
    def __init__(self, data: dict) -> None:
        self._data = data

    def __repr__(self) -> Optional[str]:
        value: Optional[str]
        for value in self._data.values():
            if value:
                return value

    def __str__(self) -> Optional[str]:
        return self.__repr__()

    @property
    def en(self) -> Optional[str]:
        """
        The title in english

        Returns
        -------
        Optional[str]
        """
        return self._data.get("en", None)

    @property
    def en_jp(self) -> Optional[str]:
        """
        The japanese title in english characters

        Returns
        -------
        Optional[str]
        """
        return self._data.get("en_jp", None)

    @property
    def ja_jp(self) -> Optional[str]:
        """
        The title in japanese

        Returns
        -------
        Optional[str]
        """
        return self._data.get("ja_jp", None)


class Media:
    """Baseclass for Anime & Manga"""

    __slots__ = (
        "id",
        "type",
        "slug",
        "synopsis",
        "canonical_title",
        "abbreviated_titles",
        "rating_frequencies",
        "age_rating",
        "age_rating_guide",
        "status",
        "tba",
        "_data",
        "_session",
    )

    def __init__(self, payload: dict, session: aiohttp.ClientSession) -> None:
        self._data: dict = payload
        self._session: aiohttp.ClientSession = session

        self.id: str = self._data["id"]
        self.type: str = self._data["type"]
        self.slug: str = self._data["attributes"]["slug"]
        self.synopsis: str = self._data["attributes"]["synopsis"]
        self.canonical_title: str = self._data["attributes"]["canonicalTitle"]
        self.abbreviated_titles: Optional[List[str]] = self._data["attributes"]["abbreviatedTitles"]
        self.rating_frequencies: Optional[Dict[str, str]] = self._data["attributes"]["ratingFrequencies"]
        self.age_rating: Optional[Literal["G", "PG", "R", "R18"]] = self._data["attributes"]["ageRating"]
        self.age_rating_guide: Optional[str] = self._data["attributes"]["ageRatingGuide"]
        self.status: Optional[Literal["current", "finished", "tba", "unreleased", "upcoming"]] = self._data["attributes"][
            "status"
        ]
        self.tba: Optional[str] = self._data["attributes"].get("tba")

    def __repr__(self) -> str:
        return f"<{self.type.capitalize()} id={self.id} title='{self.title}'>"

    def __str__(self) -> str:
        return str(self.title)

    async def _fetch_categories(self) -> Optional[List[Category]]:
        async with self._session.get(
            url=f"https://kitsu.io/api/edge/{self.type}/{self.id}/categories", headers=HEADERS
        ) as response:
            if response.status == 200:
                _raw_data = await response.json()
            else:
                return None

        return [Category(data) for data in _raw_data["data"]]

    @property
    def title(self) -> Optional[Title]:
        """
        The titles of the Anime/Manga in different languages. Other languages will be listed if they exist.

        Returns
        -------
        Optional[:class:`Title`]
        """
        try:
            return Title(self._data["attributes"]["titles"])
        except (KeyError, TypeError):
            return None

    @property
    async def categories(self) -> Optional[List[Category]]:
        """
        The categories or genres of the Anime/Manga

        Returns
        -------
        Optional[List[:class:`Title`]]
        """
        return await self._fetch_categories()

    @property
    def created_at(self) -> Optional[datetime]:
        """
        When the Anime/Manga was added on Kitsu. (Use start_date instead)

        Returns
        -------
        Optional[datetime]
        """
        try:
            return isoparse(self._data["attributes"]["createdAt"])
        except (KeyError, TypeError):
            return None

    @property
    def updated_at(self) -> Optional[datetime]:
        """
        The last time Anime/Manga was updated on Kitsu.

        Returns
        -------
        Optional[datetime]
        """
        try:
            return isoparse(self._data["attributes"]["updatedAt"])
        except (KeyError, TypeError):
            return None

    @property
    def average_rating(self) -> Optional[float]:
        """
        The average rating of the Anime/Manga on Kitsu

        Returns
        -------
        Optional[float]
        """
        try:
            return float(self._data["attributes"]["averageRating"])
        except (KeyError, TypeError):
            return None

    @property
    def user_count(self) -> Optional[int]:
        """
        The user count of the Anime/Manga on Kitsu

        Returns
        -------
        Optional[int]
        """
        try:
            return int(self._data["attributes"]["userCount"])
        except (KeyError, TypeError):
            return None

    @property
    def favorites_count(self) -> Optional[int]:
        """
        The favorites count of the Anime/Manga on Kitsu

        Returns
        -------
        Optional[int]
        """
        try:
            return int(self._data["attributes"]["favoritesCount"])
        except (KeyError, TypeError):
            return None

    @property
    def start_date(self) -> Optional[datetime]:
        """
        The date on which the Anime/Manga started

        Returns
        -------
        Optional[datetime]
        """
        try:
            return datetime.strptime(self._data["attributes"]["startDate"], "%Y-%m-%d")
        except (KeyError, TypeError):
            return None

    @property
    def end_date(self) -> Optional[datetime]:
        """
        The date on which the Anime/Manga ended.

        Returns
        -------
        Optional[datetime]
        """
        try:
            return datetime.strptime(self._data["attributes"]["endDate"], "%Y-%m-%d")
        except (KeyError, TypeError):
            return None

    @property
    def popularity_rank(self) -> Optional[int]:
        """
        The popularity rank of the Anime/Manga on Kitsu

        Returns
        -------
        Optional[int]
        """
        try:
            return int(self._data["attributes"]["popularityRank"])
        except (KeyError, TypeError):
            return None

    @property
    def rating_rank(self) -> Optional[int]:
        """
        The rating rank of the Anime/Manga on Kitsu

        Returns
        -------
        Optional[int]
        """
        try:
            return int(self._data["attributes"]["ratingRank"])
        except (KeyError, TypeError):
            return None

    def poster_image(
        self, _type: Optional[Literal["tiny", "small", "medium", "large", "original"]] = "original"
    ) -> Optional[str]:
        """
        The poster image of the Anime/Manga

        Parameters
        ----------
        _type: Optional[Literal["tiny", "small", "medium", "large", "original"]], default: "original"
            The size in which the image should be returned. The size will be orginal by default

        Returns
        -------
        Optional[str]
            The URL of the image
        """
        try:
            return self._data["attributes"]["posterImage"].get(_type, None)
        except AttributeError:
            return None

    def cover_image(self, _type: Optional[Literal["tiny", "small", "large", "original"]] = "original") -> Optional[str]:
        """
        The cover image of the Anime/Manga

        Parameters
        ----------
        _type: Optional[Literal["tiny", "small", "medium", "large", "original"]], default: "original"
            The size in which the image should be returned. The size will be orginal by default

        Returns
        -------
        Optional[str]
            The URL of the image
        """
        try:
            return self._data["attributes"]["coverImage"].get(_type, None)
        except AttributeError:
            return None


class Anime(Media):
    """
    The information about an Anime wrapped in a class

    Attributes
    ----------
    id: str
        The UUID of the Anime on Kitsu
    slug: str
        The name of the Anime with hyphens, It's recommended to use title or canoncial_title instead.
        Example: `cowboy-bebop`
    canonical_title: str
        The canonical title of the Anime
    synopsis: str
        The synopsis/description of the Anime
    abbreviated_titles: Optional[List[str]]
        A list of abbreivated titles for the Anime
    rating_frequencies: Optional[Dict[str, str]]
        The rating fequencies of the Anime
    age_rating: Optional[Literal["G", "PG", "R", "R18"]]
        The age rating for the Anime
    age_rating_guide: Optional[str]
        Elaborated age rating for the Anime
    status: Optional[Literal["current", "finished", "tba", "unreleased", "upcoming"]]
        The status of the anime
    tba: Optional[str]
    subtype: Optional[Literal["ONA", "OVA", "TV", "movie", "music", "special"]]
        The subtype of the Anime
    youtube_video_id: Optional[str]
        The youtube video ID associated with the Anime
    nsfw: Optional[bool]
        If the Anime is NSFW(Not safe for work/18+)
    """

    __slots__ = ("subtype", "youtube_video_id", "nsfw")

    def __init__(self, payload: dict, session: aiohttp.ClientSession) -> None:
        super().__init__(payload, session)

        self.subtype: Optional[Literal["ONA", "OVA", "TV", "movie", "music", "special"]] = self._data["attributes"][
            "subtype"
        ]
        self.youtube_video_id: Optional[str] = self._data["attributes"]["youtubeVideoId"]
        self.nsfw: Optional[bool] = self._data["attributes"]["nsfw"]

    async def _fetch_streaming_links(self) -> Optional[List[StreamingLink]]:
        async with self._session.get(
            url=f"https://kitsu.io/api/edge/anime/{self.id}/streaming-links", headers=HEADERS
        ) as response:
            if response.status == 200:
                _raw_data = await response.json()
            else:
                return None

        return [StreamingLink(data) for data in _raw_data["data"]]

    async def _fetch_episodes(self) -> Optional[List[Episode]]:
        async with self._session.get(url=f"https://kitsu.io/api/edge/anime/{self.id}/episodes", headers=HEADERS) as response:
            if response.status == 200:
                _raw_data = await response.json()
            else:
                return None

        return [Episode(data) for data in _raw_data["data"]]

    @property
    async def streaming_links(self) -> Optional[List[StreamingLink]]:
        """
        The streaming links & information for the Anime

        Returns
        -------
        Optional[List[:class:`StreamingLink`]]
        """
        return await self._fetch_streaming_links()

    @property
    async def episodes(self) -> Optional[List[Episode]]:
        """
        The episodes of the Anime

        Returns
        -------
        Optional[List[:class:`Episode`]]
        """
        return await self._fetch_episodes()

    @property
    def episode_count(self) -> Optional[int]:
        """
        The number of episodes of this Anime

        Returns
        -------
        Optional[int]
        """
        try:
            return int(self._data["attributes"]["episodeCount"])
        except (KeyError, TypeError):
            return None

    @property
    def episode_length(self) -> Optional[int]:
        """
        The avg length of episodes of this Anime in minutes

        Returns
        -------
        Optional[int]
        """
        try:
            return int(self._data["attributes"]["episodeLength"])
        except (KeyError, TypeError):
            return None


class Manga(Media):
    """The information about a Manga wrapped in a class

    Attributes
    ----------
    id: str
        The UUID of the Manga on Kitsu
    slug: str
        The name of the Manga with hyphens, It's recommended to use title or canoncial_title instead.
        Example: `shingeki-no-kyojin`
    canonical_title: str
        The canonical title of the Manga
    synopsis: str
        The Synopsis/Description of the Manga
    abbreviated_titles: Optional[List[str]]
        A list of abbreivated titles for the Manga
    rating_frequencies: Optional[Dict[str, str]]
        The rating fequencies of the Manga
    age_rating: Optional[Literal["G", "PG", "R", "R18"]]
        The age rating for the Manga
    age_rating_guide: Optional[str]
        Elaborated age rating for the Manga
    status: Optional[Literal["current", "finished", "tba", "unreleased", "upcoming"]]
        The status of the Manga
    subtype: Optional[Literal["doujin", "manga", "manhua", "manhwa", "novel", "oel", "oneshot"]]
        The subtype of the Manga
    serialization: Optional[str]
    """

    __slots__ = ("subtype", "serialization")

    def __init__(self, payload: dict, session: aiohttp.ClientSession) -> None:
        super().__init__(payload, session)

        self.subtype: Optional[Literal["doujin", "manga", "manhua", "manhwa", "novel", "oel", "oneshot"]] = self._data[
            "attributes"
        ]["subtype"]
        self.serialization: Optional[str] = self._data["attributes"]["serialization"]

    @property
    def chapter_count(self) -> Optional[int]:
        """
        The number of chapters in this Manga

        Returns
        -------
        Optional[int]
        """
        try:
            return int(self._data["attributes"]["chapterCount"])
        except (KeyError, TypeError):
            return None

    @property
    def volume_count(self) -> Optional[int]:
        """
        The number of volumes of this Manga

        Returns
        -------
        Optional[int]
        """
        try:
            return int(self._data["attributes"]["volumeCount"])
        except (KeyError, TypeError):
            return None
