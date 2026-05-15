"""
ERP 工艺工作流 — LangGraph 定义

三段式（通过 interrupt_after 实现自然中断，无需手动路由）：
  Phase 1 (Online ERP):   login → create_order → fetch_drawing
    ↓ interrupt_after (等人确认图纸/提供图纸)
  Phase 2 (Offline AI):   template_match → (vision_analyze?) → process_reasoning → generate_cnc
    ↓ interrupt_after (人工审核 CNC 代码)
  Phase 3 (Online ERP):   erp_reconnect → fill_process_plan → fill_routing_cnc → END

多 Bot 架构：
  - 每个 agent 实例调用 build_erp_graph()，传入独立 checkpointer
  - 不再使用全局 _graph_instance 单例
  - 每个 Bot 拥有自己的图实例 + SqliteSaver 连接
"""

import logging

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from typing import Optional
from workflows.erp_process.state import ERPState, Checkpoint

log = logging.getLogger("graph")


def route_template_match(state: dict) -> str:
    if state.get("matched_template"):
        log.info("模板匹配命中，跳过视觉分析")
        return "process_reasoning"
    log.info("模板未匹配，走视觉分析")
    return "vision_analyze"


def route_after_login(state: dict) -> str:
    if state.get("checkpoint") == Checkpoint.LOGIN_FAILED:
        log.error("登录失败，工作流中止")
        return END  # type: ignore
    return "create_order"


def build_erp_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> StateGraph:
    from workflows.erp_process.nodes import (
        node_login, node_create_order, node_fetch_drawing,
        node_template_match, node_vision_analyze, node_process_reasoning,
        node_generate_cnc, node_erp_reconnect, node_fill_plan,
        node_fill_routing,
    )

    builder = StateGraph(ERPState)

    # Phase 1
    builder.add_node("login_erp", node_login)
    builder.add_node("create_order", node_create_order)
    builder.add_node("fetch_drawing", node_fetch_drawing)

    # Phase 2
    builder.add_node("template_match", node_template_match)
    builder.add_node("vision_analyze", node_vision_analyze)
    builder.add_node("process_reasoning", node_process_reasoning)
    builder.add_node("generate_cnc", node_generate_cnc)

    # Phase 3
    builder.add_node("erp_reconnect", node_erp_reconnect)
    builder.add_node("fill_process_plan", node_fill_plan)
    builder.add_node("fill_routing_cnc", node_fill_routing)

    # Edges
    builder.add_edge(START, "login_erp")
    builder.add_conditional_edges(
        "login_erp", route_after_login,
        {"create_order": "create_order", END: END},
    )
    builder.add_edge("create_order", "fetch_drawing")
    builder.add_edge("fetch_drawing", "template_match")
    builder.add_conditional_edges(
        "template_match", route_template_match,
        {"vision_analyze": "vision_analyze", "process_reasoning": "process_reasoning"},
    )
    builder.add_edge("vision_analyze", "process_reasoning")
    builder.add_edge("process_reasoning", "generate_cnc")
    builder.add_edge("generate_cnc", "erp_reconnect")
    builder.add_edge("erp_reconnect", "fill_process_plan")
    builder.add_edge("fill_process_plan", "fill_routing_cnc")
    builder.add_edge("fill_routing_cnc", END)

    # Compile
    if checkpointer is None:
        import os, sqlite3
        cp_path = os.environ.get("CHECKPOINTS_DB", "checkpoints.db")
        conn = sqlite3.connect(cp_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)

    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_after=["fetch_drawing", "generate_cnc"],
    )
    log.info("LangGraph 编译完成（2 个中断点: fetch_drawing, generate_cnc）")
    return graph
