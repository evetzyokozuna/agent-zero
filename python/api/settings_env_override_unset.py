from typing import Any

from python.helpers.api import ApiHandler, Request, Response
from python.helpers import settings


class SetSettingsEnvOverrideUnset(ApiHandler):
    async def process(self, input: dict[str, Any], request: Request) -> dict[str, Any] | Response:
        key = str(input.get("key", "")).strip()
        if not key:
            raise Exception("Missing required field: key")

        backend = settings.remove_env_override(key=key)
        out = settings.convert_out(backend)
        return dict(out)
