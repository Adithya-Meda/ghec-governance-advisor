"""Flexible repository inventory parser for Repo360 activity and runner scrapers."""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

ORG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
TRUE_VALUES = frozenset({"true", "yes", "y", "1"})
FALSE_VALUES = frozenset({"false", "no", "n", "0"})


@dataclass(frozen=True)
class RepoEntry:
    """Repository entry targeting an organization and repo."""

    org: str
    repo: str
    enabled: bool = True


def load_flexible_repo_entries(path: str | os.PathLike) -> List[RepoEntry]:
    """Parse and validate repository inventory from CSV with flexible column headers.

    Supported column aliases:
      - Organization: 'org', 'org_name', 'organization'
      - Repository: 'repo', 'repo_name', 'repository'
      - Enabled flag: 'enabled', 'active' (optional, defaults to True)

    Supports wildcard '*' for repo to target all repositories in the organization.
    """
    file_path = os.path.abspath(path)
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Repository inventory CSV not found: {file_path}")

    entries: List[RepoEntry] = []
    seen: Dict[Tuple[str, str], bool] = {}
    errors: List[str] = []

    with open(file_path, "r", newline="", encoding="utf-8-sig") as handle:
        lines = [line for line in handle if line.strip() and not line.strip().startswith("#")]
        if not lines:
            raise ValueError(f"{os.path.basename(file_path)} contains no repository rows.")

        reader = csv.DictReader(lines)
        if not reader.fieldnames:
            raise ValueError(f"{os.path.basename(file_path)} is empty or missing headers.")

        field_map: Dict[str, str] = {}
        for fn in reader.fieldnames:
            if not fn:
                continue
            cleaned = fn.strip().lower()
            if cleaned in ("org", "org_name", "organization"):
                field_map["org"] = fn
            elif cleaned in ("repo", "repo_name", "repository"):
                field_map["repo"] = fn
            elif cleaned in ("enabled", "active"):
                field_map["enabled"] = fn

        if "org" not in field_map or "repo" not in field_map:
            raise ValueError(
                f"{os.path.basename(file_path)} must include organization and repository columns "
                "(e.g. 'org,repo' or 'org_name,repo_name')."
            )

        org_col = field_map["org"]
        repo_col = field_map["repo"]
        enabled_col = field_map.get("enabled")

        for line_no, raw in enumerate(reader, start=2):
            if not any(v and v.strip() for v in raw.values() if isinstance(v, str)):
                continue

            org = (raw.get(org_col) or "").strip()
            if not org or org.startswith("#"):
                continue

            repo = (raw.get(repo_col) or "").strip()
            if repo.startswith("#"):
                continue

            if enabled_col:
                flag = (raw.get(enabled_col) or "").strip().lower()
            else:
                flag = "true"

            problems: List[str] = []
            if not ORG_RE.fullmatch(org):
                problems.append(f"invalid organization '{org}' (alphanumeric/hyphens only)")
            if repo != "*" and (not REPO_RE.fullmatch(repo) or repo in {".", ".."}):
                problems.append(f"invalid repository '{repo}' (use '*' for all repositories)")
            if flag not in TRUE_VALUES and flag not in FALSE_VALUES:
                problems.append(f"invalid enabled value '{flag}' (must be true/false/yes/no/1/0)")

            if problems:
                errors.append(f"line {line_no}: {'; '.join(problems)}")
                continue

            is_enabled = flag in TRUE_VALUES
            key = (org.lower(), repo.lower())
            if key in seen:
                if seen[key] != is_enabled:
                    errors.append(f"line {line_no}: conflicting enabled values for {org}/{repo}")
                continue

            seen[key] = is_enabled
            entries.append(RepoEntry(org=org, repo=repo, enabled=is_enabled))

    if errors:
        raise ValueError(f"{os.path.basename(file_path)} validation failed:\n  " + "\n  ".join(errors))

    if not any(entry.enabled for entry in entries):
        raise ValueError(f"{os.path.basename(file_path)} contains no enabled repositories to scan.")

    return entries
