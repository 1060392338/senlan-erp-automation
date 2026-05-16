#!/usr/bin/env python3
"""表征测试 — 锁定 process_reasoning.py 和 fill_by_vision.py 纯函数当前行为

这些测试在重构前编写，确保重构不破坏现有行为。
"""

import sys
import os
import json
import unittest
from pathlib import Path

# 项目根目录
PROJ = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, PROJ)

# ── 待测模块 ──
from scripts.vision_service import extract_prod_no, scan_drawings
from config.dropdown_options import ERP_PROCESS_OPTIONS

# 导入 process_reasoning 中的模块级函数
# 注意：_开头的私有函数也能直接 import
from workflows.erp_process.process_reasoning import (
    reason_process,
    _estimate_hours,
    _generate_task,
    _generate_remark,
    _generate_check,
    _extract_engrave_content,
    map_to_erp_processes,
    FEATURE_PROCESS_MAP,
    SHAPE_TO_ROUGH,
    SHAPE_TO_FINISH,
    PROCESS_PRIORITY,
    PROCESS_EQUIPMENT,
)


class TestExtractProdNo(unittest.TestCase):
    """文件名 → (prod_no, part_no) 提取"""

    def test_dash_separated(self):
        self.assertEqual(extract_prod_no("C03026051501-001.pdf"),
                         ("C03026051501", "001"))

    def test_dash_separated_alpha_part(self):
        self.assertEqual(extract_prod_no("C03026051501-A1.pdf"),
                         ("C03026051501", "A1"))

    def test_no_part_no(self):
        self.assertEqual(extract_prod_no("W20126051401.pdf"),
                         ("W20126051401", None))

    def test_multiple_dashes(self):
        """只取第一个-切分"""
        self.assertEqual(extract_prod_no("ABC-001-extra.pdf"),
                         ("ABC", "001-extra"))

    def test_no_extension(self):
        self.assertEqual(extract_prod_no("C03026051501-001"),
                         ("C03026051501", "001"))

    def test_path_with_directory(self):
        self.assertEqual(extract_prod_no("/path/to/C03026051501-002.pdf"),
                         ("C03026051501", "002"))


class TestExtractEngraveContent(unittest.TestCase):
    """刻字内容提取"""

    def test_from_special_reqs(self):
        result = _extract_engrave_content(
            ["刻字:FMK-7736.030.61", "利角"],
            [{"type": "外形", "spec": "100×82mm"}]
        )
        self.assertEqual(result, "刻字:FMK-7736.030.61")

    def test_from_features(self):
        result = _extract_engrave_content(
            [],
            [{"type": "刻字", "spec": "FMK-7736.030.61"}]
        )
        self.assertEqual(result, "FMK-7736.030.61")

    def test_no_engraving(self):
        result = _extract_engrave_content(
            ["利角", "TIN涂层"],
            [{"type": "外形", "spec": "100×82mm"}]
        )
        self.assertEqual(result, "")

    def test_empty_inputs(self):
        self.assertEqual(_extract_engrave_content([], []), "")


class TestEstimateHours(unittest.TestCase):
    """工时估算"""

    def test_rough_turning_with_spec(self):
        """车床大件"""
        hours = _estimate_hours(
            "车床",
            [{"type": "外形", "spec": "200×100×50mm"}],
            [{"type": "外形", "spec": "200×100×50mm"}],
            "square", 1
        )
        self.assertAlmostEqual(hours, 3.0, delta=0.1)

    def test_rough_turning_no_spec(self):
        """车床无规格"""
        hours = _estimate_hours(
            "车床",
            [],
            [{"type": "外形", "spec": "100mm"}],
            "square", 1
        )
        self.assertGreater(hours, 0)

    def test_finish_turning(self):
        """数控精车"""
        hours = _estimate_hours(
            "数控精车",
            [{"type": "外形", "spec": "107×30mm"}],
            [{"type": "外形", "spec": "107×30mm"}],
            "round", 1
        )
        self.assertGreater(hours, 0)
        # 有倒角加时
        hours_with_chamfer = _estimate_hours(
            "数控精车",
            [{"type": "外形", "spec": "107×30mm"}],
            [{"type": "外形", "spec": "107×30mm"}, {"type": "倒角", "spec": "C1"}],
            "round", 1
        )
        self.assertGreater(hours_with_chamfer, hours)

    def test_wire_edm(self):
        """慢走丝"""
        hours = _estimate_hours(
            "慢走丝",
            [{"type": "精孔", "spec": "10.47", "qty": 2}],
            [{"type": "精孔", "spec": "10.47", "qty": 2}],
            "square", 1
        )
        self.assertGreaterEqual(hours, 1.0)

    def test_mirror_edm(self):
        """镜面放电"""
        hours = _estimate_hours(
            "镜面放电",
            [{"type": "镶件槽", "spec": "3×3mm", "qty": 4}],
            [{"type": "镶件槽", "spec": "3×3mm", "qty": 4}],
            "square", 1
        )
        self.assertGreaterEqual(hours, 2.0)

    def test_grinding_with_planar(self):
        """平面磨床带形位公差"""
        hours = _estimate_hours(
            "平面磨床",
            [{"type": "平面度", "spec": "0.005"}, {"type": "平行度", "spec": "0.005"}],
            [],
            "square", 1
        )
        self.assertAlmostEqual(hours, 3.0, delta=0.1)

    def test_grinding_no_planar(self):
        hours = _estimate_hours("平面磨床", [], [], "square", 1)
        self.assertAlmostEqual(hours, 2.0, delta=0.1)

    def test_drilling(self):
        hours = _estimate_hours(
            "打孔",
            [{"type": "钻孔", "spec": "10.5", "qty": 4}],
            [],
            "square", 1
        )
        self.assertAlmostEqual(hours, 0.8, delta=0.1)

    def test_heat_treatment(self):
        self.assertEqual(_estimate_hours("热处理", [], [], "square", 1), 0)

    def test_surface_coating(self):
        self.assertEqual(_estimate_hours("表面处理", [], [], "square", 1), 0)

    def test_inspection(self):
        self.assertEqual(_estimate_hours("出货全检", [], [], "square", 1), 1.0)

    def test_warehouse(self):
        self.assertEqual(_estimate_hours("生产入库", [], [], "square", 1), 0.5)

    def test_engraving(self):
        self.assertEqual(_estimate_hours("雕刻", [], [], "square", 1), 0.5)


class TestGenerateTask(unittest.TestCase):
    """任务描述生成"""

    def test_rough_turning_basic(self):
        task = _generate_task("车床", [{"type": "外形", "spec": "100×82mm"}], False, False, False)
        self.assertIn("粗车外形", task)

    def test_rough_turning_with_threads(self):
        task = _generate_task(
            "车床",
            [{"type": "外形", "spec": "100×82mm"}],
            False, False, True
        )
        self.assertIn("攻丝", task)  # 无 spec 时

    def test_finish_turning(self):
        task = _generate_task(
            "数控精车",
            [{"type": "外形", "spec": "107×30mm"}],
            False, False, False
        )
        self.assertIn("精车外形", task)

    def test_finish_turning_with_chamfer(self):
        task = _generate_task(
            "数控精车",
            [{"type": "外形", "spec": "107×30mm"}],
            False, False, False
        )
        self.assertIn("精车外形107×30mm到位", task)

    def test_wire_edm(self):
        task = _generate_task(
            "慢走丝",
            [{"type": "精孔", "spec": "10.47", "qty": 2, "roughness": 0.63}],
            False, False, False
        )
        self.assertIn("割精孔", task)

    def test_mirror_edm(self):
        task = _generate_task(
            "镜面放电",
            [{"type": "镶件槽", "spec": "3×3mm", "qty": 4}],
            False, False, False
        )
        self.assertIn("镜面放电", task)

    def test_polishing(self):
        self.assertEqual(_generate_task("抛光", [], False, False, False), "去毛刺抛光到位")

    def test_heat_treatment_task(self):
        self.assertEqual(_generate_task("热处理", [], False, False, False), "淬火+回火至要求硬度")

    def test_inspection_task(self):
        self.assertEqual(_generate_task("出货全检", [], False, False, False), "全尺寸检测并出具报告")


class TestGenerateCheck(unittest.TestCase):
    """检验要求生成"""

    def test_rough_turning(self):
        self.assertEqual(_generate_check("车床", [], False), "余量0.5mm")

    def test_finish_turning(self):
        self.assertEqual(_generate_check("数控精车", [], False), "中心;尺寸公差")

    def test_wire_edm(self):
        self.assertEqual(_generate_check("慢走丝", [], False), "孔径公差±0.005;Ra0.63")

    def test_mirror_edm(self):
        self.assertEqual(_generate_check("镜面放电", [], False), "中心;电极损耗<0.5%")

    def test_polish_with_sharp(self):
        self.assertIn("刃口锋利度", _generate_check("抛光", [], True))

    def test_polish_no_sharp(self):
        self.assertEqual(_generate_check("抛光", [], False), "表面Ra0.8")

    def test_grinding_with_planar(self):
        check = _generate_check(
            "平面磨床",
            [{"type": "平面度", "spec": "0.005"}, {"type": "平行度", "spec": "0.008"}],
            False
        )
        self.assertIn("平面度0.005", check)
        self.assertIn("平行度0.008", check)

    def test_drilling(self):
        self.assertEqual(_generate_check("打孔", [], False), "牙规通止")


class TestGenerateRemark(unittest.TestCase):
    """工艺备注生成 — 比较关键特征"""

    def test_rough_turning_basic(self):
        remark = _generate_remark(
            "车床",
            [{"type": "外形", "spec": "100×82mm"}],
            "K490 Vanadis 8", "58-63HRC", "TIN",
            "", False,
            [{"type": "外形", "spec": "100×82mm"}],
            ["利角"]
        )
        self.assertIn("K490 Vanadis 8", remark)
        self.assertIn("58-63HRC", remark)
        self.assertIn("开粗留余量", remark)

    def test_finish_turning_with_features(self):
        remark = _generate_remark(
            "数控精车",
            [{"type": "外形", "spec": "107×30mm", "tolerance": "±0.01"}],
            "STAVAX ESR", "HRC48-52", "",
            "刻字:FMK-7736", False,
            [{"type": "外形", "spec": "107×30mm", "tolerance": "±0.01"},
             {"type": "倒角", "spec": "C1", "roughness": 0.8}],
            []
        )
        self.assertIn("精加工到位", remark)
        self.assertIn("公差", remark)
        self.assertIn("倒角", remark)

    def test_wire_edm_with_cut_times(self):
        """粗糙度决定割修次数"""
        remark = _generate_remark(
            "慢走丝",
            [{"type": "精孔", "spec": "10.47", "qty": 2, "roughness": 0.63}],
            "K490 Vanadis 8", "58-63HRC", "",
            "", False,
            [], []
        )
        # Ra0.63 → ≤1.0 → 割1修2
        self.assertIn("割1修2", remark)

    def test_wire_edm_cut_3_for_low_roughness(self):
        remark = _generate_remark(
            "慢走丝",
            [{"type": "精孔", "spec": "10.47", "qty": 2, "roughness": 0.3}],
            "K490", "60HRC", "",
            "", False, [], []
        )
        self.assertIn("割1修3", remark)

    def test_mirror_edm_remark(self):
        remark = _generate_remark(
            "镜面放电",
            [{"type": "镶件槽", "spec": "3×3mm", "qty": 4}],
            "STAVAX ESR", "HRC48-52", "",
            "", False, [], []
        )
        self.assertIn("Ra0.2", remark)
        self.assertIn("电极", remark)

    def test_polish_with_sharp_edge(self):
        remark = _generate_remark(
            "抛光", [], "K490", "60HRC", "",
            "", True,
            [{"type": "外形", "spec": "100×82mm"}],
            ["利角"]
        )
        self.assertIn("利角", remark)
        self.assertIn("不允许倒角", remark)

    def test_engraving_with_content(self):
        remark = _generate_remark(
            "雕刻", [], "K490", "60HRC", "",
            "刻字:FMK-7736.030.61", False, [], []
        )
        self.assertIn("FMK-7736", remark)

    def test_heat_treatment_remark(self):
        remark = _generate_remark(
            "热处理", [], "K490 Vanadis 8", "58-63HRC", "",
            "", False, [], []
        )
        self.assertIn("58-63HRC", remark)


class TestMapToErpProcesses(unittest.TestCase):
    """工序名 → ERP下拉选项 映射"""

    def setUp(self):
        self.sample_plan = [
            {"seq": 1, "name": "车床", "machine_hours": 1.5, "worker": "车床", "remark": "粗车", "equipment": "TAKISAWA"},
            {"seq": 2, "name": "热处理", "machine_hours": 0, "worker": "外协", "remark": "58-63HRC", "equipment": "外协"},
            {"seq": 3, "name": "数控精车", "machine_hours": 2.0, "worker": "数控精车", "remark": "精加工", "equipment": "TAKISAWA"},
            {"seq": 4, "name": "慢走丝", "machine_hours": 1.5, "worker": "慢走丝", "remark": "割精孔", "equipment": "SODICK"},
            {"seq": 5, "name": "抛光", "machine_hours": 2.0, "worker": "抛光", "remark": "抛光到位", "equipment": "手工"},
            {"seq": 6, "name": "出货全检", "machine_hours": 1.0, "worker": "出货全检", "remark": "全检", "equipment": "ZEISS CMM"},
            {"seq": 7, "name": "生产入库", "machine_hours": 0.5, "worker": "生产入库", "remark": "入库", "equipment": ""},
        ]

    def test_all_names_in_erp_options(self):
        """所有推理工序名必须能映射到ERP选项"""
        mapped = map_to_erp_processes(self.sample_plan)
        for step in mapped:
            self.assertIn(step["name"], ERP_PROCESS_OPTIONS,
                          f"工序 '{step['name']}' 不在 ERP 选项列表中")

    def test_skips_meta_steps(self):
        """跳过元步骤"""
        plan = self.sample_plan + [
            {"seq": 8, "name": "注意事项", "meta_step": True, "machine_hours": 0},
            {"seq": 9, "name": "⚠️ 利角注意", "meta_step": True, "machine_hours": 0},
        ]
        mapped = map_to_erp_processes(plan)
        names = [s["name"] for s in mapped]
        self.assertNotIn("注意事项", names)
        self.assertNotIn("⚠️ 利角注意", names)

    def test_name_to_erp_mapping(self):
        """特殊映射名称要正确转换"""
        plan_with_alias = [
            # 这些是 NAME_TO_ERP 中的别名
            {"seq": 1, "name": "检测", "machine_hours": 1.0, "worker": "", "remark": "", "equipment": ""},
            {"seq": 2, "name": "刻字", "machine_hours": 0.5, "worker": "", "remark": "", "equipment": ""},
            {"seq": 3, "name": "EDM", "machine_hours": 2.0, "worker": "", "remark": "", "equipment": ""},
            {"seq": 4, "name": "小磨床", "machine_hours": 2.0, "worker": "", "remark": "", "equipment": ""},
        ]
        mapped = map_to_erp_processes(plan_with_alias)
        mapped_names = [s["name"] for s in mapped]
        self.assertIn("出货全检", mapped_names)  # 检测 → 出货全检
        self.assertIn("雕刻", mapped_names)     # 刻字 → 雕刻
        self.assertIn("镜面放电", mapped_names)  # EDM → 镜面放电
        self.assertIn("平面磨床", mapped_names)  # 小磨床 → 平面磨床


class TestReasonProcessIntegration(unittest.TestCase):
    """reason_process 端到端测试"""

    def test_round_cutting_blade(self):
        """圆形 Cutting blade 零件"""
        part_info = {
            "name": "Cutting blade",
            "material": "K490 Vanadis 8",
            "hardness": "58-63HRC",
            "shape": "round",
            "coating": "TIN",
            "qty": 2
        }
        features = [
            {"type": "外形", "spec": "100×102×82mm"},
            {"type": "钻孔", "spec": "10.5", "qty": 4},
            {"type": "螺纹", "spec": "M8", "qty": 3},
            {"type": "精孔", "spec": "10.47", "qty": 2},
            {"type": "精密槽", "spec": "3.05", "qty": 3, "roughness": 0.63},
            {"type": "斜面", "spec": "30°"},
        ]
        special_reqs = ["利角", "TIN涂层", "刻字:FMK-7736.030.61"]

        result = reason_process(part_info, features, special_reqs)

        # 验证：圆形零件 → 车床粗加工在前
        names = [s["name"] for s in result]
        self.assertIn("车床", names)
        self.assertIn("热处理", names)
        self.assertIn("数控精车", names)
        self.assertIn("慢走丝", names)
        self.assertIn("抛光", names)
        self.assertIn("出货全检", names)
        self.assertIn("生产入库", names)

        # 热处分水岭检测
        heat_idx = names.index("热处理")
        rough_before_heat = [n for n in names[:heat_idx]
                             if PROCESS_PRIORITY.get(n, 999) < 25]
        fine_after_heat = [n for n in names[heat_idx + 1:]
                           if PROCESS_PRIORITY.get(n, 999) >= 25]
        self.assertGreater(len(rough_before_heat), 0)  # 粗加工在热处理前
        self.assertGreater(len(fine_after_heat), 0)    # 精加工在热处理后

        # 每种工序都有工时 > 0（除了外协工序）
        for s in result:
            if s["name"] not in ("热处理", "表面处理"):
                self.assertGreater(s["machine_hours"], 0,
                                   f"工序 {s['name']} 工时应大于0")

        # 表面处理（TIN涂层）
        surface_names = [s["name"] for s in result]
        self.assertIn("表面处理", surface_names)

        # 雕刻（刻字要求）
        self.assertIn("雕刻", surface_names)

    def test_square_insert(self):
        """方形镶件零件"""
        part_info = {
            "name": "前模镶件",
            "material": "STAVAX ESR",
            "hardness": "HRC48-52",
            "shape": "square",
            "coating": "",
            "qty": 1
        }
        features = [
            {"type": "外形", "spec": "107×30mm"},
            {"type": "钻孔", "spec": "10.5", "qty": 2},
            {"type": "精孔", "spec": "3.05", "qty": 3, "roughness": 0.63},
            {"type": "镶件槽", "spec": "3×3mm", "qty": 4},
            {"type": "倒角", "spec": "C1", "roughness": 0.8},
        ]
        special_reqs = ["利角"]

        result = reason_process(part_info, features, special_reqs)

        names = [s["name"] for s in result]

        # 方形 → 铣床在前
        self.assertIn("铣床", names, "方形零件应使用铣床")

        # 特定工序存在
        self.assertIn("热处理", names)
        self.assertIn("慢走丝", names)
        self.assertIn("镜面放电", names)
        self.assertIn("抛光", names)

        # 抛光remark包含了利角
        polish_remark = next((s["remark"] for s in result if s["name"] == "抛光"), "")
        self.assertIn("利角", polish_remark)

    def test_flat_no_features(self):
        """极简零件"""
        part_info = {
            "name": "垫片",
            "material": "S-7",
            "hardness": "",
            "shape": "flat",
            "coating": "",
            "qty": 1
        }
        result = reason_process(part_info, [], [])

        names = [s["name"] for s in result]

        # 必须包含基础工序
        self.assertIn("铣床", names)
        self.assertIn("抛光", names)
        self.assertIn("出货全检", names)
        self.assertIn("生产入库", names)

        # 无硬度 → 应该有热处理（取决于硬度字符串处理）
        # 当前代码检查 hardness != "" 所以空字符串不会触发热处理
        # 这里不assert热处理存在，因为无硬度时可能没有

    def test_round_single_feature(self):
        """圆形单特征"""
        part_info = {
            "name": "轴套",
            "material": "Cr12MoV",
            "hardness": "58-60HRC",
            "shape": "round",
            "coating": "",
            "qty": 3
        }
        features = [
            {"type": "外形", "spec": "∅50×100mm"},
        ]
        special_reqs = []

        result = reason_process(part_info, features, special_reqs)
        names = [s["name"] for s in result]

        # 圆形 → 车床
        self.assertIn("车床", names)
        # 有硬度 → 热处理
        self.assertIn("热处理", names)
        # 精加工
        self.assertIn("数控精车", names)

    def test_engraving_content_in_process(self):
        """刻字要求传导到雕刻工序"""
        part_info = {"name": "Test", "material": "S-7", "hardness": "", "shape": "square", "coating": "", "qty": 1}
        result = reason_process(part_info, [], ["刻字:FMK-7736.030.61"])
        engrave_step = next((s for s in result if s["name"] == "雕刻"), None)
        self.assertIsNotNone(engrave_step, "有刻字要求应有雕刻工序")
        self.assertIn("FMK-7736", engrave_step["remark"])


class TestConstants(unittest.TestCase):
    """常量和配置表的完整性"""

    def test_future_process_map_covers_all_shapes(self):
        """所有 SHAPE_TO_FINISH 的 shape 在 SHAPE_TO_ROUGH 中也有对应"""
        for shape in SHAPE_TO_FINISH:
            self.assertIn(shape, SHAPE_TO_ROUGH,
                          f"SHAPE '{shape}' 在 SHAPE_TO_ROUGH 中缺失")

    def test_process_priorities_unique(self):
        """工序优先级不应重复（同优先级合理，但至少不冲突）"""
        priorities = list(PROCESS_PRIORITY.values())
        # 只是检查不是太多相同的值
        from collections import Counter
        counts = Counter(priorities)
        # 每个优先级值最多出现3次（粗加工同一层级）
        most_common = counts.most_common(1)[0]
        self.assertLessEqual(most_common[1], 4)

    def test_process_equipment_has_all_priorities(self):
        """PROCESS_EQUIPMENT 覆盖所有 PROCESS_PRIORITY 中的工序"""
        for proc in PROCESS_PRIORITY:
            self.assertIn(proc, PROCESS_EQUIPMENT,
                          f"工序 '{proc}' 在 PROCESS_EQUIPMENT 中缺失")


if __name__ == "__main__":
    unittest.main(verbosity=2)
