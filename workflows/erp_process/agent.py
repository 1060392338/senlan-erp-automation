"""
ERPProcessAgent — 单 Agent 工作流实现

多 Bot 架构：
  - 每个 Bot 创建自己的 ERPProcessAgent 实例，传入独立 ServiceContainer
  - 每个 agent.run() 创建独立的 RequestContext
  - 通过 thread_id = {tenant}-{agent}-{run_id} 隔离 LangGraph 状态

多轮对话：
  - agent.run() 接受 user_message 参数，在中断点记录对话历史
  - resume 时加载历史消息
  - 对话历史按 tenant/user/thread_id 隔离存储
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from agents.base import WorkflowAgent
from workflows.erp_process.graph import build_erp_graph
from services.context import RequestContext
from services.tenant_context import build_tenant_config
from services.chat_history import ChatHistoryService
from services.service_container import ServiceContainer

log = logging.getLogger("erp_process_agent")


class ERPProcessAgent(WorkflowAgent):
    """销售订单→2D图纸AI读图→工艺推理→计划工艺回填→CNC代码生成"""

    agent_name = "erp_process_agent"
    agent_description = "销售订单→2D图纸AI读图→工艺推理→计划工艺回填→CNC代码生成"

    def __init__(self, services: Optional[ServiceContainer] = None):
        """
        Args:
            services: 独立服务容器。不传则使用 ServiceRegistry（兼容旧代码）。
                      多 Bot 场景：每个 Bot 传入自己的 ServiceContainer。
        """
        self._services = services
        self._graph = None

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "customer": {"type": "string", "description": "客户名称"},
                "part_name": {"type": "string", "description": "零件名称"},
                "drawing_path": {"type": "string", "description": "图纸本地路径"},
                "qty": {"type": "integer", "description": "数量"},
                "deadline": {"type": "string", "description": "交期"},
                "user_message": {"type": "string", "description": "用户输入（多轮对话）"},
            },
            "required": ["customer", "part_name"],
        }

    @property
    def graph(self):
        if self._graph is None:
            self._graph = build_erp_graph()
        return self._graph

    # ── 共享服务获取 ──

    def _get_shared_services(self):
        """获取共享服务（优先用 ServiceContainer，fallback 到 ServiceRegistry）"""
        if self._services:
            return (
                self._services.kb,
                self._services.template,
                self._services.drawing,
            )
        from services import ServiceRegistry
        try:
            kb = ServiceRegistry.get("kb")
        except KeyError:
            kb = None
        try:
            template = ServiceRegistry.get("template")
        except KeyError:
            template = None
        try:
            drawing = ServiceRegistry.get("drawing")
        except KeyError:
            drawing = None
        return kb, template, drawing

    # ── 核心运行方法 ──

    def run(
        self,
        input_data: dict,
        thread_id: Optional[str] = None,
        tenant_config: Optional[dict] = None,
        resume: bool = False,
        user_id: Optional[str] = None,
        user_message: Optional[str] = None,
    ) -> dict:
        """
        执行工作流。

        Args:
            input_data: 输入数据（含 user_message 用于多轮对话）
            thread_id: LangGraph thread_id（含 run_id，用于多会话隔离）
            tenant_config: 租户配置 dict
            resume: 是否从断点恢复
            user_id: 用户 ID（多用户隔离）
            user_message: 用户在中断点输入的回复（自然语言）

        Returns:
            执行结果 dict
        """
        # ── 解析 thread_id ──
        if not thread_id:
            run_id = uuid.uuid4().hex[:12]
            thread_id = f"{self.agent_name}-{run_id}"
        else:
            run_id = thread_id.split("-")[-1]

        # ── 解析 user_id ──
        uid = user_id or input_data.get("user_id", "default")
        if user_message:
            input_data["user_message"] = user_message

        # ── 构建 tenant_config ──
        tc = build_tenant_config(tenant_config or {})

        # ── 创建 ChatHistoryService ──
        chat_history_svc = ChatHistoryService()

        # ── 创建 RequestContext ──
        shared_kb, shared_template, shared_drawing = self._get_shared_services()

        ctx = RequestContext.create(
            tenant_config=tc,
            run_id=run_id,
            global_config=self._get_global_config(),
            user_id=uid,
            shared_kb=shared_kb,
            shared_template=shared_template,
            shared_drawing=shared_drawing,
            chat_history=chat_history_svc,
        )

        config = {
            "configurable": {
                "thread_id": thread_id,
                "ctx": ctx,
            }
        }

        log.info(
            f"run: thread={thread_id}, tenant={tc.get('id')}, "
            f"user={uid}, run_id={run_id}, resume={resume}"
        )

        # ── 多轮对话：保存用户消息 ──
        tenant_id = tc.get("id", "default")
        if user_message:
            chat_history_svc.add_message(thread_id, tenant_id, uid, "user", user_message)

        # ── 飞书通知：工作流开始 ──
        if ctx.notifier:
            notify_events = tc.get("notify_on", [])
            if "workflow_start" in notify_events:
                try:
                    ctx.notifier.notify_workflow_start(
                        ctx.display_name,
                        input_data.get("part_name", ""),
                    )
                except Exception as e:
                    log.warning(f"飞书通知失败: {e}")

        # ── 断点恢复 vs 全新执行 ──
        if resume:
            log.info(f"断点恢复: thread_id={thread_id}")
            current_state = ctx.state.load(thread_id)
            if current_state:
                saved_input = current_state.get("input", {})
                if saved_input:
                    saved_input.update(input_data)
                    input_data = saved_input

        # ── 初始 State ──
        initial_state = {
            "input": input_data,
            "tenant_config": tc,
            "errors": [],
            "checkpoint": 0,
            "plan_saved": False,
            "routing_saved": False,
            "cnc_saved": False,
            "session_id": ctx.session_id,
            "prod_no": None,
            "drawing_url": None,
            "part_info": None,
            "features": None,
            "matched_template": None,
            "process_plan": None,
            "cnc_code": None,
            "user_message": user_message,
            "chat_history": chat_history_svc.get_history(thread_id, tenant_id, uid, limit=20) if resume else [],
        }

        # ── 执行 ──
        try:
            result = self.graph.invoke(initial_state, config)
        finally:
            # 保存状态快照
            try:
                ctx.state.save(thread_id, {
                    "input": input_data,
                    "run_id": run_id,
                    "tenant_id": tc.get("id"),
                    "user_id": uid,
                })
            except Exception as e:
                log.warning(f"保存状态失败: {e}")

        log.info(
            f"完成: run_id={run_id}, "
            f"checkpoint={result.get('checkpoint', '?')}"
        )

        # ── 多轮对话：保存回复 ──
        try:
            summary = _format_result_summary(result)
            chat_history_svc.add_message(thread_id, tenant_id, uid, "assistant", summary)
        except Exception as e:
            log.warning(f"保存对话历史失败: {e}")

        # ── 释放资源 ──
        # 注意：仅在非中断完成时关闭浏览器
        # 如果是中断（checkpoint=10 或 21），浏览器保持打开
        from workflows.erp_process.state import Checkpoint
        cp = result.get("checkpoint", 0)
        is_interrupted = cp in (Checkpoint.DRAWING_FETCHED, Checkpoint.CNC_GENERATED)
        if not is_interrupted:
            ctx.close()
        else:
            log.info(f"工作流在 checkpoint={cp} 处中断，浏览器保持打开")

        return result

    def _get_global_config(self) -> dict:
        """获取全局配置"""
        if self._services:
            return {}
        from services import ServiceRegistry
        return ServiceRegistry.get_config()


def _format_result_summary(result: dict) -> str:
    """格式化结果摘要（保存到对话历史）"""
    from workflows.erp_process.state import Checkpoint
    cp = result.get("checkpoint", 0)
    prod_no = result.get("prod_no", "")
    plan_saved = result.get("plan_saved", False)
    routing_saved = result.get("routing_saved", False)

    if cp == Checkpoint.DRAWING_FETCHED:
        return f"Phase 1 完成。生产单号: {prod_no}。请上传图纸或确认跳过视觉分析。"

    if cp == Checkpoint.CNC_GENERATED:
        return "CNC 代码已生成，请人工审核。输入 '继续' 以回填 ERP。"

    parts = []
    if prod_no:
        parts.append(f"生产单号: {prod_no}")
    if plan_saved:
        parts.append("计划工艺已回填")
    if routing_saved:
        parts.append("CNC代码已回填")
    if not parts:
        parts.append("工作流执行完成")

    return "；".join(parts)
