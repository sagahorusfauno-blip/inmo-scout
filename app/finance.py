"""Cálculos de rentabilidad de una inversión en vivienda para alquilar."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Assumptions:
    down_payment_pct: float = 20.0
    purchase_costs_pct: float = 10.0
    mortgage_rate_pct: float = 3.0
    mortgage_years: int = 25
    vacancy_pct: float = 5.0
    opex_pct_of_rent: float = 20.0
    renovation: float = 0.0

    @classmethod
    def from_settings(cls, s) -> "Assumptions":
        return cls(s.down_payment_pct, s.purchase_costs_pct, s.mortgage_rate_pct,
                   s.mortgage_years, s.vacancy_pct, s.opex_pct_of_rent)


@dataclass
class Result:
    total_investment: float      # precio + gastos de compra + reforma
    cash_needed: float           # entrada + gastos + reforma
    loan: float
    monthly_mortgage: float
    annual_rent: float
    annual_net_income: float     # NOI: alquiler - vacío - gastos (antes de hipoteca)
    gross_yield_pct: float       # alquiler anual / precio
    net_yield_pct: float         # NOI / inversión total (cap rate sobre coste)
    monthly_cash_flow: float     # tras hipoteca
    cash_on_cash_pct: float      # cash flow anual / dinero aportado
    per_m2: float | None = None


def mortgage_payment(principal: float, annual_rate_pct: float, years: int) -> float:
    """Cuota mensual de un préstamo francés."""
    if principal <= 0 or years <= 0:
        return 0.0
    r = annual_rate_pct / 100 / 12
    n = years * 12
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def analyze(price: float, monthly_rent: float, a: Assumptions, size_m2: float | None = None) -> Result:
    costs = price * a.purchase_costs_pct / 100
    total = price + costs + a.renovation
    loan = price * (1 - a.down_payment_pct / 100)
    cash = total - loan
    pay = mortgage_payment(loan, a.mortgage_rate_pct, a.mortgage_years)

    annual_rent = monthly_rent * 12
    effective = annual_rent * (1 - a.vacancy_pct / 100)
    noi = effective - annual_rent * a.opex_pct_of_rent / 100
    cash_flow_year = noi - pay * 12

    return Result(
        total_investment=total,
        cash_needed=cash,
        loan=loan,
        monthly_mortgage=pay,
        annual_rent=annual_rent,
        annual_net_income=noi,
        gross_yield_pct=annual_rent / price * 100 if price else 0.0,
        net_yield_pct=noi / total * 100 if total else 0.0,
        monthly_cash_flow=cash_flow_year / 12,
        cash_on_cash_pct=cash_flow_year / cash * 100 if cash > 0 else 0.0,
        per_m2=price / size_m2 if size_m2 else None,
    )
