"""Rolling cashflow calculations aligned with the latest customer script."""

from __future__ import annotations

from datetime import date

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
    """Build rolling cashflow exactly following the customer's latest script."""

    initial_generation = round(estimate_initial_generation_10k_kwh(payload), 4)
    discounted_consumer_tariff = round(payload.discounted_consumer_tariff, 6)
    initial_outflow = round(payload.cost.total_investment_10k_cny, 4)
    capex_input_vat = _calc_capex_input_vat(payload)
    annual_generation = _resolve_annual_generation(payload)
    p_values = _resolve_yearly_block(
        payload.rolling.baseline_self_use_revenues_10k_cny,
        [round(value * payload.discounted_consumer_tariff, 8) for value in _self_use_energy(annual_generation, payload)],
        payload.project.operation_years,
    )
    m_values = _resolve_yearly_block(
        payload.rolling.baseline_feed_in_revenues_10k_cny,
        [round(value * payload.tariff.feed_in_tariff, 8) for value in _grid_energy(annual_generation, payload)],
        payload.project.operation_years,
    )
    baseline_revenues = list(payload.rolling.baseline_monthly_revenues_10k_cny)
    historical_months_count = min(payload.rolling.historical_months_count, len(baseline_revenues))
    baseline_cashflows = list(payload.rolling.baseline_monthly_cashflows_10k_cny)

    insurance_per_year = round(initial_outflow * 0.001, 8)
    om_half = round(payload.cost.annual_om_10k_cny / 2, 8)

    baseline_discounted_tariff = payload.rolling.baseline_discounted_consumer_tariff or discounted_consumer_tariff
    actual_overrides = _build_actual_month_overrides(payload, discounted_consumer_tariff)

    model_cashflows = _build_cashflows_for_discounted_tariff(
        payload=payload,
        discounted_tariff=discounted_consumer_tariff,
        baseline_discounted_tariff=baseline_discounted_tariff,
        annual_generation=annual_generation,
        p_values=p_values,
        m_values=m_values,
        baseline_revenues=baseline_revenues,
        historical_months_count=historical_months_count,
        insurance_per_year=insurance_per_year,
        om_half=om_half,
        actual_overrides=actual_overrides,
    )
    display_cashflows = (
        baseline_cashflows
        if baseline_cashflows
        and not actual_overrides
        and abs(discounted_consumer_tariff - baseline_discounted_tariff) < 1e-9
        else model_cashflows
    )
    current_monthly_irr = _calculate_monthly_irr(display_cashflows)
    current_project_irr = round(current_monthly_irr * 12, 6) if current_monthly_irr is not None else None

    monthly_rows = _build_monthly_rows_for_discounted_tariff(
        payload=payload,
        discounted_tariff=discounted_consumer_tariff,
        baseline_discounted_tariff=baseline_discounted_tariff,
        annual_generation=annual_generation,
        p_values=p_values,
        m_values=m_values,
        baseline_revenues=baseline_revenues,
        historical_months_count=historical_months_count,
        insurance_per_year=insurance_per_year,
        om_half=om_half,
        actual_overrides=actual_overrides,
    )

    annual_rows = _aggregate_annual_rows(payload, monthly_rows, annual_generation)

    return ProjectCashflowResult(
        initial_generation_10k_kwh=initial_generation,
        discounted_consumer_tariff=discounted_consumer_tariff,
        monthly_irr=current_monthly_irr,
        historical_months_count=historical_months_count,
        monthly_projections=monthly_rows,
        annual_projections=annual_rows,
        capex_input_vat_10k_cny=capex_input_vat,
        initial_outflow_10k_cny=initial_outflow,
        project_npv_10k_cny=round(_calculate_monthly_npv(model_cashflows, payload.finance.discount_rate / 12 if payload.finance.discount_rate else 0.0), 4),
        project_irr=current_project_irr,
        cumulative_cashflow_10k_cny=monthly_rows[-1].cumulative_cashflow_10k_cny if monthly_rows else -initial_outflow,
    )


def build_project_irr_for_discounted_tariff(payload: CalculationInput, discounted_tariff: float) -> float | None:
    """Calculate project IRR for one discounted tariff using the latest script logic."""

    annual_generation = _resolve_annual_generation(payload)
    p_values = _resolve_yearly_block(
        payload.rolling.baseline_self_use_revenues_10k_cny,
        [round(value * payload.discounted_consumer_tariff, 8) for value in _self_use_energy(annual_generation, payload)],
        payload.project.operation_years,
    )
    m_values = _resolve_yearly_block(
        payload.rolling.baseline_feed_in_revenues_10k_cny,
        [round(value * payload.tariff.feed_in_tariff, 8) for value in _grid_energy(annual_generation, payload)],
        payload.project.operation_years,
    )
    cashflows = _build_cashflows_for_discounted_tariff(
        payload=payload,
        discounted_tariff=discounted_tariff,
        baseline_discounted_tariff=(payload.rolling.baseline_discounted_consumer_tariff or payload.discounted_consumer_tariff),
        annual_generation=annual_generation,
        p_values=p_values,
        m_values=m_values,
        baseline_revenues=list(payload.rolling.baseline_monthly_revenues_10k_cny),
        historical_months_count=payload.rolling.historical_months_count,
        insurance_per_year=round(payload.cost.total_investment_10k_cny * 0.001, 8),
        om_half=round(payload.cost.annual_om_10k_cny / 2, 8),
    )
    monthly_irr = _calculate_monthly_irr(cashflows)
    if monthly_irr is None:
        return None
    return round(monthly_irr * 12, 6)


def _build_cashflows_for_discounted_tariff(
    *,
    payload: CalculationInput,
    discounted_tariff: float,
    baseline_discounted_tariff: float,
    annual_generation: list[float],
    p_values: list[float],
    m_values: list[float],
    baseline_revenues: list[float],
    historical_months_count: int,
    insurance_per_year: float,
    om_half: float,
    actual_overrides: dict[int, dict[str, float]],
) -> list[float]:
    """Build month-0 to month-300 cashflows using the latest script logic."""

    monthly_revenues = _build_monthly_revenues_for_discounted_tariff(
        payload=payload,
        discounted_tariff=discounted_tariff,
        baseline_discounted_tariff=baseline_discounted_tariff,
        annual_generation=annual_generation,
        p_values=p_values,
        m_values=m_values,
        baseline_revenues=baseline_revenues,
        historical_months_count=historical_months_count,
        actual_overrides=actual_overrides,
    )
    investment = payload.cost.total_investment_10k_cny
    cashflows = [-investment]
    vat_credit_carry = -_calc_capex_input_vat(payload)

    for month_num, gross_revenue in enumerate(monthly_revenues, start=1):
        insurance_cost = insurance_per_year if month_num % 12 == 1 else 0.0
        om_cost = om_half if month_num % 6 == 1 else 0.0
        total_cost = insurance_cost + om_cost

        input_vat = round(total_cost / 1.06 * 0.06, 2) if total_cost > 0 else 0.0
        revenue_excluding_vat = round(gross_revenue / 1.13, 2)
        output_vat = round(revenue_excluding_vat * 0.13, 2)
        vat_balance = output_vat - input_vat + vat_credit_carry
        vat_credit_carry = min(vat_balance, 0) if vat_balance < 0 else 0
        surcharge_tax = round(vat_balance * 0.12, 2) if vat_balance > 0 else 0.0
        net_cashflow = gross_revenue - total_cost - (vat_balance if vat_balance > 0 else 0.0) - surcharge_tax
        cashflows.append(net_cashflow)

    return cashflows


def _build_monthly_rows_for_discounted_tariff(
    *,
    payload: CalculationInput,
    discounted_tariff: float,
    baseline_discounted_tariff: float,
    annual_generation: list[float],
    p_values: list[float],
    m_values: list[float],
    baseline_revenues: list[float],
    historical_months_count: int,
    insurance_per_year: float,
    om_half: float,
    actual_overrides: dict[int, dict[str, float]],
) -> list[MonthlyProjection]:
    """Build detailed monthly rows for UI/export under one discounted tariff."""

    monthly_revenues = _build_monthly_revenues_for_discounted_tariff(
        payload=payload,
        discounted_tariff=discounted_tariff,
        baseline_discounted_tariff=baseline_discounted_tariff,
        annual_generation=annual_generation,
        p_values=p_values,
        m_values=m_values,
        baseline_revenues=baseline_revenues,
        historical_months_count=historical_months_count,
        actual_overrides=actual_overrides,
    )
    monthly_rows: list[MonthlyProjection] = []
    cumulative_cashflow = -payload.cost.total_investment_10k_cny
    vat_credit_carry = -_calc_capex_input_vat(payload)
    monthly_discount_rate = payload.finance.discount_rate / 12 if payload.finance.discount_rate else 0.0
    q_values = _build_q_values(discounted_tariff, baseline_discounted_tariff, p_values, m_values)

    for month_num, gross_revenue in enumerate(monthly_revenues, start=1):
        operating_year = ((month_num - 1) // 12) + 1
        month_in_year = ((month_num - 1) % 12) + 1
        actual_override = actual_overrides.get(month_num)
        if actual_override is not None:
            generation_10k_kwh = round(actual_override["generation_10k_kwh"], 4)
            self_consumed_10k_kwh = round(actual_override["self_consumed_10k_kwh"], 4)
            exported_10k_kwh = round(actual_override["exported_10k_kwh"], 4)
            period_type = "actual"
        else:
            generation_10k_kwh = round(annual_generation[operating_year - 1] / 12, 4)
            self_consumed_10k_kwh = round(generation_10k_kwh * payload.consumption.self_consumption_ratio, 4)
            exported_10k_kwh = round(generation_10k_kwh - self_consumed_10k_kwh, 4)
            period_type = "historical" if month_num <= historical_months_count else "projected"
        insurance_cost = insurance_per_year if month_num % 12 == 1 else 0.0
        om_cost = om_half if month_num % 6 == 1 else 0.0
        total_cost = round(insurance_cost + om_cost, 8)
        input_vat = round(total_cost / 1.06 * 0.06, 2) if total_cost > 0 else 0.0
        revenue_excluding_vat = round(gross_revenue / 1.13, 2)
        output_vat = round(revenue_excluding_vat * 0.13, 2)
        vat_balance = output_vat - input_vat + vat_credit_carry
        vat_payable = round(vat_balance, 2) if vat_balance > 0 else 0.0
        vat_credit_carry = min(vat_balance, 0) if vat_balance < 0 else 0
        surcharge_tax = round(vat_balance * 0.12, 2) if vat_balance > 0 else 0.0
        net_cashflow = gross_revenue - total_cost - vat_payable - surcharge_tax
        discount_factor = round(1 / ((1 + monthly_discount_rate) ** month_num), 8) if monthly_discount_rate else 1.0
        discounted_cashflow = round(net_cashflow * discount_factor, 8)
        cumulative_cashflow = round(cumulative_cashflow + net_cashflow, 8)
        annualized_revenue_basis = round(q_values[operating_year - 1], 8)

        monthly_rows.append(
            MonthlyProjection(
                month_index=month_num,
                operating_year=operating_year,
                month_in_year=month_in_year,
                period_type=period_type,
                generation_10k_kwh=generation_10k_kwh,
                self_consumed_10k_kwh=self_consumed_10k_kwh,
                exported_10k_kwh=exported_10k_kwh,
                gross_revenue_10k_cny=round(gross_revenue, 8),
                annualized_revenue_basis_10k_cny=annualized_revenue_basis,
                insurance_cost_10k_cny=insurance_cost,
                om_cost_10k_cny=om_cost,
                replacement_cost_10k_cny=0.0,
                total_cost_10k_cny=total_cost,
                input_vat_10k_cny=input_vat,
                output_vat_10k_cny=output_vat,
                vat_balance_10k_cny=round(vat_balance, 8),
                vat_payable_10k_cny=vat_payable,
                vat_credit_carry_10k_cny=round(vat_credit_carry, 8),
                surcharge_tax_10k_cny=surcharge_tax,
                net_cashflow_10k_cny=round(net_cashflow, 8),
                discount_factor=discount_factor,
                discounted_cashflow_10k_cny=discounted_cashflow,
                cumulative_cashflow_10k_cny=cumulative_cashflow,
            )
        )

    return monthly_rows


def _build_monthly_revenues_for_discounted_tariff(
    *,
    payload: CalculationInput,
    discounted_tariff: float,
    baseline_discounted_tariff: float,
    annual_generation: list[float],
    p_values: list[float],
    m_values: list[float],
    baseline_revenues: list[float],
    historical_months_count: int,
    actual_overrides: dict[int, dict[str, float]],
) -> list[float]:
    """Build the monthly C series exactly like the latest customer script."""

    old_discounted_tariff = baseline_discounted_tariff
    mixed_old = payload.consumption.self_consumption_ratio * old_discounted_tariff + (
        1 - payload.consumption.self_consumption_ratio
    ) * payload.tariff.feed_in_tariff
    mixed_new = payload.consumption.self_consumption_ratio * discounted_tariff + (
        1 - payload.consumption.self_consumption_ratio
    ) * payload.tariff.feed_in_tariff
    ratio = mixed_new / mixed_old if mixed_old else 1.0

    monthly_revenues: list[float] = []
    for revenue in baseline_revenues[:historical_months_count]:
        monthly_revenues.append(revenue * ratio)

    q_values = _build_q_values(discounted_tariff, old_discounted_tariff, p_values, m_values)
    if q_values:
        forecast_q_rows = list(payload.rolling.forecast_q_row_numbers)
        if forecast_q_rows:
            for q_row_number in forecast_q_rows:
                q_index = q_row_number - 63
                if 0 <= q_index < len(q_values):
                    monthly_revenues.append(q_values[q_index] / 12)
        else:
            monthly_revenues.extend([q_values[0] / 12] * 4)
            if len(q_values) > 1:
                monthly_revenues.extend([q_values[1] / 12] * 12)
            if len(q_values) > 2:
                monthly_revenues.extend([q_values[2] / 12] * 12)
            for year_index in range(3, len(q_values)):
                monthly_revenues.extend([q_values[year_index] / 12] * 12)

    total_months = payload.project.operation_years * 12
    monthly_revenues = monthly_revenues[:total_months]
    for month_index, override in actual_overrides.items():
        if 1 <= month_index <= len(monthly_revenues):
            monthly_revenues[month_index - 1] = override["gross_revenue_10k_cny"]
    return monthly_revenues


def _build_q_values(
    discounted_tariff: float,
    old_discounted_tariff: float,
    p_values: list[float],
    m_values: list[float],
) -> list[float]:
    """Rebuild yearly Q values from yearly P and M values."""

    q_values: list[float] = []
    for index in range(min(len(p_values), len(m_values))):
        p_new = p_values[index] * (discounted_tariff / old_discounted_tariff) if old_discounted_tariff else 0.0
        q_values.append(m_values[index] + p_new)
    return q_values


def _resolve_annual_generation(payload: CalculationInput) -> list[float]:
    """Use the workbook annual generation forecast block."""

    values = list(payload.rolling.annual_generation_forecast_10k_kwh[: payload.project.operation_years])
    while len(values) < payload.project.operation_years:
        values.append(project_generation_for_year(payload, len(values) + 1)[0])
    return [float(value) for value in values]


def _resolve_yearly_block(values: list[float], fallback: list[float], operation_years: int) -> list[float]:
    """Use workbook yearly values when present, otherwise fall back."""

    resolved = list(values[:operation_years])
    while len(resolved) < operation_years:
        resolved.append(fallback[len(resolved)] if len(resolved) < len(fallback) else 0.0)
    return [float(value) for value in resolved]


def _self_use_energy(annual_generation: list[float], payload: CalculationInput) -> list[float]:
    return [float(value * payload.consumption.self_consumption_ratio) for value in annual_generation]


def _grid_energy(annual_generation: list[float], payload: CalculationInput) -> list[float]:
    return [float(value * (1 - payload.consumption.self_consumption_ratio)) for value in annual_generation]


def _aggregate_annual_rows(
    payload: CalculationInput,
    monthly_rows: list[MonthlyProjection],
    annual_generation: list[float],
) -> list[AnnualProjection]:
    """Aggregate monthly rows back to annual previews using Excel annual-sheet logic."""

    annual_rows: list[AnnualProjection] = []
    cumulative_discounted_cashflow = -payload.cost.total_investment_10k_cny
    cumulative_cashflow = -payload.cost.total_investment_10k_cny
    annual_vat_carry = -_calc_annual_capex_input_vat(payload)
    annual_output_vat_rate = payload.tax.annual_output_vat_rate or payload.tax.output_vat_rate

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
        revenue_excluding_vat = round(gross_revenue / (1 + annual_output_vat_rate), 2) if gross_revenue else 0.0
        output_vat = round(gross_revenue / (1 + annual_output_vat_rate) * annual_output_vat_rate, 2) if gross_revenue else 0.0
        construction_cost = round(payload.cost.replacement_costs_10k_cny_by_year.get(year, 0.0), 4)
        annual_rent = round(payload.cost.annual_rent_10k_cny, 4)
        annual_om = round(payload.cost.annual_om_10k_cny, 4)
        annual_cost = round(construction_cost + annual_rent + annual_om, 4)
        input_vat = round(annual_cost / 1.06 * 0.06, 2) if annual_cost > 0 else 0.0
        annual_vat_balance = round(output_vat - input_vat + (annual_vat_carry if annual_vat_carry < 0 else 0.0), 2)
        vat_payable = annual_vat_balance if annual_vat_balance > 0 else 0.0
        annual_vat_carry = annual_vat_balance if annual_vat_balance < 0 else 0.0
        surcharge_tax = round(annual_vat_balance * payload.tax.surcharge_rate, 3) if annual_vat_balance > 0 else 0.0
        net_cashflow = round(gross_revenue - annual_cost - vat_payable - surcharge_tax, 4)
        cumulative_cashflow = round(cumulative_cashflow + net_cashflow, 4)
        present_value_factor = (
            round(1 / ((1 + payload.finance.discount_rate) ** year), 4)
            if payload.finance.discount_rate
            else 1.0
        )
        discounted_cashflow = round(net_cashflow * present_value_factor, 4)
        cumulative_discounted_cashflow = round(cumulative_discounted_cashflow + discounted_cashflow, 4)

        annual_rows.append(
            AnnualProjection(
                year=year,
                degradation_pct=0.0,
                generation_10k_kwh=round(annual_generation[year - 1], 2),
                self_consumed_10k_kwh=self_consumed_10k_kwh,
                exported_10k_kwh=exported_10k_kwh,
                self_consumption_revenue_10k_cny=self_revenue,
                feed_in_revenue_10k_cny=feed_in_revenue,
                subsidy_revenue_10k_cny=0.0,
                gross_revenue_10k_cny=gross_revenue,
                revenue_excluding_vat_10k_cny=revenue_excluding_vat,
                construction_cost_10k_cny=construction_cost,
                annual_rent_10k_cny=annual_rent,
                annual_om_10k_cny=annual_om,
                annual_cost_10k_cny=annual_cost,
                annual_insurance_10k_cny=round(sum(row.insurance_cost_10k_cny for row in rows), 4),
                annual_om_and_rent_10k_cny=round(annual_rent + annual_om, 4),
                input_vat_10k_cny=input_vat,
                output_vat_10k_cny=output_vat,
                annual_vat_balance_10k_cny=annual_vat_balance,
                vat_payable_10k_cny=vat_payable,
                vat_credit_carry_10k_cny=annual_vat_carry,
                surcharge_tax_10k_cny=surcharge_tax,
                net_cashflow_10k_cny=net_cashflow,
                present_value_factor=present_value_factor,
                discounted_cashflow_10k_cny=discounted_cashflow,
                cumulative_discounted_cashflow_10k_cny=cumulative_discounted_cashflow,
                cumulative_cashflow_10k_cny=cumulative_cashflow,
            )
        )

    return annual_rows


def _calc_capex_input_vat(payload: CalculationInput) -> float:
    """Calculate initial deductible VAT exactly like the customer script."""

    investment = payload.cost.total_investment_10k_cny
    return round((investment * 0.7 / 1.13 * 0.13 + investment * 0.3 / 1.09 * 0.09), 2)


def _calc_annual_capex_input_vat(payload: CalculationInput) -> float:
    """Calculate annual-sheet initial deductible VAT using annual preview tax rates."""

    investment = payload.cost.total_investment_10k_cny
    primary_rate = payload.tax.annual_capex_input_vat_primary_rate
    secondary_rate = payload.tax.annual_capex_input_vat_secondary_rate
    return round(
        (
            investment * payload.tax.capex_input_vat_primary_ratio / (1 + primary_rate) * primary_rate
            + investment * payload.tax.capex_input_vat_secondary_ratio / (1 + secondary_rate) * secondary_rate
        ),
        2,
    )


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


def _build_actual_month_overrides(
    payload: CalculationInput,
    discounted_tariff: float,
) -> dict[int, dict[str, float]]:
    """Map complete monthly actual records onto rolling month indices."""

    anchor_period = _resolve_anchor_period(payload)
    if anchor_period is None:
        return {}

    overrides: dict[int, dict[str, float]] = {}
    total_months = payload.project.operation_years * 12
    for record in payload.monthly_records:
        period = _parse_period_label(record.period_label)
        if (
            period is None
            or record.generation_10k_kwh is None
            or record.self_consumed_10k_kwh is None
            or record.exported_10k_kwh is None
        ):
            continue

        month_index = _months_between(anchor_period, period) + 1
        if month_index < 1 or month_index > total_months:
            continue

        gross_revenue = (
            record.self_consumed_10k_kwh * discounted_tariff
            + record.exported_10k_kwh * payload.tariff.feed_in_tariff
        )
        overrides[month_index] = {
            "generation_10k_kwh": float(record.generation_10k_kwh),
            "self_consumed_10k_kwh": float(record.self_consumed_10k_kwh),
            "exported_10k_kwh": float(record.exported_10k_kwh),
            "gross_revenue_10k_cny": round(gross_revenue, 8),
        }

    return overrides


def _resolve_anchor_period(payload: CalculationInput) -> date | None:
    """Resolve the rolling month-1 anchor from grid connection or earliest record."""

    if payload.project.grid_connection_date:
        parsed = _parse_period_label(payload.project.grid_connection_date)
        if parsed is not None:
            return parsed

    parsed_records = sorted(
        (
            parsed
            for parsed in (_parse_period_label(record.period_label) for record in payload.monthly_records)
            if parsed is not None
        ),
        key=lambda item: (item.year, item.month),
    )
    return parsed_records[0] if parsed_records else None


def _parse_period_label(value: str | None) -> date | None:
    """Parse YYYY-MM or YYYY-MM-DD labels into a month anchor date."""

    if not value:
        return None

    normalized = value.strip()
    try:
        if len(normalized) >= 7:
            return date.fromisoformat(f"{normalized[:7]}-01")
    except ValueError:
        return None
    return None


def _months_between(start: date, end: date) -> int:
    """Return the whole-month distance between two month anchor dates."""

    return (end.year - start.year) * 12 + (end.month - start.month)
