"""Persistencia en SQLite: anuncios, histórico de precios, búsquedas y alertas."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import Listing, Search

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    operation TEXT NOT NULL,
    title TEXT, price REAL, size_m2 REAL, rooms INTEGER, bathrooms INTEGER,
    city TEXT, zone TEXT, address TEXT, lat REAL, lon REAL,
    description TEXT, property_type TEXT, image_url TEXT, extra TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    favorite INTEGER NOT NULL DEFAULT 0,
    rent_override REAL,
    ai_analysis TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_zone ON listings(operation, city, zone);

CREATE TABLE IF NOT EXISTS price_history (
    key TEXT NOT NULL,
    ts TEXT NOT NULL,
    price REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ph_key ON price_history(key);

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, source TEXT NOT NULL, operation TEXT NOT NULL,
    location TEXT NOT NULL, max_price REAL, min_size REAL, min_rooms INTEGER,
    max_pages INTEGER NOT NULL DEFAULT 3, enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL,
    ts TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0
);
"""

LISTING_COLS = [
    "source", "external_id", "url", "operation", "title", "price", "size_m2", "rooms",
    "bathrooms", "city", "zone", "address", "lat", "lon", "description",
    "property_type", "image_url",
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    """Envoltorio fino y thread-safe sobre sqlite3 (el rastreo corre en hilos)."""

    def __init__(self, path: Path | str):
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ---------- anuncios ----------
    def upsert_listing(self, l: Listing) -> tuple[str, Optional[float]]:
        """Guarda el anuncio. Devuelve ("new"|"price_change"|"same", precio_anterior)."""
        now = _now()
        with self._lock, self.conn:
            row = self.conn.execute("SELECT price, lat FROM listings WHERE key=?", (l.key,)).fetchone()
            values = [getattr(l, c) for c in LISTING_COLS]
            if row is None:
                self.conn.execute(
                    f"INSERT INTO listings (key, {', '.join(LISTING_COLS)}, extra, first_seen, last_seen) "
                    f"VALUES (?, {', '.join('?' * len(LISTING_COLS))}, ?, ?, ?)",
                    [l.key, *values, json.dumps(l.extra), now, now],
                )
                if l.price:
                    self.conn.execute("INSERT INTO price_history VALUES (?, ?, ?)", (l.key, now, l.price))
                return "new", None

            # No machacar coordenadas ya geocodificadas con None
            if l.lat is None and row["lat"] is not None:
                values[LISTING_COLS.index("lat")] = row["lat"]
                values[LISTING_COLS.index("lon")] = self.conn.execute(
                    "SELECT lon FROM listings WHERE key=?", (l.key,)).fetchone()[0]
            sets = ", ".join(f"{c}=?" for c in LISTING_COLS)
            self.conn.execute(
                f"UPDATE listings SET {sets}, extra=?, last_seen=?, active=1 WHERE key=?",
                [*values, json.dumps(l.extra), now, l.key],
            )
            old = row["price"]
            if l.price and old and abs(l.price - old) >= 1:
                self.conn.execute("INSERT INTO price_history VALUES (?, ?, ?)", (l.key, now, l.price))
                return "price_change", old
            return "same", old

    def deactivate_stale(self, days: int = 7) -> int:
        """Marca como retirados los anuncios que no se han vuelto a ver en `days` días."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self._lock, self.conn:
            return self.conn.execute("UPDATE listings SET active=0 WHERE active=1 AND last_seen < ?",
                                     (cutoff,)).rowcount

    def set_coords(self, key: str, lat: float, lon: float) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE listings SET lat=?, lon=? WHERE key=?", (lat, lon, key))

    def set_ai_analysis(self, key: str, analysis: dict) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE listings SET ai_analysis=? WHERE key=?",
                              (json.dumps(analysis, ensure_ascii=False), key))

    def set_favorite(self, key: str, fav: bool) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE listings SET favorite=? WHERE key=?", (int(fav), key))

    def set_rent_override(self, key: str, rent: Optional[float]) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE listings SET rent_override=? WHERE key=?", (rent, key))

    def get_listing(self, key: str) -> Optional[sqlite3.Row]:
        with self._lock:
            return self.conn.execute("SELECT * FROM listings WHERE key=?", (key,)).fetchone()

    def listings(self, operation: str = "venta", only_active: bool = True) -> list[sqlite3.Row]:
        q = "SELECT * FROM listings WHERE operation=?"
        if only_active:
            q += " AND active=1"
        with self._lock:
            return self.conn.execute(q + " ORDER BY last_seen DESC", (operation,)).fetchall()

    def price_history(self, key: str) -> list[tuple[str, float]]:
        with self._lock:
            return [(r["ts"], r["price"]) for r in self.conn.execute(
                "SELECT ts, price FROM price_history WHERE key=? ORDER BY ts", (key,))]

    def price_m2_samples(self, operation: str, city: str, zone: str = "") -> list[float]:
        """€/m² de anuncios activos comparables (misma operación, ciudad y, si hay, zona)."""
        q = ("SELECT price / size_m2 FROM listings WHERE operation=? AND active=1 "
             "AND price > 0 AND size_m2 > 10 AND lower(city)=lower(?)")
        args = [operation, city]
        if zone:
            q += " AND lower(zone)=lower(?)"
            args.append(zone)
        with self._lock:
            return [r[0] for r in self.conn.execute(q, args)]

    # ---------- búsquedas ----------
    def searches(self) -> list[Search]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM searches ORDER BY id").fetchall()
        return [Search(**{**dict(r), "enabled": bool(r["enabled"])}) for r in rows]

    def save_search(self, s: Search) -> int:
        cols = ["name", "source", "operation", "location", "max_price", "min_size",
                "min_rooms", "max_pages", "enabled"]
        vals = [getattr(s, c) for c in cols]
        with self._lock, self.conn:
            if s.id is None:
                cur = self.conn.execute(
                    f"INSERT INTO searches ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
                return cur.lastrowid
            self.conn.execute(f"UPDATE searches SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                              [*vals, s.id])
            return s.id

    def delete_search(self, search_id: int) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM searches WHERE id=?", (search_id,))

    # ---------- alertas ----------
    def add_alert(self, key: str, kind: str, message: str) -> bool:
        """Crea la alerta si no existe ya una idéntica. Devuelve True si es nueva."""
        with self._lock, self.conn:
            dup = self.conn.execute("SELECT 1 FROM alerts WHERE key=? AND kind=? AND message=?",
                                    (key, kind, message)).fetchone()
            if dup:
                return False
            self.conn.execute("INSERT INTO alerts (key, kind, message, ts) VALUES (?, ?, ?, ?)",
                              (key, kind, message, _now()))
            return True

    def alerts(self, limit: int = 200) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def mark_alerts_seen(self) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE alerts SET seen=1")
