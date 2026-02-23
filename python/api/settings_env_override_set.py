from typing import Any

from python.helpers.api import ApiHandler, Request, Response
from python.helpers import settings


class SetSettingsEnvOverride(ApiHandler):
    async def process(self, input: dict[str, Any], request: Request) -> dict[str, Any] | Response:
        key = str(input.get("key", "")).strip()
        if not key:
            raise Exception("Missing required field: key")
        if "value" not in input:
            raise Exception("Missing required field: value")

        backend = settings.save_env_override(key=key, value=input.get("value"))
        out = settings.convert_out(backend)
        return dict(out)
