"""ERP 工艺工作流 V3 — LangGraph 定义（多Agent编排版）

三段式（通过 interrupt_after 实现自然中断）：

  Phase 1 (Online ERP):
    login_erp → detect_new_orders → fetch_feishu_drawing
      ↓ interrupt_after (等待确认图纸匹配)

  Phase 2 (多Agent编排 - 非LangGraph节点，内部for循环):
    supervisor_agent_run
      ├── 识图Agent.analyze()    — qwen3.6-plus 视觉分析
      ├── 编程Agent.generate()    — LLM生成CNC代码 + 自我审查
      ├── 审核Agent.check()       — 交叉审查
      └── 循环: 不通过→修正→再审核 (max 3次)
      ↓ interrupt_after (人工审核 CNC 代码)

  Phase 3 (Online ERP):
    erp_reconnect → fill_process_plan（含上传图纸）→ END

V3+ (fill_routing_cnc removed): CNC代码不再写入ERP，通过飞书机器人返回。
  详见: scripts/fill_by_vision.py::format_cnc_for_remark()

V3 核心变更：
  - process_reasoning / generate_cnc 两个节点合并为 supervisor_agent_run
  - 所有 LLM 提示词通过 Jinja2 模板管理（templates/prompts/）
  - CNC 代码由 LLM 生成，不是 f-string
  - 3个子Agent：识图/编程/审核，主Agent调度
"""

import logging
import os
import sqlite3

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from typing import Optional
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState, Checkpoint
from services.prompt_service import PromptService

log = logging.getLogger("graph")


def route_after_login(state: dict) -> str:
    if state.get("checkpoint") == Checkpoint.LOGIN_FAILED:
        log.error("登录失败，工作流中止")
        return END  # type: ignore
    return "detect_new_orders"


def route_no_new_orders(state: dict) -> str:
    if state.get("new_orders") and len(state["new_orders"]) > 0:
        return "fetch_feishu_drawing"
    log.info("没有新生产单，工作流结束")
    return END  # type: ignore


def node_supervisor_agent_run(state: dict, config: RunnableConfig, services: Optional[dict] = None) -> dict:
    """多Agent编排节点 — 替代 process_reasoning + generate_cnc"""
    ctx = config["configurable"]["ctx"]

    log.info(">>> 多Agent编排开始 <<<")

    # 创建主Agent（传入 LLM + PromptService）
    from workflows.erp_process.agents.supervisor import SupervisorAgent
    prompt_svc = PromptService()
    agent = SupervisorAgent(llm=ctx.llm, prompt_service=prompt_svc)

    # 执行多Agent编排
    result = agent.run(state)

    log.info("<<< 多Agent编排完成 >>>")
    return result


def build_erp_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> StateGraph:
    from workflows.erp_process.nodes import (
        node_login, node_detect_new_orders, node_fetch_drawing,
        node_erp_reconnect, node_fill_plan,
    )

    builder = StateGraph(ERPState)

    # Phase 1
    builder.add_node("login_erp", node_login)
    builder.add_node("detect_new_orders", node_detect_new_orders)
    builder.add_node("fetch_feishu_drawing", node_fetch_drawing)

    # Phase 2 — 多Agent编排
    builder.add_node("supervisor_agent_run", node_supervisor_agent_run)

    # Phase 3
    builder.add_node("erp_reconnect", node_erp_reconnect)
    builder.add_node("fill_process_plan", node_fill_plan)

    # Edges
    builder.add_edge(START, "login_erp")
    builder.add_conditional_edges(
        "login_erp", route_after_login,
        {"detect_new_orders": "detect_new_orders", END: END},
    )
    builder.add_conditional_edges(
        "detect_new_orders", route_no_new_orders,
        {"fetch_feishu_drawing": "fetch_feishu_drawing", END: END},
    )
    builder.add_edge("fetch_feishu_drawing", "supervisor_agent_run")
    builder.add_edge("supervisor_agent_run", "erp_reconnect")
    builder.add_edge("erp_reconnect", "fill_process_plan")
    builder.add_edge("fill_process_plan", END)

    # Compile
    if checkpointer is None:
        cp_path = os.environ.get("CHECKPOINTS_DB", "checkpoints.db")
        conn = sqlite3.connect(cp_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)

    graph = builder.compile(
        checkpointer=checkpointer,
    )
    log.info("LangGraph V3 编译完成（无中断点）")
    return graph
