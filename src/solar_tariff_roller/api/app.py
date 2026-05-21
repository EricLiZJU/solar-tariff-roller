"""Simple FastAPI UI for target IRR solving."""

from __future__ import annotations

from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from solar_tariff_roller.schemas.input import MonthlyGenerationRecordInput
from solar_tariff_roller.services.calc import analyze_sensitivity, generate_sensitivity_values
from solar_tariff_roller.services.exporter import export_calculation_bundle
from solar_tariff_roller.services.parser import (
    build_monthly_updates_path,
    load_monthly_updates,
    load_project_workbook,
    upsert_monthly_update,
)
from solar_tariff_roller.services.solver import solve_tariff_by_target_irr

DEFAULT_CALCULATION_WORKBOOK = (
    "/Users/lihongyang/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/wxid_31ux569lgb2v22_5145/temp/drag/"
    "【测算表】浙江高宇液压机电有限公司分布式光伏发电项目.xlsx"
)
DEFAULT_STATION_WORKBOOK = (
    "/Users/lihongyang/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/wxid_31ux569lgb2v22_5145/temp/drag/"
    "台州高宇液压电站发电统计表(1).xlsx"
)
SENSITIVITY_OPTIONS = {
    "tariff.consumer_tariff": "用户侧综合电价",
    "tariff.feed_in_tariff": "余电上网电价",
    "consumption.self_consumption_ratio": "自发自用比例",
    "cost.total_investment_10k_cny": "总投资",
}


def create_app() -> FastAPI:
    """Create the web app for manual IRR solving."""

    app = FastAPI(title="Solar Tariff Roller")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _render_page()

    @app.get("/solve", response_class=HTMLResponse)
    def solve_page(
        target_irr: float = Query(..., ge=0, le=1),
        calculation_workbook: str = Query(DEFAULT_CALCULATION_WORKBOOK),
        station_workbook: str = Query(DEFAULT_STATION_WORKBOOK),
        sensitivity_parameter: str = Query("tariff.consumer_tariff"),
        sensitivity_start: float = Query(0.68),
        sensitivity_stop: float = Query(0.76),
        sensitivity_step: float = Query(0.04, gt=0),
    ) -> str:
        try:
            context = _build_workbench_context(
                target_irr=target_irr,
                calculation_workbook=calculation_workbook,
                station_workbook=station_workbook,
                sensitivity_parameter=sensitivity_parameter,
                sensitivity_start=sensitivity_start,
                sensitivity_stop=sensitivity_stop,
                sensitivity_step=sensitivity_step,
            )
        except Exception as exc:  # pragma: no cover - UI fallback
            return _render_page(
                error=str(exc),
                target_irr=target_irr,
                calculation_workbook=calculation_workbook,
                station_workbook=station_workbook,
                sensitivity_parameter=sensitivity_parameter,
                sensitivity_start=sensitivity_start,
                sensitivity_stop=sensitivity_stop,
                sensitivity_step=sensitivity_step,
            )
        return _render_page(
            result_html=_render_result_html(context),
            target_irr=target_irr,
            calculation_workbook=calculation_workbook,
            station_workbook=station_workbook,
            sensitivity_parameter=sensitivity_parameter,
            sensitivity_start=sensitivity_start,
            sensitivity_stop=sensitivity_stop,
            sensitivity_step=sensitivity_step,
        )

    @app.get("/update-monthly", response_class=HTMLResponse)
    def update_monthly_page(
        target_irr: float = Query(..., ge=0, le=1),
        calculation_workbook: str = Query(DEFAULT_CALCULATION_WORKBOOK),
        station_workbook: str = Query(DEFAULT_STATION_WORKBOOK),
        sensitivity_parameter: str = Query("tariff.consumer_tariff"),
        sensitivity_start: float = Query(0.68),
        sensitivity_stop: float = Query(0.76),
        sensitivity_step: float = Query(0.04, gt=0),
        period_label: str = Query(...),
        generation_10k_kwh: float = Query(..., ge=0),
        self_consumed_10k_kwh: float = Query(..., ge=0),
        exported_10k_kwh: float = Query(..., ge=0),
    ) -> str:
        try:
            record = MonthlyGenerationRecordInput(
                period_label=period_label,
                generation_10k_kwh=generation_10k_kwh,
                self_consumed_10k_kwh=self_consumed_10k_kwh,
                exported_10k_kwh=exported_10k_kwh,
            )
            store_path = upsert_monthly_update(
                Path(calculation_workbook),
                Path(station_workbook),
                record,
            )
            context = _build_workbench_context(
                target_irr=target_irr,
                calculation_workbook=calculation_workbook,
                station_workbook=station_workbook,
                sensitivity_parameter=sensitivity_parameter,
                sensitivity_start=sensitivity_start,
                sensitivity_stop=sensitivity_stop,
                sensitivity_step=sensitivity_step,
            )
            success = (
                f"已保存 {period_label} 的月度真实数据，并重新完成测算。"
                f" 当前更新文件: {store_path}"
            )
        except Exception as exc:  # pragma: no cover - UI fallback
            return _render_page(
                error=str(exc),
                target_irr=target_irr,
                calculation_workbook=calculation_workbook,
                station_workbook=station_workbook,
                sensitivity_parameter=sensitivity_parameter,
                sensitivity_start=sensitivity_start,
                sensitivity_stop=sensitivity_stop,
                sensitivity_step=sensitivity_step,
                update_period_label=period_label,
                update_generation_10k_kwh=generation_10k_kwh,
                update_self_consumed_10k_kwh=self_consumed_10k_kwh,
                update_exported_10k_kwh=exported_10k_kwh,
            )

        return _render_page(
            result_html=_render_result_html(context),
            success=success,
            target_irr=target_irr,
            calculation_workbook=calculation_workbook,
            station_workbook=station_workbook,
            sensitivity_parameter=sensitivity_parameter,
            sensitivity_start=sensitivity_start,
            sensitivity_stop=sensitivity_stop,
            sensitivity_step=sensitivity_step,
            update_period_label=period_label,
            update_generation_10k_kwh=generation_10k_kwh,
            update_self_consumed_10k_kwh=self_consumed_10k_kwh,
            update_exported_10k_kwh=exported_10k_kwh,
        )

    @app.get("/api/solve")
    def solve_api(
        target_irr: float = Query(..., ge=0, le=1),
        calculation_workbook: str = Query(DEFAULT_CALCULATION_WORKBOOK),
        station_workbook: str = Query(DEFAULT_STATION_WORKBOOK),
        sensitivity_parameter: str = Query("tariff.consumer_tariff"),
        sensitivity_start: float = Query(0.68),
        sensitivity_stop: float = Query(0.76),
        sensitivity_step: float = Query(0.04, gt=0),
    ) -> JSONResponse:
        try:
            context = _build_workbench_context(
                target_irr=target_irr,
                calculation_workbook=calculation_workbook,
                station_workbook=station_workbook,
                sensitivity_parameter=sensitivity_parameter,
                sensitivity_start=sensitivity_start,
                sensitivity_stop=sensitivity_stop,
                sensitivity_step=sensitivity_step,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        solved = context["solved"]
        sensitivity = context["sensitivity"]
        exports = context["exports"]
        payload = context["payload"]
        return JSONResponse(
            {
                "target_irr": solved.target_irr,
                "solved_consumer_tariff": solved.solved_consumer_tariff,
                "solved_discounted_consumer_tariff": solved.solved_discounted_consumer_tariff,
                "solved_npv_10k_cny": solved.solved_npv_10k_cny,
                "solved_project_irr": solved.solved_project_irr,
                "json_export_path": str(exports["json"]),
                "excel_export_path": str(exports["excel"]),
                "monthly_update_store_path": str(context["update_store_path"]),
                "monthly_updates_count": len(context["persisted_updates"]),
                "effective_self_consumption_ratio": payload.consumption.self_consumption_ratio,
                "recent_monthly_records": [
                    record.model_dump()
                    for record in payload.monthly_records[-12:]
                ],
                "sensitivity_analysis": {
                    "parameter_name": sensitivity.parameter_name,
                    "values": [
                        {
                            "parameter_value": point.parameter_value,
                            "project_npv_10k_cny": point.project_npv_10k_cny,
                            "project_irr": point.project_irr,
                            "cumulative_cashflow_10k_cny": point.cumulative_cashflow_10k_cny,
                            "discounted_consumer_tariff": point.discounted_consumer_tariff,
                        }
                        for point in sensitivity.points
                    ],
                },
            }
        )

    return app


def _build_workbench_context(
    *,
    target_irr: float,
    calculation_workbook: str,
    station_workbook: str,
    sensitivity_parameter: str,
    sensitivity_start: float,
    sensitivity_stop: float,
    sensitivity_step: float,
) -> dict[str, object]:
    """Run the full workbench pipeline and return render-ready context."""

    calculation_path = Path(calculation_workbook)
    station_path = Path(station_workbook)
    payload = load_project_workbook(calculation_path, station_path)
    solved = solve_tariff_by_target_irr(payload, target_irr=target_irr)
    sensitivity_values = generate_sensitivity_values(
        sensitivity_start,
        sensitivity_stop,
        sensitivity_step,
    )
    sensitivity = analyze_sensitivity(payload, sensitivity_parameter, sensitivity_values)
    exports = export_calculation_bundle(
        payload,
        reference_workbook_path=calculation_path,
        target_irr=target_irr,
        sensitivity_parameter=sensitivity_parameter,
        sensitivity_start=sensitivity_start,
        sensitivity_stop=sensitivity_stop,
        sensitivity_step=sensitivity_step,
    )
    update_store_path = build_monthly_updates_path(calculation_path, station_path)
    persisted_updates = load_monthly_updates(calculation_path, station_path)
    return {
        "payload": payload,
        "solved": solved,
        "sensitivity": sensitivity,
        "exports": exports,
        "update_store_path": update_store_path,
        "persisted_updates": persisted_updates,
    }


def _render_result_html(context: dict[str, object]) -> str:
    """Build the result area for solve and update pages."""

    payload = context["payload"]
    solved = context["solved"]
    sensitivity = context["sensitivity"]
    exports = context["exports"]
    update_store_path = context["update_store_path"]
    persisted_updates = context["persisted_updates"]

    sensitivity_rows = "".join(
        f"""
        <tr>
          <td>{point.parameter_value:.6f}</td>
          <td>{point.project_npv_10k_cny:.4f}</td>
          <td>{'' if point.project_irr is None else f'{point.project_irr:.6f}'}</td>
          <td>{point.cumulative_cashflow_10k_cny:.4f}</td>
          <td>{point.discounted_consumer_tariff:.6f}</td>
        </tr>
        """
        for point in sensitivity.points
    )
    monthly_rows = "".join(
        f"""
        <tr>
          <td>{escape(record.period_label)}</td>
          <td>{'' if record.generation_10k_kwh is None else f'{record.generation_10k_kwh:.4f}'}</td>
          <td>{'' if record.self_consumed_10k_kwh is None else f'{record.self_consumed_10k_kwh:.4f}'}</td>
          <td>{'' if record.exported_10k_kwh is None else f'{record.exported_10k_kwh:.4f}'}</td>
          <td>{'' if record.self_consumption_ratio is None else f'{record.self_consumption_ratio:.4%}'}</td>
        </tr>
        """
        for record in payload.monthly_records[-12:]
    )
    npv_chart_svg = _build_line_chart_svg(
        [point.parameter_value for point in sensitivity.points],
        [point.project_npv_10k_cny for point in sensitivity.points],
        "NPV(万元)",
    )
    irr_chart_svg = _build_bar_chart_svg(
        [point.parameter_value for point in sensitivity.points],
        [0.0 if point.project_irr is None else point.project_irr for point in sensitivity.points],
        "IRR",
    )

    return f"""
    <section class="results-stack">
      <section class="card result spotlight">
        <div class="section-head">
          <div>
            <p class="eyebrow">Solve Result</p>
            <h2>反算结果</h2>
          </div>
          <span class="badge">IRR 已咬合</span>
        </div>
        <div class="metric-grid">
          <article class="metric primary">
            <span>目标 IRR</span>
            <strong>{solved.target_irr:.6f}</strong>
          </article>
          <article class="metric accent">
            <span>用户侧综合电价</span>
            <strong>{solved.solved_consumer_tariff:.6f}</strong>
            <em>元/kWh</em>
          </article>
          <article class="metric accent">
            <span>折后消纳电价</span>
            <strong>{solved.solved_discounted_consumer_tariff:.6f}</strong>
            <em>元/kWh</em>
          </article>
          <article class="metric">
            <span>校验 NPV</span>
            <strong>{solved.solved_npv_10k_cny:.6f}</strong>
            <em>万元</em>
          </article>
          <article class="metric">
            <span>校验 IRR</span>
            <strong>{solved.solved_project_irr:.6f}</strong>
          </article>
        </div>
      </section>
      <section class="two-col">
        <section class="card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Project Snapshot</p>
              <h2>项目概览</h2>
            </div>
          </div>
          <div class="mini-grid">
            <div><span>项目名称</span><strong>{escape(payload.project.project_name)}</strong></div>
            <div><span>电站名称</span><strong>{escape(payload.project.station_name or "-")}</strong></div>
            <div><span>装机容量</span><strong>{payload.project.capacity_mwp:.6f} MWp</strong></div>
            <div><span>当前折现率</span><strong>{payload.finance.discount_rate:.6f}</strong></div>
            <div><span>生效自用比例</span><strong>{payload.consumption.self_consumption_ratio:.4%}</strong></div>
            <div><span>月度更新条数</span><strong>{len(persisted_updates)}</strong></div>
          </div>
        </section>
        <section class="card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Export Files</p>
              <h2>导出结果</h2>
            </div>
          </div>
          <div class="path-list">
            <div>
              <span>JSON 文件</span>
              <code>{escape(str(exports["json"]))}</code>
            </div>
            <div>
              <span>Excel 文件</span>
              <code>{escape(str(exports["excel"]))}</code>
            </div>
            <div>
              <span>月度更新文件</span>
              <code>{escape(str(update_store_path))}</code>
            </div>
          </div>
        </section>
      </section>
      <section class="card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Monthly Actuals</p>
            <h2>最近 12 个月真实数据</h2>
          </div>
          <span class="badge">更新后自动重算</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>月份</th>
                <th>发电量(万kWh)</th>
                <th>自用电量(万kWh)</th>
                <th>上网电量(万kWh)</th>
                <th>消纳率</th>
              </tr>
            </thead>
            <tbody>
              {monthly_rows}
            </tbody>
          </table>
        </div>
      </section>
      <section class="card">
        <div class="section-head">
          <div>
            <p class="eyebrow">Sensitivity Analysis</p>
            <h2>敏感性分析</h2>
          </div>
          <span class="badge">{escape(SENSITIVITY_OPTIONS.get(sensitivity.parameter_name, sensitivity.parameter_name))}</span>
        </div>
        <div class="chart-grid">
          <section class="chart-card">
            <div class="chart-head">
              <h3>NPV 折线图</h3>
              <p>观察参数变化对净现值的影响趋势</p>
            </div>
            {npv_chart_svg}
          </section>
          <section class="chart-card">
            <div class="chart-head">
              <h3>IRR 柱状图</h3>
              <p>观察参数变化对 IRR 的抬升或压缩</p>
            </div>
            {irr_chart_svg}
          </section>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>参数值</th>
                <th>NPV(万元)</th>
                <th>IRR</th>
                <th>累计现金流(万元)</th>
                <th>折后用户侧电价(元/kWh)</th>
              </tr>
            </thead>
            <tbody>
              {sensitivity_rows}
            </tbody>
          </table>
        </div>
      </section>
    </section>
    """


def _render_page(
    result_html: str = "",
    error: str | None = None,
    success: str | None = None,
    target_irr: float = 0.095977,
    calculation_workbook: str = DEFAULT_CALCULATION_WORKBOOK,
    station_workbook: str = DEFAULT_STATION_WORKBOOK,
    sensitivity_parameter: str = "tariff.consumer_tariff",
    sensitivity_start: float = 0.68,
    sensitivity_stop: float = 0.76,
    sensitivity_step: float = 0.04,
    update_period_label: str = "",
    update_generation_10k_kwh: float | None = None,
    update_self_consumed_10k_kwh: float | None = None,
    update_exported_10k_kwh: float | None = None,
) -> str:
    """Render the single-page HTML UI."""

    error_html = (
        f'<section class="card error"><strong>错误:</strong> {escape(error)}</section>' if error else ""
    )
    success_html = (
        f'<section class="card success"><strong>完成:</strong> {escape(success)}</section>' if success else ""
    )
    options_html = "".join(
        f'<option value="{escape(key)}" {"selected" if key == sensitivity_parameter else ""}>{escape(label)}</option>'
        for key, label in SENSITIVITY_OPTIONS.items()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>消纳电价反算工具</title>
  <style>
    :root {{
      --bg: #f5efe3;
      --panel: rgba(255, 250, 242, 0.92);
      --panel-strong: #fffdf8;
      --ink: #173038;
      --muted: #57686f;
      --accent: #0f766e;
      --accent-2: #c77d17;
      --line: #d7c8ad;
      --line-strong: #c5b18f;
      --shadow: 0 24px 60px rgba(23, 48, 56, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Noto Sans SC", "Hiragino Sans GB", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(199,125,23,.18), transparent 24%),
        radial-gradient(circle at 80% 0%, rgba(15,118,110,.14), transparent 26%),
        linear-gradient(135deg, rgba(255,255,255,.22), rgba(255,255,255,0)),
        var(--bg);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 36px 20px 72px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(320px, .9fr);
      gap: 22px;
      align-items: stretch;
      margin-bottom: 24px;
    }}
    .hero-copy {{
      padding: 30px;
      border-radius: 28px;
      background:
        linear-gradient(145deg, rgba(255,253,248,.98), rgba(252,243,228,.92)),
        var(--panel-strong);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--accent-2);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .16em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0 0 14px;
      font-size: clamp(34px, 5vw, 54px);
      line-height: 1.02;
      letter-spacing: -0.03em;
    }}
    .lead {{
      margin: 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.75;
      max-width: 62ch;
    }}
    .hero-aside {{
      display: grid;
      gap: 16px;
    }}
    .stat-card {{
      padding: 22px;
      border-radius: 24px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,.9), rgba(247,239,226,.88));
      box-shadow: var(--shadow);
    }}
    .stat-card strong {{
      display: block;
      margin-top: 8px;
      font-size: 28px;
    }}
    .stat-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.65;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(320px, .9fr);
      gap: 22px;
      align-items: start;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 24px;
      box-shadow: var(--shadow);
    }}
    .card h2 {{
      margin: 0;
      font-size: 24px;
    }}
    .section-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(15,118,110,.12);
      color: var(--accent);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .06em;
      text-transform: uppercase;
    }}
    form {{
      display: grid;
      gap: 16px;
    }}
    .form-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .form-grid .full {{
      grid-column: 1 / -1;
    }}
    label {{
      display: grid;
      gap: 8px;
      font-weight: 600;
      color: var(--ink);
    }}
    .hint {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
      margin-top: -4px;
    }}
    input, select {{
      width: 100%;
      padding: 14px 16px;
      border: 1px solid var(--line-strong);
      border-radius: 12px;
      background: rgba(255,255,255,.92);
      font-size: 15px;
      color: var(--ink);
    }}
    input:focus, select:focus {{
      outline: 2px solid rgba(15,118,110,.18);
      border-color: var(--accent);
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin-top: 8px;
    }}
    button {{
      width: fit-content;
      padding: 13px 22px;
      border: 0;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--accent), #155e75 58%, #0e7490);
      color: white;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 18px 28px rgba(15,118,110,.18);
    }}
    .ghost-link {{
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }}
    .side-stack {{
      display: grid;
      gap: 18px;
    }}
    .result {{ margin-top: 0; }}
    .results-stack {{
      display: grid;
      gap: 18px;
    }}
    .spotlight {{
      background:
        linear-gradient(160deg, rgba(255,255,255,.96), rgba(247,241,229,.92)),
        var(--panel);
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
    }}
    .metric {{
      padding: 18px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.88);
    }}
    .metric.primary {{
      background: linear-gradient(135deg, rgba(15,118,110,.12), rgba(21,94,117,.04));
      border-color: rgba(15,118,110,.18);
    }}
    .metric.accent {{
      background: linear-gradient(135deg, rgba(199,125,23,.13), rgba(255,255,255,.9));
    }}
    .metric span, .mini-grid span, .path-list span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}
    .metric strong {{
      display: block;
      font-size: 27px;
      line-height: 1.05;
    }}
    .metric em {{
      display: inline-block;
      margin-top: 8px;
      color: var(--muted);
      font-style: normal;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .05em;
      text-transform: uppercase;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .mini-grid {{
      display: grid;
      gap: 14px;
    }}
    .mini-grid div, .path-list div {{
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(255,255,255,.84);
      border: 1px solid var(--line);
    }}
    .mini-grid strong {{
      font-size: 18px;
      line-height: 1.4;
    }}
    .path-list {{
      display: grid;
      gap: 14px;
    }}
    .path-list code {{
      display: block;
      color: var(--ink);
      white-space: normal;
      word-break: break-all;
      font-size: 13px;
      line-height: 1.7;
    }}
    .callout {{
      padding: 18px;
      border-radius: 18px;
      border: 1px dashed var(--line-strong);
      background: rgba(255,255,255,.58);
    }}
    .callout h3 {{
      margin: 0 0 10px;
      font-size: 17px;
    }}
    .callout p, .callout li {{
      color: var(--muted);
      line-height: 1.7;
      font-size: 14px;
    }}
    .callout ul {{
      margin: 0;
      padding-left: 18px;
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      margin-bottom: 18px;
    }}
    .chart-card {{
      padding: 18px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.84);
    }}
    .chart-head {{
      margin-bottom: 12px;
    }}
    .chart-head h3 {{
      margin: 0 0 6px;
      font-size: 18px;
    }}
    .chart-head p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .chart-svg {{
      width: 100%;
      height: auto;
      display: block;
      border-radius: 14px;
      background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(245,239,227,.92));
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: rgba(255,255,255,.78);
      border-radius: 16px;
      overflow: hidden;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      background: rgba(15,118,110,.08);
      font-size: 13px;
      letter-spacing: .04em;
    }}
    .error {{
      margin-top: 18px;
      border-color: #e7b6a7;
      background: #fff2ee;
    }}
    .success {{
      margin-top: 18px;
      border-color: #b7dacb;
      background: #eef9f2;
    }}
    .footer-note {{
      margin-top: 22px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
    }}
    @media (max-width: 940px) {{
      .hero,
      .layout,
      .two-col,
      .form-grid,
      .chart-grid {{
        grid-template-columns: 1fr;
      }}
      .wrap {{
        padding: 24px 16px 48px;
      }}
      .hero-copy {{
        padding: 24px;
      }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <section class="hero-copy">
        <p class="eyebrow">Solar Tariff Roller</p>
        <h1>消纳电价反算工具台</h1>
        <p class="lead">这是一张面向业务测算的单页工作台。输入目标 IRR 后，系统会沿用当前 Excel 口径自动反算用户侧综合电价、折后消纳电价，并同步生成带对账信息的 JSON 和 Excel 结果文件。</p>
      </section>
      <aside class="hero-aside">
        <section class="stat-card">
          <p class="eyebrow">Default Port</p>
          <strong>9000</strong>
          <p>建议使用 `uvicorn ... --port 9000` 启动，业务同事访问时记住这个地址就够了。</p>
        </section>
        <section class="stat-card">
          <p class="eyebrow">Work Mode</p>
          <strong>Excel 对账</strong>
          <p>输出结果默认会附带反算结果和 Excel 对账，便于测算确认、方案比选和交付留痕。</p>
        </section>
      </aside>
    </section>
    <section class="layout">
      <section>
        <section class="card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Input Panel</p>
              <h2>参数输入</h2>
            </div>
            <span class="badge">面向业务使用</span>
          </div>
          <form method="get" action="/solve">
            <div class="form-grid">
              <label>目标 IRR
                <input name="target_irr" type="number" step="0.000001" min="0" max="1" value="{target_irr}">
              </label>
              <label>访问建议端口
                <input type="text" value="9000" disabled>
              </label>
              <label>敏感性分析变量
                <select name="sensitivity_parameter">
                  {options_html}
                </select>
              </label>
              <label>敏感性步长
                <input name="sensitivity_step" type="number" step="0.000001" min="0.000001" value="{sensitivity_step}">
              </label>
              <label>敏感性起点
                <input name="sensitivity_start" type="number" step="0.000001" value="{sensitivity_start}">
              </label>
              <label>敏感性终点
                <input name="sensitivity_stop" type="number" step="0.000001" value="{sensitivity_stop}">
              </label>
              <label class="full">测算表路径
                <input name="calculation_workbook" type="text" value="{escape(calculation_workbook)}">
              </label>
              <label class="full">电站统计表路径
                <input name="station_workbook" type="text" value="{escape(station_workbook)}">
              </label>
            </div>
            <p class="hint">如果后续要切项目，直接替换两条文件路径即可，系统会重新解析并反算。</p>
            <div class="actions">
              <button type="submit">开始反算</button>
              <a class="ghost-link" href="/api/solve?target_irr={target_irr}&calculation_workbook={escape(calculation_workbook)}&station_workbook={escape(station_workbook)}&sensitivity_parameter={escape(sensitivity_parameter)}&sensitivity_start={sensitivity_start}&sensitivity_stop={sensitivity_stop}&sensitivity_step={sensitivity_step}">查看 JSON API</a>
            </div>
          </form>
        </section>
        <section class="card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Monthly Update</p>
              <h2>更新本月真实数据</h2>
            </div>
            <span class="badge">写入后自动重算</span>
          </div>
          <form method="get" action="/update-monthly">
            <input type="hidden" name="target_irr" value="{target_irr}">
            <input type="hidden" name="calculation_workbook" value="{escape(calculation_workbook)}">
            <input type="hidden" name="station_workbook" value="{escape(station_workbook)}">
            <input type="hidden" name="sensitivity_parameter" value="{escape(sensitivity_parameter)}">
            <input type="hidden" name="sensitivity_start" value="{sensitivity_start}">
            <input type="hidden" name="sensitivity_stop" value="{sensitivity_stop}">
            <input type="hidden" name="sensitivity_step" value="{sensitivity_step}">
            <div class="form-grid">
              <label>月份
                <input name="period_label" type="text" placeholder="例如 2026-05" value="{escape(update_period_label)}">
              </label>
              <label>发电量(万kWh)
                <input name="generation_10k_kwh" type="number" step="0.0001" min="0" value="{'' if update_generation_10k_kwh is None else update_generation_10k_kwh}">
              </label>
              <label>自用电量(万kWh)
                <input name="self_consumed_10k_kwh" type="number" step="0.0001" min="0" value="{'' if update_self_consumed_10k_kwh is None else update_self_consumed_10k_kwh}">
              </label>
              <label>上网电量(万kWh)
                <input name="exported_10k_kwh" type="number" step="0.0001" min="0" value="{'' if update_exported_10k_kwh is None else update_exported_10k_kwh}">
              </label>
            </div>
            <p class="hint">建议每个月补录一次真实发电量、自用电量和上网电量。系统会把该月份写入项目更新文件，并用最近 12 个月实际数据刷新消纳率后重新测算。</p>
            <div class="actions">
              <button type="submit">保存并重算</button>
            </div>
          </form>
        </section>
        {error_html}
        {success_html}
        {result_html}
      </section>
      <aside class="side-stack">
        <section class="card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Usage</p>
              <h2>启动方式</h2>
            </div>
          </div>
          <div class="callout">
            <h3>推荐命令</h3>
            <p><code>PYTHONPATH=src uvicorn solar_tariff_roller.api.app:create_app --factory --host 127.0.0.1 --port 9000</code></p>
          </div>
        </section>
        <section class="card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Workflow</p>
              <h2>使用流程</h2>
            </div>
          </div>
          <div class="callout">
            <ul>
              <li>输入目标 IRR 和两份 Excel 路径。</li>
              <li>点击“开始反算”，系统自动解析、测算、反推电价。</li>
              <li>每月把真实发电、自用、上网数据补录进系统，页面会自动重算。</li>
              <li>结果页会展示关键价格、校验 NPV/IRR 和导出文件路径。</li>
              <li>导出的 Excel 中会附带 `反算结果`、`敏感性分析`、`月度数据` 和 `Excel对账` 工作表。</li>
            </ul>
          </div>
        </section>
        <section class="card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Endpoints</p>
              <h2>可用接口</h2>
            </div>
          </div>
          <div class="callout">
            <p><strong>页面表单:</strong> <code>/</code> 与 <code>/solve</code></p>
            <p><strong>月度更新:</strong> <code>/update-monthly</code></p>
            <p><strong>JSON 接口:</strong> <code>/api/solve</code></p>
            <p><strong>文档:</strong> <code>/docs</code></p>
          </div>
        </section>
      </aside>
    </section>
    <p class="footer-note">这版页面已经支持按月补录真实运营数据，并在同一页里完成重算与导出。后续如果继续完善，可以再补批量导入、更新日志和多项目切换。</p>
  </main>
</body>
</html>"""


def _build_line_chart_svg(x_values: list[float], y_values: list[float], y_label: str) -> str:
    """Render a simple inline SVG line chart."""

    width = 640
    height = 300
    left = 56
    right = 24
    top = 28
    bottom = 40
    inner_width = width - left - right
    inner_height = height - top - bottom

    min_y = min(y_values)
    max_y = max(y_values)
    if max_y == min_y:
        max_y += 1
        min_y -= 1

    points = []
    labels = []
    for index, (x_value, y_value) in enumerate(zip(x_values, y_values)):
        x = left + (inner_width * index / max(1, len(x_values) - 1))
        y = top + inner_height * (1 - (y_value - min_y) / (max_y - min_y))
        points.append(f"{x:.2f},{y:.2f}")
        labels.append(
            f'<text x="{x:.2f}" y="{height - 12}" text-anchor="middle" class="axis-label">{x_value:.4f}</text>'
        )

    y_ticks = []
    for step in range(5):
        tick_value = min_y + (max_y - min_y) * (4 - step) / 4
        y = top + inner_height * step / 4
        y_ticks.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" class="grid-line" />'
            f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" class="axis-label">{tick_value:.2f}</text>'
        )

    return f"""
    <svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="敏感性分析折线图">
      <style>
        .grid-line {{ stroke: #d8ccbb; stroke-width: 1; }}
        .axis-line {{ stroke: #8ea0a6; stroke-width: 1.2; }}
        .axis-label {{ fill: #5b6d73; font-size: 12px; font-family: sans-serif; }}
        .line {{ fill: none; stroke: #0f766e; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }}
        .dot {{ fill: #c77d17; stroke: white; stroke-width: 2; }}
        .title {{ fill: #173038; font-size: 13px; font-weight: 700; font-family: sans-serif; }}
      </style>
      {''.join(y_ticks)}
      <line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" class="axis-line" />
      <line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" class="axis-line" />
      <text x="{left}" y="16" class="title">{escape(y_label)}</text>
      <polyline points="{' '.join(points)}" class="line" />
      {''.join(f'<circle cx="{p.split(",")[0]}" cy="{p.split(",")[1]}" r="5" class="dot" />' for p in points)}
      {''.join(labels)}
    </svg>
    """


def _build_bar_chart_svg(x_values: list[float], y_values: list[float], y_label: str) -> str:
    """Render a simple inline SVG bar chart."""

    width = 640
    height = 300
    left = 56
    right = 24
    top = 28
    bottom = 40
    inner_width = width - left - right
    inner_height = height - top - bottom

    max_y = max(y_values) if y_values else 1
    if max_y == 0:
        max_y = 1
    bar_width = inner_width / max(1, len(x_values)) * 0.6

    bars = []
    labels = []
    for index, (x_value, y_value) in enumerate(zip(x_values, y_values)):
        center_x = left + inner_width * (index + 0.5) / max(1, len(x_values))
        x = center_x - bar_width / 2
        bar_height = inner_height * (y_value / max_y)
        y = top + inner_height - bar_height
        bars.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" rx="8" class="bar" />'
            f'<text x="{center_x:.2f}" y="{y - 8:.2f}" text-anchor="middle" class="axis-label">{y_value:.4f}</text>'
        )
        labels.append(
            f'<text x="{center_x:.2f}" y="{height - 12}" text-anchor="middle" class="axis-label">{x_value:.4f}</text>'
        )

    y_ticks = []
    for step in range(5):
        tick_value = max_y * (4 - step) / 4
        y = top + inner_height * step / 4
        y_ticks.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" class="grid-line" />'
            f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" class="axis-label">{tick_value:.4f}</text>'
        )

    return f"""
    <svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="敏感性分析柱状图">
      <style>
        .grid-line {{ stroke: #d8ccbb; stroke-width: 1; }}
        .axis-line {{ stroke: #8ea0a6; stroke-width: 1.2; }}
        .axis-label {{ fill: #5b6d73; font-size: 12px; font-family: sans-serif; }}
        .bar {{ fill: url(#barGradient); }}
        .title {{ fill: #173038; font-size: 13px; font-weight: 700; font-family: sans-serif; }}
      </style>
      <defs>
        <linearGradient id="barGradient" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="#0f766e" />
          <stop offset="100%" stop-color="#c77d17" />
        </linearGradient>
      </defs>
      {''.join(y_ticks)}
      <line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" class="axis-line" />
      <line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" class="axis-line" />
      <text x="{left}" y="16" class="title">{escape(y_label)}</text>
      {''.join(bars)}
      {''.join(labels)}
    </svg>
    """
