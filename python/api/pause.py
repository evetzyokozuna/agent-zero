from python.helpers.api import ApiHandler, Request, Response
from python.helpers import session_epoch


class Pause(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
            # input data
            paused = input.get("paused", False)
            ctxid = input.get("context", "")
            fresh_start = bool(input.get("fresh_start", False))
            stop_epoch = input.get("stop_epoch", None)

            # context instance - get or create
            context = self.use_context(ctxid)

            context.paused = paused
            epoch = session_epoch.get_epoch(context)
            if fresh_start:
                epoch = session_epoch.bump_epoch(context, observed_stop_epoch=stop_epoch)

            return {
                "message": "Agent paused." if paused else "Agent unpaused.",
                "pause": paused,
                "epoch": epoch,
            }    
