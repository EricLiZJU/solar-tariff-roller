"""Simple FastAPI UI for target IRR solving."""

from __future__ import annotations

import mimetypes
from html import escape
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from solar_tariff_roller.schemas.input import MonthlyGenerationRecordInput
from solar_tariff_roller.services.calc import (
    analyze_sensitivity,
    build_cashflow_result,
    generate_sensitivity_values,
)
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
DEFAULT_UPLOAD_DIR = Path("data/processed/uploads")
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

    @app.get("/help", response_class=HTMLResponse)
    def help_page() -> str:
        return _render_help_page()

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

    @app.post("/solve", response_class=HTMLResponse)
    async def solve_page_upload(
        target_irr: float = Form(...),
        calculation_workbook: str = Form(""),
        station_workbook: str = Form(""),
        sensitivity_parameter: str = Form("tariff.consumer_tariff"),
        sensitivity_start: float = Form(0.68),
        sensitivity_stop: float = Form(0.76),
        sensitivity_step: float = Form(0.04),
        calculation_workbook_file: UploadFile | None = File(default=None),
        station_workbook_file: UploadFile | None = File(default=None),
    ) -> str:
        calculation_workbook, station_workbook = await _resolve_workbook_inputs(
            calculation_workbook,
            station_workbook,
            calculation_workbook_file,
            station_workbook_file,
        )
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

    @app.post("/update-monthly", response_class=HTMLResponse)
    async def update_monthly_page_upload(
        target_irr: float = Form(...),
        calculation_workbook: str = Form(""),
        station_workbook: str = Form(""),
        sensitivity_parameter: str = Form("tariff.consumer_tariff"),
        sensitivity_start: float = Form(0.68),
        sensitivity_stop: float = Form(0.76),
        sensitivity_step: float = Form(0.04),
        period_label: str = Form(...),
        generation_10k_kwh: float = Form(...),
        self_consumed_10k_kwh: float = Form(...),
        exported_10k_kwh: float = Form(...),
        calculation_workbook_file: UploadFile | None = File(default=None),
        station_workbook_file: UploadFile | None = File(default=None),
    ) -> str:
        calculation_workbook, station_workbook = await _resolve_workbook_inputs(
            calculation_workbook,
            station_workbook,
            calculation_workbook_file,
            station_workbook_file,
        )
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

    @app.get("/download")
    def download_file(path: str, filename: str | None = None) -> FileResponse:
        file_path = Path(path).expanduser().resolve()
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if not _is_path_allowed(file_path):
            raise HTTPException(status_code=403, detail="File path is not allowed")

        media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return FileResponse(file_path, media_type=media_type, filename=filename or file_path.name)

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
    calculation_result = build_cashflow_result(payload)
    exports = export_calculation_bundle(
        payload,
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
        "calculation_result": calculation_result,
        "exports": exports,
        "update_store_path": update_store_path,
        "persisted_updates": persisted_updates,
    }


async def _resolve_workbook_inputs(
    calculation_workbook: str,
    station_workbook: str,
    calculation_workbook_file: UploadFile | None,
    station_workbook_file: UploadFile | None,
) -> tuple[str, str]:
    """Resolve workbook paths from either manual paths or uploaded files."""

    calculation_path = calculation_workbook.strip()
    station_path = station_workbook.strip()

    if calculation_workbook_file is not None and calculation_workbook_file.filename:
        calculation_path = await _save_uploaded_file(calculation_workbook_file)
    if station_workbook_file is not None and station_workbook_file.filename:
        station_path = await _save_uploaded_file(station_workbook_file)

    if not calculation_path or not station_path:
        raise ValueError("请提供测算表和电站统计表，可输入路径或直接选择文件")

    return calculation_path, station_path


async def _save_uploaded_file(upload: UploadFile) -> str:
    """Persist one uploaded workbook locally and return its saved path."""

    suffix = Path(upload.filename or "").suffix or ".xlsx"
    target_dir = DEFAULT_UPLOAD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = _sanitize_filename(Path(upload.filename or "upload").stem)
    target_path = target_dir / f"{safe_stem}_{uuid4().hex[:8]}{suffix}"

    content = await upload.read()
    target_path.write_bytes(content)
    await upload.close()
    return str(target_path.resolve())


def _sanitize_filename(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)
    return sanitized.strip("_") or "upload"


def _is_path_allowed(path: Path) -> bool:
    """Restrict downloadable files to the project data directories."""

    allowed_roots = [
        Path.cwd().resolve() / "data",
    ]
    return any(root == path or root in path.parents for root in allowed_roots)


def _build_download_url(path: Path) -> str:
    safe_name = quote(path.name)
    return f"/download?path={quote(str(path))}&filename={safe_name}"


def _render_result_html(context: dict[str, object]) -> str:
    """Build the result area for solve and update pages."""

    payload = context["payload"]
    solved = context["solved"]
    sensitivity = context["sensitivity"]
    calculation_result = context["calculation_result"]
    exports = context["exports"]
    update_store_path = context["update_store_path"]
    persisted_updates = context["persisted_updates"]
    first_year = calculation_result.annual_projections[0] if calculation_result.annual_projections else None
    annual_preview = calculation_result.annual_projections[:8]
    rolling_monthly_preview = calculation_result.monthly_projections[:12]
    actual_month_count = sum(1 for row in calculation_result.monthly_projections if row.period_type == "actual")
    historical_month_count = sum(1 for row in calculation_result.monthly_projections if row.period_type == "historical")
    projected_month_count = sum(1 for row in calculation_result.monthly_projections if row.period_type == "projected")

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
    actual_monthly_rows = "".join(
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
    rolling_monthly_preview_rows = "".join(
        f"""
        <tr class="period-row {_period_row_class(row.period_type)}" data-period="{escape(row.period_type)}">
          <td>{row.month_index}</td>
          <td>{row.operating_year}</td>
          <td>{row.month_in_year}</td>
          <td>{_render_period_type_label(row.period_type)}</td>
          <td>{row.gross_revenue_10k_cny:.2f}</td>
          <td>{row.total_cost_10k_cny:.2f}</td>
          <td>{row.vat_payable_10k_cny:.2f}</td>
          <td>{row.surcharge_tax_10k_cny:.2f}</td>
          <td>{row.net_cashflow_10k_cny:.2f}</td>
          <td>{row.cumulative_cashflow_10k_cny:.2f}</td>
        </tr>
        """
        for row in rolling_monthly_preview
    )
    annual_rows = "".join(
        f"""
        <tr>
          <td>{row.year}</td>
          <td>{row.generation_10k_kwh:.2f}</td>
          <td>{row.gross_revenue_10k_cny:.2f}</td>
          <td>{row.revenue_excluding_vat_10k_cny:.2f}</td>
          <td>{row.output_vat_10k_cny:.2f}</td>
          <td>{row.annual_cost_10k_cny:.2f}</td>
          <td>{row.input_vat_10k_cny:.2f}</td>
          <td>{row.annual_vat_balance_10k_cny:.2f}</td>
          <td>{row.surcharge_tax_10k_cny:.2f}</td>
          <td>{row.net_cashflow_10k_cny:.2f}</td>
          <td>{row.discounted_cashflow_10k_cny:.2f}</td>
        </tr>
        """
        for row in annual_preview
    )
    annual_full_rows = "".join(
        f"""
        <tr>
          <td>{row.year}</td>
          <td>{row.degradation_pct:.2f}%</td>
          <td>{row.generation_10k_kwh:.2f}</td>
          <td>{row.gross_revenue_10k_cny:.2f}</td>
          <td>{row.revenue_excluding_vat_10k_cny:.2f}</td>
          <td>{row.output_vat_10k_cny:.2f}</td>
          <td>{row.construction_cost_10k_cny:.2f}</td>
          <td>{row.annual_rent_10k_cny:.2f}</td>
          <td>{row.annual_om_10k_cny:.2f}</td>
          <td>{row.annual_cost_10k_cny:.2f}</td>
          <td>{row.input_vat_10k_cny:.2f}</td>
          <td>{row.annual_vat_balance_10k_cny:.2f}</td>
          <td>{row.surcharge_tax_10k_cny:.2f}</td>
          <td>{row.net_cashflow_10k_cny:.2f}</td>
          <td>{row.cumulative_cashflow_10k_cny:.2f}</td>
          <td>{row.present_value_factor:.4f}</td>
          <td>{row.discounted_cashflow_10k_cny:.2f}</td>
          <td>{row.cumulative_discounted_cashflow_10k_cny:.2f}</td>
        </tr>
        """
        for row in calculation_result.annual_projections
    )
    rolling_monthly_full_rows = "".join(
        f"""
        <tr class="period-row {_period_row_class(row.period_type)}" data-period="{escape(row.period_type)}">
          <td>{row.month_index}</td>
          <td>{row.operating_year}</td>
          <td>{row.month_in_year}</td>
          <td>{_render_period_type_label(row.period_type)}</td>
          <td>{row.generation_10k_kwh:.4f}</td>
          <td>{row.self_consumed_10k_kwh:.4f}</td>
          <td>{row.exported_10k_kwh:.4f}</td>
          <td>{row.gross_revenue_10k_cny:.2f}</td>
          <td>{row.total_cost_10k_cny:.2f}</td>
          <td>{row.input_vat_10k_cny:.2f}</td>
          <td>{row.output_vat_10k_cny:.2f}</td>
          <td>{row.vat_payable_10k_cny:.2f}</td>
          <td>{row.surcharge_tax_10k_cny:.2f}</td>
          <td>{row.net_cashflow_10k_cny:.2f}</td>
          <td>{row.discounted_cashflow_10k_cny:.2f}</td>
          <td>{row.cumulative_cashflow_10k_cny:.2f}</td>
        </tr>
        """
        for row in calculation_result.monthly_projections
    )
    npv_chart_svg = _build_line_chart_svg(
        [point.parameter_value for point in sensitivity.points],
        [point.project_npv_10k_cny for point in sensitivity.points],
        "NPV(万元)",
        svg_id="npv-chart-svg",
    )
    irr_chart_svg = _build_bar_chart_svg(
        [point.parameter_value for point in sensitivity.points],
        [0.0 if point.project_irr is None else point.project_irr for point in sensitivity.points],
        "IRR",
        svg_id="irr-chart-svg",
    )
    excel_download_url = _build_download_url(Path(exports["excel"]))
    json_download_url = _build_download_url(Path(exports["json"]))

    return f"""
    <section class="results-board">
      <section class="card toolbar-card panel-span-2">
        <div class="toolbar">
          <div class="toolbar-copy">
            <p class="eyebrow">Downloads</p>
            <h2>结果与图表下载</h2>
          </div>
          <div class="toolbar-actions">
            <a class="button-link secondary" href="{excel_download_url}">下载 Excel</a>
            <a class="button-link secondary" href="{json_download_url}">下载 JSON</a>
            <button type="button" class="button-link secondary" onclick="downloadSvg('npv-chart-svg', 'npv_sensitivity.svg')">下载 NPV 图</button>
            <button type="button" class="button-link secondary" onclick="downloadSvg('irr-chart-svg', 'irr_sensitivity.svg')">下载 IRR 图</button>
          </div>
        </div>
      </section>
      <section class="card result spotlight panel-span-2">
        <div class="section-head">
          <div>
            <p class="eyebrow">Solve Result</p>
            <h2>反算结果</h2>
          </div>
          <span class="badge">滚动 IRR 已咬合</span>
        </div>
        <div class="metric-grid">
          <article class="metric primary"><span>目标 IRR</span><strong>{solved.target_irr:.6f}</strong></article>
          <article class="metric accent"><span>反算折后消纳电价</span><strong>{solved.solved_discounted_consumer_tariff:.6f}</strong><em>元/kWh</em></article>
          <article class="metric accent"><span>折算自用电综合电价</span><strong>{solved.solved_consumer_tariff:.6f}</strong><em>元/kWh</em></article>
          <article class="metric"><span>校验 NPV</span><strong>{solved.solved_npv_10k_cny:.6f}</strong><em>万元</em></article>
          <article class="metric"><span>校验滚动 IRR</span><strong>{solved.solved_project_irr:.6f}</strong></article>
        </div>
      </section>
      <section class="card panel-span-2">
        <div class="section-head">
          <div>
            <p class="eyebrow">Project Snapshot</p>
            <h2>项目概览与当前文件</h2>
          </div>
        </div>
        <div class="project-strip">
          <div class="mini-grid compact">
            <div><span>项目名称</span><strong>{escape(payload.project.project_name)}</strong></div>
            <div><span>电站名称</span><strong>{escape(payload.project.station_name or "-")}</strong></div>
            <div><span>装机容量</span><strong>{payload.project.capacity_mwp:.6f} MWp</strong></div>
            <div><span>IRR 年化方式</span><strong>{escape(payload.rolling.irr_annualization_mode)}</strong></div>
            <div><span>生效自用比例</span><strong>{payload.consumption.self_consumption_ratio:.4%}</strong></div>
            <div><span>月度更新条数</span><strong>{len(persisted_updates)}</strong></div>
          </div>
          <div class="path-list inline">
            <div><span>Excel 结果文件</span><code>{escape(str(exports["excel"]))}</code></div>
            <div><span>月度更新文件</span><code>{escape(str(update_store_path))}</code></div>
          </div>
        </div>
      </section>
      <section class="card panel-span-2">
        <div class="section-head">
          <div>
            <p class="eyebrow">Horizontal Workspace</p>
            <h2>计算过程与运营数据</h2>
          </div>
        </div>
        <div class="workspace-triple workspace-quad">
          <section class="subpanel">
            <div class="section-head tight"><div><p class="eyebrow">Calculation Trace</p><h3>计算中间过程</h3></div></div>
            <div class="accordion-stack">
              <details class="accordion" open><summary>滚动测算基础口径</summary><div class="accordion-body"><div class="mini-grid compact"><div><span>滚动起算年发电量</span><strong>{calculation_result.initial_generation_10k_kwh:.4f} 万kWh</strong></div><div><span>余电上网电价</span><strong>{payload.tariff.feed_in_tariff:.6f} 元/kWh</strong></div><div><span>初始投资流出</span><strong>{calculation_result.initial_outflow_10k_cny:.2f} 万元</strong></div><div><span>资本开支进项税</span><strong>{calculation_result.capex_input_vat_10k_cny:.2f} 万元</strong></div></div></div></details>
              <details class="accordion" open><summary>当前滚动年度电量拆分</summary><div class="accordion-body"><div class="mini-grid compact"><div><span>当前滚动年度发电量</span><strong>{0.0 if first_year is None else first_year.generation_10k_kwh:.2f} 万kWh</strong></div><div><span>累计衰减</span><strong>{0.0 if first_year is None else first_year.degradation_pct:.2f}%</strong></div><div><span>当前滚动年度自用电量</span><strong>{0.0 if first_year is None else first_year.self_consumed_10k_kwh:.3f} 万kWh</strong></div><div><span>当前滚动年度上网电量</span><strong>{0.0 if first_year is None else first_year.exported_10k_kwh:.3f} 万kWh</strong></div></div></div></details>
              <details class="accordion"><summary>当前滚动年度收益与税费</summary><div class="accordion-body"><div class="mini-grid compact"><div><span>当前滚动年度含税收入</span><strong>{0.0 if first_year is None else first_year.gross_revenue_10k_cny:.2f} 万元</strong></div><div><span>当前滚动年度不含税收入</span><strong>{0.0 if first_year is None else first_year.revenue_excluding_vat_10k_cny:.2f} 万元</strong></div><div><span>当前滚动年度销项税金</span><strong>{0.0 if first_year is None else first_year.output_vat_10k_cny:.2f} 万元</strong></div><div><span>当前滚动年度成本费用小计</span><strong>{0.0 if first_year is None else first_year.annual_cost_10k_cny:.2f} 万元</strong></div><div><span>当前滚动年度进项税金</span><strong>{0.0 if first_year is None else first_year.input_vat_10k_cny:.2f} 万元</strong></div><div><span>当前滚动年度应缴增值税</span><strong>{0.0 if first_year is None else first_year.annual_vat_balance_10k_cny:.2f} 万元</strong></div><div><span>当前滚动年度附加税</span><strong>{0.0 if first_year is None else first_year.surcharge_tax_10k_cny:.2f} 万元</strong></div></div></div></details>
              <details class="accordion"><summary>滚动现金流结果</summary><div class="accordion-body"><div class="mini-grid compact"><div><span>当前滚动年度净现金流</span><strong>{0.0 if first_year is None else first_year.net_cashflow_10k_cny:.2f} 万元</strong></div><div><span>当前滚动年度折现系数</span><strong>{0.0 if first_year is None else first_year.present_value_factor:.4f}</strong></div><div><span>滚动月度 IRR</span><strong>{'' if calculation_result.monthly_irr is None else f'{calculation_result.monthly_irr:.6f}'}</strong></div><div><span>项目累计净现金流</span><strong>{calculation_result.cumulative_cashflow_10k_cny:.2f} 万元</strong></div></div></div></details>
            </div>
          </section>
          <section class="subpanel">
            <div class="section-head tight"><div><p class="eyebrow">Annual Preview</p><h3>滚动测算年度汇总预览</h3></div><span class="badge">前 8 个滚动年度</span></div>
            <div class="table-wrap compact-table"><table class="sticky-table"><thead><tr><th>年份</th><th>发电量</th><th>含税收入</th><th>不含税收入</th><th>销项税金</th><th>成本费用小计</th><th>进项税金</th><th>应缴增值税</th><th>附加税</th><th>当期现金流</th><th>当期净现值</th></tr></thead><tbody>{annual_rows}</tbody></table></div>
            <details class="accordion expand-table"><summary>展开查看完整 25 个滚动年度汇总</summary><div class="accordion-body"><div class="table-wrap compact-table tall-table"><table class="sticky-table"><thead><tr><th>年份</th><th>累计衰减</th><th>发电量</th><th>含税收入</th><th>不含税收入</th><th>销项税金</th><th>建造成本</th><th>租金</th><th>运维费</th><th>成本费用小计</th><th>进项税金</th><th>应缴增值税</th><th>附加税</th><th>当期现金流</th><th>累计现金净流量</th><th>现值系数</th><th>当期净现值</th><th>累计净现值</th></tr></thead><tbody>{annual_full_rows}</tbody></table></div></div></details>
          </section>
          <section class="subpanel">
            <div class="section-head tight"><div><p class="eyebrow">Monthly Preview</p><h3>滚动测算月度汇总预览</h3></div><span class="badge">前 12 个滚动月份</span></div>
            <div class="month-legend">
              <span class="legend-pill actual">真实替换 {actual_month_count}</span>
              <span class="legend-pill historical">历史基线 {historical_month_count}</span>
              <span class="legend-pill projected">预测月份 {projected_month_count}</span>
            </div>
            <div class="filter-bar">
              <button type="button" class="filter-chip active" data-target="monthly-preview-table" data-filter="all" onclick="filterPeriodRows(this)">全部</button>
              <button type="button" class="filter-chip" data-target="monthly-preview-table" data-filter="actual" onclick="filterPeriodRows(this)">只看真实</button>
              <button type="button" class="filter-chip" data-target="monthly-preview-table" data-filter="historical" onclick="filterPeriodRows(this)">只看历史</button>
              <button type="button" class="filter-chip" data-target="monthly-preview-table" data-filter="projected" onclick="filterPeriodRows(this)">只看预测</button>
            </div>
            <div class="table-wrap compact-table"><table id="monthly-preview-table" class="sticky-table"><thead><tr><th>月份序号</th><th>年度</th><th>月次</th><th>类型</th><th>总收入</th><th>成本</th><th>增值税</th><th>附加税</th><th>净现金流</th><th>累计现金流</th></tr></thead><tbody>{rolling_monthly_preview_rows}</tbody></table></div>
            <details class="accordion expand-table"><summary>展开查看完整 300 个月滚动汇总</summary><div class="accordion-body"><div class="month-legend"><span class="legend-pill actual">真实替换 {actual_month_count}</span><span class="legend-pill historical">历史基线 {historical_month_count}</span><span class="legend-pill projected">预测月份 {projected_month_count}</span></div><div class="filter-bar"><button type="button" class="filter-chip active" data-target="monthly-full-table" data-filter="all" onclick="filterPeriodRows(this)">全部</button><button type="button" class="filter-chip" data-target="monthly-full-table" data-filter="actual" onclick="filterPeriodRows(this)">只看真实</button><button type="button" class="filter-chip" data-target="monthly-full-table" data-filter="historical" onclick="filterPeriodRows(this)">只看历史</button><button type="button" class="filter-chip" data-target="monthly-full-table" data-filter="projected" onclick="filterPeriodRows(this)">只看预测</button></div><div class="table-wrap compact-table tall-table"><table id="monthly-full-table" class="sticky-table"><thead><tr><th>月份序号</th><th>年度</th><th>月次</th><th>类型</th><th>发电量</th><th>自用电量</th><th>上网电量</th><th>总收入</th><th>成本</th><th>进项税</th><th>销项税</th><th>增值税</th><th>附加税</th><th>净现金流</th><th>折现现金流</th><th>累计现金流</th></tr></thead><tbody>{rolling_monthly_full_rows}</tbody></table></div></div></details>
          </section>
          <section class="subpanel">
            <div class="section-head tight"><div><p class="eyebrow">Monthly Actuals</p><h3>最近 12 个月真实数据</h3></div><span class="badge">自动重算</span></div>
            <div class="table-wrap compact-table"><table class="sticky-table"><thead><tr><th>月份</th><th>发电量</th><th>自用电量</th><th>上网电量</th><th>消纳率</th></tr></thead><tbody>{actual_monthly_rows}</tbody></table></div>
          </section>
        </div>
      </section>
      <section class="card panel-span-2">
        <div class="section-head">
          <div>
            <p class="eyebrow">Sensitivity Analysis</p>
            <h2>敏感性分析</h2>
          </div>
          <span class="badge">{escape(SENSITIVITY_OPTIONS.get(sensitivity.parameter_name, sensitivity.parameter_name))}</span>
        </div>
        <div class="chart-grid large">
          <section class="chart-card"><div class="chart-head"><h3>NPV 折线图</h3><p>观察参数变化对净现值的影响趋势</p></div>{npv_chart_svg}</section>
          <section class="chart-card"><div class="chart-head"><h3>IRR 柱状图</h3><p>观察参数变化对 IRR 的抬升或压缩</p></div>{irr_chart_svg}</section>
        </div>
        <div class="table-wrap compact-table"><table class="sticky-table"><thead><tr><th>参数值</th><th>NPV(万元)</th><th>IRR</th><th>累计现金流(万元)</th><th>折后用户侧电价(元/kWh)</th></tr></thead><tbody>{sensitivity_rows}</tbody></table></div>
      </section>
    </section>
    """


def _render_period_type_label(period_type: str) -> str:
    if period_type == "actual":
        return "真实"
    if period_type == "historical":
        return "历史"
    return "预测"


def _period_row_class(period_type: str) -> str:
    if period_type == "actual":
        return "period-actual"
    if period_type == "historical":
        return "period-historical"
    return "period-projected"


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
      --bg: #f3f7fb;
      --panel: rgba(255, 255, 255, 0.9);
      --panel-strong: #ffffff;
      --panel-soft: #f8fbff;
      --ink: #0f172a;
      --muted: #64748b;
      --accent: #0f766e;
      --accent-2: #2563eb;
      --accent-soft: rgba(37, 99, 235, 0.08);
      --line: #d9e2ec;
      --line-strong: #c3d0df;
      --shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "SF Pro Display", "Noto Sans SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 0% 0%, rgba(15,118,110,.10), transparent 28%),
        radial-gradient(circle at 100% 0%, rgba(37,99,235,.10), transparent 24%),
        linear-gradient(180deg, rgba(255,255,255,.72), rgba(255,255,255,.38)),
        var(--bg);
    }}
    .wrap {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 28px 22px 40px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
      align-items: start;
      margin-bottom: 18px;
    }}
    .hero-copy {{
      padding: 28px 30px;
      border-radius: 24px;
      background:
        linear-gradient(135deg, rgba(255,255,255,.98), rgba(248,251,255,.92)),
        var(--panel-strong);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}
    .hero-topbar {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }}
    .hero-main {{
      min-width: 0;
    }}
    .tab-nav {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px;
      border-radius: 999px;
      background: rgba(248,251,255,.96);
      border: 1px solid var(--line);
    }}
    .tab-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      padding: 8px 16px;
      border-radius: 999px;
      color: var(--muted);
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
    }}
    .tab-link.active {{
      color: var(--ink);
      background: #ffffff;
      box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--accent-2);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .12em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: clamp(34px, 4vw, 52px);
      line-height: 1.04;
      letter-spacing: -0.03em;
    }}
    .lead {{
      margin: 0;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.72;
      max-width: 70ch;
    }}
    .hero-strip {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
    }}
    .hero-chip {{
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(248,251,255,.88);
      border: 1px solid var(--line);
    }}
    .hero-chip strong {{
      display: block;
      margin-bottom: 6px;
      font-size: 15px;
    }}
    .hero-chip span {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }}
    .layout {{
      display: block;
      width: 100%;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    .card h2 {{
      margin: 0;
      font-size: 22px;
      letter-spacing: -0.02em;
    }}
    .toolbar-card {{
      padding: 16px 18px;
      background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(246,250,255,.94));
    }}
    .toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .toolbar-copy h2 {{
      font-size: 18px;
    }}
    .toolbar-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .section-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 7px 11px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent-2);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .06em;
      text-transform: uppercase;
      border: 1px solid rgba(37,99,235,.1);
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
      padding: 13px 14px;
      border: 1px solid var(--line-strong);
      border-radius: 14px;
      background: rgba(248, 251, 255, 0.96);
      font-size: 14px;
      color: var(--ink);
    }}
    input[type="month"] {{
      min-height: 46px;
    }}
    input:focus, select:focus {{
      outline: 2px solid rgba(37,99,235,.12);
      border-color: var(--accent-2);
    }}
    .file-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
    }}
    .hidden-file {{
      position: absolute;
      width: 1px;
      height: 1px;
      opacity: 0;
      pointer-events: none;
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
      padding: 12px 20px;
      border: 0;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--accent-2), #1d4ed8 55%, #0f766e);
      color: white;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 14px 28px rgba(37,99,235,.18);
    }}
    .button-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      padding: 10px 16px;
      border-radius: 999px;
      border: 1px solid transparent;
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}
    .button-link.secondary {{
      color: var(--accent-2);
      background: rgba(255,255,255,.92);
      border-color: var(--line-strong);
      box-shadow: none;
    }}
    .head-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .result {{ margin-top: 0; }}
    .results-board {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .panel-span-2 {{ grid-column: 1 / -1; }}
    .spotlight {{
      background:
        linear-gradient(135deg, rgba(255,255,255,.98), rgba(243,247,251,.94)),
        var(--panel);
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric {{
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.82);
    }}
    .metric.primary {{
      background: linear-gradient(135deg, rgba(37,99,235,.10), rgba(37,99,235,.03));
      border-color: rgba(37,99,235,.12);
    }}
    .metric.accent {{
      background: linear-gradient(135deg, rgba(15,118,110,.10), rgba(255,255,255,.9));
    }}
    .metric span, .mini-grid span, .path-list span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }}
    .metric strong {{
      display: block;
      font-size: 24px;
      line-height: 1.1;
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
    .mini-grid {{
      display: grid;
      gap: 14px;
    }}
    .mini-grid.compact {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .mini-grid div, .path-list div {{
      padding: 13px 14px;
      border-radius: 16px;
      background: var(--panel-soft);
      border: 1px solid var(--line);
    }}
    .mini-grid strong {{
      font-size: 17px;
      line-height: 1.4;
    }}
    .path-list {{
      display: grid;
      gap: 12px;
    }}
    .path-list.inline {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .project-strip {{
      display: grid;
      grid-template-columns: 1.3fr 1fr;
      gap: 14px;
      align-items: stretch;
    }}
    .path-list code {{
      display: block;
      color: var(--ink);
      white-space: normal;
      word-break: break-all;
      font-size: 12px;
      line-height: 1.65;
    }}
    .callout {{
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: var(--panel-soft);
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
    .callout ol {{
      margin: 0;
      padding-left: 20px;
      color: var(--muted);
      line-height: 1.8;
      font-size: 14px;
    }}
    .accordion-stack {{
      display: grid;
      gap: 14px;
    }}
    .workspace-triple {{
      display: grid;
      grid-template-columns: 1.05fr 1.2fr .9fr;
      gap: 14px;
      align-items: start;
    }}
    .workspace-quad {{
      grid-template-columns: 1fr 1.05fr 1.15fr .9fr;
    }}
    .subpanel {{
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,.72);
      padding: 14px;
    }}
    .section-head.tight {{
      margin-bottom: 12px;
    }}
    .section-head.tight h3 {{
      margin: 0;
      font-size: 18px;
      letter-spacing: -0.02em;
    }}
    .accordion {{
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel-soft);
      overflow: hidden;
    }}
    .accordion summary {{
      list-style: none;
      cursor: pointer;
      padding: 16px 18px;
      font-size: 15px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .accordion summary::-webkit-details-marker {{
      display: none;
    }}
    .accordion summary::after {{
      content: "展开";
      font-size: 11px;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: var(--accent-2);
      background: rgba(37,99,235,.08);
      border-radius: 999px;
      padding: 6px 10px;
    }}
    .accordion[open] summary::after {{
      content: "收起";
    }}
    .accordion-body {{
      padding: 0 18px 18px;
    }}
    .month-legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .legend-pill {{
      display: inline-flex;
      align-items: center;
      padding: 7px 11px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.92);
      color: var(--muted);
    }}
    .legend-pill.actual {{
      background: rgba(15,118,110,.10);
      color: #0f766e;
      border-color: rgba(15,118,110,.18);
    }}
    .legend-pill.historical {{
      background: rgba(37,99,235,.08);
      color: #2563eb;
      border-color: rgba(37,99,235,.16);
    }}
    .legend-pill.projected {{
      background: rgba(100,116,139,.08);
      color: #475569;
      border-color: rgba(100,116,139,.14);
    }}
    .filter-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .filter-chip {{
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--line-strong);
      background: rgba(255,255,255,.9);
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      box-shadow: none;
    }}
    .filter-chip.active {{
      color: var(--accent-2);
      border-color: rgba(37,99,235,.22);
      background: rgba(37,99,235,.08);
    }}
    .expand-table {{
      margin-top: 16px;
    }}
    .table-wrap {{
      overflow-x: auto;
      overflow-y: auto;
      max-height: 370px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,.92);
    }}
    .compact-table {{
      max-height: 372px;
    }}
    .tall-table {{
      max-height: 520px;
    }}
    .sticky-table {{
      border-radius: 0;
    }}
    .sticky-table thead th {{
      position: sticky;
      top: 0;
      z-index: 3;
      box-shadow: inset 0 -1px 0 var(--line);
    }}
    .sticky-table th:first-child,
    .sticky-table td:first-child {{
      position: sticky;
      left: 0;
      z-index: 2;
      background: rgba(255,255,255,.98);
      box-shadow: inset -1px 0 0 var(--line);
    }}
    .sticky-table thead th:first-child {{
      z-index: 4;
      background: #eef4ff;
    }}
    .period-row.period-actual td {{
      background: rgba(15,118,110,.06);
    }}
    .period-row.period-historical td {{
      background: rgba(37,99,235,.04);
    }}
    .period-row.period-projected td {{
      background: rgba(100,116,139,.035);
    }}
    .period-row.hidden-row {{
      display: none;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 14px;
    }}
    .chart-grid.large .chart-card {{
      min-height: 420px;
    }}
    .chart-card {{
      padding: 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: var(--panel-soft);
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
      background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(243,247,251,.92));
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: rgba(255,255,255,.92);
    }}
    th, td {{
      padding: 11px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
      font-size: 13px;
    }}
    th {{
      background: rgba(37,99,235,.06);
      font-size: 12px;
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
      .results-board,
      .metric-grid,
      .form-grid,
      .chart-grid,
      .project-strip,
      .path-list.inline,
      .workspace-triple,
      .hero-strip,
      .toolbar {{
        grid-template-columns: 1fr;
      }}
      .wrap {{
        padding: 24px 16px 48px;
      }}
      .hero-copy {{
        padding: 24px;
      }}
      .hero-topbar {{
        align-items: stretch;
      }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <section class="hero-copy">
        <div class="hero-topbar">
          <div class="hero-main">
            <p class="eyebrow">Solar Tariff Roller</p>
            <h1>消纳电价测算工作台</h1>
            <p class="lead">界面按桌面工具方式重新收敛成一张紧凑工作台。先读取测算表和电站统计表建立滚动测算基线，再按月录入真实发电、自用和上网数据，系统会自动刷新消纳率、滚动现金流、IRR 和反算电价。</p>
          </div>
          <nav class="tab-nav" aria-label="页面导航">
            <a class="tab-link active" href="/">工作台</a>
            <a class="tab-link" href="/help">使用说明</a>
          </nav>
        </div>
        <div class="hero-strip">
          <div class="hero-chip"><strong>滚动基线</strong><span>先确认两份 Excel 和目标 IRR，再建立首次滚动测算基线。</span></div>
          <div class="hero-chip"><strong>月度更新</strong><span>每次录入一个月份，重复录入同月会自动覆盖。</span></div>
          <div class="hero-chip"><strong>统一口径</strong><span>发电量、自用电量、上网电量统一使用万kWh。</span></div>
          <div class="hero-chip"><strong>先看中间值</strong><span>先核对当前滚动年度拆分、税费和净现金流，再看完整明细。</span></div>
        </div>
      </section>
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
          <form method="post" action="/solve" enctype="multipart/form-data">
            <div class="form-grid">
              <label>目标 IRR
                <input name="target_irr" type="number" step="0.000001" min="0" max="1" value="{target_irr}">
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
                <div class="file-row">
                  <input id="calculation_workbook" name="calculation_workbook" type="text" value="{escape(calculation_workbook)}">
                  <label class="button-link secondary" for="calculation_workbook_file">浏览文件</label>
                  <input id="calculation_workbook_file" class="hidden-file" name="calculation_workbook_file" type="file" accept=".xlsx,.xls" onchange="syncFileName('calculation_workbook_file','calculation_workbook')">
                </div>
              </label>
              <label class="full">电站统计表路径
                <div class="file-row">
                  <input id="station_workbook" name="station_workbook" type="text" value="{escape(station_workbook)}">
                  <label class="button-link secondary" for="station_workbook_file">浏览文件</label>
                  <input id="station_workbook_file" class="hidden-file" name="station_workbook_file" type="file" accept=".xlsx,.xls" onchange="syncFileName('station_workbook_file','station_workbook')">
                </div>
              </label>
            </div>
            <p class="hint">建议第一次先建立滚动测算基线。确认“计算中间过程”里的当前滚动年度拆分、税费和现金流无误后，再录入月度真实数据。</p>
            <div class="actions">
              <button type="submit">开始测算</button>
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
          <form method="post" action="/update-monthly" enctype="multipart/form-data">
            <input type="hidden" name="target_irr" value="{target_irr}">
            <input type="hidden" name="calculation_workbook" value="{escape(calculation_workbook)}">
            <input type="hidden" name="station_workbook" value="{escape(station_workbook)}">
            <input type="hidden" name="sensitivity_parameter" value="{escape(sensitivity_parameter)}">
            <input type="hidden" name="sensitivity_start" value="{sensitivity_start}">
            <input type="hidden" name="sensitivity_stop" value="{sensitivity_stop}">
            <input type="hidden" name="sensitivity_step" value="{sensitivity_step}">
            <div class="form-grid">
              <label>月份
                <input name="period_label" type="month" value="{escape(update_period_label)}">
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
            <input id="monthly_calculation_workbook_file" class="hidden-file" name="calculation_workbook_file" type="file" accept=".xlsx,.xls">
            <input id="monthly_station_workbook_file" class="hidden-file" name="station_workbook_file" type="file" accept=".xlsx,.xls">
            <p class="hint">每次只更新一个月份即可。如果某个月要修正，重新录入同一个月份，系统会自动覆盖该月历史值，并重新计算最近 12 个月消纳率。</p>
            <div class="actions">
              <button type="submit">保存并重算</button>
            </div>
          </form>
        </section>
        {error_html}
        {success_html}
        {result_html}
      </section>
    </section>
    <p class="footer-note">这版页面已经改成更紧凑的工作台布局，优先减少纵向滚动，并突出业务操作、结果核对和中间过程追踪。后续如果继续完善，比较值得补的是批量月度导入、结果下载按钮和历史版本对比。</p>
  </main>
  <script>
    function syncFileName(fileInputId, textInputId) {{
      const fileInput = document.getElementById(fileInputId);
      const textInput = document.getElementById(textInputId);
      if (!fileInput || !textInput || !fileInput.files.length) return;
      textInput.value = fileInput.files[0].name;
    }}

    function downloadSvg(svgId, filename) {{
      const svg = document.getElementById(svgId);
      if (!svg) return;
      const serializer = new XMLSerializer();
      const source = serializer.serializeToString(svg);
      const blob = new Blob([source], {{ type: "image/svg+xml;charset=utf-8" }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }}

    function filterPeriodRows(button) {{
      const targetId = button.dataset.target;
      const filter = button.dataset.filter;
      const table = document.getElementById(targetId);
      if (!table) return;

      const buttons = button.parentElement ? button.parentElement.querySelectorAll('.filter-chip') : [];
      buttons.forEach((item) => item.classList.toggle('active', item === button));

      const rows = table.querySelectorAll('tbody tr.period-row');
      rows.forEach((row) => {{
        const matched = filter === 'all' || row.dataset.period === filter;
        row.classList.toggle('hidden-row', !matched);
      }});
    }}
  </script>
</body>
</html>"""


def _render_help_page() -> str:
    """Render the standalone help page."""

    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>使用说明</title>
  <style>
    :root {
      --bg: #f3f7fb;
      --panel: rgba(255, 255, 255, 0.94);
      --ink: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --line: #d9e2ec;
      --shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "PingFang SC", "SF Pro Display", "Noto Sans SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 0% 0%, rgba(15,118,110,.08), transparent 28%),
        radial-gradient(circle at 100% 0%, rgba(37,99,235,.10), transparent 24%),
        linear-gradient(180deg, rgba(255,255,255,.72), rgba(255,255,255,.38)),
        var(--bg);
    }
    .wrap {
      max-width: 980px;
      margin: 0 auto;
      padding: 28px 22px 40px;
    }
    .hero {
      padding: 28px 30px;
      border-radius: 24px;
      background: var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      margin-bottom: 18px;
    }
    .hero-topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }
    .eyebrow {
      margin: 0 0 10px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    h1 {
      margin: 0 0 12px;
      font-size: clamp(32px, 4vw, 46px);
      line-height: 1.06;
      letter-spacing: -0.03em;
    }
    .lead {
      margin: 0;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.72;
    }
    .back-row {
      display: none;
    }
    .button-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      padding: 10px 16px;
      border-radius: 999px;
      border: 1px solid var(--line);
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
      color: var(--accent);
      background: rgba(255,255,255,.92);
    }
    .tab-nav {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 6px;
      border-radius: 999px;
      background: rgba(248,251,255,.96);
      border: 1px solid var(--line);
    }
    .tab-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      padding: 8px 16px;
      border-radius: 999px;
      color: var(--muted);
      text-decoration: none;
      font-size: 13px;
      font-weight: 700;
    }
    .tab-link.active {
      color: var(--ink);
      background: #ffffff;
      box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
    }
    .stack {
      display: grid;
      gap: 18px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      box-shadow: var(--shadow);
    }
    .card h2 {
      margin: 0 0 16px;
      font-size: 22px;
      letter-spacing: -0.02em;
    }
    .callout {
      padding: 18px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(248,251,255,.9);
    }
    .callout p, .callout li {
      color: var(--muted);
      line-height: 1.8;
      font-size: 14px;
    }
    .callout ol, .callout ul {
      margin: 0;
      padding-left: 22px;
    }
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <div class="hero-topbar">
        <div>
          <p class="eyebrow">Guide</p>
          <h1>使用说明</h1>
          <p class="lead">这一页集中展示系统使用流程、填写注意事项和结果说明。主页面只保留业务操作和测算结果，避免信息过度堆叠。</p>
        </div>
        <nav class="tab-nav" aria-label="页面导航">
          <a class="tab-link" href="/">工作台</a>
          <a class="tab-link active" href="/help">使用说明</a>
        </nav>
      </div>
    </section>
    <section class="stack">
      <section class="card">
        <p class="eyebrow">Guide</p>
        <h2>详细使用流程</h2>
        <div class="callout">
          <ol>
            <li>先确认两份源文件路径正确，分别对应测算表和电站统计表。</li>
            <li>输入目标 IRR，点击“开始测算”，先看反算结果是否与预期接近。</li>
            <li>检查“计算中间过程”里的当前滚动年度发电、收入、税费和净现金流，确认口径无误。</li>
            <li>进入“更新本月真实数据”，录入当月发电量、自用电量、上网电量。</li>
            <li>系统保存后会自动重算，并把最新月度记录写入本地更新文件。</li>
            <li>需要对外提交时，直接使用结果区域展示的 Excel 文件。</li>
          </ol>
        </div>
      </section>
      <section class="card">
        <p class="eyebrow">Notes</p>
        <h2>填写注意事项</h2>
        <div class="callout">
          <ul>
            <li>目标 IRR 请填小数，不要填百分数。例如 9.60% 应填写 `0.096`。</li>
            <li>月度发电量、自用电量、上网电量单位统一为 `万kWh`。</li>
            <li>同一个月份重复提交时，系统会按最后一次提交结果覆盖。</li>
            <li>如果月度数据更新后结果变化较大，优先核对该月电量单位和自用/上网拆分是否正确。</li>
            <li>页面展示的是快速核对视图，完整对账和全周期明细请以导出的 Excel 为准。</li>
          </ul>
        </div>
      </section>
      <section class="card">
        <p class="eyebrow">Output</p>
        <h2>结果说明</h2>
        <div class="callout">
          <p><strong>反算结果:</strong> 展示目标 IRR 对应的综合电价、折后电价、校验 NPV 和校验 IRR。</p>
          <p><strong>计算中间过程:</strong> 展示当前滚动年度发电拆分、收益税费、现金流关键值，便于和 Excel 对账。</p>
          <p><strong>滚动年度汇总预览:</strong> 页面仅展示前 8 个滚动年度，完整结果在导出 Excel 中查看。</p>
        </div>
      </section>
    </section>
  </main>
</body>
</html>"""


def _build_line_chart_svg(
    x_values: list[float],
    y_values: list[float],
    y_label: str,
    svg_id: str = "line-chart-svg",
) -> str:
    """Render a simple inline SVG line chart."""

    width = 860
    height = 420
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
    <svg id="{svg_id}" class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="敏感性分析折线图">
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


def _build_bar_chart_svg(
    x_values: list[float],
    y_values: list[float],
    y_label: str,
    svg_id: str = "bar-chart-svg",
) -> str:
    """Render a simple inline SVG bar chart."""

    width = 860
    height = 420
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
    <svg id="{svg_id}" class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="敏感性分析柱状图">
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
