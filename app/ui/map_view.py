"""Mapa Leaflet/OpenStreetMap dentro de un QWebEngineView."""
from __future__ import annotations

import html
import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<style>__LEAFLET_CSS__</style><script>__LEAFLET_JS__</script>
<style>html,body,#map{height:100%;margin:0} .lg{background:#fff;padding:6px 8px;border-radius:4px;font:12px sans-serif}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:4px}</style>
</head><body><div id="map"></div><script>
const pts = __POINTS__;
const map = L.map('map').setView([40.42, -3.70], 6);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom: 19, attribution: '&copy; OpenStreetMap'}).addTo(map);
const group = [];
for (const p of pts) {
  const m = L.circleMarker([p.lat, p.lon], {radius: p.fav ? 9 : 6, color: p.color, fillColor: p.color,
                                             fillOpacity: 0.8, weight: p.fav ? 3 : 1});
  m.bindPopup(p.popup); m.addTo(map); group.push([p.lat, p.lon]);
}
if (group.length) map.fitBounds(group, {padding: [30, 30], maxZoom: 15});
const lg = L.control({position: 'bottomright'});
lg.onAdd = () => { const d = L.DomUtil.create('div', 'lg');
  d.innerHTML = '<b>Precio vs. zona</b><br><span class="dot" style="background:#1a9850"></span>&gt;15% más barato'
   + '<br><span class="dot" style="background:#91cf60"></span>5-15% más barato'
   + '<br><span class="dot" style="background:#fee08b"></span>en mercado'
   + '<br><span class="dot" style="background:#d73027"></span>más caro'
   + '<br><span class="dot" style="background:#888"></span>sin datos'; return d; };
lg.addTo(map);
</script></body></html>"""


ASSETS = Path(__file__).parent / "assets"   # Leaflet 1.9.4 incluido para no depender de un CDN


def color_for(discount: float | None) -> str:
    if discount is None:
        return "#888"
    if discount >= 15:
        return "#1a9850"
    if discount >= 5:
        return "#91cf60"
    if discount >= -5:
        return "#fee08b"
    return "#d73027"


class _ExternalLinksPage(QWebEnginePage):
    """Abre los enlaces de los anuncios en el navegador del sistema."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class MapView(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPage(_ExternalLinksPage(self))

    def show_points(self, points: list[dict]) -> None:
        """points: dicts con lat, lon, title, price, url, discount, fav."""
        data = []
        for p in points:
            price = f"{p['price']:,.0f} €".replace(",", ".") if p.get("price") else "—"
            d = p.get("discount")
            disc = "" if d is None else f"<br>{abs(d):.0f}% {'bajo' if d >= 0 else 'sobre'} la mediana"
            popup = (f"<b>{html.escape(p['title'] or '')}</b><br>{price}{disc}"
                     f"<br><a href='{html.escape(p['url'])}'>Ver anuncio</a>")
            data.append({"lat": p["lat"], "lon": p["lon"], "popup": popup,
                         "color": color_for(p.get("discount")), "fav": bool(p.get("fav"))})
        page = (TEMPLATE
                .replace("__LEAFLET_CSS__", (ASSETS / "leaflet.css").read_text(encoding="utf-8"))
                .replace("__LEAFLET_JS__", (ASSETS / "leaflet.js").read_text(encoding="utf-8"))
                .replace("__POINTS__", json.dumps(data)))
        self.setHtml(page, QUrl("https://inmoscout.local/"))
