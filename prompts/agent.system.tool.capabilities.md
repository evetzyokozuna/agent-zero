### capabilities

runtime capability discovery and detailed docs for tools and skills
use this when tool availability is uncertain, tool not found occurs, or you need exact argument guidance

methods:
- `capabilities:list` -> comprehensive runtime-discovered inventory of tools and skills
- `capabilities:describe` -> verbose detail for one tool or skill

important:
- if a tool is missing/unclear, call `capabilities:list` first before retrying with guessed tool names
- for file operations, `code_execution_tool` supports multiple explicit modes; use `capabilities:describe` for exact constraints
- when a skill may help, list capabilities then describe the exact skill name before executing

usage:

1) list capabilities
~~~json
{
    "thoughts": [
        "Need authoritative inventory before choosing a tool."
    ],
    "headline": "Listing available tools and skills",
    "tool_name": "capabilities:list"
}
~~~

2) describe one capability
~~~json
{
    "thoughts": [
        "Need exact argument and usage details for this capability."
    ],
    "headline": "Getting detailed capability guide",
    "tool_name": "capabilities:describe",
    "tool_args": {
        "target": "code_execution_tool"
    }
}
~~~
