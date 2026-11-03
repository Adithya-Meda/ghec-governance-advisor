"""Unit tests for GitHub App authentication and token management."""

import time
from unittest.mock import MagicMock, patch
import jwt
import pytest

from src.auth.github_app_auth import GitHubAppAuth


def test_auth_init_valid(test_rsa_key_pem: str) -> None:
    """Test successful initialization with valid PEM string."""
    auth = GitHubAppAuth(
        app_id=123456,
        installation_id=789012,
        private_key=test_rsa_key_pem,
        api_base_url="https://api.github.com",
    )
    assert auth.app_id == 123456
    assert auth.installation_id == 789012
    assert "credentials redacted" in repr(auth)


def test_auth_init_invalid_key() -> None:
    """Test error handling when private key format is malformed."""
    with pytest.raises(ValueError, match="Invalid private key format"):
        GitHubAppAuth(
            app_id=123,
            installation_id=456,
            private_key="INVALID_KEY_DATA",
        )


def test_jwt_generation(test_rsa_key_pem: str) -> None:
    """Verify that generated JWT has correct claims and can be decoded."""
    auth = GitHubAppAuth(
        app_id=99999,
        installation_id=11111,
        private_key=test_rsa_key_pem,
    )
    token = auth.generate_jwt(expiration_seconds=300)
    assert isinstance(token, str)

    # Decode without verifying signature to check payload
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["iss"] == "99999"
    assert decoded["exp"] > time.time()


@patch("requests.post")
def test_token_caching(mock_post: MagicMock, test_rsa_key_pem: str) -> None:
    """Ensure installation token is cached and reused until near expiry."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "token": "ghs_mock_token_1234567890",
        "expires_at": "2026-10-29T23:59:59Z",
    }
    mock_post.return_value = mock_response

    auth = GitHubAppAuth(
        app_id=123,
        installation_id=456,
        private_key=test_rsa_key_pem,
    )

    # First call triggers API request
    token1 = auth.get_installation_token()
    assert token1 == "ghs_mock_token_1234567890"
    assert mock_post.call_count == 1

    # Second call uses cache
    token2 = auth.get_installation_token()
    assert token2 == "ghs_mock_token_1234567890"
    assert mock_post.call_count == 1  # No second HTTP call

    headers = auth.get_auth_headers()
    assert headers["Authorization"] == "Bearer ghs_mock_token_1234567890"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


@patch("requests.get")
def test_discover_installations(mock_get: MagicMock, test_rsa_key_pem: str) -> None:
    """Verify listing installations via GitHub App JWT."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "id": 987654,
            "account": {"login": "enterprise-org", "type": "Organization"},
            "repository_selection": "all",
        }
    ]
    mock_get.return_value = mock_response

    auth = GitHubAppAuth(
        app_id=123,
        private_key=test_rsa_key_pem,
    )
    assert auth.installation_id is None

    installations = auth.discover_installations()
    assert len(installations) == 1
    assert installations[0]["id"] == 987654
    assert installations[0]["account"]["login"] == "enterprise-org"
    assert mock_get.called


@patch("requests.get")
@patch("requests.post")
def test_auto_discover_during_token_exchange(mock_post: MagicMock, mock_get: MagicMock, test_rsa_key_pem: str) -> None:
    """Verify that omitting installation_id auto-discovers and exchanges token."""
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = [
        {"id": 555666, "account": {"login": "auto-org"}, "repository_selection": "all"}
    ]
    mock_get.return_value = mock_get_resp

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {"token": "ghs_auto_discovered_token"}
    mock_post.return_value = mock_post_resp

    auth = GitHubAppAuth(app_id=123, private_key=test_rsa_key_pem)
    token = auth.get_installation_token()
    assert token == "ghs_auto_discovered_token"
    assert auth.installation_id == 555666

