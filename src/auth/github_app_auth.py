"""GitHub App Authentication Manager.

Handles RS256 JWT generation and Installation Access Token retrieval
for GitHub Enterprise Cloud (GHEC) instances without leaking credentials.
"""

from __future__ import annotations

import base64
import email.utils
import logging
import os
import time
from typing import Any, Dict, List, Optional
import jwt
import requests

logger = logging.getLogger(__name__)


class GitHubAppAuth:
    """Manages secure token generation and caching for GitHub Apps."""

    def __init__(
        self,
        app_id: int | str,
        installation_id: Optional[int | str] = None,
        private_key: str = "",
        api_base_url: str = "https://api.github.com",
    ) -> None:
        """Initialize GitHub App Auth.

        Args:
            app_id: Numeric GitHub App ID.
            installation_id: Numeric Installation ID (optional; auto-discovered if omitted).
            private_key: Path to PEM file, or raw PEM string content.
            api_base_url: Base API URL for GHEC (defaults to https://api.github.com).
        """
        self.app_id = int(app_id)
        self.installation_id = int(installation_id) if installation_id else None
        self.api_base_url = api_base_url.rstrip("/")
        self._private_key_pem = self._load_private_key(private_key)
        self._cached_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._clock_skew: float = self._calculate_clock_skew()

    def set_installation_id(self, installation_id: int | str) -> None:
        """Set or update the active installation ID."""
        self.installation_id = int(installation_id)
        self._cached_token = None
        self._token_expires_at = 0.0

    def discover_installations(self) -> List[Dict[str, Any]]:
        """List all active installations of this GitHub App using JWT auth.

        Returns:
            List of installation dictionaries from GitHub API.
        """
        jwt_token = self.generate_jwt()
        endpoint = f"{self.api_base_url}/app/installations"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GHEC-Governance-Advisor/1.0",
        }
        try:
            response = requests.get(endpoint, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as err:
            logger.error("Failed to list GitHub App installations: %s", err)
            return []

    def _calculate_clock_skew(self) -> float:
        """Calculate clock skew between local machine and GitHub API server.

        Prevents 401 Unauthorized errors caused by local machine clock drift.
        """
        try:
            resp = requests.head(self.api_base_url, timeout=5)
            server_date = resp.headers.get("Date")
            if server_date:
                server_timestamp = email.utils.parsedate_to_datetime(server_date).timestamp()
                skew = time.time() - server_timestamp
                if abs(skew) > 15:
                    logger.info("Adjusted for local clock skew relative to GitHub: %.1f seconds", skew)
                return skew
        except Exception as err:
            logger.debug("Could not determine GitHub server clock skew: %s", err)
        return 0.0

    @staticmethod
    def _load_private_key(key_input: str) -> str:
        """Load private key from file path or raw string with safe validation.

        Args:
            key_input: File path or raw PEM/base64 string.

        Returns:
            Validated PEM private key string.
        """
        # If input points to an existing file, read it
        if os.path.isfile(key_input):
            try:
                with open(key_input, "r", encoding="utf-8") as key_file:
                    content = key_file.read().strip()
            except Exception as err:
                raise ValueError(f"Failed to read private key file: {err}") from err
        else:
            content = key_input.strip()

        # Handle base64 encoded private keys (common in CI/CD secrets)
        if not content.startswith("-----BEGIN"):
            try:
                decoded = base64.b64decode(content).decode("utf-8").strip()
                if decoded.startswith("-----BEGIN"):
                    content = decoded
            except Exception:
                pass  # Fall back to content as-is

        if "-----BEGIN" not in content or "PRIVATE KEY-----" not in content:
            raise ValueError(
                "Invalid private key format. Must be an RSA/PKCS#8 PEM private key."
            )

        return content

    def generate_jwt(self, expiration_seconds: int = 540) -> str:
        """Generate a short-lived JSON Web Token signed with RS256.

        Args:
            expiration_seconds: JWT lifetime in seconds (max 600, default 540 / 9 mins).

        Returns:
            Encoded JWT string.
        """
        # Adjust timestamp using server clock skew to guarantee 'iat' is valid for GitHub
        now = int(time.time() - self._clock_skew)
        # GitHub allows a 60 second clock drift leeway
        payload = {
            "iat": now - 60,
            "exp": now + expiration_seconds,
            "iss": str(self.app_id),
        }
        encoded_jwt = jwt.encode(
            payload,
            self._private_key_pem,
            algorithm="RS256",
        )
        return encoded_jwt

    def get_installation_token(self, force_refresh: bool = False) -> str:
        """Obtain a valid installation access token, using cache if still valid.

        Args:
            force_refresh: Whether to bypass cache and request a fresh token.

        Returns:
            Bearer token string (starts with 'ghs_').
        """
        now = time.time()
        # Use cached token if valid for at least 5 more minutes
        if (
            not force_refresh
            and self._cached_token
            and (self._token_expires_at - now) > 300
        ):
            return self._cached_token

        # Auto-discover installation ID if not explicitly specified
        if not self.installation_id:
            installations = self.discover_installations()
            if not installations:
                raise RuntimeError(
                    f"No active installations found for GitHub App ID {self.app_id}. "
                    "Ensure an Organization Owner has installed the App on your GitHub organization."
                )
            self.set_installation_id(installations[0]["id"])

        jwt_token = self.generate_jwt()
        endpoint = f"{self.api_base_url}/app/installations/{self.installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            response = requests.post(endpoint, headers=headers, timeout=15)
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
            self._cached_token = data["token"]
            # Typically valid for 1 hour (3600 seconds)
            self._token_expires_at = now + 3500
            return self._cached_token
        except requests.exceptions.RequestException as err:
            details = ""
            if getattr(err, "response", None) is not None:
                details = f" - Details: {err.response.text}"
            logger.error(
                "Failed to obtain installation token for App ID %s and Installation ID %s%s",
                self.app_id,
                self.installation_id,
                details,
            )
            raise RuntimeError(
                f"GitHub App token exchange failed: {err}{details}"
            ) from err

    def get_auth_headers(self) -> Dict[str, str]:
        """Return standardized authorization headers for GHEC API requests."""
        token = self.get_installation_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GHEC-Governance-Advisor/1.0",
        }

    def __repr__(self) -> str:
        """Safe representation redacting sensitive credentials."""
        return (
            f"<GitHubAppAuth app_id={self.app_id} "
            f"installation_id={self.installation_id} "
            f"endpoint={self.api_base_url} (credentials redacted)>"
        )
