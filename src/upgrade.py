"""Production-grade upgrade utility for the Repo360 CLI suite."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple
import requests

from .credentials import get_credentials_path, get_secrets_dir

logger = logging.getLogger("repo360.upgrade")

DEFAULT_REPO_URL = "https://github.com/Adithya-Meda/repo360.git"
GITHUB_API_COMMITS = "https://api.github.com/repos/Adithya-Meda/repo360/commits/main"


def detect_installer() -> Tuple[str, List[str]]:
    """Detect whether Repo360 is running within pipx or standard pip/virtualenv.

    Returns:
        Tuple of (installer_name, base_command_tokens).
    """
    prefix = sys.prefix.lower()
    has_pipx = shutil.which("pipx") is not None

    if "pipx" in prefix and has_pipx:
        return "pipx", ["pipx", "install", "--force"]

    # Fallback to python -m pip using the current active interpreter
    return "pip", [sys.executable, "-m", "pip", "install", "--upgrade"]


def build_upgrade_command(
    repo_url: str = DEFAULT_REPO_URL,
    installer_override: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """Construct the exact shell command to install/upgrade Repo360 to the latest version.

    Args:
        repo_url: Git repository clone URL.
        installer_override: Force 'pipx' or 'pip'.

    Returns:
        Tuple of (installer_type, command_list).
    """
    installer, base_cmd = detect_installer()
    if installer_override:
        if installer_override.lower() == "pipx":
            installer, base_cmd = "pipx", ["pipx", "install", "--force"]
        else:
            installer, base_cmd = "pip", [sys.executable, "-m", "pip", "install", "--upgrade"]

    target_spec = f"git+{repo_url}"
    cmd = list(base_cmd)
    cmd.append(target_spec)
    return installer, cmd


def check_remote_status(repo_url: str = DEFAULT_REPO_URL) -> Tuple[bool, str]:
    """Check remote GitHub repository for the latest commit/release on main.

    Returns:
        Tuple of (success_bool, message_or_commit_info).
    """
    try:
        clean_url = repo_url.rstrip("/")
        if clean_url.endswith(".git"):
            clean_url = clean_url[:-4]
        parts = clean_url.split("/")
        if len(parts) >= 2:
            owner, repo_name = parts[-2], parts[-1]
            api_url = f"https://api.github.com/repos/{owner}/{repo_name}/commits/main"
            resp = requests.get(
                api_url,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Repo360-Upgrade/1.0"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                sha = data.get("sha", "")[:8]
                date = data.get("commit", {}).get("committer", {}).get("date", "")
                msg = data.get("commit", {}).get("message", "").splitlines()[0]
                return True, f"Latest version on main: {sha} ({date}) - '{msg}'"
    except Exception as exc:
        return False, f"Could not query remote GitHub repository: {exc}"

    return False, "Could not query remote GitHub repository."


def execute_upgrade(cmd: List[str], dry_run: bool = False) -> int:
    """Execute the upgrade process via subprocess."""
    cmd_str = " ".join(cmd)
    if dry_run:
        print(f"\n\033[96m[DRY-RUN]\033[0m Would execute upgrade command:\n  {cmd_str}\n")
        return 0

    print(f"\n\033[96m[INFO]\033[0m Executing upgrade:\n  {cmd_str}\n")
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except Exception as exc:
        print(f"\n\033[91m[FAIL]\033[0m Upgrade command execution failed: {exc}\n")
        return 1


def verify_local_state() -> None:
    """Verify that user credentials and configurations remain intact post-upgrade."""
    config_file = Path(get_credentials_path())
    secrets_dir = Path(get_secrets_dir())

    config_ok = config_file.is_file()
    pem_count = len(list(secrets_dir.glob("*.pem"))) if secrets_dir.is_dir() else 0

    print("\033[96m[VERIFY]\033[0m Verifying configuration integrity:")
    if config_ok:
        print(f"  Configuration file : \033[92m[OK]\033[0m {config_file}")
    else:
        print(f"  Configuration file : \033[93m[NOTICE]\033[0m Not configured yet (run 'repo360 setup')")

    if pem_count > 0:
        print(f"  GitHub App keys    : \033[92m[OK]\033[0m {pem_count} private key(s) detected in {secrets_dir}")
    else:
        print(f"  GitHub App keys    : \033[93m[NOTICE]\033[0m No stored private keys found in {secrets_dir}")


def run_upgrade_cli(argv: Optional[List[str]] = None) -> int:
    """CLI orchestrator for 'repo360 upgrade' subcommand."""
    parser = argparse.ArgumentParser(
        prog="repo360 upgrade",
        description="Upgrade Repo360 CLI to the latest version directly from GitHub.",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_REPO_URL,
        help=f"Custom Git repository source URL (default: {DEFAULT_REPO_URL}).",
    )
    parser.add_argument(
        "--pip",
        action="store_true",
        help="Force using standard 'python -m pip' instead of auto-detecting pipx.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check remote repository status for updates without installing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned upgrade command without executing it.",
    )

    args = parser.parse_args(argv)

    installer_override = "pip" if args.pip else None

    # Handle --check
    if args.check:
        print(f"\033[96m[INFO]\033[0m Checking {args.source} for updates...")
        ok, msg = check_remote_status(args.source)
        if ok:
            print(f"\033[92m[PASS]\033[0m {msg}")
        else:
            print(f"\033[93m[WARN]\033[0m {msg}")
        installer, cmd = build_upgrade_command(args.source, installer_override)
        print(f"Run 'repo360 upgrade' to install via {installer}: {' '.join(cmd)}\n")
        return 0

    installer, cmd = build_upgrade_command(args.source, installer_override)
    print(f"\033[96m[INFO]\033[0m Detected package manager: \033[1m{installer}\033[0m")
    print(f"\033[96m[INFO]\033[0m Upgrading Repo360 to latest version from {args.source}...")

    exit_code = execute_upgrade(cmd, dry_run=args.dry_run)
    if exit_code == 0 and not args.dry_run:
        print("\n\033[92m[SUCCESS]\033[0m Repo360 upgrade completed successfully.")
        verify_local_state()
        print("\nRun 'repo360 --help' to explore updated features.\n")
    elif exit_code != 0:
        print(f"\n\033[91m[FAIL]\033[0m Upgrade failed with exit code {exit_code}.\n")

    return exit_code
