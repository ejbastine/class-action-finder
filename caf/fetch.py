"""Polite, cached HTTP GET. Every page is cached on disk; a failed request falls back to the
last cached copy so one flaky site never sinks a run."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import config

log = logging.getLogger(__name__)


class Fetcher:
    def __init__(self, cache_dir: Path = config.PAGE_CACHE_DIR, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.network_hits = 0
        self._last_hit: dict[str, float] = {}
        self._client = httpx.Client(
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            follow_redirects=True,
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def _path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".html")

    def get(self, url: str, ttl_hours: float) -> str | None:
        """Page text, from cache when fresh enough. None if unavailable."""
        path = self._path(url)
        fresh = path.exists() and time.time() - path.stat().st_mtime < ttl_hours * 3600
        if path.exists() and (fresh or self.offline):
            return path.read_text(encoding="utf-8")
        if self.offline:
            return None
        host = urlsplit(url).hostname or ""
        wait = config.REQUEST_GAP_SECONDS - (time.monotonic() - self._last_hit.get(host, -1e9))
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()
        self.network_hits += 1
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            log.warning("fetch failed for %s: %s", url, exc)
            return path.read_text(encoding="utf-8") if path.exists() else None
        if resp.status_code != 200:
            log.warning("HTTP %s for %s", resp.status_code, url)
            return path.read_text(encoding="utf-8") if path.exists() else None
        text = resp.text
        path.write_text(text, encoding="utf-8")
        return text
