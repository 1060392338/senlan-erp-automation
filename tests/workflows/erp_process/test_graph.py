"""LangGraph 编译与运行测试（V3 — 多Agent编排版）"""

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
        assert "login_erp" in nodes
        assert "detect_new_orders" in nodes
        assert "fetch_feishu_drawing" in nodes
        assert "supervisor_agent_run" in nodes  # V3 新增
        assert "erp_reconnect" in nodes
        assert "fill_process_plan" in nodes

    def test_no_singleton(self):
        from workflows.erp_process.graph import build_erp_graph

        g1 = build_erp_graph()
        g2 = build_erp_graph()
        assert g1 is not g2

    def test_interrupt_points(self):
        """V3+ 编译无中断点（LangGraph编译配置中的 interrupt_after 已移除）"""
        from workflows.erp_process.graph import build_erp_graph

        g = build_erp_graph()
        if hasattr(g, "interrupt_after_nodes"):
            # 当前编译无中断点，首次中断在外部由飞书流程控制
            assert len(g.interrupt_after_nodes) == 0

    def test_state_schema(self):
        from workflows.erp_process.state import ERPState

        keys = ERPState.__annotations__.keys()
        required = ["input", "tenant_config", "prod_no", "new_orders", "process_plan", "cnc_code"]
        for k in required:
            assert k in keys, f"缺少状态字段: {k}"

    def test_v3_no_old_nodes(self):
        """V3: V1/V2 旧节点不应存在"""
        from workflows.erp_process.graph import build_erp_graph

        g = build_erp_graph()
        nodes = list(g.nodes.keys())
        for old in ["create_order", "template_match", "vision_analyze",
                     "process_reasoning", "generate_cnc"]:
            assert old not in nodes, f"旧节点 {old} 仍存在于图中"


class TestAgent:
    """Agent 集成"""

    def test_supervisor_import(self):
        from workflows.erp_process.agents.supervisor import SupervisorAgent

        agent = SupervisorAgent()
        result = agent.run({
            "prod_no": "PO-TEST-001",
            "input": {},
        })
        assert "part_info" in result
        assert "features" in result
        assert "process_plan" in result
        assert "cnc_code" in result
        assert result["checkpoint"] == 20

    def test_vision_agent_import(self):
        from workflows.erp_process.agents.vision_agent import VisionAgent

        agent = VisionAgent()
        result = agent.analyze(drawing_path="", prod_no="PO-TEST-001")
        assert "part_info" in result
        assert "features" in result
        assert result["confidence"] == 0.0  # 降级

    def test_cnc_agent_import(self):
        from workflows.erp_process.agents.cnc_agent import CNCProgrammingAgent

        agent = CNCProgrammingAgent()
        result = agent.generate(
            part_info={"name": "Test", "material": "K490", "hardness": "58-63"},
            features=[{"type": "外形", "spec": "100x50mm"}],
            process_plan=[],
        )
        assert "code_segments" in result
        assert "self_review" in result

    def test_review_agent_import(self):
        from workflows.erp_process.agents.review_agent import ReviewAgent

        agent = ReviewAgent()
        result = agent.check(
            vision_output={"part_info": {"name": "Test"}},
            cnc_output={"code_segments": [], "self_review": {"overall": "pass"}},
        )
        assert "final_verdict" in result

    def test_prompt_service(self):
        from services.prompt_service import PromptService

        ps = PromptService()
        # 测试渲染 vision system prompt
        sys_prompt = ps.render("vision/system.j2")
        assert "工程图" in sys_prompt
        # 测试渲染 messages
        msgs = ps.render_messages("supervisor", template_name="system")
        assert len(msgs) > 0
        assert "主控调度Agent" in msgs[0]["content"]

    def test_agent_import(self):
        from workflows.erp_process.agent import ERPProcessAgent

        agent = ERPProcessAgent()
        assert agent.agent_name == "erp_process_agent"

    def test_supervisor_discoverers_agent(self):
        from agents.supervisor import SupervisorAgent

        sup = SupervisorAgent()
        assert "erp_process_agent" in sup.agents


class TestGraphInvocation:
    """图调用（mock 上下文）"""

    def test_graph_invoke_with_mock_config(self):
        from workflows.erp_process.graph import build_erp_graph

        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import StateGraph, START, END
        from workflows.erp_process.state import ERPState
        from workflows.erp_process.nodes import (
            node_login, node_detect_new_orders, node_fetch_drawing,
            node_erp_reconnect, node_fill_plan,
        )
        from workflows.erp_process.graph import node_supervisor_agent_run

        builder = StateGraph(ERPState)
        builder.add_node("login_erp", node_login)
        builder.add_node("detect_new_orders", node_detect_new_orders)
        builder.add_node("fetch_feishu_drawing", node_fetch_drawing)
        builder.add_node("supervisor_agent_run", node_supervisor_agent_run)
        builder.add_node("erp_reconnect", node_erp_reconnect)
        builder.add_node("fill_process_plan", node_fill_plan)

        builder.add_edge(START, "login_erp")
        builder.add_edge("login_erp", "detect_new_orders")
        builder.add_edge("detect_new_orders", "fetch_feishu_drawing")
        builder.add_edge("fetch_feishu_drawing", "supervisor_agent_run")
        builder.add_edge("supervisor_agent_run", "erp_reconnect")
        builder.add_edge("erp_reconnect", "fill_process_plan")
        builder.add_edge("fill_process_plan", END)

        gv3 = builder.compile(checkpointer=MemorySaver())
        assert gv3 is not None
        nodes = list(gv3.nodes.keys())
        assert "supervisor_agent_run" in nodes
