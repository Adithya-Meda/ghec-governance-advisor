"""Flat CSV Report Generator for automated SIEM / BI ingestion."""

from __future__ import annotations

import csv
import os
from typing import List

from .base_reporter import BaseReporter
from ..checks.base import CheckResult


class CSVReporter(BaseReporter):
    """Generates standardized CSV audit reports."""

    def generate(
        self,
        results: List[CheckResult],
        output_path: str,
        executive_summary: str = "",
        model_name: str = "",
    ) -> str:
        """Write check results to flat CSV file."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        headers = [
            "org_name",
            "repo_name",
            "persona",
            "category",
            "check_id",
            "check_name",
            "status",
            "severity",
            "recommendation_source",
            "ai_enriched",
            "detected_stack",
            "target_config_file",
            "current_state",
            "recommended_state",
            "remediation_code_after",
            "explanation",
            "remediation_command",
            "documentation_url",
            "ai_safety_notice",
        ]

        with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(headers)
            for r in results:
                is_ai = self.is_ai_result(r)
                rec_source = "AI_TAILORED" if is_ai else "STANDARD_RULE"
                ai_enriched_str = "true" if is_ai else "false"
                safety_notice = (
                    "ADVISORY ONLY: Test and validate in non-production environments prior to deployment."
                    if is_ai
                    else ""
                )
                detected_stack = r.extra_details.get("detected_stack", "")
                target_file = self.infer_target_file(r.check_id)
                remediation_code = r.remediation_snippet_after or r.recommended_state

                writer.writerow(
                    [
                        r.org_name,
                        r.repo_name,
                        r.persona.value,
                        r.category,
                        r.check_id,
                        r.check_name,
                        r.status.value,
                        r.severity.value,
                        rec_source,
                        ai_enriched_str,
                        detected_stack,
                        target_file,
                        r.current_state,
                        r.recommended_state,
                        remediation_code,
                        r.explanation,
                        r.remediation_command,
                        r.documentation_url,
                        safety_notice,
                    ]
                )

        return output_path
