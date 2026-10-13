from __future__ import annotations

import json
from typing import Any


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)


def from_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
