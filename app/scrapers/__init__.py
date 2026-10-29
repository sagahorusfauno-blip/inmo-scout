"""Registro de rastreadores. Para añadir un portal nuevo, crea una subclase de
BaseScraper y añádela a SCRAPERS."""
from .base import BaseScraper, BlockedError, PoliteClient
from .idealista_api import IdealistaApiScraper
from .pisos import PisosScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    PisosScraper.name: PisosScraper,
    IdealistaApiScraper.name: IdealistaApiScraper,
}

__all__ = ["SCRAPERS", "BaseScraper", "BlockedError", "PoliteClient"]
