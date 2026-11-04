# Repo360

360-Degree Platform Governance, Compliance, and Engineering Intelligence for GitHub Organizations. Audits repositories, monitors security posture, evaluates CI/CD hardening, and generates interactive HTML dashboards, executive Excel workbooks, and flat SIEM CSV feeds.

> [!WARNING]
> **Advisory Only:** Remediation snippets, policy suggestions, and summaries are advisory. Always validate suggested changes before applying them to production environments.

---

## Prerequisites

- **Python 3.10+** and **[pipx](https://pypa.github.io/pipx/)** (for CLI use)
- **Organization Admin / Owner access** on GitHub (to register and install the read-only GitHub App)
- *(Optional)* **AI API Key** (Gemini, OpenAI, or Anthropic for AI-tailored remediations; the rule engine functions completely offline without one)

---

## Supported Platforms

| Platform | Domain Example | Setup Command |
| :--- | :--- | :--- |
| **GitHub.com** | `https://github.com` | `repo360 setup --org <your-org>` |
| **GHE.com** *(Data Residency)* | `https://<enterprise>.ghe.com` | `repo360 setup --org <your-org> --domain https://<enterprise>.ghe.com` |
| **GHES** *(On-Premises)* | `https://ghe.mycompany.com` | `repo360 setup --org <your-org> --domain https://ghe.mycompany.com` |

---

## How to Use

### Method 1: Local CLI (Recommended)

#### 1. Install
```bash
pipx install git+https://github.com/Adithya-Meda/repo360.git
```

#### 2. Setup (One-Time)
```bash
repo360 setup --org <your-org>
```
*Opens your browser to register the read-only GitHub App, auto-downloads your private key to `~/.repo360/secrets/`, and prompts for your preferred AI provider.*

#### 3. Run Audit
```bash
# Audit all organizations where the GitHub App is installed
repo360 audit

# Or filter to specific organizations
repo360 audit --org OrgAlpha,OrgBeta
```
*Audits all accessible repositories with live progress banners and writes reports to `./repo360-output/` (`.html`, `.xlsx`, `.csv`).*

#### 4. Help & Options
```bash
# View available commands and global options
repo360 -h

# View options for the audit command
repo360 audit -h
```

---

### Multi-Organization Support (Single App & Private Key)

Repo360 natively supports multi-organization enterprises across GitHub.com, GHE.com, and GitHub Enterprise Server using a single GitHub App:

1. **Install Once, Use Everywhere:**
   Install your registered GitHub App across any number of organizations in your enterprise.
2. **Auto-Discovery:**
   Running `repo360 audit` automatically discovers every organization where the app is installed, dynamically provisions scoped installation tokens per organization, and aggregates findings into a single executive dashboard and SIEM export.
3. **Targeted Filtering:**
   Use `--org <org1,org2>` to audit specific organizations on demand.

---

### Method 2: GitHub Actions (CI/CD)

Run automated platform audits across organizations on a scheduled or dispatch basis without local installation.

#### 1. Configure Secrets & Variables

Navigate to **Settings** &rarr; **Secrets and variables** &rarr; **Actions** in your repository or organization.

##### GitHub App Authentication (Required)
- `REPO360_APP_ID`: Numeric GitHub App ID (store under **Repository Variables** or **Secrets**).
- `REPO360_APP_PRIVATE_KEY`: RSA private key `.pem` string (store under **Repository Secrets**).
- `REPO360_APP_INSTALLATION_ID`: *(Optional)* Numeric Installation ID (store under **Repository Variables**). Auto-discovered across all organizations if omitted.

##### AI Remediation Engine (Optional)
To enable AI-tailored remediations and executive risk narratives across any provider (Google Gemini, OpenAI, Anthropic), configure a single secret:
- **`AI_API_KEY`**: Set as an Encrypted Secret with your API key from Google Gemini, OpenAI, or Anthropic. (Legacy keys like `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` are also automatically recognized as fallbacks).
- **`AI_MODEL`**: *(Optional)* Target model override (e.g., `gemini-3.5-flash`, `gpt-4o`, `claude-3-5-sonnet-20241022`). Repo360 automatically auto-detects the provider from the model name. Defaults to `gemini-3.5-flash`.

*(Note: The rule engine evaluates all governance checks offline if no AI key is provided).*

---

#### 2. Workflow Definition (`.github/workflows/audit.yml`)

Following enterprise supply-chain security baselines, all actions are pinned to full 40-character immutable commit SHAs:

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
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: "Run Repo360 Action"
        # Pin to immutable commit SHA (or use 'uses: ./' if running within the Repo360 repo)
        uses: Adithya-Meda/repo360@35587da11467a5bf5066a337a5089f6655c6b653 # main
        with:
          # Required GitHub App Credentials
          app_id: ${{ vars.REPO360_APP_ID }}
          private_key: ${{ secrets.REPO360_APP_PRIVATE_KEY }}

          # Single Unified AI Key (Supports Gemini, OpenAI, or Anthropic)
          ai_api_key: ${{ secrets.AI_API_KEY || secrets.GEMINI_API_KEY }}
          # Optional model override (provider is auto-detected):
          # ai_model: "gpt-4o"
          # Optional org filter:
          # org: "OrgAlpha,OrgBeta"

      - name: "Publish Audit Reports Artifact"
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        if: always()
        with:
          name: repo360-audit-reports
          path: |
            repo360-output/*.xlsx
            repo360-output/*.csv
            repo360-output/*.html
          retention-days: 60
```

---

## Audited Checks & Platform Coverage

- **Org Governance:** Organization rulesets, secret scanning push protection, runner group least privilege isolation, default workflow token permissions.
- **Repository Security:** Branch protection review gates (2 approvals), `CODEOWNERS` validation, GitHub Actions commit SHA pinning, workflow concurrency groups, Dependabot.
- **Developer Enablement:** Dev containers (`devcontainer.json`), GitHub Copilot instructions, standardized issue & PR templates, pre-commit hooks.

---

## License

[MIT License](LICENSE)
