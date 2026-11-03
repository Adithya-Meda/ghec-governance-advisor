"""Centralized Credential and Configuration Management for GHEC Advisor.

Enables 100% zero-configuration execution:
- Eliminates the requirement for .env, repos.csv, and config JSON files.
- Persists credentials securely in the user profile directory: ~/.ghec-advisor/config.json
- Stores RSA private keys in: ~/.ghec-advisor/secrets/
- Supports multi-tier resolution: Environment Variables > Local .env > User Profile Config.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("ghec-credentials")


def get_user_config_dir() -> str:
    """Return OS-standard user configuration directory for GHEC Advisor.

    Can be overridden via GHEC_CONFIG_DIR environment variable.
    """
    custom = os.getenv("GHEC_CONFIG_DIR")
    if custom:
        path = os.path.abspath(custom)
    else:
        path = os.path.expanduser("~/.ghec-advisor")
    os.makedirs(path, exist_ok=True)
    return path


def get_credentials_path() -> str:
    """Return path to saved credentials JSON file."""
    return os.path.join(get_user_config_dir(), "config.json")


def get_secrets_dir() -> str:
    """Return path to secrets directory where private keys are stored."""
    path = os.path.join(get_user_config_dir(), "secrets")
    os.makedirs(path, exist_ok=True)
    return path


def save_private_key(key_content: str, app_slug: str = "gh-governance-advisor", dest_dir: Optional[str] = None) -> str:
    """Save RSA private key with standardized naming convention and safe permissions."""
    today_str = time.strftime("%Y-%m-%d")
    filename = f"{app_slug}.{today_str}.private-key.pem"
    target_dir = dest_dir or get_secrets_dir()
    os.makedirs(target_dir, exist_ok=True)
    key_path = os.path.join(target_dir, filename)

    with open(key_path, "w", encoding="utf-8") as f:
        f.write(key_content)

    # Restrict permissions to owner-only on POSIX systems (chmod 600)
    try:
        os.chmod(key_path, 0o600)
    except Exception:
        pass

    return key_path


def save_user_credentials(
    app_id: int | str,
    private_key_path: str,
    installation_id: Optional[int | str] = None,
    api_base_url: str = "https://api.github.com",
    llm_provider: str = "gemini",
    llm_model: str = "gemini-3.5-flash",
    llm_api_key: str = "",
    llm_enabled: bool = True,
) -> str:
    """Persist user credentials and AI preferences to ~/.ghec-advisor/config.json."""
    config_data: Dict[str, Any] = {
        "github": {
            "app_id": int(app_id) if str(app_id).isdigit() else app_id,
            "installation_id": int(installation_id) if installation_id and str(installation_id).isdigit() else installation_id,
            "private_key_path": os.path.abspath(private_key_path) if os.path.isfile(private_key_path) else private_key_path,
            "api_base_url": api_base_url.rstrip("/"),
        },
        "llm": {
            "provider": llm_provider,
            "model": llm_model,
            "api_key": llm_api_key.strip(),
            "enabled": llm_enabled and (llm_provider != "none"),
        },
    }

    config_path = get_credentials_path()
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    try:
        os.chmod(config_path, 0o600)
    except Exception:
        pass

    return config_path


def load_user_credentials() -> Dict[str, Any]:
    """Load configuration from ~/.ghec-advisor/config.json if it exists."""
    config_path = get_credentials_path()
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as err:
            logger.debug("Failed reading user config from %s: %s", config_path, err)
    return {}


def find_private_key(candidate_path: Optional[str] = None) -> Optional[str]:
    """Search for a valid private key in specified path, user secrets dir, or local secrets/."""
    # 1. Direct path check
    if candidate_path:
        expanded = os.path.expanduser(candidate_path)
        if os.path.isfile(expanded):
            return os.path.abspath(expanded)
        if candidate_path.startswith("-----BEGIN"):
            return candidate_path

    # 2. Check ~/.ghec-advisor/secrets/
    user_secrets = get_secrets_dir()
    if os.path.isdir(user_secrets):
        keys = [
            os.path.join(user_secrets, f)
            for f in sorted(os.listdir(user_secrets), reverse=True)
            if f.endswith(".private-key.pem") or f.endswith(".pem")
        ]
        if keys:
            return keys[0]

    # 3. Check local ./secrets/
    local_secrets = os.path.join(os.getcwd(), "secrets")
    if os.path.isdir(local_secrets):
        keys = [
            os.path.join(local_secrets, f)
            for f in sorted(os.listdir(local_secrets), reverse=True)
            if f.endswith(".private-key.pem") or f.endswith(".pem")
        ]
        if keys:
            return keys[0]

    return None


def resolve_runtime_credentials() -> Dict[str, Any]:
    """Resolve credentials across environment variables, local .env, and user profile config.

    Precedence:
    1. System environment variables (for CI/CD pipelines and containers)
    2. Local .env file (if running inside a cloned repository)
    3. User profile config (~/.ghec-advisor/config.json)
    """
    user_cfg = load_user_credentials()
    user_gh = user_cfg.get("github", {})
    user_llm = user_cfg.get("llm", {})

    # GitHub App ID
    app_id = (os.getenv("GHEC_APP_ID") or user_gh.get("app_id") or "")
    if app_id:
        app_id = str(app_id).strip()

    # Installation ID
    installation_id = (os.getenv("GHEC_APP_INSTALLATION_ID") or user_gh.get("installation_id") or "")
    if installation_id:
        installation_id = str(installation_id).strip()

    # API Base URL
    api_base_url = (
        os.getenv("GHEC_API_BASE_URL")
        or user_gh.get("api_base_url")
        or "https://api.github.com"
    ).rstrip("/")

    # Private Key
    raw_key = os.getenv("GHEC_APP_PRIVATE_KEY") or ""
    key_path = os.getenv("GHEC_APP_PRIVATE_KEY_PATH") or user_gh.get("private_key_path") or ""

    resolved_key = ""
    if raw_key and raw_key.startswith("-----BEGIN"):
        resolved_key = raw_key
    else:
        found = find_private_key(key_path or raw_key)
        if found:
            resolved_key = found

    # LLM Settings
    llm_provider = (
        os.getenv("LLM_PROVIDER")
        or user_llm.get("provider")
        or "gemini"
    ).lower().strip()

    # Auto-detect provider from model name if set
    env_model = os.getenv("LLM_MODEL") or user_llm.get("model") or ""
    if env_model:
        m_lower = env_model.lower()
        if m_lower.startswith(("gpt-", "o1", "o3", "chatgpt-")):
            llm_provider = "openai"
        elif m_lower.startswith("claude-"):
            llm_provider = "anthropic"

    # Default model per provider
    default_models = {
        "gemini": "gemini-3.5-flash",
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
    }
    llm_model = env_model or default_models.get(llm_provider, "gemini-3.5-flash")

    # API Key per provider
    llm_api_key = ""
    if llm_provider in ("openai", "azure"):
        llm_api_key = (
            os.getenv("OPENAI_API_KEY")
            or os.getenv("LLM_API_KEY")
            or user_llm.get("api_key")
            or ""
        ).strip()
    elif llm_provider == "anthropic":
        llm_api_key = (
            os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("LLM_API_KEY")
            or user_llm.get("api_key")
            or ""
        ).strip()
    else:
        llm_api_key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("LLM_API_KEY")
            or user_llm.get("api_key")
            or ""
        ).strip()

    if llm_api_key.startswith("${") and llm_api_key.endswith("}"):
        llm_api_key = ""

    llm_enabled = user_llm.get("enabled", True)
    if os.getenv("LLM_ENABLED") is not None:
        llm_enabled = os.getenv("LLM_ENABLED", "true").lower() in ("true", "1", "yes")

    return {
        "app_id": app_id,
        "installation_id": installation_id,
        "private_key": resolved_key,
        "api_base_url": api_base_url,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "llm_api_key": llm_api_key,
        "llm_enabled": llm_enabled,
    }
