import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


pytestmark = pytest.mark.tier1


def test_settings_store_exposes_scoped_persistence_api() -> None:
    store_path = PROJECT_ROOT / "webui" / "components" / "settings" / "settings-store.js"
    content = store_path.read_text(encoding="utf-8")
    assert "persistSettingToScope" in content
    assert 'API.callJsonApi("settings_scope_override_set"' in content
    assert "fineTuningApplyScope" in content
