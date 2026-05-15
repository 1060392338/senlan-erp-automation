"""
服务层 — 共享基础设施

多 Bot 架构：
- ServiceContainer — 每个 Agent 实例拥有独立服务（KB/Template/Drawing）
- ServiceRegistry — 保留向后兼容（新代码优先用 ServiceContainer）
- ChatHistoryService — 会话历史管理

每个 Bot 实例 = 一个 ServiceContainer + 一个 ERPProcessAgent
Bot A 和 Bot B 的服务完全隔离，互不干扰。
"""

import threading
from typing import Any


class ServiceRegistry:
    """全局服务注册器（兼容旧代码，新代码用 ServiceContainer）"""
    _services: dict[str, Any] = {}
    _config: dict = {}
    _lock: threading.RLock = threading.RLock()

    @classmethod
    def init(cls, config: dict):
        with cls._lock:
            cls._config = config

    @classmethod
    def register(cls, name: str, service: Any) -> None:
        with cls._lock:
            cls._services[name] = service

    @classmethod
    def get(cls, name: str) -> Any:
        with cls._lock:
            if name not in cls._services:
                raise KeyError(f"服务 '{name}' 未注册")
            return cls._services[name]

    @classmethod
    def get_config(cls) -> dict:
        with cls._lock:
            return dict(cls._config)

    @classmethod
    def list(cls) -> list[str]:
        with cls._lock:
            return list(cls._services.keys())

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._services.clear()
            cls._config.clear()
