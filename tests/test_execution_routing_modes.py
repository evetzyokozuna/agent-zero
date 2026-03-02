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
