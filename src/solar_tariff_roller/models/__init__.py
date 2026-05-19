"""Domain models."""

from solar_tariff_roller.models.project import (
    CalculationContext,
    ConsumptionParams,
    CostParams,
    FinanceParams,
    GenerationParams,
    MonthlyGenerationRecord,
    ProjectProfile,
    TariffParams,
    TaxParams,
)
from solar_tariff_roller.models.results import (
    AnnualProjection,
    ProjectCashflowResult,
    SensitivityAnalysisResult,
    SensitivityPoint,
)

__all__ = [
    "AnnualProjection",
    "CalculationContext",
    "ConsumptionParams",
    "CostParams",
    "FinanceParams",
    "GenerationParams",
    "MonthlyGenerationRecord",
    "ProjectProfile",
    "ProjectCashflowResult",
    "SensitivityAnalysisResult",
    "SensitivityPoint",
    "TariffParams",
    "TaxParams",
]
