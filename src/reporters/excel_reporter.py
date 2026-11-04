"""Production-Grade Multi-Tab Excel Workbook Generator."""

from __future__ import annotations

import os
from typing import Any, Dict, List
import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .base_reporter import BaseReporter
from ..checks.base import CheckResult, CheckSeverity, CheckStatus, Persona


class ExcelReporter(BaseReporter):
    """Generates structured Excel audit reports with executive summaries and playbooks."""

    def __init__(self) -> None:
        self.font_title = Font(name="Calibri", size=16, bold=True, color="1F497D")
        self.font_subtitle = Font(name="Calibri", size=11, italic=True, color="595959")
        self.font_section = Font(name="Calibri", size=13, bold=True, color="1F497D")
        self.font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        self.font_data = Font(name="Calibri", size=11)
        self.font_bold = Font(name="Calibri", size=11, bold=True)
        self.font_italic = Font(name="Calibri", size=10, italic=True, color="595959")
        self.font_code = Font(name="Consolas", size=10)
        self.font_ai_badge = Font(name="Calibri", size=10, bold=True, color="FFFFFF")

        self.fill_header = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        self.fill_ai_header = PatternFill(start_color="4B0082", end_color="4B0082", fill_type="solid")
        self.fill_ai_badge = PatternFill(start_color="6F42C1", end_color="6F42C1", fill_type="solid")
        self.fill_pass = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
        self.fill_warn = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
        self.fill_fail = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
        self.fill_skip = PatternFill(start_color="E0E0E0", end_color="E0E0E0", fill_type="solid")

        thin = Side(border_style="thin", color="D9D9D9")
        self.border_cell = Border(left=thin, right=thin, top=thin, bottom=thin)

    def _apply_status_style(self, cell, status: CheckStatus) -> None:
        """Apply color-coded badge style to status cell."""
        if status == CheckStatus.PASS:
            cell.fill = self.fill_pass
        elif status == CheckStatus.WARN:
            cell.fill = self.fill_warn
        elif status == CheckStatus.FAIL:
            cell.fill = self.fill_fail
        else:
            cell.fill = self.fill_skip

    def _auto_adjust_columns(self, sheet) -> None:
        """Autofit column widths for readability."""
        for col in sheet.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value or "")
                first_line = val.split("\n")[0]
                if len(first_line) > max_len:
                    max_len = min(len(first_line), 45)
            sheet.column_dimensions[col_letter].width = max(max_len + 4, 12)

    def generate(
        self,
        results: List[CheckResult],
        output_path: str,
        executive_summary: str = "",
        model_name: str = "",
    ) -> str:
        """Build and write the Excel workbook."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        wb = Workbook()

        # 1. Summary Sheet with Organization Breakdown
        ws_summary = wb.active
        ws_summary.title = "Executive_Summary"
        self._build_summary_sheet(ws_summary, results, executive_summary, model_name=model_name)

        # 2. Consolidated Fleet Playbook (Aggregates identical remediations across the fleet)
        ws_playbook = wb.create_sheet(title="Fleet_Playbook")
        self._build_fleet_playbook_sheet(ws_playbook, results)

        # 3. Dedicated AI Recommendations Sheet (Consolidated per pattern)
        ws_ai = wb.create_sheet(title="AI_Recommendations")
        self._build_ai_recommendations_sheet(ws_ai, results)

        # 4. Org Admin Sheet
        ws_org = wb.create_sheet(title="Org_Admin_Findings")
        self._build_findings_sheet(
            ws_org,
            [r for r in results if r.persona == Persona.ORG_ADMIN],
            is_org=True,
        )

        # 5. Repo Admin Sheet
        ws_repo = wb.create_sheet(title="Repo_Admin_Findings")
        self._build_findings_sheet(
            ws_repo,
            [r for r in results if r.persona == Persona.REPO_ADMIN],
            is_org=False,
        )

        # 6. Contributor Sheet
        ws_contrib = wb.create_sheet(title="Contributor_Findings")
        self._build_findings_sheet(
            ws_contrib,
            [r for r in results if r.persona == Persona.CONTRIBUTOR],
            is_org=False,
        )

        wb.save(output_path)
        return output_path

    def _build_summary_sheet(
        self,
        ws,
        results: List[CheckResult],
        executive_summary: str = "",
        model_name: str = "",
    ) -> None:
        ws.views.sheetView[0].showGridLines = True
        ws["B2"] = "Repo360 Platform Governance & Intelligence Summary"
        ws["B2"].font = self.font_title

        total = len(results)
        passed = sum(1 for r in results if r.status == CheckStatus.PASS)
        warned = sum(1 for r in results if r.status == CheckStatus.WARN)
        failed = sum(1 for r in results if r.status == CheckStatus.FAIL)
        skipped = sum(1 for r in results if r.status == CheckStatus.SKIPPED)
        ai_count = sum(1 for r in results if self.is_ai_result(r))

        compliance_rate = (passed / max(total - skipped, 1)) * 100

        # Section 1: Fleet-Wide Metrics (Columns B-C)
        metrics = [
            ("Audit Execution Timestamp", self.get_local_timestamp()),
            ("Total Findings Evaluated", total),
            ("Passed Checks (PASS)", passed),
            ("Warning Risks (WARN)", warned),
            ("Failed Checks (FAIL)", failed),
            ("Skipped / Not Applicable", skipped),
            ("Overall Compliance Score", f"{compliance_rate:.1f}%"),
            ("AI-Tailored Remediations Synthesized", ai_count),
        ]

        headers_overview = ["Audit Metric", "Value"]
        for col_idx, h in enumerate(headers_overview, start=2):
            cell = ws.cell(row=5, column=col_idx, value=h)
            cell.font = self.font_header
            cell.fill = self.fill_header
            cell.alignment = Alignment(horizontal="left", vertical="center")

        for row_idx, (metric, val) in enumerate(metrics, start=6):
            c1 = ws.cell(row=row_idx, column=2, value=metric)
            c2 = ws.cell(row=row_idx, column=3, value=val)
            c1.font = self.font_data
            c2.font = self.font_bold
            c1.border = self.border_cell
            c2.border = self.border_cell
            c2.alignment = Alignment(horizontal="right", vertical="center")

            if metric == "AI-Tailored Remediations Synthesized" and ai_count > 0:
                c2.fill = self.fill_ai_badge
                c2.font = self.font_ai_badge

        # Section 2: Organization Governance & Compliance Breakdown (Columns E-M)
        org_metrics = self.build_organization_metrics(results)
        org_headers = [
            "Organization Name",
            "Repositories Audited",
            "Total Checks",
            "Controls Present (PASS)",
            "Controls Missing (FAIL)",
            "Review Items (WARN)",
            "Critical / High Risks",
            "Org Compliance Score",
            "Posture Status",
        ]

        for col_idx, h in enumerate(org_headers, start=5):
            cell = ws.cell(row=5, column=col_idx, value=h)
            cell.font = self.font_header
            cell.fill = self.fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        org_start_row = 6
        for r_offset, org_info in enumerate(org_metrics):
            row_idx = org_start_row + r_offset
            row_vals = [
                org_info["org_name"],
                org_info["repo_count"],
                org_info["total"],
                org_info["passed"],
                org_info["failed"],
                org_info["warned"],
                org_info["critical_high"],
                f"{org_info['compliance_score']:.1f}%",
                org_info["status"],
            ]
            for col_idx, val in enumerate(row_vals, start=5):
                cell = ws.cell(row=row_idx, column=col_idx, value=self.sanitize_spreadsheet_value(val))
                cell.font = self.font_data
                cell.border = self.border_cell
                cell.alignment = Alignment(horizontal="center", vertical="center")

                if col_idx == 5:  # Org Name
                    cell.alignment = Alignment(horizontal="left", vertical="center")
                    cell.font = self.font_bold
                elif col_idx == 8:  # Controls Present (PASS)
                    cell.fill = self.fill_pass
                    cell.font = self.font_bold
                elif col_idx == 9 and org_info["failed"] > 0:  # Controls Missing (FAIL)
                    cell.fill = self.fill_fail
                    cell.font = self.font_bold
                elif col_idx == 10 and org_info["warned"] > 0:  # Review Items (WARN)
                    cell.fill = self.fill_warn
                    cell.font = self.font_bold
                elif col_idx == 12:  # Compliance score
                    score_val = org_info["compliance_score"]
                    cell.fill = self.fill_pass if score_val >= 80 else (self.fill_warn if score_val >= 50 else self.fill_fail)
                    cell.font = self.font_bold
                elif col_idx == 13:  # Status
                    if org_info["status"] == "COMPLIANT":
                        cell.fill = self.fill_pass
                    elif org_info["status"] == "REVIEW NEEDED":
                        cell.fill = self.fill_warn
                    else:
                        cell.fill = self.fill_fail
                    cell.font = self.font_bold

        org_end_row = max(13, org_start_row + len(org_metrics))

        # Section 3: Executive AI Narrative
        if executive_summary:
            active_model = model_name or self.infer_ai_model(results, "Gemini")
            narrative_banner_row = org_end_row + 2

            header_cell = ws.cell(
                row=narrative_banner_row,
                column=2,
                value=f"AI Executive Risk & Governance Narrative (Synthesized via {active_model})",
            )
            header_cell.font = self.font_header
            header_cell.fill = self.fill_ai_header
            header_cell.alignment = Alignment(horizontal="left", vertical="center")
            ws.merge_cells(f"B{narrative_banner_row}:M{narrative_banner_row}")
            ws.row_dimensions[narrative_banner_row].height = 26
            for c in range(2, 14):
                ws.cell(row=narrative_banner_row, column=c).fill = self.fill_ai_header
                ws.cell(row=narrative_banner_row, column=c).border = self.border_cell

            lines = executive_summary.splitlines()
            visual_lines = 0
            for l in lines:
                l_str = l.strip()
                if not l_str:
                    visual_lines += 1
                else:
                    visual_lines += max(1, (len(l_str) + 125) // 126)

            needed_rows = max(12, visual_lines + 2)
            narrative_start_row = narrative_banner_row + 1
            narrative_end_row = narrative_start_row + needed_rows - 1

            c_narrative = ws.cell(row=narrative_start_row, column=2, value=executive_summary)
            c_narrative.font = self.font_data
            c_narrative.alignment = Alignment(wrap_text=True, vertical="top")
            ws.merge_cells(f"B{narrative_start_row}:M{narrative_end_row}")

            for r in range(narrative_start_row, narrative_end_row + 1):
                ws.row_dimensions[r].height = 18
                for c in range(2, 14):
                    ws.cell(row=r, column=c).border = self.border_cell

            notice_row = narrative_end_row + 2
        else:
            notice_row = org_end_row + 2

        c_notice = ws.cell(
            row=notice_row,
            column=2,
            value="AI Safety Notice: All AI-synthesized remediation snippets and summaries are advisory only. Review and validate in non-production environments before deployment.",
        )
        c_notice.font = self.font_italic
        c_notice.alignment = Alignment(wrap_text=True, vertical="center")
        ws.merge_cells(f"B{notice_row}:M{notice_row}")
        ws.row_dimensions[notice_row].height = 24

        self._auto_adjust_columns(ws)

        for col_char in ("D", "E", "F", "G", "H", "I", "J", "K", "L", "M"):
            if ws.column_dimensions[col_char].width < 14:
                ws.column_dimensions[col_char].width = 14

    def _build_fleet_playbook_sheet(self, ws, results: List[CheckResult]) -> None:
        """Build consolidated fleet-wide playbook grouping common remediations across repositories."""
        ws.views.sheetView[0].showGridLines = True
        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 26

        headers = [
            "Category",
            "Remediation Pattern / Check Name",
            "Severity",
            "Detected Tech Stack",
            "Target Configuration File",
            "Affected Repos Count",
            "Affected Repositories List",
            "Canonical Recommended Configuration / Code",
            "Official Documentation URL",
        ]

        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = self.font_header
            cell.fill = self.fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        clusters = self.build_remediation_clusters(results)

        if not clusters:
            ws.cell(
                row=2,
                column=1,
                value="All evaluated repositories met compliance standards. No fleet remediations required.",
            )
            ws.cell(row=2, column=1).font = self.font_italic
            ws.cell(row=2, column=1).alignment = Alignment(horizontal="center", vertical="center")
            ws.merge_cells("A2:I2")
        else:
            for row_idx, c in enumerate(clusters, start=2):
                repos_str = ", ".join(c["affected_repos"])
                values = [
                    self.sanitize_spreadsheet_value(c["category"]),
                    self.sanitize_spreadsheet_value(c["check_name"]),
                    c["severity"].value,
                    self.sanitize_spreadsheet_value(c["detected_stack"]),
                    self.sanitize_spreadsheet_value(c["target_file"]),
                    f"{c['affected_count']} repo(s)",
                    self.sanitize_spreadsheet_value(repos_str),
                    self.sanitize_spreadsheet_value(c["remediation_code"]),
                    self.sanitize_spreadsheet_value(c["documentation_url"]),
                ]

                for col_idx, val in enumerate(values, start=1):
                    cell = ws.cell(row=row_idx, column=col_idx, value=val)
                    cell.font = self.font_data
                    cell.border = self.border_cell
                    cell.alignment = Alignment(vertical="top", wrap_text=True)

                    if col_idx == 3:  # Severity column
                        cell.alignment = Alignment(horizontal="center", vertical="top")
                    elif col_idx == 6:  # Affected Repos Count
                        cell.alignment = Alignment(horizontal="center", vertical="top")
                        cell.font = self.font_bold
                    elif col_idx == 8:  # Code block
                        cell.font = self.font_code

        self._auto_adjust_columns(ws)

    def _build_ai_recommendations_sheet(self, ws, results: List[CheckResult]) -> None:
        """Build dedicated worksheet consolidating AI-synthesized remediations across repositories."""
        ws.views.sheetView[0].showGridLines = True
        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 26

        headers = [
            "Repository",
            "Category",
            "Finding / Check",
            "Severity",
            "Status",
            "Detected Tech Stack",
            "AI Model Engine",
            "Recommendation Source",
            "Target Configuration File",
            "AI-Synthesized Remediation Code / Config",
            "Why AI Recommends This",
            "Official Documentation URL",
        ]

        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = self.font_header
            cell.fill = self.fill_ai_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ai_findings = [r for r in results if self.is_ai_result(r)]
        is_fallback = False

        if not ai_findings:
            ai_findings = [
                r for r in results
                if r.status in (CheckStatus.WARN, CheckStatus.FAIL)
                and (r.remediation_snippet_after or r.recommended_state)
            ]
            is_fallback = True

        if not ai_findings:
            ws.cell(
                row=2,
                column=1,
                value="All evaluated checks met compliance standards. No remediations required.",
            )
            ws.cell(row=2, column=1).font = self.font_italic
            ws.cell(row=2, column=1).alignment = Alignment(horizontal="center", vertical="center")
            ws.merge_cells("A2:L2")
        else:
            # Consolidate by check_id to avoid repeating identical AI code blocks for every repository
            grouped_ai: Dict[str, Dict[str, Any]] = {}
            for f in ai_findings:
                key = f.check_id
                if key not in grouped_ai:
                    grouped_ai[key] = {
                        "repos": [],
                        "finding": f,
                        "stacks": set(),
                    }
                if f.repo_name and f.repo_name not in grouped_ai[key]["repos"]:
                    grouped_ai[key]["repos"].append(f.repo_name)
                stack_item = f.extra_details.get("detected_stack")
                if stack_item:
                    grouped_ai[key]["stacks"].add(stack_item)

            for row_idx, item in enumerate(grouped_ai.values(), start=2):
                f = item["finding"]
                repos_list = item["repos"]
                repos_display = ", ".join(repos_list)
                if len(repos_list) > 3:
                    repos_display = f"{len(repos_list)} repo(s): {', '.join(repos_list[:3])}..."

                stacks_list = sorted(item["stacks"])
                stack_display = ", ".join(stacks_list) if stacks_list else (
                    f.extra_details.get("detected_stack") or ("Detected Framework" if not is_fallback else "General Platform")
                )
                model_name = f.extra_details.get("ai_model") or ("gemini-3.5-flash" if not is_fallback else "Deterministic Policy Engine")
                source_label = f"AI Tailored ({model_name})" if not is_fallback else "Standard Policy (Offline Fallback)"
                target_file = self.infer_target_file(f.check_id)
                remediation_code = f.remediation_snippet_after or f.recommended_state

                values = [
                    self.sanitize_spreadsheet_value(repos_display),
                    self.sanitize_spreadsheet_value(f.category),
                    self.sanitize_spreadsheet_value(f.check_name),
                    f.severity.value,
                    f.status.value,
                    self.sanitize_spreadsheet_value(stack_display),
                    self.sanitize_spreadsheet_value(model_name),
                    self.sanitize_spreadsheet_value(source_label),
                    self.sanitize_spreadsheet_value(target_file),
                    self.sanitize_spreadsheet_value(remediation_code),
                    self.sanitize_spreadsheet_value(f.explanation),
                    self.sanitize_spreadsheet_value(f.documentation_url),
                ]

                for col_idx, val in enumerate(values, start=1):
                    cell = ws.cell(row=row_idx, column=col_idx, value=val)
                    cell.font = self.font_data
                    cell.border = self.border_cell
                    cell.alignment = Alignment(vertical="top", wrap_text=True)

                    if col_idx == 5:  # Status
                        self._apply_status_style(cell, f.status)
                    elif col_idx == 8:  # Recommendation Source badge
                        cell.fill = self.fill_ai_badge
                        cell.font = self.font_ai_badge
                        cell.alignment = Alignment(horizontal="center", vertical="top")
                    elif col_idx == 10:  # Code block
                        cell.font = self.font_code

        safety_row = ws.max_row + 2
        c_safe = ws.cell(
            row=safety_row,
            column=1,
            value="AI Safety Notice: AI-synthesized remediation snippets and configuration files are advisory only. Validate in a lower environment prior to production merge.",
        )
        c_safe.font = self.font_italic
        c_safe.alignment = Alignment(vertical="center")
        ws.merge_cells(f"A{safety_row}:L{safety_row}")
        ws.row_dimensions[safety_row].height = 22

        self._auto_adjust_columns(ws)

    def _build_findings_sheet(self, ws, findings: List[CheckResult], is_org: bool) -> None:
        """Build compact findings worksheet with clean status formatting and minimal repetition."""
        ws.views.sheetView[0].showGridLines = True
        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 24

        headers = [
            "Organization",
            "Target Resource",
            "Category",
            "Check Name",
            "Status",
            "Severity",
            "Target Configuration File",
            "Current State",
            "Recommended State",
            "Explanation & Remediation",
            "Documentation URL",
        ]

        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = self.font_header
            cell.fill = self.fill_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for row_idx, f in enumerate(findings, start=2):
            target_file = self.infer_target_file(f.check_id)

            if f.status == CheckStatus.PASS:
                current_state_val = "Control verified present and compliant."
                rec_state_val = "Maintain standard baseline."
                expl_val = "Verified compliant with organization governance policies."
                ws.row_dimensions[row_idx].height = 20
            else:
                current_state_val = f.current_state
                rec_state_val = f.recommended_state
                expl_val = f"{f.explanation} (Refer to Fleet Playbook for canonical code)"
                ws.row_dimensions[row_idx].height = 28

            values = [
                self.sanitize_spreadsheet_value(f.org_name),
                self.sanitize_spreadsheet_value(f.repo_name),
                self.sanitize_spreadsheet_value(f.category),
                self.sanitize_spreadsheet_value(f.check_name),
                f.status.value,
                f.severity.value,
                self.sanitize_spreadsheet_value(target_file),
                self.sanitize_spreadsheet_value(current_state_val),
                self.sanitize_spreadsheet_value(rec_state_val),
                self.sanitize_spreadsheet_value(expl_val),
                self.sanitize_spreadsheet_value(f.documentation_url),
            ]
            for col_idx, val in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = self.font_data
                cell.border = self.border_cell
                cell.alignment = Alignment(vertical="top", wrap_text=True)

                if col_idx == 5:  # Status column
                    self._apply_status_style(cell, f.status)

        self._auto_adjust_columns(ws)
