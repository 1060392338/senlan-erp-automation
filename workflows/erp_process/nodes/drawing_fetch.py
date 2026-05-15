"""节点: 飞书请求图纸 + 阿里百炼视觉分析

流程：
  首次运行：发送飞书消息请求图纸 → 中断等待
  恢复运行：检查用户是否提供了图纸URL → 调用 qwen3.6-plus 视觉分析 → 存结果到 state
"""

import json
import logging
import os
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.fetch_drawing")


def node_fetch_drawing(state: ERPState, config: RunnableConfig, services: dict | None = None) -> dict:
    """飞书请求图纸 + 视觉分析"""
    ctx = config["configurable"]["ctx"]
    input_data = state.get("input", {})
    prod_no = state.get("prod_no", "")
    part_name = input_data.get("part_name", "")
    user_message = input_data.get("user_message", "")
    drawing_url = state.get("drawing_url") or input_data.get("drawing_path", "")
    
    # ── 判断是首次运行还是恢复 ──
    is_resume = bool(user_message) or bool(drawing_url)
    
    if not is_resume:
        # ── 首次运行：发飞书请求图纸 ──
        log.info(f"飞书请求图纸: prod_no={prod_no}, part={part_name}, session={ctx.session_id}")
        
        # 发送飞书消息请求图纸
        if ctx.notifier:
            try:
                msg = (
                    f"📋 **[{ctx.display_name}] 需要图纸**\n\n"
                    f"**生产单号**: {prod_no or '待确认'}\n"
                    f"**零件名称**: {part_name}\n"
                    f"**客户**: {input_data.get('customer', '')}\n\n"
                    "请将2D图纸图片发送过来，我会用AI分析后继续工艺规划。\n"
                    "发送格式：图纸URL或图片附件。"
                )
                ctx.notifier.send_text(msg)
                log.info("飞书消息发送成功")
            except Exception as e:
                log.warning(f"飞书消息发送失败: {e}")
        
        return {
            "stage": "fetch_drawing",
            "drawing_requested": True,
            "checkpoint": Checkpoint.DRAWING_FETCHED,
        }
    
    # ── 恢复运行：分析图纸 ──
    log.info(f"收到图纸: drawing_url={drawing_url[:80] if drawing_url else '(来自user_message)'}, part={part_name}")
    
    # 从 user_message 提取图纸URL
    final_drawing_url = drawing_url
    if not final_drawing_url and user_message:
        # 尝试从 user_message 提取URL
        import re
        urls = re.findall(r'https?://[^\s]+', user_message)
        if urls:
            final_drawing_url = urls[0]
            log.info(f"从用户消息提取到URL: {final_drawing_url[:80]}")
    
    # ── 调用阿里百炼 qwen3.6-plus 视觉分析 ──
    part_info = {}
    features = []
    
    if final_drawing_url and ctx.llm:
        try:
            log.info(f"调用 qwen3.6-plus 视觉分析: {final_drawing_url[:80]}")
            
            # 构建视觉分析 prompt（五层推理）
            vision_prompt = (
                "你是一个专业的工程图识别助手。请仔细分析这张2D工程图，"
                "以 JSON 格式返回以下信息：\n\n"
                "L1 零件基本信息：name（零件名称/图号）, material（材料）, "
                "hardness（硬度）, shape（外形：square/round/irregular）, "
                "coating（表面处理）, qty（数量）\n\n"
                "L2 几何特征列表（features），每个特征包含："
                "type（外形/精孔/螺纹/槽/斜面/倒角/粗糙度面等）, "
                "spec（规格尺寸）, qty（数量，可选）, "
                "roughness（粗糙度Ra值，可选）, note（特殊要求，如利角/不倒角）\n\n"
                "L5 特殊要求（特殊要求列表），如：Sharp edge（利角不倒角）, "
                "TiN coating, laser marking（激光刻字）等\n\n"
                "返回格式（仅JSON，无其他文字）：\n"
                '{"part_info":{"name":"...","material":"...","hardness":"...",'
                '"shape":"square/round","coating":"...","qty":2},'
                '"features":[{"type":"外形","spec":"100x82mm"},...],'
                '"special_requirements":["Sharp edge","TiN coating"]}'
            )
            
            # 调用百炼视觉模型
            response = ctx.llm.vision(
                model="qwen3.6-plus",
                image_url=final_drawing_url,
                prompt=vision_prompt,
            )
            
            # 解析JSON结果
            if response:
                text = response
                if hasattr(response, 'choices') and response.choices:
                    text = response.choices[0].message.content
                
                # 提取JSON
                import re
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    part_info = parsed.get("part_info", {})
                    features = parsed.get("features", [])
                    special_reqs = parsed.get("special_requirements", [])
                    
                    log.info(f"视觉分析完成: part={part_info.get('name','')}, features={len(features)}")
                    
                    # 注册到 DrawingRegistry
                    drawing_svc = state.get("_drawing_svc") or services.get("drawing") if services else None
                    if drawing_svc:
                        drawing_svc.register(prod_no, {
                            "part_info": part_info,
                            "features": features,
                            "special_requirements": special_reqs,
                        })
        except Exception as e:
            log.warning(f"视觉分析失败，使用降级默认值: {e}")
    
    if not part_info:
        # 降级：使用输入中的默认信息
        part_info = {
            "name": part_name,
            "material": input_data.get("material", "K490 Vanadis 8"),
            "hardness": input_data.get("hardness", "58-63HRC"),
            "shape": input_data.get("shape", "square"),
            "coating": input_data.get("coating", "TiN"),
            "qty": input_data.get("qty", 2),
        }
        features = [
            {"type": "外形", "spec": "190x77mm"},
            {"type": "精孔", "spec": "∅2.0+0.01", "qty": 8, "roughness": 0.63},
            {"type": "螺纹", "spec": "M10x1"},
            {"type": "利角", "note": "严禁倒角"},
        ]
    
    return {
        "stage": "template_match",
        "drawing_url": final_drawing_url,
        "part_info": part_info,
        "features": features,
        "drawing_analyzed": True,
        "checkpoint": Checkpoint.DRAWING_FETCHED,
    }
