"""Modelos de datos compartidos por rastreadores, base de datos y UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Listing:
    """Un anuncio inmobiliario normalizado, venga del portal que venga."""

    source: str                 # "pisos", "idealista", ...
    external_id: str            # id del anuncio en el portal
    url: str
    operation: str              # "venta" | "alquiler"
    title: str = ""
    price: Optional[float] = None
    size_m2: Optional[float] = None
    rooms: Optional[int] = None
    bathrooms: Optional[int] = None
    city: str = ""
    zone: str = ""              # barrio / distrito, se usa para comparar precios
    address: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    description: str = ""
    property_type: str = "piso"
    image_url: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"

    @property
    def price_m2(self) -> Optional[float]:
        if self.price and self.size_m2:
            return self.price / self.size_m2
        return None


@dataclass
class Search:
    """Una búsqueda guardada que se rastrea periódicamente."""

    id: Optional[int]
    name: str
    source: str                 # nombre del rastreador
    operation: str              # "venta" | "alquiler"
    location: str               # p. ej. "madrid", "valencia/ruzafa"
    max_price: Optional[float] = None
    min_size: Optional[float] = None
    min_rooms: Optional[int] = None
    max_pages: int = 3
    enabled: bool = True
