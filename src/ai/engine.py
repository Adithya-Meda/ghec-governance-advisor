"""Enterprise AI Synthesis & Remediation Engine.

Supports multiple LLM providers:
1. Google GenAI (Gemini) - native SDK integration
2. OpenAI / Azure OpenAI - standard REST Chat Completions
3. Anthropic (Claude) - standard REST Messages API

Capabilities:
- Synthesize Executive Risk Briefings from multi-repository audit findings.
- Tailor remediation snippets (Copilot instructions, DevContainers, Dependabot)
  specifically to each repository's detected language and framework stack.
- Sanitize all prompt inputs to prevent credential or proprietary code leakage.
"""

from __future__ import annotations

import logging
import os
import re
import time
import warnings
from typing import Any, Dict, List, Optional, Tuple

# Suppress noisy internal warnings from third-party client
warnings.filterwarnings("ignore", message=".*automatic function calling.*")
warnings.filterwarnings("ignore", category=UserWarning, module="google")

from ..checks.base import CheckResult, CheckStatus

logger = logging.getLogger(__name__)


class AIEngine:
    """Safe, resilient multi-provider LLM integration for governance analysis and remediation."""

    SENSITIVE_PATTERN = re.compile(
        r"(ghp_[a-zA-Z0-9]{36}|ghs_[a-zA-Z0-9]{36}|-----BEGIN[^\-]+-----|bearer\s+[a-zA-Z0-9_\-\.]+)",
        re.IGNORECASE,
    )

    FALLBACK_MODELS_BY_PROVIDER: Dict[str, Tuple[str, ...]] = {
        "gemini": (
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ),
        "openai": (
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
        ),
        "anthropic": (
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-haiku-20240307",
        ),
    }

    # Backward compatibility alias for Gemini callers
    FALLBACK_MODELS = FALLBACK_MODELS_BY_PROVIDER["gemini"]

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-3.5-flash",
        provider: str = "gemini",
        enabled: bool = True,
        base_url: str = "",
    ) -> None:
        """Initialize AI Engine with multi-provider routing.

        Args:
            api_key: API Key for the target provider (optional).
            model_name: Target model identifier (e.g. gemini-3.5-flash, gpt-4o, claude-3-5-sonnet-20241022).
            provider: LLM provider name ("gemini", "openai", "azure", "anthropic").
            enabled: Master toggle for AI capabilities.
            base_url: Custom API endpoint base URL (optional, for Azure / proxies).
        """
        self.api_key = (api_key or "").strip()
        if self.api_key.startswith("${") and self.api_key.endswith("}"):
            self.api_key = ""

        # Auto-infer provider if model name strongly indicates it
        prov = (provider or "").strip().lower()
        model_lower = (model_name or "").lower()
        if not prov or prov == "auto":
            if model_lower.startswith(("gpt-", "o1", "o3", "chatgpt-")):
                prov = "openai"
            elif model_lower.startswith("claude-"):
                prov = "anthropic"
            else:
                prov = "gemini"
        self.provider = prov

        # Default model per provider if unspecified
        if not model_name:
            if self.provider in ("openai", "azure"):
                self.model_name = "gpt-4o"
            elif self.provider == "anthropic":
                self.model_name = "claude-3-5-sonnet-20241022"
            else:
                self.model_name = "gemini-3.5-flash"
        else:
            self.model_name = model_name

        self.enabled = enabled and bool(self.api_key)
        self.base_url = (base_url or "").strip()
        self._client: Optional[Any] = None
        self._gen_config: Optional[Any] = None
        self._remediation_cache: Dict[str, str] = {}
        self.init_error: Optional[str] = None

        if self.enabled:
            if self.provider == "gemini":
                try:
                    from google import genai
                    from google.genai import types

                    self._client = genai.Client(api_key=self.api_key)
                    self._gen_config = types.GenerateContentConfig(
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    )
                    logger.info("AI Engine initialized using Gemini (model: %s)", self.model_name)
                except Exception as err:
                    logger.warning("Could not initialize Google GenAI client: %s. Falling back to deterministic mode.", err)
                    self.init_error = f"Package initialization failed: {err}"
                    self.enabled = False
            elif self.provider in ("openai", "azure"):
                logger.info("AI Engine initialized using OpenAI / Azure (model: %s)", self.model_name)
            elif self.provider == "anthropic":
                logger.info("AI Engine initialized using Anthropic (model: %s)", self.model_name)
            else:
                logger.warning("Unsupported LLM provider '%s'. Falling back to deterministic mode.", self.provider)
                self.enabled = False

    def is_available(self) -> bool:
        """Return True if AI engine is configured and ready."""
        if not self.enabled or not self.api_key:
            return False
        if self.provider == "gemini":
            return self._client is not None
        return True

    def verify_connection(self) -> tuple[bool, str]:
        """Perform an active pre-flight connectivity and credential check with model fallback."""
        if not self.enabled or not self.api_key:
            key_name = (
                "OPENAI_API_KEY" if self.provider in ("openai", "azure")
                else "ANTHROPIC_API_KEY" if self.provider == "anthropic"
                else "GEMINI_API_KEY"
            )
            return False, f"{key_name} is not configured"

        if self.provider in ("openai", "azure"):
            return self._verify_openai()
        elif self.provider == "anthropic":
            return self._verify_anthropic()
        else:
            return self._verify_gemini()

    def _verify_gemini(self) -> tuple[bool, str]:
        """Verify Google Gemini connection and active model quota."""
        if not self._client:
            return False, "Google GenAI client not initialized"

        candidate_models = [self.model_name] + [
            m for m in self.FALLBACK_MODELS_BY_PROVIDER["gemini"] if m != self.model_name
        ]
        last_error = ""

        for candidate in candidate_models:
            try:
                kwargs: Dict[str, Any] = {
                    "model": candidate,
                    "contents": "ping",
                }
                if self._gen_config is not None:
                    kwargs["config"] = self._gen_config

                self._client.models.generate_content(**kwargs)
                if candidate != self.model_name:
                    logger.info(
                        "Primary model '%s' unavailable. Seamlessly fell back to '%s'.",
                        self.model_name,
                        candidate,
                    )
                    self.model_name = candidate
                return True, "OK"
            except Exception as err:
                err_msg = str(err)
                last_error = err_msg
                if "API_KEY_INVALID" in err_msg or "UNAUTHENTICATED" in err_msg:
                    self.enabled = False
                    return False, "API Key Invalid or Expired"
                continue

        if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error:
            reason = "Quota exhausted / Rate limit reached on candidate models"
        elif "404" in last_error or "NOT_FOUND" in last_error:
            reason = f"Models {candidate_models} not found or inaccessible"
        else:
            reason = f"Connection error ({last_error[:60]})"
        self.enabled = False
        return False, reason

    def _verify_openai(self) -> tuple[bool, str]:
        """Verify OpenAI connection and active model quota via REST API."""
        import requests

        base_url = self.base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }
        candidate_models = [self.model_name] + [
            m for m in self.FALLBACK_MODELS_BY_PROVIDER["openai"] if m != self.model_name
        ]
        last_error = ""

        for candidate in candidate_models:
            try:
                payload = {
                    "model": candidate,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=10)
                if resp.status_code == 200:
                    if candidate != self.model_name:
                        logger.info(
                            "Primary model '%s' unavailable. Seamlessly fell back to '%s'.",
                            self.model_name,
                            candidate,
                        )
                        self.model_name = candidate
                    return True, "OK"
                elif resp.status_code in (401, 403):
                    self.enabled = False
                    return False, "API Key Invalid or Expired"
                elif resp.status_code == 429:
                    last_error = "Quota exhausted / Rate limit reached on candidate models"
                    continue
                elif resp.status_code == 404:
                    last_error = f"Model {candidate} not found"
                    continue
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:50]}"
            except Exception as err:
                last_error = str(err)
                continue

        self.enabled = False
        return False, last_error or "OpenAI connection failed"

    def _verify_anthropic(self) -> tuple[bool, str]:
        """Verify Anthropic connection and active model quota via REST API."""
        import requests

        base_url = self.base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
        url = f"{base_url.rstrip('/')}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        candidate_models = [self.model_name] + [
            m for m in self.FALLBACK_MODELS_BY_PROVIDER["anthropic"] if m != self.model_name
        ]
        last_error = ""

        for candidate in candidate_models:
            try:
                payload = {
                    "model": candidate,
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "ping"}],
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=10)
                if resp.status_code == 200:
                    if candidate != self.model_name:
                        logger.info(
                            "Primary model '%s' unavailable. Seamlessly fell back to '%s'.",
                            self.model_name,
                            candidate,
                        )
                        self.model_name = candidate
                    return True, "OK"
                elif resp.status_code in (401, 403):
                    self.enabled = False
                    return False, "API Key Invalid or Expired"
                elif resp.status_code == 429:
                    last_error = "Quota exhausted / Rate limit reached on candidate models"
                    continue
                elif resp.status_code == 404:
                    last_error = f"Model {candidate} not found"
                    continue
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:50]}"
            except Exception as err:
                last_error = str(err)
                continue

        self.enabled = False
        return False, last_error or "Anthropic connection failed"

    def sanitize_text(self, text: str) -> str:
        """Redact sensitive tokens and key patterns before sending to LLM."""
        return self.SENSITIVE_PATTERN.sub("[REDACTED_CREDENTIAL]", text)

    def _call_gemini(self, prompt: str, retry_on_rate_limit: bool = True) -> Optional[str]:
        """Execute Gemini call with resilient rate-limit handling and safe model fallback."""
        if not self.is_available():
            return None

        candidate_models = [self.model_name] + [
            m for m in self.FALLBACK_MODELS_BY_PROVIDER["gemini"] if m != self.model_name
        ]

        for model in candidate_models:
            for attempt in range(2 if retry_on_rate_limit else 1):
                try:
                    kwargs: Dict[str, Any] = {
                        "model": model,
                        "contents": self.sanitize_text(prompt),
                    }
                    if self._gen_config is not None:
                        kwargs["config"] = self._gen_config

                    response = self._client.models.generate_content(**kwargs)
                    if response and response.text:
                        if model != self.model_name:
                            self.model_name = model
                        return response.text.strip()
                    return None
                except Exception as err:
                    err_msg = str(err)
                    if "API_KEY_INVALID" in err_msg or "UNAUTHENTICATED" in err_msg:
                        logger.warning("AI engine suspended (API Key Invalid). Falling back to deterministic templates.")
                        self.enabled = False
                        return None
                    elif "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg or "503" in err_msg:
                        if attempt == 0:
                            time.sleep(1)
                            continue
                        break  # try next fallback model
                    elif "NOT_FOUND" in err_msg or "404" in err_msg:
                        break  # try next fallback model
                    else:
                        logger.debug("AI generation skipped on %s for check: %s", model, err)
                        break
        return None

    def _call_openai(self, prompt: str, retry_on_rate_limit: bool = True) -> Optional[str]:
        """Execute OpenAI Chat Completion API call with model fallback."""
        if not self.is_available():
            return None

        import requests

        base_url = self.base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }
        candidates = [self.model_name] + [
            m for m in self.FALLBACK_MODELS_BY_PROVIDER["openai"] if m != self.model_name
        ]

        for model in candidates:
            for attempt in range(2 if retry_on_rate_limit else 1):
                try:
                    payload = {
                        "model": model,
                        "messages": [{"role": "user", "content": self.sanitize_text(prompt)}],
                        "temperature": 0.2,
                    }
                    resp = requests.post(url, headers=headers, json=payload, timeout=30)
                    if resp.status_code == 200:
                        data = resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            if model != self.model_name:
                                self.model_name = model
                            content = choices[0].get("message", {}).get("content", "")
                            return content.strip() if content else None
                        return None
                    elif resp.status_code in (401, 403):
                        logger.warning("OpenAI API Key Invalid or Unauthenticated. Falling back to deterministic mode.")
                        self.enabled = False
                        return None
                    elif resp.status_code == 429:
                        if attempt == 0:
                            time.sleep(1)
                            continue
                        break
                    elif resp.status_code == 404:
                        break
                    else:
                        logger.debug("OpenAI API returned status %s for %s", resp.status_code, model)
                        break
                except Exception as err:
                    logger.debug("OpenAI API call failed on model %s: %s", model, err)
                    break
        return None

    def _call_anthropic(self, prompt: str, retry_on_rate_limit: bool = True) -> Optional[str]:
        """Execute Anthropic Messages API call with model fallback."""
        if not self.is_available():
            return None

        import requests

        base_url = self.base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
        url = f"{base_url.rstrip('/')}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        candidates = [self.model_name] + [
            m for m in self.FALLBACK_MODELS_BY_PROVIDER["anthropic"] if m != self.model_name
        ]

        for model in candidates:
            for attempt in range(2 if retry_on_rate_limit else 1):
                try:
                    payload = {
                        "model": model,
                        "max_tokens": 2048,
                        "messages": [{"role": "user", "content": self.sanitize_text(prompt)}],
                        "temperature": 0.2,
                    }
                    resp = requests.post(url, headers=headers, json=payload, timeout=30)
                    if resp.status_code == 200:
                        data = resp.json()
                        contents = data.get("content", [])
                        if contents:
                            if model != self.model_name:
                                self.model_name = model
                            text = contents[0].get("text", "")
                            return text.strip() if text else None
                        return None
                    elif resp.status_code in (401, 403):
                        logger.warning("Anthropic API Key Invalid or Unauthenticated. Falling back to deterministic mode.")
                        self.enabled = False
                        return None
                    elif resp.status_code == 429:
                        if attempt == 0:
                            time.sleep(1)
                            continue
                        break
                    elif resp.status_code == 404:
                        break
                    else:
                        logger.debug("Anthropic API returned status %s for %s", resp.status_code, model)
                        break
                except Exception as err:
                    logger.debug("Anthropic API call failed on model %s: %s", model, err)
                    break
        return None

    def _generate_text(self, prompt: str, retry_on_rate_limit: bool = True) -> Optional[str]:
        """Route text generation to the active LLM provider."""
        if not self.is_available():
            return None
        if self.provider in ("openai", "azure"):
            return self._call_openai(prompt, retry_on_rate_limit=retry_on_rate_limit)
        elif self.provider == "anthropic":
            return self._call_anthropic(prompt, retry_on_rate_limit=retry_on_rate_limit)
        else:
            return self._call_gemini(prompt, retry_on_rate_limit=retry_on_rate_limit)

    def generate_executive_summary(self, results: List[CheckResult], org_name: str) -> str:
        """Synthesize a high-level executive risk and governance narrative."""
        if not self.is_available():
            return ""

        total = len(results)
        passed = sum(1 for r in results if r.status == CheckStatus.PASS)
        warned = sum(1 for r in results if r.status == CheckStatus.WARN)
        failed = sum(1 for r in results if r.status == CheckStatus.FAIL)

        # Extract top failure categories and check names
        failed_checks = [f"- [{r.category}] {r.repo_name}: {r.check_name} ({r.current_state})" for r in results if r.status == CheckStatus.FAIL][:12]
        warned_checks = [f"- [{r.category}] {r.repo_name}: {r.check_name}" for r in results if r.status == CheckStatus.WARN][:8]

        prompt = f"""You are a Principal Cloud Security and DevOps Architect auditing GitHub Enterprise Cloud.
Analyze these audit findings for organization '{self.sanitize_text(org_name)}' and synthesize a concise, high-impact Executive Risk Briefing.

METRICS:
- Total Checks: {total}
- Passing: {passed}
- Warnings: {warned}
- Critical Failures / Action Required: {failed}

HIGH RISK / FAILED CHECKS:
{chr(10).join(failed_checks) if failed_checks else 'None'}

WARNINGS:
{chr(10).join(warned_checks) if warned_checks else 'None'}

FORMAT YOUR RESPONSE IN 2-3 CONCISE MARKDOWN PARAGRAPHS:
1. Executive Risk Summary: Overall posture, score evaluation, and primary governance gaps.
2. Supply-Chain & Critical Vulnerability Vectors: Specifically calling out risks from unpinned actions, missing rulesets, or exposed secrets.
3. Strategic 30-Day Remediation Plan: High-priority immediate fixes for the platform team.
Keep it factual, authoritative, professional, and actionable. Do not use filler or platitudes."""

        summary = self._generate_text(prompt)
        return summary or ""

    def enrich_remediation(self, result: CheckResult, tech_stack: Dict[str, Any]) -> None:
        """Generate tailored remediation snippets based on repository tech stack."""
        if not self.is_available() or result.status not in (CheckStatus.WARN, CheckStatus.FAIL):
            return

        # Target checks where AI context adds major value
        supported_checks = (
            "copilot_instructions",
            "devcontainers",
            "dependabot_configuration",
            "workflow_sha_pinning",
            "workflow_concurrency_groups",
            "codeowners_validation",
            "pull_request_templates",
            "issue_templates",
            "pre_commit_hooks",
        )
        if result.check_id not in supported_checks:
            return

        languages = ", ".join(tech_stack.get("languages", [])) or "General Software"
        frameworks = ", ".join(tech_stack.get("frameworks", [])) or "Standard"
        manifests = ", ".join(tech_stack.get("manifests", [])) or "None"

        prompt = f"""You are a Senior DevOps Engineer. Generate a production-ready, custom-tailored configuration snippet to remediate this finding:

REPOSITORY CONTEXT:
- Repository: {self.sanitize_text(result.repo_name)}
- Detected Languages: {self.sanitize_text(languages)}
- Detected Frameworks/Libraries: {self.sanitize_text(frameworks)}
- Build/Config Manifests Found: {self.sanitize_text(manifests)}

AUDIT FINDING:
- Check: {result.check_name}
- Problem: {result.current_state}
- Recommended Goal: {result.recommended_state}

TASK:
Provide ONLY the exact, tailored configuration file content to resolve this for this specific tech stack.
- For 'copilot_instructions': Write a customized .github/copilot-instructions.md with team style rules, testing conventions, and safety guidelines specific to {languages}.
- For 'devcontainers': Provide a complete, valid .devcontainer/devcontainer.json configured with the right runtime container image, port forwards, and VS Code extensions for {languages} and {frameworks}.
- For 'dependabot_configuration': Provide a valid .github/dependabot.yml covering all detected package ecosystems ({manifests}).
- For 'workflow_concurrency_groups': Provide the exact GitHub Actions YAML 'concurrency' block configured with cancel-in-progress for PR branches.
- For 'codeowners_validation': Provide a complete, production-ready .github/CODEOWNERS defining granular team ownership for this tech stack.
- For 'pull_request_templates': Provide a comprehensive .github/PULL_REQUEST_TEMPLATE.md checklist (tests, docs, security) tailored to {languages}.
- For 'pre_commit_hooks': Provide a valid .pre-commit-config.yaml with modern linting and formatting hooks for {languages}.
- For 'issue_templates': Provide a YAML issue template (.github/ISSUE_TEMPLATE/bug_report.yml) configured for {languages}.

Output ONLY the code/configuration snippet inside code fences. Do not add introductory or concluding chat."""

        cache_key = f"{result.check_id}:{languages}:{frameworks}:{manifests}"
        if cache_key in self._remediation_cache:
            cleaned_text = self._remediation_cache[cache_key]
        else:
            text = self._generate_text(prompt)
            if not text:
                return
            cleaned_text = text.strip()
            # Remove wrapping markdown fences if present for cleaner diff display
            if cleaned_text.startswith("```"):
                lines = cleaned_text.splitlines()
                if len(lines) >= 2 and lines[-1].startswith("```"):
                    cleaned_text = "\n".join(lines[1:-1])
            self._remediation_cache[cache_key] = cleaned_text

        result.remediation_snippet_after = (
            f"# [AI Tailored for {languages}]\n"
            f"# ADVISORY ONLY: Review, test, and validate in non-production environments before applying.\n"
            f"{cleaned_text}"
        )
        result.extra_details["ai_enriched"] = True
        result.extra_details["detected_stack"] = languages
        result.extra_details["ai_model"] = self.model_name
        result.extra_details["ai_provider"] = self.provider
