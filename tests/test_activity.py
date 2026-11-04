"""Unit and integration tests for Repo360 user activity scraper."""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from src.activity.models import (
    Activity,
    ActivityConfig,
    fmt_timestamp,
    is_bot,
    parse_ts,
)
from src.activity.collector import (
    build_org_rows,
    build_rows,
    classify,
)
from src.activity.reporter import write_activity_csv, write_activity_workbook


def test_activity_model_methods():
    act = Activity()
    now = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
    act.add("commits", now)
    act.add("prs_opened", now)
    act.add("reviews", now)

    assert act.commits == 1
    assert act.prs_opened == 1
    assert act.reviews == 1
    assert act.total() == 3
    assert len(act.active_days) == 1
    assert act.first_active == now
    assert act.last_active == now

    act2 = Activity()
    later = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    act2.add("commits", later)
    act.merge(act2)

    assert act.commits == 2
    assert act.total() == 4
    assert len(act.active_days) == 2
    assert act.last_active == later


def test_activity_classification():
    cfg = ActivityConfig(active_min_days=8, moderate_min_days=3)
    assert classify(10, cfg) == "Active"
    assert classify(8, cfg) == "Active"
    assert classify(5, cfg) == "Moderate"
    assert classify(3, cfg) == "Moderate"
    assert classify(1, cfg) == "Low"
    assert classify(0, cfg) == "Inactive"


def test_is_bot_detection():
    assert is_bot({"type": "Bot", "login": "some-app"}) is True
    assert is_bot({"type": "User", "login": "app[bot]"}) is True
    assert is_bot({"type": "User", "login": "dependabot"}) is True
    assert is_bot({"type": "User", "login": "alice"}) is False


def test_build_rows_and_org_rows():
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    act = Activity()
    act.add("commits", now)

    results = {("acme-org", "service-a"): {"alice": act}}
    members = {"acme-org": {"alice", "bob"}}
    cfg = ActivityConfig(active_min_days=8, moderate_min_days=3, include_inactive_members=True)

    user_rows, repo_rows = build_rows(
        results=results,
        members=members,
        cfg=cfg,
        end=now,
        teams_by_user={("acme-org", "alice"): {"backend-team"}},
        org_team_complete={"acme-org": True},
    )

    assert len(user_rows) == 2  # alice (active) + bob (inactive member)
    alice_row = next(r for r in user_rows if r[1] == "alice")
    bob_row = next(r for r in user_rows if r[1] == "bob")

    assert alice_row[2] == "Low"
    assert alice_row[4] == 1  # Total activities
    assert alice_row[17] == "Yes"  # Member
    assert alice_row[18] == "backend-team"
    assert len(alice_row) == 19

    assert bob_row[2] == "Inactive"
    assert bob_row[4] == 0

    assert len(repo_rows) == 1
    assert repo_rows[0][1] == "service-a"
    assert repo_rows[0][2] == "alice"

    org_rows = build_org_rows(user_rows, results)
    assert len(org_rows) == 1
    assert org_rows[0][0] == "acme-org"
    assert org_rows[0][1] == 1  # 1 repo
    assert org_rows[0][2] == 1  # 1 contributor


def test_write_activity_workbook_and_csv(tmp_path):
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    act = Activity()
    act.add("commits", now)
    cfg = ActivityConfig(output_dir=str(tmp_path))

    user_rows, repo_rows = build_rows(
        results={("acme-org", "service-a"): {"alice": act}},
        members={"acme-org": {"alice"}},
        cfg=cfg,
        end=now,
        teams_by_user={},
        org_team_complete={"acme-org": True},
    )
    org_rows = build_org_rows(user_rows, {("acme-org", "service-a"): {"alice": act}})

    xlsx_path = tmp_path / "activity.xlsx"
    csv_path = tmp_path / "activity.csv"

    write_activity_workbook(
        path=xlsx_path,
        cfg=cfg,
        since=now,
        end=now,
        user_rows=user_rows,
        repo_rows=repo_rows,
        org_rows=org_rows,
        failures=[],
        repos_scanned=1,
        execution_duration=1.5,
    )
    from src.activity.models import USER_HEADERS
    write_activity_csv(csv_path, USER_HEADERS, user_rows)

    assert xlsx_path.is_file()
    assert xlsx_path.stat().st_size > 1000
    assert csv_path.is_file()
    assert "alice" in csv_path.read_text(encoding="utf-8")


def test_format_error_permission_mapping():
    from src.activity.collector import _format_error
    import requests

    resp_403 = requests.Response()
    resp_403.status_code = 403
    http_err_403 = requests.exceptions.HTTPError(response=resp_403)

    msg_pulls = _format_error("Pulls", http_err_403)
    assert "403 Forbidden" in msg_pulls
    assert "pull_requests: read" in msg_pulls

    msg_issues = _format_error("Issues", http_err_403)
    assert "403 Forbidden" in msg_issues
    assert "issues: read" in msg_issues

    resp_404 = requests.Response()
    resp_404.status_code = 404
    http_err_404 = requests.exceptions.HTTPError(response=resp_404)
    msg_404 = _format_error("Pulls", http_err_404)
    assert "404 Not Found" in msg_404

    generic_err = RuntimeError("Network timeout")
    msg_generic = _format_error("Commits", generic_err)
    assert "Commits: Network timeout" in msg_generic
