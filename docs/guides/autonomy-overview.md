# Autonomy Guardrails Overview

This guide describes the autonomy hardening added on `feature/autonomy`: what changed, why it matters, and how to use the new controls safely.

## What was added

The autonomy work introduces guardrails and budgets across the main failure-prone runtime paths:

- Monologue safety floor (iteration/runtime/error caps)
- Tool argument payload controls (hard size cap + spill-to-file rewrite)
- Code execution reliability controls (timeouts, output bounds, dump path)
- Subordinate delegation limits (depth, calls/turn, runtime)
- Queue backpressure controls (size limits + overflow policy)
- Memory load guardrails (query/limit/response clamps)
- History compression tuning controls (ratios + pass limits)
- Runtime budgets (turn/task/subordinate caps)
- Execution routing architecture modes (Tool-First/Tool-First fallback/Hybrid/Model-First)

Guard switches are provided for staged adoption:

- newly introduced guard switches default to backward-compatible `off` unless explicitly enabled
- recommended production posture is to enable all guard switches

This allows gradual rollout for existing deployments while still supporting strict defaults in profile examples.

## Where to tune

You can tune autonomy settings in three places:

1. Settings UI: **Agent Settings -> Fine-Tuning**
2. `.env` keys: `A0_SET_<setting_name>`
3. Profile examples: `docs/setup/env-examples/`

Guard-specific detail:

- `autonomy-guards-reference.md` (what each guard does, risk when disabled)
- `execution-routing-modes.md` (how plain-text vs tool routing is selected)

## Fine-Tuning panel

A dedicated **Fine-Tuning** panel is available in Settings with sectioned controls and field descriptions. It exposes the main autonomy knobs with typed editors:

- Number controls for caps and limits
- Sliders for ratio knobs
- Toggles for booleans
- Text areas for model/global kwargs

This is the recommended path for interactive tuning and validation.

When `.env` contains `A0_SET_<setting_name>`, that key is treated as an active override at read time. The Fine-Tuning panel now shows an **Active .env Overrides Detected** section that lists:

- setting key
- `.env` value currently in force
- current UI value

For each listed key, use **Overwrite .env with UI value** to explicitly persist the current UI value into `.env` so the override remains aligned.

Fine-Tuning panel preview:

![Fine-Tuning Settings Panel](../res/usage/autonomy-fine-tuning-panel.png)

## Important behavior notes

### Settings precedence and persistence

Settings precedence is:

1. `.env` overrides (`A0_SET_*`) at read time
2. `settings.json` values saved from the UI
3. runtime defaults

Implication: a normal UI save updates `settings.json`, but any key with an active `A0_SET_*` override will resolve back to the `.env` value when settings are read again. Use the explicit overwrite action in Fine-Tuning when you want a UI change to become the new `.env` source of truth.

For full inheritance order across global/profile/project scopes, see `settings-precedence-hierarchy.md`.

### Why Fine-Tuning differs from API keys/secrets

Most Fine-Tuning/autonomy knobs are persisted in `settings.json` by design, while API keys and a few sensitive runtime fields are persisted via `.env`/secret paths.

Rationale:

- autonomy knobs are operational tuning values that may change frequently by environment
- `.env` is treated as deployment-level override source (`A0_SET_*`) with highest precedence
- secrets should avoid plain settings persistence and remain in secret-oriented storage paths

To reduce friction around persistence scope, Fine-Tuning surfaces per-setting inline **Save this value to selected target** actions next to affected controls.
Fine-Tuning also includes a top-level **apply target** selector so saves can target global, profile, project, project+profile, or explicit `.env` lock scope.

### Execution routing defaults

Execution routing modes are strictly opt-in:

- default mode is `tool_first` (legacy strict JSON-tool contract)
- no routing behavior changes occur unless new execution-mode knobs are explicitly enabled
- risky-intent tool-route enforcement can stay enabled even in `hybrid` or `model_first`

### Tool payload spill is not chunking

`tool_args_spill_threshold_chars` spills large string fields to files and rewrites them for transport, then resolves them before execution. It does not split a single payload into multiple tool calls.

### File-write reliability policy

When `A0_SET_code_exec_prefer_python_file_write=true`:

- terminal heredoc writes are blocked or converted to Python file writes (when command form is safely convertible)
- malformed/unterminated heredocs fail fast with explicit warnings

This prevents common infinite retry loops caused by truncated heredoc tool payloads.

### Code input size guard

`A0_SET_code_exec_max_input_chars` sets an upper bound for `code_execution_tool` payload size (`runtime=python|nodejs|terminal`).

- oversized `code` payloads are rejected early with a clear warning
- Python payloads get a preflight syntax check before execution

This helps surface truncation/malformed payload issues early instead of failing deep in runtime execution.

For regressive overwrite loop handling, these knobs tune abort behavior:

- `A0_SET_code_exec_regressive_guard_retry_threshold`
- `A0_SET_code_exec_regressive_guard_retry_window_seconds`

## Operational defaults

A practical starting point is the balanced profile in `docs/setup/env-examples/profile_balanced_production.env`.

From there:

- tighten limits for safety-first deployments
- raise selected limits for large/throughput-heavy workloads
- change one knob family at a time and validate before broader rollout

## Next references

- Full setting-by-setting reference: `autonomy-knobs-reference.md`
- Guard-by-guard reference: `autonomy-guards-reference.md`
- Execution routing architecture and rollout: `execution-routing-modes.md`
- Scope inheritance and lock semantics: `settings-precedence-hierarchy.md`
- Validation and soak workflow: `autonomy-testing.md`
- Ready-to-apply profile examples: `../setup/env-examples/`
