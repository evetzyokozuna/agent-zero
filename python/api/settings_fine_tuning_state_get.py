from typing import Any

from python.helpers.api import ApiHandler, Request, Response
from python.helpers import settings, projects


class GetSettingsFineTuningState(ApiHandler):
    async def process(self, input: dict[str, Any], request: Request) -> dict[str, Any] | Response:
        profile = str(input.get("profile", "") or "").strip() or None
        project = str(input.get("project", "") or "").strip() or None
        ctxid = str(input.get("ctxid", "") or "").strip()

        if not project and ctxid:
            try:
                context = self.use_context(ctxid)
                project = str(projects.get_context_project_name(context) or "").strip() or None
            except Exception:
                project = None

        current = settings.get_settings()
        active_profile = profile or str(current.get("agent_profile", "") or "").strip() or None
        target_options = settings.get_fine_tuning_target_options(
            active_profile=active_profile,
            active_project=project,
        )
        source_map = settings.get_setting_source_map(
            profile=active_profile,
            project=project,
        )
        return {
            "target_options": target_options,
            "source_map": source_map,
            "resolved_profile": active_profile or "",
            "resolved_project": project or "",
        }
