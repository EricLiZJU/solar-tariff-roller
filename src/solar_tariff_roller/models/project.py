"""Project-related domain models."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProjectProfile:
    """Core project attributes for tariff calculation."""

    project_name: str
    station_name: str | None = None
    region: str | None = None
    city: str | None = None
    district: str | None = None
    grid_connection_date: str | None = None
    operation_years: int = 25
    capacity_mwp: float = 0.0


@dataclass(slots=True)
class GenerationParams:
    """Generation-related assumptions."""

    annual_sun_hours: float
    performance_ratio: float
    first_year_degradation_pct: float = 2.5
    annual_degradation_pct: float = 0.6


@dataclass(slots=True)
class ConsumptionParams:
    """Consumption and export assumptions."""

    self_consumption_ratio: float
    monthly_self_consumption_ratios: list[float] = field(default_factory=list)
    feasibility_self_consumption_ratio: float | None = None


@dataclass(slots=True)
class TariffParams:
    """Tariff and subsidy assumptions."""

    feed_in_tariff: float
    consumer_tariff: float
    consumer_discount_rate: float
    national_subsidy: float = 0.0
    provincial_subsidy: float = 0.0
    local_subsidy: float = 0.0


@dataclass(slots=True)
class CostParams:
    """Investment and O&M assumptions."""

    capex_per_watt: float
    total_investment_10k_cny: float
    annual_rent_10k_cny: float = 0.0
    annual_om_10k_cny: float = 0.0
    annual_insurance_10k_cny: float = 0.0
    replacement_costs_10k_cny_by_year: dict[int, float] = field(default_factory=dict)


@dataclass(slots=True)
class TaxParams:
    """Tax assumptions used in cashflow calculation."""

    output_vat_rate: float = 0.13
    input_vat_rate: float = 0.06
    surcharge_rate: float = 0.12
    capex_input_vat_primary_rate: float = 0.13
    capex_input_vat_secondary_rate: float = 0.09
    capex_input_vat_primary_ratio: float = 0.7
    capex_input_vat_secondary_ratio: float = 0.3


@dataclass(slots=True)
class FinanceParams:
    """Financial target assumptions."""

    discount_rate: float = 0.06
    target_irr: float | None = None


@dataclass(slots=True)
class MonthlyGenerationRecord:
    """Monthly operating record imported from historical station sheets."""

    period_label: str
    generation_10k_kwh: float | None = None
    self_consumed_10k_kwh: float | None = None
    exported_10k_kwh: float | None = None
    self_consumption_ratio: float | None = None


@dataclass(slots=True)
class CalculationContext:
    """Fully assembled input context for calculations."""

    project: ProjectProfile
    generation: GenerationParams
    consumption: ConsumptionParams
    tariff: TariffParams
    cost: CostParams
    tax: TaxParams
    finance: FinanceParams
    monthly_records: list[MonthlyGenerationRecord] = field(default_factory=list)
