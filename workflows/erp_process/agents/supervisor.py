"""主Agent — 监督调度

职责：协调识图/编程/审核三个子Agent，循环修正直到审核通过
"""

import copy
import json
import logging
import re
from typing import Optional

from services.prompt_service import PromptService
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("agent.supervisor")


class SupervisorAgent:
    """主控调度Agent"""

    # 类常量
    MAX_RETRIES = 3                   # 审核不通过最大重试次数
    LOOP_TIMEOUT_SECONDS = 600        # 多Agent编排总超时（含LLM调用）

    def __init__(self, llm=None, prompt_service: Optional[PromptService] = None):
        self._llm = llm
        self._prompt = prompt_service or PromptService()
        self._max_retries = self.MAX_RETRIES

        # 延迟导入避免循环依赖
        self._vision = None
        self._cnc = None
        self._review = None

    @property
    def vision(self):
        if self._vision is None:
            from workflows.erp_process.agents.vision_agent import VisionAgent
            self._vision = VisionAgent(llm=self._llm, prompt_service=self._prompt)
        return self._vision

    @property
    def cnc(self):
        if self._cnc is None:
            from workflows.erp_process.agents.cnc_agent import CNCProgrammingAgent
            self._cnc = CNCProgrammingAgent(llm=self._llm, prompt_service=self._prompt)
        return self._cnc

    @property
    def review(self):
        if self._review is None:
            from workflows.erp_process.agents.review_agent import ReviewAgent
            self._review = ReviewAgent(llm=self._llm, prompt_service=self._prompt)
        return self._review

    def run(self, state: dict) -> dict:
        """执行多Agent编排

        Args:
            state: 当前工作流状态

        Returns:
            更新后的状态（含 part_info, features, process_plan, cnc_code）
        """
        import time as _time
        _start = _time.time()
        log.info("=== 主Agent开始执行 ===")

        prod_no = state.get("prod_no", "")
        drawing_path = state.get("drawing_local_path") or state.get("drawing_url", "")
        input_data = state.get("input", {})

        def _check_timeout():
            """超时检查"""
            if _time.time() - _start > self.LOOP_TIMEOUT_SECONDS:
                log.warning(f"多Agent编排超过 {self.LOOP_TIMEOUT_SECONDS}s 超时，使用当前已生成的成果")
                return True
            return False

        # ── Step 1: 识图Agent分析图纸 ──
        log.info("Step 1: 识图Agent 分析图纸")
        vision_result = self.vision.analyze(
            drawing_path=drawing_path,
            prod_no=prod_no,
        )

        part_info = vision_result.get("part_info", {})
        features = vision_result.get("features", [])
        special_reqs = vision_result.get("special_requirements", [])

        log.info(
            f"  零件: {part_info.get('name','')}, "
            f"材料: {part_info.get('material','')}, "
            f"特征: {len(features)}个"
        )

        # ── Step 2: 工艺推理（五层规则引擎，同V2） ──
        log.info("Step 2: 工艺推理（五层规则）")
        process_plan = self._reason_process(part_info, features, special_reqs)
        log.info(f"  工艺路线: {len(process_plan)}道工序")

        # ── Step 3: 编程Agent生成CNC代码 + 自我审查 ──
        log.info("Step 3: 编程Agent 生成CNC代码")
        cnc_result = self.cnc.generate(
            part_info=part_info,
            features=features,
            process_plan=process_plan,
        )
        log.info(
            f"  代码段: {len(cnc_result.get('code_segments', []))}段, "
            f"自我审查: {cnc_result.get('self_review', {}).get('overall', '?')}"
        )

        # ── Step 4: 审核Agent交叉审查 ──
        log.info("Step 4: 审核Agent 交叉审查")
        review_result = self.review.check(
            vision_output=vision_result,
            cnc_output=cnc_result,
            part_info=part_info,
        )

        # ── Step 5: 循环修正 ──
        retry_count = 0
        while (
            review_result.get("final_verdict") in ("revision_needed", "reject")
            and retry_count < self._max_retries
        ):
            retry_count += 1
            log.info(
                f"Step 5.{retry_count}: 审核不通过 "
                f"({review_result.get('final_verdict')}), 第{retry_count}次修正"
            )

            # 根据审核反馈修正CNC代码
            cnc_feedback = {
                "vision_review": review_result.get("vision_review", {}),
                "cnc_review": review_result.get("cnc_review", {}),
            }

            cnc_result = self.cnc.generate(
                part_info=part_info,
                features=features,
                process_plan=process_plan,
                feedback=cnc_feedback,
            )

            # 超时检查
            if _check_timeout():
                break

            # 重新审查
            review_result = self.review.check(
                vision_output=vision_result,
                cnc_output=cnc_result,
                part_info=part_info,
            )

        final_verdict = review_result.get("final_verdict", "approve")
        log.info(f"  审核最终结论: {final_verdict}, 修正轮次: {retry_count}")

        # ── Step 6: 组装最终输出 ──
        takisawa_code = ""
        sodick_params = {}
        feature_code_map = {}

        for seg in cnc_result.get("code_segments", []):
            machine = seg.get("machine", "")
            ftype = seg.get("feature", "")
            code_text = seg.get("code", "")
            if "TAKISAWA" in machine or "takisawa" in machine.lower():
                takisawa_code = code_text
            elif "SODICK" in machine or "sodick" in machine.lower():
                sodick_params = {
                    "machine": machine,
                    "code": code_text,
                }
            # 构建 feature_code_map
            if ftype:
                feature_code_map[ftype] = {
                    "machine": machine,
                    "code": code_text[:200],  # 摘要
                }

        # 也按特征构建映射（从 features 列表映射到代码段）
        for f in (features or []):
            ftype = f.get("type", "")
            if ftype and ftype not in feature_code_map:
                # 根据特征类型匹配机床
                if ftype in ("精孔", "精密槽", "EDM") or (
                    f.get("roughness") and float(re.search(r"[\d.]+", str(f["roughness"])).group() or "1") <= 0.8
                ):
                    feature_code_map[ftype] = {"machine": "SODICK AD32LS", "code": sodick_params.get("code", "")[:200]}
                else:
                    feature_code_map[ftype] = {"machine": "TAKISAWA NEX-108", "code": takisawa_code[:200]}

        return {
            "part_info": part_info,
            "features": features,
            "process_plan": process_plan,
            "drawing_local_path": drawing_path,  # 透传图纸路径给 Phase 3 上传
            "drawing_url": state.get("drawing_url"),  # 透传飞书URL
            "cnc_code": {
                "takisawa_nex108": takisawa_code,
                "sodick_ad32ls": sodick_params,
                "segments": cnc_result.get("code_segments", []),
                "feature_code_map": feature_code_map,
                "quality_report": {
                    "vision_confidence": vision_result.get("confidence", 0),
                    "cnc_self_review": cnc_result.get("self_review", {}).get("overall", "?"),
                    "cross_review_verdict": final_verdict,
                    "retry_count": retry_count,
                },
            },
            "checkpoint": Checkpoint.CNC_GENERATED,
        }

    def _reason_process(
        self, part_info: dict, features: list, special_reqs: list
    ) -> list:
        """五层工艺推理（同V2逻辑，规则引擎）"""
        shape = part_info.get("shape", "square")
        material = part_info.get("material", "K490")

        # 形状决策
        if shape in ("square", "flat"):
            plan = copy.deepcopy(_SQUARE_TEMPLATE)
        elif shape in ("round", "cylindrical"):
            plan = copy.deepcopy(_ROUND_TEMPLATE)
        else:
            plan = copy.deepcopy(_SQUARE_TEMPLATE)

        # 特殊要求注入
        has_sharp_edge = any("sharp" in str(s).lower() or "利角" in str(s) for s in special_reqs)
        has_sharp_feature = any(
            f.get("type") == "利角" or "sharp" in str(f.get("note", "")).lower()
            for f in (features or [])
        )

        if has_sharp_edge or has_sharp_feature:
            plan.append({
                "seq": 99,
                "name": "⚠️ 注意事项",
                "task": "利角 — 严禁倒角，研磨去毛刺保刃口",
                "check": "刃口锋利度",
                "meta_step": True,
            })

        log.info(f"工艺推理: shape={shape}, material={material}, plan={len(plan)}步")
        return plan


# ── 固定工艺模板（同V2） ──

_SQUARE_TEMPLATE = [
    {"seq": 1, "name": "铣床", "equipment": "JINGDIAO铣床", "task": "开粗;孔;牙", "check": "余量;孔;牙"},
    {"seq": 2, "name": "CNC 1", "equipment": "JINGDIAO精雕", "task": "开粗", "check": "余量"},
    {"seq": 3, "name": "热处理", "equipment": "外协", "task": "58-63HRC", "check": "按要求"},
    {"seq": 4, "name": "快丝", "equipment": "快走丝", "task": "开粗;外形", "check": "余量"},
    {"seq": 5, "name": "大水磨", "equipment": "OKAMOTO Sam-450", "task": "磨六面", "check": "直角;余量"},
    {"seq": 6, "name": "检测", "equipment": "ZEISS CMM", "task": "外形/直角", "check": "图纸尺寸"},
    {"seq": 7, "name": "小磨床", "equipment": "HOTMAN", "task": "调直角;外形", "check": "直角;余量"},
    {"seq": 8, "name": "CNC 2", "equipment": "JINGDIAO精雕", "task": "精加工", "check": "中心;数值"},
    {"seq": 9, "name": "小磨床", "equipment": "HOTMAN", "task": "调变形", "check": "直角;尺寸"},
    {"seq": 10, "name": "慢丝", "equipment": "慢走丝", "task": "割精密孔", "check": "孔径公差"},
    {"seq": 11, "name": "EDM", "equipment": "SODICK AD32LS", "task": "孔;槽镜面", "check": "中心;损耗"},
    {"seq": 12, "name": "抛光", "equipment": "手工", "task": "黄色面2000#", "check": "按标准"},
    {"seq": 13, "name": "总检", "equipment": "ZEISS CMM", "task": "全尺寸", "check": "按公差"},
    {"seq": 14, "name": "TiN涂层", "equipment": "外协", "task": "表面处理", "check": "颜色;厚度"},
]

_ROUND_TEMPLATE = [
    {"seq": 1, "name": "车床", "equipment": "TAKISAWA NEX-108", "task": "开粗;留余量", "check": "余量"},
    {"seq": 2, "name": "热处理", "equipment": "外协", "task": "热处理", "check": "按要求"},
    {"seq": 3, "name": "外圆磨", "equipment": "OKAMOTO", "task": "磨外圆;基准", "check": "直角;尺寸"},
    {"seq": 4, "name": "CNC精车", "equipment": "TAKISAWA NEX-108", "task": "精加工", "check": "中心;数值"},
    {"seq": 5, "name": "EDM", "equipment": "SODICK AD32LS", "task": "孔;槽镜面", "check": "中心;损耗"},
    {"seq": 6, "name": "抛光", "equipment": "手工", "task": "抛光", "check": "按标准"},
    {"seq": 7, "name": "总检", "equipment": "ZEISS CMM", "task": "全尺寸", "check": "按公差"},
    {"seq": 8, "name": "涂层", "equipment": "外协", "task": "表面处理", "check": "按要求"},
]
