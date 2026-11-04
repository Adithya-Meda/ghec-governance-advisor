"""Organization Admin governance and security checks."""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseCheck, CheckResult, CheckSeverity, CheckStatus, Persona
from ..collector.repo_inspector import RepoInspector


class OrgRulesetsCheck(BaseCheck):
    """Verifies that organization-level repository rulesets are enforced."""

    check_id = "rulesets_adoption"
    check_name = "Organization Rulesets Enforcement"
    persona = Persona.ORG_ADMIN
    category = "Governance & Compliance"
    severity = CheckSeverity.HIGH

    def evaluate(
        self, inspector: RepoInspector, org: str, thresholds: Dict[str, Any]
    ) -> CheckResult:
        rulesets = inspector.get_org_rulesets(org)
        active_rulesets = [
            r for r in rulesets if r.get("enforcement") in ("active", "evaluate")
        ]

        if active_rulesets:
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.PASS,
                severity=self.severity,
                org_name=org,
                repo_name="Organization-Wide",
                current_state=f"{len(active_rulesets)} active organization rulesets detected.",
                recommended_state="Enforce centralized organization rulesets across all repositories.",
                explanation="Organization rulesets centrally protect default branches and prevent unauthorized policy bypasses.",
                documentation_url="https://docs.github.com/en/enterprise-cloud@latest/organizations/managing-organization-settings/managing-rulesets-for-repositories-in-your-organization",
            )

        return CheckResult(
            check_id=self.check_id,
            check_name=self.check_name,
            persona=self.persona,
            category=self.category,
            status=CheckStatus.FAIL,
            severity=self.severity,
            org_name=org,
            repo_name="Organization-Wide",
            current_state="No active organization-level rulesets found.",
            recommended_state="Create centralized organization rulesets targeting default and release branches.",
            explanation="Without org-level rulesets, branch security depends on disparate repository configurations which creates compliance drift.",
            remediation_snippet_before="Legacy individual repo branch protection or unmanaged branches.",
            remediation_snippet_after="Organization Settings -> Repository Rulesets -> New ruleset: Enforce on 'All repositories' with required pull request reviews & linear history.",
            remediation_command="gh api --method POST /orgs/{org}/rulesets -f name='Standard Branch Governance'",
            documentation_url="https://docs.github.com/en/enterprise-cloud@latest/organizations/managing-organization-settings/managing-rulesets-for-repositories-in-your-organization",
        )


class OrgSecretScanningPushProtectionCheck(BaseCheck):
    """Verifies that Secret Scanning Push Protection is active across the organization."""

    check_id = "secret_scanning_push_protection"
    check_name = "Organization Secret Scanning Push Protection"
    persona = Persona.ORG_ADMIN
    category = "Security"
    severity = CheckSeverity.CRITICAL

    def evaluate(
        self, inspector: RepoInspector, org: str, thresholds: Dict[str, Any]
    ) -> CheckResult:
        org_data = inspector.get_org_info(org) or {}
        # Secret scanning and push protection are reported on the org payload or security managers
        security_features = org_data.get("security_and_analysis", {})
        secret_scanning = security_features.get("secret_scanning", {}).get("status")
        push_protection = security_features.get(
            "secret_scanning_push_protection", {}
        ).get("status")

        if push_protection == "enabled" or secret_scanning == "enabled":
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.PASS,
                severity=self.severity,
                org_name=org,
                repo_name="Organization-Wide",
                current_state="Secret Scanning & Push Protection enabled org-wide.",
                recommended_state="Enable Secret Scanning Push Protection for all existing and new repositories.",
                explanation="Push protection blocks developers from accidentally pushing secrets, credentials, and API keys before they reach git history.",
                documentation_url="https://docs.github.com/en/enterprise-cloud@latest/code-security/secret-scanning/push-protection-for-repositories-and-organizations",
            )

        return CheckResult(
            check_id=self.check_id,
            check_name=self.check_name,
            persona=self.persona,
            category=self.category,
            status=CheckStatus.FAIL,
            severity=self.severity,
            org_name=org,
            repo_name="Organization-Wide",
            current_state="Secret scanning push protection is not enabled org-wide.",
            recommended_state="Enable Secret Scanning & Push Protection automatically for all repositories.",
            explanation="Exposing secrets in Git history requires costly credential revocation and poses high breach risk.",
            remediation_snippet_before="Push protection: Disabled (developers can push raw API keys/tokens)",
            remediation_snippet_after="Organization Settings -> Code security and analysis -> Secret scanning & Push protection: Checked and enforced for new repos.",
            remediation_command="gh api --method PATCH /orgs/{org} -F 'secret_scanning_push_protection_custom_link=https://wiki.internal/security'",
            documentation_url="https://docs.github.com/en/enterprise-cloud@latest/code-security/secret-scanning/push-protection-for-repositories-and-organizations",
        )


class OrgRunnerGroupsCheck(BaseCheck):
    """Audits self-hosted runner groups to prevent unrestricted repository access."""

    check_id = "runner_groups_governance"
    check_name = "Runner Groups Least Privilege Isolation"
    persona = Persona.ORG_ADMIN
    category = "Infrastructure & CI/CD"
    severity = CheckSeverity.MEDIUM

    def evaluate(
        self, inspector: RepoInspector, org: str, thresholds: Dict[str, Any]
    ) -> CheckResult:
        runner_groups = inspector.get_org_runner_groups(org)
        if not runner_groups:
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.PASS,
                severity=self.severity,
                org_name=org,
                repo_name="Organization-Wide",
                current_state="No unmanaged self-hosted runner groups detected (using GitHub-hosted runners).",
                recommended_state="Ensure all self-hosted runner groups restrict visibility to approved repositories.",
                explanation="Restricting runner groups prevents untrusted public or internal forks from executing arbitrary commands on internal build infrastructure.",
                documentation_url="https://docs.github.com/en/enterprise-cloud@latest/actions/hosting-your-own-runners/managing-self-hosted-runners/managing-access-to-self-hosted-runners-using-groups",
            )

        unrestricted_groups = [
            g.get("name")
            for g in runner_groups
            if g.get("visibility") == "all" and not g.get("default")
        ]

        if unrestricted_groups:
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.WARN,
                severity=self.severity,
                org_name=org,
                repo_name="Organization-Wide",
                current_state=f"Runner groups accessible to all repositories: {', '.join(unrestricted_groups)}",
                recommended_state="Restrict custom runner groups to explicit repository lists.",
                explanation="Unrestricted runner groups allow any repository to consume build compute and potentially access internal network credentials.",
                remediation_snippet_before="Runner Group Visibility: All repositories",
                remediation_snippet_after="Runner Group Visibility: Selected repositories only",
                documentation_url="https://docs.github.com/en/enterprise-cloud@latest/actions/hosting-your-own-runners/managing-self-hosted-runners/managing-access-to-self-hosted-runners-using-groups",
            )

        return CheckResult(
            check_id=self.check_id,
            check_name=self.check_name,
            persona=self.persona,
            category=self.category,
            status=CheckStatus.PASS,
            severity=self.severity,
            org_name=org,
            repo_name="Organization-Wide",
            current_state="Self-hosted runner groups adhere to restricted visibility.",
            recommended_state="Maintain repository isolation on runner groups.",
            explanation="Runner groups are isolated to approved repositories.",
            documentation_url="https://docs.github.com/en/enterprise-cloud@latest/actions/hosting-your-own-runners/managing-self-hosted-runners/managing-access-to-self-hosted-runners-using-groups",
        )


class OrgDefaultWorkflowPermissionsCheck(BaseCheck):
    """Verifies default GITHUB_TOKEN permissions are read-only across the org."""

    check_id = "default_workflow_permissions"
    check_name = "Default GITHUB_TOKEN Least Privilege"
    persona = Persona.ORG_ADMIN
    category = "Security"
    severity = CheckSeverity.HIGH

    def evaluate(
        self, inspector: RepoInspector, org: str, thresholds: Dict[str, Any]
    ) -> CheckResult:
        perms = inspector.get_org_actions_permissions(org) or {}
        default_perm = perms.get("default_workflow_permissions", "read")

        if default_perm == "read":
            return CheckResult(
                check_id=self.check_id,
                check_name=self.check_name,
                persona=self.persona,
                category=self.category,
                status=CheckStatus.PASS,
                severity=self.severity,
                org_name=org,
                repo_name="Organization-Wide",
                current_state="Default workflow permission is set to Read-only.",
                recommended_state="Enforce read-only default GITHUB_TOKEN permissions org-wide.",
                explanation="Default read-only permissions prevent workflow compromise from automatically granting write access to repositories.",
                documentation_url="https://docs.github.com/en/enterprise-cloud@latest/actions/security-guides/automatic-token-authentication#modifying-the-permissions-for-the-github_token",
            )

        return CheckResult(
            check_id=self.check_id,
            check_name=self.check_name,
            persona=self.persona,
            category=self.category,
            status=CheckStatus.FAIL,
            severity=self.severity,
            org_name=org,
            repo_name="Organization-Wide",
            current_state="Default workflow permission is set to Read and Write.",
            recommended_state="Change organization default workflow permission to Read-only.",
            explanation="Read/write tokens allow any compromised workflow dependency to push code or alter releases.",
            remediation_snippet_before="Workflow permissions: Read and write permissions",
            remediation_snippet_after="Organization Settings -> Actions -> General -> Workflow permissions: 'Read repository contents and packages permissions'",
            remediation_command="gh api --method PUT /orgs/{org}/actions/permissions/workflow -F default_workflow_permissions='read'",
            documentation_url="https://docs.github.com/en/enterprise-cloud@latest/actions/security-guides/automatic-token-authentication",
        )

