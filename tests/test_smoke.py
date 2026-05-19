from solar_tariff_roller.models.project import ProjectProfile
from solar_tariff_roller.schemas.input import CalculationInput


def test_project_profile_can_be_created() -> None:
    project = ProjectProfile(project_name="demo", capacity_mwp=1.0)

    assert project.project_name == "demo"


def test_calculation_input_can_be_built() -> None:
    payload = CalculationInput(
        project={
            "project_name": "高宇液压分布式光伏",
            "capacity_mwp": 0.726635,
        },
        generation={
            "annual_sun_hours": 1329,
            "performance_ratio": 0.82,
        },
        consumption={
            "self_consumption_ratio": 0.8,
            "monthly_self_consumption_ratios": [0.8] * 12,
        },
        tariff={
            "feed_in_tariff": 0.4153,
            "consumer_tariff": 0.72,
            "consumer_discount_rate": 0.88,
        },
        cost={
            "capex_per_watt": 4.74,
            "total_investment_10k_cny": 344.83,
            "annual_om_10k_cny": 3.63,
        },
    )

    assert payload.project.project_name == "高宇液压分布式光伏"
    assert round(payload.discounted_consumer_tariff, 4) == 0.6336
