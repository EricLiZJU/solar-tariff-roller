# Formula Notes

这里后续沉淀与 Excel 对齐后的公式口径：

- 发电量
- 消纳拆分
- 上网收益
- 自用收益
- 税费
- 现金流
- IRR / NPV

当前建模约定：

- 发电量单位优先统一为 `万kWh`
- 金额单位优先统一为 `万元`
- 电价与补贴单位统一为 `元/kWh`
- 比例字段统一使用 `0-1` 小数表示，而不是百分数

第一版计算引擎口径：

- 初始年发电量：`capacity_mwp * annual_sun_hours * performance_ratio * 100`
- 第 1 年衰减按 `first_year_degradation_pct`
- 第 2 年及以后累计衰减：`first_year_degradation_pct + (year - 1) * annual_degradation_pct`
- 年度自发自用电量：`annual_generation * self_consumption_ratio`
- 年度上网电量：`annual_generation - self_consumed_generation`
- 自用收益：`self_consumed_10k_kwh * discounted_consumer_tariff`
- 上网收益：`exported_10k_kwh * feed_in_tariff`
- 补贴收益：`annual_generation * (national + provincial + local subsidy)`
- 销项税：`gross_revenue / (1 + output_vat_rate) * output_vat_rate`
- 进项税：`cost / (1 + input_vat_rate) * input_vat_rate`
- 增值税留抵按年度向后结转
- 附加税：`max(vat_payable, 0) * surcharge_rate`
- 年净现金流：`gross_revenue - annual_cost - vat_payable - surcharge_tax`
- 项目 NPV 与 IRR 以年 0 投资流出和运营期净现金流计算

敏感性分析模块：
- 当前支持单变量敏感性分析
- 参数名使用 `section.field` 形式，例如：
  - `tariff.consumer_tariff`
  - `tariff.feed_in_tariff`
  - `consumption.self_consumption_ratio`
  - `cost.total_investment_10k_cny`
- 每个场景点输出：
  - `NPV`
  - `IRR`
  - `累计现金流`
  - `折后用户侧电价`
