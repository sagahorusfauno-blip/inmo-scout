"""Diálogo de búsqueda guardada y pestaña de ajustes."""
from __future__ import annotations

from dataclasses import fields

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSpinBox, QWidget)

from ..config import Settings
from ..models import Search
from ..scrapers import SCRAPERS


class SearchDialog(QDialog):
    def __init__(self, search: Search | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Búsqueda")
        self.search = search or Search(None, "", "pisos", "venta", "")
        s = self.search
        form = QFormLayout(self)

        self.name = QLineEdit(s.name)
        self.source = QComboBox()
        for key, cls in SCRAPERS.items():
            self.source.addItem(cls.label, key)
        self.source.setCurrentIndex(max(0, self.source.findData(s.source)))
        self.operation = QComboBox()
        self.operation.addItems(["venta", "alquiler"])
        self.operation.setCurrentText(s.operation)
        self.location = QLineEdit(s.location)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.source.currentIndexChanged.connect(self._update_help)
        self._update_help()

        self.max_price = QDoubleSpinBox()
        self.max_price.setRange(0, 50_000_000)
        self.max_price.setSingleStep(10_000)
        self.max_price.setSpecialValueText("sin límite")
        self.max_price.setValue(s.max_price or 0)
        self.min_size = QSpinBox()
        self.min_size.setRange(0, 10_000)
        self.min_size.setSpecialValueText("sin mínimo")
        self.min_size.setValue(int(s.min_size or 0))
        self.min_rooms = QSpinBox()
        self.min_rooms.setRange(0, 20)
        self.min_rooms.setSpecialValueText("sin mínimo")
        self.min_rooms.setValue(s.min_rooms or 0)
        self.max_pages = QSpinBox()
        self.max_pages.setRange(1, 50)
        self.max_pages.setValue(s.max_pages)
        self.enabled = QCheckBox("Activa")
        self.enabled.setChecked(s.enabled)

        form.addRow("Nombre", self.name)
        form.addRow("Portal", self.source)
        form.addRow("Operación", self.operation)
        form.addRow("Ubicación", self.location)
        form.addRow("", self.help)
        form.addRow("Precio máximo", self.max_price)
        form.addRow("Superficie mínima (m²)", self.min_size)
        form.addRow("Habitaciones mínimas", self.min_rooms)
        form.addRow("Páginas por pasada", self.max_pages)
        form.addRow(self.enabled)
        form.addRow(QLabel("Consejo: crea también una búsqueda de <b>alquiler</b> en la misma zona; "
                           "se usa para estimar la renta y la rentabilidad de los pisos en venta."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _update_help(self) -> None:
        cls = SCRAPERS[self.source.currentData()]
        self.help.setText(f"<small>{cls.location_help}</small>")

    def _accept(self) -> None:
        if not self.location.text().strip():
            self.location.setFocus()
            return
        s = self.search
        s.name = self.name.text().strip() or self.location.text().strip()
        s.source = self.source.currentData()
        s.operation = self.operation.currentText()
        s.location = self.location.text().strip()
        s.max_price = self.max_price.value() or None
        s.min_size = self.min_size.value() or None
        s.min_rooms = self.min_rooms.value() or None
        s.max_pages = self.max_pages.value()
        s.enabled = self.enabled.isChecked()
        self.accept()


LABELS = {
    "crawl_interval_min": ("Rastrear cada (min)", "Rastreo"),
    "request_delay_s": ("Pausa entre peticiones (s)", "Rastreo"),
    "user_agent": ("User-Agent", "Rastreo"),
    "geocode": ("Geolocalizar anuncios (OpenStreetMap)", "Rastreo"),
    "down_payment_pct": ("Entrada (%)", "Financiación"),
    "purchase_costs_pct": ("Gastos de compra (%)", "Financiación"),
    "mortgage_rate_pct": ("Interés hipoteca (%)", "Financiación"),
    "mortgage_years": ("Años hipoteca", "Financiación"),
    "vacancy_pct": ("Vacío (%)", "Financiación"),
    "opex_pct_of_rent": ("Gastos sobre alquiler (%)", "Financiación"),
    "deal_discount_pct": ("Chollo si está X% bajo la mediana", "Alertas"),
    "min_gross_yield_pct": ("Chollo si rentabilidad bruta ≥ (%)", "Alertas"),
    "min_comparables": ("Comparables mínimos", "Alertas"),
    "anthropic_api_key": ("API key de Anthropic", "IA"),
    "ai_model": ("Modelo", "IA"),
    "idealista_api_key": ("Idealista API key", "Idealista"),
    "idealista_api_secret": ("Idealista API secret", "Idealista"),
}
SECRETS = {"anthropic_api_key", "idealista_api_secret"}


class SettingsTab(QScrollArea):
    def __init__(self, settings: Settings, on_saved, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.on_saved = on_saved
        self.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        self.editors = {}
        section = None
        for f in fields(Settings):
            label, sec = LABELS[f.name]
            if sec != section:
                form.addRow(QLabel(f"<h3>{sec}</h3>"))
                section = sec
            val = getattr(settings, f.name)
            if isinstance(val, bool):
                ed = QCheckBox()
                ed.setChecked(val)
            elif isinstance(val, int):
                ed = QSpinBox()
                ed.setRange(0, 100_000)
                ed.setValue(val)
            elif isinstance(val, float):
                ed = QDoubleSpinBox()
                ed.setRange(0, 1000)
                ed.setDecimals(2)
                ed.setValue(val)
            else:
                ed = QLineEdit(val)
                if f.name in SECRETS:
                    ed.setEchoMode(QLineEdit.Password)
            self.editors[f.name] = ed
            form.addRow(label, ed)
        save = QPushButton("Guardar ajustes")
        save.clicked.connect(self._save)
        form.addRow(save)
        self.setWidget(inner)

    def _save(self) -> None:
        for name, ed in self.editors.items():
            if isinstance(ed, QCheckBox):
                v = ed.isChecked()
            elif isinstance(ed, (QSpinBox, QDoubleSpinBox)):
                v = ed.value()
            else:
                v = ed.text().strip()
            setattr(self.settings, name, v)
        self.settings.save()
        self.on_saved()

