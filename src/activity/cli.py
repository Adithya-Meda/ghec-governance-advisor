"""CLI command orchestrator for Repo360 user activity analysis."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..auth.github_app_auth import GitHubAppAuth
from ..common.client import ResilientGitHubClient
from ..common.inventory import RepoEntry, load_flexible_repo_entries
from ..credentials import resolve_runtime_credentials
from .collector import (
    build_org_rows,
    build_rows,
    collect_repository,
    fetch_members,
    fetch_org_custom_properties,
    fetch_team_access,
    resolve_activity_targets,
)
from .models import ActivityConfig, RepositoryReport
from .reporter import write_activity_csv, write_activity_workbook

logger = logging.getLogger("repo360.activity")


def print_activity_scorecard(
    user_rows: List[list],
    org_rows: List[list],
    repos_count: int,
    xlsx_path: Path,
    csv_path: Path,
    elapsed_seconds: float,
) -> None:
    """Print an executive, color-coded terminal scorecard."""
    G = "\033[92m"
    Y = "\033[93m"
    C = "\033[96m"
    B = "\033[1m"
    X = "\033[0m"

    active_count = sum(1 for r in user_rows if r[2] == "Active")
    moderate_count = sum(1 for r in user_rows if r[2] == "Moderate")
    low_count = sum(1 for r in user_rows if r[2] == "Low")
    inactive_count = sum(1 for r in user_rows if r[2] == "Inactive")
    total_activities = sum(r[4] for r in user_rows)

    elapsed_str = (
        f"{int(elapsed_seconds // 60)}m {int(elapsed_seconds % 60)}s"
        if elapsed_seconds >= 60
        else f"{elapsed_seconds:.1f}s"
    )

    print(f"\n{C}{'=' * 76}{X}")
    print(f"{B}{C}   REPO360 CONTRIBUTOR & USER ACTIVITY SCORECARD{X}")
    print(f"{C}{'=' * 76}{X}")
    print(f"   {B}Organizations Scanned :{X} {len(org_rows)}")
    print(f"   {B}Repositories Scanned  :{X} {repos_count}")
    print(f"   {B}Total Users Tracked   :{X} {len(user_rows)}")
    print(f"   {B}Active Users          :{X} {G}{active_count:<5} Active (>= threshold){X}")
    print(f"   {B}Moderate Users        :{X} {Y}{moderate_count:<5} Moderate{X}")
    print(f"   {B}Low Users             :{X} {low_count:<5} Low")
    print(f"   {B}Inactive Users        :{X} {inactive_count:<5} Inactive (0 contributions)")
    print(f"   {B}Total Activities      :{X} {B}{total_activities:,}{X}")
    print(f"   {B}Duration              :{X} {elapsed_str}")
    print(f"{C}{'-' * 76}{X}")
    print(f"   {B}Executive Workbook (XLSX) :{X} {xlsx_path}")
    print(f"   {B}Flat Activity Feed (CSV)  :{X} {csv_path}")
    print(f"{C}{'=' * 76}{X}")
    print(f"{G}{B}   [SUCCESS] Activity analysis completed across {len(user_rows)} users in {elapsed_str}.{X}\n")


def run_activity_cli(argv: Optional[List[str]] = None) -> int:
    """Entry point for 'repo360 activity' subcommand."""
    parser = argparse.ArgumentParser(
        prog="repo360 activity",
        description="Analyze contributor cadence, active days, seat allocation, and commit/PR metrics.",
    )
    parser.add_argument(
        "--repos",
        default="repos.csv",
        help="Path to repository inventory CSV (default: repos.csv).",
    )
    parser.add_argument(
        "--output-dir",
        default="./repo360-output",
        help="Target directory for generated workbooks and SIEM data feeds (default: ./repo360-output).",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="Lookback analysis window in days (default: 90).",
    )
    parser.add_argument(
        "--active-min-days",
        type=int,
        default=8,
        help="Minimum active days for 'Active' status (default: 8).",
    )
    parser.add_argument(
        "--moderate-min-days",
        type=int,
        default=3,
        help="Minimum active days for 'Moderate' status (default: 3).",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived repositories in the analysis.",
    )
    parser.add_argument(
        "--include-bots",
        action="store_true",
        help="Include automated bot accounts in activity metrics.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=6,
        help="Concurrent repository worker threads (default: 6).",
    )
    parser.add_argument(
        "--config",
        default="",
        help="Optional path to custom JSON configuration file.",
    )

    args = parser.parse_args(argv)
    start_time = time.time()

    # 1. Resolve Credentials
    creds = resolve_runtime_credentials()
    app_id = creds.get("app_id")
    private_key = creds.get("private_key")
    api_base_url = creds.get("api_base_url", "https://api.github.com")

    if not app_id or not private_key:
        print("\n\033[91m[FAIL] Missing GitHub App credentials.\033[0m")
        print("Run 'repo360 setup' or configure REPO360_APP_ID and REPO360_APP_PRIVATE_KEY.\n")
        return 1

    # 2. Parse Repository Inventory
    repos_path = os.path.abspath(args.repos)
    if not os.path.isfile(repos_path):
        print(f"\n\033[91m[FAIL] Repository inventory file not found: {repos_path}\033[0m")
        print("Create a repos.csv with 'org,repo,enabled' or specify --repos <path>.\n")
        return 1

    try:
        entries = load_flexible_repo_entries(repos_path)
    except Exception as exc:
        print(f"\n\033[91m[FAIL] Invalid inventory CSV: {exc}\033[0m\n")
        return 1

    cfg = ActivityConfig(
        lookback_days=args.lookback_days,
        active_min_days=args.active_min_days,
        moderate_min_days=args.moderate_min_days,
        include_archived=args.include_archived,
        exclude_bots=not args.include_bots,
        max_workers=args.max_workers,
        output_dir=args.output_dir,
    )

    auth = GitHubAppAuth(
        app_id=app_id,
        private_key=private_key,
        api_base_url=api_base_url,
    )
    client = ResilientGitHubClient(auth=auth)

    end = datetime.now(timezone.utc)
    since = end - timedelta(days=cfg.lookback_days)
    stamp = end.strftime("%Y%m%d_%H%M%S")

    print(f"\033[96m[INFO]\033[0m Resolving target repositories from {repos_path}...")
    targets, failures, metadata_cache = resolve_activity_targets(client, entries, cfg)
    if not targets:
        print("\033[91m[FAIL] No repositories discovered or accessible to analyze.\033[0m\n")
        return 1

    orgs = sorted({org for org, _ in targets}, key=str.lower)
    print(f"\033[96m[INFO]\033[0m Scanning {len(targets)} repositories across {len(orgs)} organization(s)...")

    org_custom_props = fetch_org_custom_properties(client, orgs)
    reports: Dict[Tuple[str, str], RepositoryReport] = {}

    with ThreadPoolExecutor(max_workers=cfg.max_workers, thread_name_prefix="activity-worker") as pool:
        futures = {
            pool.submit(
                collect_repository,
                client,
                org,
                repo,
                since,
                end,
                cfg.exclude_bots,
                metadata_cache.get((org.casefold(), repo.casefold())),
                org_custom_props.get((org.casefold(), repo.casefold())),
            ): (org, repo)
            for org, repo in targets
        }
        for done_idx, fut in enumerate(as_completed(futures), start=1):
            org, repo = futures[fut]
            try:
                col = fut.result()
                reports[(org, repo)] = col
                if col.errors:
                    for err in col.errors:
                        failures.append((f"{org}/{repo}", err))
                logger.info("[%d/%d] Scanned %s/%s (%d contributors)", done_idx, len(targets), org, repo, len(col.users))
            except Exception as exc:
                failures.append((f"{org}/{repo}", str(exc)))
                logger.warning("[%d/%d] Error scanning %s/%s: %s", done_idx, len(targets), org, repo, exc)

    print(f"\033[96m[INFO]\033[0m Fetching organization members and teams...")
    members = fetch_members(client, orgs, cfg.exclude_bots, failures)
    teams_by_user, org_team_complete = fetch_team_access(
        client, orgs, cfg.exclude_bots
    )

    results = {k: v.users for k, v in reports.items() if v.activity_complete}
    user_rows, repo_rows = build_rows(results, members, cfg, end, teams_by_user, org_team_complete)
    org_rows = build_org_rows(user_rows, results)

    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / f"{cfg.file_prefix}_{stamp}.xlsx"
    csv_path = out_dir / f"{cfg.file_prefix}_{stamp}.csv"

    elapsed = time.time() - start_time
    write_activity_workbook(
        xlsx_path,
        cfg,
        since,
        end,
        user_rows,
        repo_rows,
        org_rows,
        failures,
        len(targets),
        execution_duration=elapsed,
    )
    from .models import USER_HEADERS
    write_activity_csv(csv_path, USER_HEADERS, user_rows)

    print_activity_scorecard(
        user_rows=user_rows,
        org_rows=org_rows,
        repos_count=len(targets),
        xlsx_path=xlsx_path,
        csv_path=csv_path,
        elapsed_seconds=elapsed,
    )
    return 0
