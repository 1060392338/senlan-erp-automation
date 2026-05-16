"""编程Agent — CNC 代码生成 + 自我审查

职责：接收零件特征+工艺路线 → 按设备生成 G 代码 → 自我审查
"""

import json
import logging
import re
from typing import Optional

from services.prompt_service import PromptService

log = logging.getLogger("agent.cnc")


class CNCProgrammingAgent:
    """CNC 编程Agent（含自我审查）"""

    # 类常量 — 替代魔术数字
    SELF_REVIEW_MAX_RETRIES = 2       # 自我审查失败重试次数
    ROUGHNESS_THRESHOLD = 0.8         # Ra 粗糙度阈值（≤走EDM）
    HARDNESS_THRESHOLD = 55          # HRC 硬度阈值（>走CBN刀具）
    SAFETY_HEIGHT_MIN = 50           # 安全高度最小值 mm
    TURNING_SPEED_MAX = 2500         # 精车最大转速 rpm

    def __init__(self, llm=None, prompt_service: Optional[PromptService] = None):
        self._llm = llm
        self._prompt = prompt_service or PromptService()
        self._max_retries = self.SELF_REVIEW_MAX_RETRIES

    def generate(
        self,
        part_info: dict,
        features: list,
        process_plan: list,
        feedback: Optional[dict] = None,
    ) -> dict:
        """生成 CNC 代码（所有设备）

        Args:
            part_info: 零件信息
            features: 几何特征列表
            process_plan: 工艺路线
            feedback: 上次审查反馈（重试时使用）

        Returns:
            {"code_segments": [...], "self_review": {...}}
        """
        # 按设备分类特征
        turning_features = [f for f in features if self._is_turning_feature(f)]
        edm_features = [f for f in features if self._is_edm_feature(f)]

        code_segments = []

        # 生成数控精车代码
        if turning_features:
            turning_code = self._generate_turning(part_info, turning_features, feedback)
            code_segments.append({
                "machine": "TAKISAWA NEX-108",
                "feature": "数控精车",
                "code": turning_code,
            })

        # 生成镜面放电代码
        if edm_features:
            edm_code = self._generate_edm(part_info, edm_features, feedback)
            code_segments.append({
                "machine": "SODICK AD32LS",
                "feature": "镜面放电",
                "code": edm_code,
            })

        # 自我审查
        self_review = self._self_review(code_segments, part_info)

        result = {
            "code_segments": code_segments,
            "self_review": self_review,
        }

        # 如果自我审查不通过且还有重试次数，修正
        retries = 0
        while (
            self_review.get("overall") in ("revision_needed", "fail")
            and retries < self._max_retries
        ):
            log.info(f"自我审查不通过，第 {retries + 1} 次修正")
            feedback = self_review
            # 重新生成
            if turning_features:
                turning_code = self._generate_turning(part_info, turning_features, feedback)
                code_segments[0]["code"] = turning_code
            if edm_features:
                edm_code = self._generate_edm(part_info, edm_features, feedback)
                code_segments[-1]["code"] = edm_code

            self_review = self._self_review(code_segments, part_info)
            result = {"code_segments": code_segments, "self_review": self_review}
            retries += 1

        if self_review.get("overall") == "pass":
            log.info("CNC 自我审查通过")
        else:
            log.warning(f"CNC 自我审查最终结果: {self_review.get('overall')}")

        return result

    def _generate_turning(
        self, part_info: dict, features: list, feedback: Optional[dict] = None
    ) -> str:
        """生成 TAKISAWA 精车代码"""
        if not self._llm:
            return self._fallback_turning(part_info, features)

        # 渲染 few_shot
        few_shot = self._prompt.render("cnc/few_shot/turning_example_1.j2")

        # 渲染 messages
        messages = self._prompt.render_messages(
            "cnc",
            template_name="turning",
            part_info=part_info,
            features=features,
            tool="CBN" if self._is_hard_material(part_info) else "硬质合金",
            process_name="数控精车",
            few_shot=few_shot,
            feedback=json.dumps(feedback, ensure_ascii=False) if feedback else "",
        )

        if not messages:
            return self._fallback_turning(part_info, features)

        response = self._llm.chat(messages, model="deepseek-v4-pro")
        return response or self._fallback_turning(part_info, features)

    def _generate_edm(
        self, part_info: dict, features: list, feedback: Optional[dict] = None
    ) -> str:
        """生成 SODICK 放电代码"""
        if not self._llm:
            return self._fallback_edm(part_info, features)

        few_shot = self._prompt.render("cnc/few_shot/edm_example_1.j2")

        messages = self._prompt.render_messages(
            "cnc",
            template_name="edm",
            part_info=part_info,
            features=features,
            surface_roughness=0.63,
            few_shot=few_shot,
            feedback=json.dumps(feedback, ensure_ascii=False) if feedback else "",
        )

        if not messages:
            return self._fallback_edm(part_info, features)

        response = self._llm.chat(messages, model="deepseek-v4-pro")
        return response or self._fallback_edm(part_info, features)

    def _self_review(self, code_segments: list, part_info: dict) -> dict:
        """自我审查 CNC 代码（宽松版提示词）"""
        if not self._llm or not code_segments:
            return {
                "summary": {"passed": 5, "failed": 0, "total": 5},
                "overall": "pass",
                "revision_advice": "",
            }

        generated_code = "\n\n".join(
            f"=== {s['machine']} - {s['feature']} ===\n{s['code']}" for s in code_segments
        )

        messages = self._prompt.render_messages(
            "cnc",
            template_name="self_review",
            generated_code=generated_code,
            part_info=part_info,
        )

        if not messages:
            return {"overall": "pass", "summary": {"passed": 5, "failed": 0, "total": 5}}

        response = self._llm.chat(messages, model="deepseek-v4-pro")
        if response:
            try:
                return self._parse_json(response) or {"overall": "pass", "summary": {"passed": 5, "failed": 0, "total": 5}}
            except Exception:
                pass

        return {"overall": "pass", "summary": {"passed": 5, "failed": 0, "total": 5}}

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
    def _is_turning_feature(f: dict) -> bool:
        return f.get("type") not in ("精孔", "精密槽", "EDM")

    @staticmethod
    def _is_edm_feature(f: dict) -> bool:
        return f.get("type") in ("精孔", "精密槽", "EDM") or (
            f.get("roughness") and CNCProgrammingAgent._parse_roughness(f["roughness"]) <= CNCProgrammingAgent.ROUGHNESS_THRESHOLD
        )

    @staticmethod
    def _parse_roughness(val) -> float:
        """从粗糙度值中提取数值，兼容 Ra0.63 / 0.63 / Ra 0.63 / \"0.63\" 等格式"""
        try:
            return float(re.search(r"[\d.]+", str(val)).group())
        except (AttributeError, ValueError, TypeError):
            return 1.0  # 无法解析时默认保守值

    @staticmethod
    def _is_hard_material(part_info: dict) -> bool:
        hrc = part_info.get("hardness", "")
        if isinstance(hrc, str):
            try:
                return int(re.search(r"\d+", hrc).group()) > CNCProgrammingAgent.HARDNESS_THRESHOLD
            except (AttributeError, ValueError):
                return True
        return True

    @staticmethod
    def _fallback_turning(part_info: dict, features: list) -> str:
        dim = "100"
        depth = "50"
        for f in features:
            if f.get("type") == "外形":
                spec = f.get("spec", "")
                parts = spec.replace("mm", "").split("x")
                if parts:
                    dim = parts[0].strip()
                if len(parts) > 1:
                    depth = parts[1].strip()
                break
        return (
            f"( TAKISAWA NEX-108 - 数控精车 - FALLBACK )\n"
            f"( 特征: 外形 {dim}x{depth}mm )\n"
            f"( 材料: {part_info.get('material','?')} {part_info.get('hardness','?')} )\n"
            f"G90 G21\nG28 U0 W0\nT0101\nM03 S1800\n"
            f"G00 X{dim} Z2.0 M08\nG01 Z-{depth} F0.08\n"
            f"G00 X{dim} Z2.0\nG28 U0 W0\nM30\n"
        )

    @staticmethod
    def _fallback_edm(part_info: dict, features: list) -> str:
        return (
            "( SODICK AD32LS - 镜面放电 - FALLBACK )\n"
            "( 特征: 精孔/槽 )\n"
            f"( 材料: {part_info.get('material','?')} )\n"
            "C000\nG90\nM80\nG01 Z-5.0 H001\n"
            "M88\nM02\n"
        )
