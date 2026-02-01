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

from typing import Optional

from aiohttp import ClientResponse


class HTTPException(Exception):
    """Generic API exception when the response code is a non 2xx error."""

    def __init__(self, response: ClientResponse, message: str, response_code: int) -> None:
        self.response: ClientResponse = response
        self.message: str = message
        self.response_code: Optional[int] = response_code
        super().__init__(self.response, self.message, self.response_code)


class BadRequest(HTTPException):
    """An exception for when the API query is malformed."""

    def __init__(self, response: ClientResponse, message: str) -> None:
        self.response: ClientResponse = response
        self.message: str = message
        super().__init__(response, message, 400)


class NotFound(HTTPException):
    """An exception for when the requested API item was not found."""

    def __init__(self, response: ClientResponse, message: str) -> None:
        self.response: ClientResponse = response
        self.message: str = message
        super().__init__(response, message, 404)
