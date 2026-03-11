import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from python.helpers import errors


pytestmark = pytest.mark.tier1


def test_user_facing_error_message_maps_openrouter_credit_error() -> None:
    err = Exception("OpenrouterException - {\"error\":{\"message\":\"This request requires more credits\",\"code\":402}}")
    message = errors.user_facing_error_message(err)
    assert "credit/quota" in message.lower()


def test_user_facing_error_message_maps_token_limit_error() -> None:
    err = Exception("APIError: max_tokens exceeded maximum context length")
    message = errors.user_facing_error_message(err)
    assert "token/context limit" in message.lower()


def test_user_facing_error_message_maps_rate_limit_error() -> None:
    err = Exception("429 rate limit exceeded")
    message = errors.user_facing_error_message(err)
    assert "rate-limiting" in message.lower()
