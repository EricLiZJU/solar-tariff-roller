"""Solve the latest start month for a fixed discounted self-consumption tariff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from solar_tariff_roller.schemas.input import CalculationInput
from solar_tariff_roller.services.calc.cashflow import (
    _build_actual_month_overrides,
    _resolve_anchor_period,
    build_project_irr_for_discounted_tariff_from_month,
)


@dataclass(slots=True)
class TariffStartMonthSolveResult:
    """Result of solving the latest feasible month to start one fixed tariff."""

    target_irr: float
    discounted_consumer_tariff: float
    earliest_adjustable_month_index: int
    earliest_adjustable_period_label: str | None
    earliest_feasible_start_month_index: int | None
    earliest_feasible_start_period_label: str | None
    latest_feasible_start_month_index: int | None
    latest_feasible_start_period_label: str | None
    solved_project_irr: float | None
    reachable: bool
    message: str


def solve_latest_start_month_for_tariff(
    payload: CalculationInput,
    discounted_consumer_tariff: float,
    target_irr: float | None = None,
) -> TariffStartMonthSolveResult:
    """Find the latest rolling month from which a fixed tariff can still meet target IRR."""

    effective_target_irr = target_irr if target_irr is not None else payload.finance.target_irr
    if effective_target_irr is None:
        raise ValueError("target_irr is required")
    if discounted_consumer_tariff < 0:
        raise ValueError("discounted_consumer_tariff must be >= 0")

    total_months = payload.project.operation_years * 12
    actual_overrides = _build_actual_month_overrides(payload, payload.discounted_consumer_tariff)
    earliest_adjustable_month_index = max(
        payload.rolling.historical_months_count,
        max(actual_overrides.keys(), default=0),
    ) + 1
    if earliest_adjustable_month_index > total_months:
        raise ValueError("No adjustable rolling months remain for this project")

    feasible_months: list[tuple[int, float]] = []
    for month_index in range(earliest_adjustable_month_index, total_months + 1):
        project_irr = build_project_irr_for_discounted_tariff_from_month(
            payload,
            discounted_tariff=discounted_consumer_tariff,
            start_month_index=month_index,
        )
        if project_irr is not None and project_irr >= effective_target_irr:
            feasible_months.append((month_index, project_irr))

    earliest_adjustable_period_label = _format_period_label(payload, earliest_adjustable_month_index)
    earliest_feasible_month_index = feasible_months[0][0] if feasible_months else None
    latest_feasible_month_index = feasible_months[-1][0] if feasible_months else None
    earliest_feasible_period_label = (
        _format_period_label(payload, earliest_feasible_month_index)
        if earliest_feasible_month_index is not None
        else None
    )
    latest_feasible_period_label = (
        _format_period_label(payload, latest_feasible_month_index)
        if latest_feasible_month_index is not None
        else None
    )
    solved_project_irr = feasible_months[0][1] if feasible_months else None

    if not feasible_months:
        message = (
            "固定消纳电价过低，即使从最早可调整月份开始采用，也无法达到目标 IRR。"
        )
    else:
        message = (
            f"达标启用区间为 "
            f"{earliest_feasible_period_label or f'第{earliest_feasible_month_index}个月'} 到 "
            f"{latest_feasible_period_label or f'第{latest_feasible_month_index}个月'}。"
        )

    return TariffStartMonthSolveResult(
        target_irr=effective_target_irr,
        discounted_consumer_tariff=round(discounted_consumer_tariff, 6),
        earliest_adjustable_month_index=earliest_adjustable_month_index,
        earliest_adjustable_period_label=earliest_adjustable_period_label,
        earliest_feasible_start_month_index=earliest_feasible_month_index,
        earliest_feasible_start_period_label=earliest_feasible_period_label,
        latest_feasible_start_month_index=latest_feasible_month_index,
        latest_feasible_start_period_label=latest_feasible_period_label,
        solved_project_irr=solved_project_irr,
        reachable=bool(feasible_months),
        message=message,
    )


def _format_period_label(payload: CalculationInput, month_index: int | None) -> str | None:
    if month_index is None:
        return None
    anchor_period = _resolve_anchor_period(payload)
    if anchor_period is None:
        return None
    year = anchor_period.year + ((anchor_period.month - 1 + month_index - 1) // 12)
    month = ((anchor_period.month - 1 + month_index - 1) % 12) + 1
    period = date(year, month, 1)
    return f"{period.year:04d}-{period.month:02d}"
