"""Ficha de un anuncio: datos, calculadora de rentabilidad, histórico de precios y análisis IA."""
from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, Qt, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QSpinBox, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from .. import ai, finance, market
from ..config import Settings
from ..db import Database
from .workers import Worker


def eur(v) -> str:
    return "—" if v is None else f"{v:,.0f} €".replace(",", ".")


def _spin(value, maximum, step=1.0, decimals=0, suffix="") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(0, maximum)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setValue(value or 0)
    return s


class DetailDialog(QDialog):
    def __init__(self, db: Database, settings: Settings, key: str, parent=None):
        super().__init__(parent)
        self.db, self.settings, self.key = db, settings, key
        self.row = db.get_listing(key)
        self.val = market.value_listing(db, self.row, settings)
        self.setWindowTitle(self.row["title"] or key)
        self.resize(900, 680)

        layout = QVBoxLayout(self)
        size_txt = f"{self.row['size_m2']:.0f}" if self.row["size_m2"] else "—"
        header = QLabel(f"<h2>{self.row['title']}</h2>"
                        f"{self.row['zone']}, {self.row['city']} · {eur(self.row['price'])} · "
                        f"{size_txt} m² · {self.row['rooms'] or '—'} hab. · "
                        f"{self.row['bathrooms'] or '—'} baños · {self.row['source']}")
        header.setWordWrap(True)
        layout.addWidget(header)

        buttons = QHBoxLayout()
        open_btn = QPushButton("Abrir anuncio en el navegador")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.row["url"])))
        self.fav = QCheckBox("★ Favorito")
        self.fav.setChecked(bool(self.row["favorite"]))
        self.fav.toggled.connect(lambda v: db.set_favorite(key, v))
        buttons.addWidget(open_btn)
        buttons.addWidget(self.fav)
        buttons.addStretch()
        layout.addLayout(buttons)

        tabs = QTabWidget()
        tabs.addTab(self._calculator_tab(), "Rentabilidad")
        tabs.addTab(self._history_tab(), "Histórico de precio")
        tabs.addTab(self._ai_tab(), "Análisis IA")
        desc = QTextBrowser()
        desc.setPlainText(self.row["description"] or "(sin descripción)")
        tabs.addTab(desc, "Descripción")
        layout.addWidget(tabs)

    # ---------- calculadora ----------
    def _calculator_tab(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        a = finance.Assumptions.from_settings(self.settings)
        is_sale = self.row["operation"] == "venta"

        inputs = QGroupBox("Hipótesis (edita y se recalcula)")
        f = QFormLayout(inputs)
        self.in_price = _spin(self.row["price"], 50_000_000, 1000, suffix=" €")
        self.in_rent = _spin(self.val.estimated_rent, 100_000, 25, suffix=" €/mes")
        self.in_reno = _spin(0, 5_000_000, 1000, suffix=" €")
        self.in_down = _spin(a.down_payment_pct, 100, 5, 1, " %")
        self.in_costs = _spin(a.purchase_costs_pct, 30, 0.5, 1, " %")
        self.in_rate = _spin(a.mortgage_rate_pct, 15, 0.1, 2, " %")
        self.in_years = QSpinBox()
        self.in_years.setRange(1, 40)
        self.in_years.setValue(a.mortgage_years)
        self.in_vac = _spin(a.vacancy_pct, 100, 1, 1, " %")
        self.in_opex = _spin(a.opex_pct_of_rent, 100, 1, 1, " %")
        f.addRow("Precio compra", self.in_price)
        f.addRow("Alquiler mensual", self.in_rent)
        f.addRow("Reforma", self.in_reno)
        f.addRow("Entrada", self.in_down)
        f.addRow("Gastos compra (ITP, notaría…)", self.in_costs)
        f.addRow("Interés hipoteca", self.in_rate)
        f.addRow("Años hipoteca", self.in_years)
        f.addRow("Vacío", self.in_vac)
        f.addRow("Gastos s/ alquiler", self.in_opex)
        save_rent = QPushButton("Guardar este alquiler para el anuncio")
        save_rent.clicked.connect(lambda: self.db.set_rent_override(self.key, self.in_rent.value() or None))
        f.addRow(save_rent)
        for s in (self.in_price, self.in_rent, self.in_reno, self.in_down, self.in_costs,
                  self.in_rate, self.in_vac, self.in_opex):
            s.valueChanged.connect(self._recalc)
        self.in_years.valueChanged.connect(self._recalc)

        out = QGroupBox("Resultado")
        v = QVBoxLayout(out)
        v_ = self.val
        market_txt = (f"<b>Mercado ({v_.scope})</b><br>"
                      f"€/m² venta mediano: {eur(v_.sale_m2_median)} ({v_.sale_comparables} comparables)<br>"
                      f"€/m² alquiler mediano: {f'{v_.rent_m2_median:.1f} €' if v_.rent_m2_median else '—'}"
                      f" ({v_.rent_comparables} comparables)<br>")
        if v_.discount_pct is not None:
            market_txt += f"Este anuncio está un <b>{v_.discount_pct:.1f}%</b> " \
                          f"{'por debajo' if v_.discount_pct >= 0 else 'por encima'} de la mediana<br>"
        if v_.estimated_rent is None and is_sale:
            market_txt += ("<i>No hay suficientes alquileres rastreados en la zona para estimar la renta: "
                           "añade una búsqueda de alquiler o introdúcela a mano.</i>")
        self.market_lbl = QLabel(market_txt)
        self.market_lbl.setWordWrap(True)
        self.result_lbl = QLabel()
        self.result_lbl.setTextFormat(Qt.RichText)
        v.addWidget(self.market_lbl)
        v.addWidget(self.result_lbl)
        v.addStretch()

        lay.addWidget(inputs)
        lay.addWidget(out, 1)
        if not is_sale:
            inputs.setEnabled(False)
        self._recalc()
        return w

    def _recalc(self) -> None:
        price, rent = self.in_price.value(), self.in_rent.value()
        if not price or not rent:
            self.result_lbl.setText("Introduce precio y alquiler para calcular.")
            return
        a = finance.Assumptions(self.in_down.value(), self.in_costs.value(), self.in_rate.value(),
                                self.in_years.value(), self.in_vac.value(), self.in_opex.value(),
                                self.in_reno.value())
        r = finance.analyze(price, rent, a, self.row["size_m2"])
        cf_color = "#1a7f37" if r.monthly_cash_flow >= 0 else "#cf222e"
        self.result_lbl.setText(
            f"<table cellpadding=3>"
            f"<tr><td>Inversión total</td><td align=right>{eur(r.total_investment)}</td></tr>"
            f"<tr><td>Dinero a aportar</td><td align=right><b>{eur(r.cash_needed)}</b></td></tr>"
            f"<tr><td>Hipoteca</td><td align=right>{eur(r.loan)} · {eur(r.monthly_mortgage)}/mes</td></tr>"
            f"<tr><td>Ingresos netos anuales (NOI)</td><td align=right>{eur(r.annual_net_income)}</td></tr>"
            f"<tr><td>Rentabilidad bruta</td><td align=right><b>{r.gross_yield_pct:.2f} %</b></td></tr>"
            f"<tr><td>Rentabilidad neta</td><td align=right><b>{r.net_yield_pct:.2f} %</b></td></tr>"
            f"<tr><td>Cash flow mensual</td><td align=right style='color:{cf_color}'>"
            f"<b>{eur(r.monthly_cash_flow)}</b></td></tr>"
            f"<tr><td>Cash-on-cash</td><td align=right>{r.cash_on_cash_pct:.2f} %</td></tr></table>")

    # ---------- histórico ----------
    def _history_tab(self) -> QWidget:
        hist = self.db.price_history(self.key)
        series = QLineSeries()
        for ts, price in hist:
            series.append(QDateTime(datetime.fromisoformat(ts)).toMSecsSinceEpoch(), price)
        chart = QChart()
        chart.addSeries(series)
        chart.legend().hide()
        chart.setTitle(f"{len(hist)} precio(s) registrados · visto por primera vez {self.row['first_seen'][:10]}")
        ax = QDateTimeAxis()
        ax.setFormat("dd/MM/yy")
        ay = QValueAxis()
        ay.setLabelFormat("%.0f")
        if hist:
            prices = [p for _, p in hist]
            lo, hi = min(prices), max(prices)
            pad = max((hi - lo) * 0.1, hi * 0.02)
            ay.setRange(lo - pad, hi + pad)
        chart.addAxis(ax, Qt.AlignBottom)
        chart.addAxis(ay, Qt.AlignLeft)
        series.attachAxis(ax)
        series.attachAxis(ay)
        view = QChartView(chart)
        view.setRenderHint(QPainter.Antialiasing)
        return view

    # ---------- IA ----------
    def _ai_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.ai_btn = QPushButton("Analizar con Claude")
        self.ai_btn.clicked.connect(self._run_ai)
        self.ai_view = QTextBrowser()
        lay.addWidget(self.ai_btn)
        lay.addWidget(self.ai_view)
        if self.row["ai_analysis"]:
            self._show_ai(json.loads(self.row["ai_analysis"]))
            self.ai_btn.setText("Volver a analizar con Claude")
        else:
            self.ai_view.setHtml("<p>Pulsa el botón para que Claude evalúe el anuncio con los datos de "
                                 "mercado rastreados.</p>")
        return w

    def _run_ai(self) -> None:
        self.ai_btn.setEnabled(False)
        self.ai_view.setHtml("<p>Analizando…</p>")
        worker = Worker(lambda: ai.analyze_listing(self.db, self.key, self.settings))
        worker.signals.finished.connect(self._show_ai)
        worker.signals.error.connect(lambda e: self.ai_view.setHtml(f"<p style='color:#cf222e'>{e}</p>"))
        worker.signals.finished.connect(lambda _: self.ai_btn.setEnabled(True))
        worker.signals.error.connect(lambda _: self.ai_btn.setEnabled(True))
        self._worker = worker
        QThreadPool.globalInstance().start(worker)

    def _show_ai(self, a: dict) -> None:
        def ul(items):
            return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else "<p>—</p>"
        offer = eur(a.get("suggested_offer_eur")) if a.get("suggested_offer_eur") else "—"
        self.ai_view.setHtml(
            f"<h2>{a['score']}/100 · {a['verdict'].upper()}</h2><p>{a['summary']}</p>"
            f"<p><b>Estrategia:</b> {a['strategy']}<br><b>Oferta sugerida:</b> {offer}</p>"
            f"<h3>A favor</h3>{ul(a['pros'])}<h3>En contra</h3>{ul(a['cons'])}"
            f"<h3>Señales de alerta</h3>{ul(a['red_flags'])}"
            f"<h3>Preguntas para el vendedor</h3>{ul(a['questions_for_seller'])}")
