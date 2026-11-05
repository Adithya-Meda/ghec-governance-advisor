"""Unit and integration tests for Repo360 Push Protection & Ruleset Bypass Ledger."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from openpyxl import load_workbook

from src.bypass.models import (
    BypassConfig,
    PushProtectionBypassRecord,
    RepoBypassProfile,
    RulesetBypassRecord,
)
from src.bypass.collector import build_bypass_rows
from src.bypass.reporter import write_bypass_workbook


def test_bypass_record_models():
    now = datetime.now(timezone.utc)
    push_rec = PushProtectionBypassRecord(
        org="fintech-org",
        repo="payment-service",
        alert_number=42,
        secret_type="GitHub Personal Access Token",
        actor="dev-user-1",
        timestamp=now,
        resolution="used_in_tests",
        resolution_comment="Test token with dummy scopes",
        push_protection_bypassed=True,
        html_url="https://github.com/fintech-org/payment-service/security/secret-scanning/42",
    )
    assert push_rec.alert_number == 42
    assert push_rec.actor == "dev-user-1"
    assert push_rec.push_protection_bypassed is True

    rule_rec = RulesetBypassRecord(
        org="fintech-org",
        repo="payment-service",
        rule_suite_id=1001,
        ref="refs/heads/main",
        actor="lead-architect",
        evaluation_result="bypass",
        bypassed_rules="Required linear history, Pull request",
        commit_sha="a1b2c3d4e5",
        timestamp=now,
    )
    assert rule_rec.rule_suite_id == 1001
    assert rule_rec.actor == "lead-architect"


def test_repo_bypass_profile_aggregation():
    profile = RepoBypassProfile(org="fintech-org", repo="payment-service")
    profile.push_bypasses.append(
        PushProtectionBypassRecord(
            org="fintech-org",
            repo="payment-service",
            alert_number=1,
            secret_type="AWS Access Key",
            actor="engineer-a",
        )
    )
    profile.ruleset_bypasses.append(
        RulesetBypassRecord(
            org="fintech-org",
            repo="payment-service",
            rule_suite_id=99,
            ref="main",
            actor="engineer-b",
        )
    )

    assert profile.total_bypasses == 2
    assert profile.unique_actors == {"engineer-a", "engineer-b"}


def test_build_bypass_rows():
    now = datetime.now(timezone.utc)
    profile = RepoBypassProfile(org="fintech-org", repo="auth-service")
    profile.push_bypasses.append(
        PushProtectionBypassRecord(
            org="fintech-org",
            repo="auth-service",
            alert_number=10,
            secret_type="Slack Webhook URL",
            actor="dev-ops-user",
            timestamp=now,
            resolution="false_positive",
            resolution_comment="Mock webhook",
            push_protection_bypassed=True,
        )
    )
    profile.ruleset_bypasses.append(
        RulesetBypassRecord(
            org="fintech-org",
            repo="auth-service",
            rule_suite_id=505,
            ref="release/v2",
            actor="dev-ops-user",
            evaluation_result="bypass",
            bypassed_rules="Required reviews",
            commit_sha="abcdef1234",
            timestamp=now,
        )
    )

    push_rows, ruleset_rows, org_rows, actor_rows = build_bypass_rows(
        profiles=[profile],
        orgs=["fintech-org"],
    )

    assert len(push_rows) == 1
    assert push_rows[0][0] == "fintech-org"
    assert push_rows[0][1] == "auth-service"
    assert push_rows[0][3] == "Slack Webhook URL"
    assert push_rows[0][4] == "dev-ops-user"

    assert len(ruleset_rows) == 1
    assert ruleset_rows[0][0] == "fintech-org"
    assert ruleset_rows[0][2] == 505
    assert ruleset_rows[0][4] == "dev-ops-user"

    assert len(org_rows) == 1
    assert org_rows[0][0] == "fintech-org"
    assert org_rows[0][2] == 1  # Push bypasses
    assert org_rows[0][3] == 1  # Ruleset bypasses
    assert org_rows[0][4] == 2  # Total incidents
    assert org_rows[0][5] == 1  # Unique actors

    assert len(actor_rows) == 1
    assert actor_rows[0][1] == "dev-ops-user"
    assert actor_rows[0][2] == 1  # Push count
    assert actor_rows[0][3] == 1  # Ruleset count
    assert actor_rows[0][4] == 2  # Total


def test_write_bypass_workbook(tmp_path: Path):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=90)
    profile = RepoBypassProfile(org="demo-org", repo="demo-repo")

    push_rows, ruleset_rows, org_rows, actor_rows = build_bypass_rows(
        profiles=[profile],
        orgs=["demo-org"],
    )

    out_file = tmp_path / "bypass_test.xlsx"
    cfg = BypassConfig(output_dir=str(tmp_path), lookback_days=90)

    write_bypass_workbook(
        path=out_file,
        cfg=cfg,
        since=since,
        end=now,
        push_rows=push_rows,
        ruleset_rows=ruleset_rows,
        org_rows=org_rows,
        actor_rows=actor_rows,
        failures=[],
        execution_duration=1.8,
    )

    assert out_file.exists()
    wb = load_workbook(out_file)
    sheet_names = wb.sheetnames
    assert "Executive Summary" in sheet_names
    assert "Push Protection Bypasses" in sheet_names
    assert "Ruleset Bypasses" in sheet_names
    assert "Actor Accountability Ledger" in sheet_names
