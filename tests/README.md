# Test Tiers

Tests are grouped by markers defined in `pytest.ini`:

- `tier1` fast deterministic tests for PR gating
- `tier2` heavier integration tests
- `tier3` container/e2e/soak tests

## Run commands

- Tier 1: `python3 -m pytest -m tier1 tests`
- Tier 2: `python3 -m pytest -m tier2 tests`
- Tier 3: `python3 -m pytest -m tier3 tests`

When adding tests for autonomy/guardrails/execution routing, default to `tier1` unless the test requires external processes or long-running scenarios.
