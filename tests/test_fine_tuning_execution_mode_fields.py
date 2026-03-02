import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


pytestmark = pytest.mark.tier1


def test_fine_tuning_contains_execution_mode_controls() -> None:
    template_path = (
        PROJECT_ROOT
        / "webui"
        / "components"
        / "settings"
        / "agent"
        / "fine_tuning.html"
    )
    content = template_path.read_text(encoding="utf-8")
    assert "Execution Routing Modes (Opt-In)" in content
    assert "agent_execution_mode" in content
    assert "agent_execution_allow_plain_text_response" in content
    assert "agent_execution_require_tool_for_risky_intents" in content
    assert "agent_tool_first_fallback_after_misformats" in content
    assert "agent_execution_risky_intent_regex" in content
    assert "Fine-Tuning apply target" in content
    assert "fineTuningApplyScope" in content


def test_fine_tuning_contains_inline_env_persist_actions_for_execution_controls() -> None:
    template_path = (
        PROJECT_ROOT
        / "webui"
        / "components"
        / "settings"
        / "agent"
        / "fine_tuning.html"
    )
    content = template_path.read_text(encoding="utf-8")
    assert "persistSettingToScope('agent_execution_mode')" in content
    assert "persistSettingToScope('agent_execution_allow_plain_text_response')" in content
    assert "persistSettingToScope('agent_execution_require_tool_for_risky_intents')" in content
    assert "persistSettingToScope('agent_tool_first_fallback_after_misformats')" in content
    assert "persistSettingToScope('agent_execution_risky_intent_regex')" in content
