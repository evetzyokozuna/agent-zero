# Settings Precedence and Inheritance

This guide defines how Agent Zero resolves settings across global, profile, project, and environment lock layers.

## Core policy

- inheritance is evaluated from general to specialized
- specialized layers override generalized layers
- `.env` `A0_SET_*` is an explicit lock layer and always wins unless removed

## Effective precedence order

Non-lock layers (general -> specialized):

1. defaults
2. global `usr/settings.json`
3. built-in profile `agents/<profile>/settings.json`
4. user profile `usr/agents/<profile>/settings.json`
5. project `.a0proj/settings.json`
6. project + profile `.a0proj/agents/<profile>/settings.json`

Lock layer:

7. `.env` `A0_SET_<key>`

## Why `.env` stays highest

`.env` is deployment/operator control. It is intentionally treated as a lock source so environments can pin safety or platform policies regardless of UI writes.

## Fine-Tuning implications

- saving to global/profile/project scopes follows inheritance semantics above
- saving to `.env` writes a lock override that supersedes all scopes
- if a key appears under active `.env` overrides, changing lower scopes will not affect runtime until the lock is removed or changed

## Practical guidance

- use global/profile/project scopes for polymorphic configuration
- use `.env` only for true deployment locks
- avoid broad `A0_SET_*` lock profiles when you need per-profile or per-project variation

## Example files

See example non-lock settings overlays:

- `docs/setup/settings-examples/global-settings.example.json`
- `docs/setup/settings-examples/profile-settings.example.json`
- `docs/setup/settings-examples/project-profile-settings.example.json`
