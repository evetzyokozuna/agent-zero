import sys
from pathlib import Path
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


from python.helpers import settings


pytestmark = pytest.mark.tier1


def test_execution_mode_defaults_are_backward_compatible() -> None:
    defaults = settings.get_default_settings()
    assert defaults["agent_execution_mode"] == "tool_first"
    assert defaults["agent_execution_allow_plain_text_response"] is False
    assert defaults["agent_execution_require_tool_for_risky_intents"] is True
    assert defaults["agent_tool_first_fallback_after_misformats"] == 2
    assert "write" in defaults["agent_execution_risky_intent_regex"]


def test_execution_mode_env_overrides_apply() -> None:
    # Patch lookup used by settings.get_default_value.
    overrides = {
        "A0_SET_agent_execution_mode": "hybrid",
        "A0_SET_agent_execution_allow_plain_text_response": "true",
        "A0_SET_agent_execution_require_tool_for_risky_intents": "false",
        "A0_SET_agent_tool_first_fallback_after_misformats": "4",
        "A0_SET_agent_execution_risky_intent_regex": r"\b(run|execute)\b",
    }

    original = settings.dotenv.get_dotenv_value

    def _fake_get(key: str, default=None):
        return overrides.get(key, default)

    settings.dotenv.get_dotenv_value = _fake_get  # type: ignore[assignment]
    try:
        got = settings.get_default_settings()
    finally:
        settings.dotenv.get_dotenv_value = original  # type: ignore[assignment]

    assert got["agent_execution_mode"] == "hybrid"
    assert got["agent_execution_allow_plain_text_response"] is True
    assert got["agent_execution_require_tool_for_risky_intents"] is False
    assert got["agent_tool_first_fallback_after_misformats"] == 4
    assert got["agent_execution_risky_intent_regex"] == r"\b(run|execute)\b"
