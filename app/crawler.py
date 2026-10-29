"""Orquesta una pasada de rastreo: búsquedas -> BD -> alertas -> geocodificación."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from . import market
from .config import Settings
from .db import Database
from .geocode import Geocoder
from .scrapers import SCRAPERS, BlockedError, PoliteClient

log = logging.getLogger(__name__)


@dataclass
class CrawlReport:
    new: int = 0
    updated: int = 0
    price_drops: int = 0
    alerts: list[tuple[str, str]] = field(default_factory=list)   # (título, mensaje)
    errors: list[str] = field(default_factory=list)


class Crawler:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    def run(self, progress: Callable[[str], None] = lambda _: None,
            cancelled: Callable[[], bool] = lambda: False) -> CrawlReport:
        rep = CrawlReport()
        client = PoliteClient(self.settings.user_agent, self.settings.request_delay_s)
        touched: set[str] = set()
        try:
            for s in self.db.searches():
                if not s.enabled or cancelled():
                    continue
                scraper_cls = SCRAPERS.get(s.source)
                if scraper_cls is None:
                    rep.errors.append(f"{s.name}: portal desconocido {s.source!r}")
                    continue
                try:
                    for l in scraper_cls(client, self.settings).search(s, progress):
                        if cancelled():
                            break
                        status, old = self.db.upsert_listing(l)
                        if status == "new":
                            rep.new += 1
                            touched.add(l.key)
                        elif status == "price_change":
                            rep.updated += 1
                            touched.add(l.key)
                            if old and l.price < old:
                                rep.price_drops += 1
                                pct = (1 - l.price / old) * 100
                                msg = f"Bajada de precio {old:,.0f} € → {l.price:,.0f} € (-{pct:.1f}%)"
                                if self.db.add_alert(l.key, "bajada", msg):
                                    rep.alerts.append((l.title, msg))
                except BlockedError as e:
                    rep.errors.append(f"{s.name}: {e}")
                except Exception as e:
                    log.exception("Error en búsqueda %s", s.name)
                    rep.errors.append(f"{s.name}: {e}")
        finally:
            client.close()

        # Evaluar chollos después de rastrear todo, para que las medianas incluyan lo nuevo
        progress("Evaluando oportunidades…")
        cache: dict = {}
        for key in touched:
            row = self.db.get_listing(key)
            if row is None or row["operation"] != "venta":
                continue
            reasons = market.deal_reasons(market.value_listing(self.db, row, self.settings, cache), self.settings)
            if reasons:
                msg = "Posible chollo: " + "; ".join(reasons)
                if self.db.add_alert(key, "chollo", msg):
                    rep.alerts.append((row["title"], msg))

        if self.settings.geocode and not cancelled():
            self._geocode(touched, progress)

        self.db.deactivate_stale(days=7)
        return rep

    def _geocode(self, keys: set[str], progress) -> None:
        geo = Geocoder(self.settings.user_agent)
        try:
            for key in keys:
                row = self.db.get_listing(key)
                if row is None or row["lat"] is not None:
                    continue
                progress(f"Geolocalizando {row['zone'] or row['city']}…")
                hit = geo.locate(row["zone"], row["city"])
                if hit:
                    self.db.set_coords(key, *hit)
        finally:
            geo.client.close()
