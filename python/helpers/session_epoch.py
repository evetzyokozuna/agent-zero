from __future__ import annotations

from typing import Any

from agent import AgentContext

_EPOCH_KEY = "session_epoch"


def get_epoch(context: AgentContext) -> int:
    value = context.get_data(_EPOCH_KEY)
    try:
        return int(value)
    except Exception:
        return 0


def bump_epoch(context: AgentContext, observed_stop_epoch: Any = None) -> int:
    current = get_epoch(context)
    next_epoch = current + 1
    if observed_stop_epoch is not None:
        try:
            observed = int(observed_stop_epoch)
            if observed > next_epoch:
                next_epoch = observed
        except Exception:
            pass
    context.set_data(_EPOCH_KEY, next_epoch)
    return next_epoch


def parse_epoch(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def stale_epoch_reason(context: AgentContext, provided_epoch: int | None) -> str | None:
    if provided_epoch is None:
        return None
    current = get_epoch(context)
    if provided_epoch < current:
        return (
            f"STALE_EPOCH_REJECTED: request epoch {provided_epoch} is behind current epoch {current}. "
            "Send from a fresh context/session."
        )
    return None
