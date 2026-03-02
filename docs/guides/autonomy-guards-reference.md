# Autonomy Guards Reference

This guide is the guard-focused companion to `autonomy-knobs-reference.md`.
Execution-routing architecture modes are documented separately in `execution-routing-modes.md`.

It documents:

- all guard mechanisms introduced during `feature/autonomy`
- where each guard is enforced
- switch/threshold knobs
- behavior and risk when disabled

## Guard Families

## 1) Monologue Loop Guards

Location: `agent.py`

- iteration cap
- runtime cap
- consecutive misformat cap
- consecutive repairable-error cap

Switch:

- `agent_guardrails_enabled`

Threshold knobs:

- `agent_max_iterations`
- `agent_max_runtime_seconds`
- `agent_max_consecutive_misformats`
- `agent_max_consecutive_repairable_errors`

Risk when disabled:

- runaway turns and prolonged self-repair loops

## 2) Missing Context Hard-Stop

Locations:

- `python/api/chat_files_path_get.py`
- `agent.py` tool-result hard-stop handling

Switch:

- `agent_guard_context_hard_stop_enabled`

Behavior:

- if context id is missing, request is tagged non-retryable and current turn terminates

Risk when disabled:

- repeated invalid retries after context loss, often followed by tool spam

## 3) Repeated Tool Action Breaker

Location: `agent.py`

Switch:

- `agent_guard_repeated_tool_action_enabled`

Threshold knobs:

- `tool_repeat_signature_threshold`
- `tool_repeat_signature_window_seconds`

Behavior:

- hashes normalized tool name + argument signature and blocks repeated identical actions in the window

Risk when disabled:

- repeated equivalent tool calls can continue indefinitely in one turn

## 4) Subordinate Delegation Guards

Location: `python/tools/call_subordinate.py`

Switch:

- `subordinate_guardrails_enabled`

Threshold knobs:

- `subordinate_max_depth`
- `subordinate_max_calls_per_turn`
- `subordinate_max_runtime_seconds`

Risk when disabled:

- deep or repeated subordinate cascades with high runtime cost

## 5) Terminal Input Integrity Guards

Location: `python/tools/code_execution_tool.py`

Switches:

- `code_exec_guard_unterminated_heredoc_enabled`
- `code_exec_guard_unbalanced_shell_quote_enabled`

Behavior:

- rejects truncated heredoc and malformed quote cases before execution

Risk when disabled:

- shell waiting-mode hangs and repeated recovery attempts

## 6) Repetitive Read Guards

Location: `python/tools/code_execution_tool.py`

Switches:

- `code_exec_guard_repetitive_terminal_read_enabled`
- `code_exec_guard_repetitive_file_read_enabled`
- `code_exec_guard_simple_cat_direct_read_enabled`

Behavior:

- limits repeated read-only terminal command loops
- limits repeated identical direct file reads
- routes simple `cat /path` to deterministic file-read path

Risk when disabled:

- higher chance of no-op read loops

## 7) File Write Recovery Guards

Location: `python/tools/code_execution_tool.py`

Switches:

- `code_exec_guard_regressive_overwrite_enabled`
- `code_exec_guard_write_verify_enabled`

Threshold knobs:

- `code_exec_regressive_guard_retry_threshold`
- `code_exec_regressive_guard_retry_window_seconds`

Behavior:

- blocks likely regressive append=false overwrites
- activates recovery mode and retry ceilings for guarded failures
- verifies expected bytes after overwrite

Risk when disabled:

- silent truncation and repeated destructive rewrite attempts

## 8) Same-File Ceilings and Strategy Blocking

Location: `python/tools/code_execution_tool.py`

Switches:

- `code_exec_guard_same_file_op_ceiling_enabled`
- `code_exec_guard_strategy_block_enabled`

Threshold knobs:

- `code_exec_same_file_read_ceiling`
- `code_exec_same_file_write_ceiling`
- `code_exec_file_op_window_seconds`
- `code_exec_strategy_block_ttl_seconds`

Behavior:

- caps repeated same-file read/write operations
- blocks same strategy class after guard hit (temporary TTL)

Risk when disabled:

- persistent same-path churn and same-strategy retries

## 9) Capability Discovery Hardening

Locations:

- `python/tools/capabilities.py`
- `prompts/agent.system.tools.py`
- `prompts/fw.tool_not_found.md`

Behavior:

- runtime-discovered comprehensive tool + skill inventory
- explicit detailed per-capability documentation fetch
- unknown-tool flow now points model to discovery, not guess-retry

Operational note:

- this is not a kill-switch guard, but it materially reduces failure descent caused by partial/abbreviated tool context

---

## Recommended Rollout

1. Enable all guard switches in staging.
2. Run autonomy test scenarios from `autonomy-testing.md`.
3. Start with conservative thresholds (lower repeat ceilings).
4. Relax only after observing stable behavior.

---

## Known Trade-offs

- More guards enabled -> safer behavior, more early turn termination when requests are malformed.
- Fewer guards enabled -> more permissive behavior, higher chance of repeated retries and runtime drift.

Use the Fine-Tuning panel to match strictness to workload profile.
Use `execution-routing-modes.md` when tuning plain-text vs tool-route behavior.
