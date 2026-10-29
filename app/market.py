"""Valoración de mercado a partir de los propios anuncios rastreados.

- €/m² mediano de venta en la zona  -> ¿está por debajo de mercado?
- €/m² mediano de alquiler en la zona -> alquiler estimado -> rentabilidad.
Si la zona tiene pocos comparables se usa la ciudad entera.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional

from . import finance
from .config import Settings
from .db import Database


@dataclass
class Valuation:
    sale_m2_median: Optional[float]
    sale_comparables: int
    rent_m2_median: Optional[float]
    rent_comparables: int
    estimated_rent: Optional[float]
    discount_pct: Optional[float]        # >0 = más barato que la mediana
    metrics: Optional[finance.Result]
    scope: str                            # "zona" | "ciudad"


def _median_with_fallback(db: Database, operation: str, city: str, zone: str, min_n: int,
                          cache: Optional[dict] = None):
    ck = (operation, city.lower(), zone.lower())
    if cache is not None and ck in cache:
        return cache[ck]
    res = _compute_median(db, operation, city, zone, min_n)
    if cache is not None:
        cache[ck] = res
    return res


def _compute_median(db: Database, operation: str, city: str, zone: str, min_n: int):
    if zone:
        s = db.price_m2_samples(operation, city, zone)
        if len(s) >= min_n:
            return median(s), len(s), "zona"
    s = db.price_m2_samples(operation, city)
    return (median(s) if s else None), len(s), "ciudad"


def value_listing(db: Database, row, settings: Settings, cache: Optional[dict] = None) -> Valuation:
    """`cache` (un dict vacío reutilizado) evita recalcular medianas al valorar muchos anuncios."""
    city, zone, size = row["city"] or "", row["zone"] or "", row["size_m2"]
    min_n = settings.min_comparables

    sale_m2, n_sale, scope = _median_with_fallback(db, "venta", city, zone, min_n, cache)
    rent_m2, n_rent, _ = _median_with_fallback(db, "alquiler", city, zone, min_n, cache)

    est_rent = row["rent_override"]
    if est_rent is None and rent_m2 and size and n_rent >= min_n:
        est_rent = rent_m2 * size

    discount = None
    price = row["price"]
    if price and size and sale_m2 and n_sale >= min_n:
        discount = (1 - (price / size) / sale_m2) * 100

    metrics = None
    if price and est_rent:
        metrics = finance.analyze(price, est_rent, finance.Assumptions.from_settings(settings), size)

    return Valuation(sale_m2, n_sale, rent_m2, n_rent, est_rent, discount, metrics, scope)


def deal_reasons(v: Valuation, settings: Settings) -> list[str]:
    """Motivos por los que un anuncio de venta se considera chollo (lista vacía = no lo es)."""
    reasons = []
    if v.discount_pct is not None and v.discount_pct >= settings.deal_discount_pct:
        reasons.append(f"{v.discount_pct:.0f}% bajo el €/m² mediano de la {v.scope}")
    if v.metrics and v.metrics.gross_yield_pct >= settings.min_gross_yield_pct:
        reasons.append(f"rentabilidad bruta estimada {v.metrics.gross_yield_pct:.1f}%")
    return reasons
