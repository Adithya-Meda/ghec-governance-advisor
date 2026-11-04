"""Base interface for audit reporting."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List

from ..checks.base import CheckResult


class BaseReporter(ABC):
    """Abstract base class for all report generators."""

    @abstractmethod
    def generate(
        self,
        results: List[CheckResult],
        output_path: str,
        executive_summary: str = "",
        model_name: str = "",
    ) -> str:
        """Generate report file and return the saved file path."""
        pass

    @staticmethod
    def get_local_timestamp() -> str:
        """Return formatted local timestamp with smart timezone detection (e.g. 2026-11-04 16:22:00 IST)."""
        now = datetime.now().astimezone()
        tz_name = now.tzname() or "UTC"
        tz_abbreviations = {
            "India Standard Time": "IST",
            "Pacific Standard Time": "PST",
            "Pacific Daylight Time": "PDT",
            "Eastern Standard Time": "EST",
            "Eastern Daylight Time": "EDT",
            "Central Standard Time": "CST",
            "Central Daylight Time": "CDT",
            "Mountain Standard Time": "MST",
            "Mountain Daylight Time": "MDT",
            "Greenwich Mean Time": "GMT",
            "Coordinated Universal Time": "UTC",
            "W. Europe Standard Time": "CET",
            "Central Europe Standard Time": "CET",
            "Romance Standard Time": "CET",
            "GMT Standard Time": "GMT",
            "Singapore Standard Time": "SGT",
            "Tokyo Standard Time": "JST",
            "China Standard Time": "CST",
            "AUS Eastern Standard Time": "AEST",
        }
        tz_abbr = tz_abbreviations.get(tz_name, tz_name)
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')} {tz_abbr}"

    @staticmethod
    def sanitize_spreadsheet_value(value: object) -> object:
        """Sanitize values against CSV / Excel Formula Injection (CWE-1236).

        Prepends a single quote if the string begins with =, +, -, @, tab, or carriage return.
        """
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
            return f"'{value}"
        return value

    @staticmethod
    def infer_ai_model(results: List[CheckResult], fallback: str = "Gemini") -> str:
        """Extract the active AI model name from audit findings."""
        for r in results:
            m = r.extra_details.get("ai_model")
            if m:
                return m
        return fallback

    @staticmethod
    def is_ai_result(result: CheckResult) -> bool:
        """Return True if finding was enriched with AI-synthesized remediation."""
        if result.extra_details.get("ai_enriched"):
            return True
        if result.remediation_snippet_after and "[AI Tailored" in result.remediation_snippet_after:
            return True
        return False

    @staticmethod
    def infer_target_file(check_id: str) -> str:
        """Map check ID to the relevant repository or governance configuration file."""
        file_map = {
            "copilot_instructions": ".github/copilot-instructions.md",
            "devcontainers": ".devcontainer/devcontainer.json",
            "dependabot_configuration": ".github/dependabot.yml",
            "workflow_sha_pinning": ".github/workflows/*.yml",
            "workflow_concurrency_groups": ".github/workflows/*.yml",
            "codeowners_validation": ".github/CODEOWNERS",
            "pull_request_templates": ".github/PULL_REQUEST_TEMPLATE.md",
            "issue_templates": ".github/ISSUE_TEMPLATE/bug_report.yml",
            "pre_commit_hooks": ".pre-commit-config.yaml",
            "rulesets_adoption": "Repository Rulesets (Settings)",
            "secret_scanning_push_protection": "Code Security (Settings)",
            "default_workflow_permissions": "Actions Permissions (Settings)",
            "runner_groups_isolation": "Actions Runner Groups (Settings)",
        }
        return file_map.get(check_id, "Repository / Organization Config")

    @classmethod
    def build_remediation_clusters(cls, results: List[CheckResult]) -> List[Dict[str, Any]]:
        """Cluster actionable WARN/FAIL findings by check and tech stack for consolidated fleet playbooks."""
        from ..checks.base import CheckStatus

        clusters: Dict[str, Dict[str, Any]] = {}

        for r in results:
            if r.status not in (CheckStatus.WARN, CheckStatus.FAIL):
                continue

            stack = r.extra_details.get("detected_stack") or ""
            cluster_key = f"{r.check_id}:{stack}" if stack else r.check_id

            if cluster_key not in clusters:
                remediation_code = r.remediation_snippet_after or r.recommended_state
                clusters[cluster_key] = {
                    "cluster_key": cluster_key,
                    "check_id": r.check_id,
                    "check_name": r.check_name,
                    "category": r.category,
                    "severity": r.severity,
                    "persona": r.persona,
                    "detected_stack": stack or "General Platform",
                    "target_file": cls.infer_target_file(r.check_id),
                    "current_state": r.current_state,
                    "recommended_state": r.recommended_state,
                    "remediation_code": remediation_code,
                    "remediation_snippet_before": r.remediation_snippet_before,
                    "explanation": r.explanation,
                    "documentation_url": r.documentation_url,
                    "is_ai": cls.is_ai_result(r),
                    "ai_model": r.extra_details.get("ai_model", ""),
                    "affected_repos": [],
                }

            repo_label = r.repo_name if r.repo_name != "Organization-Wide" else f"{r.org_name} (Org-Wide)"
            if repo_label not in clusters[cluster_key]["affected_repos"]:
                clusters[cluster_key]["affected_repos"].append(repo_label)

        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        cluster_list = list(clusters.values())
        for c in cluster_list:
            c["affected_count"] = len(c["affected_repos"])
            c["affected_repos"].sort()

        cluster_list.sort(
            key=lambda x: (
                severity_order.get(x["severity"].value, 99),
                -x["affected_count"],
            )
        )
        return cluster_list

