# Repo360

360-degree platform governance, compliance, and engineering intelligence for GitHub organizations. Audits repositories, evaluates security controls, and generates interactive HTML dashboards, executive Excel workbooks, and flat CSV feeds.

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

#### 3. Run Audit
```bash
# Audit all installed organizations
repo360 audit

# Audit specific organizations
repo360 audit --org OrgAlpha,OrgBeta
```
Writes reports to `./repo360-output/` (`.html`, `.xlsx`, `.csv`).

---

### Multi-Organization Support

Install the registered GitHub App across multiple organizations in your enterprise. Running `repo360 audit` automatically discovers all installations, provisions scoped tokens per organization, and aggregates findings into a single executive dashboard and SIEM export.

---

### Method 2: GitHub Actions (CI/CD)

#### 1. Configure Secrets & Variables
In **Settings** &rarr; **Secrets and variables** &rarr; **Actions**:
- `REPO360_APP_ID`: Numeric GitHub App ID (Variable or Secret)
- `REPO360_APP_PRIVATE_KEY`: RSA private key `.pem` string (Secret)
- `AI_API_KEY`: *(Optional)* API key for Google Gemini, OpenAI, or Anthropic (Secret)
- `AI_MODEL`: *(Optional)* Model override, e.g. `gpt-4o` or `claude-3-5-sonnet-20241022` (Variable, defaults to `gemini-3.5-flash`)

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
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: "Run Repo360 Action"
        uses: Adithya-Meda/repo360@35587da11467a5bf5066a337a5089f6655c6b653 # main
        with:
          app_id: ${{ vars.REPO360_APP_ID }}
          private_key: ${{ secrets.REPO360_APP_PRIVATE_KEY }}
          ai_api_key: ${{ secrets.AI_API_KEY }}

      - name: "Publish Audit Reports Artifact"
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
        if: always()
        with:
          name: repo360-audit-reports
          path: repo360-output/
          retention-days: 60
```

---

## Audited Checks & Platform Coverage

- **Org Governance:** Organization rulesets, secret scanning push protection, runner group least privilege isolation, default workflow token permissions.
- **Repository Security:** Branch protection review gates, `CODEOWNERS` validation, GitHub Actions commit SHA pinning, workflow concurrency groups, Dependabot.
- **Developer Enablement:** Dev containers (`devcontainer.json`), GitHub Copilot instructions, standardized issue & PR templates, pre-commit hooks.

---

## License

[MIT License](LICENSE)
