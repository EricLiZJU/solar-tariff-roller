"""Sensitivity analysis helpers for the pricing engine."""

from __future__ import annotations

from decimal import Decimal

from solar_tariff_roller.models.results import SensitivityAnalysisResult, SensitivityPoint
from solar_tariff_roller.schemas.input import CalculationInput
from solar_tariff_roller.services.calc.cashflow import build_cashflow_result


def analyze_sensitivity(
    payload: CalculationInput,
    parameter_name: str,
    values: list[float],
) -> SensitivityAnalysisResult:
    """Run a one-variable sensitivity analysis across the provided values."""

    points: list[SensitivityPoint] = []
    for value in values:
        scenario_payload = payload.model_copy(deep=True)
        _set_nested_value(scenario_payload, parameter_name, value)
        result = build_cashflow_result(scenario_payload)
        points.append(
            SensitivityPoint(
                parameter_name=parameter_name,
                parameter_value=round(float(value), 6),
                project_npv_10k_cny=result.project_npv_10k_cny,
                project_irr=result.project_irr,
                cumulative_cashflow_10k_cny=result.cumulative_cashflow_10k_cny,
                discounted_consumer_tariff=result.discounted_consumer_tariff,
            )
        )

    return SensitivityAnalysisResult(parameter_name=parameter_name, points=points)


def generate_sensitivity_values(start: float, stop: float, step: float) -> list[float]:
    """Generate stable sensitivity analysis points, inclusive of the stop value when aligned."""

    if step <= 0:
        raise ValueError("step must be greater than 0")
    if stop < start:
        raise ValueError("stop must be greater than or equal to start")

    start_decimal = Decimal(str(start))
    stop_decimal = Decimal(str(stop))
    step_decimal = Decimal(str(step))

    values: list[float] = []
    current = start_decimal
    while current <= stop_decimal + Decimal("1e-12"):
        values.append(float(current))
        current += step_decimal

    return values


def _set_nested_value(payload: CalculationInput, parameter_name: str, value: float) -> None:
    """Set a dotted-path field on the nested input model."""

    path = parameter_name.split(".")
    if len(path) != 2:
        raise ValueError("parameter_name must use the format '<section>.<field>'")

    section_name, field_name = path
    section = getattr(payload, section_name, None)
    if section is None:
        raise ValueError(f"Unknown section: {section_name}")
    if not hasattr(section, field_name):
        raise ValueError(f"Unknown field: {parameter_name}")

    setattr(section, field_name, value)
