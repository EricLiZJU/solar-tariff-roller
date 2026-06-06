"""Calculation services."""

from solar_tariff_roller.services.calc.cashflow import (
    build_cashflow_result,
    build_project_irr_for_discounted_tariff_from_month,
)
from solar_tariff_roller.services.calc.engine import run_calculation
from solar_tariff_roller.services.calc.generation import (
    calculate_total_degradation_pct,
    estimate_initial_generation_10k_kwh,
    project_generation_for_year,
)
from solar_tariff_roller.services.calc.reconciliation import build_cashflow_reconciliation
from solar_tariff_roller.services.calc.sensitivity import (
    analyze_sensitivity,
    generate_sensitivity_values,
)

__all__ = [
    "build_cashflow_result",
    "build_project_irr_for_discounted_tariff_from_month",
    "build_cashflow_reconciliation",
    "analyze_sensitivity",
    "calculate_total_degradation_pct",
    "estimate_initial_generation_10k_kwh",
    "generate_sensitivity_values",
    "project_generation_for_year",
    "run_calculation",
]
