"""GHEC Governance & Advisory Agent CLI Entrypoint."""

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
from typing import Any, Dict, List, Optional, Set

from .ai import AIEngine
from .auth.github_app_auth import GitHubAppAuth
from .checks import (
    ALL_CONTRIBUTOR_CHECKS,
    ALL_ORG_CHECKS,
    ALL_REPO_CHECKS,
    CheckResult,
    CheckSeverity,
    CheckStatus,
    Persona,
)
from .collector.client import GHECClient
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
        time_str = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        levelname = f"{color}[{label:^4}]{self.RESET}"
        timestamp = f"{self.DIM}[{time_str}]{self.RESET}"
        return f"{timestamp} {levelname} {record.getMessage()}"


def setup_logger() -> logging.Logger:
    """Configure color-coded console logger and silence third-party SDK noise."""
    # Silence third-party SDK internal deprecation notices (e.g. Google GenAI AFC warnings)
    logging.getLogger("google").setLevel(logging.ERROR)
    logging.getLogger("google.genai").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    app_logger = logging.getLogger("advisor-agent")
    app_logger.setLevel(logging.INFO)
    app_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter())
    app_logger.addHandler(handler)
    return app_logger


logger = setup_logger()


def _log_finding(res: CheckResult) -> None:
    """Log individual check outcome with top-level PASS, WARN, or FAIL label."""
    dim = "\033[2m"
    reset = "\033[0m"
    if res.repo_name:
        target = f"[{res.repo_name}]"
    elif res.org_name.startswith("[") and res.org_name.endswith("]"):
        target = res.org_name
    else:
        target = f"[{res.org_name}]"

    if res.status == CheckStatus.FAIL:
        logger.error("%s %s %s- %s%s", target, res.check_name, dim, res.current_state, reset)
    elif res.status == CheckStatus.WARN:
        logger.warning("%s %s %s- %s%s", target, res.check_name, dim, res.current_state, reset)
    elif res.status == CheckStatus.PASS:
        logger.log(LOG_LEVEL_PASS, "%s %s", target, res.check_name)
    elif res.status == CheckStatus.SKIPPED:
        logger.info("%s %s %s(Skipped - %s)%s", target, res.check_name, dim, res.current_state, reset)


def print_terminal_scorecard(
    results: List[CheckResult],
    targets: List[RepoTarget],
    report_paths: Dict[str, str],
    ai_engine: Optional[AIEngine] = None,
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
    D = "\033[2m"   # Dim
    X = "\033[0m"   # Reset

    score_color = G if health_score >= 80 else (Y if health_score >= 60 else R)
    ai_status = (
        f"{G}ONLINE ({ai_engine.model_name}){X}"
        if (ai_engine and ai_engine.is_available())
        else f"{Y}OFFLINE (Deterministic Fallback){X}"
    )

    print(f"\n{C}{'=' * 76}{X}")
    print(f"{B}{C}   GITHUB ENTERPRISE PLATFORM GOVERNANCE & ENABLEMENT SCORECARD{X}")
    print(f"{C}{'=' * 76}{X}")
    print(f"   {B}Repositories Audited :{X} {len(targets)}")
    print(f"   {B}Total Checks Run     :{X} {total}")
    print(f"   {B}Passed Checks (PASS) :{X} {G}{passed:<4} PASS{X}")
    print(f"   {B}Warning Risks (WARN) :{X} {Y}{warned:<4} WARN{X}")
    print(f"   {B}Failed Checks (FAIL) :{X} {R}{failed:<4} FAIL{X}")
    print(f"   {B}Overall Health Score :{X} {score_color}{health_score:.1f}%{X}")
    print(f"   {B}AI Remediation Engine:{X} {ai_status}")
    print(f"{C}{'-' * 76}{X}")
    print(f"   {B}Interactive Dashboard (HTML) :{X} {report_paths.get('html', '')}")
    print(f"   {B}Executive Workbook   (XLSX) :{X} {report_paths.get('xlsx', '')}")
    print(f"   {B}Flat SIEM Feed       (CSV)  :{X} {report_paths.get('csv', '')}")
    print(f"{C}{'=' * 76}{X}\n")


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
        logger.info("\033[1;96mAuditing Organization:\033[0m \033[1;97m%s\033[0m", org)
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
    for target in targets:
        logger.info(
            "\033[1;96mAuditing Repository:\033[0m \033[1;97m%s/%s\033[0m \033[2m(branch: %s)\033[0m",
            target.org_name,
            target.repo_name,
            target.default_branch,
        )
        tech_stack: Dict[str, Any] = {}
        if ai_engine and ai_engine.is_available():
            tech_stack = inspector.detect_tech_stack(
                target.org_name, target.repo_name, target.default_branch
            )

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


def main() -> int:
    """CLI entrypoint with clean Ctrl+C interruption handling."""
    try:
        return _run_cli()
    except KeyboardInterrupt:
        logger.warning("\nExecution cancelled by user (Ctrl+C). Exiting...")
        return 130


def _run_cli() -> int:
    """CLI orchestrator."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="GHEC Platform Governance & Enablement Advisory Agent"
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
        help="Optional path to repository inventory CSV (defaults to auto-discovering all organization repositories).",
    )
    parser.add_argument(
        "--auto-discover",
        action="store_true",
        help="Force auto-discovery of all repositories accessible to the GitHub App (ignores repos.csv).",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directory where output reports will be saved (defaults to ./output).",
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
        inventory_path = _resolve_config_path(args.inventory, "config/repos.csv")

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
        return 1

    # Determine output directory
    output_dir = args.output_dir or app_config.get("reporting", {}).get("output_directory", "./output")
    os.makedirs(output_dir, exist_ok=True)

    # Load credentials with priority: Environment Variables > Local .env > User Config (~/.ghec-advisor/config.json)
    from .credentials import resolve_runtime_credentials, save_user_credentials
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
                "To enable AI-tailored remediations, run 'ghec-setup' or configure %s.",
                reason,
                key_hint,
            )
            if args.require_ai:
                logger.error("Execution halted: --require-ai was specified but AI engine is offline (%s).", reason)
                return 1
    elif not ai_engine.enabled:
        logger.warning(
            "AI Remediation Engine: OFFLINE (%s not configured). "
            "Remediations will use deterministic policy defaults. "
            "To enable AI-tailored remediations, run 'ghec-setup' or configure %s.",
            key_hint,
            key_hint,
        )
        if args.require_ai:
            logger.error("Execution halted: --require-ai was specified but %s is not configured.", key_hint)
            return 1

    results: List[CheckResult] = []

    if args.mock_mode:
        logger.info("Running in offline mock mode (simulating GHEC audit results)...")
        from .mock_generator import create_mock_results
        if not targets:
            targets = [
                RepoTarget(org_name="fintech-core", repo_name="payment-gateway", target_personas={"all"}),
                RepoTarget(org_name="fintech-core", repo_name="auth-service", target_personas={"all"}),
            ]
        results = create_mock_results(targets)
        for res in results:
            _log_finding(res)
    else:
        # Load credentials resolved across Environment / Local .env / User Config
        app_id = creds["app_id"]
        installation_id = creds["installation_id"]
        private_key = creds["private_key"]
        api_base_url = creds["api_base_url"] or app_config.get("github", {}).get("api_base_url", "https://api.github.com")

        if not app_id or not private_key:
            logger.error(
                "Missing required GitHub App credentials. Run 'ghec-setup' to automatically register "
                "your GitHub App and download credentials, or set GHEC_APP_ID and GHEC_APP_PRIVATE_KEY."
            )
            return 1

        try:
            auth = GitHubAppAuth(
                app_id=app_id,
                installation_id=installation_id,
                private_key=private_key,
                api_base_url=api_base_url,
            )

            # Auto-discover installation ID if omitted
            if not auth.installation_id:
                logger.info("GHEC_APP_INSTALLATION_ID not configured. Auto-discovering installations via GitHub App JWT...")
                installations = auth.discover_installations()
                if not installations:
                    logger.error(
                        "No active installations found for GitHub App ID %s. "
                        "Ensure an Organization Owner has installed the App on your GitHub organization.",
                        app_id,
                    )
                    return 1

                # Select installation matching target org if known, otherwise primary
                selected = installations[0]
                if targets:
                    target_org = targets[0].org_name.lower()
                    matched = [
                        i for i in installations
                        if i.get("account", {}).get("login", "").lower() == target_org
                    ]
                    if matched:
                        selected = matched[0]

                auth.set_installation_id(selected["id"])
                org_login = selected.get("account", {}).get("login", "organization")
                logger.info("Auto-discovered Installation ID %s for organization '%s'.", auth.installation_id, org_login)

                # Warn if app is not configured for automatic coverage across all repositories
                repo_sel = selected.get("repository_selection", "all")
                if repo_sel != "all":
                    logger.warning(
                        "GitHub App access on '%s' is set to 'selected' repositories. "
                        "To automatically cover all current and future repositories, change to 'All repositories' in Org Settings.",
                        org_login,
                    )

                # Persist discovered installation ID to ~/.ghec-advisor/config.json so subsequent runs are instant
                save_user_credentials(
                    app_id=app_id,
                    private_key_path=private_key,
                    installation_id=auth.installation_id,
                    api_base_url=api_base_url,
                    llm_provider=provider,
                    llm_model=ai_model,
                    llm_api_key=llm_api_key,
                    llm_enabled=llm_enabled,
                )
                env_path = os.path.abspath(".env")
                if os.path.isfile(env_path):
                    ConfigValidator.update_env_file("GHEC_APP_INSTALLATION_ID", str(auth.installation_id), env_path)

            client = GHECClient(
                auth=auth,
                timeout_seconds=app_config.get("github", {}).get("timeout_seconds", 30),
                max_retries=app_config.get("github", {}).get("max_retries", 3),
            )
            inspector = RepoInspector(client=client)

            if not targets:
                logger.info("No repositories specified in repos.csv. Auto-discovering all accessible repositories via GitHub App...")
                discovered = inspector.list_installation_repositories()
                for r in discovered:
                    owner = r.get("owner", {}).get("login", "")
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
                repo_noun = "repository" if len(targets) == 1 else "repositories"
                logger.info("Auto-discovered %d accessible %s.", len(targets), repo_noun)

            if not targets:
                logger.warning("No repositories found to audit. Ensure the GitHub App is installed on repositories.")
                return 0

            results = run_audit(inspector, targets, advisory_config, ai_engine=ai_engine)
        except Exception as err:
            logger.error("Execution failed: %s", err)
            return 1

    # Generate AI Executive Briefing if available
    executive_summary = ""
    if not args.mock_mode and ai_engine.is_available() and targets:
        logger.info("Synthesizing Executive Risk & Governance Narrative via AI...")
        executive_summary = ai_engine.generate_executive_summary(results, targets[0].org_name)
    elif args.mock_mode:
        executive_summary = (
            "Simulated Executive Risk & Governance Briefing for offline audit verification."
        )

    # Generate Reports
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    prefix = app_config.get("reporting", {}).get("report_prefix", "ghec_governance_audit")

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
    print_terminal_scorecard(results, targets, report_paths, ai_engine=ai_engine)

    return 0


if __name__ == "__main__":
    sys.exit(main())
