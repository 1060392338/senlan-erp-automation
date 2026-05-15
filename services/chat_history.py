"""
ChatHistoryService — 轻量会话历史管理器

以 JSONL 格式存储用户会话历史，支持多租户/多用户隔离。
存储路径: data/chat_history/{tenant_id}/{user_id}/{thread_id}.jsonl

线程安全设计：
- 写操作：threading.Lock + 文件追加写（append），无锁竞争风险
- 读操作：加载整个文件到内存解析，适合合理长度的会话
- 纯 Python 标准库，零外部依赖
"""

import json
import threading
import time
from pathlib import Path
from typing import Optional


class ChatHistoryService:
    """会话历史管理器"""

    DEFAULT_BASE = "data/chat_history"

    def __init__(self, base_dir: str = DEFAULT_BASE):
        self._base_dir = Path(base_dir)
        self._lock = threading.Lock()

    # ── 路径工具 ──────────────────────────────────────────────

    def _thread_path(self, tenant_id: str, user_id: str, thread_id: str) -> Path:
        """获取 thread 对应的 JSONL 文件路径"""
        return self._base_dir / tenant_id / user_id / f"{thread_id}.jsonl"

    def _ensure_dir(self, tenant_id: str, user_id: str) -> Path:
        """确保租户/用户目录存在，返回用户目录"""
        user_dir = self._base_dir / tenant_id / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    # ── 写操作 ────────────────────────────────────────────────

    def add_message(self, thread_id: str, tenant_id: str, user_id: str,
                    role: str, content: str) -> dict:
        """添加一条消息到会话历史（线程安全）

        Args:
            thread_id: 会话 ID
            tenant_id: 租户 ID
            user_id: 用户 ID
            role: 角色 — "user" | "assistant" | "system"
            content: 消息内容

        Returns:
            写入的记录字典（包含自动生成的 timestamp 和 turn）
        """
        if role not in ("user", "assistant", "system"):
            raise ValueError(f"无效角色: {role}（有效值: user, assistant, system）")

        with self._lock:
            filepath = self._thread_path(tenant_id, user_id, thread_id)
            self._ensure_dir(tenant_id, user_id)

            # 计算 turn：读取已有行数作为下一轮序号
            turn = 0
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    for _ in f:
                        turn += 1

            record = {
                "role": role,
                "content": content,
                "timestamp": time.time(),
                "turn": turn,
            }

            # 追加写入（原子操作在单次 write 层面由 GIL 保护）
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()

            return record

    # ── 读操作 ────────────────────────────────────────────────

    def get_history(self, thread_id: str, tenant_id: str, user_id: str,
                    limit: int = 50) -> list[dict]:
        """获取会话历史（按 turn 升序排列）

        Args:
            thread_id: 会话 ID
            tenant_id: 租户 ID
            user_id: 用户 ID
            limit: 最多返回条数（默认 50，最新 N 条）

        Returns:
            消息记录列表，按 turn 升序
        """
        filepath = self._thread_path(tenant_id, user_id, thread_id)
        if not filepath.exists():
            return []

        records: list[dict] = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        # 按 turn 排序后取最新的 limit 条
        records.sort(key=lambda r: r.get("turn", 0))
        if limit > 0 and len(records) > limit:
            records = records[-limit:]

        return records

    def get_latest_message(self, thread_id: str, tenant_id: str,
                          user_id: str) -> Optional[dict]:
        """获取会话中最新的一条消息

        Returns:
            记录字典，若无消息则返回 None
        """
        records = self.get_history(thread_id, tenant_id, user_id, limit=1)
        return records[-1] if records else None

    # ── 删除操作 ──────────────────────────────────────────────

    def clear_history(self, thread_id: str, tenant_id: str,
                     user_id: str) -> bool:
        """清空指定会话的历史记录

        Returns:
            True 如果文件存在并删除，False 如果文件不存在
        """
        filepath = self._thread_path(tenant_id, user_id, thread_id)
        with self._lock:
            if filepath.exists():
                filepath.unlink()
                return True
            return False

    # ── 列举操作 ──────────────────────────────────────────────

    def list_threads(self, tenant_id: str, user_id: str) -> list[str]:
        """列出指定租户/用户下的所有会话 ID

        Returns:
            会话 ID 列表（按最后修改时间降序排列）
        """
        user_dir = self._base_dir / tenant_id / user_id
        if not user_dir.exists():
            return []

        threads = []
        for fpath in sorted(user_dir.glob("*.jsonl"),
                            key=lambda p: p.stat().st_mtime, reverse=True):
            threads.append(fpath.stem)  # 去掉 .jsonl 后缀
        return threads

    # ── 统计 & 工具 ────────────────────────────────────────────

    def count_messages(self, thread_id: str, tenant_id: str,
                      user_id: str) -> int:
        """统计会话中的消息总数"""
        filepath = self._thread_path(tenant_id, user_id, thread_id)
        if not filepath.exists():
            return 0
        count = 0
        with open(filepath, "r", encoding="utf-8") as f:
            for _ in f:
                count += 1
        return count

    def export_json(self, thread_id: str, tenant_id: str,
                   user_id: str) -> list[dict]:
        """导出完整会话为 JSON 列表（与 get_history 相同，无 limit）"""
        return self.get_history(thread_id, tenant_id, user_id, limit=0)

    def import_json(self, thread_id: str, tenant_id: str, user_id: str,
                   messages: list[dict]) -> int:
        """从 JSON 列表导入消息（覆盖写入）

        Args:
            messages: 消息记录列表，每条须含 role、content，可选 timestamp/turn

        Returns:
            写入的消息条数
        """
        with self._lock:
            filepath = self._thread_path(tenant_id, user_id, thread_id)
            self._ensure_dir(tenant_id, user_id)

            with open(filepath, "w", encoding="utf-8") as f:
                for i, msg in enumerate(messages):
                    record = {
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", ""),
                        "timestamp": msg.get("timestamp", time.time()),
                        "turn": msg.get("turn", i),
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            return len(messages)
