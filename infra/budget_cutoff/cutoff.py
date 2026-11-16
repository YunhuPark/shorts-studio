"""Decides whether a Cloud Billing budget notification means "stop serving the public demo".

Pure logic, no Google libraries, so it is unit-tested (tests/test_budget_cutoff.py).
main.py wires it to Pub/Sub and Cloud Run. A budget notification looks like
{"costAmount": 7123.0, "budgetAmount": 7000.0, "alertThresholdExceeded": 1.0, ...}.
"""
from __future__ import annotations

import base64
import json
from collections.abc import Callable


def decode_message(event_data: dict) -> dict:
    """The Pub/Sub payload of a CloudEvent: {"message": {"data": <base64 of a JSON object>}}."""
    raw = base64.b64decode(event_data["message"]["data"])
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("budget notification is not a JSON object")
    return payload


def should_cut(payload: dict) -> bool:
    """True when the spend so far has reached the budget. Anything unreadable never cuts (it only logs)."""
    try:
        cost = float(payload["costAmount"])
        budget = float(payload["budgetAmount"])
    except (KeyError, TypeError, ValueError):
        return False
    return budget > 0 and cost >= budget


def handle(event_data: dict, close_service: Callable[[], None], log: Callable[[str], None] = print) -> bool:
    """Returns True when the service was closed."""
    payload = decode_message(event_data)
    cost, budget = payload.get("costAmount"), payload.get("budgetAmount")
    if not should_cut(payload):
        log(f"budget ok: cost={cost} budget={budget}")
        return False
    log(f"budget reached: cost={cost} budget={budget}; closing the service to the public")
    close_service()
    return True
