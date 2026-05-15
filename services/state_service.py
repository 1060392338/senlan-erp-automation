"""
StateService — 状态持久化

管理 LangGraph 检查点，支持工作流中断恢复。
每个工作流实例由 thread_id 唯一标识。
"""

import json
from pathlib import Path
from typing import Any, Optional


class StateService:
    def __init__(self, state_dir: str = "data/states"):
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def save(self, thread_id: str, state: dict):
        """保存检查点"""
        path = self._state_dir / f"{thread_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)

    def load(self, thread_id: str) -> Optional[dict]:
        """加载检查点"""
        path = self._state_dir / f"{thread_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def delete(self, thread_id: str):
        """删除检查点"""
        path = self._state_dir / f"{thread_id}.json"
        if path.exists():
            path.unlink()

    def list(self) -> list[str]:
        """列出所有检查点 ID"""
        return [p.stem for p in self._state_dir.glob("*.json")]
