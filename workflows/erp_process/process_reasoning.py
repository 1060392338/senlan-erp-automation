"""特征驱动工艺推理引擎 — 基于图纸特征动态生成工序

不再使用固定模板（方形/圆形模板），改为：
1. 分析每个特征 → 判断需要什么工序
2. 合并相同工序，累加工时
3. 按L3规则排序（先粗后精/热处理分水岭/基准先行/慢走丝在精铣之后/表面处理最后）
4. 工时/备注/工人来自特征数量、精度、粗糙度

L3排序规则（不可违背）：
  粗加工 → 热处理 → 磨基准 → 精加工 → 慢走丝/EDM → 抛光 → 检测 → 表面处理 → 入库
  圆形: 车在前; 方形: 铣在前
"""
import re, logging

log = logging.getLogger("process_reasoning")

# ── 特征类型 → 所需工序 ──
# type: [ (工序名, 是否为粗加工, 归类), ... ]
# 归类用于去重合并
FEATURE_PROCESS_MAP = {
    "外形": [("车床", True, "rough_machining"), ("数控精车", False, "finish_machining")],
    "轮廓": [("车床", True, "rough_machining"), ("数控精车", False, "finish_machining")],
    "外圆": [("内外圆磨", False, "grinding")],
    "内圆": [("内外圆磨", False, "grinding")],
    "精孔": [("慢走丝", False, "wire_edm")],
    "精密槽": [("慢走丝", False, "wire_edm")],
    "槽": [("慢走丝", False, "wire_edm")],
    "通孔": [("打孔", True, "drilling")],
    "钻孔": [("打孔", True, "drilling")],
    "螺纹": [("打孔", True, "drilling")],
    "攻牙": [("打孔", True, "drilling")],
    "斜面": [("数控精车", False, "finish_machining")],
    "倒角": [("数控精车", False, "finish_machining")],
    "R角": [("数控精车", False, "finish_machining")],
    "圆角": [("数控精车", False, "finish_machining")],
    "平面度": [("平面磨床", False, "grinding")],
    "平行度": [("平面磨床", False, "grinding")],
    "垂直度": [("平面磨床", False, "grinding")],
    "分型面": [("镜面放电", False, "edm")],
    "碰穿面": [("镜面放电", False, "edm")],
    "镶件槽": [("镜面放电", False, "edm")],
    "逃角": [("镜面放电", False, "edm")],
    "EDM面": [("镜面放电", False, "edm")],
    "线切割孔": [("慢走丝", False, "wire_edm")],
    "齿形": [("慢走丝", False, "wire_edm")],
    "EDM孔": [("镜面放电", False, "edm")],
    "脱模斜度": [("数控精车", False, "finish_machining")],
    "刻字": [("雕刻", False, "engraving")],
    "利角": [],       # 不生成独立工序，加入抛光备注
    "sharp": [],       # 同上
    "刃口": [],        # 同上
    "表面处理": [],    # 最后统一加
    "涂层": [],        # 最后统一加
}

# ── 形状 → 粗加工工序映射 ──
SHAPE_TO_ROUGH = {
    "round": "车床",
    "cylindrical": "车床",
    "circle": "车床",
    "square": "铣床",
    "flat": "铣床",
    "plate": "铣床",
    "rectangular": "铣床",
}

SHAPE_TO_FINISH = {
    "round": "数控精车",
    "cylindrical": "数控精车",
    "circle": "数控精车",
    "square": "CNC精锣",
    "flat": "CNC精锣",
    "plate": "CNC精锣",
    "rectangular": "CNC精锣",
}

# ── L3排序优先级（数值越小越靠前） ──
PROCESS_PRIORITY = {
    "车床": 10,
    "铣床": 10,
    "外协铣床": 10,
    "打孔": 25,
    "热处理": 20,
    "快走丝": 25,
    "大水磨": 30,
    "平面磨床": 31,
    "内外圆磨": 32,
    "无心研磨": 33,
    "坐标磨": 34,
    "数控精车": 40,
    "CNC精锣": 40,
    "CNC粗锣": 12,
    "数控粗车": 12,
    "慢走丝": 50,
    "中走丝": 51,
    "镜面放电": 55,
    "高频": 56,
    "雕刻": 60,
    "抛光": 70,
    "出货全检": 80,
    "表面处理": 90,
    "生产入库": 100,
}

# ── 工序默认设备 ──
PROCESS_EQUIPMENT = {
    "车床": "TAKISAWA NEX-108",
    "铣床": "JINGDIAO铣床",
    "外协铣床": "外协",
    "打孔": "钻床",
    "热处理": "外协",
    "快走丝": "快走丝",
    "大水磨": "OKAMOTO Sam-450",
    "平面磨床": "HOTMAN",
    "内外圆磨": "OKAMOTO",
    "数控精车": "TAKISAWA NEX-108",
    "CNC精锣": "JINGDIAO精雕",
    "CNC粗锣": "JINGDIAO精雕",
    "数控粗车": "TAKISAWA NEX-108",
    "慢走丝": "SODICK AD32LS",
    "中走丝": "中走丝",
    "坐标磨": "坐标磨",
    "无心研磨": "无心研磨",
    "镜面放电": "SODICK AD32LS",
    "高频": "高频机",
    "雕刻": "激光",
    "抛光": "手工",
    "出货全检": "ZEISS CMM",
    "表面处理": "外协",
    "生产入库": "",
}


def reason_process(part_info: dict, features: list, special_reqs: list) -> list:
    """特征驱动工艺推理

    Args:
        part_info: {name, material, hardness, shape, coating, qty}
        features: [{type, spec, tolerance, roughness, qty, note}]
        special_reqs: ["刻字:xxx", "Sharp edge", ...]

    Returns:
        [{"seq": 1, "name": "车床", "equipment": "...", "task": "...",
          "check": "...", "machine_hours": 2.0, "worker": "...", "remark": "..."}, ...]
    """
    shape = (part_info.get("shape") or "square").lower()
    material = part_info.get("material", "S-7")
    hardness = part_info.get("hardness", "54-56HRC")
    coating = part_info.get("coating", "")
    part_name = part_info.get("name", "")
    qty_raw = part_info.get("qty", 1)
    if isinstance(qty_raw, str):
        try:
            qty = int(qty_raw)
        except (ValueError, TypeError):
            log.warning(f"  qty无法解析为数字: {qty_raw!r}, 使用默认值1")
            qty = 1
    else:
        qty = int(qty_raw) if qty_raw else 1

    log.info("=== 特征驱动工艺推理 ===")
    log.info(f"L1: 零件={part_name}, 材料={material}, 硬度={hardness}, 形状={shape}")
    log.info(f"    特征数: {len(features)}, 特殊要求: {len(special_reqs)}")

    # ────────── L2: 特征 → 工序映射 ──────────
    from collections import defaultdict
    process_features = defaultdict(list)  # 工序名 → [关联的特征列表]
    has_holes = has_slots = has_threads = has_sharp = False

    for f in (features or []):
        ftype = (f.get("type") or "").strip()
        required_procs = FEATURE_PROCESS_MAP.get(ftype, [])

        if not required_procs:
            # 利角类：不生成工序，标记到抛光备注
            if ftype in ("利角", "sharp", "刃口"):
                has_sharp = True
                continue
            # 未匹配特征，按形状猜测
            if shape in SHAPE_TO_FINISH:
                required_procs = [(SHAPE_TO_FINISH[shape], False, "finish_machining")]
            else:
                continue

        for proc_name, is_rough, category in required_procs:
            # 记录工时参考依据
            process_features[proc_name].append(f)

            # 标记特征类型
            if ftype in ("精孔", "钻孔", "通孔"):
                has_holes = True
            elif ftype in ("槽", "精密槽"):
                has_slots = True
            elif ftype in ("螺纹", "攻牙", "牙"):
                has_threads = True

    log.info(f"L2: 工序需求: {dict((k, len(v)) for k, v in process_features.items())}")
    log.info(f"    特征标记: 孔={has_holes} 槽={has_slots} 螺纹={has_threads} 利角={has_sharp}")

    # 从 special_reqs 中提取刻字
    engrave_content = _extract_engrave_content(special_reqs, features)
    if engrave_content and "雕刻" not in process_features:
        process_features["雕刻"] = [{"type": "刻字", "spec": engrave_content}]
        log.info(f"    从特殊要求提取刻字: {engrave_content[:50]}")

    # 从 special_reqs 检测利角要求
    for s in (special_reqs or []):
        if "利角" in str(s) or "Sharp" in str(s) or "刃口" in str(s):
            has_sharp = True
            log.info("    从特殊要求检测到利角")

    # ────────── 添加上下文工序 ──────────

    # 确保粗加工存在（根据形状）
    rough_name = SHAPE_TO_ROUGH.get(shape, "车床" if shape == "round" else "铣床")
    if rough_name not in process_features:
        # 从外形特征获取参考
        outer_features = [f for f in (features or []) if f.get("type") in ("外形", "轮廓")]
        process_features[rough_name] = outer_features or [{"type": "外形", "spec": "图纸标注"}]

    # 确保精加工存在
    finish_name = SHAPE_TO_FINISH.get(shape, "数控精车" if shape == "round" else "CNC精锣")
    if finish_name not in process_features:
        finish_features = [f for f in (features or []) if f.get("type") in (
            "外形", "轮廓", "斜面", "倒角", "R角", "圆角", "脱模斜度"
        )]
        process_features[finish_name] = finish_features or [{"type": "精加工", "spec": "到位"}]

    # ────────── L3: 合并+排序 ──────────
    # 1. 成形粗加工（车床/铣床/打孔）
    # 2. 热处理
    # 3. 磨基准（平面磨床/内外圆磨/大水磨）
    # 4. 精加工（数控精车/CNC精锣）
    # 5. 慢走丝（精孔/槽）
    # 6. EDM（镜面放电）
    # 7. 雕刻
    # 8. 抛光
    # 9. 检测
    # 10. 表面处理
    # 11. 入库

    # 按优先级排序
    def sort_key(item):
        name = item[0]
        return PROCESS_PRIORITY.get(name, 999)

    sorted_items = sorted(process_features.items(), key=sort_key)
    sorted_names = [item[0] for item in sorted_items]

    log.info(f"L3: 排序前工序: {sorted_names}")

    # ────────── 添加辅助工序 ──────────
    # 热处理（有硬度要求）
    if hardness and hardness not in ("", "无"):
        if "热处理" not in sorted_names:
            sorted_names.append("热处理")

    # 磨削（有平面度/平行度/垂直度要求，或圆形外圆）
    has_grinding_features = any(f.get("type") in ("平面度", "平行度", "垂直度", "外圆", "内圆")
                                for f in (features or []))
    has_grinding_proc = any(n in sorted_names for n in ("平面磨床", "内外圆磨", "大水磨"))

    if has_grinding_features and not has_grinding_proc:
        if shape in ("round", "cylindrical", "circle"):
            sorted_names.append("内外圆磨")
        else:
            sorted_names.append("平面磨床")

    # 抛光
    if "抛光" not in sorted_names:
        sorted_names.append("抛光")

    # 检测
    if "出货全检" not in sorted_names:
        sorted_names.append("出货全检")

    # 表面处理
    if coating and coating not in ("", "无", "none"):
        if "表面处理" not in sorted_names:
            sorted_names.append("表面处理")

    # 生产入库
    if "生产入库" not in sorted_names:
        sorted_names.append("生产入库")

    # ────────── 热处分水岭重排序 ──────────
    # 热处理前的工序（粗加工类）放在热处理前
    # 热处理后的工序（精加工类）放在热处理后
    final_order = []
    heat_pos = None

    # 寻找热处理位置
    for i, name in enumerate(sorted_names):
        if name == "热处理":
            heat_pos = i
            break

    if heat_pos is not None:
        # 热处理前：所有优先级<25（纯粗加工）的
        before_heat = [n for n in sorted_names if PROCESS_PRIORITY.get(n, 999) < 25]
        final_order.extend(before_heat)

        # 热处理
        if "热处理" not in final_order:
            final_order.append("热处理")

        # 热处理后：所有优先级>=25的（磨削/精加工/慢走丝/EDM/抛光/检测/入库）
        after_heat = [n for n in sorted_names if PROCESS_PRIORITY.get(n, 999) >= 25]
        for n in after_heat:
            if n not in final_order:
                final_order.append(n)
    else:
        final_order = sorted_names

    # 去重 + 保持顺序
    seen = set()
    deduped = []
    for n in final_order:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    final_order = deduped

    log.info(f"L3: 最终工序顺序: {final_order}")

    # ────────── L4: 工时估算 ──────────
    result = []
    for seq, name in enumerate(final_order, 1):
        # 特征列表
        feats = process_features.get(name, [])

        # 布尔标记
        is_sharp_feature = has_sharp and name == "抛光"
        engrave_content = _extract_engrave_content(special_reqs, features)

        # 工时估算
        machine_hours = _estimate_hours(name, feats, features, shape, qty)

        # 任务描述
        task = _generate_task(name, feats, has_holes, has_slots, has_threads)

        # 工艺要求
        remark = _generate_remark(name, feats, material, hardness, coating,
                                   engrave_content, is_sharp_feature,
                                   features, special_reqs)

        # 检验要求
        check = _generate_check(name, feats, has_sharp)

        step = {
            "seq": seq,
            "name": name,
            "equipment": PROCESS_EQUIPMENT.get(name, ""),
            "task": task,
            "check": check,
            "machine_hours": machine_hours,
            "worker": name if name != "表面处理" else "外协",
            "remark": remark,
        }
        result.append(step)

    # ────────── L5: 特殊要求 ──────────
    if has_sharp:
        log.info("L5: 利角要求 — 已体现在抛光工序备注中")

    if coating and coating not in ("", "无", "none"):
        log.info(f"L5: {coating}涂层需要外协，已安排")

    if engrave_content:
        log.info(f"L5: 刻字内容: {engrave_content}")

    log.info(f"=== 特征驱动推理完成: {len(result)}道工序 ===")
    for s in result:
        log.info(f"  {s['seq']:2d}. {s['name']:8s} | {s['machine_hours']:5.1f}h | {s['task'][:30]}")
    return result


def _estimate_hours(proc_name: str, feats: list, all_features: list,
                    shape: str, qty: int) -> float:
    """根据特征估算工时"""
    base = 1.0
    qty_mult = max(1, min(qty, 10))  # 数量影响上限10倍

    if proc_name in ("车床", "铣床", "外协铣床", "数控粗车"):
        # 有没有外形尺寸？大件时间长
        outer = [f for f in feats if f.get("type") in ("外形", "轮廓")]
        if outer:
            spec = str(outer[0].get("spec", "") or "")
            nums = [float(n) for n in re.findall(r"[\d.]+", spec) if n.count(".") <= 1 and float(n) > 0]
            if not nums:
                max_dim = 200
            else:
                max_dim = max(nums)
                if max_dim < 50 and ('"' in spec or "'" in spec or 'inch' in spec.lower()):
                    max_dim *= 25.4
                # 兜底：小于30mm的工件不可能有复杂特征，很可能是英制
                if max_dim < 30:
                    max_dim *= 25.4
            base = 1.5 * (max_dim / 100)
            log.info(f"    车床估算: spec={spec!r}, nums={nums}, max_dim={max_dim}, base={base}")
        else:
            base = max(1.0, len(all_features) * 0.3)
            log.info(f"    车床估算(无外形): base={base}")
        base = min(base * qty_mult, 8.0)

    elif proc_name in ("数控精车", "CNC精锣"):
        # 精加工工时
        outer = [f for f in feats if f.get("type") in ("外形", "轮廓")]
        if outer:
            spec = str(outer[0].get("spec", "") or "")
            nums = [float(n) for n in re.findall(r"[\d.]+", spec) if n.count(".") <= 1 and float(n) > 0]
            if not nums:
                max_dim = 200
            else:
                max_dim = max(nums)
                if max_dim < 50 and ('"' in spec or "'" in spec or 'inch' in spec.lower()):
                    max_dim *= 25.4
                # 兜底：小于30mm的工件不可能有复杂特征，很可能是英制
                if max_dim < 30:
                    max_dim *= 25.4
            base = 0.8 * (max_dim / 100)
        else:
            base = max(1.0, len(all_features) * 0.2)
        # 有倒角/斜面加时
        extra_features = [f for f in all_features if f.get("type") in ("倒角", "斜面", "R角", "圆角")]
        base += 0.5 * len(extra_features)

    elif proc_name in ("慢走丝", "中走丝", "快走丝"):
        # 按孔数/槽数/特征数
        holes = [f for f in feats if f.get("type") in ("精孔", "线切割孔")]
        slots = [f for f in feats if f.get("type") in ("槽", "精密槽", "齿形")]
        total_qty = sum(f.get("qty", 1) for f in holes + slots)
        base = total_qty * 0.5 + len(feats) * 0.2  # 每个0.5h + 特征基础0.2h
        # 精度高加时
        for f in holes + slots:
            try:
                roughness_val = float(f.get("roughness", 1))
                if roughness_val < 0.8:
                    base += 0.2 * f.get("qty", 1)
            except (ValueError, TypeError):
                pass

    elif proc_name == "镜面放电":
        edm_features = [f for f in feats]
        total_qty = sum(f.get("qty", 1) for f in edm_features)
        base = max(total_qty * 0.8, 2.0)

    elif proc_name in ("平面磨床", "内外圆磨", "大水磨"):
        has_planar = any(f.get("type") in ("平面度", "平行度", "垂直度") for f in feats)
        base = 3.0 if has_planar else 2.0

    elif proc_name == "打孔":
        holes = [f for f in feats]
        total_qty = sum(f.get("qty", 1) for f in holes)
        base = total_qty * 0.2  # 每个0.2h

    elif proc_name == "雕刻":
        base = 0.5

    elif proc_name == "抛光":
        base = 2.0

    elif proc_name == "热处理":
        base = 0  # 外协不计工时
    elif proc_name == "表面处理":
        base = 0
    elif proc_name == "出货全检":
        base = 1.0
    elif proc_name == "生产入库":
        base = 0.5

    return round(base, 1)


def _generate_task(proc_name: str, feats: list, has_holes: bool,
                   has_slots: bool, has_threads: bool) -> str:
    """生成任务描述 — 基于特征生成详细任务内容"""
    if proc_name in ("车床", "铣床", "外协铣床"):
        tasks = []
        outer = [f for f in feats if f.get("type") in ("外形", "轮廓")]
        if outer:
            spec = outer[0].get("spec", "")
            tasks.append(f"粗车外形{spec}")
        else:
            tasks.append("粗车外形")
        if has_threads:
            thread_feats = [f for f in feats if f.get("type") in ("螺纹", "攻牙")]
            specs = [f"攻牙{f.get('spec','')}" for f in thread_feats]
            tasks.append(";".join(specs) if specs else "攻丝")
        if has_holes:
            tasks.append("钻孔(预钻)")
        return "；".join(tasks)

    if proc_name in ("数控精车", "CNC精锣", "CNC粗锣", "数控粗车"):
        tasks = []
        has_slope = any(f.get("type") in ("斜面", "倒角", "R角", "圆角", "脱模斜度")
                       for f in feats)
        # 外形特征
        outer = [f for f in feats if f.get("type") in ("外形", "轮廓")]
        if "粗" in proc_name:
            tasks.append("粗加工")
        elif outer:
            spec = outer[0].get("spec", "")
            tasks.append(f"精车外形{spec}到位")
        else:
            tasks.append("精加工到位")
        if has_slope:
            slope_types = []
            for f in feats:
                t = f.get("type", "")
                s = f.get("spec", "")
                if t in ("斜面", "倒角", "R角", "圆角", "脱模斜度"):
                    slope_types.append(f"{t}{s}" if s else t)
            if slope_types:
                tasks.append("加工" + "、".join(slope_types))
        # 公差
        tolerances = [f.get("tolerance", "") for f in feats if f.get("tolerance")]
        if tolerances:
            tasks.append(f"保证公差{'/'.join(tolerances[:2])}")
        return "；".join(tasks)

    if proc_name == "慢走丝":
        tasks = []
        holes = [f for f in feats if f.get("type") == "精孔"]
        slots = [f for f in feats if f.get("type") in ("槽", "精密槽")]
        if holes:
            total = sum(f.get("qty", 1) for f in holes)
            specs = [f"∅{f.get('spec','').lstrip('∅Ø')}" for f in holes]
            tasks.append(f"割精孔{'/'.join(specs)}×{total}")
        if slots:
            for f in slots:
                spec = f.get("spec", "")
                qty = f.get("qty", 1)
                tasks.append(f"割槽{spec}×{qty}" if spec else f"割槽×{qty}")
        if not tasks:
            tasks.append("精密线切割加工")
        # 粗糙度要求
        rough_vals = [f.get("roughness", "") for f in feats if f.get("roughness")]
        if rough_vals:
            tasks.append(f"Ra{'/Ra'.join(sorted(set(str(r) for r in rough_vals)))}")
        return "；".join(tasks)

    if proc_name == "镜面放电":
        tasks = []
        for f in feats:
            typ = f.get("type", "特征")
            spec = f.get("spec", "")
            qty = f.get("qty", 1)
            if spec:
                tasks.append(f"镜面放电{typ}{spec}×{qty}")
            elif qty > 1:
                tasks.append(f"镜面放电{typ}×{qty}")
            else:
                tasks.append(f"镜面放电{typ}")
        if not tasks:
            tasks.append("镜面放电精加工")
        return "；".join(tasks)

    if proc_name in ("平面磨床", "内外圆磨", "大水磨"):
        tasks = []
        planar = [f for f in feats
                  if f.get("type") in ("平面度", "平行度", "垂直度")]
        cyl = [f for f in feats if f.get("type") in ("外圆", "内圆")]
        if "圆" in proc_name and cyl:
            tasks.append("磨外圆/内圆到位")
        elif planar:
            atypes = list(set(f.get("type", "") for f in planar))
            tasks.append("磨基准面" + "保" + "".join(atypes))
        else:
            tasks.append("磨基准面到位")
        return "；".join(tasks)

    if proc_name == "打孔":
        tasks = []
        threads = [f for f in feats if f.get("type") in ("螺纹", "攻牙")]
        drills = [f for f in feats if f.get("type") in ("钻孔", "通孔")]
        if threads:
            for f in threads:
                tasks.append(f"攻牙{f.get('spec','')}×{f.get('qty',1)}")
        if drills:
            for f in drills:
                tasks.append(f"钻∅{f.get('spec','').lstrip('∅Ø')}×{f.get('qty',1)}")
        if not tasks:
            total = sum(f.get("qty", 1) for f in feats)
            tasks.append(f"钻孔/攻丝×{total}")
        return "；".join(tasks)

    if proc_name == "雕刻":
        return "激光雕刻刻字"

    if proc_name == "抛光":
        return "去毛刺抛光到位"

    if proc_name == "热处理":
        return "淬火+回火至要求硬度"

    if proc_name == "出货全检":
        return "全尺寸检测并出具报告"

    if proc_name == "表面处理":
        return "外协表面处理"

    if proc_name == "生产入库":
        return "成品包装入库"

    return proc_name


def _generate_remark(proc_name: str, feats: list,
                     material: str, hardness: str, coating: str,
                     engrave_content: str, is_sharp: bool,
                     all_features: list, special_reqs: list) -> str:
    """生成工艺要求备注 — 基于特征生成详细参数"""
    parts = []

    if proc_name in ("车床", "铣床", "外协铣床"):
        parts.append(f"材料:{material} 硬度:{hardness}")
        outer = [f for f in feats if f.get("type") in ("外形", "轮廓")]
        if outer:
            spec = outer[0].get("spec", "")
            parts.append(f"外形:{spec}")
        parts.append("开粗留余量0.5mm单边供后续精加工。")
        # 如有螺纹特征
        threads = [f for f in all_features if f.get("type") in ("螺纹", "攻牙")]
        if threads:
            t_specs = [f"{f.get('type')}{f.get('spec','')}" for f in threads]
            parts.append(f"螺纹:{';'.join(t_specs)}")
        # 如有钻孔特征（粗加工时预钻孔）
        holes = [f for f in all_features if f.get("type") in ("钻孔", "通孔")]
        if holes:
            h_specs = [f"∅{f.get('spec','').lstrip('∅Ø')}" for f in holes]
            parts.append(f"预钻孔:{';'.join(h_specs)}(若需)")

    elif proc_name in ("数控精车", "CNC精锣", "CNC粗锣", "数控粗车"):
        is_finish = "粗" not in proc_name
        if is_finish:
            parts.append("精加工到位，保证尺寸公差。")
        else:
            parts.append("粗加工留余量0.5mm单边。")

        # 外形尺寸
        outer = [f for f in feats if f.get("type") in ("外形", "轮廓")]
        if outer:
            spec = outer[0].get("spec", "")
            parts.append(f"外形:{spec}")
            tolerance = outer[0].get("tolerance", "")
            if tolerance:
                parts.append(f"公差:{tolerance}")

        # 斜面/倒角/R角
        slope_feats = [f for f in all_features
                       if f.get("type") in ("斜面", "倒角", "R角", "圆角", "脱模斜度")]
        for f in slope_feats:
            spec = f.get("spec", "到位")
            rough = f.get("roughness", "")
            if rough:
                parts.append(f"{f['type']}:{spec},Ra{rough}")
            else:
                parts.append(f"{f['type']}:{spec}")

        # 粗糙度
        roughness_set = set()
        for f in all_features:
            r = f.get("roughness", "")
            if r:
                roughness_set.add(r)
        if roughness_set:
            parts.append(f"表面粗糙度:Ra{'/Ra'.join(sorted(str(r) for r in roughness_set))}")

        # 慢走丝留余量
        has_wire_features = any(f.get("type") in ("精孔", "精密槽", "槽", "线切割孔")
                                for f in all_features)
        if has_wire_features and is_finish:
            parts.append("直身面留3.0mm给慢走丝入丝。")

        # 加工参数建议
        if is_finish:
            parts.append(f"转速建议S1800-2500rpm,进给F0.05-0.12mm/rev(据硬度调整)。")

    elif proc_name == "慢走丝":
        holes = [f for f in feats if f.get("type") == "精孔"]
        if holes:
            hole_specs = []
            for f in holes:
                d = f.get("spec", "").lstrip("∅Ø")
                qty = f.get("qty", 1)
                tol = f.get("tolerance", "")
                rough = f.get("roughness", "")
                s = f"∅{d}×{qty}个"
                if tol: s += f" 公差{tol}"
                if rough: s += f" Ra{rough}"
                hole_specs.append(s)
            parts.append(f"精孔:{'; '.join(hole_specs)}")

        slots = [f for f in feats if f.get("type") in ("槽", "精密槽")]
        if slots:
            slot_specs = []
            for f in slots:
                d = f.get("spec", "")
                qty = f.get("qty", 1)
                rough = f.get("roughness", "")
                s = f"{d}×{qty}处"
                if rough: s += f" Ra{rough}"
                slot_specs.append(s)
            parts.append(f"槽:{'; '.join(slot_specs)}")

        # 割修次数（按粗糙度定）
        min_roughness = 99.0
        for f in feats:
            try:
                r = float(f.get("roughness", 99))
                if r < min_roughness:
                    min_roughness = r
            except (ValueError, TypeError):
                pass
        if min_roughness <= 0.4:
            parts.append("割1修3,线径0.25mm铜线。")
        elif min_roughness <= 1.0:
            parts.append("割1修2,线径0.25mm铜线。")
        else:
            parts.append("割1修1,线径0.25mm铜线。")

        # 公差
        has_tight_tol = any(f.get("tolerance", "") for f in feats)
        if has_tight_tol:
            parts.append("公差±0.005mm。")

    elif proc_name == "镜面放电":
        parts.append("镜面加工,表面Ra0.2。")
        for f in feats:
            typ = f.get("type", "特征")
            spec = f.get("spec", "")
            qty = f.get("qty", 1)
            depth = f.get("depth", "")
            rough = f.get("roughness", "")
            s = f"{typ}"
            if spec: s += f" {spec}"
            if depth: s += f" 深度{depth}"
            if qty > 1: s += f" ×{qty}"
            if rough: s += f" Ra{rough}"
            parts.append(s)
        parts.append("电极:铜/石墨,放电电流IP3-5A,脉宽ON50us/OFF25us。")

    elif proc_name in ("平面磨床", "内外圆磨", "大水磨"):
        planar = [f for f in feats
                  if f.get("type") in ("平面度", "平行度", "垂直度", "外圆", "内圆")]
        if planar:
            vals = [f"{f['type']}{f.get('spec','')}" for f in planar]
            parts.append(f"形位公差:{'; '.join(vals)}")
        else:
            parts.append("磨基准面到位。")
        parts.append("表面Ra0.8。")

        # 磨削量
        has_grinding_features = any(f.get("spec") or f.get("tolerance") for f in feats)
        if has_grinding_features:
            parts.append("留磨量0.1-0.15mm,砂轮粒度60-80#。")

    elif proc_name == "雕刻":
        if engrave_content:
            parts.append(f"刻字内容:{engrave_content}")
        else:
            parts.append("刻字按图纸要求。")
        parts.append("激光刻字机,深度0.1-0.3mm。")

    elif proc_name == "抛光":
        if is_sharp:
            parts.append("⚠️ 利角(Sharp edge)明确标注不允许倒角,研磨去毛刺时必须保留锋利刃口!")
        parts.append("去毛刺抛光到位。")
        # 提取粗糙度要求
        rough_vals = []
        for f in all_features:
            r = f.get("roughness", "")
            if r and r not in rough_vals:
                rough_vals.append(r)
        if rough_vals:
            parts.append(f"表面粗糙度要求:Ra{'/Ra'.join(sorted(str(r) for r in rough_vals))}")

    elif proc_name == "打孔":
        threads = [f for f in feats if f.get("type") in ("螺纹", "攻牙")]
        drills = [f for f in feats if f.get("type") in ("钻孔", "通孔")]
        total_qty = sum(f.get("qty", 1) for f in feats)
        specs = []
        for f in threads:
            s = f"攻牙{f.get('spec','')}×{f.get('qty',1)}"
            specs.append(s)
        for f in drills:
            s = f"钻∅{f.get('spec','').lstrip('∅Ø')}×{f.get('qty',1)}"
            specs.append(s)
        if specs:
            parts.append(f"钻孔/攻丝:{'; '.join(specs)}")
        else:
            parts.append(f"钻孔/攻丝×{total_qty}")
        # 热处理后钻孔用硬质合金钻头
        parts.append("材料已淬硬,使用硬质合金钻头/丝锥。")

    elif proc_name == "热处理":
        parts.append(f"热处理至{hardness}。")
        # 从特殊要求中提取退火/回火信息
        heat_reqs = [s for s in (special_reqs or [])
                     if any(kw in s for kw in ["回火", "退火", "淬火", "渗碳", "氮化"])]
        if heat_reqs:
            parts.append(f"工艺要求:{'; '.join(heat_reqs)}")
        parts.append("注意控制变形量,预留磨削余量。")

    elif proc_name == "表面处理":
        if coating and coating not in ("", "无", "none"):
            parts.append(f"{coating}表面处理,外协加工。")
        else:
            parts.append("表面处理,外协加工。")

    elif proc_name == "出货全检":
        parts.append("全尺寸检测,核对图纸所有公差标注。")
        # 列出关键检测项
        key_checks = []
        for f in (all_features or []):
            tol = f.get("tolerance", "")
            rough = f.get("roughness", "")
            typ = f.get("type", "")
            spec = f.get("spec", "")
            if tol:
                key_checks.append(f"{typ}{spec} 公差{tol}")
            elif rough:
                key_checks.append(f"{typ}{spec} Ra{rough}")
        if key_checks:
            parts.append(f"关键检测项:{'; '.join(key_checks[:5])}")
        parts.append("使用三坐标/投影仪检测。")

    elif proc_name == "生产入库":
        parts.append("完成品入库,附检测报告。")
        if coating and coating not in ("", "无", "none"):
            parts.append(f"{coating}涂层已外协处理。")

    # 特殊要求注入（通用）
    special_text = []
    for s in (special_reqs or []):
        if "Sharp" in s or "利角" in s:
            continue
        if proc_name == "雕刻" and ("刻字" in s or "engrave" in s.lower()):
            continue
        special_text.append(s)
    if special_text:
        parts.append(f"注意:{'; '.join(special_text)}")

    return " ".join(parts)


def _generate_check(proc_name: str, feats: list, has_sharp: bool) -> str:
    """生成检验要求"""
    if proc_name in ("车床", "铣床"):
        return "余量0.5mm"
    if proc_name in ("数控精车", "CNC精锣"):
        return "中心;尺寸公差"
    if proc_name == "慢走丝":
        return "孔径公差±0.005;Ra0.63"
    if proc_name == "镜面放电":
        return "中心;电极损耗<0.5%"
    if proc_name in ("平面磨床", "内外圆磨", "大水磨"):
        planar = [f for f in feats if f.get("type") in ("平面度", "平行度", "垂直度")]
        if planar:
            return ";".join(f"{f['type']}{f.get('spec','')}" for f in planar)
        return "平行度0.005;直角度0.005"
    if proc_name == "抛光":
        return "表面Ra0.8" + (";刃口锋利度" if has_sharp else "")
    if proc_name == "热处理":
        return "硬度确认"
    if proc_name == "雕刻":
        return "内容正确"
    if proc_name == "出货全检":
        return "按公差"
    if proc_name == "打孔":
        return "牙规通止"
    return ""


def _extract_engrave_content(special_reqs: list, features: list) -> str:
    """提取刻字内容"""
    for s in (special_reqs or []):
        if "刻字" in str(s) or "engrave" in str(s).lower():
            return str(s)
    for f in (features or []):
        if (f.get("type") or "").lower() in ("刻字", "engrave"):
            return f.get("spec", "")
    return ""


def map_to_erp_processes(process_plan: list) -> list:
    """将推理的工序名映射到ERP下拉框选项并验证"""
    from config.dropdown_options import ERP_PROCESS_OPTIONS, NAME_TO_ERP

    NAME_MAP = NAME_TO_ERP

    mapped = []
    for step in process_plan:
        original_name = step.get("name", "")

        # 跳过元步骤
        if step.get("meta_step") or "注意事项" in original_name or "⚠️" in original_name:
            continue

        # 映射
        erp_name = NAME_MAP.get(original_name, original_name)

        # 验证
        if erp_name not in ERP_PROCESS_OPTIONS:
            import difflib
            log.warning(f"'{erp_name}'不在ERP选项，模糊匹配...")
            matches = difflib.get_close_matches(erp_name, ERP_PROCESS_OPTIONS, n=1, cutoff=0.6)
            if matches:
                erp_name = matches[0]
            else:
                raise ValueError(f"'{erp_name}'无法匹配")

        mapped.append({
            "name": erp_name,
            "machine_hours": step.get("machine_hours", 0),
            "worker": step.get("worker", step.get("equipment", "")),
            "remark": step.get("remark", ""),
        })
        log.info(f"  映射: {original_name} → {erp_name}")

    return mapped
