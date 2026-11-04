"""Unit tests for the Enterprise AI Synthesis & Remediation Engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ai.engine import AIEngine
from src.checks.base import CheckResult, CheckSeverity, CheckStatus, Persona


def test_ai_disabled_when_no_api_key() -> None:
    """Verify AI Engine disables cleanly when API key is missing."""
    engine = AIEngine(api_key="", enabled=True)
    assert not engine.is_available()
    assert engine.generate_executive_summary([], "test-org") == ""


def test_ai_disabled_when_toggle_false() -> None:
    """Verify AI Engine disables when master enabled toggle is False."""
    engine = AIEngine(api_key="dummy_key", enabled=False)
    assert not engine.is_available()


def test_sanitize_text() -> None:
    """Verify credential and token sanitization regex."""
    engine = AIEngine(api_key="", enabled=False)

    text_with_ghp = "Found leaked token: ghp_123456789012345678901234567890123456 in repo"
    sanitized = engine.sanitize_text(text_with_ghp)
    assert "ghp_" not in sanitized
    assert "[REDACTED_CREDENTIAL]" in sanitized

    text_with_bearer = "Authorization: Bearer my-secret-jwt-token-value"
    sanitized_bearer = engine.sanitize_text(text_with_bearer)
    assert "my-secret-jwt-token-value" not in sanitized_bearer
    assert "[REDACTED_CREDENTIAL]" in sanitized_bearer


@patch("google.genai.Client")
def test_generate_executive_summary_success(mock_client_cls: MagicMock) -> None:
    """Verify executive summary generation with mocked Gemini client."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = "### Executive Risk Briefing\nOverall posture is strong with 1 critical gap."
    mock_client.models.generate_content.return_value = mock_response

    engine = AIEngine(api_key="valid-mock-key", enabled=True)
    assert engine.is_available()

    results = [
        CheckResult(
            check_id="branch_rulesets",
            check_name="Branch Protection Rulesets",
            category="Security",
            persona=Persona.REPO_ADMIN,
            severity=CheckSeverity.CRITICAL,
            status=CheckStatus.FAIL,
            org_name="my-org",
            repo_name="core-service",
            current_state="No ruleset",
            recommended_state="Require 2 approvals",
            explanation="Add branch ruleset",
        ),
        CheckResult(
            check_id="copilot_instructions",
            check_name="GitHub Copilot Instructions",
            category="Developer Experience",
            persona=Persona.CONTRIBUTOR,
            severity=CheckSeverity.LOW,
            status=CheckStatus.WARN,
            org_name="my-org",
            repo_name="core-service",
            current_state="Missing",
            recommended_state="Add instructions",
            explanation="Create .github/copilot-instructions.md",
        ),
    ]

    summary = engine.generate_executive_summary(results, org_name="my-org")
    assert "Executive Risk Briefing" in summary
    assert mock_client.models.generate_content.called


@patch("google.genai.Client")
def test_enrich_remediation_success(mock_client_cls: MagicMock) -> None:
    """Verify remediation enrichment tailoring for specific tech stack."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = "```markdown\n# Custom Copilot Instructions for Python / FastAPI\n- Use type hints\n```"
    mock_client.models.generate_content.return_value = mock_response

    engine = AIEngine(api_key="valid-mock-key", enabled=True)

    result = CheckResult(
        check_id="copilot_instructions",
        check_name="GitHub Copilot Instructions",
        category="Developer Experience",
        persona=Persona.CONTRIBUTOR,
        severity=CheckSeverity.LOW,
        status=CheckStatus.WARN,
        org_name="my-org",
        repo_name="fastapi-backend",
        current_state="Missing",
        recommended_state="Add instructions",
        explanation="Create .github/copilot-instructions.md",
    )

    tech_stack = {
        "languages": ["Python"],
        "frameworks": ["FastAPI", "Pydantic"],
        "manifests": ["pyproject.toml"],
    }

    engine.enrich_remediation(result, tech_stack)
    assert result.extra_details.get("ai_enriched") is True
    assert "Custom Copilot Instructions" in result.remediation_snippet_after
    assert "# [AI Tailored" not in result.remediation_snippet_after
    assert "# ADVISORY ONLY:" not in result.remediation_snippet_after


def test_enrich_remediation_skips_passing_or_unsupported() -> None:
    """Verify enrichment does nothing for PASS checks or checks outside AI scope."""
    engine = AIEngine(api_key="valid-mock-key", enabled=True)

    # 1. PASS status check
    passing_result = CheckResult(
        check_id="copilot_instructions",
        check_name="GitHub Copilot Instructions",
        category="Developer Experience",
        persona=Persona.CONTRIBUTOR,
        severity=CheckSeverity.LOW,
        status=CheckStatus.PASS,
        org_name="my-org",
        repo_name="test-repo",
        current_state="Present",
        recommended_state="Present",
        explanation="None",
    )
    engine.enrich_remediation(passing_result, {"languages": ["Python"]})
    assert "ai_enriched" not in passing_result.extra_details

    # 2. Check not targeted for AI file generation
    org_result = CheckResult(
        check_id="organization_rulesets",
        check_name="Organization-wide Rulesets",
        category="Governance",
        persona=Persona.ORG_ADMIN,
        severity=CheckSeverity.HIGH,
        status=CheckStatus.FAIL,
        org_name="my-org",
        repo_name="N/A",
        current_state="Missing",
        recommended_state="Configure ruleset",
        explanation="Configure in org settings",
    )
    engine.enrich_remediation(org_result, {})
    assert "ai_enriched" not in org_result.extra_details


@patch("google.genai.Client", side_effect=RuntimeError("Client failed to init"))
def test_ai_client_init_exception_fallback(mock_client_cls: MagicMock) -> None:
    """Verify AI Engine falls back gracefully if client init fails."""
    engine = AIEngine(api_key="valid-mock-key", enabled=True)
    assert not engine.is_available()


@patch("google.genai.Client")
def test_generate_executive_summary_api_error_fallback(mock_client_cls: MagicMock) -> None:
    """Verify summary generation returns empty string when API error occurs."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.models.generate_content.side_effect = RuntimeError("API quota exceeded")

    engine = AIEngine(api_key="valid-mock-key", enabled=True)
    summary = engine.generate_executive_summary([], "test-org")
    assert summary == ""


@patch("google.genai.Client")
def test_enrich_remediation_api_error_handled(mock_client_cls: MagicMock) -> None:
    """Verify remediation enrichment fails silently when API error occurs."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.models.generate_content.side_effect = RuntimeError("API timeout")

    engine = AIEngine(api_key="valid-mock-key", enabled=True)
    result = CheckResult(
        check_id="copilot_instructions",
        check_name="GitHub Copilot Instructions",
        category="Developer Experience",
        persona=Persona.CONTRIBUTOR,
        severity=CheckSeverity.LOW,
        status=CheckStatus.WARN,
        org_name="my-org",
        repo_name="fastapi-backend",
        current_state="Missing",
        recommended_state="Add instructions",
        explanation="Create .github/copilot-instructions.md",
    )
    engine.enrich_remediation(result, {"languages": ["Python"]})
    assert "ai_enriched" not in result.extra_details


@patch("google.genai.Client")
def test_verify_connection_success(mock_client_cls: MagicMock) -> None:
    """Verify pre-flight healthcheck succeeds when API responds."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.models.generate_content.return_value = MagicMock(text="pong")

    engine = AIEngine(api_key="valid-key", enabled=True)
    is_ok, reason = engine.verify_connection()
    assert is_ok is True
    assert reason == "OK"


@patch("google.genai.Client")
def test_verify_connection_failure(mock_client_cls: MagicMock) -> None:
    """Verify pre-flight healthcheck detects invalid API key upfront."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.models.generate_content.side_effect = Exception("API_KEY_INVALID: Key not found")

    engine = AIEngine(api_key="bad-key", enabled=True)
    is_ok, reason = engine.verify_connection()
    assert is_ok is False
    assert "Invalid" in reason
    assert not engine.is_available()


def test_provider_auto_inference() -> None:
    """Verify provider inference based on model identifier."""
    engine_openai = AIEngine(api_key="key", model_name="gpt-4o", provider="auto", enabled=True)
    assert engine_openai.provider == "openai"
    assert engine_openai.is_available()

    engine_anthropic = AIEngine(api_key="key", model_name="claude-3-5-sonnet-20241022", provider="auto", enabled=True)
    assert engine_anthropic.provider == "anthropic"
    assert engine_anthropic.is_available()

    engine_gemini = AIEngine(api_key="key", model_name="gemini-3.5-flash", provider="auto", enabled=False)
    assert engine_gemini.provider == "gemini"


@patch("requests.post")
def test_openai_generation_and_verification(mock_post: MagicMock) -> None:
    """Verify OpenAI REST API call and connectivity verification."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "### OpenAI Executive Risk Briefing"}}]
    }
    mock_post.return_value = mock_resp

    engine = AIEngine(api_key="sk-mock-key", model_name="gpt-4o", provider="openai", enabled=True)
    assert engine.is_available()

    is_ok, reason = engine.verify_connection()
    assert is_ok is True
    assert reason == "OK"

    summary = engine.generate_executive_summary([], "fintech-org")
    assert "OpenAI Executive Risk Briefing" in summary


@patch("requests.post")
def test_anthropic_generation_and_verification(mock_post: MagicMock) -> None:
    """Verify Anthropic Messages REST API call and connectivity verification."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [{"text": "### Claude Executive Risk Briefing"}]
    }
    mock_post.return_value = mock_resp

    engine = AIEngine(
        api_key="sk-ant-mock-key",
        model_name="claude-3-5-sonnet-20241022",
        provider="anthropic",
        enabled=True,
    )
    assert engine.is_available()

    is_ok, reason = engine.verify_connection()
    assert is_ok is True
    assert reason == "OK"

    summary = engine.generate_executive_summary([], "fintech-org")
    assert "Claude Executive Risk Briefing" in summary


@patch("google.genai.Client")
def test_enrich_remediation_uses_cache(mock_client_cls: MagicMock) -> None:
    """Verify that remediation generation caches by check_id and tech stack to avoid redundant API calls."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.text = "```yaml\n# Cached Snippet\n```"
    mock_client.models.generate_content.return_value = mock_response

    engine = AIEngine(api_key="valid-mock-key", enabled=True)

    result1 = CheckResult(
        check_id="copilot_instructions",
        check_name="GitHub Copilot Instructions",
        category="Developer Experience",
        persona=Persona.CONTRIBUTOR,
        severity=CheckSeverity.LOW,
        status=CheckStatus.FAIL,
        org_name="my-org",
        repo_name="repo1",
        current_state="Missing",
        recommended_state="Present",
        explanation="Missing .github/copilot-instructions.md",
    )
    result2 = CheckResult(
        check_id="copilot_instructions",
        check_name="GitHub Copilot Instructions",
        category="Developer Experience",
        persona=Persona.CONTRIBUTOR,
        severity=CheckSeverity.LOW,
        status=CheckStatus.FAIL,
        org_name="my-org",
        repo_name="repo2",
        current_state="Missing",
        recommended_state="Present",
        explanation="Missing .github/copilot-instructions.md",
    )

    stack = {"languages": ["Python"], "frameworks": ["FastAPI"], "manifests": ["requirements.txt"]}
    engine.enrich_remediation(result1, stack)
    engine.enrich_remediation(result2, stack)

    # generate_content should have only been invoked ONCE due to caching
    assert mock_client.models.generate_content.call_count == 1
    assert result1.remediation_snippet_after == result2.remediation_snippet_after
    assert "# Cached Snippet" in result2.remediation_snippet_after


