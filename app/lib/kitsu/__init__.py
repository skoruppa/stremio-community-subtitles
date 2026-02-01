"""
Kitsu.io API Wrapper
--------------------

A Simple & Lightweight asynchronous python wrapper for Kitsu's Manga & Anime API.
"""

__title__ = "kitsu"
__version__ = "1.1.0"
__author__ = "MrArkon"
__license__ = "MIT"
__copyright__ = "Copyright 2021-present MrArkon"

__all__ = ("Client", "HTTPException", "BadRequest", "NotFound", "Anime", "Manga")
__path__ = __import__("pkgutil").extend_path(__path__, __name__)

from logging import NullHandler, getLogger

from .client import Client
from .errors import BadRequest, HTTPException, NotFound
from .models import Anime, Manga

getLogger(__name__).addHandler(NullHandler())
