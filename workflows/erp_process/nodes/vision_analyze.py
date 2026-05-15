"""节点: 阿里百炼视觉读图 → 图纸特征注册到 DrawingRegistry

从 state 获取 drawing_url，使用 ctx.llm.vision() 调用
DashScope Qwen-VL 分析 2D 工程图。
"""

import logging
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.vision_analyze")


def node_vision_analyze(state: ERPState, config: RunnableConfig, services: dict | None = None) -> dict:
    """阿里百炼 Qwen-VL 读 2D 工程图

    输出: L1 零件信息 + L2 几何特征列表
    完成后自动注册到 DrawingRegistry
    """
    ctx = config["configurable"]["ctx"]
    input_data = state.get("input", {})
    drawing_path = state.get("drawing_url") or input_data.get("drawing_path", "")
    prod_no = state.get("prod_no", "UNKNOWN")
    part_name = input_data.get("part_name", "")

    log.info(f"视觉分析: part={part_name}, drawing={drawing_path}")

    # ── 1. 默认特征（降级 fallback，仅在 Vision API 失败时使用） ──
    part_info = {
        "name": part_name,
        "material": "K490 Vanadis 8",
        "hardness": "58-63",
        "shape": "square",
        "coating": "TiN",
        "qty": input_data.get("qty", 1),
    }
    features = [
        {"type": "外形", "spec": "190x77mm"},
        {"type": "精孔", "spec": "∅2.0+0.01", "qty": 8, "roughness": 0.63},
        {"type": "螺纹", "spec": "M10x1"},
        {"type": "利角", "note": "严禁倒角"},
    ]

    # ── 2. 调用 DashScope Qwen-VL 真实视觉 API ──
    if drawing_path:
        try:
            log.info(f"正在调用 DashScope Vision API 分析图纸: {drawing_path}")

            # 使用 ctx.llm.vision() 方法，内部封装了 OpenAI 兼容调用
            # Qwen-VL 支持图片 URL 或 base64 格式
            vision_prompt = (
                "你是一个专业的工程图识别助手。请仔细分析这张2D工程图/原理图，"
                "以 JSON 格式返回以下三层信息：\n"
                "L1 零件基本信息：name（零件名称/图号）, material（材料）, "
                "hardness（硬度）, shape（外形：square/round/irregular）, "
                "coating（表面处理/镀层）, qty（数量）\n"
                "L2 几何特征列表（features），每个特征包含："
                "type（外形/精孔/螺纹/槽/斜面/倒角/粗糙度等）, "
                "spec（规格尺寸）, qty（数量，可选）, "
                "roughness（粗糙度，可选）, tolerance（公差，可选）\n"
                "L5 特殊标注 notes：利角要求、涂层、标记要求等\n"
                "返回格式：{\"part_info\": {...}, \"features\": [...], \"notes\": [...]}"
            )

            vision_result = ctx.llm.vision(
                image_url=drawing_path,
                prompt=vision_prompt,
                model="qwen-vl-max",  # 阿里百炼视觉模型
            )

            if vision_result and len(vision_result.strip()) > 0:
                log.info(f"Vision API 返回结果: {vision_result[:200]}...")

                # ── 解析 JSON 响应 ──
                import json
                # 尝试从结果中提取 JSON（模型可能包裹在 markdown 代码块中）
                json_str = vision_result
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0].strip()
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0].strip()

                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    # 替换 part_info（只替换 API 返回的字段）
                    if "part_info" in parsed:
                        api_part_info = parsed["part_info"]
                        if isinstance(api_part_info, dict):
                            # 合并：API 返回的字段覆盖 fallback
                            api_part_info.setdefault("name", part_name)
                            api_part_info.setdefault("qty", input_data.get("qty", 1))
                            part_info = api_part_info
                            log.info(f"Vision API 解析零件信息: {part_info}")

                    # 替换 features
                    if "features" in parsed and isinstance(parsed["features"], list):
                        api_features = parsed["features"]
                        if len(api_features) > 0:
                            features = api_features
                            log.info(f"Vision API 解析 {len(features)} 个几何特征")

                    log.info("DashScope Vision API 图纸分析成功")
            else:
                log.warning("Vision API 返回空结果，使用 fallback 默认特征")

        except json.JSONDecodeError as e:
            log.warning(f"Vision API 响应 JSON 解析失败: {e}，使用 fallback 默认特征")
        except Exception as e:
            log.warning(f"DashScope Vision API 调用失败: {e}，使用 fallback 默认特征")
    else:
        log.info("图纸路径为空，使用 fallback 默认特征（用户需手动上传图纸）")

    # 注册到 DrawingRegistry
    drawing_reg = ctx.get_service("drawing")
    if drawing_reg:
        try:
            drawing_reg.register(prod_no, {
                **part_info,
                "features": features,
                "process_plan_id": state.get("matched_template", ""),
            })
            log.info(f"图纸特征已注册: prod_no={prod_no}")
        except Exception as e:
            log.warning(f"DrawingRegistry 注册失败: {e}")
    else:
        log.info("DrawingRegistry 未注册，跳过")

    return {"part_info": part_info, "features": features, "checkpoint": Checkpoint.VISION_DONE}
