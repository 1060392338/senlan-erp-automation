"""节点: 模板匹配 — 通过 DrawingRegistry 查找相似图纸"""

import logging
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.template_match")


def node_template_match(state: ERPState, config: RunnableConfig, services: dict | None = None) -> dict:
    """在 DrawingRegistry 中匹配相似图纸"""
    ctx = config["configurable"]["ctx"]
    input_data = state.get("input", {})
    prod_no = state.get("prod_no", "UNKNOWN")

    part_name = input_data.get("part_name", "")
    drawing_path = input_data.get("drawing_path", "")

    matched = None

    # 尝试通过 DrawingRegistry 匹配
    drawing_reg = ctx.get_service("drawing")
    if drawing_reg:
        try:
            query_features = {
                "name": part_name,
                "drawing_path": drawing_path,
            }
            similar_docs = drawing_reg.find_similar(query_features)
            if similar_docs:
                template_id = similar_docs[0].metadata.get("process_used", "")
                matched = template_id if template_id else "similar_found"
                log.info(f"模板匹配命中: {matched}")
            else:
                log.info("模板匹配无结果")
        except Exception as e:
            log.warning(f"模板匹配失败: {e}")
    else:
        log.info("DrawingRegistry 未注册，跳过模板匹配")

    return {"matched_template": matched, "checkpoint": Checkpoint.TEMPLATE_MATCHED}
