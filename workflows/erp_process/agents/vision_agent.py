"""识图Agent — 阿里百炼 qwen3.6-plus 视觉分析

职责：接收2D工程图 → 输出结构化零件信息
"""

import json
import logging
import os
import re
from typing import Optional

from services.prompt_service import PromptService

log = logging.getLogger("agent.vision")


class VisionAgent:
    """工程图识别Agent"""

    def __init__(self, llm=None, prompt_service: Optional[PromptService] = None):
        self._llm = llm
        self._prompt = prompt_service or PromptService()

    def analyze(self, drawing_path: str, prod_no: str = "") -> dict:
        """分析2D工程图

        Args:
            drawing_path: 图纸本地路径或 URL
            prod_no: 生产单号（用于日志）

        Returns:
            {"part_info": {...}, "features": [...], "special_requirements": [...],
             "confidence": 0.0~1.0, "warnings": [...]}
        """
        if not drawing_path or not os.path.exists(drawing_path):
            log.warning(f"图纸路径无效: {drawing_path}")
            return self._fallback(prod_no)

        log.info(f"视觉分析: {drawing_path}, prod_no={prod_no}")

        if not self._llm:
            log.warning("LLM 未配置，使用降级")
            return self._fallback(prod_no)

        try:
            # 渲染视觉 prompt（含 system + few_shot）
            system_prompt = self._prompt.render("vision/system.j2")
            few_shot = self._prompt.render("vision/few_shot.j2")
            user_prompt = self._prompt.render("vision/analyze.j2", few_shot=few_shot, prod_no=prod_no)

            if not user_prompt:
                log.warning("提示词渲染为空")
                return self._fallback(prod_no)

            # 调用 LLM vision（带 system prompt）
            response = self._llm.vision_with_system(
                image_url=drawing_path,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model="qwen3.6-plus",
            )

            if not response:
                return self._fallback(prod_no)

            text = response
            if hasattr(response, "choices") and response.choices:
                text = response.choices[0].message.content

            # 提取 JSON
            result = self._parse_json(text)
            if result:
                log.info(f"视觉分析成功: {result.get('part_info', {}).get('name', '')}")
                return self._normalize(result)

        except Exception as e:
            log.warning(f"视觉分析失败: {e}")

        return self._fallback(prod_no)

    def _parse_json(self, text: str) -> Optional[dict]:
        """从 LLM 响应中提取 JSON"""
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not json_match:
            return None

        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            # 处理常见 JSON 错误
            cleaned = json_match.group()
            cleaned = re.sub(r",\s*}", "}", cleaned)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                return None

    def _normalize(self, raw: dict) -> dict:
        """规范化输出"""
        part_info = raw.get("part_info", {})
        features = raw.get("features", [])
        special_reqs = raw.get("special_requirements", [])

        return {
            "part_info": {
                "name": part_info.get("name", ""),
                "material": part_info.get("material", "K490 Vanadis 8"),
                "hardness": part_info.get("hardness", "58-63HRC"),
                "shape": part_info.get("shape", "square"),
                "coating": part_info.get("coating", ""),
                "qty": part_info.get("qty", 1),
            },
            "features": features,
            "special_requirements": special_reqs,
            "confidence": 0.8 if features else 0.3,
            "warnings": [],
        }

    def _fallback(self, prod_no: str = "") -> dict:
        """降级返回默认值"""
        return {
            "part_info": {
                "name": prod_no or "未知零件",
                "material": "K490 Vanadis 8",
                "hardness": "58-63HRC",
                "shape": "square",
                "coating": "TiN",
                "qty": 1,
            },
            "features": [
                {"type": "外形", "spec": "190x77mm"},
                {"type": "精孔", "spec": "∅2.0+0.01", "qty": 8, "roughness": 0.63},
                {"type": "螺纹", "spec": "M10x1"},
                {"type": "利角", "note": "严禁倒角"},
            ],
            "special_requirements": ["Sharp edge", "TiN coating"],
            "confidence": 0.0,
            "warnings": ["LLM不可用，使用默认降级数据"],
        }
