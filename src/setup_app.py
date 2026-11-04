"""Automated 1-Click GitHub App Registration Wizard for GHEC.

Uses GitHub's official App Manifest flow:
1. Prompts interactively for target Organization and parameters.
2. Spins up a temporary local HTTP server on http://localhost:8989
3. Opens browser to GitHub with pre-configured read-only governance permissions
4. Exchanges authorization code via POST /app-manifests/{code}/conversions
5. Automatically saves the RSA private key (.pem) to user config (~/.ghec-advisor/secrets/)
6. Opens GitHub App installation page and automatically fetches Installation ID
7. Prompts user to select AI Remediation Provider and enter API key
8. Persists all credentials to ~/.ghec-advisor/config.json (Zero .env or repos.csv required!)
"""

from __future__ import annotations

import argparse
import html
import http.server
import json
import logging
import os
import socketserver
import time
import urllib.parse
import webbrowser
from typing import Optional
import requests

from .auth.github_app_auth import GitHubAppAuth
from .credentials import (
    get_credentials_path,
    save_private_key,
    save_user_credentials,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("setup-wizard")

PORT = 8989
CALLBACK_URL = f"http://localhost:{PORT}/callback"


def get_manifest(github_domain: str, app_name: str = "GH-Governance-Advisor") -> dict:
    """Generate the GitHub App manifest payload."""
    return {
        "name": app_name or "GH-Governance-Advisor",
        "url": github_domain,
        "description": "Platform Governance & Best Practices Advisory Agent for GHEC",
        "hook_attributes": {
            "url": github_domain,
            "active": False,
        },
        "redirect_url": CALLBACK_URL,
        "default_permissions": {
            "actions": "read",
            "administration": "read",
            "contents": "read",
            "metadata": "read",
            "organization_administration": "read",
            "secret_scanning_alerts": "read",
        },
        "public": False,
    }


class ManifestCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler to serve the initial auto-redirect and receive the GitHub callback."""

    target_org: str = ""
    app_name: str = ""
    github_domain: str = "https://github.com"
    api_domain: str = "https://api.github.com"
    conversion_result: dict | None = None

    def log_message(self, format: str, *args) -> None:
        """Suppress standard HTTP server access logs."""
        pass

    def do_GET(self) -> None:
        """Handle initial browser landing and GitHub callback redirect."""
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path == "/":
            # Auto-assign unique name using target_org to avoid global GitHub App name collisions
            default_name = f"GH-Governance-Advisor-{self.target_org}" if self.target_org else "GH-Governance-Advisor"
            active_name = self.app_name or default_name
            manifest_json = json.dumps(get_manifest(self.github_domain, app_name=active_name))
            form_action = (
                f"{self.github_domain}/organizations/{self.target_org}/settings/apps/new"
                if self.target_org
                else f"{self.github_domain}/settings/apps/new"
            )

            html_page = f"""<!DOCTYPE html>
            <html>
            <head><title>Connecting to GitHub...</title></head>
            <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
              <h2>Redirecting to GitHub to create your App...</h2>
              <p>Please click the button below if you are not redirected automatically.</p>
              <form id="manifestForm" method="post" action="{html.escape(form_action)}">
                <input type="hidden" name="manifest" value='{html.escape(manifest_json)}'>
                <button type="submit" style="padding: 10px 20px; font-size: 16px; cursor: pointer;">
                  Continue to GitHub
                </button>
              </form>
              <script>document.getElementById('manifestForm').submit();</script>
            </body>
            </html>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_page.encode("utf-8"))
            return

        elif parsed_url.path == "/callback":
            # GitHub redirected back with ?code=...
            query_params = urllib.parse.parse_qs(parsed_url.query)
            code = query_params.get("code", [""])[0]

            if not code:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Error: Missing authorization code in callback.")
                return

            # Exchange code for app credentials
            conversion_endpoint = f"{self.api_domain}/app-manifests/{code}/conversions"
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }

            try:
                resp = requests.post(conversion_endpoint, headers=headers, timeout=15)
                resp.raise_for_status()
                ManifestCallbackHandler.conversion_result = resp.json()

                success_html = """<!DOCTYPE html>
                <html>
                <body style="font-family: sans-serif; text-align: center; padding: 60px; background: #0d1117; color: #58a6ff;">
                  <h1 style="color: #3fb950;">GitHub App Created Successfully!</h1>
                  <p style="color: #c9d1d9; font-size: 18px;">Your private key has been saved automatically.</p>
                  <p style="color: #8b949e;">You can now close this browser tab and return to your terminal.</p>
                </body>
                </html>"""

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(success_html.encode("utf-8"))

            except Exception as err:
                logger.error("Failed to convert manifest code: %s", err)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Failed to convert app manifest: {err}".encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


def resolve_api_base_url(domain: str) -> str:
    """Resolve GitHub REST API base URL across GitHub.com, ghe.com, and GHES.

    - github.com -> https://api.github.com
    - *.ghe.com (e.g. octocorp.ghe.com) -> https://api.octocorp.ghe.com
    - GHES on-premises (e.g. ghe.mycompany.com) -> https://ghe.mycompany.com/api/v3
    """
    domain = domain.strip().rstrip("/")
    if not domain.startswith("http://") and not domain.startswith("https://"):
        domain = f"https://{domain}"

    parsed = urllib.parse.urlparse(domain)
    host = parsed.netloc.lower()

    if host == "github.com" or host.endswith(".github.com"):
        return "https://api.github.com"
    elif host.endswith(".ghe.com"):
        return f"{parsed.scheme}://api.{host}"
    else:
        return f"{domain}/api/v3"


def run_wizard(
    org_name: str,
    github_domain: str = "https://github.com",
    app_name: str = "",
    open_browser: bool = True,
) -> None:
    """Run the interactive setup wizard."""
    github_domain = github_domain.strip().rstrip("/")
    if not github_domain.startswith("http://") and not github_domain.startswith("https://"):
        github_domain = f"https://{github_domain}"
    api_domain = resolve_api_base_url(github_domain)

    default_name = f"GH-Governance-Advisor-{org_name}" if org_name else "GH-Governance-Advisor"
    chosen_name = app_name or default_name

    ManifestCallbackHandler.target_org = org_name
    ManifestCallbackHandler.app_name = chosen_name
    ManifestCallbackHandler.github_domain = github_domain
    ManifestCallbackHandler.api_domain = api_domain
    ManifestCallbackHandler.conversion_result = None

    print("\n" + "=" * 65)
    print("  GHEC GOVERNANCE ADVISOR - 1-CLICK GITHUB APP SETUP")
    print("=" * 65)
    print(f"Target Organization: {org_name}")
    print(f"App Name:            {chosen_name}")
    print(f"GitHub Domain:       {github_domain}")
    print(f"Callback Listener:   {CALLBACK_URL}")
    print("-" * 65)
    print("Starting local listener and opening your browser...")

    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("localhost", PORT), ManifestCallbackHandler)
    server.timeout = 0.5
    if open_browser:
        webbrowser.open(f"http://localhost:{PORT}/")

    # Wait for the single callback request (timeout=0.5 ensures responsive Ctrl+C handling on Windows)
    try:
        while ManifestCallbackHandler.conversion_result is None:
            server.handle_request()
    finally:
        server.server_close()

    result = ManifestCallbackHandler.conversion_result
    if not result:
        print("Setup aborted: Could not obtain GitHub App credentials.")
        return

    app_id = result.get("id")
    app_slug = result.get("slug") or "gh-governance-advisor"
    pem_key = result.get("pem", "")
    install_url = f"{github_domain}/organizations/{org_name}/settings/apps/{app_slug}/installations"

    # 1. Automatically save private key to ~/.ghec-advisor/secrets/
    key_path = save_private_key(pem_key, app_slug=app_slug)
    # Also save a copy to ./secrets/ if local workspace exists
    try:
        local_secrets = os.path.join(os.getcwd(), "secrets")
        if os.path.isdir(local_secrets) or os.path.isfile(".env"):
            save_private_key(pem_key, app_slug=app_slug, dest_dir=local_secrets)
    except Exception:
        pass

    print("\n" + "=" * 65)
    print("  STEP 1: GITHUB APP CREATED")
    print("=" * 65)
    print(f"  App Name:         {result.get('name')}")
    print(f"  App ID:           {app_id}")
    print(f"  Private Key:      Saved to {key_path}")
    print("-" * 65)

    # 2. App Installation & Auto-fetch Installation ID
    print("\n" + "=" * 65)
    print("  STEP 2: INSTALL APP ON YOUR ORGANIZATION")
    print("=" * 65)
    print(f"  Installation URL: {install_url}")
    print("  Please click 'Install' and choose 'All repositories' (recommended).")
    print("-" * 65)

    if open_browser:
        try:
            webbrowser.open(install_url)
        except Exception:
            pass

    installation_id: Optional[int] = None
    try:
        auth = GitHubAppAuth(app_id=app_id, private_key=pem_key, api_base_url=api_domain)
        prompt_msg = (
            "Press Enter once you clicked 'Install' in the browser to auto-fetch your Installation ID\n"
            "(or enter 'm' to input manually, 's' to skip and auto-discover during audit): "
        )
        choice = input(prompt_msg).strip().lower()

        if choice == "m":
            manual_in = input("Enter Installation ID: ").strip()
            if manual_in.isdigit():
                installation_id = int(manual_in)
        elif choice != "s":
            print("Querying GitHub API for active installations...")
            for _ in range(3):
                installations = auth.discover_installations()
                if installations:
                    matched = [
                        i for i in installations
                        if i.get("account", {}).get("login", "").lower() == org_name.lower()
                    ]
                    selected = matched[0] if matched else installations[0]
                    installation_id = int(selected["id"])
                    org_login = selected.get("account", {}).get("login", org_name)
                    print(f"-> [SUCCESS] Auto-detected Installation ID: {installation_id} for '{org_login}'!")
                    break
                time.sleep(2)

            if not installation_id:
                print("Could not auto-detect active installation yet.")
                manual_in = input("Enter Installation ID manually (or press Enter to auto-discover during audit): ").strip()
                if manual_in.isdigit():
                    installation_id = int(manual_in)
    except Exception as err:
        logger.debug("Installation discovery error: %s", err)
        manual_in = input("Enter Installation ID manually (or press Enter to auto-discover during audit): ").strip()
        if manual_in.isdigit():
            installation_id = int(manual_in)

    # 3. Interactive AI Remediation Provider Selection
    print("\n" + "=" * 65)
    print("  STEP 3: AI REMEDIATION & GOVERNANCE ADVISORY ENGINE")
    print("=" * 65)
    print("Select your AI Remediation Provider:")
    print("  [1] Google Gemini (Recommended - default model: gemini-3.5-flash)")
    print("  [2] OpenAI (default model: gpt-4o)")
    print("  [3] Anthropic Claude (default model: claude-3-5-sonnet-20241022)")
    print("  [4] None / Disable AI (Deterministic policy checks only)")
    print("-" * 65)

    llm_choice = input("Select provider [1-4] (default: 1): ").strip() or "1"
    llm_provider = "gemini"
    llm_model = "gemini-3.5-flash"
    llm_api_key = ""
    llm_enabled = True

    if llm_choice == "2":
        llm_provider = "openai"
        llm_model = "gpt-4o"
        llm_api_key = input("Enter OPENAI_API_KEY (press Enter to skip): ").strip()
        custom_model = input(f"Enter model name [{llm_model}]: ").strip()
        if custom_model:
            llm_model = custom_model
    elif llm_choice == "3":
        llm_provider = "anthropic"
        llm_model = "claude-3-5-sonnet-20241022"
        llm_api_key = input("Enter ANTHROPIC_API_KEY (press Enter to skip): ").strip()
        custom_model = input(f"Enter model name [{llm_model}]: ").strip()
        if custom_model:
            llm_model = custom_model
    elif llm_choice == "4":
        llm_provider = "none"
        llm_model = ""
        llm_api_key = ""
        llm_enabled = False
    else:
        llm_provider = "gemini"
        llm_model = "gemini-3.5-flash"
        llm_api_key = input("Enter GEMINI_API_KEY (press Enter to skip): ").strip()
        custom_model = input(f"Enter model name [{llm_model}]: ").strip()
        if custom_model:
            llm_model = custom_model

    # 4. Persist credentials securely
    cfg_path = save_user_credentials(
        app_id=app_id,
        private_key_path=key_path,
        installation_id=installation_id,
        api_base_url=api_domain,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_enabled=llm_enabled,
    )

    # Optional: Also update local .env if present for project consistency
    try:
        from .validator import ConfigValidator
        env_path = os.path.abspath(".env")
        if os.path.isfile(env_path):
            ConfigValidator.update_env_file("GHEC_APP_ID", str(app_id), env_path)
            if installation_id:
                ConfigValidator.update_env_file("GHEC_APP_INSTALLATION_ID", str(installation_id), env_path)
            ConfigValidator.update_env_file("GHEC_APP_PRIVATE_KEY_PATH", key_path, env_path)
            if llm_enabled and llm_api_key:
                if llm_provider == "gemini":
                    ConfigValidator.update_env_file("GEMINI_API_KEY", llm_api_key, env_path)
                elif llm_provider == "openai":
                    ConfigValidator.update_env_file("OPENAI_API_KEY", llm_api_key, env_path)
                elif llm_provider == "anthropic":
                    ConfigValidator.update_env_file("ANTHROPIC_API_KEY", llm_api_key, env_path)
                ConfigValidator.update_env_file("LLM_PROVIDER", llm_provider, env_path)
                ConfigValidator.update_env_file("LLM_MODEL", llm_model, env_path)
    except Exception as err:
        logger.debug("Could not auto-update local .env: %s", err)

    print("\n" + "=" * 65)
    print("  SETUP COMPLETE! ZERO CONFIGURATION REQUIRED.")
    print("=" * 65)
    print(f"  App Name:         {result.get('name')}")
    print(f"  App ID:           {app_id}")
    print(f"  Installation ID:  {installation_id or 'Auto-discovered during audit'}")
    print(f"  Private Key:      {key_path}")
    print(f"  Configuration:    {cfg_path}")
    ai_status = f"{llm_provider.upper()} ({llm_model})" if llm_enabled else "DISABLED"
    print(f"  AI Remediation:   {ai_status}")
    print("-" * 65)
    print("  No .env, repos.csv, or JSON config files are required!")
    print("  Run your governance audit anytime from any directory:")
    print()
    print("    ghec-advisor")
    print("=" * 65 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="1-Click GitHub App Setup Wizard for GHEC")
    parser.add_argument(
        "--org",
        required=False,
        default="",
        help="Target GitHub organization name (e.g. fintech-core).",
    )
    parser.add_argument(
        "--app-name",
        required=False,
        default="",
        help="Custom GitHub App name (defaults to GH-Governance-Advisor-<org>).",
    )
    parser.add_argument(
        "--domain",
        required=False,
        default="https://github.com",
        help="GitHub domain (default: https://github.com).",
    )
    args = parser.parse_args()

    try:
        org = args.org
        if not org:
            org = input("Enter your target GitHub Organization name: ").strip()

        if not org:
            print("Error: Organization name is required.")
            return 1

        domain = args.domain
        if not args.org and domain == "https://github.com":
            custom_domain = input(
                "Enter GitHub Domain [https://github.com] (press Enter for default, or e.g. https://<enterprise>.ghe.com or https://ghe.company.com): "
            ).strip()
            if custom_domain:
                domain = custom_domain

        run_wizard(org_name=org, github_domain=domain, app_name=args.app_name)
        return 0
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user (Ctrl+C). Exiting...")
        return 130


if __name__ == "__main__":
    import sys
    sys.exit(main())
