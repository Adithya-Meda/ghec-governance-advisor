"""Repo360 Platform Governance & Intelligence CLI Entrypoint."""

from __future__ import annotations

import warnings

# Suppress external SDK deprecation warnings for cleaner CLI output
warnings.filterwarnings("ignore", message=".*automatic function calling.*")
warnings.filterwarnings("ignore", category=UserWarning)

import argparse
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

from .ai import AIEngine
from .auth.github_app_auth import GitHubAppAuth
from .checks import (
    ALL_CONTRIBUTOR_CHECKS,
    ALL_ORG_CHECKS,
    ALL_REPO_CHECKS,
    CheckResult,
    CheckStatus,
)
from .collector.client import Repo360Client
from .collector.repo_inspector import RepoInspector
from .reporters.csv_reporter import CSVReporter
from .reporters.excel_reporter import ExcelReporter
from .reporters.html_reporter import HTMLReporter
from .validator import ConfigValidator, RepoTarget

try:
    import colorama

    colorama.init(autoreset=True)
except ImportError:
    pass


LOG_LEVEL_PASS = 25
logging.addLevelName(LOG_LEVEL_PASS, "PASS")


class ColoredFormatter(logging.Formatter):
    """Color-coded logging formatter with standardized 4-character top-level badges."""

    LEVEL_LABELS = {
        logging.DEBUG: "DEBG",
        logging.INFO: "INFO",
        LOG_LEVEL_PASS: "PASS",
        logging.WARNING: "WARN",
        logging.ERROR: "FAIL",
        logging.CRITICAL: "CRIT",
    }

    LEVEL_COLORS = {
        logging.DEBUG: "\033[90m",                   # Gray
        logging.INFO: "\033[96m",                    # Cyan [INFO]
        LOG_LEVEL_PASS: "\033[92m\033[1m",           # Bold Green [PASS]
        logging.WARNING: "\033[93m\033[1m",          # Bold Yellow [WARN]
        logging.ERROR: "\033[91m\033[1m",            # Bold Red [FAIL]
        logging.CRITICAL: "\033[95m\033[1m",         # Bold Magenta [CRIT]
    }
    RESET = "\033[0m"
    DIM = "\033[2m"

    def format(self, record: logging.LogRecord) -> str:
        label = self.LEVEL_LABELS.get(record.levelno, record.levelname[:4])
        color = self.LEVEL_COLORS.get(record.levelno, self.RESET)
        time_str = self.formatTime(record, "%d-%m-%Y %H:%M:%S")
        levelname = f"{color}[{label:^4}]{self.RESET}"
        timestamp = f"{self.DIM}[{time_str}]{self.RESET}"
        return f"{timestamp} {levelname} {record.getMessage()}"


def setup_logger() -> logging.Logger:
    """Configure color-coded console logger and silence third-party SDK noise."""
    # Silence third-party SDK internal deprecation notices (e.g. Google GenAI AFC warnings)
    logging.getLogger("google").setLevel(logging.ERROR)
    logging.getLogger("google.genai").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    app_logger = logging.getLogger("repo360")
    app_logger.setLevel(logging.INFO)
    app_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter())
    app_logger.addHandler(handler)
    return app_logger


logger = setup_logger()


def _log_finding(res: CheckResult) -> None:
    """Log individual check outcome under [INFO] with professional [EXISTS], [MISSING], or [REVIEW] badges."""
    dim = "\033[2m"
    bold = "\033[1m"
    green = "\033[92m"
    yellow = "\033[93m"
    red = "\033[91m"
    reset = "\033[0m"

    raw_target = res.repo_name or res.org_name or "Organization-Wide"
    target_clean = raw_target.strip("[]")
    target = f"[{target_clean}]"

    if res.status == CheckStatus.PASS:
        badge = f"{green}{bold}[EXISTS] {reset}"
        logger.info("%s %s %s", badge, target, res.check_name)
    elif res.status == CheckStatus.FAIL:
        badge = f"{red}{bold}[MISSING]{reset}"
        logger.info("%s %s %s %s- %s%s", badge, target, res.check_name, dim, res.current_state, reset)
    elif res.status == CheckStatus.WARN:
        badge = f"{yellow}{bold}[REVIEW] {reset}"
        logger.info("%s %s %s %s- %s%s", badge, target, res.check_name, dim, res.current_state, reset)
    elif res.status == CheckStatus.SKIPPED:
        badge = f"{dim}[SKIPPED]{reset}"
        logger.info("%s %s %s %s(Skipped - %s)%s", badge, target, res.check_name, dim, res.current_state, reset)


def _print_failure_banner(reason: str) -> None:
    """Print a standardized color-coded execution failure announcement."""
    R = "\033[91m"
    B = "\033[1m"
    X = "\033[0m"
    print(f"\n{R}{'=' * 76}{X}")
    print(f"{B}{R}   AUDIT FAILED / EXECUTION TERMINATED{X}")
    print(f"{R}{'=' * 76}{X}")
    for line in reason.strip().splitlines():
        print(f"   {line}")
    print(f"{R}{'=' * 76}{X}\n")


def print_terminal_scorecard(
    results: List[CheckResult],
    targets: List[RepoTarget],
    report_paths: Dict[str, str],
    ai_engine: Optional[AIEngine] = None,
    elapsed_seconds: float = 0.0,
) -> None:
    """Print an executive color-coded scorecard to stdout."""
    total = len(results)
    passed = sum(1 for r in results if r.status == CheckStatus.PASS)
    warned = sum(1 for r in results if r.status == CheckStatus.WARN)
    failed = sum(1 for r in results if r.status == CheckStatus.FAIL)
    health_score = (passed / total * 100) if total > 0 else 100.0

    G = "\033[92m"  # Green
    Y = "\033[93m"  # Yellow
    R = "\033[91m"  # Red
    C = "\033[96m"  # Cyan
    B = "\033[1m"   # Bold
    X = "\033[0m"   # Reset

    score_color = G if health_score >= 80 else (Y if health_score >= 60 else R)
    ai_status = (
        f"{G}ONLINE ({ai_engine.model_name}){X}"
        if (ai_engine and ai_engine.is_available())
        else f"{Y}OFFLINE (Deterministic Fallback){X}"
    )

    elapsed_str = (
        f"{int(elapsed_seconds // 60)}m {int(elapsed_seconds % 60)}s"
        if elapsed_seconds >= 60
        else f"{elapsed_seconds:.1f}s"
    )

    print(f"\n{C}{'=' * 76}{X}")
    print(f"{B}{C}   REPO360 PLATFORM GOVERNANCE & ENGINEERING SCORECARD{X}")
    print(f"{C}{'=' * 76}{X}")
    unique_orgs = sorted({target.org_name for target in targets})
    org_summary = (
        f"{len(unique_orgs)} ({', '.join(unique_orgs)})"
        if len(unique_orgs) <= 4
        else f"{len(unique_orgs)} organizations"
    )
    print(f"   {B}Organizations Audited:{X} {org_summary}")
    print(f"   {B}Repositories Audited :{X} {len(targets)}")
    print(f"   {B}Total Checks Run     :{X} {total}")
    print(f"   {B}Controls Present     :{X} {G}{passed:<4} EXISTS{X}")
    print(f"   {B}Controls Missing     :{X} {R}{failed:<4} MISSING{X}")
    print(f"   {B}Items Needing Review :{X} {Y}{warned:<4} REVIEW{X}")
    print(f"   {B}Overall Posture Score:{X} {score_color}{health_score:.1f}%{X}")
    print(f"   {B}AI Remediation Engine:{X} {ai_status}")
    if elapsed_seconds > 0:
        print(f"   {B}Execution Duration   :{X} {elapsed_str}")
    print(f"{C}{'-' * 76}{X}")
    print(f"   {B}Interactive Dashboard (HTML) :{X} {report_paths.get('html', '')}")
    print(f"   {B}Executive Workbook   (XLSX) :{X} {report_paths.get('xlsx', '')}")
    print(f"   {B}Flat SIEM Feed       (CSV)  :{X} {report_paths.get('csv', '')}")
    print(f"{C}{'=' * 76}{X}")
    repo_noun = "repository" if len(targets) == 1 else "repositories"
    org_noun = "organization" if len(unique_orgs) == 1 else "organizations"
    time_suffix = f" in {elapsed_str}" if elapsed_seconds > 0 else ""
    print(f"{G}{B}   [SUCCESS] Audit completed successfully across {len(targets)} {repo_noun} in {len(unique_orgs)} {org_noun}{time_suffix}.{X}\n")


def _log_repo_banner(
    idx: int,
    total: int,
    target: RepoTarget,
    tech_stack: Optional[Dict[str, Any]] = None,
) -> None:
    """Log an executive progress banner indicating the repository currently being evaluated."""
    pct = int((idx / total) * 100) if total > 0 else 100
    bar_length = 15
    filled_len = max(1, int(round(bar_length * idx / total))) if (idx > 0 and total > 0) else 0
    filled_len = min(filled_len, bar_length)

    if 0 < filled_len < bar_length:
        filled_str = "=" * (filled_len - 1) + ">"
    elif filled_len >= bar_length:
        filled_str = "=" * bar_length
    else:
        filled_str = ""

    unfilled_len = max(0, bar_length - len(filled_str))
    unfilled_str = "-" * unfilled_len

    stack_str = ""
    if tech_stack:
        langs = tech_stack.get("languages", [])
        if langs:
            stack_str = f" | Stack: {', '.join(langs[:3])}"

    C = "\033[96m"   # Cyan
    B = "\033[1m"    # Bold
    Y = "\033[93m"   # Yellow
    W = "\033[97m"   # Bright White
    D = "\033[2m"    # Dim
    X = "\033[0m"    # Reset

    pad = len(str(total))
    pct_badge = f"{B}{Y}[{pct:3d}% | {idx:>{pad}}/{total}]{X}"
    bar_badge = f"{C}[{B}{filled_str}{X}{D}{unfilled_str}{C}]{X}"
    repo_title = f"{B}{W}{target.org_name}/{target.repo_name}{X}"
    branch_info = f"{D}(branch: {target.default_branch}{stack_str}){X}"

    separator = f"{D}{'-' * 74}{X}"
    logger.info(separator)
    logger.info("%s %s Auditing Repository: %s %s", pct_badge, bar_badge, repo_title, branch_info)
    logger.info(separator)


def run_audit(
    inspector: RepoInspector,
    targets: List[RepoTarget],
    advisory_config: Dict[str, Any],
    ai_engine: Optional[AIEngine] = None,
) -> List[CheckResult]:
    """Execute all enabled checks across target organizations and repositories."""
    results: List[CheckResult] = []
    enabled_checks = advisory_config.get("enabled_checks", {})
    thresholds = advisory_config.get("policy_thresholds", {})

    # 1. Evaluate Organization-Level Checks (once per unique org)
    unique_orgs = sorted({target.org_name for target in targets})
    for org in unique_orgs:
        D = "\033[2m"
        X = "\033[0m"
        logger.info(f"{D}{'-' * 74}{X}")
        logger.info("\033[1;96mAuditing Organization:\033[0m \033[1;97m%s\033[0m (Organization-Wide Governance)", org)
        logger.info(f"{D}{'-' * 74}{X}")
        for check_cls in ALL_ORG_CHECKS:
            check_instance = check_cls()
            if check_instance.is_enabled(enabled_checks):
                try:
                    res = check_instance.evaluate(inspector, org, thresholds)
                    results.append(res)
                    _log_finding(res)
                except Exception as err:
                    logger.warning("Check %s failed on org %s: %s", check_instance.check_id, org, err)

    # 2. Evaluate Repository & Contributor Checks
    total_repos = len(targets)
    for idx, target in enumerate(targets, start=1):
        tech_stack: Dict[str, Any] = {}
        if ai_engine and ai_engine.is_available():
            tech_stack = inspector.detect_tech_stack(
                target.org_name, target.repo_name, target.default_branch
            )

        _log_repo_banner(idx, total_repos, target, tech_stack)

        # Evaluate Repo Admin Checks
        if "all" in target.target_personas or "repo_admin" in target.target_personas:
            for check_cls in ALL_REPO_CHECKS:
                check_instance = check_cls()
                if check_instance.is_enabled(enabled_checks):
                    try:
                        res = check_instance.evaluate(
                            inspector,
                            target.org_name,
                            target.repo_name,
                            target.default_branch,
                            thresholds,
                        )
                        if ai_engine and ai_engine.is_available():
                            ai_engine.enrich_remediation(res, tech_stack)
                        results.append(res)
                        _log_finding(res)
                    except Exception as err:
                        logger.warning(
                            "Check %s failed on %s/%s: %s",
                            check_instance.check_id,
                            target.org_name,
                            target.repo_name,
                            err,
                        )

        # Evaluate Contributor & Freshers Checks
        if "all" in target.target_personas or "contributor" in target.target_personas:
            for check_cls in ALL_CONTRIBUTOR_CHECKS:
                check_instance = check_cls()
                if check_instance.is_enabled(enabled_checks):
                    try:
                        res = check_instance.evaluate(
                            inspector,
                            target.org_name,
                            target.repo_name,
                            target.default_branch,
                            thresholds,
                        )
                        if ai_engine and ai_engine.is_available():
                            ai_engine.enrich_remediation(res, tech_stack)
                        results.append(res)
                        _log_finding(res)
                    except Exception as err:
                        logger.warning(
                            "Check %s failed on %s/%s: %s",
                            check_instance.check_id,
                            target.org_name,
                            target.repo_name,
                            err,
                        )

    return results


def _resolve_config_path(custom_path: str, default_relative: str) -> Optional[str]:
    """Resolve configuration file path, checking explicit input, CWD, then package bundle."""
    if custom_path:
        if os.path.isfile(custom_path):
            return custom_path
        raise FileNotFoundError(f"Specified configuration file not found: {custom_path}")

    # Check current working directory
    cwd_path = os.path.join(os.getcwd(), default_relative)
    if os.path.isfile(cwd_path):
        return cwd_path

    # Check bundled package directory
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled_path = os.path.join(pkg_root, default_relative)
    if os.path.isfile(bundled_path):
        return bundled_path

    return None


def _print_root_help() -> int:
    """Print the top-level Repo360 CLI commands and overview."""
    print("""Repo360 - 360-Degree Platform Governance, Compliance & Engineering Intelligence

Usage:
  repo360 <command> [options]

Commands:
  audit       Run security, platform governance, and CI/CD audit across repositories
  setup       Launch 1-click GitHub App setup wizard & credential configuration
  activity    Analyze contributor cadence, active days, seat allocation, and commit/PR metrics
  runners     Inspect Actions self-hosted runner fleet usage, compute hours, and queue wait times
  upgrade     Upgrade Repo360 CLI to the latest release or branch directly from GitHub

Options:
  -h, --help  Show this help message or help for a specific command

Run 'repo360 <command> --help' for details on a specific command (e.g. 'repo360 activity -h').
""")
    return 0


def main() -> int:
    """CLI entrypoint with strict subcommand routing.

    Running bare 'repo360' prints available commands and does NOT invoke any operation.
    """
    import sys

    # 1. Bare invocation: 'repo360' with no arguments displays help
    if len(sys.argv) <= 1:
        return _print_root_help()

    subcmd = sys.argv[1].lower()

    # 2. Root help flags
    if subcmd in ("-h", "--help"):
        return _print_root_help()

    # 3. Route recognized subcommands
    if subcmd == "audit":
        sys.argv.pop(1)
        try:
            return _run_cli()
        except KeyboardInterrupt:
            logger.warning("\nExecution cancelled by user (Ctrl+C). Exiting...")
            _print_failure_banner("Audit cancelled by user (Ctrl+C). No final reports generated.")
            return 130

    if subcmd in ("setup", "install-app"):
        sys.argv.pop(1)
        from .setup_app import main as setup_main
        return setup_main()

    if subcmd in ("activity", "users", "user-activity"):
        sys.argv.pop(1)
        from .activity.cli import run_activity_cli
        try:
            return run_activity_cli()
        except KeyboardInterrupt:
            logger.warning("\nExecution cancelled by user (Ctrl+C). Exiting...")
            return 130

    if subcmd in ("runners", "metrics", "runner-metrics"):
        sys.argv.pop(1)
        from .runners.cli import run_runners_cli
        try:
            return run_runners_cli()
        except KeyboardInterrupt:
            logger.warning("\nExecution cancelled by user (Ctrl+C). Exiting...")
            return 130

    if subcmd in ("upgrade", "update"):
        sys.argv.pop(1)
        from .upgrade import run_upgrade_cli
        try:
            return run_upgrade_cli()
        except KeyboardInterrupt:
            logger.warning("\nUpgrade cancelled by user (Ctrl+C). Exiting...")
            return 130

    # 4. Unknown subcommand or misplaced option
    print(f"Error: Unknown command '{sys.argv[1]}'. Run 'repo360 --help' for available commands.\n")
    return 1


def run_audit_cli() -> int:
    """Dedicated entrypoint for repo360-audit standalone shortcut."""
    try:
        return _run_cli()
    except KeyboardInterrupt:
        logger.warning("\nExecution cancelled by user (Ctrl+C). Exiting...")
        _print_failure_banner("Audit cancelled by user (Ctrl+C). No final reports generated.")
        return 130


def run_activity_cli() -> int:
    """Dedicated entrypoint for repo360 activity standalone execution."""
    from .activity.cli import run_activity_cli as _run_act
    try:
        return _run_act()
    except KeyboardInterrupt:
        logger.warning("\nExecution cancelled by user (Ctrl+C). Exiting...")
        return 130


def run_runners_cli() -> int:
    """Dedicated entrypoint for repo360 runners standalone execution."""
    from .runners.cli import run_runners_cli as _run_run
    try:
        return _run_run()
    except KeyboardInterrupt:
        logger.warning("\nExecution cancelled by user (Ctrl+C). Exiting...")
        return 130


def run_upgrade_cli() -> int:
    """Dedicated entrypoint for repo360 upgrade standalone execution."""
    from .upgrade import run_upgrade_cli as _run_up
    try:
        return _run_up()
    except KeyboardInterrupt:
        logger.warning("\nExecution cancelled by user (Ctrl+C). Exiting...")
        return 130


def _run_cli() -> int:
    """CLI orchestrator."""
    start_time = time.time()
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        prog="repo360 audit",
        description="Repo360 - 360-Degree Platform Governance, Compliance & Engineering Intelligence"
    )
    parser.add_argument(
        "--app-config",
        default="",
        help="Optional path to custom app runtime configuration JSON (defaults to built-in enterprise settings).",
    )
    parser.add_argument(
        "--advisory-config",
        default="",
        help="Optional path to custom policy JSON (defaults to all 14 enterprise best practices enabled).",
    )
    parser.add_argument(
        "--inventory",
        default="",
        help="Optional path to custom repository inventory CSV.",
    )
    parser.add_argument(
        "--auto-discover",
        action="store_true",
        help="Force auto-discovery of all repositories accessible to the GitHub App.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directory where output reports will be saved (defaults to ./repo360-output).",
    )
    parser.add_argument(
        "--org",
        default="",
        help="Optional comma-separated list of organizations to audit (e.g. 'org1,org2'). If omitted, all organizations with GitHub App installed are audited.",
    )
    parser.add_argument(
        "--mock-mode",
        action="store_true",
        help="Run in offline mock mode using simulated data for verification.",
    )
    parser.add_argument(
        "--require-ai",
        action="store_true",
        help="Strict mode: Abort audit immediately if AI Remediation Engine cannot authenticate.",
    )

    args = parser.parse_args()

    # Resolve config paths (explicit CLI > CWD > bundled package defaults > built-in defaults)
    try:
        app_cfg_path = _resolve_config_path(args.app_config, "config/config.json")
        advisory_cfg_path = _resolve_config_path(args.advisory_config, "config/advisory.json")
        inventory_path = _resolve_config_path(args.inventory, "") if args.inventory else None

        app_config = (
            ConfigValidator.load_and_validate_json(app_cfg_path)
            if app_cfg_path
            else ConfigValidator.get_default_app_config()
        )
        advisory_config = (
            ConfigValidator.load_and_validate_json(advisory_cfg_path, is_advisory=True)
            if advisory_cfg_path
            else ConfigValidator.get_default_advisory_config()
        )
        targets = (
            []
            if args.auto_discover or not inventory_path
            else ConfigValidator.load_and_validate_repos_csv(inventory_path, optional=True)
        )
    except Exception as err:
        logger.error("Configuration validation failed: %s", err)
        _print_failure_banner(f"Configuration validation failed: {err}")
        return 1

    # Determine output directory
    output_dir = args.output_dir or app_config.get("reporting", {}).get("output_directory", "./repo360-output")
    os.makedirs(output_dir, exist_ok=True)

    # Load credentials with priority: Environment Variables > Local .env > User Config (~/.repo360/config.json)
    from .credentials import resolve_runtime_credentials
    creds = resolve_runtime_credentials()

    # Initialize AI Engine (Multi-provider: Gemini, OpenAI, Anthropic)
    provider = creds["llm_provider"]
    ai_model = creds["llm_model"]
    llm_api_key = creds["llm_api_key"]
    llm_enabled = creds["llm_enabled"]
    key_hint = f"{provider.upper()}_API_KEY"

    ai_engine = AIEngine(
        api_key=llm_api_key,
        model_name=ai_model,
        provider=provider,
        enabled=llm_enabled,
    )

    if not args.mock_mode and ai_engine.enabled:
        logger.info(
            "Performing pre-flight healthcheck for AI Remediation Engine (%s: %s)...",
            ai_engine.provider.upper(),
            ai_engine.model_name,
        )
        is_ok, reason = ai_engine.verify_connection()
        if is_ok:
            logger.info(
                "AI Remediation Engine: ONLINE (%s: %s - Authenticated)",
                ai_engine.provider.upper(),
                ai_engine.model_name,
            )
        else:
            logger.warning(
                "AI Remediation Engine: OFFLINE (%s). "
                "Audit will proceed using deterministic policy rules. "
                "To enable AI-tailored remediations, run 'repo360 setup' or configure %s.",
                reason,
                key_hint,
            )
            if args.require_ai:
                logger.error("Execution halted: --require-ai was specified but AI engine is offline (%s).", reason)
                _print_failure_banner(f"--require-ai was specified but AI Remediation Engine is offline ({reason}).")
                return 1
    elif not ai_engine.enabled:
        offline_reason = ai_engine.init_error or f"{key_hint} not configured"
        logger.warning(
            "AI Remediation Engine: OFFLINE (%s). "
            "Remediations will use deterministic policy defaults. "
            "To enable AI-tailored remediations, run 'repo360 setup' or configure %s.",
            offline_reason,
            key_hint,
        )
        if args.require_ai:
            logger.error("Execution halted: --require-ai was specified but %s is not configured.", key_hint)
            _print_failure_banner(f"--require-ai was specified but {key_hint} is not configured.")
            return 1

    results: List[CheckResult] = []

    if args.mock_mode:
        logger.info("Running in offline mock mode (simulating Repo360 audit results)...")
        from .mock_generator import create_mock_results
        if not targets:
            mock_orgs = (
                [o.strip() for o in args.org.split(",") if o.strip()]
                if args.org
                else ["fintech-core"]
            )
            targets = []
            for org in mock_orgs:
                targets.extend([
                    RepoTarget(org_name=org, repo_name="payment-gateway", target_personas={"all"}),
                    RepoTarget(org_name=org, repo_name="auth-service", target_personas={"all"}),
                ])
        results = create_mock_results(targets)

        # 1. Organization-Wide Governance findings
        D = "\033[2m"
        X = "\033[0m"
        unique_mock_orgs = sorted({target.org_name for target in targets})
        for org in unique_mock_orgs:
            logger.info(f"{D}{'-' * 74}{X}")
            logger.info("\033[1;96mAuditing Organization:\033[0m \033[1;97m%s\033[0m (Organization-Wide Governance)", org)
            logger.info(f"{D}{'-' * 74}{X}")
            for res in results:
                if res.org_name == org and res.repo_name == "[Organization-Wide]":
                    _log_finding(res)

        # 2. Repository findings with progress banner
        mock_stacks = [
            {"languages": ["Python", "Docker"]},
            {"languages": ["TypeScript", "Node.js"]},
        ]
        total_targets = len(targets)
        for idx, target in enumerate(targets, start=1):
            stack = mock_stacks[(idx - 1) % len(mock_stacks)]
            _log_repo_banner(idx, total_targets, target, stack)
            for res in results:
                if res.org_name == target.org_name and res.repo_name == target.repo_name:
                    _log_finding(res)
    else:
        # Load credentials resolved across Environment / Local .env / User Config
        app_id = creds["app_id"]
        installation_id = creds["installation_id"]
        private_key = creds["private_key"]
        api_base_url = creds["api_base_url"] or app_config.get("github", {}).get("api_base_url", "https://api.github.com")

        if not app_id or not private_key:
            logger.error(
                "Missing required GitHub App credentials. Run 'repo360 setup' to automatically register "
                "your GitHub App and download credentials, or set REPO360_APP_ID and REPO360_APP_PRIVATE_KEY."
            )
            _print_failure_banner(
                "Missing required GitHub App credentials.\n"
                "  Action: Run 'repo360 setup' to automatically register your GitHub App and download credentials,\n"
                "  or configure REPO360_APP_ID and REPO360_APP_PRIVATE_KEY."
            )
            return 1

        try:
            auth = GitHubAppAuth(
                app_id=app_id,
                installation_id=installation_id,
                private_key=private_key,
                api_base_url=api_base_url,
            )

            # Discover all installations for the GitHub App
            all_installations = auth.discover_installations()
            if not all_installations:
                logger.error(
                    "No active installations found for GitHub App ID %s. "
                    "Ensure an Organization Owner has installed the App on your GitHub organization.",
                    app_id,
                )
                _print_failure_banner(
                    f"No active installations found for GitHub App ID {app_id}.\n"
                    "  Action: Ensure an Organization Owner has installed the App on your GitHub organization."
                )
                return 1

            # Filter installations if --org was specified
            requested_orgs_raw = getattr(args, "org", "").strip()
            if requested_orgs_raw:
                filter_orgs = {o.strip().lower() for o in requested_orgs_raw.split(",") if o.strip()}
                active_installations = [
                    inst for inst in all_installations
                    if inst.get("account", {}).get("login", "").lower() in filter_orgs
                ]
                found_orgs = {
                    inst.get("account", {}).get("login", "").lower() for inst in active_installations
                }
                missing_orgs = filter_orgs - found_orgs
                if missing_orgs:
                    logger.warning(
                        "The following requested organizations were not found among GitHub App installations: %s",
                        ", ".join(sorted(missing_orgs)),
                    )
                if not active_installations:
                    logger.error("None of the specified organizations (%s) have the GitHub App installed.", requested_orgs_raw)
                    _print_failure_banner(
                        f"None of the specified organizations ({requested_orgs_raw}) have the GitHub App installed.\n"
                        "  Action: Install the GitHub App in the specified organization(s) or adjust the --org parameter."
                    )
                    return 1
            else:
                active_installations = all_installations

            # Set active installation if not explicitly configured
            if not auth.installation_id and active_installations:
                auth.set_installation_id(active_installations[0]["id"])

            client = Repo360Client(
                auth=auth,
                timeout_seconds=app_config.get("github", {}).get("timeout_seconds", 30),
                max_retries=app_config.get("github", {}).get("max_retries", 3),
            )
            inspector = RepoInspector(client=client)

            if not targets:
                logger.info(
                    "Discovering accessible repositories across %d GitHub organization(s)...",
                    len(active_installations),
                )
                for inst in active_installations:
                    org_login = inst.get("account", {}).get("login", "")
                    inst_id = inst.get("id")
                    if not inst_id:
                        continue

                    repo_sel = inst.get("repository_selection", "all")
                    if repo_sel != "all":
                        logger.warning(
                            "GitHub App access on '%s' is set to 'selected' repositories. "
                            "To automatically cover all current and future repositories, change to 'All repositories' in Org Settings.",
                            org_login,
                        )

                    discovered = inspector.list_installation_repositories(installation_id=inst_id)
                    for r in discovered:
                        owner = r.get("owner", {}).get("login", "") or org_login
                        name = r.get("name", "")
                        default_branch = r.get("default_branch", "main") or "main"
                        if owner and name:
                            targets.append(
                                RepoTarget(
                                    org_name=owner,
                                    repo_name=name,
                                    target_personas={"all"},
                                    default_branch=default_branch,
                                )
                            )

                unique_discovered_orgs = sorted({t.org_name for t in targets})
                repo_noun = "repository" if len(targets) == 1 else "repositories"
                logger.info(
                    "Auto-discovered %d accessible %s across %d organization(s): %s.",
                    len(targets),
                    repo_noun,
                    len(unique_discovered_orgs),
                    ", ".join(unique_discovered_orgs),
                )

            if not targets:
                logger.warning("No repositories found to audit. Ensure the GitHub App is installed on repositories.")
                return 0

            results = run_audit(inspector, targets, advisory_config, ai_engine=ai_engine)
        except Exception as err:
            logger.error("Execution failed: %s", err)
            _print_failure_banner(f"Audit execution error: {err}")
            return 1

    # Generate AI Executive Briefing if available
    executive_summary = ""
    if not args.mock_mode and ai_engine.is_available() and targets:
        logger.info("Synthesizing Executive Risk & Governance Narrative via AI...")
        unique_orgs = sorted({t.org_name for t in targets})
        executive_summary = ai_engine.generate_executive_summary(results, ", ".join(unique_orgs))
    elif args.mock_mode:
        executive_summary = (
            "Simulated Executive Risk & Governance Briefing for offline audit verification."
        )

    # Generate Reports
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    prefix = app_config.get("reporting", {}).get("report_prefix", "repo360_audit")

    xlsx_path = os.path.join(output_dir, f"{prefix}_{timestamp}.xlsx")
    csv_path = os.path.join(output_dir, f"{prefix}_{timestamp}.csv")
    html_path = os.path.join(output_dir, f"{prefix}_{timestamp}.html")

    active_model = ai_engine.model_name if (ai_engine and ai_engine.is_available()) else ""

    logger.info("Generating Excel Report: %s", xlsx_path)
    ExcelReporter().generate(results, xlsx_path, executive_summary=executive_summary, model_name=active_model)

    logger.info("Generating CSV Report: %s", csv_path)
    CSVReporter().generate(results, csv_path, executive_summary=executive_summary, model_name=active_model)

    logger.info("Generating Interactive HTML Report: %s", html_path)
    HTMLReporter().generate(results, html_path, executive_summary=executive_summary, model_name=active_model)

    # Render Color-Coded Terminal Scorecard
    report_paths = {
        "html": os.path.abspath(html_path),
        "xlsx": os.path.abspath(xlsx_path),
        "csv": os.path.abspath(csv_path),
    }
    elapsed = time.time() - start_time
    print_terminal_scorecard(results, targets, report_paths, ai_engine=ai_engine, elapsed_seconds=elapsed)

    return 0


if __name__ == "__main__":
    sys.exit(main())
