"""核心服务单元测试"""

import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# 确保能找到项目模块
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRequestContext:
    """RequestContext 创建与资源隔离"""

    def test_create_basic(self):
        from services.context import RequestContext

        ctx = RequestContext.create(
            tenant_config={"id": "test", "erp": {"url": "http://test.com", "username": "u", "password": "p"}},
            run_id="test-run-001",
            global_config={"services": {"llm": {"default_model": "qwen-max"}}},
        )

        assert ctx.run_id == "test-run-001"
        assert ctx.tenant_id == "test"
        assert ctx.session_id == "test-test-run-001"
        assert ctx.erp_config["url"] == "http://test.com"

    def test_two_instances_have_different_session_ids(self):
        from services.context import RequestContext

        ctx_a = RequestContext.create(
            tenant_config={"id": "t1"},
            run_id="aaa",
            global_config={},
        )
        ctx_b = RequestContext.create(
            tenant_config={"id": "t2"},
            run_id="bbb",
            global_config={},
        )
        assert ctx_a.session_id != ctx_b.session_id
        assert "aaa" in ctx_a.session_id
        assert "bbb" in ctx_b.session_id

    def test_create_with_drawing_registry(self):
        from services.context import RequestContext

        mock_drawing = MagicMock()
        ctx = RequestContext.create(
            tenant_config={"id": "t"},
            run_id="test",
            global_config={},
            shared_drawing=mock_drawing,
        )
        assert ctx.drawing_registry is mock_drawing


class TestTenantContext:
    """租户配置工厂"""

    def test_build_basic(self):
        from services.tenant_context import build_tenant_config

        raw = {
            "id": "senlan_472",
            "display_name": "森蓝精密",
            "erp": {"url": "http://112.74.35.30/", "username": "472", "password": "123456"},
            "feishu": {"notify_on": ["workflow_start", "workflow_complete"]},
        }
        cfg = build_tenant_config(raw)
        assert cfg["id"] == "senlan_472"
        assert cfg["erp"]["username"] == "472"
        assert "workflow_start" in cfg["feishu"]["notify_on"]

    def test_build_defaults(self):
        from services.tenant_context import build_tenant_config

        cfg = build_tenant_config({"id": "minimal"})
        assert cfg["id"] == "minimal"
        assert cfg["enabled"] is True
        assert cfg["drawing_dir"] == "data/drawings/"

    def test_should_notify(self):
        from services.tenant_context import should_notify

        cfg = {"notify_on": ["workflow_start", "cnc_ready"]}
        assert should_notify(cfg, "workflow_start") is True
        assert should_notify(cfg, "phase1_complete") is False


class TestServiceRegistry:
    """服务注册表"""

    def test_register_and_get(self):
        from services import ServiceRegistry

        ServiceRegistry.reset()
        mock = MagicMock()
        ServiceRegistry.register("test_svc", mock)
        assert ServiceRegistry.get("test_svc") is mock

    def test_get_unregistered_raises(self):
        from services import ServiceRegistry

        ServiceRegistry.reset()
        with pytest.raises(KeyError):
            ServiceRegistry.get("nonexistent")

    def test_list(self):
        from services import ServiceRegistry

        ServiceRegistry.reset()
        ServiceRegistry.register("a", MagicMock())
        ServiceRegistry.register("b", MagicMock())
        svcs = ServiceRegistry.list()
        assert "a" in svcs
        assert "b" in svcs

    def test_init_config(self):
        from services import ServiceRegistry

        ServiceRegistry.reset()
        ServiceRegistry.init({"key": "val"})
        assert ServiceRegistry._config.get("key") == "val"


class TestBrowserService:
    """浏览器服务"""

    def test_init(self):
        from services.browser_service import BrowserService

        svc = BrowserService(chrome_data="/tmp/test_chrome", port=9999)
        assert svc is not None
        assert svc._base_port == 9999

    def test_close_noop(self):
        """不报错即通过"""
        from services.browser_service import BrowserService

        svc = BrowserService(chrome_data="/tmp/test_chrome", port=9999)
        svc.close()  # 没有页面，不报错


class TestLLMClient:
    """LLM 客户端"""

    def test_init_defaults(self):
        from services.llm_client import LLMClient

        client = LLMClient()
        assert client._default_model == "deepseek-v4-pro"
        assert client.vision_model == "qwen-vl-max"

    def test_init_custom_vision(self):
        from services.llm_client import LLMClient

        client = LLMClient(vision_model="qwen-vl-plus")
        assert client.vision_model == "qwen-vl-plus"


class TestNotificationService:
    """飞书通知服务"""

    def test_init_empty_config(self):
        from services.notification_service import FeishuNotifier

        notifier = FeishuNotifier({})
        assert notifier._app_id == ""
        assert notifier._app_secret == ""

    def test_init_with_config(self):
        from services.notification_service import FeishuNotifier

        notifier = FeishuNotifier({"app_id": "test", "app_secret": "secret"})
        assert notifier._app_id == "test"
        assert notifier._app_secret == "secret"


class TestStateService:
    """状态持久化"""

    def test_save_and_load(self, tmp_path):
        from services.state_service import StateService

        svc = StateService(state_dir=str(tmp_path))
        svc.save("test-thread", {"key": "value"})
        loaded = svc.load("test-thread")
        assert loaded is not None
        assert loaded["key"] == "value"

    def test_load_nonexistent(self, tmp_path):
        from services.state_service import StateService

        svc = StateService(state_dir=str(tmp_path))
        assert svc.load("nonexistent") is None

    def test_save_overwrites(self, tmp_path):
        from services.state_service import StateService

        svc = StateService(state_dir=str(tmp_path))
        svc.save("dup", {"v": 1})
        svc.save("dup", {"v": 2})
        loaded = svc.load("dup")
        assert loaded["v"] == 2


class TestDrawingRegistry:
    """图纸登记簿"""

    def test_register_and_find(self):
        # DrawingRegistry 需要 langchain，如果不能导入则跳过
        pytest.importorskip("langchain.schema")
        from services.drawing_registry import DrawingRegistry

        mock_kb = MagicMock()
        reg = DrawingRegistry(mock_kb)
        reg.register("PO-001", {"name": "test_part", "features": []})
        mock_kb.retrieve.return_value = []
        result = reg.find_similar({"name": "unknown_part"})
        assert result == []

    def test_find_nonexistent(self):
        pytest.importorskip("langchain.schema")
        from services.drawing_registry import DrawingRegistry

        mock_kb = MagicMock()
        mock_kb.retrieve.return_value = []
        reg = DrawingRegistry(mock_kb)
        result = reg.find_similar({"name": "does_not_exist"})
        assert result == []


class TestTenantConfig:
    """config.yaml 加载"""

    def test_load_config(self):
        from main import load_config

        cfg = load_config("config.yaml")
        assert "tenants" in cfg
        assert "agent" in cfg
        assert "services" in cfg

    def test_find_tenant(self):
        from main import load_config, find_tenant

        cfg = load_config("config.yaml")
        t = find_tenant(cfg, "senlan_472")
        assert t is not None
        assert t.get("id") == "senlan_472"

    def test_find_nonexistent_tenant(self):
        from main import load_config, find_tenant

        cfg = load_config("config.yaml")
        assert find_tenant(cfg, "nonexistent") is None
