"""Unit and integration tests for Repo360 DORA & Flow Metrics."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from openpyxl import load_workbook

from src.dora.models import (
    DORAConfig,
    DeploymentRecord,
    RecoveryIncident,
    RepoDORAMetrics,
    compute_composite_tier,
    get_cfr_tier,
    get_df_tier,
    get_lttc_tier,
    get_mttr_tier,
)
from src.dora.collector import (
    build_dora_rows,
    calculate_recovery_incidents,
)
from src.dora.reporter import write_dora_workbook


def test_dora_tier_classifiers():
    # Deployment Frequency
    assert get_df_tier(10.0) == "Elite"
    assert get_df_tier(3.0) == "High"
    assert get_df_tier(0.5) == "Medium"
    assert get_df_tier(0.1) == "Low"

    # Lead Time for Changes
    assert get_lttc_tier(0.5) == "Elite"
    assert get_lttc_tier(48.0) == "High"
    assert get_lttc_tier(300.0) == "Medium"
    assert get_lttc_tier(800.0) == "Low"
    assert get_lttc_tier(None) == "N/A"

    # Change Failure Rate
    assert get_cfr_tier(2.0) == "Elite"
    assert get_cfr_tier(10.0) == "High"
    assert get_cfr_tier(25.0) == "Medium"
    assert get_cfr_tier(40.0) == "Low"

    # MTTR
    assert get_mttr_tier(0.5) == "Elite"
    assert get_mttr_tier(12.0) == "High"
    assert get_mttr_tier(72.0) == "Medium"
    assert get_mttr_tier(200.0) == "Low"
    assert get_mttr_tier(None) == "N/A"

    # Composite Tier
    assert compute_composite_tier(["Elite", "Elite", "High", "Elite"]) == "Elite"
    assert compute_composite_tier(["High", "High", "Medium", "High"]) == "High"
    assert compute_composite_tier(["Low", "Low", "Medium", "Low"]) == "Low"


def test_recovery_incident_calculation():
    now = datetime.now(timezone.utc)
    ev_success_1 = DeploymentRecord(
        event_type="Deployment",
        event_id="dep-1",
        name="Deploy 1",
        environment="production",
        status="SUCCESS",
        ref="main",
        created_at=now - timedelta(hours=10),
    )
    ev_fail = DeploymentRecord(
        event_type="Deployment",
        event_id="dep-2",
        name="Deploy 2",
        environment="production",
        status="FAILURE",
        ref="main",
        created_at=now - timedelta(hours=6),
    )
    ev_restore = DeploymentRecord(
        event_type="Deployment",
        event_id="dep-3",
        name="Deploy 3 (Hotfix)",
        environment="production",
        status="SUCCESS",
        ref="hotfix",
        created_at=now - timedelta(hours=4),
    )

    incidents = calculate_recovery_incidents([ev_success_1, ev_fail, ev_restore])
    assert len(incidents) == 1
    inc = incidents[0]
    assert "dep-2" in inc.failed_event
    assert "dep-3" in inc.restored_event
    assert inc.mttr_hours == 2.0


def test_repo_dora_metrics_aggregation():
    now = datetime.now(timezone.utc)
    m = RepoDORAMetrics(org="fintech-org", repo="payment-gateway")

    # Add 10 deployments: 9 success, 1 failure
    for i in range(9):
        m.deployments.append(
            DeploymentRecord(
                event_type="Deployment",
                event_id=f"dep-{i}",
                name="Deploy",
                environment="production",
                status="SUCCESS",
                ref="main",
                created_at=now - timedelta(days=i),
                lead_time_hours=2.0 + i,
            )
        )
    m.deployments.append(
        DeploymentRecord(
            event_type="Deployment",
            event_id="dep-fail",
            name="Deploy Fail",
            environment="production",
            status="FAILURE",
            ref="main",
            created_at=now - timedelta(days=10),
            lead_time_hours=4.0,
        )
    )
    m.incidents.append(
        RecoveryIncident(
            failed_event="dep-fail",
            failure_time=now - timedelta(days=10),
            restored_event="dep-8",
            restored_time=now - timedelta(days=8),
            mttr_hours=48.0,
        )
    )

    assert m.total_deploys == 10
    assert m.successful_deploys == 9
    assert m.failed_deploys == 1
    assert m.change_failure_rate_pct == 10.0
    assert m.deployment_frequency_per_week(70) == 1.0
    assert m.median_lead_time_hours is not None
    assert m.median_mttr_hours == 48.0

    overall, df_tier, lttc_tier, cfr_tier, mttr_tier = m.get_tiers(70)
    assert df_tier == "High"
    assert cfr_tier == "High"
    assert mttr_tier == "Medium"


def test_build_dora_rows():
    now = datetime.now(timezone.utc)
    m = RepoDORAMetrics(org="fintech-org", repo="auth-service")
    m.deployments.append(
        DeploymentRecord(
            event_type="Release",
            event_id="v1.0.0",
            name="v1.0.0 Release",
            environment="production",
            status="SUCCESS",
            ref="v1.0.0",
            created_at=now,
            lead_time_hours=1.5,
        )
    )

    repo_rows, org_rows, deployment_rows, recovery_rows = build_dora_rows(
        metrics_list=[m],
        orgs=["fintech-org"],
        window_days=90,
    )

    assert len(repo_rows) == 1
    assert repo_rows[0][0] == "fintech-org"
    assert repo_rows[0][1] == "auth-service"
    assert repo_rows[0][3] == 1  # Total deploys
    assert repo_rows[0][4] == 1  # Successful

    assert len(org_rows) == 1
    assert org_rows[0][0] == "fintech-org"
    assert org_rows[0][2] == 1  # Active deploy repos
    assert org_rows[0][4] == 1  # Total deploys

    assert len(deployment_rows) == 1
    assert deployment_rows[0][2] == "Release"
    assert deployment_rows[0][3] == "v1.0.0"


def test_write_dora_workbook(tmp_path: Path):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=90)
    m = RepoDORAMetrics(org="demo-org", repo="demo-repo")

    repo_rows, org_rows, deployment_rows, recovery_rows = build_dora_rows(
        metrics_list=[m],
        orgs=["demo-org"],
        window_days=90,
    )

    out_file = tmp_path / "dora_test.xlsx"
    cfg = DORAConfig(output_dir=str(tmp_path), lookback_days=90)

    write_dora_workbook(
        path=out_file,
        cfg=cfg,
        since=since,
        end=now,
        repo_rows=repo_rows,
        org_rows=org_rows,
        deployment_rows=deployment_rows,
        recovery_rows=recovery_rows,
        failures=[],
        execution_duration=2.0,
    )

    assert out_file.exists()
    wb = load_workbook(out_file)
    sheet_names = wb.sheetnames
    assert "Executive Summary" in sheet_names
    assert "Repository DORA Scorecard" in sheet_names
    assert "Deployment & Release Ledger" in sheet_names
    assert "Recovery & MTTR Ledger" in sheet_names
