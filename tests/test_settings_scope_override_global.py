import sys
from pathlib import Path
import types

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Lightweight stubs for optional heavy deps used during module imports.
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

from python.helpers import settings


pytestmark = pytest.mark.tier1


def test_save_scope_override_global_does_not_call_set_settings(monkeypatch) -> None:
    defaults = settings.get_default_settings()
    target_key = "agent_transient_error_max_retries"
    written: dict[str, object] = {}
    applied = {"called": False}

    def _fail_set_settings(*_args, **_kwargs):
        raise AssertionError("set_settings should not be called for global scoped key override")

    monkeypatch.setattr(settings, "set_settings", _fail_set_settings)
    monkeypatch.setattr(settings, "_read_settings_json_file", lambda _path: {})
    monkeypatch.setattr(
        settings,
        "_write_settings_json_file",
        lambda _path, data: written.setdefault("data", data.copy()),
    )
    monkeypatch.setattr(
        settings, "reload_settings", lambda: {**defaults, target_key: 5}
    )
    monkeypatch.setattr(
        settings,
        "_apply_settings",
        lambda _previous: applied.__setitem__("called", True),
    )

    settings._settings = defaults.copy()
    result = settings.save_scope_override(target_key, 5, "global")

    assert written["data"][target_key] == 5
    assert applied["called"] is True
    assert result[target_key] == 5
