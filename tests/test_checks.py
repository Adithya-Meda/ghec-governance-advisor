"""Unit tests for individual Org, Repo, and Contributor checks."""

from unittest.mock import MagicMock
import pytest

from src.checks.base import CheckStatus
from src.checks.org_checks import (
    OrgDefaultWorkflowPermissionsCheck,
    OrgRulesetsCheck,
    OrgRunnerGroupsCheck,
    OrgSecretScanningPushProtectionCheck,
)
from src.checks.repo_checks import (
    BranchRulesetsCheck,
    CodeownersCheck,
    DependabotConfigCheck,
    WorkflowConcurrencyGroupsCheck,
    WorkflowShaPinningCheck,
)
from src.checks.contributor_checks import (
    CopilotInstructionsCheck,
    DevcontainersCheck,
    IssueTemplatesCheck,
    PreCommitHooksCheck,
    PullRequestTemplatesCheck,
)


# --- Org Checks ---

def test_org_rulesets_check() -> None:
    inspector = MagicMock()
    check = OrgRulesetsCheck()

    inspector.get_org_rulesets.return_value = [{"name": "Standard Ruleset", "enforcement": "active"}]
    assert check.evaluate(inspector, "org", {}).status == CheckStatus.PASS

    inspector.get_org_rulesets.return_value = []
    assert check.evaluate(inspector, "org", {}).status == CheckStatus.FAIL


def test_org_secret_scanning_check() -> None:
    inspector = MagicMock()
    check = OrgSecretScanningPushProtectionCheck()

    # Pass
    inspector.get_org_info.return_value = {
        "security_and_analysis": {
            "secret_scanning_push_protection": {"status": "enabled"}
        }
    }
    assert check.evaluate(inspector, "org", {}).status == CheckStatus.PASS

    # Fail
    inspector.get_org_info.return_value = {}
    assert check.evaluate(inspector, "org", {}).status == CheckStatus.FAIL


def test_org_runner_groups_check() -> None:
    inspector = MagicMock()
    check = OrgRunnerGroupsCheck()

    # Pass - no runner groups
    inspector.get_org_runner_groups.return_value = []
    assert check.evaluate(inspector, "org", {}).status == CheckStatus.PASS

    # Warn - unrestricted visibility
    inspector.get_org_runner_groups.return_value = [{"name": "custom-group", "visibility": "all", "default": False}]
    assert check.evaluate(inspector, "org", {}).status == CheckStatus.WARN

    # Pass - restricted visibility
    inspector.get_org_runner_groups.return_value = [{"name": "custom-group", "visibility": "selected", "default": False}]
    assert check.evaluate(inspector, "org", {}).status == CheckStatus.PASS


def test_org_default_workflow_permissions_check() -> None:
    inspector = MagicMock()
    check = OrgDefaultWorkflowPermissionsCheck()

    inspector.get_org_actions_permissions.return_value = {"default_workflow_permissions": "read"}
    assert check.evaluate(inspector, "org", {}).status == CheckStatus.PASS

    inspector.get_org_actions_permissions.return_value = {"default_workflow_permissions": "write"}
    assert check.evaluate(inspector, "org", {}).status == CheckStatus.FAIL


# --- Repo Checks ---

def test_codeowners_check_variations() -> None:
    inspector = MagicMock()
    check = CodeownersCheck()

    # 1. Full catch-all rule -> PASS
    inspector.get_file_content.return_value = "* @fintech-core/maintainers\n/api/ @team-api"
    assert check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.PASS

    # 2. Specific rules without catch-all -> WARN
    inspector.get_file_content.return_value = "/api/ @team-api"
    assert check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.WARN

    # 3. Missing file -> FAIL
    inspector.get_file_content.return_value = None
    assert check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.FAIL


def test_branch_rulesets_check() -> None:
    inspector = MagicMock()
    check = BranchRulesetsCheck()
    thresholds = {"minimum_approvals": 2}

    # Fail - no protection or rulesets
    inspector.get_repo_rulesets.return_value = []
    inspector.get_branch_protection.return_value = None
    res_fail = check.evaluate(inspector, "org", "repo", "main", thresholds)
    assert res_fail.status == CheckStatus.FAIL

    # Warn - approvals below threshold
    inspector.get_branch_protection.return_value = {
        "required_pull_request_reviews": {"required_approving_review_count": 1}
    }
    res_warn = check.evaluate(inspector, "org", "repo", "main", thresholds)
    assert res_warn.status == CheckStatus.WARN

    # Pass - meets threshold
    inspector.get_branch_protection.return_value = {
        "required_pull_request_reviews": {"required_approving_review_count": 2}
    }
    res_pass = check.evaluate(inspector, "org", "repo", "main", thresholds)
    assert res_pass.status == CheckStatus.PASS


def test_workflow_sha_pinning_check() -> None:
    inspector = MagicMock()
    check = WorkflowShaPinningCheck()

    # No workflows -> SKIPPED
    inspector.list_workflows.return_value = []
    assert check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.SKIPPED

    # Unpinned action -> WARN
    inspector.list_workflows.return_value = [{"name": "CI", "path": ".github/workflows/ci.yml"}]
    inspector.get_file_content.return_value = "steps:\n  - uses: actions/checkout@v4"
    res_unpinned = check.evaluate(inspector, "org", "repo", "main", {})
    assert res_unpinned.status == CheckStatus.WARN

    # Pinned action -> PASS
    inspector.get_file_content.return_value = (
        "steps:\n  - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1"
    )
    assert check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.PASS


def test_workflow_concurrency_check() -> None:
    inspector = MagicMock()
    check = WorkflowConcurrencyGroupsCheck()

    inspector.list_workflows.return_value = [{"name": "Build", "path": ".github/workflows/build.yml"}]

    # Missing concurrency -> WARN
    inspector.get_file_content.return_value = "name: Build\non: push"
    assert check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.WARN

    # Has concurrency -> PASS
    inspector.get_file_content.return_value = "name: Build\nconcurrency:\n  group: main\n  cancel-in-progress: true"
    assert check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.PASS


def test_dependabot_config_check() -> None:
    inspector = MagicMock()
    check = DependabotConfigCheck()

    inspector.check_file_exists.return_value = True
    assert check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.PASS

    inspector.check_file_exists.return_value = False
    assert check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.FAIL


# --- Contributor Checks ---

def test_contributor_checks() -> None:
    inspector = MagicMock()

    # DevContainers
    dev_check = DevcontainersCheck()
    inspector.check_file_exists.return_value = True
    assert dev_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.PASS
    inspector.check_file_exists.return_value = False
    assert dev_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.WARN

    # Copilot Instructions
    copilot_check = CopilotInstructionsCheck()
    inspector.check_file_exists.return_value = True
    assert copilot_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.PASS
    inspector.check_file_exists.return_value = False
    assert copilot_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.WARN

    # Issue Templates
    issue_check = IssueTemplatesCheck()
    inspector.check_file_exists.return_value = True
    assert issue_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.PASS
    inspector.check_file_exists.return_value = False
    assert issue_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.WARN

    # PR Templates
    pr_check = PullRequestTemplatesCheck()
    inspector.check_file_exists.return_value = True
    assert pr_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.PASS
    inspector.check_file_exists.return_value = False
    assert pr_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.WARN

    # Pre-commit
    pc_check = PreCommitHooksCheck()
    inspector.check_file_exists.return_value = True
    assert pc_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.PASS
    inspector.check_file_exists.return_value = False
    assert pc_check.evaluate(inspector, "org", "repo", "main", {}).status == CheckStatus.WARN
