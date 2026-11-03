"""Repository and Organization data collector for GHEC governance checks."""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional
import requests

from .client import GHECClient

logger = logging.getLogger(__name__)


class RepoInspector:
    """Collects metadata, settings, and file contents from GHEC."""

    def __init__(self, client: GHECClient) -> None:
        """Initialize with an authenticated client.

        Args:
            client: Authenticated GHECClient instance.
        """
        self.client = client

    # --- Organization-Level Collectors ---

    def get_org_info(self, org: str) -> Optional[Dict[str, Any]]:
        """Fetch general organization metadata."""
        return self.client.get(f"/orgs/{org}", allow_404=True)

    def get_org_rulesets(self, org: str) -> List[Dict[str, Any]]:
        """Fetch all organization-level repository rulesets."""
        data = self.client.get(f"/orgs/{org}/rulesets", allow_404=True)
        return data if isinstance(data, list) else []

    def get_org_runner_groups(self, org: str) -> List[Dict[str, Any]]:
        """Fetch self-hosted runner groups in the organization."""
        data = self.client.get(f"/orgs/{org}/actions/runner-groups", allow_404=True)
        if isinstance(data, dict) and "runner_groups" in data:
            return data["runner_groups"]
        return []

    def get_org_actions_permissions(self, org: str) -> Optional[Dict[str, Any]]:
        """Fetch default actions permissions for the organization."""
        return self.client.get(f"/orgs/{org}/actions/permissions", allow_404=True)

    def list_installation_repositories(
        self, per_page: int = 100, max_pages: int = 50
    ) -> List[Dict[str, Any]]:
        """List all repositories accessible to the current GitHub App installation."""
        all_repos: List[Dict[str, Any]] = []
        page = 1

        while page <= max_pages:
            data = self.client.get(
                "/installation/repositories",
                params={"per_page": per_page, "page": page},
                allow_404=True,
            )
            if not data or not isinstance(data, dict):
                break

            repos = data.get("repositories", [])
            if not repos:
                break

            all_repos.extend(repos)
            total_count = data.get("total_count", 0)
            if len(all_repos) >= total_count or len(repos) < per_page:
                break
            page += 1

        return all_repos

    # --- Repository-Level Collectors ---

    def get_repo_metadata(self, org: str, repo: str) -> Optional[Dict[str, Any]]:
        """Fetch repository details."""
        return self.client.get(f"/repos/{org}/{repo}", allow_404=True)

    def get_repo_rulesets(self, org: str, repo: str) -> List[Dict[str, Any]]:
        """Fetch repository-level rulesets (falls back gracefully if 403 forbidden or unconfigured)."""
        try:
            data = self.client.get(f"/repos/{org}/{repo}/rulesets", allow_404=True)
            return data if isinstance(data, list) else []
        except requests.exceptions.HTTPError as err:
            if getattr(err, "response", None) is not None and err.response.status_code == 403:
                logger.debug("Rulesets API returned 403 on %s/%s (falling back to classic protection).", org, repo)
                return []
            raise

    def get_branch_protection(
        self, org: str, repo: str, branch: str = "main"
    ) -> Optional[Dict[str, Any]]:
        """Fetch branch protection rules for a specific branch (falls back gracefully if 403/404)."""
        try:
            return self.client.get(
                f"/repos/{org}/{repo}/branches/{branch}/protection", allow_404=True
            )
        except requests.exceptions.HTTPError as err:
            if getattr(err, "response", None) is not None and err.response.status_code == 403:
                logger.debug("Branch protection API returned 403 on %s/%s:%s.", org, repo, branch)
                return None
            raise

    def get_file_content(
        self, org: str, repo: str, path: str, ref: str = "main"
    ) -> Optional[str]:
        """Fetch and decode utf-8 text file content from repository.

        Args:
            org: Organization name.
            repo: Repository name.
            path: Relative path to file (e.g., 'CODEOWNERS' or '.github/copilot-instructions.md').
            ref: Branch or commit ref.

        Returns:
            Decoded file text content, or None if file does not exist.
        """
        data = self.client.get(
            f"/repos/{org}/{repo}/contents/{path.lstrip('/')}",
            params={"ref": ref},
            allow_404=True,
        )
        if not data or not isinstance(data, dict):
            return None

        content = data.get("content")
        encoding = data.get("encoding")
        if content and encoding == "base64":
            try:
                decoded_bytes = base64.b64decode(content)
                return decoded_bytes.decode("utf-8", errors="replace")
            except Exception as err:
                logger.warning("Failed to decode %s in %s/%s: %s", path, org, repo, err)
                return None
        return None

    def list_workflows(self, org: str, repo: str) -> List[Dict[str, Any]]:
        """List GitHub Actions workflow files and details."""
        data = self.client.get(f"/repos/{org}/{repo}/actions/workflows", allow_404=True)
        if isinstance(data, dict) and "workflows" in data:
            return data["workflows"]
        return []

    def get_environments(self, org: str, repo: str) -> List[Dict[str, Any]]:
        """Fetch deployment environments configured for the repository."""
        data = self.client.get(f"/repos/{org}/{repo}/environments", allow_404=True)
        if isinstance(data, dict) and "environments" in data:
            return data["environments"]
        return []

    def check_file_exists(
        self, org: str, repo: str, path: str, ref: str = "main"
    ) -> bool:
        """Check if a file or directory exists in the repo."""
        data = self.client.get(
            f"/repos/{org}/{repo}/contents/{path.lstrip('/')}",
            params={"ref": ref},
            allow_404=True,
        )
        return data is not None

    def detect_tech_stack(
        self, org: str, repo: str, ref: str = "main"
    ) -> Dict[str, Any]:
        """Detect the technology stack, languages, and package manifests of a repository."""
        languages: List[str] = []
        manifests: List[str] = []
        frameworks: List[str] = []

        manifest_checks = [
            ("package.json", "Node.js / TypeScript"),
            ("requirements.txt", "Python"),
            ("pyproject.toml", "Python"),
            ("pom.xml", "Java (Maven)"),
            ("build.gradle", "Java / Kotlin (Gradle)"),
            ("go.mod", "Go"),
            ("Cargo.toml", "Rust"),
            ("global.json", "C# / .NET Core"),
            ("Directory.Build.props", "C# / .NET Core"),
            ("NuGet.config", "C# / .NET Core"),
            ("Dockerfile", "Docker"),
            ("docker-compose.yml", "Docker Compose"),
            ("CMakeLists.txt", "C / C++"),
        ]

        # Use primary language from repo metadata if available
        repo_meta = self.get_repo_metadata(org, repo) or {}
        primary_lang = repo_meta.get("language")
        if primary_lang:
            languages.append(primary_lang)

        for filename, lang in manifest_checks:
            if self.check_file_exists(org, repo, filename, ref=ref):
                manifests.append(filename)
                if lang not in languages:
                    languages.append(lang)

        # Quick peek at package.json or requirements.txt for key frameworks
        if "package.json" in manifests:
            pkg_content = self.get_file_content(org, repo, "package.json", ref=ref)
            if pkg_content:
                for kw in ["react", "next", "vue", "angular", "express", "nest"]:
                    if f'"{kw}"' in pkg_content.lower():
                        frameworks.append(kw.capitalize())

        if "requirements.txt" in manifests or "pyproject.toml" in manifests:
            req_content = (
                self.get_file_content(org, repo, "requirements.txt", ref=ref)
                or self.get_file_content(org, repo, "pyproject.toml", ref=ref)
                or ""
            )
            for kw in ["fastapi", "django", "flask", "pydantic", "pytest", "sqlalchemy"]:
                if kw in req_content.lower():
                    frameworks.append(kw.capitalize())

        return {
            "languages": languages or ["General Software"],
            "manifests": manifests,
            "frameworks": frameworks,
        }

