import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from python.helpers import files


pytestmark = pytest.mark.tier1


def _read_comm_prompt(**kwargs) -> str:
    return files.read_prompt_file(
        "agent.system.main.communication.md",
        _directories=[str(PROJECT_ROOT / "prompts")],
        **kwargs,
    )


def test_tool_first_prompt_requires_strict_json_contract() -> None:
    prompt = _read_comm_prompt(
        execution_mode="tool_first",
        allow_plain_text_response=False,
        require_tool_for_risky_intents=True,
    )
    assert "respond valid json with fields" in prompt
    assert "no text allowed before or after json" in prompt


def test_hybrid_prompt_with_plain_text_enabled_mentions_dual_format() -> None:
    prompt = _read_comm_prompt(
        execution_mode="hybrid",
        allow_plain_text_response=True,
        require_tool_for_risky_intents=True,
    )
    assert "you may answer in one of two formats" in prompt
    assert "plain text response for informational/non-executable requests" in prompt
    assert "you must use a json tool call" in prompt


def test_model_first_prompt_prefers_plain_text() -> None:
    prompt = _read_comm_prompt(
        execution_mode="model_first",
        allow_plain_text_response=True,
        require_tool_for_risky_intents=True,
    )
    assert "default to plain text for informational requests" in prompt
    assert "use json tool calls only when execution is needed" in prompt
