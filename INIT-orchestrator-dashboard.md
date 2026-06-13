# INIT — Orchestrator Dashboard

**Status:** Active — Build Phase
**Started:** 2026-06-13
**Repo:** ai-max-dashboard
**Classification:** Shallow (single tool, single repo, no cross-repo writes)
**Maturity target:** M2 (script runs, produces correct output, documented)

## Intent

Build a cross-orchestrator status dashboard that reads STATUS.md files from all ai-max orchestrator repos and produces a unified, human-readable summary. The dashboard lives outside ai-max (as requested) so it can evolve independently of the framework.

## Scenarios

### S-001: Dashboard reads multiple orchestrators
Given a configuration of orchestrator paths, the dashboard script reads each orchestrator's STATUS.md, extracts active initiatives, and produces a unified table.

### S-002: Dashboard handles STATUS.md format variation
Different orchestrators have different STATUS.md formats (wisp-capital has detailed strategy rows, cortex is moderate, ktg is minimal). The dashboard parses each correctly without requiring a fixed schema.

### S-003: Dashboard is runnable from anywhere
The script can be run from any directory and still find all orchestrators. Configuration is explicit (env var or config file) rather than hardcoded.

## Phases

### Phase 1: Write the dashboard script
- Read orchestrator paths from a config file or env var
- Parse each STATUS.md for active initiatives section
- Extract: orchestrator name, initiative count, blocked count, next actions
- Output: markdown table to stdout, optionally write to file

### Phase 2: Test with real orchestrators
- Run against cortex-orchestrator, wisp-capital-orchestrator, ktg-orchestrator
- Verify output matches manual inspection of each STATUS.md
- Fix parsing edge cases

### Phase 3: Add Justfile and README
- Add `just dashboard` command
- Document usage in README.md
- Add configuration examples

### Phase 4: Verify and archive
- Run final test against all orchestrators
- Commit and push
- Archive INIT

## Risk & Mitigation

- **Risk:** STATUS.md format changes break the parser.
  - **Mitigation:** Parser looks for section headers ("## Active initiatives") rather than assuming table position. Fails gracefully with a warning if a section is not found.
- **Risk:** Missing or stale orchestrator paths.
  - **Mitigation:** Config file is explicit. Missing paths are skipped with a warning, not a crash.
