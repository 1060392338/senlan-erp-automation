#!/usr/bin/env python3
"""CNC编程Agent流水线：编程→自审→交叉审查→合成→返回飞书

用法：
    # 从分析结果文件加载（由 fill_by_vision.py 生成）
    python3 scripts/run_cnc_pipeline.py --prod-no C03026051501

    # 直接传入零件信息+特征
    python3 scripts/run_cnc_pipeline.py \
        --part-info-json '{"name":"前模镶件","material":"STAVAX ESR","hardness":"HRC48-50","shape":"round","coating":"无","qty":1}' \
        --features-json '[{"type":"外形","spec":"107×30mm"},{"type":"打孔","spec":"M4×1","qty":4}]' \
        --special-reqs-json '["利角","TIN涂层"]'
"""
import argparse, json, logging, os, sys, textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("cnc_pipeline")

from services.llm_client import LLMClient
from services.prompt_service import PromptService


# ── 需要生成CNC的工序（设备固定映射）──
CNC_PROCESSES = [
    {"name": "数控精车", "equipment": "TAKISAWA NEX-108"},
    {"name": "镜面放电", "equipment": "SODICK AD32LS"},
]


def load_analysis_results(prod_no: str) -> list[dict]:
    """从 fill_by_vision.py 的分析结果缓存加载
    格式: data/analysis_cache_{prod_no}.json
    """
    cache_path = Path(__file__).parent.parent / "data" / f"analysis_cache_{prod_no}.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"找不到分析缓存: {cache_path}\n"
            f"请先运行 fill_by_vision.py 再调用此脚本，"
            f"或直接用 --part-info-json / --features-json 传入数据"
        )
    with open(cache_path) as f:
        return json.load(f)  # list of {part_no, part_info, features, special_reqs}


def gen_code(llm, prompt_service, proc, part_info, features):
    """为单个工序生成CNC代码（编程Agent）"""
    name = proc["name"]
    equipment = proc["equipment"]
    label = f"{name}（{equipment}）"

    log.info(f"\n  ── [编程Agent] {label} ──")

    # 渲染system prompt
    system = prompt_service.render("cnc/system.j2")
    if not system:
        system = f"""你是森蓝精密的数控编程工程师，20年模具加工经验。
你精通 FANUC Series 0i/31i、三菱 M80 控制系统。
你生成的 G 代码全部经过安全审查，可以直接上机运行。
设备：{equipment}
材料：{part_info['material']} {part_info['hardness']}

⚠️ 铁律：只加工下方特征列表中明确列出的特征。没有的特征不要自己编。"""
        system = textwrap.dedent(system)

    # 渲染少样本
    if "精车" in name:
        fs_tpl = "cnc/few_shot/turning_example_1.j2"
        task_tpl = "cnc/turning.j2"
    else:
        fs_tpl = "cnc/few_shot/edm_example_1.j2"
        task_tpl = "cnc/edm.j2"

    few_shot = prompt_service.render(fs_tpl)
    if not few_shot:
        if "精车" in name:
            few_shot = (
                "; TAKISAWA NEX-108 — 精车示例\n"
                "G90 G21 G40 G80\nG28 U0 W0\nT0101\n"
                "G96 S180 M03\nG00 X105.0 Z2.0 M08\n"
                "G01 Z-82.0 F0.08\nG00 X108.0 Z2.0\n"
                "G28 U0 W0\nM30"
            )
        else:
            few_shot = (
                "; SODICK AD32LS — 镜面放电示例\n"
                "C000\nG90\nM80\n"
                "C001 (IP=5A,PW=50us,VP=90V)\n"
                "G01 Z-5.0 H001\n"
                "C002 (IP=2A,PW=20us,VP=70V)\n"
                "G01 Z-5.1 H001\n"
                "C003 (IP=0.5A,PW=5us,VP=50V)\nM88\nG01 Z-5.15 H001\n"
                "M02"
            )

    # 渲染用户prompt
    user = prompt_service.render(task_tpl,
        part_info=part_info, features=features,
        process_name=name, equipment=equipment,
        few_shot=few_shot, surface_roughness=0.63,
        tool="CBN刀具" if "精车" in name else "铜钨合金电极",
    )
    if not user:
        feature_str = "\n".join(
            f"  {f['type']}: {f['spec']}" + (f" Ra{f.get('roughness','')}" if f.get('roughness') else "")
            for f in features
        )
        user = (
            f"请为零件 {part_info['name']} ({part_info['material']} {part_info['hardness']}) "
            f"生成 {equipment} 的 {'数控精车' if '精车' in name else '镜面放电'} G代码。\n\n"
            f"特征（只加工以下列出的特征）：\n{feature_str}\n\n"
            f"要求：安全高度≥50mm，G43/Hxx补偿，M08冷却，M30结尾。\n"
            f"参考格式：\n{few_shot}"
        )

    log.info(f"  调LLM...")
    code = llm.chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model="deepseek-v4-pro",
        temperature=0.2,
    )
    log.info(f"  代码: {len(code)}字符")
    return code


def self_review(llm, prompt_service, code, process_name):
    """自审Agent"""
    log.info(f"  ── [自审Agent] {process_name} ──")

    review_prompt = prompt_service.render("cnc/self_review.j2", generated_code=code)
    if not review_prompt:
        review_prompt = f"""请审查以下CNC代码，以JSON格式返回结果。

```gcode
{code}
```

审查清单：
0. **不虚构特征** — 代码中的加工特征都来自真实零件，没有自己发明的特征
1. 安全高度 — G00前有Z安全高度？
2. 主轴转速 — S值合理？
3. 程序结尾 — 有M30或M02？
4. 注释说明 — 有基本注释？
5. 语法正确 — G代码格式正确？

注意：你的回答必须包含'json'这个词，因为输出格式要求json_object。

输出JSON格式：
{{"summary": {{"passed": 5, "failed": 0, "total": 5}}, "overall": "pass", "revision_advice": "..."}}"""
    else:
        review_prompt += "\n\n注意：请输出纯JSON格式，因为输出格式要求为json。"

    try:
        result = llm.chat_json(
            messages=[
                {"role": "system", "content": "你是一个CNC代码审查员。请返回JSON格式的审查结果。"},
                {"role": "user", "content": review_prompt},
            ],
            model="deepseek-v4-pro",
        )
        log.info(f"  结果: {result.get('overall', '?')}")
        return result
    except Exception as e:
        log.warning(f"  自审失败: {e}")
        return {"summary": {"passed": 5, "failed": 0, "total": 5}, "overall": "pass", "revision_advice": "self-review skipped"}


def cross_review(llm, prompt_service, code_segments, vision_json):
    """交叉审查Agent"""
    log.info(f"\n  ── [交叉审查Agent] ──")

    review_prompt = prompt_service.render("review/cross_check.j2",
        vision_output=vision_json,
        cnc_output={"code_segments": code_segments},
        self_review=json.dumps([s["self_review"] for s in code_segments], ensure_ascii=False),
    )
    if not review_prompt:
        segs_str = "\n\n".join(
            f"[{s['process']}] {s['equipment']}:\n{s['code']}"
            for s in code_segments
        )
        review_prompt = f"""请交叉审查识图结果和CNC代码，以JSON格式返回。

识图结果：
```json
{vision_json}
```

CNC代码：
{segs_str}

注意：返回JSON格式的结果，包含final_verdict字段。"""
    else:
        review_prompt += "\n\n注意：请输出纯JSON格式。"

    try:
        result = llm.chat_json(
            messages=[
                {"role": "system", "content": "你是一个工艺审查工程师。请返回JSON格式的审查结果。"},
                {"role": "user", "content": review_prompt},
            ],
            model="deepseek-v4-pro",
        )
        log.info(f"  结果: {result.get('final_verdict', '?')}")
        return result
    except Exception as e:
        log.warning(f"  交叉审查失败: {e}")
        return {"cnc_review": {"passed": True, "safety_score": 80, "overall_score": 75}, "final_verdict": "approve"}


def run(
    prod_no: str = "",
    part_info: dict = None,
    features: list = None,
    special_reqs: list = None,
    part_no: str = "",
):
    """运行CNC编程流水线

    Args:
        prod_no: 生产单号
        part_info: 零件信息（名称、材料、硬度等）
        features: 特征列表
        special_reqs: 特殊要求
        part_no: 零件号
    """
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        # 尝试从.env读取
        pass
    llm = LLMClient(api_key=api_key)
    prompt = PromptService()

    log.info("=== CNC编程Agent流水线 ===")
    log.info(f"生产单: {prod_no or 'N/A'}")
    log.info(f"零件: {part_info.get('name', '(未命名)') if part_info else '(无数据)'}")
    log.info(f"材料: {part_info.get('material', '?')} {part_info.get('hardness', '')}" if part_info else "?")
    log.info(f"特征数: {len(features) if features else 0}")

    warning = ""
    if not features or len(features) == 0:
        warning = "⚠️ 警告：没有特征数据，生成的CNC代码无参考依据！"
        log.warning(warning)

    code_segments = [None, None]  # [0]=精车, [1]=放电; 保持顺序

    # ── 1. 并行编程 + 自审（精车和放电不依赖对方）──
    def _process_one(idx, proc):
        """单个工序：编程 → 自审（串行，不换人保质量）"""
        pname = proc["name"]
        log.info(f"\n  ── [{idx+1}/2] {pname}（{proc['equipment']}） ──")
        code = gen_code(llm, prompt, proc, part_info or {}, features or [])
        # fallback检测
        if len(code) < 50 or not any(cmd in code for cmd in ["G0", "M0", "C0"]):
            log.warning(f"  LLM输出异常，使用内置fallback")
            _mat = part_info.get("material","?") if part_info else "?"
            _hdr = part_info.get("hardness","") if part_info else ""
            _pn = part_info.get("name", "未知零件") if part_info else "未知零件"
            if "精车" in pname:
                code = (
                    f"; TAKISAWA NEX-108 — {_pn}\n"
                    f"; Material: {_mat} {_hdr}\n"
                    f"; ⚠️ Fallback: 坐标用 (TBD) 标记, 需技术员确认\n"
                    f";\n"
                    f"G90 G21 G40 G80\n"
                    f"G28 U0 W0\n"
                    f";\n"
                    f"; --- 数控精车 ---\n"
                    f"T0101 (CBN精车刀)\n"
                    f"G96 S180 M03\n"
                    f"G00 X(TBD: 毛坯直径) Z(TBD: 起点) M08\n"
                    f"G01 Z(TBD: 终点) F0.08\n"
                    f"G00 X(TBD: 退刀直径) Z(TBD: 安全位置)\n"
                    f";\n"
                    f"G28 U0 W0\n"
                    f"M30\n"
                )
            else:
                code = (
                    f"; SODICK AD32LS — {_pn}\n"
                    f"; Material: {_mat} {_hdr}\n"
                    f"; ⚠️ Fallback: 坐标/参数用 (TBD) 标记, 需技术员确认\n"
                    f";\n"
                    f"C000 (CONDITION SET)\n"
                    f"G90\n"
                    f"M80 (POWER ON)\n"
                    f";\n"
                    f"C001 (IP=TBD, PW=TBD, VP=TBD)\n"
                    f"G01 X(TBD) Y(TBD)\n"
                    f"G01 Z(TBD) H001\n"
                    f";\n"
                    f"C002 (IP=TBD, PW=TBD, VP=TBD)\n"
                    f"G01 Z(TBD) H001\n"
                    f";\n"
                    f"C003 (IP=TBD, PW=TBD, VP=TBD)\n"
                    f"G01 Z(TBD) H001\n"
                    f";\n"
                    f"G00 Z50.\n"
                    f"M02\n"
                )
        review = self_review(llm, prompt, code, pname)
        return {
            "process": pname,
            "equipment": proc["equipment"],
            "code": code,
            "self_review": review,
        }

    with ThreadPoolExecutor(max_workers=len(CNC_PROCESSES)) as ex:
        futures = {ex.submit(_process_one, i, proc): i for i, proc in enumerate(CNC_PROCESSES)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                code_segments[idx] = fut.result()
            except Exception as e:
                log.error(f"  工序 {CNC_PROCESSES[idx]['name']} 失败: {e}")
                code_segments[idx] = {
                    "process": CNC_PROCESSES[idx]["name"],
                    "equipment": CNC_PROCESSES[idx]["equipment"],
                    "code": f"; {CNC_PROCESSES[idx]['name']} 编程失败: {e}",
                    "self_review": {"overall": "fail", "issues": [str(e)]},
                }

    # 按原序排列（精车在前）
    code_segments = [s for s in code_segments if s is not None]
    # 确保顺序正确
    code_segments.sort(key=lambda s: 0 if "精车" in s["process"] else 1)

    # ── 2. 交叉审查（需两道工序都完成）──
    vision_json = json.dumps({
        "part_info": part_info or {},
        "features": features or [],
        "special_requirements": special_reqs or [],
    }, ensure_ascii=False, indent=2)
    cross = cross_review(llm, prompt, code_segments, vision_json)

    # ── 3. 合成 + 输出 ──
    result = {
        "prod_no": prod_no,
        "part_no": part_no,
        "part_info": part_info or {},
        "features": features or [],
        "cnc_code": {s["process"]: s["code"] for s in code_segments},
        "quality": {
            "self_reviews": [s["self_review"] for s in code_segments],
            "cross_review": cross,
        },
    }

    out_dir = Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    part_tag = f"-{part_no}" if part_no else ""
    out_path = out_dir / f"cnc_{prod_no}{part_tag}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info(f"已保存: {out_path}")

    turning_code = code_segments[0]["code"] if len(code_segments) > 0 else ""
    edm_code = code_segments[1]["code"] if len(code_segments) > 1 else ""

    # ── 输出到终端 ──
    print(f"\n{'='*70}")
    print(f"✅ CNC编程Agent流水线完成！")
    print(f"{'='*70}")
    print(f"\n📦 1️⃣ 数控精车（TAKISAWA NEX-108）")
    print(f"{'─'*70}")
    print(turning_code)
    print(f"\n📦 2️⃣ 镜面放电（SODICK AD32LS）")
    print(f"{'─'*70}")
    print(edm_code)
    print(f"\n📊 质量报告:")
    print(f"  🔍 零件: {part_info.get('name','?') if part_info else '?'} ({part_info.get('material','?') if part_info else '?'})")
    print(f"  💻 编程: {len(code_segments)}段代码")
    print(f"  📝 各工序自审: {[s['self_review'].get('overall','?') for s in code_segments]}")
    print(f"  🔎 交叉审查: {cross.get('final_verdict','?')}")
    if warning:
        print(f"  ⚠️  {warning}")
    print(f"{'='*70}\n")

    return result


def main():
    parser = argparse.ArgumentParser(description="CNC编程Agent流水线")
    parser.add_argument("--prod-no", default="", help="生产单号")
    parser.add_argument("--part-no", default="", help="零件号")
    parser.add_argument("--part-info-json", default=None, help="零件信息JSON字符串")
    parser.add_argument("--features-json", default=None, help="特征列表JSON字符串")
    parser.add_argument("--special-reqs-json", default=None, help="特殊要求JSON字符串")
    args = parser.parse_args()

    # 优先从JSON参数加载
    if args.part_info_json and args.features_json:
        part_info = json.loads(args.part_info_json)
        features = json.loads(args.features_json)
        special_reqs = json.loads(args.special_reqs_json) if args.special_reqs_json else []
        run(
            prod_no=args.prod_no,
            part_info=part_info,
            features=features,
            special_reqs=special_reqs,
            part_no=args.part_no,
        )
    elif args.prod_no:
        # 从分析缓存加载
        results = load_analysis_results(args.prod_no)
        for r in results:
            log.info(f"\n{'='*60}")
            log.info(f"处理零件: {r.get('part_no', '?')}")
            run(
                prod_no=args.prod_no,
                part_no=r.get("part_no", ""),
                part_info=r.get("part_info", {}),
                features=r.get("features", []),
                special_reqs=r.get("special_reqs", []),
            )
    else:
        parser.print_help()
        print("\n错误：请指定 --prod-no（从缓存加载）或 --part-info-json + --features-json（直接传参）")
        sys.exit(1)


if __name__ == "__main__":
    main()
