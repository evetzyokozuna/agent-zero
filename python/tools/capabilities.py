import os
from pathlib import Path

from python.helpers.tool import Tool, Response
from python.helpers import files, skills, subagents


class Capabilities(Tool):
    async def execute(self, **kwargs) -> Response:
        method = (self.method or "list").strip().lower()
        if method == "list":
            return Response(message=self._list_capabilities(), break_loop=False)
        if method == "describe":
            target = str(kwargs.get("target", "")).strip()
            if not target:
                msg = (
                    "capabilities:describe requires `target` (tool or skill name). "
                    "Example: capabilities:describe target='code_execution_tool'"
                )
                return Response(message=msg, break_loop=False)
            return Response(message=self._describe_target(target), break_loop=False)
        return Response(
            message=(
                f"Unknown capabilities method '{method}'. "
                "Use `capabilities:list` or `capabilities:describe`."
            ),
            break_loop=False,
        )

    def _list_capabilities(self) -> str:
        tool_names = self._discover_tool_names()
        # Make multi-mode capabilities explicit to prevent hidden file-read/write behavior.
        if "code_execution_tool" in tool_names:
            tool_names.extend(
                [
                    "code_execution_tool:file_read",
                    "code_execution_tool:file_write",
                    "code_execution_tool:terminal",
                    "code_execution_tool:python",
                    "code_execution_tool:nodejs",
                    "code_execution_tool:output",
                ]
            )
        tool_names = sorted(set(tool_names))

        skill_items = skills.list_skills(agent=self.agent)
        skill_names = sorted(s.name for s in skill_items if s.name)

        tool_lines = "\n".join(f"- `{name}`" for name in tool_names) or "- (none)"
        skill_lines = "\n".join(f"- `{name}`" for name in skill_names) or "- (none)"

        return (
            "Comprehensive capability index (runtime-discovered):\n\n"
            "## Tools\n"
            f"{tool_lines}\n\n"
            "## Skills\n"
            f"{skill_lines}\n\n"
            "Use `capabilities:describe` with a specific tool/skill name for verbose detail."
        )

    def _describe_target(self, target: str) -> str:
        normalized = target.strip().lower()
        tool_docs = self._load_tool_docs_by_heading()
        if normalized in tool_docs:
            return (
                f"Detailed tool guide for `{normalized}`:\n\n"
                f"{tool_docs[normalized]}"
            )

        # Support mode aliases like code_execution_tool:file_write.
        if normalized.startswith("code_execution_tool:"):
            base = tool_docs.get("code_execution_tool")
            if base:
                return (
                    f"Detailed tool guide for `{normalized}` "
                    "(from `code_execution_tool`):\n\n"
                    f"{base}"
                )

        skill = skills.find_skill(target, agent=self.agent, include_content=True)
        if skill:
            return skills.load_skill_for_agent(skill.name, agent=self.agent)

        suggestions = sorted(
            [name for name in tool_docs.keys() if normalized in name or name in normalized]
        )[:8]
        suggestion_text = ", ".join(suggestions) if suggestions else "none"
        return (
            f"Capability `{target}` not found.\n"
            f"Closest tool matches: {suggestion_text}\n"
            "Use `capabilities:list` to inspect all available tools and skills."
        )

    def _discover_tool_names(self) -> list[str]:
        names: set[str] = set()
        tool_dirs = subagents.get_paths(
            self.agent,
            "tools",
            must_exist_completely=False,
            default_root="python",
        )
        for tool_dir in tool_dirs:
            for path in files.get_unique_filenames_in_dirs([tool_dir], "*.py"):
                base = os.path.basename(path)
                if base == "unknown.py" or base.startswith("_"):
                    continue
                if base.endswith("._py"):
                    base = base.replace("._py", "")
                else:
                    base = base[:-3]
                if base:
                    names.add(base)
        return sorted(names)

    def _load_tool_docs_by_heading(self) -> dict[str, str]:
        prompt_dirs = subagents.get_paths(self.agent, "prompts")
        docs: dict[str, str] = {}
        prompt_files = files.get_unique_filenames_in_dirs(prompt_dirs, "agent.system.tool.*.md")
        for prompt_file in prompt_files:
            try:
                content = files.read_prompt_file(prompt_file, _agent=self.agent)
            except Exception:
                continue
            first_line = content.splitlines()[0].strip() if content else ""
            if first_line.startswith("### "):
                key = first_line[4:].strip().lower()
                docs[key] = content
            # Keep a filename alias as fallback.
            alias = Path(prompt_file).name.replace("agent.system.tool.", "").replace(".md", "")
            docs.setdefault(alias.lower(), content)
        return docs
