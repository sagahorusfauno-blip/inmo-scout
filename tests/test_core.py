from pathlib import Path

import pytest

from app import finance, market
from app.config import Settings
from app.crawler import Crawler
from app.db import Database
from app.models import Listing, Search
from app.scrapers import SCRAPERS
from app.scrapers.base import BaseScraper, parse_number
from app.scrapers.pisos import parse_listing_page

FIX = Path(__file__).parent / "fixtures"


def mk(i, op="venta", price=200_000, size=100, zone="Ruzafa", city="Valencia"):
    return Listing("test", str(i), f"https://x/{i}", op, f"Piso {i}", price, size, 3, 1, city, zone)


def test_parse_number():
    assert parse_number("1.250.000 €") == 1_250_000
    assert parse_number("85,5 m²") == 85.5
    assert parse_number("sin precio") is None


def test_mortgage_payment_known_value():
    # 100.000 € a 3% 25 años ≈ 474,21 €/mes
    assert finance.mortgage_payment(100_000, 3, 25) == pytest.approx(474.21, abs=0.01)
    assert finance.mortgage_payment(120_000, 0, 10) == pytest.approx(1000)


def test_analyze_yields():
    a = finance.Assumptions(down_payment_pct=20, purchase_costs_pct=10, mortgage_rate_pct=3,
                            mortgage_years=25, vacancy_pct=0, opex_pct_of_rent=0)
    r = finance.analyze(100_000, 700, a)
    assert r.gross_yield_pct == pytest.approx(8.4)
    assert r.cash_needed == pytest.approx(30_000)
    assert r.net_yield_pct == pytest.approx(8400 / 110_000 * 100)
    assert r.monthly_cash_flow == pytest.approx(700 - finance.mortgage_payment(80_000, 3, 25))


def test_pisos_parser():
    items = parse_listing_page((FIX / "pisos_listado.html").read_text(), "venta", "Valencia")
    assert len(items) == 2
    a, b = items
    assert a.external_id == "61234567890_100500"
    assert a.url.startswith("https://www.pisos.com/comprar/")
    assert (a.price, a.size_m2, a.rooms, a.bathrooms) == (215_000, 85, 3, 1)
    assert (a.zone, a.city) == ("Ruzafa", "Valencia Capital")
    assert a.image_url.endswith("x.jpg")
    assert (b.price, b.size_m2, b.rooms, b.bathrooms) == (1_150_000, 160.5, 5, None)


def test_db_price_history_and_alert_dedup(tmp_path):
    db = Database(tmp_path / "t.db")
    assert db.upsert_listing(mk(1))[0] == "new"
    assert db.upsert_listing(mk(1))[0] == "same"
    status, old = db.upsert_listing(mk(1, price=180_000))
    assert (status, old) == ("price_change", 200_000)
    assert [p for _, p in db.price_history("test:1")] == [200_000, 180_000]
    assert db.add_alert("test:1", "bajada", "x") is True
    assert db.add_alert("test:1", "bajada", "x") is False


def test_coords_survive_rescrape(tmp_path):
    db = Database(tmp_path / "t.db")
    db.upsert_listing(mk(1))
    db.set_coords("test:1", 39.46, -0.37)
    db.upsert_listing(mk(1))
    row = db.get_listing("test:1")
    assert (row["lat"], row["lon"]) == (39.46, -0.37)


def test_valuation_and_deal(tmp_path):
    db = Database(tmp_path / "t.db")
    s = Settings(min_comparables=3, deal_discount_pct=15, min_gross_yield_pct=7)
    for i in range(5):
        db.upsert_listing(mk(i, price=300_000))                 # 3.000 €/m²
        db.upsert_listing(mk(100 + i, op="alquiler", price=1_200))  # 12 €/m²/mes
    db.upsert_listing(mk(99, price=200_000))                    # 2.000 €/m²
    v = market.value_listing(db, db.get_listing("test:99"), s)
    assert v.scope == "zona"
    assert v.sale_m2_median == 3000
    assert v.estimated_rent == pytest.approx(1200)
    assert v.discount_pct == pytest.approx(33.33, abs=0.01)
    assert v.metrics.gross_yield_pct == pytest.approx(7.2)
    assert len(market.deal_reasons(v, s)) == 2


class FakeScraper(BaseScraper):
    name = "fake"
    prices = {}

    def search(self, s, progress=lambda _: None):
        for i, p in self.prices.items():
            yield mk(i, price=p)


def test_crawler_detects_price_drop(tmp_path, monkeypatch):
    monkeypatch.setitem(SCRAPERS, "fake", FakeScraper)
    db = Database(tmp_path / "t.db")
    db.save_search(Search(None, "t", "fake", "venta", "x"))
    settings = Settings(geocode=False, request_delay_s=0)
    FakeScraper.prices = {1: 200_000, 2: 150_000}
    rep = Crawler(db, settings).run()
    assert (rep.new, rep.price_drops, rep.errors) == (2, 0, [])
    FakeScraper.prices = {1: 190_000, 2: 150_000}
    rep = Crawler(db, settings).run()
    assert rep.price_drops == 1
    assert "Bajada de precio" in rep.alerts[0][1]
