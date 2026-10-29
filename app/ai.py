"""Análisis de anuncios con Claude: resumen, puntuación y riesgos como JSON validado."""
from __future__ import annotations

from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from . import market
from .config import Settings
from .db import Database

SYSTEM = """Eres un analista de inversión inmobiliaria en España. Evalúas anuncios de \
vivienda como inversión para alquilar o revender. Sé concreto y escéptico: señala lo que el \
anuncio omite (estado, planta, ascensor, ocupación, cargas, certificado energético, derramas). \
Usa los datos de mercado que se te dan; si son pocos comparables, dilo. Responde en español."""


class AiAnalysis(BaseModel):
    score: int = Field(description="Puntuación 0-100 como oportunidad de inversión")
    verdict: Literal["descartar", "vigilar", "visitar", "oferta"]
    summary: str = Field(description="Resumen de 2-3 frases")
    strategy: str = Field(description="Estrategia recomendada: alquiler tradicional, por habitaciones, reforma y venta...")
    pros: list[str]
    cons: list[str]
    red_flags: list[str] = Field(description="Señales de alerta (okupado, nuda propiedad, subasta, sin ascensor...)")
    questions_for_seller: list[str]
    suggested_offer_eur: int | None = Field(description="Oferta razonable en euros, o null si no hay datos")


def _fmt(v, suffix=""):
    return f"{v:,.0f}{suffix}" if isinstance(v, (int, float)) else "desconocido"


def build_prompt(row, val: market.Valuation) -> str:
    m = val.metrics
    lines = [
        f"Anuncio: {row['title']}",
        f"URL: {row['url']}",
        f"Operación: {row['operation']} · Tipo: {row['property_type']}",
        f"Precio: {_fmt(row['price'], ' €')} · Superficie: {_fmt(row['size_m2'], ' m²')} · "
        f"Habitaciones: {row['rooms']} · Baños: {row['bathrooms']}",
        f"Ubicación: {row['zone']}, {row['city']} · {row['address']}",
        f"Descripción del anunciante:\n{row['description'] or '(sin descripción)'}",
        "",
        f"Mercado ({val.scope}): €/m² venta mediano {_fmt(val.sale_m2_median)} "
        f"({val.sale_comparables} comparables)",
    ]
    if val.rent_m2_median:
        lines.append(f"€/m² alquiler mediano {val.rent_m2_median:.1f} ({val.rent_comparables} comparables)")
    else:
        lines.append("Sin datos de alquiler en la zona")
    if val.discount_pct is not None:
        lines.append(f"Descuento frente a la mediana: {val.discount_pct:.1f}%")
    if m:
        lines.append(
            f"Alquiler estimado {_fmt(val.estimated_rent, ' €/mes')}; rentabilidad bruta "
            f"{m.gross_yield_pct:.1f}%, neta {m.net_yield_pct:.1f}%, cash flow {m.monthly_cash_flow:,.0f} €/mes, "
            f"cash-on-cash {m.cash_on_cash_pct:.1f}%")
    lines.append("\nEvalúa esta oportunidad.")
    return "\n".join(lines)


def analyze_listing(db: Database, key: str, settings: Settings) -> dict:
    if not settings.anthropic_api_key:
        raise RuntimeError("Añade tu API key de Anthropic en Ajustes para usar el análisis con IA")
    row = db.get_listing(key)
    if row is None:
        raise KeyError(key)
    val = market.value_listing(db, row, settings)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.beta.messages.parse(
        model=settings.ai_model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(row, val)}],
        output_config={"effort": "medium"},
        output_format=AiAnalysis,
        # Si el modelo rechaza la petición, la API la reintenta con un modelo alternativo
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("El modelo ha rechazado analizar este anuncio")
    if response.parsed_output is None:
        raise RuntimeError(f"Respuesta incompleta de la IA (stop_reason={response.stop_reason})")
    result = response.parsed_output.model_dump()
    db.set_ai_analysis(key, result)
    return result
