"""Infraestructura común de rastreo: cliente HTTP educado y clase base de rastreadores."""
from __future__ import annotations

import logging
import re
import threading
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from typing import Callable, Iterator, Optional
from urllib.parse import urlparse

import httpx

from ..models import Listing, Search

log = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}


class BlockedError(RuntimeError):
    """El portal ha bloqueado la petición (captcha, 403, robots.txt...)."""


class PoliteClient:
    """Cliente HTTP que respeta robots.txt y espera entre peticiones al mismo dominio."""

    def __init__(self, user_agent: str, delay_s: float = 4.0, timeout: float = 30.0):
        self.user_agent = user_agent
        self.delay_s = delay_s
        self._client = httpx.Client(headers={**BROWSER_HEADERS, "User-Agent": user_agent},
                                    timeout=timeout, follow_redirects=True)
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._lock = threading.Lock()

    def _allowed(self, url: str) -> bool:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self._client.get(base + "/robots.txt")
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])
            self._robots[base] = rp
        return rp.can_fetch(self.user_agent, url)

    def _wait(self, host: str) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last.get(host, 0)
            if elapsed < self.delay_s:
                time.sleep(self.delay_s - elapsed)
            self._last[host] = time.monotonic()

    def get(self, url: str, check_robots: bool = True, **kw) -> httpx.Response:
        if check_robots and not self._allowed(url):
            raise BlockedError(f"robots.txt no permite rastrear {url}")
        return self._request("GET", url, **kw)

    def post(self, url: str, **kw) -> httpx.Response:
        return self._request("POST", url, **kw)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        host = urlparse(url).netloc
        for attempt in range(3):
            self._wait(host)
            try:
                r = self._client.request(method, url, **kw)
            except httpx.TransportError as e:
                log.warning("Error de red en %s (%s), reintento %d", url, e, attempt + 1)
                time.sleep(2 ** (attempt + 1))
                continue
            if r.status_code in (403, 429) or "captcha" in r.text[:5000].lower():
                raise BlockedError(f"{host} ha bloqueado la petición (HTTP {r.status_code})")
            if r.status_code >= 500:
                time.sleep(2 ** (attempt + 1))
                continue
            return r
        raise RuntimeError(f"No se pudo descargar {url}")

    def close(self) -> None:
        self._client.close()


def parse_number(text: str | None) -> Optional[float]:
    """'1.250.000 €' -> 1250000.0 ; '85,5 m²' -> 85.5"""
    if not text:
        return None
    m = re.search(r"\d[\d.\s]*(?:,\d+)?", text.replace("\xa0", " "))
    if not m:
        return None
    num = m.group(0).replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


ProgressFn = Callable[[str], None]


class BaseScraper(ABC):
    name: str = ""
    label: str = ""
    location_help: str = ""

    def __init__(self, client: PoliteClient, settings):
        self.client = client
        self.settings = settings

    @abstractmethod
    def search(self, s: Search, progress: ProgressFn = lambda _: None) -> Iterator[Listing]:
        ...

    @staticmethod
    def matches(l: Listing, s: Search) -> bool:
        """Filtros que se aplican en local, por si el portal no los soporta en la URL."""
        if s.max_price and l.price and l.price > s.max_price:
            return False
        if s.min_size and l.size_m2 and l.size_m2 < s.min_size:
            return False
        if s.min_rooms and l.rooms is not None and l.rooms < s.min_rooms:
            return False
        return True
