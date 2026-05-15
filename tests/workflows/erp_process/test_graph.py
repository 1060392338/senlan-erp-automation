"""LangGraph 编译与运行测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestGraphCompilation:
    """图编译"""

    def test_build_graph(self):
        from workflows.erp_process.graph import build_erp_graph

        g = build_erp_graph()
        assert g is not None
        nodes = list(g.nodes.keys())
        assert len(nodes) >= 11  # 10 个业务节点 + __start__
        assert "login_erp" in nodes
        assert "create_order" in nodes
        assert "fetch_drawing" in nodes
        assert "template_match" in nodes
        assert "process_reasoning" in nodes
        assert "generate_cnc" in nodes
        assert "erp_reconnect" in nodes
        assert "fill_process_plan" in nodes
        assert "fill_routing_cnc" in nodes

    def test_no_singleton(self):
        """build_erp_graph 每次调用创建新实例（多 Bot 架构要求）"""
        from workflows.erp_process.graph import build_erp_graph

        g1 = build_erp_graph()
        g2 = build_erp_graph()
        assert g1 is not g2

    def test_interrupt_points(self):
        from workflows.erp_process.graph import build_erp_graph

        g = build_erp_graph()
        # 检查中断点
        if hasattr(g, "interrupt_after_nodes"):
            interrupts = g.interrupt_after_nodes
            assert "fetch_drawing" in interrupts
            assert "generate_cnc" in interrupts

    def test_state_schema(self):
        """状态定义包含所有关键字段"""
        from workflows.erp_process.state import ERPState

        # TypedDict 检查
        keys = ERPState.__annotations__.keys()
        required = ["input", "tenant_config", "prod_no", "process_plan", "cnc_code"]
        for k in required:
            assert k in keys, f"缺少状态字段: {k}"


class TestAgent:
    """Agent 集成"""

    def test_agent_import(self):
        from workflows.erp_process.agent import ERPProcessAgent

        agent = ERPProcessAgent()
        assert agent.agent_name == "erp_process_agent"
        assert "part_name" in agent.input_schema()["required"]

    def test_supervisor_discovers_agent(self):
        from agents.supervisor import SupervisorAgent

        sup = SupervisorAgent()
        assert "erp_process_agent" in sup.agents
        assert sup.agents["erp_process_agent"].agent_name == "erp_process_agent"


class TestGraphInvocation:
    """图调用（mock 上下文）"""

    def test_graph_invoke_with_mock_config(self):
        """模拟一次完整的图调用（需要 checkpointer，所以使用 None）"""
        from workflows.erp_process.graph import build_erp_graph

        g = build_erp_graph()
        # 使用 MemorySaver 避免 checkpoints.db 依赖
        from langgraph.checkpoint.memory import MemorySaver

        ms = MemorySaver()
        # 重新编译图（覆盖全局单例）
        from langgraph.graph import StateGraph, START, END
        from workflows.erp_process.state import ERPState
        from workflows.erp_process.nodes import (
            node_login, node_create_order, node_fetch_drawing,
            node_template_match, node_process_reasoning,
            node_generate_cnc, node_erp_reconnect,
            node_fill_plan, node_fill_routing,
        )

        builder = StateGraph(ERPState)
        builder.add_node("login_erp", node_login)
        builder.add_node("create_order", node_create_order)
        builder.add_node("fetch_drawing", node_fetch_drawing)
        builder.add_node("template_match", node_template_match)
        builder.add_node("process_reasoning", node_process_reasoning)
        builder.add_node("generate_cnc", node_generate_cnc)
        builder.add_node("erp_reconnect", node_erp_reconnect)
        builder.add_node("fill_process_plan", node_fill_plan)
        builder.add_node("fill_routing_cnc", node_fill_routing)

        builder.add_edge(START, "login_erp")
        builder.add_edge("login_erp", "create_order")
        builder.add_edge("create_order", "fetch_drawing")
        builder.add_edge("fetch_drawing", "template_match")
        builder.add_edge("template_match", "process_reasoning")
        builder.add_edge("process_reasoning", "generate_cnc")
        builder.add_edge("generate_cnc", "erp_reconnect")
        builder.add_edge("erp_reconnect", "fill_process_plan")
        builder.add_edge("fill_process_plan", "fill_routing_cnc")
        builder.add_edge("fill_routing_cnc", END)

        test_graph = builder.compile(checkpointer=ms)

        state = {
            "input": {"customer": "Test", "part_name": "Blade", "qty": 2},
            "tenant_config": {"id": "t", "erp": {"url": "http://t.com/", "username": "u", "password": "p"}},
            "errors": [],
            "checkpoint": 0,
            "session_id": "test",
            "plan_saved": False,
            "routing_saved": False,
            "cnc_saved": False,
            "prod_no": None,
            "drawing_url": None,
            "part_info": {"name": "Blade", "material": "K490", "hardness": "58-63", "shape": "square"},
            "features": [{"type": "外形", "spec": "190x77mm"}],
            "matched_template": None,
            "process_plan": None,
            "cnc_code": None,
        }

        from services.context import RequestContext
        from unittest.mock import MagicMock

        ctx = RequestContext(
            run_id="test-run",
            tenant_id="t",
            user_id="test",
            tenant_config=state["tenant_config"],
            global_config={},
        )
        ctx.browser = MagicMock()
        ctx.llm = MagicMock()
        ctx.get_service = MagicMock(return_value=MagicMock())
        # 确保 get_service('drawing').find_similar() 返回 None，触发 Vision 路径
        mock_drawing = MagicMock()
        mock_drawing.find_similar.return_value = None
        # 确保 template_service 返回真实字符串，否则 msgpack 序列化会炸
        mock_template = MagicMock()
        mock_template.generate_cnc.return_value = "G90 G21 ; test CNC code"
        mock_template.generate_edm_params.return_value = {"machine": "SODICK", "steps": []}
        def _get_service(name):
            if name == "drawing":
                return mock_drawing
            if name == "template":
                return mock_template
            return MagicMock()
        ctx.get_service.side_effect = _get_service

        config = {"configurable": {"thread_id": "test-graph", "ctx": ctx}}

        # 执行图
        result = test_graph.invoke(state, config)

        assert result is not None
        assert result["prod_no"] is not None
        assert result["plan_saved"] is True
        assert result["routing_saved"] is True
        assert result["cnc_saved"] is True
