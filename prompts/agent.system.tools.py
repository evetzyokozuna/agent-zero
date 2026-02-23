import os
from typing import Any
from python.helpers.files import VariablesPlugin
from python.helpers import files, skills, subagents
from python.helpers.print_style import PrintStyle


class BuidToolsPrompt(VariablesPlugin):
    def get_variables(self, file: str, backup_dirs: list[str] | None = None, **kwargs) -> dict[str, Any]:

        # collect all prompt folders in order of their priority
        folder = files.get_abs_path(os.path.dirname(file))
        folders = [folder]
        if backup_dirs:
            for backup_dir in backup_dirs:
                folders.append(files.get_abs_path(backup_dir))

        # collect all tool instruction files
        prompt_files = files.get_unique_filenames_in_dirs(folders, "agent.system.tool.*.md")
        
        # load tool instructions
        tools = []
        for prompt_file in prompt_files:
            try:
                tool = files.read_prompt_file(prompt_file, **kwargs)
                tools.append(tool)
            except Exception as e:
                PrintStyle().error(f"Error loading tool '{prompt_file}': {e}")

        full_tools_prompt = "\n\n".join(tools)
        full_tools_prompt += self._build_runtime_capability_index(backup_dirs=backup_dirs, **kwargs)
        return {"tools": full_tools_prompt}

    def _build_runtime_capability_index(self, backup_dirs: list[str] | None = None, **kwargs) -> str:
        agent = kwargs.get("_agent")
        if not agent:
            return ""
        try:
            tool_dirs = subagents.get_paths(
                agent,
                "tools",
                must_exist_completely=False,
                default_root="python",
            )
            names: set[str] = set()
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

            skills_list = skills.list_skills(agent=agent)
            skill_names = sorted(s.name for s in skills_list if s.name)
            tool_names = sorted(names)
            tool_lines = "\n".join(f"- `{name}`" for name in tool_names) or "- (none discovered)"
            skill_lines = "\n".join(f"- `{name}`" for name in skill_names) or "- (none discovered)"
            return (
                "\n\n## Runtime capability index (comprehensive)\n\n"
                "Use this as the canonical discovered inventory. For detailed usage of a specific item, "
                "use `capabilities:describe`.\n\n"
                "### Local tools discovered\n"
                f"{tool_lines}\n\n"
                "### Skills discovered\n"
                f"{skill_lines}"
            )
        except Exception as e:
            PrintStyle().error(f"Error building runtime capability index: {e}")
            return ""
