"""Generation-related calculations."""

from solar_tariff_roller.schemas.input import CalculationInput


def estimate_initial_generation_10k_kwh(payload: CalculationInput) -> float:
    """Estimate first-year theoretical generation before degradation."""

    return (
        payload.project.capacity_mwp
        * payload.generation.annual_sun_hours
        * payload.generation.performance_ratio
        * 0.1
    )


def calculate_total_degradation_pct(payload: CalculationInput, year: int) -> float:
    """Calculate cumulative degradation percentage for a given operating year."""

    if year <= 0:
        raise ValueError("year must be >= 1")

    if year == 1:
        return payload.generation.first_year_degradation_pct

    return payload.generation.first_year_degradation_pct + (
        year - 1
    ) * payload.generation.annual_degradation_pct


def project_generation_for_year(payload: CalculationInput, year: int) -> tuple[float, float]:
    """Return annual generation and cumulative degradation for the given year."""

    initial_generation = estimate_initial_generation_10k_kwh(payload)
    degradation_pct = calculate_total_degradation_pct(payload, year)
    annual_generation = initial_generation * (1 - degradation_pct / 100)
    return round(annual_generation, 2), round(degradation_pct, 4)
