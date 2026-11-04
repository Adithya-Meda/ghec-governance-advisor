"""User activity and contributor cadence collection engine."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from ..common.client import ResilientGitHubClient
from ..common.inventory import RepoEntry
from .models import (
    DATE_FMT,
    IST,
    METRIC_KEYS,
    METRIC_LABELS,
    METRICS,
    STATUS_IDX,
    STATUS_ORDER,
    STATUSES,
    TOTAL_IDX,
    Activity,
    ActivityConfig,
    RepositoryReport,
    fmt_timestamp,
    is_bot,
    parse_ts,
)

logger = logging.getLogger("repo360.activity")


def resolve_activity_targets(
    client: ResilientGitHubClient,
    entries: List[RepoEntry],
    cfg: ActivityConfig,
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], Dict[Tuple[str, str], Dict[str, Any]]]:
    """Resolve and expand target repositories (including '*' wildcard) with metadata cache."""
    enabled_entries = [e for e in entries if e.enabled]
    org_wildcards = {e.org.lower(): e.org for e in enabled_entries if e.repo == "*"}
    specific_repos = [(e.org, e.repo) for e in enabled_entries if e.repo != "*"]

    targets: List[Tuple[str, str]] = []
    failures: List[Tuple[str, str]] = []
    metadata_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

    # Expand wildcards
    for org_lower, original_org in org_wildcards.items():
        try:
            for repo_data in client.paginate(original_org, f"/orgs/{original_org}/repos", {"type": "all"}):
                repo_name = repo_data.get("name")
                if not repo_name:
                    continue
                if repo_data.get("archived") and not cfg.include_archived:
                    continue
                if repo_data.get("fork") and not cfg.include_forks:
                    continue
                targets.append((original_org, repo_name))
                metadata_cache[(original_org.casefold(), repo_name.casefold())] = repo_data
        except Exception as exc:
            failures.append((f"{original_org}/*", str(exc)))
            logger.error("Failed expanding wildcard for org %s: %s", original_org, exc)

    # Fetch specific repos
    for org, repo in specific_repos:
        try:
            repo_data = client.get(org, f"/repos/{org}/{repo}")
            if repo_data.get("archived") and not cfg.include_archived:
                continue
            if repo_data.get("fork") and not cfg.include_forks:
                continue
            targets.append((org, repo))
            metadata_cache[(org.casefold(), repo.casefold())] = repo_data
        except Exception as exc:
            failures.append((f"{org}/{repo}", str(exc)))
            logger.warning("Repository %s/%s inaccessible: %s", org, repo, exc)

    targets.sort(key=lambda t: (t[0].lower(), t[1].lower()))
    return targets, failures, metadata_cache


def fetch_org_custom_properties(
    client: ResilientGitHubClient, orgs: List[str]
) -> Dict[Tuple[str, str], Any]:
    """Fetch repository custom property values in bulk per organization."""
    props: Dict[Tuple[str, str], Any] = {}
    for org in orgs:
        try:
            for item in client.paginate(org, f"/orgs/{org}/properties/values"):
                repo_name = item.get("repository_name")
                if repo_name and "properties" in item:
                    props[(org.casefold(), repo_name.casefold())] = item["properties"]
        except Exception as exc:
            logger.debug("Org custom properties bulk retrieval unavailable for %s: %s", org, exc)
    return props


def collect_pull_requests_graphql(
    client: ResilientGitHubClient,
    org: str,
    repo: str,
    collected_since: datetime,
    since: datetime,
    end: datetime,
    exclude_bots: bool,
    report: Optional[RepositoryReport],
    record_fn: Any,
) -> bool:
    """Collect PRs, merges, and reviews via batched GraphQL query for fast retrieval."""
    query = """
    query($owner: String!, $name: String!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        pullRequests(first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            number
            createdAt
            mergedAt
            updatedAt
            author {
              login
            }
            reviews(first: 50) {
              nodes {
                author {
                  login
                }
                submittedAt
                state
              }
            }
          }
        }
      }
    }
    """
    cursor = None
    while True:
        data = client.graphql(org, query, {"owner": org, "name": repo, "cursor": cursor})
        repo_data = (data.get("data") or {}).get("repository")
        if not repo_data:
            return False

        prs = (repo_data.get("pullRequests") or {}).get("nodes") or []
        for pr in prs:
            updated_at = parse_ts(pr["updatedAt"])
            if updated_at < collected_since:
                return True

            author_dict = {"login": pr["author"]["login"]} if pr.get("author") and pr["author"].get("login") else None
            record_fn(author_dict, "prs_opened", pr.get("createdAt"))
            record_fn(author_dict, "prs_merged", pr.get("mergedAt"))
            created = parse_ts(pr["createdAt"])
            eligible = not (exclude_bots and author_dict and is_bot(author_dict))
            if report is not None and eligible and since <= created <= end:
                report.cohort_opened += 1
                if pr.get("mergedAt") and parse_ts(pr["mergedAt"]) <= end:
                    report.cohort_merged += 1

            first_review: Optional[datetime] = None
            reviews = (pr.get("reviews") or {}).get("nodes") or []
            for review in reviews:
                if review.get("state") == "PENDING" or not review.get("submittedAt"):
                    continue
                rev_dict = {"login": review["author"]["login"]} if review.get("author") and review["author"].get("login") else None
                record_fn(rev_dict, "reviews", review["submittedAt"])
                submitted = parse_ts(review["submittedAt"])
                if (
                    rev_dict and rev_dict.get("login") and author_dict
                    and rev_dict["login"].lower() != (author_dict.get("login") or "").lower()
                    and not (exclude_bots and is_bot(rev_dict))
                    and created <= submitted <= end
                ):
                    first_review = min(first_review, submitted) if first_review else submitted

            if report is not None and first_review and since <= first_review <= end:
                report.review_hours.append((first_review - created).total_seconds() / 3600)

        page_info = (repo_data.get("pullRequests") or {}).get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return True


def collect_repo_events(
    client: ResilientGitHubClient,
    org: str,
    repo: str,
    since: datetime,
    exclude_bots: bool,
    end: Optional[datetime] = None,
    report: Optional[RepositoryReport] = None,
) -> Dict[str, Activity]:
    """Collect commit, PR, review, and issue activities for a single repository."""
    activity: Dict[str, Activity] = defaultdict(Activity)
    base = f"/repos/{org}/{repo}"
    end = end or datetime.now(timezone.utc)
    month_start = end.astimezone(IST).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    collected_since = min(since, end - timedelta(days=30), month_start) if report else since
    since_param = {"since": collected_since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def record(user: Optional[Dict[str, Any]], metric: str, timestamp: Optional[str]) -> None:
        if not timestamp or (user and exclude_bots and is_bot(user)):
            return
        when = parse_ts(timestamp)
        login = user.get("login") if user else None
        if collected_since <= when <= end and report is not None:
            report.events.append((login.lower() if login else None, metric, when))
        if since <= when <= end and login:
            activity[login].add(metric, when)

    # 1. Commits
    pushed_at_str = report.metadata.get("pushed_at") if report and report.metadata else None
    pushed_at = parse_ts(pushed_at_str) if pushed_at_str else None
    if not (pushed_at and pushed_at < collected_since):
        try:
            for commit in client.paginate(
                org, f"{base}/commits", {**since_param, "until": end.strftime("%Y-%m-%dT%H:%M:%SZ")}
            ):
                record(commit.get("author"), "commits", commit.get("commit", {}).get("author", {}).get("date"))
        except Exception as exc:
            if report:
                report.errors.append(f"Commits: {exc}")

    # 2. Pull Requests
    has_prs = report is None or report.metadata.get("has_pull_requests", True)
    if has_prs:
        pr_success = False
        try:
            pr_success = collect_pull_requests_graphql(
                client, org, repo, collected_since, since, end, exclude_bots, report, record
            )
        except Exception as exc:
            logger.debug("GraphQL PR collection failed for %s/%s (%s); falling back to REST", org, repo, exc)
            pr_success = False

        if not pr_success:
            try:
                pulls = client.paginate(org, f"{base}/pulls", {"state": "all", "sort": "updated", "direction": "desc"})
                for pr in pulls:
                    if parse_ts(pr["updated_at"]) < collected_since:
                        break
                    record(pr.get("user"), "prs_opened", pr.get("created_at"))
                    record(pr.get("user"), "prs_merged", pr.get("merged_at"))
                    created = parse_ts(pr["created_at"])
                    eligible = not (exclude_bots and is_bot(pr.get("user") or {}))
                    if report is not None and eligible and since <= created <= end:
                        report.cohort_opened += 1
                        if pr.get("merged_at") and parse_ts(pr["merged_at"]) <= end:
                            report.cohort_merged += 1

                    first_review: Optional[datetime] = None
                    for review in client.paginate(org, f"{base}/pulls/{pr['number']}/reviews"):
                        reviewer = review.get("user") or {}
                        if review.get("state") == "PENDING" or not review.get("submitted_at"):
                            continue
                        record(reviewer, "reviews", review["submitted_at"])
                        submitted = parse_ts(review["submitted_at"])
                        if (
                            reviewer.get("login")
                            and reviewer["login"].lower() != (pr.get("user") or {}).get("login", "").lower()
                            and not (exclude_bots and is_bot(reviewer))
                            and created <= submitted <= end
                        ):
                            first_review = min(first_review, submitted) if first_review else submitted

                    if report is not None and first_review and since <= first_review <= end:
                        report.review_hours.append((first_review - created).total_seconds() / 3600)
            except Exception as exc:
                if report:
                    report.errors.append(f"Pulls: {exc}")

    # 3. Issues & Comments
    has_issues = report.metadata.get("has_issues", True) if report and report.metadata else True
    if has_issues:
        try:
            for issue in client.paginate(org, f"{base}/issues", {"state": "all", **since_param}):
                if "pull_request" not in issue:
                    record(issue.get("user"), "issues_opened", issue.get("created_at"))
        except Exception as exc:
            if report:
                report.errors.append(f"Issues: {exc}")

        try:
            for comment in client.paginate(org, f"{base}/issues/comments", since_param):
                record(comment.get("user"), "issue_comments", comment.get("created_at"))
        except Exception as exc:
            if report:
                report.errors.append(f"Issue Comments: {exc}")

    if has_prs:
        try:
            for comment in client.paginate(org, f"{base}/pulls/comments", since_param):
                record(comment.get("user"), "review_comments", comment.get("created_at"))
        except Exception as exc:
            if report:
                report.errors.append(f"PR Comments: {exc}")

    return dict(activity)


def collect_repository(
    client: ResilientGitHubClient,
    org: str,
    repo: str,
    since: datetime,
    end: datetime,
    exclude_bots: bool,
    cached_metadata: Optional[Dict[str, Any]] = None,
    cached_properties: Optional[Any] = None,
) -> RepositoryReport:
    """Perform complete activity inspection and governance audit for a repository."""
    report = RepositoryReport()
    base = f"/repos/{org}/{repo}"

    # 1. Metadata
    if cached_metadata is not None:
        report.metadata = cached_metadata
    else:
        try:
            report.metadata = client.get(org, base)
        except Exception as exc:
            report.errors.append(f"Metadata: {exc}")
            return report

    # 2. Activity scan
    size = report.metadata.get("size", 1)
    pushed_at = parse_ts(report.metadata["pushed_at"]) if report.metadata.get("pushed_at") else None
    updated_at = parse_ts(report.metadata["updated_at"]) if report.metadata.get("updated_at") else None

    is_dormant = bool(size == 0 or (pushed_at and pushed_at < since and updated_at and updated_at < since))
    if is_dormant:
        report.users = {}
        report.activity_complete = True
    else:
        try:
            report.users = collect_repo_events(client, org, repo, since, exclude_bots, end, report)
            report.activity_complete = True
        except Exception as exc:
            report.errors.append(f"Activity: {exc}")

    # 4. Branch protection
    if size == 0 or report.metadata.get("archived"):
        report.protected = "No"
        report.protected_branches = ()
    else:
        try:
            protected = [
                b["name"]
                for b in client.paginate(org, f"{base}/branches", {"protected": "true"})
                if isinstance(b, dict) and "name" in b
            ]
            report.protected_branches = tuple(sorted(protected, key=str.casefold))
            report.protected = "Yes" if report.protected_branches else "No"
        except Exception as exc:
            report.errors.append(f"Branch protection: {exc}")

    # 5. CODEOWNERS check
    branch = report.metadata.get("default_branch")
    if not branch or size == 0:
        report.codeowners = "No"
    else:
        try:
            tree_data = client.get(org, f"{base}/git/trees/{branch}", {"recursive": "1"})
            tree_paths = {item["path"] for item in tree_data.get("tree", []) if item.get("type") == "blob"}
            for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
                if path in tree_paths:
                    report.codeowners, report.codeowners_path = "Yes", path
                    break
            else:
                report.codeowners = "No"
        except Exception:
            for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
                try:
                    content = client.get(org, f"{base}/contents/{path}", {"ref": branch})
                    if isinstance(content, dict) and content.get("type") == "file":
                        report.codeowners, report.codeowners_path = "Yes", path
                        break
                except Exception:
                    continue
            else:
                report.codeowners = "No"

    return report


def fetch_members(
    client: ResilientGitHubClient, orgs: List[str], exclude_bots: bool, failures: List[Tuple[str, str]]
) -> Dict[str, Set[str]]:
    """Fetch current organization members."""
    members: Dict[str, Set[str]] = {}
    for org in orgs:
        try:
            org_members = {
                m["login"] for m in client.paginate(org, f"/orgs/{org}/members")
                if isinstance(m, dict) and "login" in m and not (exclude_bots and is_bot(m))
            }
            members[org] = org_members
        except Exception as exc:
            logger.warning("Failed retrieving members for %s: %s", org, exc)
            failures.append((f"{org} (members)", str(exc)))
    return members


def fetch_team_access(
    client: ResilientGitHubClient,
    orgs: List[str],
    exclude_bots: bool,
) -> Tuple[Dict[Tuple[str, str], Set[str]], Dict[str, bool]]:
    """Map user team memberships across target organizations."""
    teams_by_user: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    org_team_complete: Dict[str, bool] = {}

    for org in orgs:
        try:
            teams = list(client.paginate(org, f"/orgs/{org}/teams"))
            for team in teams:
                slug = team.get("slug")
                if not slug:
                    continue
                try:
                    t_members = {
                        m["login"] for m in client.paginate(org, f"/orgs/{org}/teams/{slug}/members")
                        if isinstance(m, dict) and "login" in m and not (exclude_bots and is_bot(m))
                    }
                    for login in t_members:
                        teams_by_user[(org, login)].add(slug)
                except Exception as exc:
                    logger.debug("Team %s/%s member lookup failed: %s", org, slug, exc)
            org_team_complete[org] = True
        except Exception as exc:
            logger.debug("Teams lookup unavailable for %s: %s", org, exc)
            org_team_complete[org] = False

    return teams_by_user, org_team_complete


def classify(active_days: int, cfg: ActivityConfig) -> str:
    """Categorize user into Active, Moderate, Low, or Inactive based on distinct days."""
    if active_days >= cfg.active_min_days:
        return "Active"
    if active_days >= cfg.moderate_min_days:
        return "Moderate"
    return "Low" if active_days else "Inactive"


def build_rows(
    results: Dict[Tuple[str, str], Dict[str, Activity]],
    members: Dict[str, Set[str]],
    cfg: ActivityConfig,
    end: datetime,
    teams_by_user: Dict[Tuple[str, str], Set[str]],
    org_team_complete: Dict[str, bool],
) -> Tuple[List[list], List[list]]:
    """Compile formatted tabular user rows and repo activity rows."""
    per_user: Dict[Tuple[str, str], Activity] = defaultdict(Activity)
    repos_by_user: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    teams_norm: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    repo_rows: List[list] = []

    for (org, login), teams in teams_by_user.items():
        teams_norm[(org, login.casefold())].update(teams)

    for (org, repo), users in sorted(results.items(), key=lambda x: (x[0][0].lower(), x[0][1].lower())):
        for login, act in sorted(users.items(), key=lambda x: (-x[1].total(), x[0].lower())):
            per_user[(org, login)].merge(act)
            repos_by_user[(org, login)].add(repo)
            repo_rows.append([
                org, repo, login, act.total(),
                act.commits, act.prs_opened, act.prs_merged, act.reviews,
                act.review_comments, act.issues_opened, act.issue_comments,
                len(act.active_days), fmt_timestamp(act.last_active),
            ])

    if cfg.include_inactive_members:
        for org, logins in members.items():
            for login in logins:
                per_user.setdefault((org, login), Activity())

    user_rows: List[list] = []
    for (org, login), act in per_user.items():
        member_flag = ("Yes" if login in members.get(org, set()) else "No") if org in members else "Unknown"
        teams = sorted(teams_norm.get((org, login.casefold()), ()), key=str.casefold)
        team_str = "; ".join(teams)
        if not org_team_complete.get(org, False):
            team_str = f"{team_str}; Unknown" if team_str else "Unknown"
        elif not team_str:
            team_str = "None"

        active_days_count = len(act.active_days)
        active_months = len(act.commit_months)
        avg_commits = round(act.commits / active_months, 2) if active_months else None
        days_since_last = (end - act.last_active).days if act.last_active else None

        user_rows.append([
            org,
            login,
            classify(active_days_count, cfg),
            active_days_count,
            act.total(),
            act.commits,
            act.prs_opened,
            act.prs_merged,
            act.reviews,
            act.review_comments,
            act.issues_opened,
            act.issue_comments,
            avg_commits,
            len(repos_by_user.get((org, login), ())),
            fmt_timestamp(act.first_active),
            fmt_timestamp(act.last_active),
            days_since_last,
            member_flag,
            team_str,
        ])

    user_rows.sort(key=lambda r: (r[0].lower(), STATUS_ORDER.get(r[STATUS_IDX], 99), -r[TOTAL_IDX], r[1].lower()))
    return user_rows, repo_rows


def build_org_rows(user_rows: List[list], results: Dict[Tuple[str, str], Dict[str, Activity]]) -> List[list]:
    """Aggregate per-organization contributor metrics and status distribution."""
    repo_counts = Counter(org for org, _ in results)
    stats: Dict[str, Counter] = defaultdict(Counter)
    for row in user_rows:
        org = row[0]
        stats[org][row[STATUS_IDX]] += 1
        stats[org]["total"] += row[TOTAL_IDX]
        if row[TOTAL_IDX] > 0:
            stats[org]["contributors"] += 1

    orgs = sorted(set(repo_counts) | set(stats), key=str.lower)
    return [
        [
            org,
            repo_counts[org],
            stats[org]["contributors"],
            stats[org]["Active"],
            stats[org]["Moderate"],
            stats[org]["Low"],
            stats[org]["Inactive"],
            stats[org]["total"],
        ]
        for org in orgs
    ]


def load_history(path: Path) -> Dict[str, Any]:
    """Load historical adoption trend snapshots."""
    if not path.is_file():
        return {"version": 1, "snapshots": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("version") == 1 and isinstance(data.get("snapshots"), list):
            return data
    except Exception as exc:
        logger.debug("Could not read adoption history from %s: %s", path, exc)
    return {"version": 1, "snapshots": []}


def save_history(path: Path, data: Dict[str, Any]) -> None:
    """Safely persist adoption history snapshots."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp.replace(path)
    except Exception as exc:
        logger.debug("Failed saving adoption history: %s", exc)
        if temp.exists():
            temp.unlink(missing_ok=True)
