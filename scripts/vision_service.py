#!/usr/bin/env python3
"""视觉分析服务 — 图纸扫描、视觉分析、缓存管理

从 fill_by_vision.py 提取，职责单一：
1. 扫描图纸目录，提取生产单号和零件号
2. 调用阿里百炼视觉分析 + 工艺推理
3. 保存/加载分析缓存
"""

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.llm_client import LLMClient
from workflows.erp_process.agents.vision_agent import VisionAgent
from workflows.erp_process.process_reasoning import reason_process, map_to_erp_processes

log = logging.getLogger("vision_service")


# ─── 文件名工具 ─────────────────────────────────────

def extract_prod_no(filename: str) -> tuple[str, Optional[str]]:
    """从文件名提取生产单号和零件号

    "C03026051501-001.pdf" → ("C03026051501", "001")
    "W20126051401.pdf"    → ("W20126051401", None)
    """
    stem = Path(filename).stem
    if "-" in stem:
        idx = stem.index("-")
        return stem[:idx], stem[idx + 1:]
    return stem, None


def scan_drawings(drawings_dir: str) -> dict:
    """扫描图纸目录，返回 { prod_no: {part_no: pdf_path} }

    同名文件，有后缀和无后缀同时存在时，警告并优先使用带后缀的。
    """
    result = defaultdict(dict)
    dir_path = Path(drawings_dir)
    if not dir_path.is_dir():
        raise ValueError(f"图纸目录不存在: {drawings_dir}")

    for f in sorted(dir_path.glob("*.pdf")):
        prod_no, part_no = extract_prod_no(str(f))
        key = part_no  # None 在 dict 中也是合法key
        if key in result[prod_no]:
            log.warning(f"⚠ 同名冲突: {prod_no} 已存在 part={key}, 被 {f.name} 覆盖")
        result[prod_no][part_no] = str(f)

    log.info(f"扫描图纸: {len(result)} 个生产单, 共 {sum(len(v) for v in result.values())} 张图纸")
    for pn, parts in result.items():
        labels = [k if k else "(无零件号)" for k in parts]
        log.info(f"  {pn}: {labels}")
    return dict(result)


# ─── 分析缓存 ──────────────────────────────────────

CACHE_DIR = Path(__file__).resolve().parent.parent / "data"


def save_analysis_cache(prod_no: str, part_no: str, part_info: dict,
                        features: list, special_reqs: list):
    """保存视觉分析结果到缓存文件，供 CNC pipeline 读取"""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / f"analysis_cache_{prod_no}.json"
    entry = {
        "part_no": part_no,
        "part_info": part_info,
        "features": features,
        "special_reqs": special_reqs,
    }
    if cache_path.exists():
        with open(cache_path) as f:
            existing = json.load(f)
    else:
        existing = []
    existing = [e for e in existing if e.get("part_no") != part_no]
    existing.append(entry)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    log.info(f"  ✓ 分析缓存已保存: {cache_path.name}")


def load_analysis_cache(prod_no: str) -> list:
    """从分析缓存加载数据"""
    cache_path = CACHE_DIR / f"analysis_cache_{prod_no}.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"找不到分析缓存: {cache_path}\n"
            f"请先运行 fill_by_vision.py 或 vision_service.analyze_batch()"
        )
    with open(cache_path) as f:
        return json.load(f)


# ─── 视觉分析+推理 ─────────────────────────────────

class VisionService:
    """视觉分析服务 — 封装阿里百炼视觉分析 + 工艺推理"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        if not self.api_key:
            log.warning("DASHSCOPE_API_KEY 未配置，视觉分析将失败")
        self._llm = None
        self._vision = None

    @property
    def llm(self):
        if self._llm is None:
            self._llm = LLMClient(api_key=self.api_key)
        return self._llm

    @property
    def vision(self):
        if self._vision is None:
            self._vision = VisionAgent(llm=self.llm)
        return self._vision

    def analyze_single(self, pdf_path: str, label: str = None) -> tuple:
        """分析单张图纸，返回 (part_info, features, special_reqs)

        Args:
            pdf_path: PDF图纸路径
            label: 日志标签（如 "C03026051501-001"）

        Returns:
            (part_info, features, special_reqs)
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"图纸不存在: {pdf_path}")

        label = label or path.stem
        log.info(f"[视觉] {label}")

        vision_result = self.vision.analyze(drawing_path=pdf_path, prod_no=label)
        part_info = vision_result.get("part_info", {})
        features = vision_result.get("features", [])
        special_reqs = vision_result.get("special_requirements", [])

        return part_info, features, special_reqs

    def analyze_and_reason(self, pdf_path: str, label: str = None) -> dict:
        """分析图纸 + 工艺推理，返回 {part_info, features, special_reqs, process_plan}"""
        part_info, features, special_reqs = self.analyze_single(pdf_path, label)

        log.info(f"  零件: {part_info.get('name','?')}, "
                 f"材料: {part_info.get('material','?')}, "
                 f"特征: {len(features)}个")

        full_plan = reason_process(part_info, features, special_reqs)
        process_plan = map_to_erp_processes(full_plan)

        log.info(f"  工序: {[p['name'] for p in process_plan]}, "
                 f"共{len(process_plan)}道")

        return {
            "part_info": part_info,
            "features": features,
            "special_reqs": special_reqs,
            "process_plan": process_plan,
        }

    def analyze_batch(self, drawings: dict, cache: bool = True,
                       skip_errors: bool = True) -> dict:
        """批量分析图纸，可选保存缓存，可选跳过失败零件

        Args:
            drawings: { prod_no: {part_no: pdf_path} }
            cache: 是否保存分析缓存到文件
            skip_errors: True=跳过失败零件继续处理, False=失败即终止

        Returns:
            { prod_no: {part_no: process_plan} }
        """
        plans = {}
        total = sum(len(parts) for parts in drawings.values())
        done = 0
        errors = []

        for prod_no, parts in drawings.items():
            plans[prod_no] = {}
            for part_no, pdf_path in parts.items():
                done += 1
                label = f"{prod_no}-{part_no}" if part_no else prod_no

                try:
                    result = self.analyze_and_reason(pdf_path, label)
                    plans[prod_no][part_no] = result["process_plan"]

                    if cache:
                        save_analysis_cache(
                            prod_no, part_no,
                            result["part_info"],
                            result["features"],
                            result["special_reqs"],
                        )

                except Exception as e:
                    error_msg = f"[视觉 {done}/{total}] {label} 失败: {e}"
                    log.error(error_msg)
                    errors.append(error_msg)
                    if not skip_errors:
                        raise

        if errors:
            log.warning(f"批量分析完成，{len(errors)}/{total} 个错误")
            for err in errors:
                log.warning(f"  - {err}")

        return plans
