from python.helpers.api import ApiHandler, Request, Response
from python.helpers import message_queue as mq, session_epoch
from agent import AgentContext
from python.helpers.state_monitor_integration import mark_dirty_for_context
import json

class MessageQueueRemove(ApiHandler):
    """Remove message(s) from queue."""

    async def process(self, input: dict, request: Request) -> dict | Response:
        context = AgentContext.get(input.get("context", ""))
        if not context:
            return Response("Context not found", status=404)
        stale_reason = session_epoch.stale_epoch_reason(
            context, session_epoch.parse_epoch(input.get("epoch", None))
        )
        if stale_reason:
            return Response(
                response=json.dumps(
                    {
                        "ok": False,
                        "code": "STALE_EPOCH_REJECTED",
                        "error": stale_reason,
                        "context": context.id,
                        "epoch": session_epoch.get_epoch(context),
                    }
                ),
                status=409,
                mimetype="application/json",
            )

        item_id = input.get("item_id")  # None means clear all
        remaining = mq.remove(context, item_id)
        mark_dirty_for_context(context.id, reason="message_queue_remove")

        return {"ok": True, "remaining": remaining, "epoch": session_epoch.get_epoch(context)}
