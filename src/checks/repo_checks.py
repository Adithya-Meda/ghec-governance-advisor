"""Repository Admin governance, security, and CI/CD checks."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .base import BaseCheck, CheckResult, CheckSeverity, CheckStatus, Persona
from ..collector.repo_inspector import RepoInspector


class CodeownersCheck(BaseCheck):
    """Verifies that a valid CODEOWNERS file exists and assigns team ownership."""

    check_id = "codeowners_validation"
    check_name = "CODEOWNERS Configuration"
    persona = Persona.REPO_ADMIN
    category = "Governance & Maintainability"
    severity = CheckSeverity.HIGH

    def evaluate(
        self,
        inspector: RepoInspector,
        org: str,
        repo: str,
        default_branch: str,
        thresholds: Dict[str, Any],
    ) -> CheckResult:
        # Check standard locations: .github/CODEOWNERS, root CODEOWNERS, docs/CODEOWNERS
        content = (
            inspector.get_file_content(org, repo, ".github/CODEOWNERS", default_branch)
            or inspector.get_file_content(org, repo, "CODEOWNERS", default_branch)
            or inspector.get_file_content(org, repo, "docs/CODEOWNERS", default_branch)
        )

        if content and content.strip():
            # Check if default wildcard rule exists
            has_wildcard = any(
                line.strip().startswith("*") for line in content.splitlines()
            )
            if has_wildcard:
                return CheckResult(
                    check_id=self.check_id,
                    check_name=self.check_name,
                    persona=self.persona,
                    category=self.category,
                    status=CheckStatus.PASS,
                    severity=self.severity,
                    org_name=org,
                    repo_name=repo,
                    current_state="Valid CODEOWNERS file with root wildcard rule present.",
                    recommended_state="Maintain CODEOWNERS with active team handles.",
                    explanation="CODEOWNERS guarantees that changes are reviewed and approved by designated domain maintainers.",
                    documentation_url="https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners",
                )
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.WARN,
                severity=CheckSeverity.MEDIUM,
                org_name=org,
                repo_name=repo,
                current_state="CODEOWNERS file exists, but lacks a default '*' catch-all team rule.",
                recommended_state="Add a default catch-all rule '* @org/team' at the top of CODEOWNERS.",
                explanation="Without a default catch-all rule, files added to new directories may escape mandatory review.",
                remediation_snippet_before="# Partial CODEOWNERS without root rule\n/src/api/ @team-api",
                remediation_snippet_after="# Catch-all default rule\n* @org/core-maintainers\n/src/api/ @org/team-api",
                documentation_url="https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners",
            )

        return CheckResult(
            check_id=self.check_id,
            check_name=self.check_name,
            persona=self.persona,
            category=self.category,
            status=CheckStatus.FAIL,
            severity=self.severity,
            org_name=org,
            repo_name=repo,
            current_state="No CODEOWNERS file detected.",
            recommended_state="Create '.github/CODEOWNERS' defining responsible team handles.",
            explanation="Missing CODEOWNERS allows unauthorized or unreviewed modifications to critical code paths.",
            remediation_snippet_before="[Missing .github/CODEOWNERS]",
            remediation_snippet_after="# .github/CODEOWNERS\n* @org/team-leads\n/infra/ @org/devops",
            documentation_url="https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners",
        )


class BranchRulesetsCheck(BaseCheck):
    """Verifies that branch rulesets or protection rules guard the default branch."""

    check_id = "branch_rulesets"
    check_name = "Branch Governance & Approval Gates"
    persona = Persona.REPO_ADMIN
    category = "Governance & Delivery"
    severity = CheckSeverity.CRITICAL

    def evaluate(
        self,
        inspector: RepoInspector,
        org: str,
        repo: str,
        default_branch: str,
        thresholds: Dict[str, Any],
    ) -> CheckResult:
        required_approvals = thresholds.get("minimum_approvals", 2)
        if isinstance(required_approvals, dict):
            required_approvals = 2

        # Check repo rulesets first
        rulesets = inspector.get_repo_rulesets(org, repo)
        active_rulesets = [
            r for r in rulesets if r.get("enforcement") in ("active", "evaluate")
        ]

        # Check classic branch protection
        protection = inspector.get_branch_protection(org, repo, default_branch)

        has_protection = bool(active_rulesets or protection)
        if not has_protection:
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.FAIL,
                severity=self.severity,
                org_name=org,
                repo_name=repo,
                current_state=f"Default branch '{default_branch}' has no rulesets or protection enabled.",
                recommended_state=f"Apply a ruleset requiring PR approvals (min {required_approvals}).",
                explanation=f"Default branch must enforce peer reviews and status checks prior to merging into {default_branch}.",
                remediation_snippet_before="Direct push allowed to main without PR review or status checks.",
                remediation_snippet_after=f"Repository Ruleset targeting '{default_branch}':\n- Require Pull Request with {required_approvals} approvals\n- Require status checks to pass\n- Block force pushes and deletions",
                documentation_url="https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets",
            )

        # Inspect required approvals if classic protection exists
        current_approvals = 0
        if protection and isinstance(protection, dict):
            pr_reviews = protection.get("required_pull_request_reviews", {})
            current_approvals = pr_reviews.get("required_approving_review_count", 0)

        if current_approvals < required_approvals:
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.WARN,
                severity=CheckSeverity.HIGH,
                org_name=org,
                repo_name=repo,
                current_state=f"Approval count ({current_approvals}) is below policy threshold ({required_approvals}).",
                recommended_state=f"Increase required approving review count to at least {required_approvals}.",
                explanation=f"Pull requests require at least {required_approvals} approving reviews to protect code quality.",
                remediation_snippet_before=f"Required approvals: {current_approvals}",
                remediation_snippet_after=f"Required approvals: {required_approvals} (with dismissal of stale reviews)",
                documentation_url="https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets",
            )

        approval_noun = "approval" if required_approvals == 1 else "approvals"
        return CheckResult(
            check_id=self.check_id,
            check_name=self.check_name,
            persona=self.persona,
            category=self.category,
            status=CheckStatus.PASS,
            severity=self.severity,
            org_name=org,
            repo_name=repo,
            current_state=f"Branch ruleset/protection active on '{default_branch}' compliant with {required_approvals} {approval_noun} standard.",
            recommended_state=f"Maintain branch protection policy.",
            explanation="Default branch has active protection rules enforcing reviews.",
            documentation_url="https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets",
        )


class WorkflowShaPinningCheck(BaseCheck):
    """Verifies that GitHub Actions use immutable commit SHAs instead of mutable tags."""

    check_id = "workflow_sha_pinning"
    check_name = "GitHub Actions Immutable SHA Pinning"
    persona = Persona.REPO_ADMIN
    category = "Supply Chain Security"
    severity = CheckSeverity.HIGH

    MUTABLE_TAG_PATTERN = re.compile(
        r"uses:\s*([a-zA-Z0-9_\-\.]+\/[a-zA-Z0-9_\-\.]+)(?:@[a-zA-Z0-9_\-\.]+)"
    )
    SHA_PATTERN = re.compile(r"@[a-f0-9]{40}")

    def evaluate(
        self,
        inspector: RepoInspector,
        org: str,
        repo: str,
        default_branch: str,
        thresholds: Dict[str, Any],
    ) -> CheckResult:
        workflows = inspector.list_workflows(org, repo)
        if not workflows:
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.SKIPPED,
                severity=CheckSeverity.INFO,
                org_name=org,
                repo_name=repo,
                current_state="No GitHub Actions workflows configured in repository.",
                recommended_state="Use immutable SHAs when adopting Actions.",
                explanation="No workflow YAML files to inspect.",
                documentation_url="https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#using-third-party-actions",
            )

        unpinned_actions: List[str] = []
        for wf in workflows:
            wf_path = wf.get("path")
            if not wf_path:
                continue
            content = inspector.get_file_content(org, repo, wf_path, default_branch)
            if not content:
                continue

            for line in content.splitlines():
                if "uses:" in line and not line.strip().startswith("#"):
                    # Exclude local actions (./) or docker actions (docker://)
                    if "./" in line or "docker://" in line:
                        continue
                    if not self.SHA_PATTERN.search(line):
                        match = self.MUTABLE_TAG_PATTERN.search(line)
                        if match:
                            unpinned_actions.append(f"{wf.get('name')}: {match.group(0).strip()}")

        if unpinned_actions:
            sample_unpinned = unpinned_actions[:3]
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.WARN,
                severity=self.severity,
                org_name=org,
                repo_name=repo,
                current_state=f"{len(unpinned_actions)} unpinned third-party actions detected: {'; '.join(sample_unpinned)}",
                recommended_state="Pin actions to immutable 40-character commit SHAs with comments.",
                explanation="Mutable tags (e.g., @v4) can be retargeted or hijacked by malicious actors to inject supply-chain attacks.",
                remediation_snippet_before="- uses: actions/checkout@v4",
                remediation_snippet_after="- uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1",
                documentation_url="https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#using-third-party-actions",
            )

        return CheckResult(
            check_id=self.check_id,
            check_name=self.check_name,
            persona=self.persona,
            category=self.category,
            status=CheckStatus.PASS,
            severity=self.severity,
            org_name=org,
            repo_name=repo,
            current_state="All audited GitHub Actions utilize immutable commit SHAs.",
            recommended_state="Continue pinning all action versions via SHA.",
            explanation="Immutable pinning guards against supply-chain tampering.",
            documentation_url="https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#using-third-party-actions",
        )


class WorkflowConcurrencyGroupsCheck(BaseCheck):
    """Verifies workflows define concurrency groups to auto-cancel redundant builds."""

    check_id = "workflow_concurrency_groups"
    check_name = "CI Concurrency & Cost Optimization"
    persona = Persona.REPO_ADMIN
    category = "CI/CD & Cost"
    severity = CheckSeverity.MEDIUM

    def evaluate(
        self,
        inspector: RepoInspector,
        org: str,
        repo: str,
        default_branch: str,
        thresholds: Dict[str, Any],
    ) -> CheckResult:
        workflows = inspector.list_workflows(org, repo)
        if not workflows:
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.SKIPPED,
                severity=CheckSeverity.INFO,
                org_name=org,
                repo_name=repo,
                current_state="No workflows present.",
                recommended_state="Add concurrency controls when workflows are created.",
                explanation="No workflow files found.",
                documentation_url="https://docs.github.com/en/actions/using-jobs/using-concurrency",
            )

        missing_concurrency: List[str] = []
        for wf in workflows:
            wf_path = wf.get("path")
            if not wf_path:
                continue
            content = inspector.get_file_content(org, repo, wf_path, default_branch)
            if content and "concurrency:" not in content:
                missing_concurrency.append(wf.get("name", wf_path))

        if missing_concurrency:
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.WARN,
                severity=self.severity,
                org_name=org,
                repo_name=repo,
                current_state=f"Workflows missing concurrency controls: {', '.join(missing_concurrency[:3])}",
                recommended_state="Configure concurrency with cancel-in-progress: true.",
                explanation="Without concurrency groups, pushing multiple commits in a PR queues redundant builds, wasting cloud runner minutes.",
                remediation_snippet_before="# Workflow without concurrency\non: [pull_request]\njobs: ...",
                remediation_snippet_after="concurrency:\n  group: ${{ github.workflow }}-${{ github.ref }}\n  cancel-in-progress: true",
                documentation_url="https://docs.github.com/en/actions/using-jobs/using-concurrency",
            )

        return CheckResult(
            check_id=self.check_id,
            check_name=self.check_name,
            persona=self.persona,
            category=self.category,
            status=CheckStatus.PASS,
            severity=self.severity,
            org_name=org,
            repo_name=repo,
            current_state="Workflows implement concurrency cancellation groups.",
            recommended_state="Maintain concurrency groups on branch builds.",
            explanation="Redundant in-flight CI runs are automatically canceled.",
            documentation_url="https://docs.github.com/en/actions/using-jobs/using-concurrency",
        )


class DependabotConfigCheck(BaseCheck):
    """Verifies that Dependabot version and security updates are configured."""

    check_id = "dependabot_configuration"
    check_name = "Dependabot Dependency Hygiene"
    persona = Persona.REPO_ADMIN
    category = "Security"
    severity = CheckSeverity.HIGH

    def evaluate(
        self,
        inspector: RepoInspector,
        org: str,
        repo: str,
        default_branch: str,
        thresholds: Dict[str, Any],
    ) -> CheckResult:
        has_dependabot = (
            inspector.check_file_exists(org, repo, ".github/dependabot.yml", default_branch)
            or inspector.check_file_exists(org, repo, ".github/dependabot.yaml", default_branch)
        )

        if has_dependabot:
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.PASS,
                severity=self.severity,
                org_name=org,
                repo_name=repo,
                current_state="Dependabot configuration file found.",
                recommended_state="Keep package ecosystems updated in dependabot.yml.",
                explanation="Dependabot automates patch updates for vulnerable dependencies.",
                documentation_url="https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuring-dependabot-version-updates",
            )

        return CheckResult(
            check_id=self.check_id,
            check_name=self.check_name,
            persona=self.persona,
            category=self.category,
            status=CheckStatus.FAIL,
            severity=self.severity,
            org_name=org,
            repo_name=repo,
            current_state="Missing .github/dependabot.yml file.",
            recommended_state="Add .github/dependabot.yml for your ecosystem (e.g., pip, npm, docker).",
            explanation="Unmonitored third-party dependencies accumulate unpatched CVEs over time.",
            remediation_snippet_before="[No dependabot.yml file]",
            remediation_snippet_after="version: 2\nupdates:\n  - package-ecosystem: 'pip'\n    directory: '/'\n    schedule:\n      interval: 'weekly'",
            documentation_url="https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuring-dependabot-version-updates",
        )

