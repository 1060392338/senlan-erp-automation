"""DEPRECATED — CNC代码不再写入ERP，通过飞书机器人返回

此节点已废弃。CNC代码由fill_by_vision.py中的format_cnc_for_remark()
嵌入到工序的工艺要求字段中，或通过飞书机器人独立返回给用户。
不再需要额外的ERP写入步骤。

保留node_fill_routing函数签名兼容LangGraph编译，
但实际只发飞书通知，不再操作ERP页面。
"""
import json
import logging
from typing import Optional
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState, Checkpoint

log = logging.getLogger("node.routing_filler")

DEPRECATED_WARNING = (
    "[DEPRECATED] routing_filler::node_fill_routing 已被废弃。\n"
    "CNC代码不再写入ERP，通过飞书机器人返回。\n"
    "详见: scripts/fill_by_vision.py::format_cnc_for_remark()\n"
    "或在 graph.py 中移除 fill_routing_cnc 节点。"
)


# ── 主节点（仅保留飞书通知）──

def node_fill_routing(state: ERPState, config: RunnableConfig, services: Optional[dict] = None) -> dict:
    """DEPRECATED — CNC代码不再写入ERP，仅发飞书通知"""
    ctx = config["configurable"]["ctx"]
    prod_no = state.get("prod_no", "W20126051401")
    cnc_code = state.get("cnc_code", {})
    part_info = state.get("part_info", {})
    part_name = part_info.get("name", "") if isinstance(part_info, dict) else ""

    log.warning(DEPRECATED_WARNING)

    # ── 仅保留飞书通知（告知CNC代码已生成，需通过机器人查看）──
    try:
        from services.notification_service import FeishuNotifier
        feishu_webhook = ctx.erp_config.get("feishu_webhook", "")
        notifier = FeishuNotifier({"webhook_url": feishu_webhook})

        takisawa_code = cnc_code.get("takisawa_nex108") or cnc_code.get("takisawa") or ""
        sodick_code = cnc_code.get("sodick_ad32ls") or cnc_code.get("sodick") or ""

        summary_lines = [
            f"✅ 森蓝ERP · CNC代码生成完成",
            f"━━━━━━━━━━━━━━━━",
            f"📦 生产单号: {prod_no}",
        ]
        if part_name:
            summary_lines.append(f"🔩 零件名称: {part_name}")
        summary_lines.append(f"📋 CNC代码（已通过飞书机器人返回，未写入ERP）:")
        if takisawa_code:
            summary_lines.append(f"  · TAKISAWA NEX-108: {len(takisawa_code)}字符")
        if sodick_code:
            summary_lines.append(f"  · SODICK AD32LS: {len(sodick_code)}字符")
        if not takisawa_code and not sodick_code:
            summary_lines.append(f"  · 无CNC代码")

        if feishu_webhook:
            notifier.send_text(feishu_webhook, "\n".join(summary_lines))
            log.info("飞书通知已发送")
        else:
            log.info("未配置飞书webhook，跳过通知")
    except Exception as e:
        log.warning(f"飞书通知失败: {e}")

    return {"routing_saved": False, "cnc_saved": False, "checkpoint": Checkpoint.PLAN_FILLED}
