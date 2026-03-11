import asyncio, random, re, string, threading, time
import hashlib
import json
import nest_asyncio
import os

nest_asyncio.apply()

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Coroutine, Dict, Literal
from enum import Enum
import models

from python.helpers import (
    extract_tools,
    files,
    errors,
    history,
    tokens,
    context as context_helper,
    dirty_json,
    subagents,
    settings,
    strings,
)
from python.helpers.print_style import PrintStyle

from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.messages import SystemMessage, BaseMessage

import python.helpers.log as Log
from python.helpers.dirty_json import DirtyJson
from python.helpers.defer import DeferredTask
from typing import Callable
from python.helpers.localization import Localization
from python.helpers.extension import call_extensions
from python.helpers.errors import RepairableException


class AgentContextType(Enum):
    USER = "user"
    TASK = "task"
    BACKGROUND = "background"


class AgentContext:

    _contexts: dict[str, "AgentContext"] = {}
    _contexts_lock = threading.RLock()
    _counter: int = 0
    _notification_manager = None

    def __init__(
        self,
        config: "AgentConfig",
        id: str | None = None,
        name: str | None = None,
        agent0: "Agent|None" = None,
        log: Log.Log | None = None,
        paused: bool = False,
        streaming_agent: "Agent|None" = None,
        created_at: datetime | None = None,
        type: AgentContextType = AgentContextType.USER,
        last_message: datetime | None = None,
        data: dict | None = None,
        output_data: dict | None = None,
        set_current: bool = False,
    ):
        # initialize context
        self.id = id or AgentContext.generate_id()
        existing = None
        with AgentContext._contexts_lock:
            existing = AgentContext._contexts.get(self.id, None)
            if existing:
                AgentContext._contexts.pop(self.id, None)
            AgentContext._contexts[self.id] = self
        if existing and existing.task:
            existing.task.kill()
        if set_current:
            AgentContext.set_current(self.id)

        # initialize state
        self.name = name
        self.config = config
        self.data = data or {}
        self.output_data = output_data or {}
        self.log = log or Log.Log()
        self.log.context = self
        self.paused = paused
        self.streaming_agent = streaming_agent
        self.task: DeferredTask | None = None
        self.created_at = created_at or datetime.now(timezone.utc)
        self.type = type
        AgentContext._counter += 1
        self.no = AgentContext._counter
        self.last_message = last_message or datetime.now(timezone.utc)

        # initialize agent at last (context is complete now)
        self.agent0 = agent0 or Agent(0, self.config, self)

    @staticmethod
    def get(id: str):
        with AgentContext._contexts_lock:
            return AgentContext._contexts.get(id, None)

    @staticmethod
    def use(id: str):
        context = AgentContext.get(id)
        if context:
            AgentContext.set_current(id)
        else:
            AgentContext.set_current("")
        return context

    @staticmethod
    def current():
        ctxid = context_helper.get_context_data("agent_context_id", "")
        if not ctxid:
            return None
        return AgentContext.get(ctxid)

    @staticmethod
    def set_current(ctxid: str):
        context_helper.set_context_data("agent_context_id", ctxid)

    @staticmethod
    def first():
        with AgentContext._contexts_lock:
            if not AgentContext._contexts:
                return None
            return list(AgentContext._contexts.values())[0]

    @staticmethod
    def all():
        with AgentContext._contexts_lock:
            return list(AgentContext._contexts.values())

    @staticmethod
    def generate_id():
        def generate_short_id():
            return "".join(random.choices(string.ascii_letters + string.digits, k=8))

        while True:
            short_id = generate_short_id()
            with AgentContext._contexts_lock:
                if short_id not in AgentContext._contexts:
                    return short_id

    @classmethod
    def get_notification_manager(cls):
        if cls._notification_manager is None:
            from python.helpers.notification import NotificationManager  # type: ignore

            cls._notification_manager = NotificationManager()
        return cls._notification_manager

    @staticmethod
    def remove(id: str):
        with AgentContext._contexts_lock:
            context = AgentContext._contexts.pop(id, None)
        if context and context.task:
            context.task.kill()
        return context

    def get_data(self, key: str, recursive: bool = True):
        # recursive is not used now, prepared for context hierarchy
        return self.data.get(key, None)

    def set_data(self, key: str, value: Any, recursive: bool = True):
        # recursive is not used now, prepared for context hierarchy
        self.data[key] = value

    def get_output_data(self, key: str, recursive: bool = True):
        # recursive is not used now, prepared for context hierarchy
        return self.output_data.get(key, None)

    def set_output_data(self, key: str, value: Any, recursive: bool = True):
        # recursive is not used now, prepared for context hierarchy
        self.output_data[key] = value

    def output(self):
        return {
            "id": self.id,
            "name": self.name,
            "created_at": (
                Localization.get().serialize_datetime(self.created_at)
                if self.created_at
                else Localization.get().serialize_datetime(datetime.fromtimestamp(0))
            ),
            "no": self.no,
            "log_guid": self.log.guid,
            "log_version": len(self.log.updates),
            "log_length": len(self.log.logs),
            "paused": self.paused,
            "last_message": (
                Localization.get().serialize_datetime(self.last_message)
                if self.last_message
                else Localization.get().serialize_datetime(datetime.fromtimestamp(0))
            ),
            "type": self.type.value,
            "running": self.is_running(),
            **self.output_data,
        }

    @staticmethod
    def log_to_all(
        type: Log.Type,
        heading: str | None = None,
        content: str | None = None,
        kvps: dict | None = None,
        update_progress: Log.ProgressUpdate | None = None,
        id: str | None = None,  # Add id parameter
        **kwargs,
    ) -> list[Log.LogItem]:
        items: list[Log.LogItem] = []
        for context in AgentContext.all():
            items.append(
                context.log.log(
                    type, heading, content, kvps, update_progress, id, **kwargs
                )
            )
        return items

    def kill_process(self):
        if self.task:
            self.task.kill()

    def reset(self):
        self.kill_process()
        self.log.reset()
        self.agent0 = Agent(0, self.config, self)
        self.streaming_agent = None
        self.paused = False

    def nudge(self):
        self.kill_process()
        self.paused = False
        self.task = self.communicate(UserMessage(self.agent0.read_prompt("fw.msg_nudge.md")))
        return self.task

    def get_agent(self):
        return self.streaming_agent or self.agent0

    def is_running(self) -> bool:
        return (self.task and self.task.is_alive()) or False

    def communicate(self, msg: "UserMessage", broadcast_level: int = 1):
        self.paused = False  # unpause if paused

        current_agent = self.get_agent()

        if self.task and self.task.is_alive():
            # set intervention messages to agent(s):
            intervention_agent = current_agent
            while intervention_agent and broadcast_level != 0:
                intervention_agent.intervention = msg
                broadcast_level -= 1
                intervention_agent = intervention_agent.data.get(
                    Agent.DATA_NAME_SUPERIOR, None
                )
        else:
            self.task = self.run_task(self._process_chain, current_agent, msg)

        return self.task

    def run_task(
        self, func: Callable[..., Coroutine[Any, Any, Any]], *args: Any, **kwargs: Any
    ):
        if not self.task:
            self.task = DeferredTask(
                thread_name=self.__class__.__name__,
            )
        self.task.start_task(func, *args, **kwargs)
        return self.task

    # this wrapper ensures that superior agents are called back if the chat was loaded from file and original callstack is gone
    async def _process_chain(self, agent: "Agent", msg: "UserMessage|str", user=True):
        try:
            msg_template = (
                agent.hist_add_user_message(msg)  # type: ignore
                if user
                else agent.hist_add_tool_result(
                    tool_name="call_subordinate", tool_result=msg  # type: ignore
                )
            )
            response = await agent.monologue()  # type: ignore
            superior = agent.data.get(Agent.DATA_NAME_SUPERIOR, None)
            if superior:
                response = await self._process_chain(superior, response, False)  # type: ignore

            # call end of process extensions
            await self.get_agent().call_extensions("process_chain_end", data={})

            return response
        except Exception as e:
            agent.handle_critical_exception(e)


@dataclass
class AgentConfig:
    chat_model: models.ModelConfig
    utility_model: models.ModelConfig
    embeddings_model: models.ModelConfig
    browser_model: models.ModelConfig
    mcp_servers: str
    profile: str = ""
    memory_subdir: str = ""
    knowledge_subdirs: list[str] = field(default_factory=lambda: ["default", "custom"])
    browser_http_headers: dict[str, str] = field(
        default_factory=dict
    )  # Custom HTTP headers for browser requests
    code_exec_ssh_enabled: bool = True
    code_exec_ssh_addr: str = "localhost"
    code_exec_ssh_port: int = 55022
    code_exec_ssh_user: str = "root"
    code_exec_ssh_pass: str = ""
    additional: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserMessage:
    message: str
    attachments: list[str] = field(default_factory=list[str])
    system_message: list[str] = field(default_factory=list[str])


class LoopData:
    def __init__(self, **kwargs):
        self.iteration = -1
        self.system = []
        self.user_message: history.Message | None = None
        self.history_output: list[history.OutputMessage] = []
        self.extras_temporary: OrderedDict[str, history.MessageContent] = OrderedDict()
        self.extras_persistent: OrderedDict[str, history.MessageContent] = OrderedDict()
        self.last_response = ""
        self.params_temporary: dict = {}
        self.params_persistent: dict = {}
        self.current_tool = None

        # override values with kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


# intervention exception class - skips rest of message loop iteration
class InterventionException(Exception):
    pass


# killer exception class - not forwarded to LLM, cannot be fixed on its own, ends message loop


class HandledException(Exception):
    pass


class Agent:

    DATA_NAME_SUPERIOR = "_superior"
    DATA_NAME_SUBORDINATE = "_subordinate"
    DATA_NAME_CTX_WINDOW = "ctx_window"

    def __init__(
        self, number: int, config: AgentConfig, context: AgentContext | None = None
    ):

        # agent config
        self.config = config

        # agent context
        self.context = context or AgentContext(config=config, agent0=self)

        # non-config vars
        self.number = number
        self.agent_name = f"A{self.number}"

        self.history = history.History(self)  # type: ignore[abstract]
        self.last_user_message: history.Message | None = None
        self.intervention: UserMessage | None = None
        self.data: dict[str, Any] = {}  # free data object all the tools can use

        asyncio.run(self.call_extensions("agent_init"))

    async def monologue(self):
        error_retries = 0  # counter for critical error retries
        set = settings.get_effective_settings(self)
        monologue_started_at = time.monotonic()
        last_iteration_started_at: float | None = None
        consecutive_misformats = 0
        consecutive_repairable_errors = 0
        while True:
            try:
                # loop data dictionary to pass to extensions
                self.loop_data = LoopData(user_message=self.last_user_message)
                # call monologue_start extensions
                await self.call_extensions("monologue_start", loop_data=self.loop_data)

                printer = PrintStyle(italic=True, font_color="#b3ffd9", padding=False)

                # let the agent run message loop until he stops it with a response tool
                while True:

                    self.context.streaming_agent = self  # mark self as current streamer
                    now = time.monotonic()
                    previous_iteration_seconds = (
                        int(now - last_iteration_started_at)
                        if last_iteration_started_at is not None
                        else 0
                    )
                    last_iteration_started_at = now
                    self.loop_data.iteration += 1
                    self.loop_data.params_temporary = {}  # clear temporary params

                    # Guardrails to prevent runaway monologues and self-repair loops.
                    guardrail_message = self._check_monologue_guardrails(
                        set=set,
                        monologue_started_at=monologue_started_at,
                        previous_iteration_seconds=previous_iteration_seconds,
                        consecutive_misformats=consecutive_misformats,
                        consecutive_repairable_errors=consecutive_repairable_errors,
                    )
                    if guardrail_message:
                        return guardrail_message
                    degradation_abort = self._check_degradation_auto_abort(set=set)
                    if degradation_abort:
                        return degradation_abort

                    # call message_loop_start extensions
                    await self.call_extensions(
                        "message_loop_start", loop_data=self.loop_data
                    )
                    await self.handle_intervention()

                    try:
                        # prepare LLM chain (model, system, history)
                        prompt = await self.prepare_prompt(loop_data=self.loop_data)

                        # call before_main_llm_call extensions
                        await self.call_extensions(
                            "before_main_llm_call", loop_data=self.loop_data
                        )
                        await self.handle_intervention()

                        debug_stream_to_console = self._debug_stream_to_console(set)
                        debug_capture_trace = self._debug_capture_enabled(set)
                        debug_trace_payload = (
                            self._build_llm_debug_trace_payload(prompt=prompt)
                            if debug_capture_trace
                            else None
                        )


                        async def reasoning_callback(chunk: str, full: str):
                            await self.handle_intervention()
                            if debug_stream_to_console and chunk == full:
                                printer.print("Reasoning: ")  # start of reasoning
                            # Pass chunk and full data to extensions for processing
                            stream_data = {"chunk": chunk, "full": full}
                            await self.call_extensions(
                                "reasoning_stream_chunk",
                                loop_data=self.loop_data,
                                stream_data=stream_data,
                            )
                            # Stream masked chunk after extensions processed it
                            if debug_stream_to_console and stream_data.get("chunk"):
                                printer.stream(stream_data["chunk"])
                            # Use the potentially modified full text for downstream processing
                            await self.handle_reasoning_stream(stream_data["full"])

                        async def stream_callback(chunk: str, full: str):
                            await self.handle_intervention()
                            # output the agent response stream
                            if debug_stream_to_console and chunk == full:
                                printer.print("Response: ")  # start of response
                            # Pass chunk and full data to extensions for processing
                            stream_data = {"chunk": chunk, "full": full}
                            await self.call_extensions(
                                "response_stream_chunk",
                                loop_data=self.loop_data,
                                stream_data=stream_data,
                            )
                            # Stream masked chunk after extensions processed it
                            if debug_stream_to_console and stream_data.get("chunk"):
                                printer.stream(stream_data["chunk"])
                            # Use the potentially modified full text for downstream processing
                            await self.handle_response_stream(stream_data["full"])

                        # call main LLM
                        agent_response, _reasoning = await self.call_chat_model(
                            messages=prompt,
                            response_callback=stream_callback,
                            reasoning_callback=reasoning_callback,
                        )
                        if not (agent_response or "").strip():
                            diag = self.loop_data.params_temporary.get(
                                "last_model_call_diagnostics", {}
                            )
                            diag_suffix = ""
                            if isinstance(diag, dict):
                                noncontent = int(diag.get("noncontent_chunk_count", 0) or 0)
                                tool_chunks = int(diag.get("tool_call_chunk_count", 0) or 0)
                                fn_chunks = int(diag.get("function_call_chunk_count", 0) or 0)
                                finish_reasons = diag.get("finish_reasons", {})
                                diag_suffix = (
                                    f" diagnostics="
                                    f"chunks:{int(diag.get('chunk_count', 0) or 0)},"
                                    f"noncontent:{noncontent},"
                                    f"tool_calls:{tool_chunks},"
                                    f"function_calls:{fn_chunks},"
                                    f"finish:{finish_reasons}"
                                )
                            empty_msg = (
                                "[MODEL_EMPTY_OUTPUT] Chat model returned an empty response. "
                                "This often indicates provider-side refusal/rate/quota pressure, "
                                "or an over-constrained context. Will treat as misformat."
                                f"{diag_suffix}"
                            )
                            self.hist_add_warning(empty_msg)
                            PrintStyle(font_color="orange", padding=True).print(empty_msg)
                            self.context.log.log(
                                type="warning",
                                content=f"{self.agent_name}: {empty_msg}",
                            )
                        if debug_capture_trace and debug_trace_payload is not None:
                            self._write_llm_debug_trace_payload(
                                payload=debug_trace_payload,
                                response=agent_response,
                                reasoning=_reasoning,
                            )
                        await self.handle_intervention(agent_response)

                        # Notify extensions to finalize their stream filters
                        await self.call_extensions(
                            "reasoning_stream_end", loop_data=self.loop_data
                        )
                        await self.handle_intervention(agent_response)

                        await self.call_extensions(
                            "response_stream_end", loop_data=self.loop_data
                        )

                        await self.handle_intervention(agent_response)

                        if (
                            (agent_response or "").strip()
                            and self.loop_data.last_response == agent_response
                        ):  # if assistant_response is the same as last non-empty message in history, let him know
                            # Append the assistant's response to the history
                            self.hist_add_ai_response(agent_response)
                            # Append warning message to the history
                            warning_msg = self.read_prompt("fw.msg_repeat.md")
                            self.hist_add_warning(message=warning_msg)
                            PrintStyle(font_color="orange", padding=True).print(
                                warning_msg
                            )
                            self.context.log.log(type="warning", content=warning_msg)

                        else:  # otherwise proceed with tool
                            # Append the assistant's response to the history
                            self.hist_add_ai_response(agent_response)
                            # process tools requested in agent message
                            tools_result = await self.process_tools(
                                agent_response, consecutive_misformats=consecutive_misformats
                            )
                            if self.loop_data.params_temporary.get(
                                "guardrail_misformat", False
                            ):
                                consecutive_misformats += 1
                            else:
                                consecutive_misformats = 0

                            # Successful parse/tool processing resets repairable error streak.
                            consecutive_repairable_errors = 0

                            if tools_result:  # final response of message loop available
                                return tools_result  # break the execution if the task is done

                        error_retries = 0  # reset retry counter on successful iteration

                    # exceptions inside message loop:
                    except InterventionException as e:
                        error_retries = 0  # reset retry counter on user intervention
                        consecutive_misformats = 0
                        consecutive_repairable_errors = 0
                        pass  # intervention message has been handled in handle_intervention(), proceed with conversation loop
                    except RepairableException as e:
                        # Forward repairable errors to the LLM, maybe it can fix them
                        msg = {"message": errors.format_error(e)}
                        await self.call_extensions("error_format", msg=msg)
                        self.hist_add_warning(msg["message"])
                        PrintStyle(font_color="red", padding=True).print(msg["message"])
                        self.context.log.log(type="warning", content=msg["message"])
                        consecutive_repairable_errors += 1
                        consecutive_misformats = 0
                    except Exception as e:
                        # Retry critical exceptions before failing
                        error_retries = await self.retry_critical_exception(
                            e, error_retries
                        )
                        consecutive_misformats = 0
                        consecutive_repairable_errors = 0

                    finally:
                        # call message_loop_end extensions
                        if self.context.task and self.context.task.is_alive(): # don't call extensions post mortem
                            await self.call_extensions(
                                "message_loop_end", loop_data=self.loop_data
                            )

            # exceptions outside message loop:
            except InterventionException as e:
                error_retries = 0  # reset retry counter on user intervention
                pass  # just start over
            except Exception as e:
                # Retry critical exceptions before failing
                error_retries = await self.retry_critical_exception(
                    e, error_retries
                )
            finally:
                self.context.streaming_agent = None  # unset current streamer
                # call monologue_end extensions
                if self.context.task and self.context.task.is_alive(): # don't call extensions post mortem
                    await self.call_extensions("monologue_end", loop_data=self.loop_data)  # type: ignore

    def _check_monologue_guardrails(
        self,
        set: settings.Settings,
        monologue_started_at: float,
        previous_iteration_seconds: int,
        consecutive_misformats: int,
        consecutive_repairable_errors: int,
    ) -> str | None:
        if not bool(set.get("agent_guardrails_enabled", False)):
            return None
        max_iterations = int(set.get("agent_max_iterations", 80))
        max_runtime_seconds = int(set.get("agent_max_runtime_seconds", 900))
        max_consecutive_misformats = int(
            set.get("agent_max_consecutive_misformats", 6)
        )
        max_consecutive_repairable_errors = int(
            set.get("agent_max_consecutive_repairable_errors", 6)
        )
        runtime_turn_budget_seconds = int(set.get("runtime_turn_budget_seconds", 0))
        runtime_task_budget_seconds = int(set.get("runtime_task_budget_seconds", 0))

        if max_iterations > 0 and self.loop_data.iteration >= max_iterations:
            return self._terminate_for_guardrail(
                reason="maximum loop iterations reached",
                detail=f"iteration={self.loop_data.iteration}, limit={max_iterations}",
            )

        elapsed_seconds = int(time.monotonic() - monologue_started_at)
        if max_runtime_seconds > 0 and elapsed_seconds >= max_runtime_seconds:
            return self._terminate_for_guardrail(
                reason="maximum monologue runtime reached",
                detail=f"elapsed_seconds={elapsed_seconds}, limit={max_runtime_seconds}",
            )

        if (
            runtime_task_budget_seconds > 0
            and elapsed_seconds >= runtime_task_budget_seconds
        ):
            return self._terminate_for_guardrail(
                reason="runtime task budget reached",
                detail=f"elapsed_seconds={elapsed_seconds}, limit={runtime_task_budget_seconds}",
            )

        if (
            runtime_turn_budget_seconds > 0
            and previous_iteration_seconds >= runtime_turn_budget_seconds
        ):
            return self._terminate_for_guardrail(
                reason="runtime turn budget reached",
                detail=f"previous_iteration_seconds={previous_iteration_seconds}, limit={runtime_turn_budget_seconds}",
            )

        if (
            max_consecutive_misformats > 0
            and consecutive_misformats >= max_consecutive_misformats
        ):
            return self._terminate_for_guardrail(
                reason="too many consecutive message misformats",
                detail=f"misformats={consecutive_misformats}, limit={max_consecutive_misformats}",
            )

        if (
            max_consecutive_repairable_errors > 0
            and consecutive_repairable_errors >= max_consecutive_repairable_errors
        ):
            return self._terminate_for_guardrail(
                reason="too many consecutive repairable errors",
                detail=f"errors={consecutive_repairable_errors}, limit={max_consecutive_repairable_errors}",
            )
        return None

    def _terminate_for_guardrail(self, reason: str, detail: str) -> str:
        self._record_degradation_metric("guardrail_hits", 1)
        warning = self.read_prompt(
            "fw.msg_guardrail_terminate.md", reason=reason, detail=detail
        )
        self.hist_add_warning(warning)
        PrintStyle(font_color="orange", padding=True).print(warning)
        self.context.log.log(
            type="warning",
            heading="Monologue guardrail triggered",
            content=f"{self.agent_name}: {warning}",
        )
        return warning

    async def prepare_prompt(self, loop_data: LoopData) -> list[BaseMessage]:
        self.context.log.set_progress("Building prompt")

        # call extensions before setting prompts
        await self.call_extensions("message_loop_prompts_before", loop_data=loop_data)

        # set system prompt and message history
        loop_data.system = await self.get_system_prompt(self.loop_data)
        loop_data.history_output = self.history.output()

        # and allow extensions to edit them
        await self.call_extensions("message_loop_prompts_after", loop_data=loop_data)

        # concatenate system prompt
        system_text = "\n\n".join(loop_data.system)

        # join extras
        extras = history.Message(  # type: ignore[abstract]
            False,
            content=self.read_prompt(
                "agent.context.extras.md",
                extras=dirty_json.stringify(
                    {**loop_data.extras_persistent, **loop_data.extras_temporary}
                ),
            ),
        ).output()
        loop_data.extras_temporary.clear()

        # convert history + extras to LLM format
        history_langchain: list[BaseMessage] = history.output_langchain(
            loop_data.history_output + extras
        )

        # build full prompt from system prompt, message history and extrS
        full_prompt: list[BaseMessage] = [
            SystemMessage(content=system_text),
            *history_langchain,
        ]
        full_text = ChatPromptTemplate.from_messages(full_prompt).format()

        # store as last context window content
        self.set_data(
            Agent.DATA_NAME_CTX_WINDOW,
            {
                "text": full_text,
                "tokens": tokens.approximate_tokens(full_text),
            },
        )

        return full_prompt

    async def retry_critical_exception(
        self, e: Exception, error_retries: int, delay: int = 3, max_retries: int = 1
    ) -> int:
        set = settings.get_effective_settings(self)
        if bool(set.get("agent_retry_split_by_error_class_enabled", False)):
            retry_class, class_max_retries, class_delay = self._classify_retry_policy(e, set)
            max_retries = class_max_retries
            delay = class_delay
            if max_retries <= 0:
                detailed_error_message = errors.format_error(e)
                user_error_message = errors.user_facing_error_message(
                    e, detailed_error=detailed_error_message
                )
                self.context.log.log(
                    type="warning",
                    heading="Critical error classified non-retryable",
                    content=f"class={retry_class}; error={user_error_message}",
                )
                self.handle_critical_exception(e)

        if error_retries >= max_retries:
            self.handle_critical_exception(e)

        detailed_error_message = errors.format_error(e)
        user_error_message = errors.user_facing_error_message(
            e, detailed_error=detailed_error_message
        )
        
        self.context.log.log(
            type="warning",
            heading="Critical error occurred, retrying...",
            content=user_error_message,
        )
        PrintStyle(font_color="orange", padding=True).print(
            "Critical error occurred, retrying..."
        )
        PrintStyle(font_color="orange", padding=True).print(detailed_error_message)
        await asyncio.sleep(delay)
        await self.handle_intervention()
        agent_facing_error = self.read_prompt(
            "fw.msg_critical_error.md", error_message=user_error_message
        )
        self.hist_add_warning(message=agent_facing_error)
        PrintStyle(font_color="orange", padding=True).print(
            agent_facing_error
        )
        return error_retries + 1

    def handle_critical_exception(self, exception: Exception):
        if isinstance(exception, HandledException):
            raise exception  # Re-raise the exception to kill the loop
        elif isinstance(exception, asyncio.CancelledError):
            # Handling for asyncio.CancelledError
            PrintStyle(font_color="white", background_color="red", padding=True).print(
                f"Context {self.context.id} terminated during message loop"
            )
            raise HandledException(
                exception
            )  # Re-raise the exception to cancel the loop
        else:
            # Handling for general exceptions
            error_text = errors.error_text(exception)
            detailed_error_message = errors.format_error(exception)
            user_error_message = errors.user_facing_error_message(
                exception, detailed_error=detailed_error_message
            )

            # Mask secrets in error messages
            PrintStyle(font_color="red", padding=True).print(detailed_error_message)
            self.context.log.log(
                type="error",
                content=user_error_message,
            )
            PrintStyle(font_color="red", padding=True).print(
                f"{self.agent_name}: {error_text}"
            )

            raise HandledException(exception)  # Re-raise the exception to kill the loop

    async def get_system_prompt(self, loop_data: LoopData) -> list[str]:
        system_prompt: list[str] = []
        await self.call_extensions(
            "system_prompt", system_prompt=system_prompt, loop_data=loop_data
        )
        return system_prompt

    def parse_prompt(self, _prompt_file: str, **kwargs):
        dirs = subagents.get_paths(self, "prompts")
        prompt = files.parse_file(
            _prompt_file, _directories=dirs, _agent=self, **kwargs
        )
        return prompt

    def read_prompt(self, file: str, **kwargs) -> str:
        dirs = subagents.get_paths(self, "prompts")
        prompt = files.read_prompt_file(file, _directories=dirs, _agent=self, **kwargs)
        if files.is_full_json_template(prompt):
            prompt = files.remove_code_fences(prompt)
        return prompt

    def get_data(self, field: str):
        return self.data.get(field, None)

    def set_data(self, field: str, value):
        self.data[field] = value

    def hist_add_message(
        self, ai: bool, content: history.MessageContent, tokens: int = 0
    ):
        self.last_message = datetime.now(timezone.utc)
        # Allow extensions to process content before adding to history
        content_data = {"content": content}
        asyncio.run(
            self.call_extensions("hist_add_before", content_data=content_data, ai=ai)
        )
        return self.history.add_message(
            ai=ai, content=content_data["content"], tokens=tokens
        )

    def hist_add_user_message(self, message: UserMessage, intervention: bool = False):
        self.history.new_topic()  # user message starts a new topic in history

        # load message template based on intervention
        if intervention:
            content = self.parse_prompt(
                "fw.intervention.md",
                message=message.message,
                attachments=message.attachments,
                system_message=message.system_message,
            )
        else:
            content = self.parse_prompt(
                "fw.user_message.md",
                message=message.message,
                attachments=message.attachments,
                system_message=message.system_message,
            )

        # remove empty parts from template
        if isinstance(content, dict):
            content = {k: v for k, v in content.items() if v}

        # add to history
        msg = self.hist_add_message(False, content=content)  # type: ignore
        self.last_user_message = msg
        return msg

    def hist_add_ai_response(self, message: str):
        self.loop_data.last_response = message
        content = self.parse_prompt("fw.ai_response.md", message=message)
        return self.hist_add_message(True, content=content)

    def hist_add_warning(self, message: history.MessageContent):
        content = self.parse_prompt("fw.warning.md", message=message)
        return self.hist_add_message(False, content=content)

    def hist_add_tool_result(self, tool_name: str, tool_result: str, **kwargs):
        data = {
            "tool_name": tool_name,
            "tool_result": tool_result,
            **kwargs,
        }
        asyncio.run(self.call_extensions("hist_add_tool_result", data=data))
        return self.hist_add_message(False, content=data)

    def concat_messages(
        self, messages
    ):  # TODO add param for message range, topic, history
        return self.history.output_text(human_label="user", ai_label="assistant")

    def get_chat_model(self):
        return models.get_chat_model(
            self.config.chat_model.provider,
            self.config.chat_model.name,
            model_config=self.config.chat_model,
            **self.config.chat_model.build_kwargs(),
        )

    def get_utility_model(self):
        return models.get_chat_model(
            self.config.utility_model.provider,
            self.config.utility_model.name,
            model_config=self.config.utility_model,
            **self.config.utility_model.build_kwargs(),
        )

    def get_browser_model(self):
        return models.get_browser_model(
            self.config.browser_model.provider,
            self.config.browser_model.name,
            model_config=self.config.browser_model,
            **self.config.browser_model.build_kwargs(),
        )

    def get_embedding_model(self):
        return models.get_embedding_model(
            self.config.embeddings_model.provider,
            self.config.embeddings_model.name,
            model_config=self.config.embeddings_model,
            **self.config.embeddings_model.build_kwargs(),
        )

    async def call_utility_model(
        self,
        system: str,
        message: str,
        callback: Callable[[str], Awaitable[None]] | None = None,
        background: bool = False,
    ):
        model = self.get_utility_model()

        # call extensions
        call_data = {
            "model": model,
            "system": system,
            "message": message,
            "callback": callback,
            "background": background,
        }
        await self.call_extensions("util_model_call_before", call_data=call_data)

        # propagate stream to callback if set
        async def stream_callback(chunk: str, total: str):
            if call_data["callback"]:
                await call_data["callback"](chunk)

        response, _reasoning = await call_data["model"].unified_call(
            system_message=call_data["system"],
            user_message=call_data["message"],
            response_callback=stream_callback if call_data["callback"] else None,
            rate_limiter_callback=(
                self.rate_limiter_callback if not call_data["background"] else None
            ),
        )

        return response

    async def call_chat_model(
        self,
        messages: list[BaseMessage],
        response_callback: Callable[[str, str], Awaitable[None]] | None = None,
        reasoning_callback: Callable[[str, str], Awaitable[None]] | None = None,
        background: bool = False,
        explicit_caching: bool = True,
    ):
        response = ""

        # model class
        model = self.get_chat_model()

        # call model
        response, reasoning = await model.unified_call(
            messages=messages,
            reasoning_callback=reasoning_callback,
            response_callback=response_callback,
            rate_limiter_callback=(
                self.rate_limiter_callback if not background else None
            ),
            explicit_caching=explicit_caching,
        )
        self.loop_data.params_temporary["last_model_call_diagnostics"] = getattr(
            model, "_last_call_diagnostics", {}
        )

        return response, reasoning

    async def rate_limiter_callback(
        self, message: str, key: str, total: int, limit: int
    ):
        # show the rate limit waiting in a progress bar, no need to spam the chat history
        self.context.log.set_progress(message, True)
        return False

    async def handle_intervention(self, progress: str = ""):
        while self.context.paused:
            await asyncio.sleep(0.1)  # wait if paused
        if (
            self.intervention
        ):  # if there is an intervention message, but not yet processed
            msg = self.intervention
            self.intervention = None  # reset the intervention message
            # If a tool was running, save its progress to history
            last_tool = self.loop_data.current_tool
            if last_tool:
                tool_progress = last_tool.progress.strip()
                if tool_progress:
                    self.hist_add_tool_result(last_tool.name, tool_progress)
                    last_tool.set_progress(None)
            if progress.strip():
                self.hist_add_ai_response(progress)
            # append the intervention message
            self.hist_add_user_message(msg, intervention=True)
            raise InterventionException(msg)

    async def wait_if_paused(self):
        while self.context.paused:
            await asyncio.sleep(0.1)

    async def process_tools(self, msg: str, consecutive_misformats: int = 0):
        self.loop_data.params_temporary["guardrail_misformat"] = False
        set = settings.get_effective_settings(self)
        execution_mode = self._get_execution_mode(set)
        # search for tool usage requests in agent message
        tool_request = extract_tools.json_parse_dirty(msg)

        if tool_request is not None:
            raw_tool_name = str(
                tool_request.get("tool_name", tool_request.get("tool", "")) or ""
            ).strip()  # Get the raw tool name
            tool_args = tool_request.get("tool_args", tool_request.get("args", {}))
            if not isinstance(tool_args, dict):
                tool_args = {}
            incomplete_tool_msg = self._incomplete_tool_envelope_message(
                raw_tool_name=raw_tool_name,
                tool_args=tool_args,
                raw_message=msg,
            )
            if incomplete_tool_msg:
                self.loop_data.params_temporary["guardrail_misformat"] = True
                self.hist_add_warning(incomplete_tool_msg)
                PrintStyle(font_color="orange", padding=True).print(incomplete_tool_msg)
                self.context.log.log(
                    type="warning",
                    content=f"{self.agent_name}: {incomplete_tool_msg}",
                )
                return incomplete_tool_msg

            response_bypass_text = self._response_tool_bypass_text(
                raw_tool_name=raw_tool_name,
                tool_args=tool_args,
                execution_mode=execution_mode,
                set=set,
            )
            if response_bypass_text is not None:
                self._log_plain_text_response(response_bypass_text)
                return response_bypass_text

            tool_args, execute_tool_args = self._normalize_tool_args(
                tool_args=tool_args,
                set=set,
            )
            preflight_msg = self._preflight_tool_call(
                raw_tool_name=raw_tool_name,
                execute_tool_args=execute_tool_args,
                set=set,
            )
            if preflight_msg:
                self.hist_add_warning(preflight_msg)
                PrintStyle(font_color="orange", padding=True).print(preflight_msg)
                self.context.log.log(
                    type="warning",
                    content=f"{self.agent_name}: {preflight_msg}",
                )
                self._flush_pending_post_tool_text(
                    execution_mode=execution_mode,
                    set=set,
                )
                return preflight_msg
            if bool(set.get("agent_guard_repeated_tool_action_enabled", False)):
                repeat_guard_message = self._check_repeated_tool_action_guard(
                    raw_tool_name=raw_tool_name,
                    execute_tool_args=execute_tool_args,
                    set=set,
                )
                if repeat_guard_message:
                    self.hist_add_warning(repeat_guard_message)
                    PrintStyle(font_color="orange", padding=True).print(repeat_guard_message)
                    self.context.log.log(
                        type="warning",
                        content=f"{self.agent_name}: {repeat_guard_message}",
                    )
                    self._flush_pending_post_tool_text(
                        execution_mode=execution_mode,
                        set=set,
                    )
                    return repeat_guard_message

            tool_name = raw_tool_name  # Initialize tool_name with raw_tool_name
            tool_method = None  # Initialize tool_method

            # Split raw_tool_name into tool_name and tool_method if applicable
            if ":" in raw_tool_name:
                tool_name, tool_method = raw_tool_name.split(":", 1)

            tool = None  # Initialize tool to None

            # Try getting tool from MCP first
            try:
                import python.helpers.mcp_handler as mcp_helper

                mcp_tool_candidate = mcp_helper.MCPConfig.get_instance().get_tool(
                    self, tool_name
                )
                if mcp_tool_candidate:
                    tool = mcp_tool_candidate
            except ImportError:
                PrintStyle(
                    background_color="black", font_color="yellow", padding=True
                ).print("MCP helper module not found. Skipping MCP tool lookup.")
            except Exception as e:
                PrintStyle(
                    background_color="black", font_color="red", padding=True
                ).print(f"Failed to get MCP tool '{tool_name}': {e}")

            # Fallback to local get_tool if MCP tool was not found or MCP lookup failed
            if not tool:
                tool = self.get_tool(
                    name=tool_name,
                    method=tool_method,
                    args=tool_args,
                    message=msg,
                    loop_data=self.loop_data,
                )

            if tool:
                self.loop_data.current_tool = tool  # type: ignore
                try:
                    await self.handle_intervention()

                    # Call tool hooks for compatibility
                    await tool.before_execution(**tool_args)
                    await self.handle_intervention()

                    # Allow extensions to preprocess tool arguments
                    await self.call_extensions(
                        "tool_execute_before",
                        tool_args=execute_tool_args or {},
                        tool_name=tool_name,
                    )
                    self._record_degradation_metric("tool_calls", 1)
                    response = await tool.execute(**execute_tool_args)
                    await self.handle_intervention()

                    # Allow extensions to postprocess tool response
                    await self.call_extensions(
                        "tool_execute_after", response=response, tool_name=tool_name
                    )

                    await tool.after_execution(response)
                    await self.handle_intervention()

                    hard_stop_message = self._check_hard_stop_tool_response(
                        tool_name=raw_tool_name,
                        tool_result=(response.message or ""),
                    )
                    if hard_stop_message:
                        self._flush_pending_post_tool_text(
                            execution_mode=execution_mode,
                            set=set,
                        )
                        return hard_stop_message

                    if response.break_loop:
                        # Ensure break-loop tool results are rendered in the UI
                        # (e.g., deterministic file reads) before returning.
                        self._log_plain_text_response(response.message or "")
                        self._flush_pending_post_tool_text(
                            execution_mode=execution_mode,
                            set=set,
                        )
                        return response.message
                finally:
                    self.loop_data.current_tool = None
            else:
                error_detail = (
                    f"Tool '{raw_tool_name}' not found or could not be initialized."
                )
                self.hist_add_warning(error_detail)
                PrintStyle(font_color="red", padding=True).print(error_detail)
                self.context.log.log(
                    type="warning", content=f"{self.agent_name}: {error_detail}"
                )
            self._flush_pending_post_tool_text(
                execution_mode=execution_mode,
                set=set,
            )
        else:
            # Ensure trailing text queued by a prior mixed/tool segment does not
            # leak into a later non-tool turn.
            self.loop_data.params_temporary.pop("pending_post_tool_text", None)
            if (
                execution_mode in ("hybrid", "model_first")
                and bool(set.get("agent_execution_allow_plain_text_response", False))
                and bool(set.get("agent_execution_require_tool_for_risky_intents", True))
                and self._is_risky_user_intent(set)
            ):
                mode_guard = (
                    "[EXECUTION_MODE:TOOL_ROUTE_REQUIRED] "
                    "This request appears executable/risky; emit a JSON tool call instead of plain text."
                )
                self.hist_add_warning(mode_guard)
                PrintStyle(font_color="orange", padding=True).print(mode_guard)
                self.context.log.log(
                    type="warning",
                    content=f"{self.agent_name}: {mode_guard}",
                )
            if self._should_accept_plain_text_response(
                msg=msg,
                execution_mode=execution_mode,
                consecutive_misformats=consecutive_misformats,
                set=set,
            ):
                self._log_plain_text_response(msg)
                return msg
            self.loop_data.params_temporary["guardrail_misformat"] = True
            warning_msg_misformat = self.read_prompt("fw.msg_misformat.md")
            self.hist_add_warning(warning_msg_misformat)
            PrintStyle(font_color="red", padding=True).print(warning_msg_misformat)
            self.context.log.log(
                type="warning",
                content=f"{self.agent_name}: Message misformat, no valid tool request found.",
            )

    def _get_execution_mode(self, set: settings.Settings) -> str:
        mode = str(set.get("agent_execution_mode", "tool_first")).strip().lower()
        if mode not in ("tool_first", "tool_first_fallback", "hybrid", "model_first"):
            return "tool_first"
        return mode

    def _should_accept_plain_text_response(
        self,
        msg: str,
        execution_mode: str,
        consecutive_misformats: int,
        set: settings.Settings,
    ) -> bool:
        if not bool(set.get("agent_execution_allow_plain_text_response", False)):
            return False
        if not (msg or "").strip():
            return False

        if execution_mode == "tool_first":
            return False

        if execution_mode == "tool_first_fallback":
            threshold = int(set.get("agent_tool_first_fallback_after_misformats", 2))
            if threshold < 1:
                threshold = 1
            return (consecutive_misformats + 1) >= threshold

        if execution_mode in ("hybrid", "model_first"):
            if (
                bool(set.get("agent_execution_require_tool_for_risky_intents", True))
                and self._is_risky_user_intent(set)
            ):
                return False
            return True

        return False

    def _response_tool_bypass_text(
        self,
        raw_tool_name: str,
        tool_args: dict,
        execution_mode: str,
        set: settings.Settings,
    ) -> str | None:
        if raw_tool_name != "response":
            return None
        if execution_mode not in ("hybrid", "model_first"):
            return None
        if not bool(set.get("agent_execution_allow_plain_text_response", False)):
            return None
        if (
            bool(set.get("agent_execution_require_tool_for_risky_intents", True))
            and self._is_risky_user_intent(set)
        ):
            return None
        response_text = self._extract_response_text(tool_args)
        if not response_text:
            return None
        return response_text

    def _extract_response_text(self, tool_args: dict[str, Any]) -> str:
        text = tool_args.get("text", tool_args.get("message", ""))
        if text is None:
            return ""
        return str(text).strip()

    def _incomplete_tool_envelope_message(
        self, raw_tool_name: str, tool_args: dict[str, Any], raw_message: str = ""
    ) -> str | None:
        text = str(raw_message or "").strip()
        if text.startswith("{") and '"tool_name"' in text and not text.endswith("}"):
            return (
                "[TOOL_JSON_INCOMPLETE] Tool JSON appears truncated before closing brace. "
                "Regenerate complete JSON."
            )
        if not str(raw_tool_name or "").strip():
            return (
                "[TOOL_JSON_INCOMPLETE] Missing `tool_name` in tool envelope. "
                "Regenerate complete JSON."
            )
        if raw_tool_name in {"code", "code_execution", "code_execution_"}:
            return (
                "[TOOL_JSON_INCOMPLETE] `tool_name` appears truncated "
                f"({raw_tool_name!r}); expected 'code_execution_tool'."
            )
        if raw_tool_name != "code_execution_tool":
            return None
        if not tool_args:
            return (
                "[TOOL_JSON_INCOMPLETE] code_execution_tool is missing `tool_args`. "
                "Regenerate complete JSON."
            )
        runtime = tool_args.get("runtime")
        if runtime is None:
            return None
        if not str(runtime).strip():
            return (
                "[TOOL_JSON_INCOMPLETE] code_execution_tool payload appears partial "
                "(empty `runtime`). Regenerate complete JSON."
            )
        return None

    def _log_plain_text_response(self, message: str) -> None:
        if not (message or "").strip():
            return
        key = "log_item_response"
        log_item = self.loop_data.params_temporary.get(key)
        if log_item is None:
            log_item = self.context.log.log(
                type="response",
                heading=f"icon://chat {self.agent_name}: Responding",
            )
            self.loop_data.params_temporary[key] = log_item
        log_item.update(content=message)

    def _flush_pending_post_tool_text(
        self,
        execution_mode: Literal["tool_first", "tool_first_fallback", "hybrid", "model_first"],
        set: settings.Settings,
    ) -> None:
        key = "pending_post_tool_text"
        text = self.loop_data.params_temporary.pop(key, "")
        if not isinstance(text, str):
            text = str(text or "")
        text = text.strip()
        if not text:
            return
        if not self._should_accept_plain_text_response(
            msg=text,
            execution_mode=execution_mode,
            consecutive_misformats=0,
            set=set,
        ):
            return
        # Emit trailing text as a separate response bubble after tool execution.
        self.loop_data.params_temporary.pop("log_item_response", None)
        self._log_plain_text_response(text)

    def _debug_stream_to_console(self, set: settings.Settings) -> bool:
        return bool(set.get("agent_debug_mode_enabled", False))

    def _debug_capture_enabled(self, set: settings.Settings) -> bool:
        return self._debug_stream_to_console(set) and bool(
            set.get("agent_debug_capture_full_llm_exchange", False)
        )

    def _truncate_debug_value(self, value: Any, max_chars: int) -> str:
        if value is None:
            text = ""
        elif isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, indent=2)
            except Exception:
                text = str(value)
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        omitted = len(text) - max_chars
        return f"{text[:max_chars]}\n\n<<< truncated {omitted} chars >>>"

    def _build_llm_debug_trace_payload(self, prompt: list[BaseMessage]) -> dict[str, Any]:
        set = settings.get_effective_settings(self)
        max_chars = int(set.get("agent_debug_capture_max_chars", 400000))
        context_id = getattr(self.context, "id", "")
        history_counter = int(getattr(self.history, "counter", 0) or 0)
        payload: dict[str, Any] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "context_id": context_id,
            "agent_name": self.agent_name,
            "iteration": int(getattr(self.loop_data, "iteration", 0)),
            "history_message_count": history_counter,
            "settings": {
                "agent_execution_mode": set.get("agent_execution_mode", "tool_first"),
                "agent_execution_allow_plain_text_response": bool(
                    set.get("agent_execution_allow_plain_text_response", False)
                ),
                "agent_execution_require_tool_for_risky_intents": bool(
                    set.get("agent_execution_require_tool_for_risky_intents", True)
                ),
            },
            "ctx_window": self.get_data(Agent.DATA_NAME_CTX_WINDOW),
        }

        serialized_prompt: list[dict[str, Any]] = []
        for msg in prompt:
            role = msg.__class__.__name__
            content = self._truncate_debug_value(getattr(msg, "content", ""), max_chars)
            serialized_prompt.append({"role": role, "content": content})
        payload["prompt_messages"] = serialized_prompt
        payload["prompt_compiled"] = self._truncate_debug_value(
            self.get_data(Agent.DATA_NAME_CTX_WINDOW), max_chars
        )
        payload["_debug_max_chars"] = max_chars
        return payload

    def _write_llm_debug_trace_payload(
        self, payload: dict[str, Any], response: str, reasoning: str | None
    ) -> None:
        try:
            set = settings.get_effective_settings(self)
            trace_dir_rel = str(set.get("agent_debug_capture_dir", "logs/llm_debug")).strip() or "logs/llm_debug"
            max_chars = int(set.get("agent_debug_capture_max_chars", 400000))
            payload = dict(payload)
            payload["model_call_diagnostics"] = self.loop_data.params_temporary.get(
                "last_model_call_diagnostics", {}
            )
            payload["response"] = self._truncate_debug_value(response, max_chars)
            payload["reasoning"] = self._truncate_debug_value(reasoning or "", max_chars)
            payload["response_length"] = len(response or "")
            payload["reasoning_length"] = len(reasoning or "")
            file_name = (
                f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}"
                f"__ctx_{self.context.id}__iter_{int(getattr(self.loop_data, 'iteration', 0))}.json"
            )
            trace_dir_abs = files.get_abs_path(trace_dir_rel)
            os.makedirs(trace_dir_abs, exist_ok=True)
            out_path = files.get_abs_path(trace_dir_abs, file_name)
            with open(out_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except Exception as e:
            # Never break agent execution for debug capture failures.
            PrintStyle(font_color="orange", padding=True).print(
                f"Debug trace capture failed: {e}"
            )

    def _is_risky_user_intent(self, set: settings.Settings) -> bool:
        text = self._latest_user_message_text().lower()
        if not text:
            return False
        pattern = str(set.get("agent_execution_risky_intent_regex", "")).strip()
        if not pattern:
            return False
        try:
            return re.search(pattern, text, flags=re.IGNORECASE) is not None
        except re.error:
            # Fail safe: if regex is invalid, rely on static keyword fallback.
            return any(
                token in text
                for token in (
                    "write ",
                    "edit ",
                    "modify ",
                    "update ",
                    "create file",
                    "delete ",
                    "remove ",
                    "run ",
                    "execute ",
                    "terminal",
                    "shell",
                    "command",
                )
            )

    def _latest_user_message_text(self) -> str:
        msg = self.last_user_message
        if not msg:
            return ""
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            candidate = content.get("user_message")
            if isinstance(candidate, str):
                return candidate
            raw = content.get("raw_content")
            if isinstance(raw, str):
                return raw
            return json.dumps(content, ensure_ascii=True)
        return str(content)

    def _check_hard_stop_tool_response(self, tool_name: str, tool_result: str) -> str | None:
        set = settings.get_effective_settings(self)
        if not bool(set.get("agent_guard_context_hard_stop_enabled", False)):
            return None
        text = (tool_result or "").lower()
        if "context_missing_hard_stop" in text or "no context id provided" in text:
            self._record_degradation_metric("missing_context_errors", 1)
            return self._terminate_for_guardrail(
                reason="missing context id in tool/API flow",
                detail=f"tool={tool_name}; hard-stop to prevent retry loops",
            )
        return None

    def _check_repeated_tool_action_guard(
        self,
        raw_tool_name: str,
        execute_tool_args: dict[str, Any],
        set: settings.Settings,
    ) -> str | None:
        threshold = int(set.get("tool_repeat_signature_threshold", 1))
        if threshold < 0:
            threshold = 0
        window_seconds = int(set.get("tool_repeat_signature_window_seconds", 180))
        if window_seconds < 1:
            window_seconds = 1

        signature = self._build_tool_action_signature(raw_tool_name, execute_tool_args)
        now = time.time()
        state = self.loop_data.params_persistent.setdefault("_tool_action_signatures", {})
        prev = state.get(signature, {})
        last_ts = float(prev.get("ts", 0) or 0)
        count = int(prev.get("count", 0) or 0)
        if (now - last_ts) <= window_seconds:
            count += 1
        else:
            count = 1
        state[signature] = {
            "count": count,
            "ts": now,
            "tool_name": raw_tool_name,
        }
        self.loop_data.params_persistent["_tool_action_signatures"] = state

        max_allowed = threshold + 1  # first execution + N repeats
        if count > max_allowed:
            self._record_degradation_metric("guardrail_hits", 1)
            return (
                "[TOOL_GUARD:REPEATED_ACTION_HARD_STOP] "
                f"Blocked repeated identical tool action for `{raw_tool_name}` "
                f"(count={count}, max_allowed={max_allowed}, window={window_seconds}s). "
                "Do not retry the same call again in this turn; switch strategy or ask for user clarification."
            )
        return None

    def _build_tool_action_signature(
        self, raw_tool_name: str, execute_tool_args: dict[str, Any]
    ) -> str:
        normalized = self._normalize_tool_signature_payload(execute_tool_args)
        payload = json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
        )
        digest = hashlib.sha256(f"{raw_tool_name}|{payload}".encode("utf-8")).hexdigest()
        return digest

    def _normalize_tool_signature_payload(self, value: Any) -> Any:
        if isinstance(value, str):
            compact = " ".join(value.split())
            if len(compact) > 512:
                short_hash = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:16]
                return f"<str:{len(compact)}:{short_hash}>"
            return compact
        if isinstance(value, dict):
            return {k: self._normalize_tool_signature_payload(v) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [self._normalize_tool_signature_payload(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self._normalize_tool_signature_payload(v) for v in value)
        if isinstance(value, set):
            return sorted(self._normalize_tool_signature_payload(v) for v in value)
        return value

    def _normalize_tool_args(
        self,
        tool_args: dict[str, Any],
        set: settings.Settings,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        max_chars = int(set.get("tool_args_max_chars", 120000))
        spill_threshold_chars = int(set.get("tool_args_spill_threshold_chars", 20000))
        spill_dir = str(set.get("tool_args_spill_dir", "usr/tmp/tool_args"))
        autorewrite_enabled = bool(set.get("tool_args_autorewrite_enabled", True))

        payload_chars = extract_tools.json_chars(tool_args)
        if max_chars > 0 and payload_chars > max_chars:
            msg = self.read_prompt(
                "fw.msg_tool_args_too_large.md",
                payload_chars=payload_chars,
                max_chars=max_chars,
            )
            raise RepairableException(msg)

        if not autorewrite_enabled or spill_threshold_chars <= 0:
            return tool_args, tool_args

        display_args, spill_count = self._spill_large_tool_args_values(
            value=tool_args,
            threshold_chars=spill_threshold_chars,
            spill_dir=spill_dir,
        )
        if spill_count <= 0:
            return display_args, display_args

        execute_args = self._resolve_spilled_tool_args(display_args)
        warning = self.read_prompt(
            "fw.msg_tool_args_spilled.md",
            spill_count=spill_count,
            payload_chars=payload_chars,
            threshold_chars=spill_threshold_chars,
        )
        self.hist_add_warning(warning)
        self.context.log.log(
            type="warning",
            content=f"{self.agent_name}: {warning}",
        )
        PrintStyle(font_color="orange", padding=True).print(warning)

        return display_args, execute_args

    def _spill_large_tool_args_values(
        self,
        value: Any,
        threshold_chars: int,
        spill_dir: str,
    ) -> tuple[Any, int]:
        spill_count = 0

        if isinstance(value, str):
            if len(value) <= threshold_chars:
                return value, spill_count
            spill_path = self._write_tool_arg_spill(value, spill_dir)
            return f"§§include({spill_path})", 1

        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, nested in value.items():
                new_value, nested_count = self._spill_large_tool_args_values(
                    nested, threshold_chars, spill_dir
                )
                out[key] = new_value
                spill_count += nested_count
            return out, spill_count

        if isinstance(value, list):
            out_list: list[Any] = []
            for nested in value:
                new_value, nested_count = self._spill_large_tool_args_values(
                    nested, threshold_chars, spill_dir
                )
                out_list.append(new_value)
                spill_count += nested_count
            return out_list, spill_count

        if isinstance(value, tuple):
            out_tuple: list[Any] = []
            for nested in value:
                new_value, nested_count = self._spill_large_tool_args_values(
                    nested, threshold_chars, spill_dir
                )
                out_tuple.append(new_value)
                spill_count += nested_count
            return tuple(out_tuple), spill_count

        return value, spill_count

    def _write_tool_arg_spill(self, content: str, spill_dir: str) -> str:
        timestamp = int(time.time() * 1000)
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        filename = f"tool_args_{timestamp}_{suffix}.txt"
        rel_path = os.path.join(spill_dir, filename)
        files.write_file(rel_path, content)
        return files.get_abs_path(rel_path)

    def _resolve_spilled_tool_args(self, value: Any) -> Any:
        if isinstance(value, str):
            return strings.replace_file_includes(value)
        if isinstance(value, dict):
            return {k: self._resolve_spilled_tool_args(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_spilled_tool_args(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self._resolve_spilled_tool_args(v) for v in value)
        return value

    def _record_degradation_metric(self, key: str, delta: int = 1) -> None:
        try:
            now = time.time()
            state = self.loop_data.params_persistent.setdefault("_degradation_metrics", {})
            entry = state.get(key, {"count": 0, "ts": now, "window": []})
            count = int(entry.get("count", 0) or 0) + delta
            window = list(entry.get("window", []))
            window.append(now)
            if len(window) > 200:
                window = window[-200:]
            state[key] = {"count": count, "ts": now, "window": window}
            self.loop_data.params_persistent["_degradation_metrics"] = state
        except Exception:
            return

    def _read_degradation_metric(self, key: str) -> dict[str, Any]:
        state = self.loop_data.params_persistent.get("_degradation_metrics", {})
        got = state.get(key, {})
        return {
            "count": int(got.get("count", 0) or 0),
            "window": list(got.get("window", [])),
            "ts": float(got.get("ts", 0) or 0),
        }

    def _check_degradation_auto_abort(self, set: settings.Settings) -> str | None:
        if not bool(set.get("agent_degradation_auto_abort_enabled", False)):
            return None
        tool_call_ceiling = int(set.get("agent_tool_call_ceiling_per_turn", 30))
        guardrail_hits_per_minute = int(set.get("agent_guardrail_hits_ceiling_per_minute", 8))
        missing_context_ceiling = int(set.get("agent_missing_context_errors_ceiling_per_turn", 1))

        tool_calls = self._read_degradation_metric("tool_calls")["count"]
        if tool_call_ceiling > 0 and tool_calls >= tool_call_ceiling:
            return self._terminate_for_guardrail(
                reason="degradation auto-abort: excessive tool calls",
                detail=f"tool_calls={tool_calls}, ceiling={tool_call_ceiling}",
            )

        missing_context_errors = self._read_degradation_metric("missing_context_errors")["count"]
        if missing_context_ceiling > 0 and missing_context_errors >= missing_context_ceiling:
            return self._terminate_for_guardrail(
                reason="degradation auto-abort: repeated missing context errors",
                detail=(
                    f"missing_context_errors={missing_context_errors}, "
                    f"ceiling={missing_context_ceiling}"
                ),
            )

        hits = self._read_degradation_metric("guardrail_hits")
        now = time.time()
        per_minute = [
            ts for ts in hits["window"] if isinstance(ts, (int, float)) and (now - float(ts)) <= 60
        ]
        if guardrail_hits_per_minute > 0 and len(per_minute) >= guardrail_hits_per_minute:
            return self._terminate_for_guardrail(
                reason="degradation auto-abort: guardrail hit rate too high",
                detail=(
                    f"guardrail_hits_last_minute={len(per_minute)}, "
                    f"ceiling={guardrail_hits_per_minute}"
                ),
            )
        return None

    def _preflight_tool_call(
        self,
        raw_tool_name: str,
        execute_tool_args: dict[str, Any],
        set: settings.Settings,
    ) -> str | None:
        if not bool(set.get("code_exec_tool_preflight_enabled", False)):
            return None
        tool_name = str(raw_tool_name or "").split(":", 1)[0]
        if tool_name != "code_execution_tool":
            return None
        return self._preflight_code_execution_tool_args(execute_tool_args)

    def _preflight_code_execution_tool_args(self, args: dict[str, Any]) -> str | None:
        if not str(getattr(self.context, "id", "")).strip():
            return (
                "[TOOL_PREFLIGHT:MISSING_CONTEXT] context id is missing; "
                "request a fresh context-bound operation."
            )
        runtime_name = str(args.get("runtime", "")).strip().lower()
        valid_runtimes = {"python", "nodejs", "terminal", "file", "output", "reset"}
        if runtime_name not in valid_runtimes:
            return (
                "[TOOL_PREFLIGHT:INVALID_RUNTIME] code_execution_tool requires a valid `runtime` "
                f"({sorted(valid_runtimes)}). Got {runtime_name!r}."
            )
        workdir = str(settings.get_effective_settings(self).get("workdir_path", "")).strip()
        if not workdir:
            return (
                "[TOOL_PREFLIGHT:MISSING_WORKSPACE_ROOT] workdir_path is empty; "
                "cannot safely execute path-affecting operations."
            )

        if runtime_name in {"python", "nodejs", "terminal"}:
            code = args.get("code", "")
            if not isinstance(code, str) or not code.strip():
                return (
                    "[TOOL_PREFLIGHT:MISSING_CODE] code_execution_tool runtime requires non-empty "
                    "`code` content."
                )
            return None

        if runtime_name == "file":
            path = args.get("path", "")
            if not isinstance(path, str) or not path.strip():
                return "[TOOL_PREFLIGHT:MISSING_PATH] file runtime requires non-empty `path`."
            normalized = files.normalize_a0_path(path.strip())
            target = os.path.abspath(normalized)
            if target in {"/", os.path.abspath(workdir)}:
                return (
                    "[TOOL_PREFLIGHT:UNSAFE_PATH] file runtime path resolves to an unsafe root/"
                    "directory target. Provide a concrete file path."
                )
            if "content" not in args:
                return "[TOOL_PREFLIGHT:MISSING_CONTENT] file runtime requires `content`."
        return None

    def _classify_retry_policy(
        self, e: Exception, set: settings.Settings
    ) -> tuple[str, int, int]:
        text = errors.format_error(e).lower()
        if any(
            token in text
            for token in [
                "context_missing_hard_stop",
                "no context id provided",
                "stale_epoch_rejected",
                "context not found",
                "unauthorized",
                "forbidden",
                "csrf",
                "invalid csrf token",
            ]
        ):
            return "context_session_auth", 0, 0
        if any(
            token in text
            for token in [
                "[read_guard",
                "[write_guard",
                "[tool_guard",
                "[strategy_guard",
                "guardrail",
            ]
        ):
            return "guardrail", 0, 0
        if any(
            token in text
            for token in [
                "timeout",
                "timed out",
                "temporarily unavailable",
                "connection reset",
                "connection refused",
                "502",
                "503",
                "504",
                "429",
                "rate limit",
                "network",
            ]
        ):
            return (
                "transient_io_network",
                int(set.get("agent_transient_error_max_retries", 2)),
                int(set.get("agent_transient_error_retry_delay_seconds", 2)),
            )
        return (
            "other_critical",
            int(set.get("agent_critical_error_max_retries", 1)),
            int(set.get("agent_critical_error_retry_delay_seconds", 3)),
        )

    async def handle_reasoning_stream(self, stream: str):
        await self.handle_intervention()
        await self.call_extensions(
            "reasoning_stream",
            loop_data=self.loop_data,
            text=stream,
        )

    async def handle_response_stream(self, stream: str):
        await self.handle_intervention()
        try:
            set = settings.get_effective_settings(self)
            execution_mode = self._get_execution_mode(set)
            stripped = (stream or "").lstrip()
            if (
                stripped
                and not stripped.startswith("{")
                and self._should_accept_plain_text_response(
                    msg=stream,
                    execution_mode=execution_mode,
                    consecutive_misformats=0,
                    set=set,
                )
            ):
                # Plain-text outputs do not pass through JSON tool parsing,
                # so mirror them into the response log as they stream.
                self._log_plain_text_response(stream)
            if len(stream) < 25:
                return  # no reason to try
            response = DirtyJson.parse_string(stream)
            if isinstance(response, dict):
                await self.call_extensions(
                    "response_stream",
                    loop_data=self.loop_data,
                    text=stream,
                    parsed=response,
                )

        except Exception as e:
            pass

    def get_tool(
        self,
        name: str,
        method: str | None,
        args: dict,
        message: str,
        loop_data: LoopData | None,
        **kwargs,
    ):
        from python.tools.unknown import Unknown
        from python.helpers.tool import Tool

        classes = []

        # search for tools in agent's folder hierarchy
        paths = subagents.get_paths(self, "tools", name + ".py", default_root="python")
        for path in paths:
            try:
                classes = extract_tools.load_classes_from_file(path, Tool)  # type: ignore[arg-type]
                break
            except Exception:
                continue

        tool_class = classes[0] if classes else Unknown
        return tool_class(
            agent=self,
            name=name,
            method=method,
            args=args,
            message=message,
            loop_data=loop_data,
            **kwargs,
        )

    async def call_extensions(self, extension_point: str, **kwargs) -> Any:
        return await call_extensions(
            extension_point=extension_point, agent=self, **kwargs
        )
