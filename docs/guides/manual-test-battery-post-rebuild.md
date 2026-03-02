# Manual Test Battery (Post-Rebuild)

This checklist captures the remaining non-fully-automatable validation after a fresh rebuild/redeploy.

## Scope

- settings inheritance and lock semantics across global/profile/project/env layers
- fine-tuning UX clarity for scope targeting and lock visibility
- execution routing behavior quality under real conversational load
- long-running degradation resilience and recovery behavior

## Environment Preconditions

- container rebuilt from latest `feature/autonomy`
- preserved data volumes reattached:
  - `/a0/usr`
  - `/app/work_dir`
  - `/app/memory`
- health checks green
- active profile and project contexts available for scope testing

## A) Settings Hierarchy and Persistence

1. **Global baseline write**
   - Set `agent_execution_mode=tool_first` using Fine-Tuning apply target `Global`.
   - Confirm persisted value in `usr/settings.json`.
2. **Profile override write**
   - Set same key to `hybrid` using apply target `Profile`.
   - Confirm persisted value in `usr/agents/<profile>/settings.json`.
3. **Project+profile override write**
   - Set same key to `model_first` using apply target `Project + Profile`.
   - Confirm persisted value in `.a0proj/agents/<profile>/settings.json`.
4. **Effective precedence check**
   - With no env lock, confirm effective runtime value is project+profile (most specialized non-env scope).
5. **Env lock check**
   - Set `A0_SET_agent_execution_mode=tool_first` via apply target `Environment lock`.
   - Confirm runtime uses lock value even when lower scopes differ.
6. **Lock removal recovery**
   - Remove/unset `A0_SET_agent_execution_mode`.
   - Confirm effective value falls back to most specialized non-env layer.

## B) Fine-Tuning UX and Clarity

1. Verify apply target selector copy clearly distinguishes:
   - global/profile/project/project+profile/env lock
2. Verify per-field save action respects selected target.
3. Verify active env override indicator and value display are correct.
4. Verify error handling for missing project/profile target inputs is clear.

## C) Execution Routing Behavioral Validation

For each mode (`tool_first`, `tool_first_fallback`, `hybrid`, `model_first`):

1. **Informational prompt**: "Explain what changed in settings precedence."
2. **Executable prompt**: "Edit Today.md with a single bullet."
3. With risky-intent enforcement enabled:
   - informational asks can use plain text where mode allows
   - executable asks require tool route
4. With `tool_first_fallback`:
   - verify fallback triggers after configured misformat threshold
   - verify no runaway misformat spiral

## D) Degradation and Stability

1. 30-minute mixed workload soak:
   - conversational + tool operations + file reads/writes
2. Confirm:
   - no repeated context-loss churn
   - no persistent repeated-action loops
   - no stale-epoch UI parsing regressions
3. Capture:
   - key log excerpts
   - guardrail trigger counts
   - any recovered vs unrecovered incidents

## E) Health Advisor Regression Pass

1. Switch to `health_advisor` profile.
2. Verify health log tool flows still function with new scoped settings behavior.
3. Confirm no cross-profile settings contamination.

## Evidence Capture

For each test case capture:

- active apply target
- relevant key/value snapshots per layer
- prompt/input and observed result
- pass/fail and notes
- timestamped logs/screenshots
