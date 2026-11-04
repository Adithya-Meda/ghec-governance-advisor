# Repo360

Platform governance, compliance, engineering intelligence, and infrastructure metrics for GitHub organizations. Evaluates repositories against security baselines, analyzes contributor activity, monitors Actions self-hosted runner fleets, and generates interactive HTML dashboards, executive Excel workbooks, and SIEM CSV feeds.

> [!WARNING]
> **Advisory Only:** Remediation snippets and policies are advisory. Validate suggested changes in non-production environments before applying.

---

## Prerequisites

- **Python 3.10+** and **[pipx](https://pypa.github.io/pipx/)** (for CLI use)
- **Organization Owner / Admin access** on GitHub (to install the read-only GitHub App)
- *(Optional)* **AI API Key** (Gemini, OpenAI, or Anthropic for tailored remediation snippets)

---

## Supported Platforms

| Platform | Domain Example | Setup Command |
| :--- | :--- | :--- |
| **GitHub.com** | `https://github.com` | `repo360 setup --org <your-org>` |
| **GHE.com** *(Data Residency)* | `https://<enterprise>.ghe.com` | `repo360 setup --org <your-org> --domain https://<enterprise>.ghe.com` |
| **GHES** *(On-Premises)* | `https://ghe.mycompany.com` | `repo360 setup --org <your-org> --domain https://ghe.mycompany.com` |

---

## Repository Inventory (`repos.csv`)

Define target repositories in a CSV inventory file (`repos.csv`):

```csv
org,repo,enabled
my-org,*,true
my-org,payment-gateway,true
my-org,auth-service,true
```

Wildcards (`*`) scan all repositories across an organization. Comments (`#`) are supported.

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
Registers the read-only GitHub App, downloads the private key to `~/.repo360/secrets/`, and saves local configuration.

#### 3. Run Commands

```bash
# Governance Audit (HTML dashboard, executive Excel, SIEM CSV)
repo360 audit
repo360 audit --org <your-org>
repo360 audit --inventory repos.csv

# User Activity & Contributor Metrics (Excel & CSV)
repo360 activity --repos repos.csv --lookback-days 90

# Actions Self-Hosted Runners Analytics (Excel & CSV)
repo360 runners --repos repos.csv --lookback-days 90
```

All reports are written to `./repo360-output/`.

---

### Method 2: GitHub Actions (CI/CD)

Repo360 is packaged as a composite action that sets up the environment, executes requested scans, and uploads reports as workflow artifacts.

#### 1. Configure Secrets & Variables
In repository **Settings** &rarr; **Secrets and variables** &rarr; **Actions**:
- `REPO360_APP_ID`: Numeric GitHub App ID (Variable or Secret)
- `REPO360_APP_PRIVATE_KEY`: RSA private key `.pem` string (Secret)
- `AI_API_KEY`: *(Optional)* API key for Google Gemini, OpenAI, or Anthropic (Secret)

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
      - name: "Checkout Repository"
        uses: actions/checkout@v4

      - name: "Run Repo360 Action"
        uses: Adithya-Meda/repo360@main
        with:
          app_id: ${{ vars.REPO360_APP_ID }}
          private_key: ${{ secrets.REPO360_APP_PRIVATE_KEY }}
          ai_api_key: ${{ secrets.AI_API_KEY }}
          inventory: "repos.csv"
          # Optional additional metrics
          collect_activity: "false"
          collect_runners: "false"
```

---

## Audited Checks & Platform Coverage

- **Org Governance:** Organization rulesets, secret scanning push protection, runner group least privilege isolation, default workflow token permissions.
- **Repository Security:** Branch protection review gates, `CODEOWNERS` validation, GitHub Actions commit SHA pinning, workflow concurrency groups, Dependabot.
- **Developer Enablement:** Dev containers (`devcontainer.json`), GitHub Copilot instructions, standardized issue & PR templates, pre-commit hooks.
- **Infrastructure & Usage:** Actions self-hosted runner fleet utilization, queue wait times, SLA breaches (>60s), and contributor adoption patterns.

---

## License

[MIT License](LICENSE)
