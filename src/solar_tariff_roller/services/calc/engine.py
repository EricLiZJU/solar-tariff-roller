"""High-level calculation engine."""

from __future__ import annotations

from solar_tariff_roller.schemas.input import CalculationInput
from solar_tariff_roller.services.calc.cashflow import build_cashflow_result


def run_calculation(payload: CalculationInput) -> dict:
    """Run the first-pass calculation engine and return a serializable result."""

    result = build_cashflow_result(payload)
    return {
        "initial_generation_10k_kwh": result.initial_generation_10k_kwh,
        "discounted_consumer_tariff": result.discounted_consumer_tariff,
        "capex_input_vat_10k_cny": result.capex_input_vat_10k_cny,
        "initial_outflow_10k_cny": result.initial_outflow_10k_cny,
        "project_npv_10k_cny": result.project_npv_10k_cny,
        "project_irr": result.project_irr,
        "cumulative_cashflow_10k_cny": result.cumulative_cashflow_10k_cny,
        "annual_projections": [
            {
                "year": row.year,
                "degradation_pct": row.degradation_pct,
                "generation_10k_kwh": row.generation_10k_kwh,
                "self_consumed_10k_kwh": row.self_consumed_10k_kwh,
                "exported_10k_kwh": row.exported_10k_kwh,
                "self_consumption_revenue_10k_cny": row.self_consumption_revenue_10k_cny,
                "feed_in_revenue_10k_cny": row.feed_in_revenue_10k_cny,
                "subsidy_revenue_10k_cny": row.subsidy_revenue_10k_cny,
                "gross_revenue_10k_cny": row.gross_revenue_10k_cny,
                "revenue_excluding_vat_10k_cny": row.revenue_excluding_vat_10k_cny,
                "construction_cost_10k_cny": row.construction_cost_10k_cny,
                "annual_cost_10k_cny": row.annual_cost_10k_cny,
                "annual_insurance_10k_cny": row.annual_insurance_10k_cny,
                "annual_om_and_rent_10k_cny": row.annual_om_and_rent_10k_cny,
                "input_vat_10k_cny": row.input_vat_10k_cny,
                "output_vat_10k_cny": row.output_vat_10k_cny,
                "vat_payable_10k_cny": row.vat_payable_10k_cny,
                "vat_credit_carry_10k_cny": row.vat_credit_carry_10k_cny,
                "surcharge_tax_10k_cny": row.surcharge_tax_10k_cny,
                "net_cashflow_10k_cny": row.net_cashflow_10k_cny,
                "present_value_factor": row.present_value_factor,
                "discounted_cashflow_10k_cny": row.discounted_cashflow_10k_cny,
                "cumulative_discounted_cashflow_10k_cny": row.cumulative_discounted_cashflow_10k_cny,
                "cumulative_cashflow_10k_cny": row.cumulative_cashflow_10k_cny,
            }
            for row in result.annual_projections
        ],
    }
