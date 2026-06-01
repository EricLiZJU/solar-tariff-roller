"""Normalized input schemas for the pricing engine."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProjectProfileInput(BaseModel):
    """Static project attributes from the feasibility sheet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_name: str = Field(description="项目名称")
    station_name: str | None = Field(default=None, description="电站名称")
    region: str | None = Field(default=None, description="区域")
    city: str | None = Field(default=None, description="地市")
    district: str | None = Field(default=None, description="县区")
    grid_connection_date: str | None = Field(default=None, description="并网时间")
    operation_years: int = Field(default=25, ge=1, le=50, description="运营年限")
    capacity_mwp: float = Field(gt=0, description="装机容量 MWp")


class GenerationParamsInput(BaseModel):
    """Assumptions for annual generation forecast."""

    annual_sun_hours: float = Field(gt=0, description="年日照时间 小时")
    performance_ratio: float = Field(gt=0, le=1, description="综合系数")
    first_year_degradation_pct: float = Field(default=2.5, ge=0, le=100)
    annual_degradation_pct: float = Field(default=0.6, ge=0, le=100)


class ConsumptionParamsInput(BaseModel):
    """Self-consumption and export split assumptions."""

    self_consumption_ratio: float = Field(ge=0, le=1, description="自发自用比例")
    monthly_self_consumption_ratios: list[float] = Field(
        default_factory=list,
        description="按月消纳比例，取值 0 到 1",
    )
    feasibility_self_consumption_ratio: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="可研消纳率",
    )

    @field_validator("monthly_self_consumption_ratios")
    @classmethod
    def validate_monthly_ratios(cls, value: list[float]) -> list[float]:
        if len(value) not in (0, 12):
            raise ValueError("monthly_self_consumption_ratios must contain 12 values")

        for item in value:
            if not 0 <= item <= 1:
                raise ValueError("monthly_self_consumption_ratios values must be between 0 and 1")

        return value


class TariffParamsInput(BaseModel):
    """Tariff assumptions used to split station revenue."""

    feed_in_tariff: float = Field(ge=0, description="余电上网电价 元/kWh")
    consumer_tariff: float = Field(ge=0, description="用户侧综合电价 元/kWh")
    consumer_discount_rate: float = Field(gt=0, le=1, description="自用电折扣系数")
    national_subsidy: float = Field(default=0.0, ge=0, description="国家补贴 元/kWh")
    provincial_subsidy: float = Field(default=0.0, ge=0, description="省级补贴 元/kWh")
    local_subsidy: float = Field(default=0.0, ge=0, description="地方补贴 元/kWh")

    @property
    def discounted_consumer_tariff(self) -> float:
        """Consumer tariff after the agreed discount."""

        return self.consumer_tariff * self.consumer_discount_rate


class CostParamsInput(BaseModel):
    """Capex and recurring operating costs."""

    capex_per_watt: float = Field(ge=0, description="单位造价 元/W")
    total_investment_10k_cny: float = Field(ge=0, description="总投资 万元")
    annual_rent_10k_cny: float = Field(default=0.0, ge=0, description="年租金 万元")
    annual_om_10k_cny: float = Field(default=0.0, ge=0, description="年运维费 万元")
    annual_insurance_10k_cny: float = Field(default=0.0, ge=0, description="年保险费 万元")
    replacement_costs_10k_cny_by_year: dict[int, float] = Field(
        default_factory=dict,
        description="按年份记录的更换或追加建造成本",
    )


class TaxParamsInput(BaseModel):
    """Tax assumptions aligned with the current Excel logic."""

    output_vat_rate: float = Field(default=0.13, ge=0, le=1, description="销项增值税率")
    input_vat_rate: float = Field(default=0.06, ge=0, le=1, description="进项增值税率")
    surcharge_rate: float = Field(default=0.12, ge=0, le=1, description="附加税比例")
    capex_input_vat_primary_rate: float = Field(default=0.13, ge=0, le=1, description="建造成本主税率")
    capex_input_vat_secondary_rate: float = Field(default=0.09, ge=0, le=1, description="建造成本次税率")
    capex_input_vat_primary_ratio: float = Field(default=0.7, ge=0, le=1, description="建造成本主税率占比")
    capex_input_vat_secondary_ratio: float = Field(default=0.3, ge=0, le=1, description="建造成本次税率占比")

    @model_validator(mode="after")
    def validate_capex_vat_ratios(self) -> "TaxParamsInput":
        total_ratio = self.capex_input_vat_primary_ratio + self.capex_input_vat_secondary_ratio
        if abs(total_ratio - 1.0) > 1e-9:
            raise ValueError("capex input VAT ratios must sum to 1")

        return self


class FinanceParamsInput(BaseModel):
    """Financial metric assumptions."""

    discount_rate: float = Field(default=0.06, ge=0, le=1, description="折现率")
    target_irr: float | None = Field(default=None, ge=0, le=1, description="目标 IRR")


class RollingParamsInput(BaseModel):
    """Inputs specific to the rolling tariff workbook logic."""

    baseline_monthly_revenues_10k_cny: list[float] = Field(
        default_factory=list,
        description="滚动表中已固化的历史月度含税收入",
    )
    annual_generation_forecast_10k_kwh: list[float] = Field(
        default_factory=list,
        description="滚动表中按年给出的后续发电量预测",
    )
    irr_annualization_mode: str = Field(
        default="simple",
        description="月度 IRR 年化方式，可选 effective 或 simple",
    )

    @field_validator("irr_annualization_mode")
    @classmethod
    def validate_annualization_mode(cls, value: str) -> str:
        if value not in {"effective", "simple"}:
            raise ValueError("irr_annualization_mode must be 'effective' or 'simple'")
        return value


class MonthlyGenerationRecordInput(BaseModel):
    """Monthly operating values imported from station statistics sheets."""

    model_config = ConfigDict(str_strip_whitespace=True)

    period_label: str = Field(description="月份或期间标识")
    generation_10k_kwh: float | None = Field(default=None, ge=0)
    self_consumed_10k_kwh: float | None = Field(default=None, ge=0)
    exported_10k_kwh: float | None = Field(default=None, ge=0)
    self_consumption_ratio: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_energy_balance(self) -> "MonthlyGenerationRecordInput":
        if (
            self.generation_10k_kwh is not None
            and self.self_consumed_10k_kwh is not None
            and self.exported_10k_kwh is not None
            and self.self_consumed_10k_kwh + self.exported_10k_kwh > self.generation_10k_kwh + 1e-6
        ):
            raise ValueError("self consumed plus exported energy cannot exceed generation")

        return self


class CalculationInput(BaseModel):
    """Normalized input payload shared by parser and calculator."""

    project: ProjectProfileInput
    generation: GenerationParamsInput
    consumption: ConsumptionParamsInput
    tariff: TariffParamsInput
    cost: CostParamsInput
    tax: TaxParamsInput = Field(default_factory=TaxParamsInput)
    finance: FinanceParamsInput = Field(default_factory=FinanceParamsInput)
    rolling: RollingParamsInput = Field(default_factory=RollingParamsInput)
    monthly_records: list[MonthlyGenerationRecordInput] = Field(default_factory=list)

    @property
    def discounted_consumer_tariff(self) -> float:
        """Expose the discounted user-side tariff to calculators."""

        return self.tariff.discounted_consumer_tariff
