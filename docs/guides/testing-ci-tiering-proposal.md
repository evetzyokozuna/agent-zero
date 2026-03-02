# Tiered CI Testing Proposal

This proposal defines a practical CI strategy for autonomy/execution features using three test tiers.

## Goals

- keep PR feedback fast
- gate merges on deterministic coverage
- run heavier network/container checks on schedule

## Tiers

### Tier 1 (required on PR)

Scope:

- deterministic unit tests
- in-process integration tests
- static template contract tests

Command:

`python3 -m pytest -m tier1 tests`

Target runtime:

- under 5 minutes

### Tier 2 (optional PR + required nightly)

Scope:

- heavier integration tests with local ASGI/WS servers
- network/process tests that are still deterministic

Command:

`python3 -m pytest -m tier2 tests`

### Tier 3 (nightly/manual)

Scope:

- container-based smoke and soak scenarios
- long-running behavioral stability checks

Command:

`python3 -m pytest -m tier3 tests`

## Suggested GitHub Actions layout

- `ci-tier1.yml`: trigger on pull_request + push to protected branches
- `ci-tier2.yml`: trigger on workflow_dispatch + nightly schedule
- `ci-tier3.yml`: trigger on nightly + manual only

## Initial autonomy/execution test ownership

Tier 1 now covers:

- execution-routing mode logic
- prompt contract switching by mode
- execution-mode settings defaults and env override behavior
- fine-tuning template controls for execution routing + inline env persist actions

Tier 2/Tier 3 should add:

- API-level end-to-end execution mode behavior
- dockerized behavior/guardrail soak matrix
