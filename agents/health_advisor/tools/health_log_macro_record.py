"""Record a new item to MacrosAndRecipes.md. Use for named products/recipes when user provides macros."""
import os
import importlib.util
from python.helpers.tool import Tool, Response

_tools_dir = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "_health_log_utils", os.path.join(_tools_dir, "_health_log_utils.py")
)
_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utils)
get_workdir_path = _utils.get_workdir_path
path_macros_md = _utils.path_macros_md


def _format_macro_line(item_name: str, kcal: str, protein: str, carbs: str, fat: str, serving: str = "") -> str:
    """Format as '- item: Xkcal | PXg CXg FXg' or '- item (per Xg): Xkcal | ...'."""
    p = str(protein).strip() or "0"
    c = str(carbs).strip() or "0"
    f = str(fat).strip() or "0"
    k = str(kcal).strip() or "0"
    if not p.endswith("g"):
        p = f"{p}g"
    if not c.endswith("g"):
        c = f"{c}g"
    if not f.endswith("g"):
        f = f"{f}g"
    if not k.endswith("kcal"):
        k = f"{k}kcal"
    macro_str = f"{k} | P{p} C{c} F{f}"
    label = item_name.strip()
    if serving and str(serving).strip():
        label = f"{label} (per {serving.strip()})"
    return f"- {label}: {macro_str}\n"


class HealthLogMacroRecord(Tool):
    async def execute(
        self,
        workdir: str = "",
        item_name: str = "",
        kcal: str = "",
        protein: str = "",
        carbs: str = "",
        fat: str = "",
        serving_size: str = "",
        **kwargs,
    ):
        if not item_name or not str(item_name).strip():
            return Response(
                message="Error: item_name required",
                break_loop=False,
            )
        if not any([kcal, protein, carbs, fat]):
            return Response(
                message="Error: at least one of kcal, protein, carbs, fat required",
                break_loop=False,
            )

        workdir_path = get_workdir_path(workdir)
        macros_path = path_macros_md(workdir_path)

        line = _format_macro_line(
            item_name=item_name,
            kcal=kcal or "0",
            protein=protein or "0",
            carbs=carbs or "0",
            fat=fat or "0",
            serving=serving_size,
        )

        content = ""
        if os.path.exists(macros_path):
            with open(macros_path, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.endswith("\n"):
                content += "\n"
        else:
            content = "# MacrosAndRecipes.md\n\n"

        content += line
        with open(macros_path, "w", encoding="utf-8") as f:
            f.write(content)

        return Response(
            message=f"Recorded **{item_name}** in MacrosAndRecipes.md: {line.strip()}",
            break_loop=False,
        )
