"""Target IRR solver services."""

from solar_tariff_roller.services.solver.target_irr import (
    TargetIrrSolveResult,
    solve_tariff_by_target_irr,
)

__all__ = [
    "TargetIrrSolveResult",
    "solve_tariff_by_target_irr",
]
