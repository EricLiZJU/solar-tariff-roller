"""Target IRR solver services."""

from solar_tariff_roller.services.solver.target_irr import (
    TargetIrrSolveResult,
    solve_tariff_by_target_irr,
)
from solar_tariff_roller.services.solver.start_month import (
    TariffStartMonthSolveResult,
    solve_latest_start_month_for_tariff,
)

__all__ = [
    "TariffStartMonthSolveResult",
    "TargetIrrSolveResult",
    "solve_latest_start_month_for_tariff",
    "solve_tariff_by_target_irr",
]
