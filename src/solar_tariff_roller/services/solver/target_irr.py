"""Target IRR reverse-solver services."""

from __future__ import annotations

from dataclasses import dataclass

from scipy.optimize import brentq

from solar_tariff_roller.schemas.input import CalculationInput
from solar_tariff_roller.services.calc.cashflow import build_cashflow_result


@dataclass(slots=True)
class TargetIrrSolveResult:
    """Solved tariff result for a target IRR."""

    target_irr: float
    solved_consumer_tariff: float
    solved_discounted_consumer_tariff: float
    solved_npv_10k_cny: float
    solved_project_irr: float | None


def solve_tariff_by_target_irr(
    payload: CalculationInput,
    target_irr: float | None = None,
    lower_bound: float = 0.0,
    upper_bound: float = 5.0,
) -> TargetIrrSolveResult:
    """Solve the consumer tariff required to achieve the target IRR."""

    effective_target_irr = target_irr if target_irr is not None else payload.finance.target_irr
    if effective_target_irr is None:
        raise ValueError("target_irr is required")

    if not 0 <= effective_target_irr <= 1:
        raise ValueError("target_irr must be between 0 and 1")

    solve_payload = payload.model_copy(deep=True)
    solve_payload.finance.discount_rate = effective_target_irr
    solve_payload.finance.target_irr = effective_target_irr

    def objective(consumer_tariff: float) -> float:
        trial_payload = solve_payload.model_copy(deep=True)
        trial_payload.tariff.consumer_tariff = consumer_tariff
        result = build_cashflow_result(trial_payload)
        return result.project_npv_10k_cny

    lower_value = objective(lower_bound)
    upper_value = objective(upper_bound)
    if lower_value == 0:
        solved_tariff = lower_bound
    elif upper_value == 0:
        solved_tariff = upper_bound
    else:
        if lower_value * upper_value > 0:
            raise ValueError(
                "Unable to bracket a solution for the target IRR; adjust the tariff bounds"
            )
        solved_tariff = brentq(objective, lower_bound, upper_bound)

    solved_payload = solve_payload.model_copy(deep=True)
    solved_payload.tariff.consumer_tariff = round(float(solved_tariff), 6)
    solved_result = build_cashflow_result(solved_payload)

    return TargetIrrSolveResult(
        target_irr=effective_target_irr,
        solved_consumer_tariff=round(solved_payload.tariff.consumer_tariff, 6),
        solved_discounted_consumer_tariff=round(solved_payload.discounted_consumer_tariff, 6),
        solved_npv_10k_cny=round(solved_result.project_npv_10k_cny, 6),
        solved_project_irr=solved_result.project_irr,
    )
