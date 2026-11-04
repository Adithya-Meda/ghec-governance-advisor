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


def find_pipx_executable() -> Optional[str]:
    """Locate pipx executable in PATH or standard user package script directories."""
    path_hit = shutil.which("pipx")
    if path_hit:
        return path_hit

    appdata = os.environ.get("LOCALAPPDATA")
    candidates = [
        Path(os.path.expanduser("~")) / ".local" / "bin" / "pipx.exe",
        Path(os.path.expanduser("~")) / ".local" / "bin" / "pipx",
    ]
    if appdata:
        candidates.extend([
            Path(appdata) / "Programs" / "Python" / "Scripts" / "pipx.exe",
            Path(appdata) / "pipx" / "pipx.exe",
        ])
        packages_dir = Path(appdata) / "Packages"
        if packages_dir.is_dir():
            for p in packages_dir.glob("PythonSoftwareFoundation.Python.*/LocalCache/local-packages/Python*/Scripts/pipx.exe"):
                candidates.append(p)

    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def detect_installer() -> Tuple[str, List[str]]:
    """Detect whether Repo360 is running within pipx or standard pip/virtualenv.

    Returns:
        Tuple of (installer_name, base_command_tokens).
    """
    prefix = sys.prefix.lower()
    pipx_bin = find_pipx_executable()

    if "pipx" in prefix and pipx_bin:
        # Use 'pipx runpip' to safely upgrade in-place without tearing down the venv,
        # preventing Windows OS Error 32 (file lock on running python.exe)
        return "pipx", [pipx_bin, "runpip", "repo360", "install", "--upgrade"]

    # Fallback to python -m pip using the current active interpreter
    return "pip", [sys.executable, "-m", "pip", "install", "--upgrade"]


def get_upgrade_commands(
    repo_url: str = DEFAULT_REPO_URL,
    installer_override: Optional[str] = None,
) -> List[Tuple[str, List[str]]]:
    """Generate prioritized upgrade command candidates for resilient execution across platforms.

    Returns:
        List of (strategy_name, command_tokens).
    """
    target_spec = f"git+{repo_url}"
    commands: List[Tuple[str, List[str]]] = []

    prefix = sys.prefix.lower()
    pipx_bin = find_pipx_executable()

    if installer_override == "pip":
        return [("pip", [sys.executable, "-m", "pip", "install", "--upgrade", target_spec])]

    # 1. In pipx: in-place upgrade via 'pipx runpip' avoids OS Error 32 on Windows and venv rebuilds
    if ("pipx" in prefix or installer_override == "pipx") and pipx_bin:
        commands.append(("pipx", [pipx_bin, "runpip", "repo360", "install", "--upgrade", target_spec]))

    # 2. Check for uv if available
    uv_bin = shutil.which("uv")
    if not uv_bin and pipx_bin:
        cand = Path(pipx_bin).parent / ("uv.exe" if sys.platform == "win32" else "uv")
        if cand.is_file():
            uv_bin = str(cand)
    if uv_bin:
        commands.append(("uv", [uv_bin, "pip", "install", "--python", sys.executable, "--upgrade", target_spec]))

    # 3. Universal Python interpreter fallback
    commands.append(("pip", [sys.executable, "-m", "pip", "install", "--upgrade", target_spec]))
    return commands


def build_upgrade_command(
    repo_url: str = DEFAULT_REPO_URL,
    installer_override: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """Construct the primary shell command to upgrade Repo360 to the latest version.

    Args:
        repo_url: Git repository clone URL.
        installer_override: Force 'pipx' or 'pip'.

    Returns:
        Tuple of (installer_type, command_list).
    """
    candidates = get_upgrade_commands(repo_url, installer_override)
    return candidates[0][0], candidates[0][1]


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


def _prepare_windows_binaries(scripts_dir: Path) -> List[Tuple[Path, Path]]:
    """On Windows, running .exe files cannot be deleted or overwritten in-place.

    Windows NT allows renaming running executables. Renaming existing entrypoints
    to temporary names allows the package installer to write clean new .exe files.
    """
    renamed: List[Tuple[Path, Path]] = []
    if sys.platform != "win32" or not scripts_dir.is_dir():
        return renamed

    # Clean up stale .old files from prior runs
    for old_file in scripts_dir.glob("*.exe.old_*"):
        try:
            old_file.unlink(missing_ok=True)
        except OSError:
            pass

    # Rename entrypoints to avoid OS error 5 / 32 during wheel extraction
    pid = os.getpid()
    for exe_name in ("repo360.exe", "repo360-audit.exe", "repo360-activity.exe", "repo360-runners.exe"):
        exe_file = scripts_dir / exe_name
        if exe_file.is_file():
            staged = scripts_dir / f"{exe_name}.old_{pid}"
            try:
                exe_file.rename(staged)
                renamed.append((exe_file, staged))
            except OSError as exc:
                logger.debug("Could not stage rename for %s: %s", exe_file, exc)

    return renamed


def _restore_windows_binaries(renamed: List[Tuple[Path, Path]], success: bool) -> None:
    """Restore original executables if upgrade failed, or attempt removal of staged files."""
    if sys.platform != "win32":
        return

    for original, staged in renamed:
        if not success:
            if not original.is_file() and staged.is_file():
                try:
                    staged.rename(original)
                except OSError:
                    pass
        else:
            if staged.is_file():
                try:
                    staged.unlink(missing_ok=True)
                except OSError:
                    # Windows holds running exe lock until process exits; cleaned up on next run
                    pass


def execute_upgrade(candidates: List[Tuple[str, List[str]]], dry_run: bool = False) -> int:
    """Execute the upgrade process via subprocess with resilient fallback across strategies."""
    if dry_run:
        chosen = candidates[0]
        print(f"\n\033[96m[DRY-RUN]\033[0m Would execute upgrade ({chosen[0]}):\n  {' '.join(chosen[1])}\n")
        return 0

    scripts_dir = Path(sys.executable).parent
    renamed = _prepare_windows_binaries(scripts_dir)

    success = False
    last_error: Optional[str] = None
    for strategy_name, cmd in candidates:
        logger.debug("Executing upgrade via %s: %s", strategy_name, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                success = True
                break
            err_lines = [line.strip() for line in (result.stderr or result.stdout or "").splitlines() if line.strip()]
            last_error = err_lines[-1] if err_lines else f"Exited with code {result.returncode}"
        except Exception as exc:
            last_error = str(exc)

    _restore_windows_binaries(renamed, success=success)

    if success:
        return 0

    print(f"\n\033[91m[FAIL]\033[0m Upgrade failed: {last_error}\n")
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

    candidates = get_upgrade_commands(args.source, installer_override)
    print("\033[96m[INFO]\033[0m Upgrading Repo360 to the latest version...")

    exit_code = execute_upgrade(candidates, dry_run=args.dry_run)
    if exit_code == 0 and not args.dry_run:
        print("\033[92m[SUCCESS]\033[0m Repo360 upgraded successfully.")
    elif exit_code != 0:
        print(f"\033[91m[FAIL]\033[0m Upgrade failed with exit code {exit_code}.\n")

    return exit_code
