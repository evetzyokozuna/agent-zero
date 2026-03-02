from python.helpers.api import ApiHandler, Request, Response
from python.helpers import message_queue as mq, session_epoch
from agent import AgentContext
from python.helpers.state_monitor_integration import mark_dirty_for_context
import json


class MessageQueueAdd(ApiHandler):
    """Add a message to the queue."""

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

        text = input.get("text", "").strip()
        attachments = input.get("attachments", [])  # filenames from /upload API
        item_id = input.get("item_id")

        if not text and not attachments:
            return Response("Empty message", status=400)

        item = mq.add(context, text, attachments, item_id)
        if item.get("rejected"):
            reason = item.get("reason", "queue_rejected")
            return Response(f"Message queue rejected new item ({reason})", status=429)
        mark_dirty_for_context(context.id, reason="message_queue_add")
        return {
            "ok": True,
            "item_id": item["id"],
            "queue_length": len(mq.get_queue(context)),
            "epoch": session_epoch.get_epoch(context),
        }
