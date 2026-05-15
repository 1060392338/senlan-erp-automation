"""工作流节点单元测试"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from langchain_core.runnables import RunnableConfig

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ── Helper: 构建模拟的 config 和 RequestContext ──


def _mock_config(mock_ctx=None, thread_id="test-thread") -> RunnableConfig:
    """创建模拟的 LangGraph 运行配置"""
    if mock_ctx is None:
        mock_ctx = _mock_context()
    return RunnableConfig(configurable={"thread_id": thread_id, "ctx": mock_ctx})


def _mock_context():
    """创建模拟的 RequestContext"""
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
        "tenant_config": {"id": "test", "erp": {"url": "http://test.com/", "username": "u", "password": "p"}},
        "errors": [],
        "checkpoint": 0,
        "session_id": "test-run",
        "plan_saved": False,
        "routing_saved": False,
        "cnc_saved": False,
        "prod_no": None,
        "drawing_url": None,
        "part_info": None,
        "features": None,
        "matched_template": None,
        "process_plan": None,
        "cnc_code": None,
    }
    base.update(overrides)
    return base


# ── 测试各节点 ──


class TestLoginNode:
    """ERP 登录节点"""

    def test_login(self):
        from workflows.erp_process.nodes.login import node_login

        state = _make_state()
        config = _mock_config()
        result = node_login(state, config)
        assert "session_id" in result
        assert "test" in result["session_id"]
        assert result["checkpoint"] == 5


class TestSalesOrderNode:
    """销售订单节点"""

    def test_create_order(self):
        from workflows.erp_process.nodes.sales_order import node_create_order

        state = _make_state()
        config = _mock_config()
        result = node_create_order(state, config)
        assert isinstance(result["prod_no"], str), f"prod_no should be str, got {type(result['prod_no'])}"
        assert "PO-" in result["prod_no"]

    def test_prod_no_uses_part_name(self):
        from workflows.erp_process.nodes.sales_order import node_create_order

        state = _make_state()
        state["input"] = {"customer": "X", "part_name": "Die", "qty": 5}
        config = _mock_config()
        result = node_create_order(state, config)
        assert isinstance(result["prod_no"], str)
        assert "Die" in result["prod_no"]


class TestDrawingFetchNode:
    """图纸获取节点"""

    def test_fetch_drawing(self):
        from workflows.erp_process.nodes.drawing_fetch import node_fetch_drawing

        state = _make_state(prod_no="PO-TEST-001")
        state["input"]["drawing_path"] = "/tmp/test_drawing.pdf"
        config = _mock_config()
        result = node_fetch_drawing(state, config)
        assert "/tmp/test_drawing.pdf" in result.get("drawing_url", "")

    def test_fetch_without_path(self):
        from workflows.erp_process.nodes.drawing_fetch import node_fetch_drawing

        state = _make_state(prod_no="PO-TEST-002")
        config = _mock_config()
        result = node_fetch_drawing(state, config)
        # 无图纸路径不应报错
        assert result["checkpoint"] == 10


class TestTemplateMatchNode:
    """模板匹配节点"""

    def test_match(self):
        from workflows.erp_process.nodes.template_match import node_template_match

        state = _make_state()
        config = _mock_config()
        config["configurable"]["ctx"].get_service.return_value.find_similar.return_value = None
        result = node_template_match(state, config)
        assert result["checkpoint"] == 15


class TestVisionAnalyzeNode:
    """视觉分析节点"""

    def test_analyze(self):
        from workflows.erp_process.nodes.vision_analyze import node_vision_analyze

        state = _make_state(
            prod_no="PO-TEST-001",
            drawing_url="/tmp/test.pdf",
        )
        config = _mock_config()
        result = node_vision_analyze(state, config)
        assert result["part_info"] is not None
        assert result["features"] is not None
        # 即使没有真实 Vision API，也应该有默认特征
        assert len(result["features"]) > 0


class TestProcessReasoningNode:
    """工艺推理节点"""

    def test_square_route_14_steps(self):
        from workflows.erp_process.nodes.process_reasoning import node_process_reasoning

        state = _make_state(
            part_info={"name": "Cutting Blade", "material": "K490", "shape": "square"},
            features=[{"type": "外形", "spec": "190x77mm"}],
        )
        config = _mock_config()
        result = node_process_reasoning(state, config)
        plan = result["process_plan"]
        assert len(plan) >= 14  # 方形→14道工序 + 可能的特殊标注
        first = plan[0]
        assert first["name"] in ("铣床", "CNC 1")  # 第一道是铣或CNC开粗

    def test_round_route(self):
        from workflows.erp_process.nodes.process_reasoning import node_process_reasoning

        state = _make_state(
            part_info={"name": "Shaft", "material": "SKD11", "shape": "round"},
            features=[{"type": "外形", "spec": "∅50x200mm"}],
        )
        config = _mock_config()
        result = node_process_reasoning(state, config)
        plan = result["process_plan"]
        assert len(plan) >= 7  # 圆形→7道工序
        names = [s["name"] for s in plan]
        assert "车床" in names

    def test_sharp_edge_added(self):
        """利角特征应在工序末尾加入特殊提示"""
        from workflows.erp_process.nodes.process_reasoning import node_process_reasoning

        state = _make_state(
            part_info={"name": "Cutting Blade", "material": "K490", "shape": "square"},
            features=[{"type": "利角", "note": "严禁倒角"}],
            template_id=None,
        )
        config = _mock_config()
        result = node_process_reasoning(state, config)
        plan = result["process_plan"]
        notes = [s for s in plan if s.get("meta_step")]
        assert len(notes) >= 1
        assert "利角" in str(notes) or "Sharp" in str(notes) or "刃口" in str(notes)


class TestGenerateCncNode:
    """CNC 代码生成节点"""

    def test_generate(self):
        from workflows.erp_process.nodes.generate_cnc import node_generate_cnc

        state = _make_state(
            prod_no="PO-TEST-001",
            part_info={"name": "Cutting Blade", "material": "K490", "hardness": "58-63"},
            features=[{"type": "外形", "spec": "190x77mm"}],
            process_plan=[{"seq": 8, "name": "CNC 2"}, {"seq": 11, "name": "EDM"}],
        )
        config = _mock_config()
        result = node_generate_cnc(state, config)
        cnc = result["cnc_code"]
        assert cnc is not None
        assert "takisawa_nex108" in cnc
        assert "sodick_ad32ls" in cnc


class TestErpReconnectNode:
    """ERP 重连节点"""

    def test_reconnect(self):
        from workflows.erp_process.nodes.erp_reconnect import node_erp_reconnect

        state = _make_state(prod_no="PO-TEST-001")
        config = _mock_config()
        result = node_erp_reconnect(state, config)
        assert result["checkpoint"] == 22


class TestProcessFillerNode:
    """计划工艺回填节点"""

    def test_fill(self):
        from workflows.erp_process.nodes.process_filler import node_fill_plan

        state = _make_state(
            prod_no="PO-TEST-001",
            process_plan=[{"seq": 1, "name": "铣床", "task": "开粗"}],
        )
        config = _mock_config()
        result = node_fill_plan(state, config)
        assert result["plan_saved"] is True

    def test_fill_without_prod_no(self):
        from workflows.erp_process.nodes.process_filler import node_fill_plan

        state = _make_state()
        config = _mock_config()
        result = node_fill_plan(state, config)
        assert result["plan_saved"] is False


class TestRoutingFillerNode:
    """计划工序回填节点"""

    def test_fill(self):
        from workflows.erp_process.nodes.routing_filler import node_fill_routing

        state = _make_state(
            prod_no="PO-TEST-001",
            cnc_code={
                "takisawa_nex108": "G90 G21",
                "sodick_ad32ls": {"machine": "SODICK", "steps": []},
                "notes": [],
            },
        )
        config = _mock_config()
        result = node_fill_routing(state, config)
        assert result["routing_saved"] is True
        assert result["cnc_saved"] is True

    def test_fill_without_cnc(self):
        from workflows.erp_process.nodes.routing_filler import node_fill_routing

        state = _make_state(prod_no="PO-TEST-002")
        config = _mock_config()
        result = node_fill_routing(state, config)
        assert result["routing_saved"] is False
        assert result["cnc_saved"] is False
