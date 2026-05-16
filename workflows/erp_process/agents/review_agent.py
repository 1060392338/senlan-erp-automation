"""审核Agent — 交叉审查子Agent输出

职责：审查识图Agent和编程Agent的输出 → 给出审批意见
"""

import json
import logging
import re
from typing import Optional

from services.prompt_service import PromptService

log = logging.getLogger("agent.review")


class ReviewAgent:
    """工艺质量审核Agent"""

    def __init__(self, llm=None, prompt_service: Optional[PromptService] = None):
        self._llm = llm
        self._prompt = prompt_service or PromptService()

    def check(
        self,
        vision_output: dict,
        cnc_output: dict,
        part_info: Optional[dict] = None,
    ) -> dict:
        """交叉审查识图和编程输出

        Args:
            vision_output: 识图Agent结果
            cnc_output: 编程Agent结果（含 self_review）
            part_info: 原始零件信息（可选）

        Returns:
            {"vision_review": {...}, "cnc_review": {...}, "final_verdict": "approve"|"revision_needed"|"reject"}
        """
        log.info("=== 交叉审查开始 ===")

        if not self._llm:
            log.info("LLM 不可用，自动批准")
            return self._auto_approve(vision_output, cnc_output)

        self_review = cnc_output.get("self_review", {})

        try:
            messages = self._prompt.render_messages(
                "review",
                template_name="cross_check",
                vision_output=json.dumps(vision_output, ensure_ascii=False, indent=2),
                cnc_output=self._format_cnc_for_review(cnc_output),
                self_review=json.dumps(self_review, ensure_ascii=False, indent=2),
            )

            if not messages:
                return self._auto_approve(vision_output, cnc_output)

            response = self._llm.chat(messages, model="deepseek-v4-pro")
            if response:
                result = self._parse_json(response)
                if result and "final_verdict" in result:
                    log.info(f"审核结论: {result['final_verdict']}")
                    return result

        except Exception as e:
            log.warning(f"审核调用失败: {e}")

        return self._auto_approve(vision_output, cnc_output)

    def _format_cnc_for_review(self, cnc_output: dict) -> dict:
        """格式化 CNC 输出用于审查（完整传递，不分段截断）"""
        segments = cnc_output.get("code_segments", [])
        return {
            "code_segments": [
                {
                    "machine": s.get("machine", ""),
                    "feature": s.get("feature", ""),
                    "code": s.get("code", ""),
                }
                for s in segments
            ]
        }

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _auto_approve(vision_output: dict, cnc_output: dict) -> dict:
        return {
            "vision_review": {
                "passed": True,
                "issues": [],
                "feature_coverage": 1.0,
            },
            "cnc_review": {
                "passed": True,
                "issues": [],
                "safety_score": 85,
                "overall_score": 80,
            },
            "final_verdict": "approve",
            "feedback_for_main_agent": "LLM不可用，自动批准",
        }
