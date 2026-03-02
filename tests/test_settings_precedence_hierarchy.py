import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
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


def test_effective_settings_merges_general_to_specialized_before_env_lock(monkeypatch) -> None:
    # Neutralize env lock for this precedence test.
    monkeypatch.setattr(settings, "_apply_env_overrides", lambda s: s)
    monkeypatch.setattr(
        settings, "_read_settings_file", lambda: settings.normalize_settings(settings.get_default_settings())
    )

    # Fake projects module to avoid importing full runtime graph.
    fake_projects = ModuleType("python.helpers.projects")
    fake_projects.get_context_project_name = lambda _ctx: "projA"
    fake_projects.get_project_meta_folder = (
        lambda project_name, *parts: f"/tmp/{project_name}/.a0proj/" + "/".join(parts)
    )
    monkeypatch.setitem(sys.modules, "python.helpers.projects", fake_projects)

    def fake_read(path: str):
        p = path.replace("\\", "/")
        if p.endswith("/agents/agent0/settings.json") and "/usr/" not in p and "/.a0proj/" not in p:
            return {"agent_execution_mode": "tool_first"}
        if p.endswith("/usr/agents/agent0/settings.json"):
            return {"agent_execution_mode": "hybrid"}
        if p.endswith("/.a0proj/settings.json"):
            return {"agent_execution_mode": "model_first"}
        if p.endswith("/.a0proj/agents/agent0/settings.json"):
            return {"agent_execution_mode": "tool_first_fallback"}
        return {}

    monkeypatch.setattr(settings, "_read_settings_json_file", fake_read)

    agent = SimpleNamespace(
        config=SimpleNamespace(profile="agent0"),
        context=SimpleNamespace(),
    )
    effective = settings.get_effective_settings(agent)
    assert effective["agent_execution_mode"] == "tool_first_fallback"
