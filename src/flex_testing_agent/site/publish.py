"""Build the GitHub Pages site from ``docs/test-suggestions/*.yaml``."""

from __future__ import annotations

import html
from pathlib import Path

import yaml

from flex_testing_agent.site.models import TestSuggestion

DEFAULT_SUGGESTIONS_DIR = Path("docs/test-suggestions")
DEFAULT_OUTPUT_DIR = Path("pages")

_STATUS_ORDER = {"validated": 0, "suggested": 1, "draft": 2}


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
    # validated first, then newest updated, then id
    ordered = sorted(suggestions, key=lambda item: item.id)
    ordered.sort(key=lambda item: item.updated, reverse=True)
    ordered.sort(key=lambda item: _STATUS_ORDER.get(item.status, 9))
    return ordered


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _css() -> str:
    return """
:root {
  --bg: #f6f3ee;
  --ink: #1c1b19;
  --muted: #5c574f;
  --panel: #fffdf9;
  --line: #d9d2c5;
  --accent: #006c68;
  --validated: #1f6b3a;
  --suggested: #8a5a00;
  --draft: #5c574f;
  --pass: #1f6b3a;
  --fail: #9b1c1c;
  --blocked: #8a5a00;
  --skipped: #5c574f;
  --font: "IBM Plex Sans", "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: var(--font);
  color: var(--ink);
  background:
    radial-gradient(1200px 600px at 10% -10%, #e7efe9 0%, transparent 55%),
    radial-gradient(900px 500px at 100% 0%, #efe7d8 0%, transparent 50%),
    var(--bg);
  line-height: 1.5;
}
a { color: var(--accent); }
header, main, footer {
  width: min(980px, calc(100% - 2rem));
  margin-inline: auto;
}
header { padding: 2.5rem 0 1rem; }
header h1 { margin: 0 0 0.35rem; font-size: clamp(1.8rem, 3vw, 2.4rem); }
header p { margin: 0; color: var(--muted); max-width: 42rem; }
nav {
  display: flex; gap: 1rem; flex-wrap: wrap;
  margin-top: 1.25rem; padding-top: 1rem; border-top: 1px solid var(--line);
}
nav a { text-decoration: none; font-weight: 600; }
main { padding-bottom: 3rem; }
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 1.1rem 1.2rem;
  margin: 0.85rem 0;
}
.card h2, .card h3 { margin: 0 0 0.4rem; }
.meta { color: var(--muted); font-size: 0.92rem; }
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
ul.steps { margin: 0.4rem 0 0.2rem; padding-left: 1.2rem; }
pre, code { font-family: var(--mono); font-size: 0.88rem; }
pre {
  background: #1c1b19;
  color: #f4efe6;
  padding: 0.85rem 1rem;
  border-radius: 10px;
  overflow-x: auto;
}
table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; }
th, td {
  text-align: left; padding: 0.55rem 0.4rem;
  border-bottom: 1px solid var(--line); vertical-align: top;
}
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
    <p>Published Flex robot test suggestions from monorepo release deltas, plus the local harness that runs them.</p>
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
    Apache-2.0 · Opentrons · Built from <code>docs/test-suggestions/</code> on push to <code>main</code>.
  </footer>
</body>
</html>
"""


def render_index(suggestions: list[TestSuggestion]) -> str:
    """Render the catalog homepage."""
    cards: list[str] = []
    for item in suggestions:
        if item.status == "draft":
            continue
        cards.append(
            f"""
<section class="card">
  <p class="meta">
    <span class="badge {item.status}">{item.status}</span>
    · updated {_esc(item.updated)}
    · {_esc(item.release.monorepo_branch)}
  </p>
  <h2><a href="suggestions/{_esc(item.id)}.html">{_esc(item.title)}</a></h2>
  <p>{_esc(item.summary)}</p>
  <p class="meta">Hardware: {_esc(", ".join(item.hardware_required) or "none listed")}</p>
</section>
""".strip()
        )
    body = f"""
<h2>Test suggestions</h2>
<p class="meta">Plans derived from <code>opentrons/opentrons</code> release branches (the monorepo). Add YAML under <code>docs/test-suggestions/</code>; CI publishes this site.</p>
{"".join(cards) if cards else "<p>No published suggestions yet.</p>"}
"""
    return _layout("flex-testing-agent · test suggestions", body)


def render_suggestion(item: TestSuggestion) -> str:
    """Render one suggestion detail page."""
    prs = "".join(
        f'<li><a href="{_esc(pr.url)}">#{pr.number}</a> {_esc(pr.title)}</li>'
        for pr in item.release.prs
    )
    commands = "\n".join(item.harness.commands)
    rows: list[str] = []
    for test in item.tests:
        result = (
            f'<span class="badge {test.result}">{test.result}</span>'
            if test.result
            else "—"
        )
        steps = "".join(f"<li>{_esc(step)}</li>" for step in test.steps)
        notes = f"<p class='meta'>{_esc(test.notes)}</p>" if test.notes else ""
        rows.append(
            f"""
<tr>
  <td><strong>{_esc(test.id)}</strong><br/>{_esc(test.name)}<br/>{result}</td>
  <td>
    <p>{_esc(test.why)}</p>
    <ul class="steps">{steps}</ul>
    {notes}
  </td>
</tr>
""".strip()
        )
    body = f"""
<p class="meta"><a href="../index.html">← All suggestions</a></p>
<section class="card">
  <p class="meta">
    <span class="badge {item.status}">{item.status}</span>
    · updated {_esc(item.updated)}
  </p>
  <h2>{_esc(item.title)}</h2>
  <p>{_esc(item.summary)}</p>
  <p class="meta">
    Monorepo branch: <code>{_esc(item.release.monorepo_branch)}</code>
    {f" · compared to <code>{_esc(item.release.compared_to_tag)}</code>" if item.release.compared_to_tag else ""}
    {f" · robot OS <code>{_esc(item.release.robot_os)}</code>" if item.release.robot_os else ""}
  </p>
  <p class="meta">Hardware: {_esc(", ".join(item.hardware_required) or "none listed")}</p>
  {"<h3>Related PRs</h3><ul>" + prs + "</ul>" if prs else ""}
  {"<h3>Harness commands</h3><pre>" + _esc(commands) + "</pre>" if commands else ""}
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

    # Keep a tiny nojekyll so GitHub Pages serves as static files.
    nojekyll = output_dir / ".nojekyll"
    nojekyll.write_text("", encoding="utf-8")
    written.append(nojekyll)
    return written
