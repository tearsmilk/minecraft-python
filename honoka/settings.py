"""settings.json: the player's choices and what was installed."""

from __future__ import annotations

import json
from typing import Any

from . import paths


def load() -> dict[str, Any]:
    try:
        return json.loads(paths.settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(values: dict[str, Any]) -> None:
    path = paths.settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def update(**values: Any) -> dict[str, Any]:
    current = load()
    current.update(values)
    save(current)
    return current
