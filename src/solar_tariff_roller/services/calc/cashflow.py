"""Rolling cashflow calculations aligned with the customer script."""

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
    """Build rolling cashflow exactly following the customer's monthly script logic."""

    initial_generation = round(estimate_initial_generation_10k_kwh(payload), 4)
    discounted_consumer_tariff = round(payload.discounted_consumer_tariff, 6)
    initial_outflow = round(payload.cost.total_investment_10k_cny, 4)
    capex_input_vat = _calc_capex_input_vat(payload)
    annual_generation = _resolve_annual_generation(payload)
    baseline_revenues = _resolve_baseline_revenues(payload)
    historical_months_count = len(baseline_revenues)
    insurance_per_year = round(payload.cost.total_investment_10k_cny * 0.001, 8)
    om_half = round(payload.cost.annual_om_10k_cny / 2, 8)
    monthly_discount_rate = payload.finance.discount_rate / 12 if payload.finance.discount_rate else 0.0

    annual_self_use = [round(value * payload.consumption.self_consumption_ratio, 8) for value in annual_generation]
    annual_grid_use = [round(value * (1 - payload.consumption.self_consumption_ratio), 8) for value in annual_generation]
    annual_self_revenue = [round(value * discounted_consumer_tariff, 8) for value in annual_self_use]
    annual_grid_revenue = [round(value * payload.tariff.feed_in_tariff, 8) for value in annual_grid_use]
    annual_total_revenue = [
        round(annual_self_revenue[index] + annual_grid_revenue[index], 8)
        for index in range(payload.project.operation_years)
    ]

    monthly_revenues = list(baseline_revenues)
    start_year_index = len(baseline_revenues) // 12
    for year_index in range(start_year_index, payload.project.operation_years):
        monthly_revenue = annual_total_revenue[year_index] / 12
        for _ in range(12):
            monthly_revenues.append(monthly_revenue)
    total_months = payload.project.operation_years * 12
    monthly_revenues = monthly_revenues[:total_months]

    monthly_rows: list[MonthlyProjection] = []
    monthly_cashflows = [-initial_outflow]
    cumulative_cashflow = -initial_outflow
    vat_credit_carry = -capex_input_vat

    for month_index in range(1, total_months + 1):
        operating_year = ((month_index - 1) // 12) + 1
        month_in_year = ((month_index - 1) % 12) + 1
        annual_generation_value = annual_generation[operating_year - 1]
        generation_10k_kwh = round(annual_generation_value / 12, 4)
        self_consumed_10k_kwh = round(generation_10k_kwh * payload.consumption.self_consumption_ratio, 4)
        exported_10k_kwh = round(generation_10k_kwh - self_consumed_10k_kwh, 4)

        gross_revenue = round(monthly_revenues[month_index - 1], 8)
        insurance_cost = insurance_per_year if month_index % 12 == 1 else 0.0
        om_cost = om_half if month_index % 6 == 1 else 0.0
        total_cost = round(insurance_cost + om_cost, 8)

        input_vat = round(total_cost / 1.06 * 0.06, 2) if total_cost > 0 else 0.0
        revenue_excluding_vat = round(gross_revenue / 1.13, 2) if gross_revenue > 0 else 0.0
        output_vat = round(revenue_excluding_vat * 0.13, 2) if revenue_excluding_vat > 0 else 0.0
        vat_balance = round(output_vat - input_vat + vat_credit_carry, 2)
        vat_payable = round(vat_balance, 2) if vat_balance > 0 else 0.0
        vat_credit_carry = round(min(vat_balance, 0.0), 2)
        surcharge_tax = round(vat_balance * 0.12, 2) if vat_balance > 0 else 0.0
        net_cashflow = gross_revenue - total_cost - vat_payable - surcharge_tax
        discount_factor = round(1 / ((1 + monthly_discount_rate) ** month_index), 8) if monthly_discount_rate else 1.0
        discounted_cashflow = round(net_cashflow * discount_factor, 8)
        cumulative_cashflow = round(cumulative_cashflow + net_cashflow, 8)

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
                annualized_revenue_basis_10k_cny=round(annual_total_revenue[operating_year - 1], 8),
                insurance_cost_10k_cny=insurance_cost,
                om_cost_10k_cny=om_cost,
                replacement_cost_10k_cny=0.0,
                total_cost_10k_cny=total_cost,
                input_vat_10k_cny=input_vat,
                output_vat_10k_cny=output_vat,
                vat_balance_10k_cny=vat_balance,
                vat_payable_10k_cny=vat_payable,
                vat_credit_carry_10k_cny=vat_credit_carry,
                surcharge_tax_10k_cny=surcharge_tax,
                net_cashflow_10k_cny=round(net_cashflow, 8),
                discount_factor=discount_factor,
                discounted_cashflow_10k_cny=discounted_cashflow,
                cumulative_cashflow_10k_cny=cumulative_cashflow,
            )
        )
        monthly_cashflows.append(net_cashflow)

    annual_rows = _aggregate_annual_rows(payload, monthly_rows, annual_generation)
    npv = round(_calculate_monthly_npv(monthly_cashflows, monthly_discount_rate), 4)
    monthly_irr = _calculate_monthly_irr(monthly_cashflows)
    project_irr = round(monthly_irr * 12, 6) if monthly_irr is not None else None

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


def _resolve_annual_generation(payload: CalculationInput) -> list[float]:
    """Use the workbook annual generation block like the customer script."""

    values = list(payload.rolling.annual_generation_forecast_10k_kwh[: payload.project.operation_years])
    while len(values) < payload.project.operation_years:
        values.append(project_generation_for_year(payload, len(values) + 1)[0])
    return [float(value) for value in values]


def _resolve_baseline_revenues(payload: CalculationInput) -> list[float]:
    """Use the fixed monthly baseline revenue block from the rolling sheet."""

    return [float(value) for value in payload.rolling.baseline_monthly_revenues_10k_cny]


def _aggregate_annual_rows(
    payload: CalculationInput,
    monthly_rows: list[MonthlyProjection],
    annual_generation: list[float],
) -> list[AnnualProjection]:
    """Aggregate monthly rows back to annual previews for UI/export."""

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
        self_revenue = round(self_consumed_10k_kwh * payload.discounted_consumer_tariff, 2)
        feed_in_revenue = round(exported_10k_kwh * payload.tariff.feed_in_tariff, 2)
        output_vat = round(sum(row.output_vat_10k_cny for row in rows), 4)
        annual_cost = round(sum(row.total_cost_10k_cny for row in rows), 4)
        discounted_cashflow = round(sum(row.discounted_cashflow_10k_cny for row in rows), 4)
        cumulative_discounted_cashflow = round(cumulative_discounted_cashflow + discounted_cashflow, 4)

        annual_rows.append(
            AnnualProjection(
                year=year,
                degradation_pct=project_generation_for_year(payload, year)[1],
                generation_10k_kwh=round(annual_generation[year - 1], 2),
                self_consumed_10k_kwh=self_consumed_10k_kwh,
                exported_10k_kwh=exported_10k_kwh,
                self_consumption_revenue_10k_cny=self_revenue,
                feed_in_revenue_10k_cny=feed_in_revenue,
                subsidy_revenue_10k_cny=0.0,
                gross_revenue_10k_cny=gross_revenue,
                revenue_excluding_vat_10k_cny=round(gross_revenue - output_vat, 2),
                construction_cost_10k_cny=0.0,
                annual_cost_10k_cny=annual_cost,
                annual_insurance_10k_cny=round(sum(row.insurance_cost_10k_cny for row in rows), 4),
                annual_om_and_rent_10k_cny=round(sum(row.om_cost_10k_cny for row in rows), 4),
                input_vat_10k_cny=round(sum(row.input_vat_10k_cny for row in rows), 4),
                output_vat_10k_cny=output_vat,
                vat_payable_10k_cny=round(sum(row.vat_payable_10k_cny for row in rows), 4),
                vat_credit_carry_10k_cny=rows[-1].vat_credit_carry_10k_cny,
                surcharge_tax_10k_cny=round(sum(row.surcharge_tax_10k_cny for row in rows), 4),
                net_cashflow_10k_cny=round(sum(row.net_cashflow_10k_cny for row in rows), 4),
                present_value_factor=round(1 / ((1 + payload.finance.discount_rate) ** year), 4)
                if payload.finance.discount_rate
                else 1.0,
                discounted_cashflow_10k_cny=discounted_cashflow,
                cumulative_discounted_cashflow_10k_cny=cumulative_discounted_cashflow,
                cumulative_cashflow_10k_cny=rows[-1].cumulative_cashflow_10k_cny,
            )
        )

    return annual_rows


def _calc_capex_input_vat(payload: CalculationInput) -> float:
    """Calculate initial deductible VAT exactly like the customer script."""

    investment = payload.cost.total_investment_10k_cny
    return round((investment * 0.7 / 1.13 * 0.13 + investment * 0.3 / 1.09 * 0.09), 2)


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
