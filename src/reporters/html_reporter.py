"""Interactive Standalone HTML Report Generator with Before/After Comparisons."""

from __future__ import annotations

import html
import os
from typing import Any, Dict, List

from .base_reporter import BaseReporter
from ..checks.base import CheckResult, CheckStatus


class HTMLReporter(BaseReporter):
    """Generates comprehensive, self-contained HTML reports with before/after diffs."""

    def generate(
        self,
        results: List[CheckResult],
        output_path: str,
        executive_summary: str = "",
        model_name: str = "",
    ) -> str:
        """Render and save HTML report."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        total = len(results)
        passed = sum(1 for r in results if r.status == CheckStatus.PASS)
        warned = sum(1 for r in results if r.status == CheckStatus.WARN)
        failed = sum(1 for r in results if r.status == CheckStatus.FAIL)
        skipped = sum(1 for r in results if r.status == CheckStatus.SKIPPED)
        ai_count = sum(1 for r in results if self.is_ai_result(r))

        effective_total = max(total - skipped, 1)
        compliance_pct = round((passed / effective_total) * 100, 1)
        generated_at = self.get_local_timestamp()

        # Render finding rows (granular repository drill-down)
        cards_html = [self._render_card(idx, r) for idx, r in enumerate(results)]

        # Render consolidated fleet playbook items
        clusters = self.build_remediation_clusters(results)
        playbook_cards_html = [self._render_playbook_card(idx, c) for idx, c in enumerate(clusters)]
        playbook_count = len(clusters)

        active_model = model_name or self.infer_ai_model(results, "Gemini")
        ai_briefing_block = ""
        if executive_summary:
            ai_briefing_block = f"""
            <div class="ai-briefing">
              <span class="ai-badge">AI Executive Risk Briefing ({html.escape(active_model)})</span>
              <div class="ai-briefing-text">{html.escape(executive_summary)}</div>
            </div>
            """

        playbook_body = (
            "".join(playbook_cards_html)
            if playbook_cards_html
            else (
                '<div class="card" style="text-align: center; color: #8b949e; padding: 32px;">'
                "All evaluated repositories met compliance standards. No fleet remediations required.</div>"
            )
        )

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Repo360 - Platform Governance & Intelligence Dashboard</title>
  <style>
    :root {{
      --bg: #0d1117;
      --card-bg: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --text-heading: #f0f6fc;
      --primary: #58a6ff;
      --pass: #238636;
      --pass-bg: rgba(35, 134, 54, 0.15);
      --warn: #d29922;
      --warn-bg: rgba(210, 153, 34, 0.15);
      --fail: #f85149;
      --fail-bg: rgba(248, 81, 73, 0.15);
      --code-bg: #0d1117;
      --diff-del-bg: rgba(248, 81, 73, 0.2);
      --diff-add-bg: rgba(46, 160, 67, 0.2);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 24px;
      line-height: 1.5;
    }}
    .container {{
      max-width: 1200px;
      margin: 0 auto;
    }}
    header {{
      border-bottom: 1px solid var(--border);
      padding-bottom: 20px;
      margin-bottom: 24px;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      flex-wrap: wrap;
      gap: 16px;
    }}
    h1 {{
      color: var(--text-heading);
      margin: 0 0 6px 0;
      font-size: 26px;
    }}
    .timestamp {{
      font-size: 13px;
      color: #8b949e;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }}
    .kpi-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      text-align: center;
    }}
    .kpi-card.kpi-card-ai {{
      border-color: rgba(137, 87, 229, 0.4);
      background: linear-gradient(180deg, rgba(121, 40, 202, 0.08) 0%, rgba(22, 27, 34, 1) 100%);
    }}
    .kpi-val {{
      font-size: 32px;
      font-weight: 700;
      color: var(--text-heading);
      margin-top: 4px;
    }}
    .kpi-label {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #8b949e;
      font-weight: 600;
    }}
    .score-pass {{ color: #3fb950; }}
    .score-warn {{ color: #d29922; }}
    .score-fail {{ color: #f85149; }}

    .view-switcher-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 20px;
      background: var(--card-bg);
      padding: 12px 16px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }}
    .view-switcher {{
      display: inline-flex;
      background: #0d1117;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 3px;
      gap: 4px;
    }}
    .view-btn {{
      background: transparent;
      border: none;
      color: var(--text);
      padding: 6px 14px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      transition: all 0.15s ease;
    }}
    .view-btn:hover {{
      color: #fff;
    }}
    .view-btn.active {{
      background: #1f6feb;
      color: #fff;
      box-shadow: 0 1px 4px rgba(0,0,0,0.4);
    }}
    .view-desc {{
      font-size: 13px;
      color: #8b949e;
    }}
    
    .controls {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 20px;
      background: var(--card-bg);
      padding: 12px 16px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }}
    .btn-group {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .tab-btn {{
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      transition: all 0.15s ease;
    }}
    .tab-btn:hover {{
      background: #21262d;
    }}
    .tab-btn.active {{
      background: #1f6feb;
      border-color: #1f6feb;
      color: #fff;
    }}
    .tab-btn.ai-tab-btn:hover {{
      border-color: #8957e5;
      color: #d2a8ff;
    }}
    .tab-btn.ai-tab-btn.active {{
      background: linear-gradient(135deg, #7928ca, #ff0080);
      border-color: #8957e5;
      color: #fff;
      box-shadow: 0 0 10px rgba(121, 40, 202, 0.4);
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 18px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
      transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }}
    .card:hover {{
      border-color: #58a6ff;
    }}
    .card.card-ai {{
      border-left: 4px solid #8957e5;
      box-shadow: 0 4px 14px rgba(137, 87, 229, 0.12);
    }}
    .card.card-ai:hover {{
      border-color: #a371f7;
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 12px;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .card-title {{
      font-size: 18px;
      font-weight: 600;
      color: var(--text-heading);
      margin: 0;
    }}
    .badges {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .badge {{
      display: inline-block;
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .badge-pass {{ background: var(--pass-bg); color: #3fb950; border: 1px solid rgba(46, 160, 67, 0.4); }}
    .badge-warn {{ background: var(--warn-bg); color: #d29922; border: 1px solid rgba(210, 153, 34, 0.4); }}
    .badge-fail {{ background: var(--fail-bg); color: #f85149; border: 1px solid rgba(248, 81, 73, 0.4); }}
    .badge-skip {{ background: #21262d; color: #8b949e; border: 1px solid var(--border); }}
    .badge-sev-critical {{ background: rgba(248, 81, 73, 0.2); color: #f85149; border: 1px solid rgba(248, 81, 73, 0.4); }}
    .badge-sev-high {{ background: rgba(219, 109, 40, 0.2); color: #db6d28; border: 1px solid rgba(219, 109, 40, 0.4); }}
    .badge-sev-medium {{ background: rgba(210, 153, 34, 0.2); color: #d29922; border: 1px solid rgba(210, 153, 34, 0.4); }}
    .badge-sev-low {{ background: rgba(56, 139, 253, 0.2); color: #58a6ff; border: 1px solid rgba(56, 139, 253, 0.4); }}
    .badge-ai {{
      background: linear-gradient(135deg, #7928ca, #ff0080);
      color: #fff !important;
      font-weight: 700;
      border: none;
      box-shadow: 0 0 8px rgba(121, 40, 202, 0.4);
    }}
    .badge-standard {{ background: #21262d; color: #8b949e; border: 1px solid var(--border); }}
    .badge-file {{
      background: #161b22;
      color: #58a6ff;
      border: 1px solid rgba(88, 166, 255, 0.3);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11px;
    }}
    
    .fleet-scope-banner {{
      background: #0d1117;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px 14px;
      margin: 12px 0 14px 0;
    }}
    .fleet-scope-header {{
      font-size: 13px;
      color: #8b949e;
      margin-bottom: 8px;
    }}
    .fleet-scope-header strong {{
      color: #58a6ff;
    }}
    .repo-chips-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .repo-chip {{
      background: #21262d;
      border: 1px solid var(--border);
      color: #c9d1d9;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 11px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .playbook-code-block {{
      border-radius: 6px;
      overflow: hidden;
      border: 1px solid var(--border);
      margin-top: 12px;
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    .playbook-code-block .code-header {{
      padding: 6px 12px;
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      background: #16241b;
      color: #3fb950;
    }}
    .playbook-code-block.ai-code .code-header {{
      background: #241438;
      color: #d2a8ff;
    }}
    .playbook-code-block pre {{
      margin: 0;
      padding: 10px 12px;
      background: var(--code-bg);
      white-space: pre-wrap;
      word-break: break-all;
    }}

    .meta-line {{
      font-size: 13px;
      color: #8b949e;
      margin-bottom: 12px;
    }}
    .meta-line strong {{
      color: #c9d1d9;
    }}
    .explanation {{
      font-size: 14px;
      margin-bottom: 14px;
      color: #c9d1d9;
    }}
    .diff-container {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-top: 14px;
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    @media (max-width: 768px) {{
      .diff-container {{ grid-template-columns: 1fr; }}
    }}
    .diff-box {{
      border-radius: 6px;
      overflow: hidden;
      border: 1px solid var(--border);
    }}
    .diff-header {{
      padding: 6px 12px;
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .diff-box.before .diff-header {{ background: #211c1d; color: #f85149; }}
    .diff-box.after .diff-header {{ background: #16241b; color: #3fb950; }}
    .diff-box.after.ai-diff .diff-header {{ background: #241438; color: #d2a8ff; }}
    .diff-box pre {{
      margin: 0;
      padding: 10px 12px;
      background: var(--code-bg);
      white-space: pre-wrap;
      word-break: break-all;
    }}
    .doc-link {{
      display: inline-block;
      margin-top: 10px;
      font-size: 13px;
      color: var(--primary);
      text-decoration: none;
    }}
    .doc-link:hover {{ text-decoration: underline; }}
    .ai-briefing {{
      background: linear-gradient(180deg, rgba(121, 40, 202, 0.12) 0%, rgba(22, 27, 34, 1) 100%);
      border: 1px solid rgba(121, 40, 202, 0.4);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
    }}
    .ai-badge {{
      background: linear-gradient(135deg, #7928ca, #ff0080);
      color: #fff;
      font-weight: 700;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 4px 10px;
      border-radius: 12px;
      display: inline-block;
      margin-bottom: 12px;
    }}
    .ai-briefing-text {{
      color: #e6edf3;
      font-size: 14px;
      line-height: 1.6;
      white-space: pre-wrap;
    }}
    .ai-safety-warning {{
      background: rgba(210, 153, 34, 0.12);
      border: 1px solid rgba(210, 153, 34, 0.4);
      color: #e3b341;
      border-radius: 6px;
      padding: 12px 16px;
      font-size: 13px;
      margin-bottom: 20px;
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Repo360 Platform Governance & Intelligence Report</h1>
        <div class="timestamp">Audit Run Generated: <strong>{generated_at}</strong></div>
      </div>
      <div>
        <span class="badge" style="background: #1f6feb; color: #fff; padding: 6px 12px; font-size: 12px;">Enterprise Cloud Edition</span>
      </div>
    </header>

    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Compliance Score</div>
        <div class="kpi-val {'score-pass' if compliance_pct >= 80 else 'score-warn' if compliance_pct >= 50 else 'score-fail'}">{compliance_pct}%</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Total Checks</div>
        <div class="kpi-val">{total}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Passed Checks (PASS)</div>
        <div class="kpi-val score-pass">{passed}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Warning Risks (WARN)</div>
        <div class="kpi-val score-warn">{warned}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Failed Checks (FAIL)</div>
        <div class="kpi-val score-fail">{failed}</div>
      </div>
      <div class="kpi-card kpi-card-ai">
        <div class="kpi-label" style="color: #bc8cff;">AI Remediations</div>
        <div class="kpi-val" style="color: #d2a8ff;">{ai_count}</div>
      </div>
    </div>

    {ai_briefing_block}

    <div class="ai-safety-warning">
      <strong>AI Safety & Advisory Notice:</strong> AI-synthesized remediation snippets, configuration files, and executive summaries are advisory only. Code configurations and policies must be reviewed, tested, and validated in non-production environments by repository maintainers prior to applying to production systems.
    </div>

    <div class="view-switcher-bar">
      <div class="view-switcher">
        <button id="btn-view-playbook" class="view-btn active" onclick="switchView('playbook')">
          Consolidated Fleet Playbook ({playbook_count})
        </button>
        <button id="btn-view-repo" class="view-btn" onclick="switchView('repo')">
          Repository Drill-Down ({total})
        </button>
      </div>
      <div class="view-desc" id="view-desc">
        Canonical remediation playbook deduplicated across the fleet by tech stack and policy.
      </div>
    </div>

    <div id="playbook-view-container">
      {playbook_body}
    </div>

    <div id="repo-view-container" style="display: none;">
      <div class="controls">
        <div class="btn-group">
          <button class="tab-btn active" onclick="filterPersona('all')">All Personas</button>
          <button class="tab-btn" onclick="filterPersona('org_admin')">Org Admin</button>
          <button class="tab-btn" onclick="filterPersona('repo_admin')">Repo Admin</button>
          <button class="tab-btn" onclick="filterPersona('contributor')">Contributor / DX</button>
        </div>
        <div class="btn-group">
          <button class="tab-btn active" onclick="filterStatus('all')">All Statuses</button>
          <button class="tab-btn" onclick="filterStatus('FAIL')">FAIL Only</button>
          <button class="tab-btn" onclick="filterStatus('WARN')">WARN Only</button>
          <button class="tab-btn" onclick="filterStatus('PASS')">PASS Only</button>
        </div>
        <div class="btn-group">
          <button class="tab-btn active" onclick="filterSource('all')">All Sources</button>
          <button class="tab-btn ai-tab-btn" onclick="filterSource('ai')">AI Tailored Only ({ai_count})</button>
          <button class="tab-btn" onclick="filterSource('standard')">Standard Rules Only</button>
        </div>
      </div>

      <div id="findings-container">
        {"".join(cards_html)}
      </div>
    </div>
  </div>

  <script>
    let activePersona = 'all';
    let activeStatus = 'all';
    let activeSource = 'all';

    function switchView(view) {{
      const btnPlaybook = document.getElementById('btn-view-playbook');
      const btnRepo = document.getElementById('btn-view-repo');
      const playbookContainer = document.getElementById('playbook-view-container');
      const repoContainer = document.getElementById('repo-view-container');
      const desc = document.getElementById('view-desc');

      if (view === 'playbook') {{
        btnPlaybook.classList.add('active');
        btnRepo.classList.remove('active');
        playbookContainer.style.display = 'block';
        repoContainer.style.display = 'none';
        desc.textContent = 'Canonical remediation playbook deduplicated across the fleet by tech stack and policy.';
      }} else {{
        btnRepo.classList.add('active');
        btnPlaybook.classList.remove('active');
        playbookContainer.style.display = 'none';
        repoContainer.style.display = 'block';
        desc.textContent = 'Granular findings and evaluations for individual repositories across all personas.';
      }}
    }}

    function filterPersona(persona) {{
      activePersona = persona;
      updateButtons(0, persona);
      applyFilters();
    }}

    function filterStatus(status) {{
      activeStatus = status;
      updateButtons(1, status);
      applyFilters();
    }}

    function filterSource(source) {{
      activeSource = source;
      updateButtons(2, source);
      applyFilters();
    }}

    function updateButtons(groupIndex, value) {{
      const groups = document.querySelectorAll('.controls .btn-group');
      if (groups.length > groupIndex) {{
        groups[groupIndex].querySelectorAll('.tab-btn').forEach(btn => {{
          if (btn.getAttribute('onclick').includes("'" + value + "'")) {{
            btn.classList.add('active');
          }} else {{
            btn.classList.remove('active');
          }}
        }});
      }}
    }}

    function applyFilters() {{
      const cards = document.querySelectorAll('.finding-card');
      cards.forEach(card => {{
        const cardPersona = card.getAttribute('data-persona');
        const cardStatus = card.getAttribute('data-status');
        const cardSource = card.getAttribute('data-source');
        
        const matchPersona = (activePersona === 'all' || cardPersona === activePersona);
        const matchStatus = (activeStatus === 'all' || cardStatus === activeStatus);
        const matchSource = (activeSource === 'all' || cardSource === activeSource);

        if (matchPersona && matchStatus && matchSource) {{
          card.style.display = 'block';
        }} else {{
          card.style.display = 'none';
        }}
      }});
    }}
  </script>
</body>
</html>
"""
        with open(output_path, "w", encoding="utf-8") as html_file:
            html_file.write(html_content)

        return output_path

    def _render_playbook_card(self, idx: int, c: Dict[str, Any]) -> str:
        """Render consolidated fleet remediation card."""
        is_ai = c["is_ai"]
        card_extra_class = " card-ai" if is_ai else ""
        stack_label = c["detected_stack"]
        sev_value = c["severity"].value
        sev_class = f"badge-sev-{sev_value.lower()}"

        source_badge = (
            f"""<span class="badge badge-ai">AI Tailored ({html.escape(stack_label)})</span>"""
            if is_ai
            else """<span class="badge badge-standard">Standard Policy</span>"""
        )

        file_badge = f"""<span class="badge badge-file">{html.escape(c["target_file"])}</span>"""
        chips_html = "".join(f"""<span class="repo-chip">{html.escape(repo)}</span>""" for repo in c["affected_repos"])

        code_block_class = "playbook-code-block ai-code" if is_ai else "playbook-code-block"
        code_header = (
            f"&plus; Canonical Recommended Configuration ({html.escape(stack_label)})"
            if is_ai
            else "&plus; Canonical Recommended Configuration"
        )

        doc_link = ""
        if c["documentation_url"]:
            doc_link = (
                f"""<a class="doc-link" href="{html.escape(c['documentation_url'])}" """
                f"""target="_blank" rel="noopener noreferrer">View Official GitHub Documentation &rarr;</a>"""
            )

        repo_unit = "Repository" if c["affected_count"] == 1 else "Repositories"

        return f"""
        <div class="card playbook-card{card_extra_class}">
          <div class="card-header">
            <h3 class="card-title">Action Item #{idx + 1}: {html.escape(c["check_name"])}</h3>
            <div class="badges">
              {source_badge}
              {file_badge}
              <span class="badge {sev_class}">{sev_value}</span>
              <span class="badge" style="background:#21262d; color:#c9d1d9;">{c["category"]}</span>
              <span class="badge" style="background:#21262d; color:#c9d1d9;">{c["persona"].value.upper()}</span>
            </div>
          </div>
          <div class="fleet-scope-banner">
            <div class="fleet-scope-header">
              Affected Fleet Scope: <strong>{c["affected_count"]} {repo_unit}</strong>
            </div>
            <div class="repo-chips-list">
              {chips_html}
            </div>
          </div>
          <div class="explanation">
            <strong>Governance Baseline:</strong> {html.escape(c["explanation"])}
          </div>
          <div class="{code_block_class}">
            <div class="code-header">{code_header}</div>
            <pre><code>{html.escape(c["remediation_code"])}</code></pre>
          </div>
          {doc_link}
        </div>
        """

    def _render_card(self, idx: int, r: CheckResult) -> str:
        status_class = f"badge-{r.status.value.lower()}"
        is_ai = self.is_ai_result(r)
        source_type = "ai" if is_ai else "standard"
        target_file = self.infer_target_file(r.check_id)

        card_extra_class = " card-ai" if is_ai else ""
        stack_label = r.extra_details.get("detected_stack") or "Detected Framework"

        source_badge = ""
        if is_ai:
            source_badge = f"""<span class="badge badge-ai">AI Tailored ({html.escape(stack_label)})</span>"""
        else:
            source_badge = """<span class="badge badge-standard">Standard Policy</span>"""

        file_badge = f"""<span class="badge badge-file">{html.escape(target_file)}</span>"""

        diff_block = ""
        if r.remediation_snippet_before or r.remediation_snippet_after:
            after_class = "diff-box after ai-diff" if is_ai else "diff-box after"
            after_header = (
                f"&plus; AI-Synthesized Configuration ({html.escape(stack_label)})"
                if is_ai
                else "&plus; Recommended Configuration"
            )
            diff_block = f"""
            <div class="diff-container">
              <div class="diff-box before">
                <div class="diff-header">&minus; Current Configuration</div>
                <pre>{html.escape(r.remediation_snippet_before or r.current_state)}</pre>
              </div>
              <div class="{after_class}">
                <div class="diff-header">{after_header}</div>
                <pre>{html.escape(r.remediation_snippet_after or r.recommended_state)}</pre>
              </div>
            </div>
            """

        doc_link = ""
        if r.documentation_url:
            doc_link = f"""<a class="doc-link" href="{html.escape(r.documentation_url)}" target="_blank" rel="noopener noreferrer">View Official GitHub Documentation &rarr;</a>"""

        return f"""
        <div class="card finding-card{card_extra_class}" data-persona="{r.persona.value}" data-status="{r.status.value}" data-source="{source_type}">
          <div class="card-header">
            <h3 class="card-title">{html.escape(r.check_name)}</h3>
            <div class="badges">
              {source_badge}
              {file_badge}
              <span class="badge {status_class}">{r.status.value}</span>
              <span class="badge" style="background:#21262d; color:#c9d1d9;">{r.category}</span>
              <span class="badge" style="background:#21262d; color:#c9d1d9;">{r.persona.value.upper()}</span>
            </div>
          </div>
          <div class="meta-line">
            Scope: <strong>{html.escape(r.org_name)}</strong> / <strong>{html.escape(r.repo_name)}</strong>
          </div>
          <div class="explanation">
            <strong>Finding:</strong> {html.escape(r.explanation)}
          </div>
          <div class="explanation">
            <strong>Current State:</strong> {html.escape(r.current_state)}<br>
            <strong>Recommended State:</strong> {html.escape(r.recommended_state)}
          </div>
          {diff_block}
          {doc_link}
        </div>
        """
