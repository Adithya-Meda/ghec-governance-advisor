"""Production Excel (.xlsx) Report Generator using openpyxl."""

from __future__ import annotations

import os
from typing import List
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .base_reporter import BaseReporter
from ..checks.base import CheckResult, CheckStatus, Persona


class ExcelReporter(BaseReporter):
    """Generates multi-sheet styled Excel workbooks for governance audits."""

    def __init__(self) -> None:
        self.font_title = Font(name="Calibri", size=16, bold=True, color="1F2328")
        self.font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        self.font_data = Font(name="Calibri", size=10, color="1F2328")
        self.font_bold = Font(name="Calibri", size=10, bold=True, color="1F2328")
        self.font_code = Font(name="Consolas", size=9, color="1F2328")
        self.font_ai_badge = Font(name="Calibri", size=10, bold=True, color="5A32A3")
        self.font_italic = Font(name="Calibri", size=10, italic=True, color="57606A")

        self.fill_header = PatternFill(start_color="24292F", end_color="24292F", fill_type="solid")
        self.fill_ai_header = PatternFill(start_color="5A32A3", end_color="5A32A3", fill_type="solid")  # Copilot Purple
        self.fill_ai_badge = PatternFill(start_color="F1E8FF", end_color="F1E8FF", fill_type="solid")

        self.fill_pass = PatternFill(start_color="D1F4D9", end_color="D1F4D9", fill_type="solid")
        self.fill_warn = PatternFill(start_color="FFF8C5", end_color="FFF8C5", fill_type="solid")
        self.fill_fail = PatternFill(start_color="FFEBE9", end_color="FFEBE9", fill_type="solid")
        self.fill_skip = PatternFill(start_color="F6F8FA", end_color="F6F8FA", fill_type="solid")

        thin_border = Side(border_style="thin", color="D0D7DE")
        self.border_cell = Border(
            left=thin_border, right=thin_border, top=thin_border, bottom=thin_border
        )

    def _apply_status_style(self, cell, status: CheckStatus) -> None:
        """Color-code status column."""
        cell.alignment = Alignment(horizontal="center", vertical="center")
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
                # Skip massive text lines from distorting column width
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

        # 1. Summary Sheet
        ws_summary = wb.active
        ws_summary.title = "Executive_Summary"
        self._build_summary_sheet(ws_summary, results, executive_summary, model_name=model_name)

        # 2. Dedicated AI Recommendations Sheet (Positioned right after summary for prominence)
        ws_ai = wb.create_sheet(title="AI_Recommendations")
        self._build_ai_recommendations_sheet(ws_ai, results)

        # 3. Org Admin Sheet
        ws_org = wb.create_sheet(title="Org_Admin_Findings")
        self._build_findings_sheet(
            ws_org,
            [r for r in results if r.persona == Persona.ORG_ADMIN],
            is_org=True,
        )

        # 4. Repo Admin Sheet
        ws_repo = wb.create_sheet(title="Repo_Admin_Findings")
        self._build_findings_sheet(
            ws_repo,
            [r for r in results if r.persona == Persona.REPO_ADMIN],
            is_org=False,
        )

        # 5. Contributor Sheet
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

        headers = ["Audit Metric", "Value"]
        for col_idx, h in enumerate(headers, start=2):
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

            # Emphasize AI synthesized metric
            if metric == "AI-Tailored Remediations Synthesized" and ai_count > 0:
                c2.fill = self.fill_ai_badge
                c2.font = self.font_ai_badge

        if executive_summary:
            active_model = model_name or self.infer_ai_model(results, "Gemini")

            # 1. Wide Header Banner
            header_cell = ws.cell(
                row=15,
                column=2,
                value=f"AI Executive Risk & Governance Narrative (Synthesized via {active_model})",
            )
            header_cell.font = self.font_header
            header_cell.fill = self.fill_ai_header
            header_cell.alignment = Alignment(horizontal="left", vertical="center")
            ws.merge_cells("B15:N15")
            ws.row_dimensions[15].height = 26
            for c in range(2, 15):
                ws.cell(row=15, column=c).fill = self.fill_ai_header
                ws.cell(row=15, column=c).border = self.border_cell

            # 2. Dynamic height calculation to ensure full direct visibility without clipping
            lines = executive_summary.splitlines()
            visual_lines = 0
            for l in lines:
                l_str = l.strip()
                if not l_str:
                    visual_lines += 1
                else:
                    visual_lines += max(1, (len(l_str) + 125) // 126)

            needed_rows = max(18, visual_lines + 2)
            narrative_start_row = 16
            narrative_end_row = narrative_start_row + needed_rows - 1

            c_narrative = ws.cell(row=narrative_start_row, column=2, value=executive_summary)
            c_narrative.font = self.font_data
            c_narrative.alignment = Alignment(wrap_text=True, vertical="top")
            ws.merge_cells(f"B{narrative_start_row}:N{narrative_end_row}")

            for r in range(narrative_start_row, narrative_end_row + 1):
                ws.row_dimensions[r].height = 18
                for c in range(2, 15):
                    ws.cell(row=r, column=c).border = self.border_cell

            notice_row = narrative_end_row + 2
        else:
            notice_row = 15

        c_notice = ws.cell(
            row=notice_row,
            column=2,
            value="AI Safety Notice: All AI-synthesized remediation snippets and summaries are advisory only. Review and validate in non-production environments before deployment.",
        )
        c_notice.font = self.font_italic
        c_notice.alignment = Alignment(wrap_text=True, vertical="center")
        ws.merge_cells(f"B{notice_row}:N{notice_row}")
        ws.row_dimensions[notice_row].height = 24

        self._auto_adjust_columns(ws)

        # Ensure summary narrative columns have generous width matching the wide executive banner
        for col_char in ("D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N"):
            if ws.column_dimensions[col_char].width < 13:
                ws.column_dimensions[col_char].width = 13

    def _build_ai_recommendations_sheet(self, ws, results: List[CheckResult]) -> None:
        """Build dedicated worksheet spotlighting all AI-synthesized remediations."""
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
            # Fallback mechanism: populate actionable policy remediations if AI was offline
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
            for row_idx, f in enumerate(ai_findings, start=2):
                stack = f.extra_details.get("detected_stack") or ("Detected Framework" if not is_fallback else "General Platform")
                model_name = f.extra_details.get("ai_model") or ("gemini-3.5-flash" if not is_fallback else "Deterministic Policy Engine")
                source_label = f"AI Tailored ({model_name})" if not is_fallback else "Standard Policy (Offline Fallback)"
                target_file = self.infer_target_file(f.check_id)
                remediation_code = f.remediation_snippet_after or f.recommended_state

                values = [
                    self.sanitize_spreadsheet_value(f.repo_name),
                    self.sanitize_spreadsheet_value(f.category),
                    self.sanitize_spreadsheet_value(f.check_name),
                    f.severity.value,
                    f.status.value,
                    self.sanitize_spreadsheet_value(stack),
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

            values = [
                self.sanitize_spreadsheet_value(f.org_name),
                self.sanitize_spreadsheet_value(f.repo_name),
                self.sanitize_spreadsheet_value(f.category),
                self.sanitize_spreadsheet_value(f.check_name),
                f.status.value,
                f.severity.value,
                self.sanitize_spreadsheet_value(target_file),
                self.sanitize_spreadsheet_value(f.current_state),
                self.sanitize_spreadsheet_value(f.recommended_state),
                self.sanitize_spreadsheet_value(f.explanation),
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
