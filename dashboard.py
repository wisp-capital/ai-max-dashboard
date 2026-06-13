#!/usr/bin/env python3
"""Cross-orchestrator status dashboard for ai-max workflow.

Reads STATUS.md files from configured orchestrator repos and produces a
unified markdown table of active initiatives, programs, and blocked work.

Usage:
    python3 dashboard.py                    # stdout
    python3 dashboard.py --output status.md # write to file
    python3 dashboard.py --json             # JSON output for piping
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class InitiativeRow:
    """A single initiative row from a STATUS.md table."""

    id: str = ""
    name: str = ""
    phase: str = ""
    maturity: str = ""
    linked_repos: str = ""
    next_action: str = ""
    blocked: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class OrchestratorState:
    """Aggregated state from one orchestrator."""

    name: str = ""
    path: str = ""
    active: int = 0
    programs: int = 0
    scheduled: int = 0
    queued: int = 0
    blocked: int = 0
    next_action: str = ""
    initiatives: list[InitiativeRow] = field(default_factory=list)
    error: str = ""


def read_orchestrator_paths() -> list[Path]:
    """Return list of orchestrator paths from config or env."""
    # Check env var first
    env_paths = os.environ.get("AIMAX_ORCHESTRATORS", "")
    if env_paths:
        return [Path(p.strip()) for p in env_paths.split(":") if p.strip()]

    # Check .orchestrators file in current dir or home
    for location in [Path(".orchestrators"), Path.home() / ".orchestrators"]:
        if location.exists():
            paths = [Path(p.strip()) for p in location.read_text().splitlines() if p.strip() and not p.strip().startswith("#")]
            return paths

    # Default: look for known orchestrators in ~/repos/
    home = Path.home() / "repos"
    defaults = [
        home / "cortex-orchestrator",
        home / "wisp-capital-orchestrator",
        home / "ktg-orchestrator",
    ]
    return [p for p in defaults if p.exists()]


def find_section(lines: list[str], header_pattern: str) -> Iterator[str]:
    """Yield lines from a markdown section until the next section."""
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("##") and re.search(header_pattern, stripped, re.IGNORECASE):
            in_section = True
            continue
        if in_section and stripped.startswith("##"):
            break
        if in_section:
            yield line


def parse_markdown_table(lines: Iterator[str]) -> list[dict[str, str]]:
    """Parse a markdown table into a list of row dicts."""
    rows = []
    header_cols: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        # Skip separator lines (| --- | --- |)
        if re.search(r"\|\s*[-:]+\s*", stripped):
            continue
        cells = [c.strip() for c in stripped.split("|")]
        cells = [c for c in cells if c]  # Remove empty from leading/trailing pipes
        if not cells:
            continue
        if not header_cols:
            header_cols = [c.lower().replace(" ", "_") for c in cells]
            continue
        row = {}
        for i, cell in enumerate(cells):
            key = header_cols[i] if i < len(header_cols) else f"col_{i}"
            row[key] = cell
        rows.append(row)
    return rows


def is_blocked(blocked_text: str) -> bool:
    """Detect if an initiative is blocked from the Blocked? column text."""
    lowered = blocked_text.lower()
    # Check for explicit yes/no, waiting states, or intentionally blocked
    return any(
        word in lowered
        for word in [
            "yes",
            "waiting",
            "blocked",
            "pending",
            "hold",
            "paused",
            "stalled",
        ]
    )


def parse_status_file(path: Path) -> OrchestratorState:
    """Parse a single STATUS.md file."""
    state = OrchestratorState(name=path.name, path=str(path))

    if not path.exists():
        state.error = f"STATUS.md not found: {path / 'STATUS.md'}"
        return state

    text = (path / "STATUS.md").read_text()
    lines = text.splitlines()

    # Parse active initiatives
    active_rows = parse_markdown_table(find_section(lines, r"active.initiatives"))
    state.active = len(active_rows)
    for row in active_rows:
        init = InitiativeRow(
            id=row.get("id", ""),
            name=row.get("name", row.get("initiative", "")),
            phase=row.get("phase", ""),
            maturity=row.get("maturity", ""),
            linked_repos=row.get("linked_repos", row.get("linked_repos", "")),
            next_action=row.get("next_action", row.get("next_action", "")),
            blocked=row.get("blocked?", row.get("blocked", "")),
            raw=row,
        )
        state.initiatives.append(init)
        if is_blocked(init.blocked):
            state.blocked += 1
        if not state.next_action and init.next_action:
            state.next_action = f"{init.name}: {init.next_action[:80]}"

    # Parse programs (optional)
    program_rows = parse_markdown_table(find_section(lines, r"active.programs"))
    state.programs = len(program_rows)

    # Parse scheduled/queued
    scheduled_rows = parse_markdown_table(find_section(lines, r"scheduled.initiatives"))
    state.scheduled = len(scheduled_rows)
    queued_rows = parse_markdown_table(find_section(lines, r"queued.initiatives"))
    state.queued = len(queued_rows)

    return state


def render_markdown(states: list[OrchestratorState]) -> str:
    """Render a unified markdown table."""
    lines = ["# Orchestrator Dashboard\n", "**Generated:** auto\n"]
    lines.append("| Orchestrator | Active | Programs | Scheduled | Queued | Blocked | Next Action |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in states:
        next_act = s.next_action[:70] if s.next_action else "—"
        lines.append(
            f"| {s.name} | {s.active} | {s.programs} | {s.scheduled} | {s.queued} | {s.blocked} | {next_act} |"
        )
    lines.append("")

    # Detail section
    lines.append("## Active Initiatives\n")
    for s in states:
        if not s.initiatives:
            continue
        lines.append(f"### {s.name}\n")
        for i in s.initiatives:
            blocked = " 🚫" if is_blocked(i.blocked) else ""
            lines.append(f"- **{i.name}** — {i.phase} | {i.maturity}{blocked}")
            if i.next_action:
                # Truncate very long next_action text
                action = i.next_action[:120]
                if len(i.next_action) > 120:
                    action += "..."
                lines.append(f"  - Next: {action}")
        lines.append("")

    return "\n".join(lines)


def render_json(states: list[OrchestratorState]) -> str:
    """Render JSON output."""
    return json.dumps([asdict(s) for s in states], indent=2, default=str)


def render_html(states: list[OrchestratorState]) -> str:
    """Render HTML output with inline CSS."""
    total_active = sum(s.active for s in states)
    total_programs = sum(s.programs for s in states)
    total_blocked = sum(s.blocked for s in states)
    total_scheduled = sum(s.scheduled for s in states)
    total_queued = sum(s.queued for s in states)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Orchestrator Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            line-height: 1.6;
            padding: 2rem;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #f0f6fc; margin-bottom: 0.5rem; font-size: 1.75rem; }
        .subtitle { color: #8b949e; margin-bottom: 1.5rem; font-size: 0.875rem; }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .stat-card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 1rem;
            text-align: center;
        }
        .stat-value { font-size: 2rem; font-weight: 700; color: #58a6ff; }
        .stat-label { font-size: 0.75rem; color: #8b949e; text-transform: uppercase; }
        .stat-value.blocked { color: #f85149; }
        .stat-value.programs { color: #a371f7; }
        .orchestrator {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            margin-bottom: 1.5rem;
            overflow: hidden;
        }
        .orch-header {
            background: #21262d;
            padding: 1rem 1.25rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.5rem;
        }
        .orch-name { font-size: 1.125rem; font-weight: 600; color: #f0f6fc; }
        .orch-badges { display: flex; gap: 0.5rem; flex-wrap: wrap; }
        .badge {
            font-size: 0.75rem;
            padding: 0.25rem 0.625rem;
            border-radius: 999px;
            font-weight: 500;
        }
        .badge-active { background: #238636; color: #fff; }
        .badge-blocked { background: #f85149; color: #fff; }
        .badge-program { background: #a371f7; color: #fff; }
        .badge-scheduled { background: #d29922; color: #1c1917; }
        .badge-queued { background: #2f81f7; color: #fff; }
        .badge-idle { background: #30363d; color: #8b949e; }
        .initiatives { padding: 0.75rem 1.25rem; }
        .initiative {
            border-left: 3px solid #30363d;
            padding: 0.75rem 1rem;
            margin-bottom: 0.75rem;
            background: #0d1117;
            border-radius: 0 8px 8px 0;
        }
        .initiative.blocked { border-left-color: #f85149; }
        .init-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 0.5rem;
            margin-bottom: 0.375rem;
        }
        .init-name { font-weight: 600; color: #f0f6fc; font-size: 0.9375rem; }
        .init-meta { font-size: 0.75rem; color: #8b949e; }
        .init-next {
            font-size: 0.8125rem;
            color: #8b949e;
            margin-top: 0.375rem;
            padding-top: 0.375rem;
            border-top: 1px solid #21262d;
        }
        .blocked-indicator {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #f85149;
            margin-left: 0.5rem;
            vertical-align: middle;
        }
        .empty-state {
            text-align: center;
            padding: 2rem;
            color: #8b949e;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
            margin-bottom: 2rem;
        }
        th, td {
            padding: 0.75rem 1rem;
            text-align: left;
            border-bottom: 1px solid #30363d;
        }
        th {
            background: #21262d;
            color: #8b949e;
            font-weight: 500;
            font-size: 0.75rem;
            text-transform: uppercase;
        }
        tr:hover td { background: #161b22; }
        .orch-link { color: #58a6ff; text-decoration: none; }
        .orch-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔥 Orchestrator Dashboard</h1>
        <p class="subtitle">""" + f"{total_active} active initiatives across {len(states)} orchestrators" + """</p>

        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">""" + str(total_active) + """</div>
                <div class="stat-label">Active</div>
            </div>
            <div class="stat-card">
                <div class="stat-value programs">""" + str(total_programs) + """</div>
                <div class="stat-label">Programs</div>
            </div>
            <div class="stat-card">
                <div class="stat-value blocked">""" + str(total_blocked) + """</div>
                <div class="stat-label">Blocked</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">""" + str(total_scheduled) + """</div>
                <div class="stat-label">Scheduled</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">""" + str(total_queued) + """</div>
                <div class="stat-label">Queued</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Orchestrator</th>
                    <th>Active</th>
                    <th>Programs</th>
                    <th>Scheduled</th>
                    <th>Queued</th>
                    <th>Blocked</th>
                    <th>Next Action</th>
                </tr>
            </thead>
            <tbody>
"""

    for s in states:
        blocked_class = ' class="blocked"' if s.blocked > 0 else ''
        next_act = s.next_action[:80] if s.next_action else "—"
        html += f"""                <tr{blocked_class}>
                    <td><strong>{s.name}</strong></td>
                    <td>{s.active}</td>
                    <td>{s.programs}</td>
                    <td>{s.scheduled}</td>
                    <td>{s.queued}</td>
                    <td>{'🚫 ' + str(s.blocked) if s.blocked else '—'}</td>
                    <td>{next_act}</td>
                </tr>
"""

    html += """            </tbody>
        </table>
"""

    for s in states:
        html += f"""        <div class="orchestrator">
            <div class="orch-header">
                <span class="orch-name">{s.name}</span>
                <div class="orch-badges">
"""
        if s.active:
            html += f'<span class="badge badge-active">{s.active} active</span>'
        if s.programs:
            html += f'<span class="badge badge-program">{s.programs} program</span>'
        if s.blocked:
            html += f'<span class="badge badge-blocked">{s.blocked} blocked</span>'
        if s.scheduled:
            html += f'<span class="badge badge-scheduled">{s.scheduled} scheduled</span>'
        if s.queued:
            html += f'<span class="badge badge-queued">{s.queued} queued</span>'
        if not any([s.active, s.programs, s.blocked, s.scheduled, s.queued]):
            html += '<span class="badge badge-idle">idle</span>'

        html += """                </div>
            </div>
            <div class="initiatives">
"""
        if not s.initiatives:
            html += '<div class="empty-state">No active initiatives</div>'
        else:
            for i in s.initiatives:
                blocked_class = ' blocked' if is_blocked(i.blocked) else ''
                html += f"""                <div class="initiative{blocked_class}">
                    <div class="init-header">
                        <span class="init-name">{i.name}
"""
                if is_blocked(i.blocked):
                    html += '<span class="blocked-indicator" title="Blocked"></span>'
                html += f"""</span>
                        <span class="init-meta">{i.phase} | {i.maturity}</span>
                    </div>
"""
                if i.next_action:
                    truncated = i.next_action[:200]
                    if len(i.next_action) > 200:
                        truncated += "..."
                    html += f'<div class="init-next">{truncated}</div>'
                html += """                </div>
"""

        html += """            </div>
        </div>
"""

    html += """    </div>
</body>
</html>"""

    return html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cross-orchestrator status dashboard")
    parser.add_argument("--output", "-o", type=Path, help="Write markdown output to file")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    parser.add_argument("--html", action="store_true", help="Output HTML instead of markdown")
    parser.add_argument("--config", "-c", type=Path, help="Path to .orchestrators config file")
    args = parser.parse_args(argv)

    paths = read_orchestrator_paths()
    if not paths:
        print("No orchestrators found. Set AIMAX_ORCHESTRATORS env var or create ~/.orchestrators", file=sys.stderr)
        return 1

    states = []
    for path in paths:
        state = parse_status_file(path)
        if state.error:
            print(f"Warning: {state.error}", file=sys.stderr)
        states.append(state)

    if args.json:
        output = render_json(states)
    elif args.html:
        output = render_html(states)
    else:
        output = render_markdown(states)

    if args.output:
        args.output.write_text(output)
        print(f"Dashboard written to {args.output}")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
