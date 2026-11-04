"""Unit tests for Excel, CSV, and HTML report generators."""

import os
import tempfile
import openpyxl
import pytest

from src.reporters.csv_reporter import CSVReporter
from src.reporters.excel_reporter import ExcelReporter
from src.reporters.html_reporter import HTMLReporter
from tests.conftest import create_mock_results
from src.validator import RepoTarget


@pytest.fixture
def mock_results() -> list:
    targets = [
        RepoTarget(
            org_name="fintech-core",
            repo_name="payment-gateway",
            target_personas={"all"},
        )
    ]
    return create_mock_results(targets)


def test_excel_reporter_generation(mock_results: list) -> None:
    """Verify Excel report generates properly structured workbook with dedicated AI sheet."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as f:
        temp_path = f.name

    try:
        reporter = ExcelReporter()
        executive_summary = "High risk gaps identified in branch rulesets and token security."
        saved_path = reporter.generate(mock_results, temp_path, executive_summary)
        assert os.path.exists(saved_path)

        # Inspect generated workbook
        wb = openpyxl.load_workbook(saved_path)
        expected_sheets = {
            "Executive_Summary",
            "Fleet_Playbook",
            "AI_Recommendations",
            "Org_Admin_Findings",
            "Repo_Admin_Findings",
            "Contributor_Findings",
        }
        assert expected_sheets.issubset(set(wb.sheetnames))

        # 1. Verify Executive Summary
        ws_summary = wb["Executive_Summary"]
        assert ws_summary["B2"].value == "Repo360 Platform Governance & Intelligence Summary"
        # Check that AI KPI row exists
        metric_labels = [ws_summary.cell(row=r, column=2).value for r in range(5, 15)]
        assert "Audit Execution Timestamp" in metric_labels
        assert "AI-Tailored Remediations Synthesized" in metric_labels

        # 2. Verify Consolidated Fleet Playbook Sheet
        ws_playbook = wb["Fleet_Playbook"]
        playbook_headers = [cell.value for cell in ws_playbook[1]]
        assert "Category" in playbook_headers
        assert "Remediation Pattern / Check Name" in playbook_headers
        assert "Affected Repos Count" in playbook_headers
        assert "Affected Repositories List" in playbook_headers
        assert "Canonical Recommended Configuration / Code" in playbook_headers
        assert ws_playbook.max_row >= 2

        # 3. Verify Dedicated AI Recommendations Sheet
        ws_ai = wb["AI_Recommendations"]
        ai_headers = [cell.value for cell in ws_ai[1]]
        assert "Repository" in ai_headers
        assert "Detected Tech Stack" in ai_headers
        assert "AI Model Engine" in ai_headers
        assert "Recommendation Source" in ai_headers
        assert "AI-Synthesized Remediation Code / Config" in ai_headers
        assert "Target Configuration File" in ai_headers
        assert "CLI Remediation Command" not in ai_headers

        # Check that rows were populated
        assert ws_ai.max_row >= 2
        # Verify AI data row
        row2_values = [cell.value for cell in ws_ai[2]]
        assert any("payment-gateway" in str(v) for v in row2_values)

        # 3. Verify Findings Sheets do not clutter with Recommendation Source or Remediation Code (After)
        ws_contrib = wb["Contributor_Findings"]
        contrib_headers = [cell.value for cell in ws_contrib[1]]
        assert "Recommendation Source" not in contrib_headers
        assert "Target Configuration File" in contrib_headers
        assert "Remediation Code (After)" not in contrib_headers
        assert "Recommended State" in contrib_headers
        assert "Explanation & Remediation" in contrib_headers

        ws_repo = wb["Repo_Admin_Findings"]
        repo_headers = [cell.value for cell in ws_repo[1]]
        assert "Recommendation Source" not in repo_headers
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_csv_reporter_generation(mock_results: list) -> None:
    """Verify flat CSV output format includes AI classification columns."""
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv", encoding="utf-8") as f:
        temp_path = f.name

    try:
        reporter = CSVReporter()
        saved_path = reporter.generate(mock_results, temp_path)
        assert os.path.exists(saved_path)

        with open(saved_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) > 1
        header_line = lines[0]
        assert "recommendation_source" in header_line
        assert "ai_enriched" in header_line
        assert "detected_stack" in header_line
        assert "remediation_cluster_key" in header_line
        assert "target_config_file" in header_line
        assert "remediation_code_after" in header_line
        assert "remediation_command" not in header_line

        full_content = "".join(lines)
        assert "AI_TAILORED" in full_content
        assert "STANDARD_RULE" in full_content
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_html_reporter_generation(mock_results: list) -> None:
    """Verify HTML report includes AI classification, filter buttons, and KPI cards."""
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html", encoding="utf-8") as f:
        temp_path = f.name

    try:
        reporter = HTMLReporter()
        executive_summary = "Organization requires immediate enforcement of branch rulesets."
        saved_path = reporter.generate(mock_results, temp_path, executive_summary)
        assert os.path.exists(saved_path)

        with open(saved_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "Repo360 Platform Governance & Intelligence Report" in content or "Repo360" in content
        assert "Compliance Score" in content
        assert "AI Remediations" in content
        assert "Consolidated Fleet Playbook" in content
        assert "Repository Drill-Down" in content
        assert "playbook-view-container" in content
        assert "repo-view-container" in content
        assert "repo-chip" in content
        assert "Affected Fleet Scope:" in content
        assert "AI Tailored Only" in content
        assert "Standard Rules Only" in content
        assert 'data-source="ai"' in content
        assert 'data-source="standard"' in content
        assert "badge-ai" in content
        assert "diff-container" in content
        assert "AI-Synthesized Configuration" in content
        assert "CLI Remediation" not in content
        assert "Audit Run Generated:" in content
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_formula_injection_defense() -> None:
    """Verify spreadsheet formula injection (CWE-1236) elements are neutralized with single quotes."""
    from src.checks.base import CheckResult, CheckStatus, CheckSeverity, Persona

    injected_result = CheckResult(
        check_id="test_injection",
        check_name="=1+1",
        persona=Persona.REPO_ADMIN,
        category="+Security",
        status=CheckStatus.FAIL,
        severity=CheckSeverity.HIGH,
        current_state="-old",
        recommended_state="@calc",
        explanation="=cmd|'/C calc'!A0",
        remediation_command="-rm -rf /",
        documentation_url="https://example.com",
        org_name="=MALICIOUS_ORG",
        repo_name="@malicious_repo",
    )

    # Test CSV
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".csv", encoding="utf-8") as f:
        csv_path = f.name
    try:
        CSVReporter().generate([injected_result], csv_path)
        with open(csv_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "'=MALICIOUS_ORG" in content
        assert "'@malicious_repo" in content
        assert "'+Security" in content
        assert "'-old" in content
        assert "'@calc" in content
        assert "'=cmd|'/C calc'!A0" in content
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)

    # Test Excel
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as f:
        xlsx_path = f.name
    try:
        ExcelReporter().generate([injected_result], xlsx_path)
        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb["Repo_Admin_Findings"]
        row2 = [cell.value for cell in ws[2]]
        assert "'=MALICIOUS_ORG" in row2
        assert "'@malicious_repo" in row2
        assert "'+Security" in row2
    finally:
        if os.path.exists(xlsx_path):
            os.remove(xlsx_path)


def test_local_timestamp_dd_mm_yyyy_format() -> None:
    """Verify local timestamp conforms to DD-MM-YYYY format."""
    import re
    from src.reporters.base_reporter import BaseReporter

    ts = BaseReporter.get_local_timestamp()
    # Expect: DD-MM-YYYY HH:MM:SS TZ (e.g. 04-11-2026 19:10:00 IST)
    match = re.match(r"^(\d{2})-(\d{2})-(\d{4})\s+\d{2}:\d{2}:\d{2}(?:\s+[A-Za-z0-9_-]+)?$", ts)
    assert match is not None, f"Timestamp '{ts}' does not match DD-MM-YYYY pattern."
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    assert 1 <= day <= 31
    assert 1 <= month <= 12
    assert year >= 2024
