"""委托任务的 JSONL 持久化适配器。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class JsonlTaskStore:
    """以追加方式保存任务状态和子代理追踪记录。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, record: dict[str, Any]) -> None:
        """线程安全地追加一条记录。"""

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """读取最近的有效记录。"""

        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines()[-max(1, limit):]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
