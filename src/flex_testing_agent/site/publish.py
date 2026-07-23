"""Build the GitHub Pages site from ``docs/test-suggestions/*.yaml``."""

from __future__ import annotations

import html
import re
from pathlib import Path

import yaml

from flex_testing_agent.site.models import (
    DEFAULT_JIRA_BROWSE,
    DEFAULT_MONOREPO_BRANCH,
    DEFAULT_MONOREPO_PR,
    TestSuggestion,
)

DEFAULT_SUGGESTIONS_DIR = Path("docs/test-suggestions")
DEFAULT_OUTPUT_DIR = Path("pages")

_STATUS_ORDER = {"validated": 0, "suggested": 1, "draft": 2}
_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
_PR_RE = re.compile(r"(?<![/\w])#(\d+)\b")


def load_suggestions(suggestions_dir: Path) -> list[TestSuggestion]:
    """Load and validate all suggestion YAML files."""
    suggestions: list[TestSuggestion] = []
    for path in sorted(suggestions_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Suggestion file must be a mapping: {path}")
        suggestion = TestSuggestion.model_validate(raw)
        if suggestion.id != path.stem:
            raise ValueError(
                f"Suggestion id {suggestion.id!r} must match filename stem "
                f"{path.stem!r} ({path})"
            )
        suggestions.append(suggestion)
    ordered = sorted(suggestions, key=lambda item: item.id)
    ordered.sort(key=lambda item: item.updated, reverse=True)
    ordered.sort(key=lambda item: _STATUS_ORDER.get(item.status, 9))
    return ordered


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def linkify(
    text: str,
    *,
    pr_urls: dict[int, str] | None = None,
) -> str:
    """Escape text and turn Jira keys / known ``#PR`` refs into links."""
    escaped = _esc(text)
    pr_urls = pr_urls or {}

    def ticket_sub(match: re.Match[str]) -> str:
        key = match.group(1)
        url = f"{DEFAULT_JIRA_BROWSE}/{key}"
        return f'<a class="ref" href="{_esc(url)}">{_esc(key)}</a>'

    escaped = _TICKET_RE.sub(ticket_sub, escaped)

    def pr_sub(match: re.Match[str]) -> str:
        number = int(match.group(1))
        url = pr_urls.get(number, f"{DEFAULT_MONOREPO_PR}/{number}")
        return f'<a class="ref" href="{_esc(url)}">#{number}</a>'

    return _PR_RE.sub(pr_sub, escaped)


def _css() -> str:
    return """
:root {
  --bg: #f4f1eb;
  --ink: #1a1917;
  --muted: #5a554c;
  --panel: #fffcf7;
  --line: #d8d0c2;
  --accent: #006c68;
  --accent-soft: #e4f2f1;
  --validated: #1f6b3a;
  --suggested: #8a5a00;
  --draft: #5a554c;
  --pass: #1f6b3a;
  --fail: #9b1c1c;
  --blocked: #8a5a00;
  --skipped: #5a554c;
  --font: "IBM Plex Sans", "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: var(--font);
  color: var(--ink);
  background:
    radial-gradient(1100px 520px at 8% -8%, #e4efe8 0%, transparent 55%),
    radial-gradient(900px 480px at 100% 0%, #efe6d6 0%, transparent 48%),
    var(--bg);
  line-height: 1.55;
}
a { color: var(--accent); }
a.ref {
  font-family: var(--mono);
  font-size: 0.92em;
  text-decoration: none;
  border-bottom: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
}
a.ref:hover { border-bottom-color: var(--accent); }
header, main, footer {
  width: min(980px, calc(100% - 2rem));
  margin-inline: auto;
}
header { padding: 2.4rem 0 1rem; }
header h1 {
  margin: 0 0 0.4rem;
  font-size: clamp(1.85rem, 3vw, 2.45rem);
  letter-spacing: -0.02em;
}
header p { margin: 0; color: var(--muted); max-width: 40rem; }
nav {
  display: flex; gap: 1rem; flex-wrap: wrap; align-items: center;
  margin-top: 1.2rem; padding-top: 1rem; border-top: 1px solid var(--line);
}
nav a { text-decoration: none; font-weight: 600; }
main { padding-bottom: 3rem; }
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 1.25rem 1.35rem;
  margin: 1rem 0;
  box-shadow: 0 1px 0 rgba(28, 27, 25, 0.03);
}
.card h2, .card h3 { margin: 0 0 0.55rem; letter-spacing: -0.01em; }
.card h2 { font-size: 1.35rem; }
.meta { color: var(--muted); font-size: 0.92rem; }
.chip-row {
  display: flex; flex-wrap: wrap; gap: 0.45rem;
  margin: 0.85rem 0 0.35rem;
}
.chip {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.28rem 0.65rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--ink);
  text-decoration: none;
  font-size: 0.86rem;
  font-weight: 600;
}
.chip:hover { border-color: var(--accent); background: var(--accent-soft); }
.chip .kind {
  font-size: 0.68rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 700;
}
.chip.jira { border-color: #c7d4ef; }
.chip.pr { border-color: #c9ddd4; }
.badge {
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #fff;
}
.badge.validated { color: var(--validated); border-color: #b9d8c3; }
.badge.suggested { color: var(--suggested); border-color: #e6d3a4; }
.badge.draft { color: var(--draft); }
.badge.pass { color: var(--pass); }
.badge.fail { color: var(--fail); }
.badge.blocked { color: var(--blocked); }
.badge.skipped { color: var(--skipped); }
.facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
  margin: 1rem 0 0.25rem;
}
.fact {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0.7rem 0.8rem;
}
.fact .label {
  display: block;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 0.2rem;
}
.fact code, .fact a { font-family: var(--mono); font-size: 0.86rem; }
ul.steps { margin: 0.45rem 0 0.2rem; padding-left: 1.2rem; }
ul.steps li { margin: 0.25rem 0; }
pre, code { font-family: var(--mono); font-size: 0.88rem; }
pre {
  background: #1c1b19;
  color: #f4efe6;
  padding: 0.9rem 1rem;
  border-radius: 10px;
  overflow-x: auto;
}
table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; }
th, td {
  text-align: left; padding: 0.7rem 0.45rem;
  border-bottom: 1px solid var(--line); vertical-align: top;
}
th { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
td.test-id { width: 10.5rem; }
footer {
  padding: 1.5rem 0 2.5rem; color: var(--muted); font-size: 0.9rem;
  border-top: 1px solid var(--line);
}
""".strip()


def _layout(title: str, body: str, *, relative_prefix: str = "") -> str:
    home = f"{relative_prefix}index.html"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet" />
  <style>{_css()}</style>
</head>
<body>
  <header>
    <h1>flex-testing-agent</h1>
    <p>Published Flex robot test suggestions from monorepo release deltas,
    with links to GitHub PRs and Jira.</p>
    <nav>
      <a href="{home}">Test suggestions</a>
      <a href="https://github.com/Opentrons/flex-testing-agent">GitHub</a>
      <a href="https://github.com/Opentrons/flex-testing-agent#readme">README</a>
    </nav>
  </header>
  <main>
{body}
  </main>
  <footer>
    Apache-2.0 · Opentrons · Built from <code>docs/test-suggestions/</code>
    on push to <code>main</code>.
  </footer>
</body>
</html>
"""


def _pr_url_map(item: TestSuggestion) -> dict[int, str]:
    return {pr.number: pr.resolved_url() for pr in item.release.prs}


def _link_chips(item: TestSuggestion) -> str:
    chips: list[str] = []
    for ticket in item.release.tickets:
        label = ticket.key
        title = f" {_esc(ticket.title)}" if ticket.title else ""
        chips.append(
            f'<a class="chip jira" href="{_esc(ticket.resolved_url())}">'
            f'<span class="kind">Jira</span> {_esc(label)}{title}</a>'
        )
    for pr in item.release.prs:
        chips.append(
            f'<a class="chip pr" href="{_esc(pr.resolved_url())}">'
            f'<span class="kind">PR</span> #{pr.number} {_esc(pr.title)}</a>'
        )
    if not chips:
        return ""
    return f'<div class="chip-row">{"".join(chips)}</div>'


def render_index(suggestions: list[TestSuggestion]) -> str:
    """Render the catalog homepage."""
    cards: list[str] = []
    for item in suggestions:
        if item.status == "draft":
            continue
        pr_urls = _pr_url_map(item)
        ticket_bits = ", ".join(
            f'<a class="ref" href="{_esc(t.resolved_url())}">{_esc(t.key)}</a>'
            for t in item.release.tickets
        )
        pr_bits = ", ".join(
            f'<a class="ref" href="{_esc(pr.resolved_url())}">#{pr.number}</a>'
            for pr in item.release.prs[:4]
        )
        refs = " · ".join(part for part in (ticket_bits, pr_bits) if part)
        cards.append(
            f"""
<section class="card">
  <p class="meta">
    <span class="badge {item.status}">{item.status}</span>
    · updated {_esc(item.updated)}
    · <a class="ref" href="{_esc(DEFAULT_MONOREPO_BRANCH + "/" + item.release.monorepo_branch)}">{_esc(item.release.monorepo_branch)}</a>
  </p>
  <h2><a href="suggestions/{_esc(item.id)}.html">{_esc(item.title)}</a></h2>
  <p>{linkify(item.summary, pr_urls=pr_urls)}</p>
  <p class="meta">Hardware: {_esc(", ".join(item.hardware_required) or "none listed")}</p>
  {f'<p class="meta">Refs: {refs}</p>' if refs else ""}
</section>
""".strip()
        )
    body = f"""
<h2>Test suggestions</h2>
<p class="meta">Plans derived from the <code>opentrons/opentrons</code> monorepo
release branches. Add YAML under <code>docs/test-suggestions/</code>; CI publishes
this site with live Jira and PR links.</p>
{"".join(cards) if cards else "<p>No published suggestions yet.</p>"}
"""
    return _layout("flex-testing-agent · test suggestions", body)


def render_suggestion(item: TestSuggestion) -> str:
    """Render one suggestion detail page."""
    pr_urls = _pr_url_map(item)
    branch_url = f"{DEFAULT_MONOREPO_BRANCH}/{item.release.monorepo_branch}"
    commands = "\n".join(item.harness.commands)
    rows: list[str] = []
    for test in item.tests:
        result = (
            f'<span class="badge {test.result}">{test.result}</span>'
            if test.result
            else "—"
        )
        steps = "".join(
            f"<li>{linkify(step, pr_urls=pr_urls)}</li>" for step in test.steps
        )
        notes = (
            f"<p class='meta'>{linkify(test.notes, pr_urls=pr_urls)}</p>"
            if test.notes
            else ""
        )
        rows.append(
            f"""
<tr>
  <td class="test-id"><strong>{_esc(test.id)}</strong><br/>{_esc(test.name)}<br/>{result}</td>
  <td>
    <p>{linkify(test.why, pr_urls=pr_urls)}</p>
    <ul class="steps">{steps}</ul>
    {notes}
  </td>
</tr>
""".strip()
        )
    compared = (
        f"<div class='fact'><span class='label'>Compared to</span>"
        f"<code>{_esc(item.release.compared_to_tag)}</code></div>"
        if item.release.compared_to_tag
        else ""
    )
    robot_os = (
        f"<div class='fact'><span class='label'>Robot OS</span>"
        f"<code>{_esc(item.release.robot_os)}</code></div>"
        if item.release.robot_os
        else ""
    )
    body = f"""
<p class="meta"><a href="../index.html">← All suggestions</a></p>
<section class="card">
  <p class="meta">
    <span class="badge {item.status}">{item.status}</span>
    · updated {_esc(item.updated)}
  </p>
  <h2>{_esc(item.title)}</h2>
  <p>{linkify(item.summary, pr_urls=pr_urls)}</p>
  {_link_chips(item)}
  <div class="facts">
    <div class="fact">
      <span class="label">Monorepo branch</span>
      <a href="{_esc(branch_url)}">{_esc(item.release.monorepo_branch)}</a>
    </div>
    {compared}
    {robot_os}
    <div class="fact">
      <span class="label">Hardware</span>
      {_esc(", ".join(item.hardware_required) or "none listed")}
    </div>
  </div>
  {f"<h3>Harness commands</h3><pre>{_esc(commands)}</pre>" if commands else ""}
</section>
<section class="card">
  <h3>Tests</h3>
  <table>
    <thead><tr><th>ID</th><th>Plan</th></tr></thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</section>
"""
    return _layout(f"{item.title} · flex-testing-agent", body, relative_prefix="../")


def publish_test_suggestion_pages(
    *,
    suggestions_dir: Path = DEFAULT_SUGGESTIONS_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Generate ``index.html`` and per-suggestion pages. Returns written paths."""
    suggestions = load_suggestions(suggestions_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suggestions_out = output_dir / "suggestions"
    suggestions_out.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    index_path = output_dir / "index.html"
    index_path.write_text(render_index(suggestions), encoding="utf-8")
    written.append(index_path)

    for item in suggestions:
        path = suggestions_out / f"{item.id}.html"
        path.write_text(render_suggestion(item), encoding="utf-8")
        written.append(path)

    nojekyll = output_dir / ".nojekyll"
    nojekyll.write_text("", encoding="utf-8")
    written.append(nojekyll)
    return written
