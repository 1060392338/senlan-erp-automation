"""工作流节点单元测试（V3 — 多Agent编排版）

只测试 ERP 交互节点（login/detect/drawing_fetch/erp_reconnect/filler）。
AI 推理层由 test_graph.py 中的 Agent 测试覆盖。
"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from langchain_core.runnables import RunnableConfig

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _mock_config(mock_ctx=None, thread_id="test-thread") -> RunnableConfig:
    if mock_ctx is None:
        mock_ctx = _mock_context()
    return RunnableConfig(configurable={"thread_id": thread_id, "ctx": mock_ctx})


def _mock_context():
    from services.context import RequestContext
    ctx = RequestContext(
        run_id="test-run",
        tenant_id="test",
        user_id="test",
        tenant_config={
            "id": "test",
            "erp": {"url": "http://test.com/", "username": "u", "password": "***"},
            "feishu": {"notify_on": ["workflow_complete"]},
        },
        global_config={"services": {"llm": {"default_model": "qwen-max"}}},
    )
    ctx.browser = MagicMock()
    ctx.llm = MagicMock()
    ctx.notifier = MagicMock()
    ctx.get_service = MagicMock(return_value=MagicMock())
    return ctx


def _make_state(**overrides) -> dict:
    base = {
        "input": {"customer": "Test", "part_name": "Cutting Blade", "qty": 2},
        "tenant_config": {"id": "test", "erp": {"url": "http://test.com/", "username": "u", "password": "***"}},
        "errors": [],
        "checkpoint": 0,
        "session_id": "test-run",
        "plan_saved": False,
        "routing_saved": False,
        "cnc_saved": False,
        "prod_no": None,
        "new_orders": None,
        "pending_order_idx": 0,
        "drawing_url": None,
        "drawing_local_path": None,
        "drawing_matched": False,
        "part_info": None,
        "features": None,
        "process_plan": None,
        "cnc_code": None,
    }
    base.update(overrides)
    return base


class TestLoginNode:
    def test_login(self):
        from workflows.erp_process.nodes.login import node_login
        state = _make_state()
        config = _mock_config()
        result = node_login(state, config)
        assert "session_id" in result
        assert result["checkpoint"] == 5


class TestDetectNewOrdersNode:
    def test_detect(self):
        from workflows.erp_process.nodes.detect_new_orders import node_detect_new_orders
        state = _make_state()
        config = _mock_config()
        result = node_detect_new_orders(state, config)
        assert "new_orders" in result
        assert result["checkpoint"] == 7

    def test_no_browser(self):
        from workflows.erp_process.nodes.detect_new_orders import node_detect_new_orders
        state = _make_state()
        config = _mock_config()
        config["configurable"]["ctx"].browser.get_page.side_effect = Exception("no browser")
        result = node_detect_new_orders(state, config)
        assert result["new_orders"] == []
        assert len(result.get("errors", [])) > 0


class TestDrawingFetchNode:
    def test_fetch_no_orders(self):
        from workflows.erp_process.nodes.drawing_fetch import node_fetch_drawing
        state = _make_state(new_orders=[], pending_order_idx=0)
        config = _mock_config()
        result = node_fetch_drawing(state, config)
        assert result["checkpoint"] == 10

    def test_fetch_with_orders_no_token(self):
        from workflows.erp_process.nodes.drawing_fetch import node_fetch_drawing
        state = _make_state(
            new_orders=[{"prod_no": "PO-TEST-001", "send_time": "2026-05-15"}],
            pending_order_idx=0,
        )
        config = _mock_config()
        config["configurable"]["ctx"].tenant_config = {"id": "test"}
        config["configurable"]["ctx"].global_config = {}
        result = node_fetch_drawing(state, config)
        assert result["prod_no"] == "PO-TEST-001"
        assert result["drawing_matched"] is False


class TestErpReconnectNode:
    def test_reconnect(self):
        from workflows.erp_process.nodes.erp_reconnect import node_erp_reconnect
        state = _make_state(prod_no="PO-TEST-001")
        config = _mock_config()
        result = node_erp_reconnect(state, config)
        assert result["checkpoint"] == 22


class TestProcessFillerNode:
    def test_fill(self):
        from workflows.erp_process.nodes.process_filler import node_fill_plan
        with (
            patch("workflows.erp_process.nodes.process_filler._navigate_to_page", return_value=True),
            patch("workflows.erp_process.nodes.process_filler._search_order", return_value=True),
            patch("workflows.erp_process.nodes.process_filler._select_and_open_dialog", return_value=True),
            patch("workflows.erp_process.nodes.process_filler._fill_vxe_table_cells", return_value=True),
            patch("workflows.erp_process.nodes.process_filler._save_dialog", return_value=True),
        ):
            state = _make_state(
                prod_no="PO-TEST-001",
                process_plan=[{"seq": 1, "name": "铣床", "task": "开粗"}],
            )
            config = _mock_config()
            result = node_fill_plan(state, config)
        assert result["plan_saved"] is True

    def test_fill_without_prod_no(self):
        from workflows.erp_process.nodes.process_filler import node_fill_plan
        state = _make_state(
            process_plan=[{"seq": 1, "name": "铣床", "task": "开粗"}],
        )
        config = _mock_config()
        result = node_fill_plan(state, config)
        assert result["plan_saved"] is False


class TestRoutingFillerNode:
    def test_fill(self):
        from workflows.erp_process.nodes.routing_filler import node_fill_routing
        state = _make_state(
            prod_no="PO-TEST-001",
            cnc_code={
                "takisawa_nex108": "G90 G21",
                "sodick_ad32ls": {"machine": "SODICK", "steps": []},
                "notes": [],
                "segments": [],
                "feature_code_map": {},
            },
        )
        config = _mock_config()
        result = node_fill_routing(state, config)
        # DEPRECATED: 不再写入ERP，返回 False
        assert result["routing_saved"] is False
        assert result["cnc_saved"] is False

    def test_fill_without_cnc(self):
        from workflows.erp_process.nodes.routing_filler import node_fill_routing
        state = _make_state(prod_no="PO-TEST-002")
        config = _mock_config()
        result = node_fill_routing(state, config)
        assert result["routing_saved"] is False
        assert result["cnc_saved"] is False
