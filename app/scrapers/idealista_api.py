"""Idealista mediante su API oficial (scrapear idealista.com está prohibido por sus
condiciones y bloqueado por su antibot). Pide credenciales en https://developers.idealista.com

La ubicación es «lat,lon,radio_metros», p. ej. «40.4168,-3.7038,2000».
"""
from __future__ import annotations

import base64
import time
from typing import Iterator

from ..models import Listing, Search
from .base import BaseScraper, ProgressFn

TOKEN_URL = "https://api.idealista.com/oauth/token"
SEARCH_URL = "https://api.idealista.com/3.5/es/search"


class IdealistaApiScraper(BaseScraper):
    name = "idealista"
    label = "Idealista (API oficial)"
    location_help = "lat,lon,radio_m — p. ej. 40.4168,-3.7038,2000"

    _token: str = ""
    _token_exp: float = 0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        key, secret = self.settings.idealista_api_key, self.settings.idealista_api_secret
        if not key or not secret:
            raise RuntimeError("Configura la API key y secret de Idealista en Ajustes")
        basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
        r = self.client.post(TOKEN_URL, headers={"Authorization": f"Basic {basic}"},
                             data={"grant_type": "client_credentials", "scope": "read"})
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600)) - 60
        return self._token

    def search(self, s: Search, progress: ProgressFn = lambda _: None) -> Iterator[Listing]:
        try:
            lat, lon, radius = [p.strip() for p in s.location.split(",")]
        except ValueError:
            raise ValueError(f"Ubicación inválida para Idealista: {s.location!r} ({self.location_help})")
        for page in range(1, s.max_pages + 1):
            progress(f"Idealista · {s.name} · página {page}")
            params = {
                "operation": "sale" if s.operation == "venta" else "rent",
                "propertyType": "homes",
                "center": f"{lat},{lon}",
                "distance": radius,
                "locale": "es",
                "maxItems": 50,
                "numPage": page,
                "order": "publicationDate",
                "sort": "desc",
            }
            if s.max_price:
                params["maxPrice"] = int(s.max_price)
            if s.min_size:
                params["minSize"] = int(s.min_size)
            r = self.client.post(SEARCH_URL, data=params,
                                 headers={"Authorization": f"Bearer {self._get_token()}"})
            r.raise_for_status()
            data = r.json()
            for e in data.get("elementList", []):
                l = Listing(
                    source="idealista",
                    external_id=str(e["propertyCode"]),
                    url=e.get("url", ""),
                    operation=s.operation,
                    title=e.get("suggestedTexts", {}).get("title", "") or e.get("address", ""),
                    price=e.get("price"),
                    size_m2=e.get("size"),
                    rooms=e.get("rooms"),
                    bathrooms=e.get("bathrooms"),
                    city=e.get("municipality", ""),
                    zone=e.get("neighborhood") or e.get("district", ""),
                    address=e.get("address", ""),
                    lat=e.get("latitude"),
                    lon=e.get("longitude"),
                    description=e.get("description", ""),
                    property_type=e.get("propertyType", "piso"),
                    image_url=e.get("thumbnail", ""),
                    extra={k: e.get(k) for k in ("floor", "exterior", "hasLift", "status", "newDevelopment")
                           if k in e},
                )
                if self.matches(l, s):
                    yield l
            if page >= data.get("totalPages", 0):
                break
