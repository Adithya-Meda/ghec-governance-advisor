# Repo360

Platform governance, compliance, engineering intelligence, and infrastructure metrics for GitHub organizations. Evaluates repositories against security baselines, analyzes contributor activity, monitors Actions self-hosted runner fleets, and generates interactive HTML dashboards, executive Excel workbooks, and SIEM CSV feeds.

> [!WARNING]
> **Advisory Only:** Remediation snippets and policies are advisory. Validate suggested changes in non-production environments before applying.

---

## Prerequisites

- **Python 3.10+** and **[pipx](https://pypa.github.io/pipx/)** (for CLI use)
- **Organization Owner / Admin access** on GitHub (to install the read-only GitHub App)
- **AI API Key** (Required for audit: Google Gemini, OpenAI, or Anthropic to synthesize tailored remediations and executive briefings)

---

## Supported Platforms

| Platform | Domain Example | Setup Command |
| :--- | :--- | :--- |
| **GitHub.com** | `https://github.com` | `repo360 setup --org <your-org>` |
| **GHE.com** *(Data Residency)* | `https://<enterprise>.ghe.com` | `repo360 setup --org <your-org> --domain https://<enterprise>.ghe.com` |
| **GHES** *(On-Premises)* | `https://ghe.mycompany.com` | `repo360 setup --org <your-org> --domain https://ghe.mycompany.com` |

---

## Required GitHub App Permissions

All permissions are read-only:

| Permission | Scope |
| :--- | :--- |
| `actions: read` | Repository |
| `administration: read` | Repository |
| `contents: read` | Repository |
| `issues: read` | Repository |
| `members: read` | Organization |
| `metadata: read` | Repository |
| `organization_administration: read` | Organization |
| `organization_self_hosted_runners: read` | Organization |
| `pull_requests: read` | Repository |
| `secret_scanning_alerts: read` | Organization |

---

## How to Use

### Method 1: Local CLI

#### 1. Install
```bash
pipx install git+https://github.com/Adithya-Meda/repo360.git
```

#### 2. Setup (One-Time)
```bash
repo360 setup --org <your-org>
```
Registers the read-only GitHub App with all required permissions, downloads the private key to `~/.repo360/secrets/`, and saves local configuration.

#### 3. Run Commands

Repositories are automatically discovered directly from GitHub App installations across your organizations:

```bash
# Governance Audit (HTML dashboard, executive Excel, SIEM CSV)
repo360 audit
repo360 audit --org <your-org>

# User Activity & Contributor Metrics (Excel & CSV)
repo360 activity
repo360 activity --org <your-org>

# Actions Self-Hosted Runners Analytics (Excel & CSV)
repo360 runners
repo360 runners --org <your-org>
```

All reports are written to `./repo360-output/`.

---

### Multi-Organization Support

Install the registered GitHub App across multiple organizations in your enterprise using the same App ID and private key:
- **Automatic Multi-Org Discovery:** Running `repo360 audit` (or `activity` / `runners`) automatically discovers every organization where the app is installed, provisions scoped tokens per organization, and aggregates findings into a single executive dashboard and SIEM export.
- **Targeted Organization Filtering:** Restrict scans to specific organizations on demand using `--org`:
  ```bash
  # Audit specific organizations
  repo360 audit --org OrgAlpha,OrgBeta

  # Analyze user activity across specific organizations
  repo360 activity --org OrgAlpha,OrgBeta

  # Analyze runner fleet across specific organizations
  repo360 runners --org OrgAlpha,OrgBeta
  ```

---

### Method 2: GitHub Actions (CI/CD)

Repo360 is packaged as a composite action that sets up the environment, executes requested scans, and uploads reports as workflow artifacts.

#### 1. Configure Secrets & Variables
In repository **Settings** &rarr; **Secrets and variables** &rarr; **Actions**:
- `REPO360_APP_ID`: Numeric GitHub App ID (Variable or Secret)
- `REPO360_APP_PRIVATE_KEY`: RSA private key `.pem` string (Secret)
- `AI_API_KEY`: API key for Google Gemini, OpenAI, or Anthropic (Secret, required for audit)

#### 2. Workflow Example (`.github/workflows/audit.yml`)

```yaml
name: "Repo360 Platform Audit"

on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1" # Weekly: Mondays at 06:00 UTC

permissions:
  contents: read

jobs:
  governance-audit:
    name: "Execute Advisory Audit"
    runs-on: ubuntu-latest

    steps:
      - name: "Run Repo360 Action"
        uses: Adithya-Meda/repo360@main
        with:
          app_id: ${{ vars.REPO360_APP_ID }} # GitHub App ID for authentication
          private_key: ${{ secrets.REPO360_APP_PRIVATE_KEY }} # Private key for token exchange
          ai_api_key: ${{ secrets.AI_API_KEY }} # Required for AI-tailored remediations in audit
          collect_activity: "true" # Scrapes contributor commit, PR, review, and issue metrics
          collect_runners: "true" # Audits self-hosted runner fleet compute, queues, and SLAs
```

---

## Audited Checks & Platform Coverage

- **Org Governance:** Organization rulesets, secret scanning push protection, runner group least privilege isolation, default workflow token permissions.
- **Repository Security:** Branch protection review gates, `CODEOWNERS` validation, GitHub Actions commit SHA pinning, workflow concurrency groups, Dependabot.
- **Developer Enablement:** Dev containers (`devcontainer.json`), GitHub Copilot instructions, standardized issue & PR templates, pre-commit hooks.
- **User Activity Collection:** Contributor commit cadence, pull requests opened/merged, code review participation, issue discussions, active days, and adoption metrics.
- **Runner Fleet Intelligence:** Actions self-hosted runner availability, ephemeral provisioning, execution compute hours, queue latency, and SLA breach tracking (>60s).

---

## License

[MIT License](LICENSE)
