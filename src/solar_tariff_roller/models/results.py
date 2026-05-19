"""Calculation result models."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class AnnualProjection:
    """One operating year's generation, revenue, tax, and cashflow result."""

    year: int
    degradation_pct: float
    generation_10k_kwh: float
    self_consumed_10k_kwh: float
    exported_10k_kwh: float
    self_consumption_revenue_10k_cny: float
    feed_in_revenue_10k_cny: float
    subsidy_revenue_10k_cny: float
    gross_revenue_10k_cny: float
    revenue_excluding_vat_10k_cny: float
    construction_cost_10k_cny: float
    annual_cost_10k_cny: float
    annual_insurance_10k_cny: float
    annual_om_and_rent_10k_cny: float
    input_vat_10k_cny: float
    output_vat_10k_cny: float
    vat_payable_10k_cny: float
    vat_credit_carry_10k_cny: float
    surcharge_tax_10k_cny: float
    net_cashflow_10k_cny: float
    present_value_factor: float
    discounted_cashflow_10k_cny: float
    cumulative_discounted_cashflow_10k_cny: float
    cumulative_cashflow_10k_cny: float


@dataclass(slots=True)
class ProjectCashflowResult:
    """Full project-level cashflow output."""

    initial_generation_10k_kwh: float
    discounted_consumer_tariff: float
    annual_projections: list[AnnualProjection] = field(default_factory=list)
    capex_input_vat_10k_cny: float = 0.0
    initial_outflow_10k_cny: float = 0.0
    project_npv_10k_cny: float = 0.0
    project_irr: float | None = None
    cumulative_cashflow_10k_cny: float = 0.0


@dataclass(slots=True)
class SensitivityPoint:
    """One scenario point in a sensitivity analysis."""

    parameter_name: str
    parameter_value: float
    project_npv_10k_cny: float
    project_irr: float | None
    cumulative_cashflow_10k_cny: float
    discounted_consumer_tariff: float


@dataclass(slots=True)
class SensitivityAnalysisResult:
    """Sensitivity analysis output for one variable."""

    parameter_name: str
    points: list[SensitivityPoint] = field(default_factory=list)
