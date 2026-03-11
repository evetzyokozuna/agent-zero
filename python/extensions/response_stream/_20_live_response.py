from python.helpers import persist_chat, tokens
from python.helpers.extension import Extension
from agent import LoopData
import asyncio
from python.helpers.log import LogItem
from python.helpers import log


class LiveResponse(Extension):

    async def execute(
        self,
        loop_data: LoopData = LoopData(),
        text: str = "",
        parsed: dict = {},
        **kwargs,
    ):
        try:
            parsed = parsed if isinstance(parsed, dict) else {}
            response_text = ""

            if parsed.get("tool_name") == "response":
                args = parsed.get("tool_args", {})
                if isinstance(args, dict):
                    response_text = str(args.get("text", args.get("message", ""))).strip()
            elif "text" in parsed:
                response_text = str(parsed.get("text", "")).strip()
            elif "message" in parsed:
                response_text = str(parsed.get("message", "")).strip()

            if not response_text:
                return

            # create log message and store it in loop data temporary params
            if "log_item_response" not in loop_data.params_temporary:
                loop_data.params_temporary["log_item_response"] = (
                    self.agent.context.log.log(
                        type="response",
                        heading=f"icon://chat {self.agent.agent_name}: Responding",
                    )
                )

            # update log message
            log_item = loop_data.params_temporary["log_item_response"]
            log_item.update(content=response_text)
        except Exception as e:
            pass
