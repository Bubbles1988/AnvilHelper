"""Finds a picture for an item on the Anvil Empires wiki (anvilempires.wiki.gg).

Order: manual override in data/manual/images.json -> cached result -> wiki API.
Results (including "no image") are cached in data/cache/images.json so the wiki is
asked only once per item.
"""

import asyncio
import json
import logging
from pathlib import Path

import aiohttp

from .data import DATA_DIR, GameData
from .text import key

log = logging.getLogger(__name__)

API_URL = "https://anvilempires.wiki.gg/api.php"
USER_AGENT = "AnvilHelperDiscordBot/1.0 (https://github.com/bubbles1988/AnvilHelper)"
CACHE_FILE = DATA_DIR / "cache" / "images.json"
_FAILED = object()  # wiki unreachable: try again next time instead of caching "no image"


class ImageFinder:
    def __init__(self, data: GameData, cache_file: Path = CACHE_FILE, enabled: bool = True):
        self.data = data
        self.enabled = enabled
        self.cache_file = cache_file
        self.cache: dict[str, str | None] = {}
        if cache_file.exists():
            try:
                self.cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("Could not read %s, starting with an empty image cache", cache_file)
        self._session: aiohttp.ClientSession | None = None

    async def close(self):
        if self._session:
            await self._session.close()

    async def find(self, name: str) -> str | None:
        k = key(name)
        if k in self.data.image_overrides:
            return self.data.image_overrides[k]
        if k in self.cache:
            return self.cache[k]
        if not self.enabled:
            return None
        url = await self._ask_wiki(self.data.wiki_titles.get(k, name))
        if url is _FAILED:
            return None
        self.cache[k] = url
        self._save()
        return url

    async def _ask_wiki(self, title: str):
        params = {
            "action": "query",
            "format": "json",
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": "256",
            "redirects": "1",
            "titles": title,
        }
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
            timeout = aiohttp.ClientTimeout(total=4)
            async with self._session.get(API_URL, params=params, timeout=timeout) as resp:
                if resp.status != 200:
                    return _FAILED
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            log.info("Wiki image lookup for %r failed: %s", title, exc)
            return _FAILED
        for page in payload.get("query", {}).get("pages", {}).values():
            thumb = page.get("thumbnail", {}).get("source")
            if thumb:
                return thumb
        return None

    def _save(self):
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(self.cache, indent=1, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not write image cache: %s", exc)
