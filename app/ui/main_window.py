"""Ventana principal: oportunidades, mapa, búsquedas, alertas y ajustes."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QStyle, QSystemTrayIcon, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import market
from ..config import Settings
from ..crawler import Crawler, CrawlReport
from ..db import Database
from .detail import DetailDialog, eur
from .dialogs import SearchDialog, SettingsTab
from .map_view import MapView
from .workers import Worker

KEY_ROLE = Qt.UserRole + 1


class NumItem(QTableWidgetItem):
    """Celda que ordena por valor numérico y muestra texto formateado."""

    def __init__(self, value, text: str | None = None):
        super().__init__(text if text is not None else ("—" if value is None else str(value)))
        self.value = value if value is not None else float("-inf")
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        if isinstance(other, NumItem):
            return self.value < other.value
        return super().__lt__(other)


def pct(v) -> str:
    return "—" if v is None else f"{v:.1f} %"


COLUMNS = ["★", "Título", "Zona", "Ciudad", "Precio", "m²", "€/m²", "Bajo mediana",
           "Alquiler est.", "Rent. bruta", "Cash flow/mes", "IA", "Portal", "Visto"]


class MainWindow(QMainWindow):
    def __init__(self, db: Database, settings: Settings):
        super().__init__()
        self.db, self.settings = db, settings
        self.pool = QThreadPool.globalInstance()
        self.crawl_worker: Worker | None = None
        self.setWindowTitle("InmoScout — inversión inmobiliaria")
        self.resize(1400, 820)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._listings_tab(), "Oportunidades")
        self.map = MapView()
        self.tabs.addTab(self.map, "Mapa")
        self.tabs.addTab(self._searches_tab(), "Búsquedas")
        self.tabs.addTab(self._alerts_tab(), "Alertas")
        self.tabs.addTab(SettingsTab(settings, self._settings_saved), "Ajustes")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)

        tb = self.addToolBar("Principal")
        self.crawl_action = QAction("⟳ Rastrear ahora", self)
        self.crawl_action.triggered.connect(self.start_crawl)
        tb.addAction(self.crawl_action)
        self.stop_action = QAction("■ Detener", self)
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(lambda: self.crawl_worker and self.crawl_worker.cancel())
        tb.addAction(self.stop_action)

        icon = self.style().standardIcon(QStyle.SP_DirHomeIcon)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("InmoScout")
        self.tray.activated.connect(lambda *_: (self.showNormal(), self.activateWindow()))
        menu = QMenu(self)
        menu.addAction("Abrir InmoScout", lambda: (self.showNormal(), self.activateWindow()))
        menu.addAction("Rastrear ahora", self.start_crawl)
        menu.addSeparator()
        menu.addAction("Salir", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.start_crawl)
        self._settings_saved(initial=True)

        self.refresh_listings()
        self.refresh_searches()
        self.refresh_alerts()

    # ================= Oportunidades =================
    def _listings_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.op_combo = QComboBox()
        self.op_combo.addItems(["venta", "alquiler"])
        self.op_combo.currentTextChanged.connect(self.refresh_listings)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filtrar por texto (zona, ciudad, título)…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.only_deals = QCheckBox("Solo bajo mediana")
        self.only_deals.toggled.connect(self._apply_filter)
        self.only_favs = QCheckBox("Solo favoritos")
        self.only_favs.toggled.connect(self._apply_filter)
        self.count_lbl = QLabel()
        bar.addWidget(QLabel("Operación:"))
        bar.addWidget(self.op_combo)
        bar.addWidget(self.filter_edit, 1)
        bar.addWidget(self.only_deals)
        bar.addWidget(self.only_favs)
        bar.addWidget(self.count_lbl)
        v.addLayout(bar)

        t = self.table = QTableWidget(0, len(COLUMNS))
        t.setHorizontalHeaderLabels(COLUMNS)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSortingEnabled(True)
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.horizontalHeader().setSortIndicator(COLUMNS.index("Bajo mediana"), Qt.DescendingOrder)
        t.doubleClicked.connect(self._open_detail)
        v.addWidget(t)
        v.addWidget(QLabel("<small>Doble clic en un anuncio para ver la calculadora, el histórico y el análisis "
                           "con IA. «Bajo mediana» compara el €/m² con los anuncios rastreados de la misma "
                           "zona.</small>"))
        return w

    def refresh_listings(self) -> None:
        op = self.op_combo.currentText()
        rows = self.db.listings(op)
        cache: dict = {}
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        self._map_points = []
        for i, r in enumerate(rows):
            val = market.value_listing(self.db, r, self.settings, cache)
            m = val.metrics
            ai_score = json.loads(r["ai_analysis"])["score"] if r["ai_analysis"] else None
            pm2 = r["price"] / r["size_m2"] if r["price"] and r["size_m2"] else None
            items = [
                QTableWidgetItem("★" if r["favorite"] else ""),
                QTableWidgetItem(r["title"]),
                QTableWidgetItem(r["zone"]),
                QTableWidgetItem(r["city"]),
                NumItem(r["price"], eur(r["price"])),
                NumItem(r["size_m2"], f"{r['size_m2']:.0f}" if r["size_m2"] else "—"),
                NumItem(pm2, eur(pm2)),
                NumItem(val.discount_pct, pct(val.discount_pct)),
                NumItem(val.estimated_rent, eur(val.estimated_rent)),
                NumItem(m.gross_yield_pct if m else None, pct(m.gross_yield_pct) if m else "—"),
                NumItem(m.monthly_cash_flow if m else None, eur(m.monthly_cash_flow) if m else "—"),
                NumItem(ai_score),
                QTableWidgetItem(r["source"]),
                QTableWidgetItem(r["first_seen"][:10]),
            ]
            items[0].setData(KEY_ROLE, r["key"])
            items[0].setData(KEY_ROLE + 1, (val.discount_pct or 0, bool(r["favorite"])))
            if val.discount_pct is not None and val.discount_pct >= self.settings.deal_discount_pct:
                items[7].setForeground(Qt.darkGreen)
            for c, it in enumerate(items):
                t.setItem(i, c, it)
            if r["lat"] is not None:
                self._map_points.append({"lat": r["lat"], "lon": r["lon"], "title": r["title"],
                                         "price": r["price"], "url": r["url"],
                                         "discount": val.discount_pct, "fav": r["favorite"]})
        t.setSortingEnabled(True)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._apply_filter()
        if self.tabs.currentWidget() is self.map:
            self.map.show_points(self._map_points)

    def _apply_filter(self) -> None:
        text = self.filter_edit.text().lower()
        shown = 0
        for i in range(self.table.rowCount()):
            disc, fav = self.table.item(i, 0).data(KEY_ROLE + 1)
            hay = " ".join(self.table.item(i, c).text().lower() for c in (1, 2, 3))
            visible = (not text or text in hay) and (not self.only_deals.isChecked() or disc > 0) \
                and (not self.only_favs.isChecked() or fav)
            self.table.setRowHidden(i, not visible)
            shown += visible
        self.count_lbl.setText(f"{shown} anuncios")

    def _open_detail(self, index) -> None:
        key = self.table.item(index.row(), 0).data(KEY_ROLE)
        DetailDialog(self.db, self.settings, key, self).exec()
        self.refresh_listings()

    def _tab_changed(self, idx: int) -> None:
        if self.tabs.widget(idx) is self.map:
            self.map.show_points(getattr(self, "_map_points", []))
        elif self.tabs.tabText(idx) == "Alertas":
            self.db.mark_alerts_seen()
            self.refresh_alerts()

    # ================= Búsquedas =================
    def _searches_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        for label, fn in (("Añadir", self._add_search), ("Editar", self._edit_search),
                          ("Eliminar", self._delete_search)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)
        self.search_table = QTableWidget(0, 7)
        self.search_table.setHorizontalHeaderLabels(
            ["Nombre", "Portal", "Operación", "Ubicación", "Precio máx.", "Páginas", "Activa"])
        self.search_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.search_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.search_table.horizontalHeader().setStretchLastSection(True)
        self.search_table.doubleClicked.connect(self._edit_search)
        v.addWidget(self.search_table)
        return w

    def refresh_searches(self) -> None:
        self._searches = self.db.searches()
        t = self.search_table
        t.setRowCount(len(self._searches))
        for i, s in enumerate(self._searches):
            for c, val in enumerate([s.name, s.source, s.operation, s.location, eur(s.max_price),
                                     str(s.max_pages), "sí" if s.enabled else "no"]):
                t.setItem(i, c, QTableWidgetItem(val))
        t.resizeColumnsToContents()

    def _selected_search(self):
        row = self.search_table.currentRow()
        return self._searches[row] if 0 <= row < len(self._searches) else None

    def _add_search(self) -> None:
        d = SearchDialog(parent=self)
        if d.exec():
            self.db.save_search(d.search)
            self.refresh_searches()

    def _edit_search(self, *_) -> None:
        s = self._selected_search()
        if s:
            d = SearchDialog(s, self)
            if d.exec():
                self.db.save_search(d.search)
                self.refresh_searches()

    def _delete_search(self) -> None:
        s = self._selected_search()
        if s and QMessageBox.question(self, "Eliminar", f"¿Eliminar la búsqueda «{s.name}»?") \
                == QMessageBox.Yes:
            self.db.delete_search(s.id)
            self.refresh_searches()

    # ================= Alertas =================
    def _alerts_tab(self) -> QWidget:
        self.alert_table = QTableWidget(0, 4)
        self.alert_table.setHorizontalHeaderLabels(["Fecha", "Tipo", "Anuncio", "Detalle"])
        self.alert_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.alert_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.alert_table.horizontalHeader().setStretchLastSection(True)
        self.alert_table.doubleClicked.connect(self._open_alert)
        return self.alert_table

    def refresh_alerts(self) -> None:
        alerts = self.db.alerts()
        t = self.alert_table
        t.setRowCount(len(alerts))
        unseen = 0
        for i, a in enumerate(alerts):
            row = self.db.get_listing(a["key"])
            title = row["title"] if row else a["key"]
            items = [QTableWidgetItem(a["ts"].replace("T", " ")), QTableWidgetItem(a["kind"]),
                     QTableWidgetItem(title), QTableWidgetItem(a["message"])]
            items[0].setData(KEY_ROLE, a["key"])
            if not a["seen"]:
                unseen += 1
                for it in items:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
            for c, it in enumerate(items):
                t.setItem(i, c, it)
        t.resizeColumnsToContents()
        idx = self.tabs.indexOf(t)
        self.tabs.setTabText(idx, f"Alertas ({unseen})" if unseen else "Alertas")

    def _open_alert(self, index) -> None:
        key = self.alert_table.item(index.row(), 0).data(KEY_ROLE)
        if self.db.get_listing(key):
            DetailDialog(self.db, self.settings, key, self).exec()

    # ================= Rastreo =================
    def start_crawl(self) -> None:
        if self.crawl_worker is not None:
            return
        if not any(s.enabled for s in self.db.searches()):
            if self.sender() is self.crawl_action:
                QMessageBox.information(self, "Sin búsquedas",
                                        "Crea primero una búsqueda en la pestaña «Búsquedas».")
            return
        crawler = Crawler(self.db, self.settings)
        self.crawl_worker = w = Worker(crawler.run, with_progress=True)
        w.signals.progress.connect(lambda msg: self.statusBar().showMessage(msg))
        w.signals.finished.connect(self._crawl_done)
        w.signals.error.connect(self._crawl_error)
        self.crawl_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.pool.start(w)

    def _crawl_finished_common(self) -> None:
        self.crawl_worker = None
        self.crawl_action.setEnabled(True)
        self.stop_action.setEnabled(False)

    def _crawl_done(self, rep: CrawlReport) -> None:
        self._crawl_finished_common()
        msg = f"Rastreo terminado: {rep.new} nuevos, {rep.updated} con cambio de precio"
        if rep.errors:
            msg += f" · {len(rep.errors)} error(es): " + " | ".join(rep.errors)[:300]
        self.statusBar().showMessage(msg)
        if rep.alerts:
            title, text = rep.alerts[0]
            extra = f" (+{len(rep.alerts) - 1} más)" if len(rep.alerts) > 1 else ""
            self.tray.showMessage(f"InmoScout: {len(rep.alerts)} alerta(s)", f"{title}\n{text}{extra}",
                                  QSystemTrayIcon.Information, 10_000)
        self.refresh_listings()
        self.refresh_alerts()

    def _crawl_error(self, err: str) -> None:
        self._crawl_finished_common()
        self.statusBar().showMessage(f"Error en el rastreo: {err}")

    def _settings_saved(self, initial: bool = False) -> None:
        self.timer.start(max(5, self.settings.crawl_interval_min) * 60_000)
        if not initial:
            self.statusBar().showMessage("Ajustes guardados", 4000)
            self.refresh_listings()

    def closeEvent(self, event) -> None:
        # Cerrar la ventana la minimiza a la bandeja para seguir rastreando
        if self.tray.isVisible() and not getattr(self, "_quitting", False):
            self.hide()
            self.tray.showMessage("InmoScout", "Sigue rastreando en segundo plano. "
                                  "Clic derecho en el icono para salir.", QSystemTrayIcon.Information, 4000)
            event.ignore()
        else:
            event.accept()

    def quit(self) -> None:
        self._quitting = True
        if self.crawl_worker:
            self.crawl_worker.cancel()
        QApplication.quit()
