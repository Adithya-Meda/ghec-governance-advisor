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
        assert "AI-Tailored Remediations Synthesized" in metric_labels

        # 2. Verify Dedicated AI Recommendations Sheet
        ws_ai = wb["AI_Recommendations"]
        ai_headers = [cell.value for cell in ws_ai[1]]
        assert "Repository" in ai_headers
        assert "Detected Tech Stack" in ai_headers
        assert "AI Model Engine" in ai_headers
        assert "Recommendation Source" in ai_headers
        assert "AI-Synthesized Remediation Code / Config" in ai_headers
        assert "Target Configuration File" in ai_headers

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
        assert "target_config_file" in header_line
        assert "remediation_code_after" in header_line

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
        assert "AI Tailored Only" in content
        assert "Standard Rules Only" in content
        assert 'data-source="ai"' in content
        assert 'data-source="standard"' in content
        assert "badge-ai" in content
        assert "diff-container" in content
        assert "AI-Synthesized Configuration" in content
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
