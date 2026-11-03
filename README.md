# GitHub Governance Advisor

Audits GitHub organizations and repositories against security, governance, and CI/CD best practices. Generates interactive HTML, Excel, and CSV reports.

> [!WARNING]
> **Advisory Only:** Remediation snippets and summaries are advisory. Always validate suggested changes before applying them to production.

---

## Prerequisites

- **Python 3.10+** and **[pipx](https://pypa.github.io/pipx/)** (for CLI use)
- **Organization Admin / Owner access** on GitHub (to create and install the read-only GitHub App)
- *(Optional)* **AI API Key** (Gemini, OpenAI, or Anthropic for AI remediations; the rule engine works without one)

---

## Supported Platforms

| Platform | Domain Example | Setup Command |
| :--- | :--- | :--- |
| **GitHub.com** | `https://github.com` | `ghec-setup --org <your-org>` |
| **GHE.com** *(Data Residency)* | `https://<enterprise>.ghe.com` | `ghec-setup --org <your-org> --domain https://<enterprise>.ghe.com` |
| **GHES** *(On-Premises)* | `https://ghe.mycompany.com` | `ghec-setup --org <your-org> --domain https://ghe.mycompany.com` |

---

## How to Use

### Method 1: Local CLI (Recommended)

#### 1. Install
```bash
pipx install git+https://github.com/Adithya-Meda/ghec-governance-advisor.git
```

#### 2. Setup (One-Time)
```bash
ghec-setup --org <your-org>
```
*Opens your browser to register the read-only GitHub App, auto-downloads your private key, and prompts for your preferred AI provider.*

#### 3. Run Audit
```bash
ghec-advisor
```
*Audits all accessible repositories and writes reports to `./output/` (`.html`, `.xlsx`, `.csv`).*

---

### Method 2: GitHub Actions (CI/CD)

Run automated audits inside any repository without local setup.

#### 1. Store Secrets in Caller Repository
- `GHEC_APP_ID`: Numeric GitHub App ID (Repository Variable)
- `GHEC_APP_PRIVATE_KEY`: Private key `.pem` contents (Repository Secret)

#### 2. Workflow Example (`.github/workflows/audit.yml`)
```yaml
name: "Governance Audit"

on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1" # Weekly

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: Adithya-Meda/ghec-governance-advisor@v1
        with:
          app_id: ${{ vars.GHEC_APP_ID }}
          private_key: ${{ secrets.GHEC_APP_PRIVATE_KEY }}
          # For GHE.com: api_base_url: "https://api.<enterprise>.ghe.com"
          # For GHES:    api_base_url: "https://ghe.mycompany.com/api/v3"

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: governance-reports
          path: output/
```

---

## Audited Checks

- **Org Governance:** Organization rulesets, secret scanning push protection, runner group restrictions, default workflow permissions.
- **Repository Security:** Branch protection review gates (2 approvals), `CODEOWNERS` validation, Action commit SHA pinning, redundancy concurrency groups, Dependabot.
- **Developer Experience:** Dev containers (`devcontainer.json`), GitHub Copilot instructions, issue & PR templates, pre-commit hooks.

---

## License

[MIT License](LICENSE)
