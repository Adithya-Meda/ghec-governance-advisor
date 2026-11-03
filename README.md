# GitHub Enterprise Cloud (GHEC) Platform Governance Advisor

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![Platform: GHEC](https://img.shields.io/badge/platform-GitHub%20Enterprise%20Cloud-black.svg)](https://docs.github.com/en/enterprise-cloud@latest)
[![Code style: PEP 8](https://img.shields.io/badge/code%20style-PEP%208-green.svg)](https://peps.python.org/pep-0008/)
[![Security: OWASP Top 10 Aligned](https://img.shields.io/badge/security-OWASP%20Aligned-success.svg)](https://owasp.org/www-project-top-ten/)

A production-grade, enterprise-ready platform engineering agent designed to continuously inspect and remediate **GitHub Enterprise Cloud (GHEC)** environments (`github.com` and `*.ghe.com`).

The advisor enforces governance, security, CI/CD, and developer experience baselines across hundreds or thousands of repositories—delivering persona-tailored recommendations, syntactically accurate before/after remediations, and multi-format reports across three operational tiers:
- **Organization Administrators:** Ruleset adoption, Secret Scanning Push Protection, runner group governance, least-privilege tokens.
- **Repository Administrators:** CODEOWNERS validation, branch protection gates, immutable GitHub Actions SHA pinning, CI concurrency groups, Dependabot hygiene.
- **Contributors & Freshers (DX):** DevContainers for instant standardized onboarding, repository-specific Copilot Instructions, structured issue/PR templates, and pre-commit hooks.

---

## Architecture & Enterprise Workflow

```
+--------------------------------------------------------------------------------------------------+
| Central Administrative Repository (ghec-governance-advisor)                                      |
|                                                                                                  |
|   +--------------------------+     +--------------------------+                                  |
|   |   config/advisory.json   |     |    config/repos.csv      | (Optional: If omitted or empty,  |
|   | (Check/Uncheck Policies) |     |   (Selective Scope Inventory)|  Auto-Discovers all repos)   |
|   +------------+-------------+     +------------+-------------+                                  |
|                |                                |                                                |
|                v                                v                                                |
|       +--------+--------------------------------+--------+                                       |
|       |               ghec-advisor CLI Entrypoint        |                                       |
|       |         (Local Terminal / pipx / GitHub Actions) |                                       |
|       +------------------------+-------------------------+                                       |
|                                |                                                                 |
|                                v                                                                 |
|       +------------------------+-------------------------+                                       |
|       |             Resilient GHEC API Collector         |                                       |
|       | - 1000+ Repos Adaptive Pacing (20ms micro-delay) |                                       |
|       | - Automatic 1-Hour App Installation Token Refresh|                                       |
|       | - Primary Quota Tracking & Secondary Rate Backoff|                                       |
|       +------------------------+-------------------------+                                       |
|                                |                                                                 |
|                                v                                                                 |
|       +------------------------+-------------------------+                                       |
|       |       Multi-Provider AI Remediation Engine       | (Optional / Air-Gapped Safe)          |
|       |   Google Gemini | OpenAI / Azure | Anthropic     |                                       |
|       | - Tech-Stack-Tailored File Remediations          |                                       |
|       | - C-Suite Executive Risk Briefing Narrative      |                                       |
|       | - Automatic Prompt Redaction & Sanitization      |                                       |
|       +------------------------+-------------------------+                                       |
|                                |                                                                 |
|                                v                                                                 |
|       +------------------------+-------------------------+                                       |
|       |               Multi-Format Audit Deliverables    |                                       |
|       | - Executive Workbook   (audit_report.xlsx)       |                                       |
|       | - Flat SIEM / BI Feed  (audit_report.csv)        |                                       |
|       | - Interactive Dashboard(audit_report.html)       |                                       |
|       +--------------------------------------------------+                                       |
+--------------------------------------------------------------------------------------------------+
```

---

## Core Capabilities & Enterprise Standards

1. **100% Untouched Target Repositories:** Target repositories require zero configuration files, bot installations, or PR noise. All scanning and remediation synthesis is performed centrally.
2. **Zero-Setup Auto-Discovery:** If `GHEC_APP_INSTALLATION_ID` or `config/repos.csv` is omitted, the agent automatically discovers the organization installation and enumerates all accessible repositories.
3. **1000+ Repos Rate-Limit Resilience:**
   - **Primary Quota Monitoring:** Tracks `x-ratelimit-remaining` and pauses execution before exhaustion.
   - **Secondary Abuse Handling:** Catches HTTP 429 and 403 secondary limits, parsing GitHub `Retry-After` headers with exponential backoff and 30-second heartbeat updates.
   - **Adaptive Pacing:** Micro-pacing prevents concurrent burst throttling across massive repository fleets.
   - **1-Hour Token Refresh:** Long-running multi-hour audits automatically renew GitHub App installation access tokens before expiry.
4. **Multi-Provider AI Remediation Engine:**
   - Native support for **Google Gemini**, **OpenAI / Azure**, and **Anthropic (Claude)**.
   - **Model Fallback Cascade:** Automatically rolls over to backup models if a primary model encounters quota depletion.
   - **Prompt Sanitization:** Strips authorization headers, API keys, and RSA private keys before sending data to external LLMs.
   - **Air-Gapped Offline Fallback:** Functions deterministically using battle-tested rule templates when no AI key is configured.
5. **Tri-Format Reporting:**
   - **Excel (`.xlsx`):** Multi-sheet workbook featuring Executive Summary, dedicated AI Recommendations, and granular Persona finding sheets.
   - **Interactive HTML (`.html`):** Standalone, self-contained dashboard with real-time text search, severity/persona filters, and syntax-highlighted **Before vs. After** remediation diffs.
   - **Flat CSV (`.csv`):** Normalized data format ready for SIEM ingestion into Splunk, Microsoft Sentinel, or Datadog.

---

## Installation

### Option A: Direct Tool Execution via `pipx` (Recommended)
`pipx` runs the CLI in an isolated virtual environment without polluting system packages:

```bash
# Clone the repository
git clone https://github.com/your-org/ghec-governance-advisor.git
cd ghec-governance-advisor

# Install CLI globally
pipx install .

# Run the advisor from anywhere
ghec-advisor --help
```

### Option B: Standard Python Virtual Environment
```bash
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate
# On Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install -e .
```

---

## 3-Step Quick Start

### Step 1: Register GitHub App

#### Automated 1-Click Setup Wizard (Recommended)
Launch the built-in wizard from your terminal:
```bash
ghec-setup --org <your-github-org>
```
1. Automatically launches your default browser with pre-configured read-only permissions.
2. Click **Create GitHub App for <your-org>**.
3. The wizard receives the authorization callback, downloads your RSA private key to `secrets/github-app.private-key.pem`, and prints your numeric **App ID**.

#### Manual Setup in GitHub UI
1. Navigate to `https://github.com/organizations/<org>/settings/apps/new`
2. **App Name:** `GitHub-Governance-Advisor`
3. **Webhook:** Uncheck *Active*.
4. **Permissions (All Read-Only):**
   - Repository: `Actions`, `Administration`, `Contents`, `Metadata`, `Secret scanning alerts`
   - Organization: `Administration`
5. Generate a private key (`.pem`) and install the App on target repositories.

### Step 2: Configure Environment (`.env`)
Copy the template and configure your credentials:
```bash
cp .env.example .env
```

```ini
# GHEC API URL
GHEC_API_BASE_URL=https://api.github.com

# GitHub App Credentials
GHEC_APP_ID=123456
GHEC_APP_PRIVATE_KEY_PATH=secrets/github-app.private-key.pem

# Optional: Auto-discovered on first run if left blank
GHEC_APP_INSTALLATION_ID=

# Multi-Provider AI (Optional)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
LLM_MODEL=gemini-3.5-flash
```

### Step 3: Run Audit

```bash
# Offline verification mode (uses mock findings)
ghec-advisor --mock-mode

# Live audit across all accessible repositories
ghec-advisor

# Scoped audit targeting specific repositories in config/repos.csv
ghec-advisor --inventory config/repos.csv
```

---

## Audited Checks & Personas

| Persona | Check Identifier | Category | Severity | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Org Admin** | `rulesets_adoption` | Governance | High | Enforces organization-level repository rulesets. |
| **Org Admin** | `secret_scanning_push_protection` | Security | Critical | Blocks accidental secret pushes org-wide. |
| **Org Admin** | `runner_groups_governance` | Infrastructure | Medium | Restricts self-hosted runner groups to approved repos. |
| **Org Admin** | `default_workflow_permissions` | Security | High | Enforces read-only default `GITHUB_TOKEN` permissions. |
| **Repo Admin** | `codeowners_validation` | Governance | High | Validates `CODEOWNERS` with default catch-all rules. |
| **Repo Admin** | `branch_rulesets` | Delivery | Critical | Enforces minimum review approval gates (default: 2). |
| **Repo Admin** | `workflow_sha_pinning` | Supply Chain | High | Requires immutable commit SHAs for third-party actions. |
| **Repo Admin** | `workflow_concurrency_groups` | CI/CD & Cost | Medium | Auto-cancels obsolete PR builds to save runner minutes. |
| **Repo Admin** | `dependabot_configuration` | Security | High | Verifies `.github/dependabot.yml` automated dependency updates. |
| **Contributor** | `devcontainers` | DX | Medium | Provides `.devcontainer/devcontainer.json` for reproducible builds. |
| **Contributor** | `copilot_instructions` | AI & DX | Low | Provides `.github/copilot-instructions.md` tailored coding rules. |
| **Contributor** | `issue_templates` | DX | Low | Standardizes bug and feature reporting templates. |
| **Contributor** | `pull_request_templates` | DX | Low | Provides PR readiness checklists (tests, docs, security). |
| **Contributor** | `pre_commit_hooks` | DX | Low | Prevents linting and secret errors prior to commit. |

---

## Configuration Reference

### Policy Configuration (`config/advisory.json`)
Toggle any check org-wide or customize policy thresholds:

```json
{
  "enabled_checks": {
    "org_admin": {
      "rulesets_adoption": true,
      "secret_scanning_push_protection": true,
      "runner_groups_governance": true,
      "default_workflow_permissions": true
    },
    "repo_admin": {
      "codeowners_validation": true,
      "branch_rulesets": true,
      "workflow_sha_pinning": true,
      "workflow_concurrency_groups": true,
      "dependabot_configuration": true
    },
    "contributor": {
      "devcontainers": true,
      "copilot_instructions": true,
      "issue_templates": true,
      "pull_request_templates": true,
      "pre_commit_hooks": true
    }
  },
  "policy_thresholds": {
    "minimum_approvals": 2,
    "require_linear_history": true,
    "disallow_force_pushes": true
  }
}
```

### Selective Repository Inventory (`config/repos.csv`)
If selective auditing is desired instead of full auto-discovery:

```csv
org_name,repo_name,target_personas,default_branch,owner_team
fintech-core,payment-gateway,all,main,@fintech-core/payments
fintech-core,auth-service,all,main,@fintech-core/security
fintech-core,internal-portal,repo_admin|contributor,main,@fintech-core/frontend
```

---

## Continuous Integration (GitHub Actions)

A zero-input workflow is included in `.github/workflows/audit.yml` that runs on a weekly schedule (Mondays at 06:00 UTC) or manual trigger:

```yaml
name: "GHEC Governance Advisory Audit"
on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1"
```

Generated Excel workbooks, CSV feeds, and interactive HTML dashboards are uploaded as workflow run artifacts retained for 60 days.

---

## Running Automated Tests

The test suite validates authentication, rate limiting, LLM fallback routing, check evaluation, and report generation:

```bash
# Run all tests
python -m pytest tests -v

# Run with test coverage
python -m pytest --cov=src tests -v
```

---

## Security & Compliance Architecture

- **Credential Redaction:** Tokens (`ghp_`, `ghs_`, Bearer tokens) and PEM headers are systematically redacted from logs and LLM prompts.
- **Short-Lived Authentication:** Uses RS256 JWTs and ephemeral 1-hour GitHub installation tokens.
- **Clock Drift Compensation:** Automatically computes local clock drift relative to GitHub API servers to prevent 401 token exchange rejections.
- **Least-Privilege Authorization:** Requires only Read-only scopes.
- **No Remote Code Execution:** Operates strictly on structured metadata and file content parsing.

---

## License

This project is licensed under the [MIT License](LICENSE).
