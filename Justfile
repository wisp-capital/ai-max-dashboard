# Justfile — ai-max-dashboard

# Default: show dashboard
_default:
    @just --list

# Run the dashboard and print to stdout
dashboard:
    python3 dashboard.py

# Run dashboard and write to DASHBOARD.md
update:
    python3 dashboard.py --output DASHBOARD.md

# Show dashboard as JSON
json:
    python3 dashboard.py --json
