"""Rastreador de pisos.com (HTML de listados).

La ubicación es el fragmento de URL del portal: en
https://www.pisos.com/venta/pisos-madrid_capital/ la ubicación es «madrid_capital».
"""
from __future__ import annotations

import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Listing, Search
from .base import BaseScraper, ProgressFn, parse_number

BASE = "https://www.pisos.com"


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _split_location(subtitle: str, fallback_city: str) -> tuple[str, str]:
    """'Ruzafa (Distrito L'Eixample. Valencia Capital)' -> ('Ruzafa', 'Valencia Capital')."""
    m = re.match(r"\s*(.*?)\s*\((.*)\)\s*$", subtitle)
    if not m:
        return subtitle.strip(), fallback_city
    zone, inner = m.group(1), m.group(2)
    city = inner.split(".")[-1].strip() or fallback_city
    return zone, city


def parse_listing_page(html: str, operation: str, fallback_city: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Listing] = []
    for card in soup.select("div.ad-preview"):
        href = card.get("data-lnk-href") or (card.select_one("a.ad-preview__title") or {}).get("href")
        if not href:
            continue
        url = urljoin(BASE, href)
        ext_id = card.get("id") or (re.search(r"(\d+_\d+)/?$", href) or re.search(r"(\d+)", href)).group(1)

        chars = [_text(c) for c in card.select(".ad-preview__char")]
        rooms = baths = size = None
        for c in chars:
            low = c.lower()
            if "hab" in low or "dorm" in low:
                rooms = int(parse_number(c) or 0) or None
            elif "baño" in low:
                baths = int(parse_number(c) or 0) or None
            elif "m²" in low or "m2" in low:
                size = parse_number(c)

        title = _text(card.select_one(".ad-preview__title"))
        zone, city = _split_location(_text(card.select_one(".ad-preview__subtitle")), fallback_city)
        img = card.select_one("img")
        out.append(Listing(
            source="pisos",
            external_id=str(ext_id),
            url=url,
            operation=operation,
            title=title,
            price=parse_number(_text(card.select_one(".ad-preview__price"))),
            size_m2=size,
            rooms=rooms,
            bathrooms=baths,
            city=city,
            zone=zone,
            address=title,
            description=_text(card.select_one(".ad-preview__description")),
            image_url=(img.get("data-src") or img.get("src") or "") if img else "",
        ))
    return out


class PisosScraper(BaseScraper):
    name = "pisos"
    label = "pisos.com"
    location_help = "Fragmento de la URL de pisos.com, p. ej. madrid_capital o valencia_capital"

    def search(self, s: Search, progress: ProgressFn = lambda _: None) -> Iterator[Listing]:
        op = "venta" if s.operation == "venta" else "alquiler"
        city = s.location.split("/")[0].replace("_capital", "").replace("_", " ").title()
        for page in range(1, s.max_pages + 1):
            url = f"{BASE}/{op}/pisos-{s.location}/" + (f"{page}/" if page > 1 else "")
            progress(f"pisos.com · {s.name} · página {page}")
            r = self.client.get(url)
            if r.status_code == 404:
                break
            items = parse_listing_page(r.text, s.operation, city)
            if not items:
                break
            for l in items:
                if self.matches(l, s):
                    yield l
