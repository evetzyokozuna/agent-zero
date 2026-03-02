from typing import Any

from python.helpers.api import ApiHandler, Request, Response
from python.helpers import settings, projects


class SetSettingsScopeOverride(ApiHandler):
    async def process(self, input: dict[str, Any], request: Request) -> dict[str, Any] | Response:
        key = str(input.get("key", "")).strip()
        if not key:
            raise Exception("Missing required field: key")
        if "value" not in input:
            raise Exception("Missing required field: value")

        scope = str(input.get("scope", "global")).strip().lower()
        profile = str(input.get("profile", "") or "").strip() or None
        project = str(input.get("project", "") or "").strip() or None
        ctxid = str(input.get("ctxid", "") or "").strip()

        if scope in ("project", "project_profile") and not project and ctxid:
            context = self.use_context(ctxid)
            project = str(projects.get_context_project_name(context) or "").strip() or None

        backend = settings.save_scope_override(
            key=key,
            value=input.get("value"),
            scope=scope,
            profile=profile,
            project=project,
        )
        out = settings.convert_out(backend)
        return dict(out)
