from python.helpers.api import ApiHandler, Request, Response
from python.helpers import message_queue as mq, session_epoch
from agent import AgentContext
from python.helpers.state_monitor_integration import mark_dirty_for_context
import json

class MessageQueueSend(ApiHandler):
    """Send queued message(s) immediately."""

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

        if not mq.has_queue(context):
            return {"ok": True, "message": "Queue empty", "epoch": session_epoch.get_epoch(context)}

        item_id = input.get("item_id")
        send_all = input.get("send_all", False)

        if send_all:
            count = mq.send_all_aggregated(context)
            return {"ok": True, "sent_count": count, "epoch": session_epoch.get_epoch(context)}

        # Send single item
        item = mq.pop_item(context, item_id) if item_id else mq.pop_first(context)
        if not item:
            return Response("Item not found", status=404)

        mq.send_message(context, item)
        mark_dirty_for_context(context.id, reason="message_queue_send")
        return {"ok": True, "sent_item_id": item["id"], "epoch": session_epoch.get_epoch(context)}
