"""Ajustes del usuario, guardados como JSON en la carpeta de datos de la app."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".local", "share")
    path = Path(base) / "InmoScout"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    # Rastreo
    crawl_interval_min: int = 120
    request_delay_s: float = 4.0          # pausa entre peticiones al mismo portal
    user_agent: str = "InmoScout/1.0 (uso personal)"
    geocode: bool = True                  # geolocalizar anuncios sin coordenadas (Nominatim)

    # Hipótesis financieras por defecto
    down_payment_pct: float = 20.0        # entrada
    purchase_costs_pct: float = 10.0      # ITP/IVA + notaría + registro + gestoría
    mortgage_rate_pct: float = 3.0
    mortgage_years: int = 25
    vacancy_pct: float = 5.0
    opex_pct_of_rent: float = 20.0        # IBI, comunidad, seguro, mantenimiento, gestión

    # Alertas de chollos
    deal_discount_pct: float = 15.0       # % por debajo del €/m² mediano de la zona
    min_gross_yield_pct: float = 7.0
    min_comparables: int = 5

    # IA
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"

    # Idealista API oficial (https://developers.idealista.com)
    idealista_api_key: str = ""
    idealista_api_secret: str = ""

    @classmethod
    def path(cls) -> Path:
        return data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        p = cls.path()
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
