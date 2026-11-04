"""Base interface for audit reporting."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

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

