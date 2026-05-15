"""节点: 工艺推理 — 五层模型 + 知识库 RAG

L1: 零件类型+材料属性 → 识别零件定位
L2: 几何特征→加工手段 → 映射到工序
L3: 5原则排序工序   → 规则引擎
L4: 参数经验值      → 切削参数查询
L5: 特殊要求/风险点 → 注意事项提取
"""

import copy
import logging
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.process_reasoning")


def node_process_reasoning(state: ERPState, config: RunnableConfig, services: dict | None = None) -> dict:
    """五层工艺推理引擎"""
    ctx = config["configurable"]["ctx"]
    part_info = state.get("part_info", {})
    features = state.get("features", [])
    template_id = state.get("matched_template")

    material = part_info.get("material", "K490")
    shape = part_info.get("shape", "square")

    log.info(
        f"工艺推理: material={material}, shape={shape}, "
        f"template={template_id or '无匹配'}"
    )

    # 有模板 → 适配模板
    if template_id:
        plan = _adapt_template(template_id, part_info, features)
        log.info(f"模板适配完成: {len(plan)} 道工序")
        return {"process_plan": plan, "checkpoint": 18}

    # 知识库 RAG
    context = ""
    try:
        kb = ctx.get_service("kb")
        query = f"{material} {shape} 工艺路线"
        kb_docs = kb.retrieve(query, k=5) if kb else []
        if kb_docs:
            context = "\n\n".join(d.page_content for d in kb_docs)
            log.info(f"知识库检索到 {len(kb_docs)} 条参考")
    except Exception as e:
        log.warning(f"知识库检索失败: {e}")

    # 形状决策
    if shape in ("square", "flat"):
        plan = _adapt_square_template(features)
    elif shape in ("round", "cylindrical"):
        plan = _adapt_round_template(features)
    else:
        plan = _generate_from_features(features, context)

    log.info(f"工艺推理完成: {len(plan)} 道工序")
    return {"process_plan": plan, "checkpoint": 18}


# ── 模板函数 ──


def _adapt_template(template_id: str, part_info: dict, features: list) -> list:
    # 根据 template_id 判断形状: 包含 round/cylindrical/shaft 关键词走圆形模板
    tid_lower = template_id.lower()
    if any(kw in tid_lower for kw in ("round", "cylindrical", "shaft")):
        return _build_template("round", features)
    return _build_template("square", features)


def _build_template(shape: str, features: list) -> list:
    """根据形状和特征构建工艺路线"""
    if shape in ("round", "cylindrical"):
        steps = copy.deepcopy(_ROUND_TEMPLATE)
    else:
        steps = copy.deepcopy(_SQUARE_TEMPLATE)

    # 检查是否有精孔/慢丝特征
    has_fine_holes = any(
        f.get("type") in ("精孔", "精密槽") for f in (features or [])
    )
    has_edm = any(
        f.get("type") == "EDM" or "镜面" in str(f.get("spec", ""))
        for f in (features or [])
    )
    has_sharp_edge = any(
        f.get("type") == "利角" or "sharp" in str(f.get("note", "")).lower()
        for f in (features or [])
    )

    # 注入特殊提示
    if has_sharp_edge:
        steps.append({
            "seq": 99,
            "name": "⚠️ 注意事项",
            "task": "利角 — 严禁倒角，研磨去毛刺保刃口",
            "check": "刃口锋利度",
            "meta_step": True,
        })

    return steps


def _adapt_square_template(features: list) -> list:
    return _build_template("square", features)


def _adapt_round_template(features: list) -> list:
    return copy.deepcopy(_ROUND_TEMPLATE)


def _generate_from_features(features: list, context: str) -> list:
    return _build_template("square", features)


# ── 固定工艺模板 ──

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
