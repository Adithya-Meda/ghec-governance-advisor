"""Excel reporter for Repo360 DORA & Flow Metrics."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..activity.models import DATE_FMT, IST
from ..activity.reporter import NAVY, autofit, finalize_sheet, safe_cell, section_title, write_table
from .models import (
    DORA_DEPLOYMENT_HEADERS,
    DORA_ORG_HEADERS,
    DORA_RECOVERY_HEADERS,
    DORA_REPO_HEADERS,
    DORAConfig,
    compute_composite_tier,
)

DORA_TIER_STYLES = {
    "Elite": ("C6EFCE", "006100"),
    "High": ("E2EFDA", "375623"),
    "Medium": ("FFF2CC", "833C0C"),
    "Low": ("FFC7CE", "9C0006"),
}

STATUS_STYLES = {
    "SUCCESS": ("C6EFCE", "006100"),
    "FAILURE": ("FFC7CE", "9C0006"),
    "IN_PROGRESS": ("FFF2CC", "833C0C"),
    "Resolved": ("C6EFCE", "006100"),
}


def write_dora_workbook(
    path: Path,
    cfg: DORAConfig,
    since: datetime,
    end: datetime,
    repo_rows: List[list],
    org_rows: List[list],
    deployment_rows: List[list],
    recovery_rows: List[list],
    failures: List[Tuple[str, str]],
    execution_duration: Optional[float] = None,
) -> None:
    """Generate executive DORA delivery and recovery performance workbook."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    since_ist, end_ist = since.astimezone(IST), end.astimezone(IST)
    duration_str = f"{execution_duration:.1f}s" if execution_duration else "N/A"

    # Sheet 1: Executive Summary
    summary = wb.active
    summary.title = "Executive Summary"
    summary["A1"] = "Repo360 DORA & Engineering Delivery Flow Metrics"
    summary["A1"].font = Font(bold=True, size=16, color=NAVY)

    summary["A2"] = (
        f"Reporting Window: {since_ist:{DATE_FMT}} to {end_ist:{DATE_FMT}} ({cfg.lookback_days} days) | "
        f"Generated: {end_ist:{DATE_FMT} %H:%M} IST | Duration: {duration_str}"
    )
    summary["A2"].font = Font(italic=True, color="595959")

    total_deploys = sum(r[3] for r in repo_rows if len(r) > 3 and isinstance(r[3], int))
    total_successful = sum(r[4] for r in repo_rows if len(r) > 4 and isinstance(r[4], int))
    total_failed = sum(r[5] for r in repo_rows if len(r) > 5 and isinstance(r[5], int))
    cfr_overall = round(total_failed / total_deploys * 100, 2) if total_deploys else 0.0

    weeks = max(1.0, cfg.lookback_days / 7.0)
    weekly_frequency = round(total_deploys / weeks, 2)

    tier_counts = Counter(r[2] for r in repo_rows if len(r) > 2)
    fleet_tier = compute_composite_tier([r[2] for r in repo_rows if len(r) > 2])

    kpis = [
        ["Total Duration", duration_str],
        ["Organizations Monitored", len(org_rows)],
        ["Repositories Assessed", len(repo_rows)],
        ["Fleet Overall DORA Performance Tier", fleet_tier],
        ["Total Production Deployments & Releases", total_deploys],
        ["Successful Deployments", total_successful],
        ["Failed Deployments / Incidents", total_failed],
        ["Fleet Deployment Frequency (/week)", weekly_frequency],
        ["Fleet Change Failure Rate (%)", f"{cfr_overall}%"],
        ["Elite Tier Repositories", tier_counts.get("Elite", 0)],
        ["High Tier Repositories", tier_counts.get("High", 0)],
        ["Medium Tier Repositories", tier_counts.get("Medium", 0)],
        ["Low Tier Repositories", tier_counts.get("Low", 0)],
    ]
    curr_row = write_table(summary, 4, ("Metric", "Fleet Aggregate"), kpis) + 2

    curr_row = section_title(summary, curr_row, "Organization DORA Performance Overview")
    curr_row = write_table(summary, curr_row, DORA_ORG_HEADERS, org_rows, bar_col=4) + 2

    autofit(summary, skip_rows=2)
    summary.sheet_view.showGridLines = False

    # Sheet 2: Repository DORA Scorecard
    repo_ws = wb.create_sheet("Repository DORA Scorecard")
    if repo_rows:
        last_repo = write_table(repo_ws, 1, DORA_REPO_HEADERS, repo_rows)
        finalize_sheet(repo_ws, 1, last_repo, len(DORA_REPO_HEADERS), "C2")

        # Colorize Tier Columns
        tier_col_idx = DORA_REPO_HEADERS.index("DORA Tier") + 1
        for r_idx in range(2, last_repo + 1):
            cell = repo_ws.cell(r_idx, tier_col_idx)
            val = str(cell.value).strip()
            if val in DORA_TIER_STYLES:
                fill, font_col = DORA_TIER_STYLES[val]
                cell.fill = PatternFill("solid", fgColor=fill)
                cell.font = Font(bold=True, color=font_col)
    else:
        empty_row = [["No repositories found on target organizations"] + ["-"] * (len(DORA_REPO_HEADERS) - 1)]
        last_repo = write_table(repo_ws, 1, DORA_REPO_HEADERS, empty_row)
        finalize_sheet(repo_ws, 1, last_repo, len(DORA_REPO_HEADERS), "C2")

    # Sheet 3: Deployment Ledger
    dep_ws = wb.create_sheet("Deployment & Release Ledger")
    if deployment_rows:
        last_dep = write_table(dep_ws, 1, DORA_DEPLOYMENT_HEADERS, deployment_rows)
        finalize_sheet(dep_ws, 1, last_dep, len(DORA_DEPLOYMENT_HEADERS), "D2")

        status_col_idx = DORA_DEPLOYMENT_HEADERS.index("Status") + 1
        for r_idx in range(2, last_dep + 1):
            cell = dep_ws.cell(r_idx, status_col_idx)
            val = str(cell.value).strip()
            if val in STATUS_STYLES:
                fill, font_col = STATUS_STYLES[val]
                cell.fill = PatternFill("solid", fgColor=fill)
                cell.font = Font(bold=True, color=font_col)
    else:
        empty_row = [["No deployment or release events recorded within window"] + ["-"] * (len(DORA_DEPLOYMENT_HEADERS) - 1)]
        last_dep = write_table(dep_ws, 1, DORA_DEPLOYMENT_HEADERS, empty_row)
        finalize_sheet(dep_ws, 1, last_dep, len(DORA_DEPLOYMENT_HEADERS), "D2")

    # Sheet 4: Recovery Ledger
    rec_ws = wb.create_sheet("Recovery & MTTR Ledger")
    if recovery_rows:
        last_rec = write_table(rec_ws, 1, DORA_RECOVERY_HEADERS, recovery_rows)
        finalize_sheet(rec_ws, 1, last_rec, len(DORA_RECOVERY_HEADERS), "C2")
    else:
        empty_row = [["No failure recovery incidents recorded within window"] + ["-"] * (len(DORA_RECOVERY_HEADERS) - 1)]
        last_rec = write_table(rec_ws, 1, DORA_RECOVERY_HEADERS, empty_row)
        finalize_sheet(rec_ws, 1, last_rec, len(DORA_RECOVERY_HEADERS), "C2")

    wb.save(path)
