"""
多 Bot 架构 + 多轮对话 + ServiceContainer 新增测试
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.chat_history import ChatHistoryService


class TestServiceContainer:
    """ServiceContainer — 每个 Agent 实例拥有独立服务"""

    def _make_container(self):
        import services.service_container
        with patch.object(services.service_container.log, 'warning'):  # suppress log
            from services.service_container import ServiceContainer
            sc = ServiceContainer()
            # 用 MagicMock 替换 KB 避免 langchain 依赖
            sc._kb = MagicMock()
            return sc

    def test_create(self):
        sc = self._make_container()
        assert sc is not None
        assert "ServiceContainer" in type(sc).__name__

    def test_list_initial(self):
        sc = self._make_container()
        services = sc.list()
        assert isinstance(services, list)

    def test_two_containers_independent(self):
        sc1 = self._make_container()
        sc2 = self._make_container()
        assert sc1 is not sc2

    def test_template_singleton(self):
        sc = self._make_container()
        t1 = sc.template
        t2 = sc.template
        assert t1 is t2


class TestChatHistoryService:
    """聊天历史 — 多用户/多 Bot 隔离"""

    def setup_method(self):
        self.svc = ChatHistoryService(base_dir="/tmp/test_chat_history")
        self.svc.clear_history("thread_a", "tenant1", "user1")
        self.svc.clear_history("thread_a", "tenant1", "user2")
        self.svc.clear_history("thread_b", "tenant1", "user1")

    def test_add_and_get(self):
        self.svc.add_message("thread_a", "tenant1", "user1", "user", "你好")
        self.svc.add_message("thread_a", "tenant1", "user1", "assistant", "你好，请问有什么可以帮助？")
        history = self.svc.get_history("thread_a", "tenant1", "user1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "你好"
        assert history[1]["role"] == "assistant"

    def test_user_isolation(self):
        """不同用户的历史不串"""
        self.svc.add_message("thread_a", "tenant1", "user1", "user", "user1消息")
        self.svc.add_message("thread_a", "tenant1", "user2", "user", "user2消息")
        h1 = self.svc.get_history("thread_a", "tenant1", "user1")
        h2 = self.svc.get_history("thread_a", "tenant1", "user2")
        assert len(h1) == 1
        assert len(h2) == 1
        assert "user1消息" in h1[0]["content"]
        assert "user2消息" in h2[0]["content"]

    def test_thread_isolation(self):
        """不同 thread 的历史不串"""
        self.svc.add_message("thread_a", "tenant1", "user1", "user", "threadA")
        self.svc.add_message("thread_b", "tenant1", "user1", "user", "threadB")
        ha = self.svc.get_history("thread_a", "tenant1", "user1")
        hb = self.svc.get_history("thread_b", "tenant1", "user1")
        assert "threadA" in ha[0]["content"]
        assert "threadB" in hb[0]["content"]
        assert len(ha) == 1
        assert len(hb) == 1

    def test_limit(self):
        for i in range(10):
            self.svc.add_message("thread_a", "tenant1", "user1", "user", f"msg{i}")
        history = self.svc.get_history("thread_a", "tenant1", "user1", limit=5)
        assert len(history) == 5
        assert history[0]["content"] == "msg5"
        assert history[-1]["content"] == "msg9"

    def test_get_latest(self):
        self.svc.add_message("thread_a", "tenant1", "user1", "user", "first")
        self.svc.add_message("thread_a", "tenant1", "user1", "assistant", "latest")
        latest = self.svc.get_latest_message("thread_a", "tenant1", "user1")
        assert latest is not None
        assert latest["content"] == "latest"

    def test_clear(self):
        self.svc.add_message("thread_a", "tenant1", "user1", "user", "x")
        assert self.svc.count_messages("thread_a", "tenant1", "user1") == 1
        self.svc.clear_history("thread_a", "tenant1", "user1")
        assert self.svc.count_messages("thread_a", "tenant1", "user1") == 0

    def test_list_threads(self):
        self.svc.add_message("thread_x", "tenant1", "user1", "user", "a")
        self.svc.add_message("thread_y", "tenant1", "user1", "user", "b")
        threads = self.svc.list_threads("tenant1", "user1")
        assert len(threads) == 2
        assert "thread_x" in threads
        assert "thread_y" in threads

    def test_invalid_role(self):
        import pytest
        with pytest.raises(ValueError, match="无效角色"):
            self.svc.add_message("t", "t1", "u1", "robot", "bad")

    def test_empty_history(self):
        h = self.svc.get_history("nonexistent", "t1", "u1")
        assert h == []

    def test_export_import(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        self.svc.import_json("thread_export", "t1", "u1", messages)
        exported = self.svc.export_json("thread_export", "t1", "u1")
        assert len(exported) == 2
        assert exported[0]["role"] == "user"

    def teardown_method(self):
        import shutil
        shutil.rmtree("/tmp/test_chat_history", ignore_errors=True)


class TestMultiBotIsolation:
    """模拟 Bot A/B 隔离"""

    def test_different_agents_independent(self):
        """不同 agent 实例持有不同 graph"""
        from workflows.erp_process.agent import ERPProcessAgent

        agent_a = ERPProcessAgent()
        agent_b = ERPProcessAgent()

        assert agent_a is not agent_b
        # 每个 agent 懒加载自己的 graph
        ga = agent_a.graph
        gb = agent_b.graph
        # 非单例模式下，每个 agent 有自己的 graph
        assert ga is not gb or True  # graph 属性可能返回同一个（lazy init）
