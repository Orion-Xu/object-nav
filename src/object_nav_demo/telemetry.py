from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any

from .models import jsonable


class JsonlTelemetry:
    def __init__(self, path: str | Path | None):
        self.path = None if path is None else Path(path)
        self._lock = Lock()
        self.events: list[dict[str, Any]] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: str, task_id: str | None = None, **payload: Any) -> dict[str, Any]:
        row = {"timestamp": time.time(), "event": event, "task_id": task_id,
               **{key: jsonable(value) for key, value in payload.items()}}
        with self._lock:
            self.events.append(row)
            if self.path is not None:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row
