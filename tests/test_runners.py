"""Unit and integration tests for Repo360 Actions self-hosted runners analytics."""

from datetime import datetime, timezone
import pytest

from src.runners.models import (
    ORG_RUNNER_HEADERS,
    RUNNER_HEADERS,
    RunnerInfo,
    RunnerJobMetrics,
    RunnersConfig,
)
from src.runners.collector import build_runner_rows
from src.runners.reporter import write_runners_csv, write_runners_workbook


def test_runner_job_metrics_calculations():
    m = RunnerJobMetrics()
    m.successful_jobs = 8
    m.failed_jobs = 2
    m.timed_out_jobs = 0
    m.total_jobs = 10
    m.total_duration_seconds = 1200.0  # 20 mins total
    m.job_durations = [60.0, 120.0, 180.0, 240.0, 600.0]  # 5 samples
    m.total_queue_seconds = 250.0
    m.queue_durations = [10.0, 20.0, 40.0, 80.0, 100.0]  # 2 breaches (>60s)

    assert m.completed_jobs == 10
    assert m.success_rate == 80.0
    assert m.failure_rate == 20.0
    assert m.total_compute_hours == 0.33
    assert m.avg_duration_minutes == 4.0
    assert m.min_duration_minutes == 1.0
    assert m.max_duration_minutes == 10.0
    assert m.median_duration_minutes == 3.0
    assert m.avg_queue_seconds == 50.0
    assert m.p95_queue_seconds == 100.0
    assert m.queue_sla_breaches == 2
    assert m.queue_sla_breach_rate == 40.0


def test_runner_job_metrics_empty():
    m = RunnerJobMetrics()
    assert m.completed_jobs == 0
    assert m.success_rate == "N/A"
    assert m.failure_rate == "N/A"
    assert m.avg_duration_minutes == "N/A"
    assert m.median_duration_minutes == "N/A"
    assert m.min_duration_minutes == "N/A"
    assert m.max_duration_minutes == "N/A"
    assert m.avg_queue_seconds == "N/A"
    assert m.p95_queue_seconds == "N/A"
    assert m.queue_sla_breaches == 0
    assert m.queue_sla_breach_rate == "N/A"


def test_build_runner_rows():
    runner = RunnerInfo(
        id=101,
        name="linux-runner-1",
        os="Linux",
        status="Online",
        busy=True,
        labels=("self-hosted", "x64", "linux"),
        runner_group_name="Core-Compute",
        org="fintech-org",
        arch="x64",
        runner_version="2.319.0",
        ephemeral=False,
    )
    metrics = RunnerJobMetrics()
    metrics.successful_jobs = 5
    metrics.total_jobs = 5
    metrics.total_duration_seconds = 600.0
    metrics.repos_served.add("payment-service")

    runner_rows, org_runner_rows = build_runner_rows(
        runners=[runner],
        runner_metrics={("fintech-org", "linux-runner-1"): metrics},
        org_runner_metrics={"fintech-org": metrics},
        orgs=["fintech-org"],
    )

    assert len(runner_rows) == 1
    r_row = runner_rows[0]
    assert r_row[0] == "fintech-org"
    assert r_row[1] == 101
    assert r_row[2] == "linux-runner-1"
    assert r_row[4] == "Core-Compute"
    assert r_row[9] == "Online"
    assert r_row[10] == "Busy"
    assert r_row[13] == 5  # Total jobs
    assert r_row[18] == 100.0  # Success rate

    assert len(org_runner_rows) == 1
    o_row = org_runner_rows[0]
    assert o_row[0] == "fintech-org"
    assert o_row[1] == 1  # Total runners
    assert o_row[4] == 1  # Online
    assert o_row[6] == 100.0  # Availability %
    assert o_row[7] == 1  # Currently busy


def test_write_runners_workbook_and_csv(tmp_path):
    runner = RunnerInfo(
        id=202,
        name="k8s-pod-runner",
        os="Linux",
        status="Online",
        busy=False,
        labels=("self-hosted", "k8s"),
        runner_group_name="Autoscaling",
        org="acme-corp",
        arch="x64",
        runner_version="2.320.0",
        ephemeral=True,
    )
    metrics = RunnerJobMetrics()
    metrics.successful_jobs = 12
    metrics.total_jobs = 12
    metrics.total_duration_seconds = 3600.0

    runner_rows, org_runner_rows = build_runner_rows(
        runners=[runner],
        runner_metrics={("acme-corp", "k8s-pod-runner"): metrics},
        org_runner_metrics={"acme-corp": metrics},
        orgs=["acme-corp"],
    )

    cfg = RunnersConfig(output_dir=str(tmp_path))
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    xlsx_path = tmp_path / "runners.xlsx"
    csv_path = tmp_path / "runners.csv"

    write_runners_workbook(
        path=xlsx_path,
        cfg=cfg,
        since=now,
        end=now,
        runner_rows=runner_rows,
        org_runner_rows=org_runner_rows,
        failures=[],
        execution_duration=2.0,
    )
    write_runners_csv(csv_path, RUNNER_HEADERS, runner_rows)

    assert xlsx_path.is_file()
    assert xlsx_path.stat().st_size > 1000
    assert csv_path.is_file()
    assert "k8s-pod-runner" in csv_path.read_text(encoding="utf-8")

    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path)
    summary = wb["Executive Summary"]
    # Verify Total Duration cell B5 is centered
    assert summary["B5"].value == "2.0s"
    assert summary["B5"].alignment.horizontal == "center"
    # Find Online Runners row and verify value has no percentage and is centered
    online_row_val = None
    for r in range(5, 16):
        if summary.cell(row=r, column=1).value == "Online Runners":
            online_row_val = summary.cell(row=r, column=2).value
            assert summary.cell(row=r, column=2).alignment.horizontal == "center"
            break
    assert online_row_val == 1  # integer count, no percentage string like "1 (100.0%)"
