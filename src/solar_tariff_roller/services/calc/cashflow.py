"""Rolling cashflow calculations."""

from __future__ import annotations

from scipy.optimize import brentq

from solar_tariff_roller.models.results import (
    AnnualProjection,
    MonthlyProjection,
    ProjectCashflowResult,
)
from solar_tariff_roller.schemas.input import CalculationInput
from solar_tariff_roller.services.calc.generation import (
    estimate_initial_generation_10k_kwh,
    project_generation_for_year,
)


def build_cashflow_result(payload: CalculationInput) -> ProjectCashflowResult:
    """Build rolling monthly cashflow and aggregate it back to annual previews."""

    initial_generation = round(estimate_initial_generation_10k_kwh(payload), 4)
    discounted_consumer_tariff = round(payload.discounted_consumer_tariff, 6)
    capex_input_vat = _calc_capex_input_vat(payload)
    initial_outflow = round(payload.cost.total_investment_10k_cny, 4)
    annual_generation = _resolve_annual_generation(payload)
    total_months = payload.project.operation_years * 12
    fixed_revenues = payload.rolling.baseline_monthly_revenues_10k_cny[:total_months]
    historical_months_count = len(fixed_revenues)
    monthly_discount_rate = _annual_to_monthly_rate(payload.finance.discount_rate)
    subsidy_unit = (
        payload.tariff.national_subsidy
        + payload.tariff.provincial_subsidy
        + payload.tariff.local_subsidy
    )

    monthly_revenues = _build_monthly_revenues(
        payload=payload,
        annual_generation=annual_generation,
        fixed_revenues=fixed_revenues,
        subsidy_unit=subsidy_unit,
        total_months=total_months,
    )

    monthly_rows: list[MonthlyProjection] = []
    monthly_cashflows = [-initial_outflow]
    vat_credit_carry = -capex_input_vat
    cumulative_cashflow = -initial_outflow

    for month_index in range(1, total_months + 1):
        operating_year = ((month_index - 1) // 12) + 1
        month_in_year = ((month_index - 1) % 12) + 1
        annual_generation_value = annual_generation[operating_year - 1]
        generation_10k_kwh = round(annual_generation_value / 12, 4)
        self_consumed_10k_kwh = round(generation_10k_kwh * payload.consumption.self_consumption_ratio, 4)
        exported_10k_kwh = round(generation_10k_kwh - self_consumed_10k_kwh, 4)

        gross_revenue = round(monthly_revenues[month_index - 1], 8)
        insurance_cost = payload.cost.annual_insurance_10k_cny if month_in_year == 1 else 0.0
        om_cost = (
            round((payload.cost.annual_rent_10k_cny + payload.cost.annual_om_10k_cny) / 2, 8)
            if month_index % 6 == 1
            else 0.0
        )
        replacement_cost = (
            payload.cost.replacement_costs_10k_cny_by_year.get(operating_year, 0.0)
            if month_in_year == 1
            else 0.0
        )
        total_cost = round(insurance_cost + om_cost + replacement_cost, 8)

        input_vat = _calc_input_vat(total_cost, payload.tax.input_vat_rate) if total_cost > 0 else 0.0
        output_vat = _calc_output_vat(gross_revenue, payload.tax.output_vat_rate) if gross_revenue > 0 else 0.0
        vat_balance = round(output_vat - input_vat + vat_credit_carry, 8)
        vat_payable = round(max(vat_balance, 0.0), 8)
        vat_credit_carry = round(min(vat_balance, 0.0), 8)
        surcharge_tax = round(vat_payable * payload.tax.surcharge_rate, 8) if vat_payable > 0 else 0.0
        net_cashflow = round(gross_revenue - total_cost - vat_payable - surcharge_tax, 8)
        discount_factor = round(1 / ((1 + monthly_discount_rate) ** month_index), 8)
        discounted_cashflow = round(net_cashflow * discount_factor, 8)
        cumulative_cashflow = round(cumulative_cashflow + net_cashflow, 8)
        annualized_revenue_basis = round(annual_generation_value * payload.consumption.self_consumption_ratio * discounted_consumer_tariff
            + annual_generation_value * (1 - payload.consumption.self_consumption_ratio) * payload.tariff.feed_in_tariff
            + annual_generation_value * subsidy_unit, 8)

        monthly_rows.append(
            MonthlyProjection(
                month_index=month_index,
                operating_year=operating_year,
                month_in_year=month_in_year,
                period_type="historical" if month_index <= historical_months_count else "projected",
                generation_10k_kwh=generation_10k_kwh,
                self_consumed_10k_kwh=self_consumed_10k_kwh,
                exported_10k_kwh=exported_10k_kwh,
                gross_revenue_10k_cny=gross_revenue,
                annualized_revenue_basis_10k_cny=annualized_revenue_basis,
                insurance_cost_10k_cny=insurance_cost,
                om_cost_10k_cny=om_cost,
                replacement_cost_10k_cny=replacement_cost,
                total_cost_10k_cny=total_cost,
                input_vat_10k_cny=input_vat,
                output_vat_10k_cny=output_vat,
                vat_balance_10k_cny=vat_balance,
                vat_payable_10k_cny=vat_payable,
                vat_credit_carry_10k_cny=vat_credit_carry,
                surcharge_tax_10k_cny=surcharge_tax,
                net_cashflow_10k_cny=net_cashflow,
                discount_factor=discount_factor,
                discounted_cashflow_10k_cny=discounted_cashflow,
                cumulative_cashflow_10k_cny=cumulative_cashflow,
            )
        )
        monthly_cashflows.append(net_cashflow)

    annual_rows = _aggregate_annual_rows(payload, monthly_rows, annual_generation, subsidy_unit)
    npv = round(_calculate_monthly_npv(monthly_cashflows, monthly_discount_rate), 4)
    monthly_irr = _calculate_monthly_irr(monthly_cashflows)
    project_irr = _annualize_irr(monthly_irr, payload.rolling.irr_annualization_mode)

    return ProjectCashflowResult(
        initial_generation_10k_kwh=initial_generation,
        discounted_consumer_tariff=discounted_consumer_tariff,
        monthly_irr=monthly_irr,
        historical_months_count=historical_months_count,
        monthly_projections=monthly_rows,
        annual_projections=annual_rows,
        capex_input_vat_10k_cny=capex_input_vat,
        initial_outflow_10k_cny=initial_outflow,
        project_npv_10k_cny=npv,
        project_irr=project_irr,
        cumulative_cashflow_10k_cny=cumulative_cashflow,
    )


def _build_monthly_revenues(
    *,
    payload: CalculationInput,
    annual_generation: list[float],
    fixed_revenues: list[float],
    subsidy_unit: float,
    total_months: int,
) -> list[float]:
    """Build the rolling monthly revenue sequence."""

    monthly_revenues = list(fixed_revenues)
    start_year_index = len(fixed_revenues) // 12

    for year_index in range(start_year_index, payload.project.operation_years):
        generation_10k_kwh = annual_generation[year_index]
        self_consumed_10k_kwh = generation_10k_kwh * payload.consumption.self_consumption_ratio
        exported_10k_kwh = generation_10k_kwh - self_consumed_10k_kwh
        annual_revenue = (
            self_consumed_10k_kwh * payload.discounted_consumer_tariff
            + exported_10k_kwh * payload.tariff.feed_in_tariff
            + generation_10k_kwh * subsidy_unit
        )
        monthly_revenues.extend([round(annual_revenue / 12, 8)] * 12)

    if len(monthly_revenues) < total_months:
        monthly_revenues.extend([0.0] * (total_months - len(monthly_revenues)))
    return monthly_revenues[:total_months]


def _resolve_annual_generation(payload: CalculationInput) -> list[float]:
    """Prefer workbook annual generation forecasts, then fall back to formula projections."""

    if len(payload.rolling.annual_generation_forecast_10k_kwh) >= payload.project.operation_years:
        return [
            round(float(value), 2)
            for value in payload.rolling.annual_generation_forecast_10k_kwh[: payload.project.operation_years]
        ]

    return [
        project_generation_for_year(payload, year)[0]
        for year in range(1, payload.project.operation_years + 1)
    ]


def _aggregate_annual_rows(
    payload: CalculationInput,
    monthly_rows: list[MonthlyProjection],
    annual_generation: list[float],
    subsidy_unit: float,
) -> list[AnnualProjection]:
    """Aggregate rolling monthly rows back to annual previews for UI/export."""

    annual_rows: list[AnnualProjection] = []
    cumulative_discounted_cashflow = -payload.cost.total_investment_10k_cny

    for year in range(1, payload.project.operation_years + 1):
        rows = [row for row in monthly_rows if row.operating_year == year]
        if not rows:
            continue

        generation_10k_kwh = round(sum(row.generation_10k_kwh for row in rows), 4)
        self_consumed_10k_kwh = round(sum(row.self_consumed_10k_kwh for row in rows), 4)
        exported_10k_kwh = round(sum(row.exported_10k_kwh for row in rows), 4)
        gross_revenue = round(sum(row.gross_revenue_10k_cny for row in rows), 4)
        feed_in_revenue = round(exported_10k_kwh * payload.tariff.feed_in_tariff, 2)
        subsidy_revenue = round(generation_10k_kwh * subsidy_unit, 2)
        self_revenue = round(gross_revenue - feed_in_revenue - subsidy_revenue, 2)
        output_vat = round(sum(row.output_vat_10k_cny for row in rows), 4)
        annual_cost = round(sum(row.total_cost_10k_cny for row in rows), 4)
        discounted_cashflow = round(sum(row.discounted_cashflow_10k_cny for row in rows), 4)
        cumulative_discounted_cashflow = round(cumulative_discounted_cashflow + discounted_cashflow, 4)
        _, degradation_pct = project_generation_for_year(payload, year)

        annual_rows.append(
            AnnualProjection(
                year=year,
                degradation_pct=degradation_pct,
                generation_10k_kwh=round(annual_generation[year - 1], 2),
                self_consumed_10k_kwh=self_consumed_10k_kwh,
                exported_10k_kwh=exported_10k_kwh,
                self_consumption_revenue_10k_cny=self_revenue,
                feed_in_revenue_10k_cny=feed_in_revenue,
                subsidy_revenue_10k_cny=subsidy_revenue,
                gross_revenue_10k_cny=gross_revenue,
                revenue_excluding_vat_10k_cny=round(gross_revenue - output_vat, 2),
                construction_cost_10k_cny=round(sum(row.replacement_cost_10k_cny for row in rows), 4),
                annual_cost_10k_cny=annual_cost,
                annual_insurance_10k_cny=round(sum(row.insurance_cost_10k_cny for row in rows), 4),
                annual_om_and_rent_10k_cny=round(sum(row.om_cost_10k_cny for row in rows), 4),
                input_vat_10k_cny=round(sum(row.input_vat_10k_cny for row in rows), 4),
                output_vat_10k_cny=output_vat,
                vat_payable_10k_cny=round(sum(row.vat_payable_10k_cny for row in rows), 4),
                vat_credit_carry_10k_cny=rows[-1].vat_credit_carry_10k_cny,
                surcharge_tax_10k_cny=round(sum(row.surcharge_tax_10k_cny for row in rows), 4),
                net_cashflow_10k_cny=round(sum(row.net_cashflow_10k_cny for row in rows), 4),
                present_value_factor=round(1 / ((1 + payload.finance.discount_rate) ** year), 4),
                discounted_cashflow_10k_cny=discounted_cashflow,
                cumulative_discounted_cashflow_10k_cny=cumulative_discounted_cashflow,
                cumulative_cashflow_10k_cny=rows[-1].cumulative_cashflow_10k_cny,
            )
        )

    return annual_rows


def _annual_to_monthly_rate(rate: float) -> float:
    """Convert an annual rate to an equivalent monthly rate."""

    if rate == 0:
        return 0.0
    return (1 + rate) ** (1 / 12) - 1


def _annualize_irr(monthly_irr: float | None, mode: str) -> float | None:
    """Annualize a monthly IRR for reporting and solving."""

    if monthly_irr is None:
        return None
    if mode == "simple":
        return round(float(monthly_irr * 12), 6)
    return round(float((1 + monthly_irr) ** 12 - 1), 6)


def _calc_output_vat(gross_revenue_10k_cny: float, rate: float) -> float:
    """Calculate output VAT from tax-inclusive revenue."""

    return round(gross_revenue_10k_cny / (1 + rate) * rate, 2)


def _calc_input_vat(cost_10k_cny: float, rate: float) -> float:
    """Calculate input VAT from tax-inclusive cost."""

    return round(cost_10k_cny / (1 + rate) * rate, 2)


def _calc_capex_input_vat(payload: CalculationInput) -> float:
    """Calculate capex input VAT using the mixed-rate rule."""

    total_investment = payload.cost.total_investment_10k_cny
    primary = (
        total_investment
        * payload.tax.capex_input_vat_primary_ratio
        / (1 + payload.tax.capex_input_vat_primary_rate)
        * payload.tax.capex_input_vat_primary_rate
    )
    secondary = (
        total_investment
        * payload.tax.capex_input_vat_secondary_ratio
        / (1 + payload.tax.capex_input_vat_secondary_rate)
        * payload.tax.capex_input_vat_secondary_rate
    )
    return round(primary + secondary, 2)


def _calculate_monthly_npv(cashflows: list[float], monthly_rate: float) -> float:
    """Calculate monthly NPV with month-0 cashflow included."""

    return sum(cashflow / ((1 + monthly_rate) ** month) for month, cashflow in enumerate(cashflows))


def _calculate_monthly_irr(cashflows: list[float]) -> float | None:
    """Calculate monthly IRR from rolling cashflows."""

    if not any(cashflow < 0 for cashflow in cashflows) or not any(cashflow > 0 for cashflow in cashflows):
        return None

    def npv(rate: float) -> float:
        return _calculate_monthly_npv(cashflows, rate)

    try:
        irr = brentq(npv, -0.5, 1.0)
    except ValueError:
        return None

    return float(irr)
