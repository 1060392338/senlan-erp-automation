#!/usr/bin/env python3
"""正确拆解表头所有选项"""
import json, re

raw = "平面磨床 车床 外协铣床 深孔钻 大水磨 热处理 出货全检 生产入库 枪钻 慢走丝 中走丝 快走丝 镜面放电 内外圆磨 外协省模 冲子内圆磨 表面处理 小车床 冲子机 委外 无心研磨 滚齿加工 成品采购 坐标磨运费喷砂雕刻打头外发全加工委外制作电极抛光晒纹烧焊扣款打孔高频珩磨委外拆电极CNC精锣半成品采购数控精车数控粗车铣床省模CNC粗锣3D打印委外模具设计模具采购全加工"

# 先取前23个(空格分隔)
parts = raw.split()
first_23 = parts[0].split() if ' ' in raw else []

# 手动拆解剩余部分
remaining_str = "坐标磨运费喷砂雕刻打头外发全加工委外制作电极抛光晒纹烧焊扣款打孔高频珩磨委外拆电极CNC精锣半成品采购数控精车数控粗车铣床省模CNC粗锣3D打印委外模具设计模具采购全加工"

# 用已知选项列表来匹配
known = [
    "坐标磨", "运费", "喷砂", "雕刻", "打头", "外发全加工", "委外制作电极",
    "抛光", "晒纹", "烧焊", "扣款", "打孔", "高频", "珩磨", "委外拆电极",
    "CNC精锣", "半成品采购", "数控精车", "数控粗车", "铣床", "省模",
    "CNC粗锣", "3D打印", "委外模具设计", "模具采购", "全加工"
]

# 验证拼接
concat = "".join(known)
if concat == remaining_str:
    print("✅ 拆解验证通过!")
else:
    print(f"❌ 不匹配!\n  期望: {remaining_str}\n  实际: {concat}")
    # 找差异
    for i, (a, b) in enumerate(zip(remaining_str, concat)):
        if a != b:
            print(f"  差异位置{i}: {a} vs {b}")
            break

# 完整列表
all_options = ["平面磨床", "车床", "外协铣床", "深孔钻", "大水磨", "热处理",
    "出货全检", "生产入库", "枪钻", "慢走丝", "中走丝", "快走丝",
    "镜面放电", "内外圆磨", "外协省模", "冲子内圆磨", "表面处理",
    "小车床", "冲子机", "委外", "无心研磨", "滚齿加工", "成品采购"
] + known

print(f"\n总选项: {len(all_options)} 个")
for i, opt in enumerate(all_options, 1):
    print(f"  {i:2d}. {opt}")

# 保存
with open("data/dropdown_options.json", "w", encoding="utf-8") as f:
    json.dump({"dropdown_options": all_options, "count": len(all_options)}, f, ensure_ascii=False, indent=2)
print("\n已保存到 data/dropdown_options.json")

# 与现有映射表对比
existing_map = [
    "平面磨床", "车床", "外协铣床", "深孔钻", "大水磨", "热处理", "出货全检", "生产入库", "枪钻",
    "慢走丝", "中走丝", "快走丝", "镜面放电", "内外圆磨", "外协省模", "冲子内圆磨", "表面处理",
    "小车床", "冲子机", "委外", "无心研磨", "滚齿加工", "成品采购", "坐标磨",
    "运费", "喷砂", "雕刻", "打头", "外发全加工", "委外制作电极", "抛光",
    "晒纹", "烧焊", "扣款", "打孔", "高频", "珩磨", "委外拆电极",
    "CNC精锣", "半成品采购", "数控精车", "数控粗车", "铣床",
    "省模", "CNC粗锣", "3D打印", "委外模具设计", "模具采购", "全加工",
]

existing_set = set(existing_map)
all_set = set(all_options)
missing = existing_set - all_set
extra = all_set - existing_set

if missing:
    print(f"\n⚠️ 映射表有但下拉框没有: {sorted(missing)}")
if extra:
    print(f"\n⚠️ 下拉框有但映射表没有: {sorted(extra)}")
if not missing and not extra:
    print("\n✅ 完全匹配!")
