# Execution Routing Modes

This guide explains the execution architecture modes that control how Agent Zero routes model output between:

- plain-text answers
- JSON tool calls

All non-default behavior is explicit opt-in. If nothing is changed, runtime behavior remains the current strict Tool-First contract.

## Why this exists

The legacy architecture assumes each assistant turn is primarily a tool envelope. That yields deterministic execution but can create user-experience friction for simple informational prompts.

Execution routing modes provide controlled alternatives while preserving safety for executable intents.

### Why higher modes matter for capable models

Strict Tool-First is excellent for deterministic execution pipelines, but it can constrain higher-order model behavior in practice:

- it forces every response through a narrow JSON-action contract even when no execution is needed
- it can turn otherwise-correct natural-language reasoning into a formatting failure path
- it can bias model behavior toward "find a tool call shape" instead of "best direct answer first"
- it can reduce fluidity for exploratory/creative tasks where the model should think and explain before acting

For stronger models, this often appears as capability suppression rather than capability absence. The model can reason well, but the protocol only rewards one output form.

`hybrid` and `model_first` modes are intended to remove that bottleneck while still enforcing explicit tool routing for risky/executable operations.

## Modes

### 1) `tool_first` (default, backward-compatible)

- Behavior: strict JSON tool-envelope expectation
- Plain-text assistant output: treated as misformat
- Risk posture: strongest deterministic enforcement

### 2) `tool_first_fallback`

- Behavior: starts as strict Tool-First
- Optional fallback: accept plain text only after N consecutive misformats
- Goal: recover from repeated formatting spirals without changing default semantics

### 3) `hybrid`

- Behavior: accepts either plain-text response or JSON tool call
- Typical use: mixed conversational + execution workloads
- Safety gate: can still require tool route for risky intents
- Capability effect: preserves room for richer explanation/planning before execution

### 4) `model_first`

- Behavior: plain text preferred for non-executable asks, tools used when execution is needed
- Typical use: conversational-first UX with guarded execution path
- Safety gate: can still require tool route for risky intents
- Capability effect: best fit when you want maximum reasoning/creative fluency with explicit execution controls

## Safety gate for risky intents

When `agent_execution_require_tool_for_risky_intents=true`, plain-text-only responses are blocked for prompts classified as executable/risky (for example file writes/deletes or shell-command requests). In those cases, the model must emit a JSON tool call.

Risk classification uses `agent_execution_risky_intent_regex`.

## Settings

All keys support `A0_SET_<setting_name>` env overrides.

- `agent_execution_mode`
  - Values: `tool_first`, `tool_first_fallback`, `hybrid`, `model_first`
  - Default: `tool_first`
- `agent_execution_allow_plain_text_response`
  - Enables non-JSON acceptance paths for non-default modes
  - Default: `false`
- `agent_execution_require_tool_for_risky_intents`
  - Forces tool route for risky/executable intents
  - Default: `true`
- `agent_tool_first_fallback_after_misformats`
  - Used by `tool_first_fallback` mode
  - Default: `2`
- `agent_execution_risky_intent_regex`
  - Regex classifier for risky/executable user intent
  - Default includes write/edit/delete/run/shell/command tokens

## Fine-Tuning behavior

Fine-Tuning exposes an **Execution Routing Modes (Opt-In)** section with:

- mode selector
- plain-text path master toggle
- risky-intent tool-route toggle
- tool-first fallback misformat threshold
- risky-intent regex editor

Fine-Tuning also exposes a **Fine-Tuning apply target** selector (global/profile/project/project+profile/env lock) so persistence scope is explicit.

This section is opt-in by design and follows the same `.env` lock behavior as other autonomy controls.

For complete inheritance order and lock semantics, see `settings-precedence-hierarchy.md`.

## Suggested rollout

1. Keep `tool_first` in production baseline.
2. Enable `tool_first_fallback` in a test environment first.
3. If needed, trial `hybrid` with `agent_execution_require_tool_for_risky_intents=true`.
4. Move to `model_first` only after validating execution-intent routing and observability.

## Choosing by objective

- prefer `tool_first` when strict deterministic action envelopes are primary
- prefer `hybrid` when you need both reliable execution and stronger conversational/creative capability
- prefer `model_first` when your highest priority is reasoning fluency and you still enforce tool routing for risky intents

## Test focus checklist

- Informational prompts return plain text only when expected by mode/toggles.
- File-write or shell-command intents are forced to tool route when safety gate is on.
- Misformat loops in `tool_first_fallback` break into deterministic plain-text completion after threshold.
- Default `tool_first` behavior remains unchanged after deploy when no new settings are enabled.
