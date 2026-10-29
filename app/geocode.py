"""Geocodificación aproximada (zona + ciudad) con Nominatim / OpenStreetMap.

Política de uso de Nominatim: máx. 1 petición/segundo y User-Agent identificable.
Se geocodifica por zona y no por anuncio para hacer muy pocas peticiones.
"""
from __future__ import annotations

import json
import logging
import random

from .config import data_dir
from .scrapers.base import PoliteClient

log = logging.getLogger(__name__)
URL = "https://nominatim.openstreetmap.org/search"


class Geocoder:
    def __init__(self, user_agent: str):
        self.client = PoliteClient(user_agent, delay_s=1.1)
        self.cache_path = data_dir() / "geocache.json"
        try:
            self.cache: dict[str, list | None] = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}

    def locate(self, zone: str, city: str) -> tuple[float, float] | None:
        query = ", ".join(p for p in (zone, city, "España") if p)
        if query not in self.cache:
            try:
                r = self.client.get(URL, check_robots=False,
                                    params={"q": query, "format": "json", "limit": 1})
                hits = r.json()
                self.cache[query] = [float(hits[0]["lat"]), float(hits[0]["lon"])] if hits else None
            except Exception as e:  # la geocodificación nunca debe tumbar el rastreo
                log.warning("Geocodificación fallida para %s: %s", query, e)
                return None
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
        hit = self.cache[query]
        if not hit:
            return None
        # Pequeña dispersión (~150 m) para que los anuncios de una misma zona no se solapen
        return hit[0] + random.uniform(-0.0015, 0.0015), hit[1] + random.uniform(-0.0015, 0.0015)
