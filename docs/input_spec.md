# Input Specification

本文件定义消纳电价计算工具第一版的标准输入字段，用于统一现有 Excel 测算表和电站运营统计表。

## 1. 项目基础信息 `project`

| 字段 | 类型 | 单位 | 说明 | 主要来源 |
| --- | --- | --- | --- | --- |
| `project_name` | string | - | 项目名称 | 测算表 |
| `station_name` | string | - | 电站名称 | 发电统计表 |
| `region` | string | - | 区域 | 发电统计表 |
| `city` | string | - | 地市 | 发电统计表 |
| `district` | string | - | - | 发电统计表 |
| `grid_connection_date` | string | - | 并网时间 | 发电统计表 |
| `operation_years` | int | 年 | 运营年限，默认 25 年 | 测算表 |
| `capacity_mwp` | float | MWp | 装机容量 | 两张表 |

## 2. 发电参数 `generation`

| 字段 | 类型 | 单位 | 说明 | 主要来源 |
| --- | --- | --- | --- | --- |
| `annual_sun_hours` | float | 小时 | 年日照时间 | 测算表 |
| `performance_ratio` | float | 0-1 | 综合系数 | 测算表 |
| `first_year_degradation_pct` | float | % | 首年衰减率，默认 2.5 | 测算表 |
| `annual_degradation_pct` | float | % | 后续年衰减率，默认 0.6 | 测算表 |

## 3. 消纳参数 `consumption`

| 字段 | 类型 | 单位 | 说明 | 主要来源 |
| --- | --- | --- | --- | --- |
| `self_consumption_ratio` | float | 0-1 | 年度自发自用比例 | 测算表 |
| `monthly_self_consumption_ratios` | list[float] | 0-1 | 按月消纳比例，可选 12 个值 | 发电统计表 |
| `feasibility_self_consumption_ratio` | float | 0-1 | 可研消纳率，用于对比实际 | 发电统计表 |

## 4. 电价与补贴 `tariff`

| 字段 | 类型 | 单位 | 说明 | 主要来源 |
| --- | --- | --- | --- | --- |
| `feed_in_tariff` | float | 元/kWh | 余电上网电价 | 测算表 |
| `consumer_tariff` | float | 元/kWh | 用户侧综合电价 | 测算表/运营数据 |
| `consumer_discount_rate` | float | 0-1 | 自用电折扣系数 | 测算表 |
| `national_subsidy` | float | 元/kWh | 国家补贴 | 测算表 |
| `provincial_subsidy` | float | 元/kWh | 省补贴 | 测算表 |
| `local_subsidy` | float | 元/kWh | 地方补贴 | 测算表 |

派生字段：

- `discounted_consumer_tariff = consumer_tariff * consumer_discount_rate`

## 5. 成本参数 `cost`

| 字段 | 类型 | 单位 | 说明 | 主要来源 |
| --- | --- | --- | --- | --- |
| `capex_per_watt` | float | 元/W | 单位造价 | 测算表 |
| `total_investment_10k_cny` | float | 万元 | 总投资 | 测算表 |
| `annual_rent_10k_cny` | float | 万元 | 年租金 | 测算表 |
| `annual_om_10k_cny` | float | 万元 | 年运维费 | 测算表 |
| `annual_insurance_10k_cny` | float | 万元 | 年保险费 | 测算表，若无先置 0 | 测算表 |

## 6. 税费参数 `tax`

| 字段 | 类型 | 单位 | 说明 | 默认值 |
| --- | --- | --- | --- | --- |
| `output_vat_rate` | float | 0-1 | 销项增值税率 | 0.13 |
| `input_vat_rate` | float | 0-1 | 进项增值税率 | 0.06 |
| `surcharge_rate` | float | 0-1 | 教育费附加等综合比例 | 0.12 |

## 7. 财务参数 `finance`

| 字段 | 类型 | 单位 | 说明 | 主要来源 |
| --- | --- | --- | --- | --- |
| `discount_rate` | float | 0-1 | 折现率 | 测算表 |
| `target_irr` | float | 0-1 | 目标 IRR，用于反算消纳电价 | 方案需求 |

## 8. 历史月度数据 `monthly_records`

| 字段 | 类型 | 单位 | 说明 | 主要来源 |
| --- | --- | --- | --- | --- |
| `period_label` | string | - | 月份标识，例如 `2024-01` | 发电统计表 |
| `generation_10k_kwh` | float | 万kWh | 月发电量 | 发电统计表 |
| `self_consumed_10k_kwh` | float | 万kWh | 月消纳电量 | 发电统计表 |
| `exported_10k_kwh` | float | 万kWh | 月上网电量 | 发电统计表 |
| `self_consumption_ratio` | float | 0-1 | 月度消纳率 | 发电统计表 |

## 当前约束

- 所有比例字段都统一成 `0-1`
- 月度比例如果提供，必须恰好 12 个值
- 月度 `消纳电量 + 上网电量` 不能大于 `发电量`
- 后续 Excel 解析器必须输出为同一份 `CalculationInput`
