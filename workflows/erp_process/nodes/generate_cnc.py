"""节点: CNC 代码生成 + 飞书通知待审核

从 process_plan 中提取数控精车和镜面放电两道工序，
使用 Jinja2 模板生成机床代码。
"""

import logging
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.generate_cnc")


def node_generate_cnc(state: ERPState, config: RunnableConfig, services: dict | None = None) -> dict:
    """生成 CNC 代码 + 通知人工审核"""
    ctx = config["configurable"]["ctx"]
    part_info = state.get("part_info", {})
    features = state.get("features", [])
    process_plan = state.get("process_plan", [])
    prod_no = state.get("prod_no", "")
    deadline = state.get("input", {}).get("deadline", "")

    log.info(
        f"CNC 生成: prod_no={prod_no}, "
        f"part={part_info.get('name')}, features={len(features or [])}"
    )

    # 生成 CNC 代码
    takisawa_code = ""
    sodick_params = {}

    try:
        tpl = ctx.get_service("template")
        if tpl:
            takisawa_code = tpl.generate_cnc(
                "takisawa", "finish", part_info, features
            )
            sodick_params = tpl.generate_edm_params(part_info, features)
            log.info("CNC 代码生成完成")
        else:
            takisawa_code = "; TemplateService 未注册\n; (占位 CNC 代码)"
            sodick_params = {"machine": "SODICK AD32LS", "note": "pending"}
            log.warning("TemplateService 未注册")
    except Exception as e:
        takisawa_code = f"; CNC 生成失败: {e}"
        sodick_params = {"machine": "SODICK AD32LS", "note": "error"}
        log.error(f"CNC 生成异常: {e}")

    # 收集注意事项
    notes = []
    if features:
        for f in features:
            if f.get("type") == "利角":
                notes.append("⚠️ 利角 — 严禁倒角，保刃口")
    if deadline:
        notes.append(f"⚠️ 交期: {deadline}")

    # 提取关键工序
    cnc_steps = [
        s for s in (process_plan or [])
        if s.get("name") in ("CNC 2", "CNC精车", "慢丝", "EDM")
    ]
    if cnc_steps:
        log.info(f"CNC 相关工序: {[s.get('name') for s in cnc_steps]}")

    cnc_code = {
        "takisawa_nex108": takisawa_code,
        "sodick_ad32ls": sodick_params,
        "notes": notes,
    }

    # 飞书通知：CNC 代码待审核
    notify_on = ctx.tenant_config.get("notify_on", [])
    if ctx.notifier and "cnc_ready" in notify_on:
        try:
            ctx.notifier.notify_cnc_ready(ctx.display_name, prod_no)
        except Exception as e:
            log.warning(f"飞书通知失败: {e}")

    return {"cnc_code": cnc_code, "checkpoint": Checkpoint.CNC_GENERATED}
