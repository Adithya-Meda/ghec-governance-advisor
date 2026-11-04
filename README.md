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
*Audits all accessible repositories with live progress banners and writes reports to `./output/` (`.html`, `.xlsx`, `.csv`).*

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

Run automated audits inside any repository without local setup.

#### 1. Store Secrets in Caller Repository
- `REPO360_APP_ID`: Numeric GitHub App ID (Repository Variable or Secret)
- `REPO360_APP_PRIVATE_KEY`: Private key `.pem` contents (Repository Secret)

#### 2. Workflow Example (`.github/workflows/audit.yml`)
```yaml
name: "Repo360 Platform Audit"

on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1" # Weekly

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: Adithya-Meda/repo360@v1
        with:
          app_id: ${{ vars.REPO360_APP_ID }}
          private_key: ${{ secrets.REPO360_APP_PRIVATE_KEY }}
          # Optional: filter by org(s); audits all installed orgs if omitted
          # org: "OrgAlpha,OrgBeta"
          # For GHE.com: api_base_url: "https://api.<enterprise>.ghe.com"
          # For GHES:    api_base_url: "https://ghe.mycompany.com/api/v3"

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: repo360-reports
          path: output/
```

---

## Audited Checks & Platform Coverage

- **Org Governance:** Organization rulesets, secret scanning push protection, runner group least privilege isolation, default workflow token permissions.
- **Repository Security:** Branch protection review gates (2 approvals), `CODEOWNERS` validation, GitHub Actions commit SHA pinning, workflow concurrency groups, Dependabot.
- **Developer Enablement:** Dev containers (`devcontainer.json`), GitHub Copilot instructions, standardized issue & PR templates, pre-commit hooks.

---

## License

[MIT License](LICENSE)
