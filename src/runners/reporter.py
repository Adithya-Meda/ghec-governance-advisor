"""Excel reporter for Actions self-hosted runners analytics."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..activity.models import DATE_FMT, IST
from ..activity.reporter import (
    NAVY,
    autofit,
    finalize_sheet,
    safe_cell,
    section_title,
    write_empty_table,
    write_table,
)
from .models import ORG_RUNNER_HEADERS, RUNNER_HEADERS, RunnerInfo, RunnersConfig


def write_runners_workbook(
    path: Path,
    cfg: RunnersConfig,
    since: datetime,
    end: datetime,
    runner_rows: List[list],
    org_runner_rows: List[list],
    failures: List[Tuple[str, str]],
    execution_duration: Optional[float] = None,
) -> None:
    """Generate executive Excel workbook for self-hosted runner fleet utilization."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    # Sheet 1: Executive Summary
    summary = wb.active
    summary.title = "Executive Summary"
    summary["A1"] = "Repo360 Actions Self-Hosted Runners Performance & Fleet Report"
    summary["A1"].font = Font(bold=True, size=16, color=NAVY)

    since_ist, end_ist = since.astimezone(IST), end.astimezone(IST)
    duration_str = f"{execution_duration:.1f}s" if execution_duration else "N/A"
    summary["A2"] = (
        f"Reporting Window: {since_ist:{DATE_FMT}} to {end_ist:{DATE_FMT}} ({cfg.lookback_days} days) "
        f"| Generated: {end_ist:{DATE_FMT} %H:%M} IST | Duration: {duration_str}"
    )
    summary["A2"].font = Font(italic=True, color="595959")

    total_runners = len(runner_rows)
    online_count = sum(1 for r in runner_rows if len(r) > 9 and str(r[9]).capitalize() == "Online")
    offline_count = sum(1 for r in runner_rows if len(r) > 9 and str(r[9]).capitalize() in ("Offline", "Ephemeral"))
    busy_count = sum(1 for r in runner_rows if len(r) > 10 and str(r[10]).capitalize() == "Busy")
    ephemeral_count = sum(1 for r in runner_rows if len(r) > 8 and "Ephemeral" in str(r[8]))
    total_compute_hours = sum(r[19] for r in runner_rows if len(r) > 19 and isinstance(r[19], (int, float)))
    total_jobs_run = sum(r[13] for r in runner_rows if len(r) > 13 and isinstance(r[13], int))
    total_sla_breaches = sum(r[26] for r in runner_rows if len(r) > 26 and isinstance(r[26], int))

    kpis = [
        ["Total Duration", duration_str],
        ["Organizations Monitored", len(org_runner_rows)],
        ["Discovered Self-Hosted Runners", total_runners],
        ["Online Runners", online_count],
        ["Offline / Dormant Runners", offline_count],
        ["Currently Busy Runners", busy_count],
        ["Ephemeral (Autoscaled) Runners", ephemeral_count],
        ["Total Workflow Jobs Executed", total_jobs_run],
        ["Total Compute Consumed (Hours)", round(total_compute_hours, 2)],
        ["Queue SLA Breaches (>60s wait)", total_sla_breaches],
        ["Unprocessed Items / Errors", len(failures)],
    ]
    curr_row = write_table(summary, 4, ("Metric", "Fleet Aggregate"), kpis) + 2

    curr_row = section_title(summary, curr_row, "Organization Fleet Breakdown")
    curr_row = write_table(summary, curr_row, ORG_RUNNER_HEADERS, org_runner_rows, bar_col=1) + 2

    if failures:
        curr_row = section_title(summary, curr_row, "Items Requiring Review / Failures")
        write_table(summary, curr_row, ("Target Item", "Issue Description"), [list(item) for item in failures])

    autofit(summary, skip_rows=2)
    summary.sheet_view.showGridLines = False

    # Sheet 2: Org Runner Summary
    org_ws = wb.create_sheet("Org Runner Summary")
    last_org = write_table(org_ws, 1, ORG_RUNNER_HEADERS, org_runner_rows)
    finalize_sheet(org_ws, 1, last_org, len(ORG_RUNNER_HEADERS), "B2")

    # Sheet 3: Self-Hosted Runners Detail
    runner_ws = wb.create_sheet("Runner Fleet Detail")
    if runner_rows:
        last_runner = write_table(runner_ws, 1, RUNNER_HEADERS, runner_rows)
        finalize_sheet(runner_ws, 1, last_runner, len(RUNNER_HEADERS), "D2")

        status_col_idx = RUNNER_HEADERS.index("Status") + 1
        for r_idx in range(2, last_runner + 1):
            cell = runner_ws.cell(r_idx, status_col_idx)
            val = str(cell.value).capitalize()
            if val == "Online":
                cell.fill = PatternFill("solid", fgColor="C6EFCE")
                cell.font = Font(bold=True, color="006100")
            elif val in ("Offline", "Ephemeral"):
                cell.fill = PatternFill("solid", fgColor="FFC7CE")
                cell.font = Font(bold=True, color="9C0006")
    else:
        write_empty_table(
            runner_ws,
            1,
            RUNNER_HEADERS,
            "No self-hosted runners found on target organizations.",
        )

    wb.save(path)
