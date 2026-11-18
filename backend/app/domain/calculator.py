"""Price estimate formula (pure, data-driven).

price_from = ceil100( base(work_type) × k(brand) × k(vehicle_type) × (1 + urgent%) + onsite_fee )
All numbers are demo values from seeds and can be edited in the admin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PricingRules:
    urgent_surcharge_pct: int = 20
    onsite_fee: int = 3000
    round_to: int = 100
    currency: str = "RUB"
    disclaimer: str = "Цены условные. Точную стоимость мастер назовёт после диагностики."


@dataclass(frozen=True)
class EstimateInput:
    work_type_title: str
    base_price: int
    brand_title: str
    brand_coefficient: float
    vehicle_type_title: str | None
    vehicle_type_coefficient: float
    urgent: bool
    onsite: bool
    onsite_included: bool  # work type is itself an onsite service (dispatch, towing)


@dataclass(frozen=True)
class BreakdownLine:
    label: str
    amount: int


@dataclass(frozen=True)
class EstimateResult:
    price_from: int
    breakdown: list[BreakdownLine]
    currency: str
    disclaimer: str


def _round_up(value: float, step: int) -> int:
    return int(math.ceil(value / step) * step)


def estimate(data: EstimateInput, rules: PricingRules) -> EstimateResult:
    """Compute the "from N ₽" price and an itemised breakdown that sums to it."""
    base = data.base_price
    lines = [BreakdownLine(f"{data.work_type_title} — базовая стоимость", base)]

    adjusted = base * data.brand_coefficient * data.vehicle_type_coefficient
    coef_delta = round(adjusted - base)
    if coef_delta:
        parts = [f"марка {data.brand_title} ×{data.brand_coefficient:g}"]
        if data.vehicle_type_title and data.vehicle_type_coefficient != 1:
            parts.append(f"{data.vehicle_type_title.lower()} ×{data.vehicle_type_coefficient:g}")
        lines.append(BreakdownLine("Коэффициент: " + ", ".join(parts), coef_delta))

    total = adjusted
    if data.urgent and rules.urgent_surcharge_pct:
        urgent_amount = adjusted * rules.urgent_surcharge_pct / 100
        lines.append(BreakdownLine(f"Срочность +{rules.urgent_surcharge_pct}%", round(urgent_amount)))
        total += urgent_amount
    if data.onsite and not data.onsite_included and rules.onsite_fee:
        lines.append(BreakdownLine("Выезд мастера", rules.onsite_fee))
        total += rules.onsite_fee

    price_from = _round_up(total, rules.round_to)
    rounding = price_from - sum(line.amount for line in lines)
    if rounding:
        lines.append(BreakdownLine("Округление", rounding))
    return EstimateResult(price_from, lines, rules.currency, rules.disclaimer)
