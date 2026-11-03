"""Automated 1-Click GitHub App Registration Wizard for GHEC.

Uses GitHub's official App Manifest flow:
1. Spins up a temporary local HTTP server on http://localhost:8989
2. Opens your browser to GitHub with pre-configured read-only permissions
3. Catches the authorization code callback upon approval
4. Exchanges code via POST /app-manifests/{code}/conversions
5. Automatically saves the RSA private key (.pem) to secrets/
6. Prints the App ID and installation instructions
"""

from __future__ import annotations

import argparse
import html
import http.server
import json
import logging
import os
import socketserver
import urllib.parse
import webbrowser
import requests

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("setup-wizard")

PORT = 8989
CALLBACK_URL = f"http://localhost:{PORT}/callback"


def get_manifest(github_domain: str) -> dict:
    """Generate the GitHub App manifest payload."""
    return {
        "name": "GitHub-Governance-Advisor",
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
            # Serve auto-submitting POST form to GitHub
            manifest_json = json.dumps(get_manifest(self.github_domain))
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


def run_wizard(org_name: str, github_domain: str = "https://github.com") -> None:
    """Run the interactive setup wizard."""
    github_domain = github_domain.rstrip("/")
    api_domain = "https://api.github.com" if "github.com" in github_domain else f"{github_domain}/api/v3"

    ManifestCallbackHandler.target_org = org_name
    ManifestCallbackHandler.github_domain = github_domain
    ManifestCallbackHandler.api_domain = api_domain

    print("\n" + "=" * 65)
    print("  GHEC GOVERNANCE ADVISOR - 1-CLICK GITHUB APP SETUP")
    print("=" * 65)
    print(f"Target Organization: {org_name}")
    print(f"GitHub Domain:       {github_domain}")
    print(f"Callback Listener:   {CALLBACK_URL}")
    print("-" * 65)
    print("Starting local listener and opening your browser...")

    server = socketserver.TCPServer(("localhost", PORT), ManifestCallbackHandler)
    webbrowser.open(f"http://localhost:{PORT}/")

    # Wait for the single callback request
    while ManifestCallbackHandler.conversion_result is None:
        server.handle_request()

    server.server_close()
    result = ManifestCallbackHandler.conversion_result

    app_id = result.get("id")
    app_slug = result.get("slug")
    pem_key = result.get("pem")
    install_url = f"{github_domain}/organizations/{org_name}/settings/apps/{app_slug}/installations"

    # Save private key securely
    os.makedirs("secrets", exist_ok=True)
    key_path = os.path.join("secrets", "github-app.private-key.pem")
    with open(key_path, "w", encoding="utf-8") as f:
        f.write(pem_key)

    # In POSIX systems, ensure strict permissions (chmod 600)
    try:
        os.chmod(key_path, 0o600)
    except Exception:
        pass

    print("\n" + "=" * 65)
    print("  GITHUB APP REGISTERED SUCCESSFULLY!")
    print("=" * 65)
    print(f"  App Name:         {result.get('name')}")
    print(f"  App ID:           {app_id}")
    print(f"  Private Key:      Saved to {os.path.abspath(key_path)}")
    print("-" * 65)
    print("  FINAL STEP - INSTALL APP ON YOUR REPOSITORIES:")
    print(f"  1. Visit: {install_url}")
    print("  2. Click 'Install' and select 'All repositories' (or target repos).")
    print("  3. Copy the numeric Installation ID from the URL after install.")
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
        "--domain",
        required=False,
        default="https://github.com",
        help="GitHub domain (default: https://github.com).",
    )
    args = parser.parse_args()

    org = args.org
    if not org:
        org = input("Enter your target GitHub Organization name: ").strip()

    if not org:
        print("Error: Organization name is required.")
        return

    run_wizard(org_name=org, github_domain=args.domain)


if __name__ == "__main__":
    main()

