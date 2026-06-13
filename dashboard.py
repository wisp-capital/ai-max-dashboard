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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cross-orchestrator status dashboard")
    parser.add_argument("--output", "-o", type=Path, help="Write markdown output to file")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
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
