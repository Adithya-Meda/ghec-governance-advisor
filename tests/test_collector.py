"""Unit tests for GHECClient and RepoInspector."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from src.collector.client import GHECClient
from src.collector.repo_inspector import RepoInspector


@pytest.fixture
def mock_client() -> GHECClient:
    auth = MagicMock()
    auth.api_base_url = "https://api.github.com"
    auth.get_auth_headers.return_value = {"Authorization": "Bearer mock_token"}
    return GHECClient(auth=auth, timeout_seconds=10)


def test_client_get_success(mock_client: GHECClient) -> None:
    """Test successful GET request."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"x-ratelimit-remaining": "4990"}
    mock_resp.json.return_value = {"id": 1234, "name": "sample-repo"}

    with patch.object(mock_client.session, "get", return_value=mock_resp):
        res = mock_client.get("/repos/org/sample-repo")
        assert res["name"] == "sample-repo"


def test_client_get_404_allowed(mock_client: GHECClient) -> None:
    """Test 404 handling when allow_404=True."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.headers = {}

    with patch.object(mock_client.session, "get", return_value=mock_resp):
        res = mock_client.get("/repos/org/non-existent", allow_404=True)
        assert res is None


@patch("time.sleep")
def test_client_secondary_rate_limit_retry(mock_sleep: MagicMock, mock_client: GHECClient) -> None:
    """Verify that secondary rate limits (403/429) automatically back off and retry."""
    # First attempt: 403 secondary rate limit with Retry-After: 1
    resp_rate_limited = MagicMock()
    resp_rate_limited.status_code = 403
    resp_rate_limited.text = "You have exceeded a secondary rate limit. Please wait."
    resp_rate_limited.headers = {"retry-after": "1"}

    # Second attempt: 200 OK
    resp_success = MagicMock()
    resp_success.status_code = 200
    resp_success.headers = {"x-ratelimit-remaining": "4500"}
    resp_success.json.return_value = {"id": 999, "name": "recovered-repo"}

    with patch.object(mock_client.session, "get", side_effect=[resp_rate_limited, resp_success]):
        res = mock_client.get("/repos/org/recovered-repo")
        assert res["name"] == "recovered-repo"
        assert mock_sleep.called



def test_client_pagination(mock_client: GHECClient) -> None:
    """Test pagination helper aggregates multi-page results."""
    page1 = [{"id": 1}, {"id": 2}]
    page2 = [{"id": 3}]

    with patch.object(mock_client, "get", side_effect=[page1, page2]):
        items = mock_client.list_paginated("/orgs/test/repos", per_page=2, max_pages=2)
        assert len(items) == 3


def test_repo_inspector_file_content(mock_client: GHECClient) -> None:
    """Test base64 file content retrieval in RepoInspector."""
    inspector = RepoInspector(client=mock_client)

    # Base64 string for "hello world"
    mock_data = {
        "content": "aGVsbG8gd29ybGQ=",
        "encoding": "base64",
    }
    with patch.object(mock_client, "get", return_value=mock_data):
        content = inspector.get_file_content("org", "repo", "README.md")
        assert content == "hello world"


def test_repo_inspector_file_exists(mock_client: GHECClient) -> None:
    """Test check_file_exists returns True when endpoint returns data."""
    inspector = RepoInspector(client=mock_client)

    with patch.object(mock_client, "get", return_value={"type": "file"}):
        assert inspector.check_file_exists("org", "repo", ".devcontainer.json") is True

    with patch.object(mock_client, "get", return_value=None):
        assert inspector.check_file_exists("org", "repo", ".missing") is False


def test_list_installation_repositories(mock_client: GHECClient) -> None:
    """Test auto-discovery of repositories via App installation."""
    inspector = RepoInspector(client=mock_client)
    mock_payload = {
        "total_count": 2,
        "repositories": [
            {"name": "service-a", "owner": {"login": "fintech-core"}, "default_branch": "main"},
            {"name": "service-b", "owner": {"login": "fintech-core"}, "default_branch": "develop"},
        ],
    }

    with patch.object(mock_client, "get", return_value=mock_payload):
        repos = inspector.list_installation_repositories()
        assert len(repos) == 2
        assert repos[0]["name"] == "service-a"
        assert repos[1]["default_branch"] == "develop"


def test_detect_tech_stack_optimized_root_listing(mock_client: GHECClient) -> None:
    """Test detect_tech_stack identifies tech stack from single root contents call."""
    inspector = RepoInspector(client=mock_client)

    def mock_get(path, *args, **kwargs):
        if path == "/repos/org/repo":
            return {"language": "Python"}
        if path == "/repos/org/repo/contents":
            return [
                {"name": "requirements.txt", "type": "file"},
                {"name": "Dockerfile", "type": "file"},
                {"name": "README.md", "type": "file"},
            ]
        if path == "/repos/org/repo/contents/requirements.txt":
            import base64
            return {"content": base64.b64encode(b"fastapi==0.110.0\nuvicorn\n").decode("utf-8"), "encoding": "base64"}
        return None

    with patch.object(mock_client, "get", side_effect=mock_get):
        stack = inspector.detect_tech_stack("org", "repo")
        assert "Python" in stack["languages"]
        assert "Docker" in stack["languages"]
        assert "requirements.txt" in stack["manifests"]
        assert "Dockerfile" in stack["manifests"]
        assert "Fastapi" in stack["frameworks"]

