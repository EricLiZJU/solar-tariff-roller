"""Cashflow calculations."""

from __future__ import annotations

from scipy.optimize import brentq

from solar_tariff_roller.models.results import AnnualProjection, ProjectCashflowResult
from solar_tariff_roller.schemas.input import CalculationInput
from solar_tariff_roller.services.calc.generation import (
    estimate_initial_generation_10k_kwh,
    project_generation_for_year,
)


def build_cashflow_result(payload: CalculationInput) -> ProjectCashflowResult:
    """Build annual project cashflow from normalized calculation input."""

    initial_generation = round(estimate_initial_generation_10k_kwh(payload), 4)
    discounted_consumer_tariff = round(payload.discounted_consumer_tariff, 6)
    annual_insurance = payload.cost.annual_insurance_10k_cny
    annual_om_and_rent = payload.cost.annual_rent_10k_cny + payload.cost.annual_om_10k_cny
    annual_cost = annual_insurance + annual_om_and_rent
    capex_input_vat = _calc_capex_input_vat(payload)
    initial_outflow = round(payload.cost.total_investment_10k_cny, 4)

    annual_rows: list[AnnualProjection] = []
    cumulative_cashflow = -initial_outflow
    cumulative_discounted_cashflow = -initial_outflow
    vat_credit_carry = -capex_input_vat
    cashflows = [-initial_outflow]

    for year in range(1, payload.project.operation_years + 1):
        generation_10k_kwh, degradation_pct = project_generation_for_year(payload, year)
        construction_cost = payload.cost.replacement_costs_10k_cny_by_year.get(year, 0.0)
        self_ratio = payload.consumption.self_consumption_ratio
        self_consumed_10k_kwh = round(generation_10k_kwh * self_ratio, 3)
        exported_10k_kwh = round(generation_10k_kwh - self_consumed_10k_kwh, 3)

        self_revenue = round(self_consumed_10k_kwh * discounted_consumer_tariff, 2)
        feed_in_revenue = round(exported_10k_kwh * payload.tariff.feed_in_tariff, 2)
        subsidy_unit = (
            payload.tariff.national_subsidy
            + payload.tariff.provincial_subsidy
            + payload.tariff.local_subsidy
        )
        subsidy_revenue = round(generation_10k_kwh * subsidy_unit, 2)
        gross_revenue = round(self_revenue + feed_in_revenue + subsidy_revenue, 2)

        revenue_excluding_vat = round(gross_revenue / (1 + payload.tax.output_vat_rate), 2)
        output_vat = _calc_output_vat(gross_revenue, payload.tax.output_vat_rate)
        annual_cost_with_replacement = annual_cost + construction_cost
        recurring_input_vat = _calc_input_vat(annual_cost_with_replacement, payload.tax.input_vat_rate)
        vat_balance = round(output_vat - recurring_input_vat + vat_credit_carry, 2)
        vat_payable = round(max(vat_balance, 0.0), 2)
        vat_credit_carry = round(min(vat_balance, 0.0), 2)
        surcharge_tax = vat_payable * payload.tax.surcharge_rate if vat_payable > 0 else 0.0
        net_cashflow = round(gross_revenue - annual_cost_with_replacement - vat_payable - surcharge_tax, 8)
        present_value_factor = round(1 / ((1 + payload.finance.discount_rate) ** year), 4)
        discounted_cashflow = net_cashflow * present_value_factor
        cumulative_cashflow = round(cumulative_cashflow + net_cashflow, 8)
        cumulative_discounted_cashflow += discounted_cashflow
        cashflows.append(net_cashflow)

        annual_rows.append(
            AnnualProjection(
                year=year,
                degradation_pct=degradation_pct,
                generation_10k_kwh=generation_10k_kwh,
                self_consumed_10k_kwh=self_consumed_10k_kwh,
                exported_10k_kwh=exported_10k_kwh,
                self_consumption_revenue_10k_cny=self_revenue,
                feed_in_revenue_10k_cny=feed_in_revenue,
                subsidy_revenue_10k_cny=subsidy_revenue,
                gross_revenue_10k_cny=gross_revenue,
                revenue_excluding_vat_10k_cny=revenue_excluding_vat,
                construction_cost_10k_cny=construction_cost,
                annual_cost_10k_cny=annual_cost_with_replacement,
                annual_insurance_10k_cny=annual_insurance,
                annual_om_and_rent_10k_cny=annual_om_and_rent,
                input_vat_10k_cny=recurring_input_vat,
                output_vat_10k_cny=output_vat,
                vat_payable_10k_cny=vat_payable,
                vat_credit_carry_10k_cny=vat_credit_carry,
                surcharge_tax_10k_cny=surcharge_tax,
                net_cashflow_10k_cny=net_cashflow,
                present_value_factor=present_value_factor,
                discounted_cashflow_10k_cny=discounted_cashflow,
                cumulative_discounted_cashflow_10k_cny=cumulative_discounted_cashflow,
                cumulative_cashflow_10k_cny=cumulative_cashflow,
            )
        )

    npv = round(_calculate_npv(cashflows, payload.finance.discount_rate), 4)
    irr = _calculate_irr(cashflows)

    return ProjectCashflowResult(
        initial_generation_10k_kwh=initial_generation,
        discounted_consumer_tariff=discounted_consumer_tariff,
        annual_projections=annual_rows,
        capex_input_vat_10k_cny=capex_input_vat,
        initial_outflow_10k_cny=initial_outflow,
        project_npv_10k_cny=npv,
        project_irr=irr,
        cumulative_cashflow_10k_cny=cumulative_cashflow,
    )


def _calc_output_vat(gross_revenue_10k_cny: float, rate: float) -> float:
    """Calculate output VAT from tax-inclusive revenue."""

    return round(gross_revenue_10k_cny / (1 + rate) * rate, 2)


def _calc_input_vat(cost_10k_cny: float, rate: float) -> float:
    """Calculate input VAT from tax-inclusive cost."""

    return round(cost_10k_cny / (1 + rate) * rate, 2)


def _calc_capex_input_vat(payload: CalculationInput) -> float:
    """Calculate capex input VAT using the Excel mixed-rate rule."""

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


def _calculate_npv(cashflows: list[float], rate: float) -> float:
    """Calculate NPV with year-0 cashflow included."""

    return sum(cashflow / ((1 + rate) ** year) for year, cashflow in enumerate(cashflows))


def _calculate_irr(cashflows: list[float]) -> float | None:
    """Calculate IRR using a root finder when the cashflow sign changes."""

    if not any(cashflow < 0 for cashflow in cashflows) or not any(cashflow > 0 for cashflow in cashflows):
        return None

    def npv(rate: float) -> float:
        return _calculate_npv(cashflows, rate)

    try:
        irr = brentq(npv, -0.99, 10.0)
    except ValueError:
        return None

    return round(float(irr), 6)
