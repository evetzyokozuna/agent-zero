# Autonomy Knobs Reference

This reference documents autonomy and guardrail settings introduced in `feature/autonomy`.

All keys use `A0_SET_<setting_name>`.

## UI and `.env` override behavior

- If `A0_SET_<setting_name>` exists in `.env`, it overrides UI-saved `settings.json` for that key at read time.
- `.env` is an explicit lock layer; use it for deployment pinning, not polymorphic inheritance.
- Fine-Tuning surfaces active overrides in an **Active .env Overrides Detected** panel.
- Use **Overwrite .env with UI value** to explicitly update the corresponding `A0_SET_*` key from the current UI value.
- Use a normal UI save when no `.env` override is active for that key.

For full global/profile/project inheritance order, see `settings-precedence-hierarchy.md`.

Example:

- `A0_SET_agent_max_iterations=100`
- `A0_SET_queue_drop_policy=reject`

---

## Guard Switches (Adoption Controls)

These switches let you keep upgraded systems behavior-compatible while selectively enabling hardening.

Recommended for production: enable all (`true`).
Backward-compatibility default in runtime for newly introduced switches: `false`.

- `agent_guardrails_enabled`
  - Master switch for monologue iteration/runtime/misformat guardrails.
  - Risk when off: runaway turn loops.
- `agent_guard_context_hard_stop_enabled`
  - Hard-stops turn on missing context id failures.
  - Risk when off: repeated invalid retries after context loss.
- `agent_guard_repeated_tool_action_enabled`
  - Enables repeated identical tool action breaker.
  - Risk when off: high-frequency retry attractor loops.
- `subordinate_guardrails_enabled`
  - Enables subordinate depth/call/runtime guardrails.
  - Risk when off: delegation cascades and runaway subordinate chains.
- `code_exec_guard_unterminated_heredoc_enabled`
  - Rejects truncated heredoc terminal commands.
  - Risk when off: shell enters waiting mode and loops.
- `code_exec_guard_unbalanced_shell_quote_enabled`
  - Rejects malformed quoted shell commands.
  - Risk when off: waiting-mode command hangs and retries.
- `code_exec_guard_repetitive_terminal_read_enabled`
  - Detects repeated identical read-only terminal commands.
  - Risk when off: read spam loops.
- `code_exec_guard_repetitive_file_read_enabled`
  - Detects repeated identical direct file reads.
  - Risk when off: no-op file read churn.
- `code_exec_guard_regressive_overwrite_enabled`
  - Blocks likely regressive full-overwrite loops and triggers recovery mode.
  - Risk when off: destructive shrinking rewrites.
- `code_exec_guard_write_verify_enabled`
  - Verifies expected/actual bytes after overwrite.
  - Risk when off: silent partial writes.
- `code_exec_guard_same_file_op_ceiling_enabled`
  - Caps same-file read/write repeat attempts in a window.
  - Risk when off: same-path operation churn.
- `code_exec_guard_strategy_block_enabled`
  - After guardrail hit, blocks same strategy class temporarily.
  - Risk when off: repeated equivalent failing strategy.
- `code_exec_guard_simple_cat_direct_read_enabled`
  - Routes simple `cat /path` calls to deterministic file-read flow.
  - Risk when off: shell read behavior can be less deterministic under load.

---

## 1) Monologue Safety Floor

- `agent_max_iterations`
- `agent_max_runtime_seconds`
- `agent_max_consecutive_misformats`
- `agent_max_consecutive_repairable_errors`

Lower values stop loops sooner but may cut off valid long tasks.
Higher values improve tolerance but increase runaway risk when guard switches are off.

---

## 2) Tool Action Loop Breakers

- `tool_repeat_signature_threshold`
  - Allowed repeats of identical tool signature per window.
  - Lower: stricter anti-looping. Higher: more retry tolerance.
- `tool_repeat_signature_window_seconds`
  - Sliding window for repeat counting.
  - Larger: catches slower loops. Smaller: less aggressive.

---

## 3) Tool Argument Payload Controls

- `tool_args_max_chars`
- `tool_args_spill_threshold_chars`
- `tool_args_spill_dir`
- `tool_args_autorewrite_enabled`

Notes:

- Spill behavior is rewrite/resolve, not multi-call chunking.
- Oversized payloads above `tool_args_max_chars` are rejected.

---

## 4) Code Execution Reliability and File Guards

Core runtime controls:

- `code_exec_first_output_timeout`
- `code_exec_between_output_timeout`
- `code_exec_max_exec_timeout`
- `code_exec_dialog_timeout`
- `code_exec_output_max_chars`
- `code_exec_auto_dump_large_output`
- `code_exec_dump_dir`
- `code_exec_prefer_python_file_write`
- `code_exec_max_input_chars`

Regressive overwrite controls:

- `code_exec_regressive_guard_retry_threshold`
- `code_exec_regressive_guard_retry_window_seconds`

Same-file ceilings and strategy windows:

- `code_exec_same_file_read_ceiling`
- `code_exec_same_file_write_ceiling`
- `code_exec_file_op_window_seconds`
- `code_exec_strategy_block_ttl_seconds`

Expected outcomes:

- Lower ceilings / lower retry thresholds: fail fast, fewer loops, higher intervention rate.
- Higher ceilings / higher thresholds: more self-repair attempts, higher loop risk.
- Larger windows/TTL: stronger suppression of repeated failure patterns.

---

## 5) Subordinate Delegation Controls

- `subordinate_max_depth`
- `subordinate_max_calls_per_turn`
- `subordinate_max_runtime_seconds`

---

## 6) Queue / Backpressure Controls

- `queue_max_items`
- `queue_max_total_chars`
- `queue_drop_policy` (`drop_oldest`, `drop_newest`, `reject`)
- `queue_send_all_max_items`

---

## 7) Memory Load Guardrails

- `memory_load_limit_max`
- `memory_load_query_max_chars`
- `memory_load_response_max_chars`

---

## 8) History Compression Tuning

- `history_compression_target_ratio`
- `history_current_topic_ratio`
- `history_topic_ratio`
- `history_bulk_ratio`
- `history_attention_current_ratio`
- `history_attention_past_ratio`
- `history_compress_max_passes`

---

## 9) Runtime Budgets

- `runtime_turn_budget_seconds` (`0` disables)
- `runtime_task_budget_seconds` (`0` disables)
- `runtime_subordinate_budget_seconds` (`0` disables)

---

## 10) Model Call Parameters (commonly used with autonomy)

- `chat_model_kwargs`
- `litellm_global_kwargs`

Common use:

- Set output/token and timeout behavior explicitly for deterministic tool-call generation.

---

## 11) Remaining Degradation Recovery Controls (Priorities 7-10)

Retry policy split by error class:

- `agent_retry_split_by_error_class_enabled`
- `agent_transient_error_max_retries`
- `agent_transient_error_retry_delay_seconds`
- `agent_critical_error_max_retries`
- `agent_critical_error_retry_delay_seconds`

Tool-call preflight validator:

- `code_exec_tool_preflight_enabled`

Deterministic critical-file mode:

- `code_exec_deterministic_critical_mode_enabled`
- `code_exec_deterministic_critical_patterns`
- `code_exec_deterministic_critical_window_seconds`
- `code_exec_deterministic_critical_break_after_write`

Degradation telemetry auto-abort:

- `agent_degradation_auto_abort_enabled`
- `agent_tool_call_ceiling_per_turn`
- `agent_guardrail_hits_ceiling_per_minute`
- `agent_missing_context_errors_ceiling_per_turn`

---

## 12) Execution Routing Architecture Modes

- `agent_execution_mode`
  - `tool_first` (default, current strict behavior)
  - `tool_first_fallback` (strict first, optional fallback after misformat threshold)
  - `hybrid` (plain text or tool call)
  - `model_first` (plain text first; tools for execution)
- `agent_execution_allow_plain_text_response`
  - Master gate for accepting non-JSON assistant output in non-default modes.
  - Default `false` preserves strict contract.
- `agent_execution_require_tool_for_risky_intents`
  - Forces tool route for risky/executable intents in Hybrid/Model-First modes.
  - Recommended `true` for production.
- `agent_tool_first_fallback_after_misformats`
  - Consecutive misformat threshold before fallback activation in `tool_first_fallback`.
- `agent_execution_risky_intent_regex`
  - Regex used to classify requests as risky/executable.

Expected outcomes:

- keep defaults untouched -> no behavior change from existing deployments
- enable plain-text path in hybrid/model-first -> better conversational handling, with policyable execution safety
- tune risky-intent regex conservatively to avoid accidental plain-text acceptance for executable asks

---

## Tuning Workflow

1. Start from `docs/setup/env-examples/profile_balanced_production.env`.
2. Enable guard switches first.
3. Tune thresholds/windows one family at a time.
4. Validate with `guides/autonomy-testing.md`.
5. Promote stable values into deployment profile.
