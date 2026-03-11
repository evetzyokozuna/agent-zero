import sys
from pathlib import Path
from types import SimpleNamespace
import types

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Provide lightweight stubs for optional heavy runtime deps used during imports.
if "sentence_transformers" not in sys.modules:
    stub = types.ModuleType("sentence_transformers")
    class _DummySentenceTransformer:
        def __init__(self, *args, **kwargs):
            pass
    stub.SentenceTransformer = _DummySentenceTransformer
    sys.modules["sentence_transformers"] = stub

if "whisper" not in sys.modules:
    whisper_stub = types.ModuleType("whisper")
    whisper_stub.load_model = lambda *args, **kwargs: None
    sys.modules["whisper"] = whisper_stub


from agent import Agent


pytestmark = pytest.mark.tier1


def _make_agent_with_user_text(text: str) -> Agent:
    agent = Agent.__new__(Agent)
    agent.last_user_message = SimpleNamespace(content={"user_message": text})
    return agent


def test_get_execution_mode_defaults_to_tool_first_on_invalid_value() -> None:
    agent = _make_agent_with_user_text("hello")
    got = agent._get_execution_mode({"agent_execution_mode": "unknown"})
    assert got == "tool_first"


def test_tool_first_never_accepts_plain_text_even_when_allow_flag_true() -> None:
    agent = _make_agent_with_user_text("explain this")
    set_data = {
        "agent_execution_allow_plain_text_response": True,
        "agent_execution_require_tool_for_risky_intents": True,
        "agent_execution_risky_intent_regex": r"write|edit|run",
    }
    assert (
        agent._should_accept_plain_text_response(
            msg="plain answer",
            execution_mode="tool_first",
            consecutive_misformats=3,
            set=set_data,
        )
        is False
    )


def test_tool_first_fallback_accepts_plain_text_after_threshold() -> None:
    agent = _make_agent_with_user_text("explain this")
    set_data = {
        "agent_execution_allow_plain_text_response": True,
        "agent_tool_first_fallback_after_misformats": 2,
        "agent_execution_require_tool_for_risky_intents": True,
        "agent_execution_risky_intent_regex": r"write|edit|run",
    }
    assert (
        agent._should_accept_plain_text_response(
            msg="plain answer",
            execution_mode="tool_first_fallback",
            consecutive_misformats=1,
            set=set_data,
        )
        is True
    )


def test_hybrid_accepts_plain_text_for_non_risky_intent() -> None:
    agent = _make_agent_with_user_text("summarize this architecture")
    set_data = {
        "agent_execution_allow_plain_text_response": True,
        "agent_execution_require_tool_for_risky_intents": True,
        "agent_execution_risky_intent_regex": r"write|edit|run|delete",
    }
    assert (
        agent._should_accept_plain_text_response(
            msg="summary text",
            execution_mode="hybrid",
            consecutive_misformats=0,
            set=set_data,
        )
        is True
    )


def test_hybrid_blocks_plain_text_for_risky_intent_when_enforced() -> None:
    agent = _make_agent_with_user_text("edit Today.md with this content")
    set_data = {
        "agent_execution_allow_plain_text_response": True,
        "agent_execution_require_tool_for_risky_intents": True,
        "agent_execution_risky_intent_regex": r"write|edit|run|delete",
    }
    assert (
        agent._should_accept_plain_text_response(
            msg="I edited it",
            execution_mode="hybrid",
            consecutive_misformats=0,
            set=set_data,
        )
        is False
    )


def test_model_first_allows_plain_text_when_risky_gate_disabled() -> None:
    agent = _make_agent_with_user_text("run a command now")
    set_data = {
        "agent_execution_allow_plain_text_response": True,
        "agent_execution_require_tool_for_risky_intents": False,
        "agent_execution_risky_intent_regex": r"write|edit|run|delete",
    }
    assert (
        agent._should_accept_plain_text_response(
            msg="non-tool explanation",
            execution_mode="model_first",
            consecutive_misformats=0,
            set=set_data,
        )
        is True
    )


def test_risky_intent_classifier_falls_back_when_regex_invalid() -> None:
    agent = _make_agent_with_user_text("please run this shell command")
    set_data = {"agent_execution_risky_intent_regex": r"("}
    assert agent._is_risky_user_intent(set_data) is True


def test_response_tool_bypass_returns_text_for_non_risky_hybrid() -> None:
    agent = _make_agent_with_user_text("tell me what changed")
    set_data = {
        "agent_execution_allow_plain_text_response": True,
        "agent_execution_require_tool_for_risky_intents": True,
        "agent_execution_risky_intent_regex": r"write|edit|run|delete",
    }
    text = agent._response_tool_bypass_text(
        raw_tool_name="response",
        tool_args={"text": "Plain answer"},
        execution_mode="hybrid",
        set=set_data,
    )
    assert text == "Plain answer"


def test_response_tool_bypass_blocks_for_risky_intent() -> None:
    agent = _make_agent_with_user_text("edit Today.md now")
    set_data = {
        "agent_execution_allow_plain_text_response": True,
        "agent_execution_require_tool_for_risky_intents": True,
        "agent_execution_risky_intent_regex": r"write|edit|run|delete",
    }
    text = agent._response_tool_bypass_text(
        raw_tool_name="response",
        tool_args={"text": "Done"},
        execution_mode="model_first",
        set=set_data,
    )
    assert text is None


def test_log_plain_text_response_creates_or_updates_response_log() -> None:
    class _LogItem:
        def __init__(self):
            self.content = ""

        def update(self, content=None, **_kwargs):
            if content is not None:
                self.content = content

    class _Log:
        def __init__(self):
            self.items = []

        def log(self, **_kwargs):
            item = _LogItem()
            self.items.append(item)
            return item

    agent = _make_agent_with_user_text("hello")
    agent.agent_name = "A0"
    agent.loop_data = SimpleNamespace(params_temporary={})
    agent.context = SimpleNamespace(log=_Log())

    agent._log_plain_text_response("First")
    agent._log_plain_text_response("Second")

    assert len(agent.context.log.items) == 1
    assert agent.context.log.items[0].content == "Second"


def test_build_llm_debug_trace_payload_uses_history_counter() -> None:
    agent = _make_agent_with_user_text("hello")
    agent.agent_name = "A0"
    agent.context = SimpleNamespace(id="ctx-1")
    agent.loop_data = SimpleNamespace(iteration=2)
    agent.history = SimpleNamespace(counter=7)
    agent.get_data = lambda _key: "ctx-window"

    payload = agent._build_llm_debug_trace_payload(prompt=[])

    assert payload["context_id"] == "ctx-1"
    assert payload["history_message_count"] == 7


def test_incomplete_tool_envelope_message_for_empty_runtime() -> None:
    agent = _make_agent_with_user_text("hello")
    msg = agent._incomplete_tool_envelope_message(
        raw_tool_name="code_execution_tool",
        tool_args={"runtime": ""},
    )
    assert msg is not None
    assert "TOOL_JSON_INCOMPLETE" in msg


def test_incomplete_tool_envelope_message_for_missing_tool_name() -> None:
    agent = _make_agent_with_user_text("hello")
    msg = agent._incomplete_tool_envelope_message(
        raw_tool_name="",
        tool_args={},
    )
    assert msg is not None
    assert "Missing `tool_name`" in msg


def test_incomplete_tool_envelope_message_for_truncated_tool_name() -> None:
    agent = _make_agent_with_user_text("hello")
    msg = agent._incomplete_tool_envelope_message(
        raw_tool_name="code",
        tool_args={},
    )
    assert msg is not None
    assert "appears truncated" in msg


def test_incomplete_tool_envelope_message_for_truncated_json_text() -> None:
    agent = _make_agent_with_user_text("hello")
    msg = agent._incomplete_tool_envelope_message(
        raw_tool_name="code_execution_tool",
        tool_args={},
        raw_message='{"tool_name":"code_execution_tool","tool_args":{"runtime":"terminal"',
    )
    assert msg is not None
    assert "truncated before closing brace" in msg


def test_preflight_tool_call_handles_none_tool_name_without_crash() -> None:
    agent = _make_agent_with_user_text("hello")
    out = agent._preflight_tool_call(
        raw_tool_name=None,  # type: ignore[arg-type]
        execute_tool_args={"runtime": "terminal", "code": "echo hi"},
        set={"code_exec_tool_preflight_enabled": True},
    )
    assert out is None
