"""Persistence and merge helpers for monthly actual operating data."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from solar_tariff_roller.schemas.input import MonthlyGenerationRecordInput


DEFAULT_MONTHLY_UPDATE_DIR = Path("data/processed/monthly_updates")


def build_monthly_updates_path(
    calculation_workbook_path: str | Path,
    station_workbook_path: str | Path,
    base_dir: str | Path = DEFAULT_MONTHLY_UPDATE_DIR,
) -> Path:
    """Build the persistence path for one workbook pair."""

    calculation_path = Path(calculation_workbook_path).expanduser().resolve()
    station_path = Path(station_workbook_path).expanduser().resolve()
    digest = hashlib.sha1(
        f"{calculation_path}::{station_path}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:12]
    stem = _sanitize_stem(calculation_path.stem)
    target_dir = Path(base_dir)
    return target_dir / f"{stem}_{digest}.json"


def load_monthly_updates(
    calculation_workbook_path: str | Path,
    station_workbook_path: str | Path,
    base_dir: str | Path = DEFAULT_MONTHLY_UPDATE_DIR,
) -> list[MonthlyGenerationRecordInput]:
    """Load persisted monthly updates for one workbook pair."""

    path = build_monthly_updates_path(calculation_workbook_path, station_workbook_path, base_dir)
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    return [MonthlyGenerationRecordInput(**record) for record in records]


def upsert_monthly_update(
    calculation_workbook_path: str | Path,
    station_workbook_path: str | Path,
    record: MonthlyGenerationRecordInput | dict[str, object],
    base_dir: str | Path = DEFAULT_MONTHLY_UPDATE_DIR,
) -> Path:
    """Insert or replace one persisted monthly actual record."""

    target_path = build_monthly_updates_path(calculation_workbook_path, station_workbook_path, base_dir)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_record = _normalize_record(
        record
        if isinstance(record, MonthlyGenerationRecordInput)
        else MonthlyGenerationRecordInput(**record)
    )

    existing_records = {
        item.period_label: item
        for item in load_monthly_updates(calculation_workbook_path, station_workbook_path, base_dir)
    }
    existing_records[normalized_record.period_label] = normalized_record

    payload = {
        "calculation_workbook": str(Path(calculation_workbook_path)),
        "station_workbook": str(Path(station_workbook_path)),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "records": [
            existing_records[label].model_dump()
            for label in sorted(existing_records.keys())
        ],
    }
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path


def merge_monthly_records(
    base_records: list[MonthlyGenerationRecordInput],
    override_records: list[MonthlyGenerationRecordInput],
) -> list[MonthlyGenerationRecordInput]:
    """Merge persisted monthly overrides on top of workbook records."""

    merged = {record.period_label: _normalize_record(record) for record in base_records}
    for record in override_records:
        merged[record.period_label] = _normalize_record(record)

    return [merged[label] for label in sorted(merged.keys())]


def calculate_recent_self_consumption_ratio(
    records: list[MonthlyGenerationRecordInput],
    months: int = 12,
) -> float | None:
    """Calculate a weighted recent self-consumption ratio from monthly actuals."""

    recent_records = _select_recent_complete_records(records, months)
    if not recent_records:
        return None

    generation_total = sum(record.generation_10k_kwh or 0.0 for record in recent_records)
    self_consumed_total = sum(record.self_consumed_10k_kwh or 0.0 for record in recent_records)
    if generation_total <= 0:
        return None

    return round(self_consumed_total / generation_total, 6)


def calculate_recent_monthly_ratios(
    records: list[MonthlyGenerationRecordInput],
    months: int = 12,
) -> list[float]:
    """Return the latest complete monthly self-consumption ratios."""

    recent_records = _select_recent_complete_records(records, months)
    if len(recent_records) < months:
        return []

    return [round(record.self_consumption_ratio or 0.0, 6) for record in recent_records]


def _select_recent_complete_records(
    records: list[MonthlyGenerationRecordInput],
    months: int,
) -> list[MonthlyGenerationRecordInput]:
    normalized = [_normalize_record(record) for record in records]
    complete_records = [
        record
        for record in normalized
        if record.generation_10k_kwh is not None
        and record.self_consumed_10k_kwh is not None
        and record.exported_10k_kwh is not None
        and record.self_consumption_ratio is not None
    ]
    return sorted(complete_records, key=lambda item: item.period_label)[-months:]


def _normalize_record(record: MonthlyGenerationRecordInput) -> MonthlyGenerationRecordInput:
    generation = record.generation_10k_kwh
    self_consumed = record.self_consumed_10k_kwh
    exported = record.exported_10k_kwh
    ratio = record.self_consumption_ratio

    if generation is not None and self_consumed is not None and exported is None:
        exported = round(max(generation - self_consumed, 0.0), 4)
    if generation is not None and exported is not None and self_consumed is None:
        self_consumed = round(max(generation - exported, 0.0), 4)
    if ratio is None and generation is not None and generation > 0 and self_consumed is not None:
        ratio = round(self_consumed / generation, 6)

    return MonthlyGenerationRecordInput(
        period_label=record.period_label,
        generation_10k_kwh=generation,
        self_consumed_10k_kwh=self_consumed,
        exported_10k_kwh=exported,
        self_consumption_ratio=ratio,
    )


def _sanitize_stem(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)
    sanitized = sanitized.strip("_")
    return sanitized or "project"
