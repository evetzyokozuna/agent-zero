from agent import AgentContext, UserMessage
from python.helpers.api import ApiHandler, Request, Response

from python.helpers import files, extension, message_queue as mq, session_epoch
import os
import json
from python.helpers.security import safe_filename
from python.helpers.defer import DeferredTask


class Message(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        task_or_response = await self.communicate(input=input, request=request)
        if isinstance(task_or_response, Response):
            return task_or_response
        task, context = task_or_response
        return await self.respond(task, context)

    async def respond(self, task: DeferredTask, context: AgentContext):
        result = await task.result()  # type: ignore
        return {
            "message": result,
            "context": context.id,
            "epoch": session_epoch.get_epoch(context),
        }

    async def communicate(self, input: dict, request: Request):
        # Handle both JSON and multipart/form-data
        if request.content_type.startswith("multipart/form-data"):
            text = request.form.get("text", "")
            ctxid = request.form.get("context", "")
            message_id = request.form.get("message_id", None)
            request_epoch = session_epoch.parse_epoch(request.form.get("epoch", None))
            attachments = request.files.getlist("attachments")
            attachment_paths = []

            upload_folder_int = "/a0/usr/uploads"
            upload_folder_ext = files.get_abs_path("usr/uploads") # for development environment

            if attachments:
                os.makedirs(upload_folder_ext, exist_ok=True)
                for attachment in attachments:
                    if attachment.filename is None:
                        continue
                    filename = safe_filename(attachment.filename)
                    if not filename:
                        continue
                    save_path = files.get_abs_path(upload_folder_ext, filename)
                    attachment.save(save_path)
                    attachment_paths.append(os.path.join(upload_folder_int, filename))
        else:
            # Handle JSON request as before
            input_data = request.get_json()
            text = input_data.get("text", "")
            ctxid = input_data.get("context", "")
            message_id = input_data.get("message_id", None)
            request_epoch = session_epoch.parse_epoch(input_data.get("epoch", None))
            attachment_paths = []

        # Now process the message
        message = text

        # Obtain agent context
        context = self.use_context(ctxid)
        stale_reason = session_epoch.stale_epoch_reason(context, request_epoch)
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

        # call extension point, alow it to modify data
        data = { "message": message, "attachment_paths": attachment_paths }
        await extension.call_extensions("user_message_ui", agent=context.get_agent(), data=data)
        message = data.get("message", "")
        attachment_paths = data.get("attachment_paths", [])

        # Store attachments in agent data
        # context.agent0.set_data("attachments", attachment_paths)

        # Log to console and UI using helper function
        mq.log_user_message(context, message, attachment_paths, message_id)

        return context.communicate(UserMessage(message, attachment_paths)), context
