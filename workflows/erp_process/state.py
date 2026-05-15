"""ERP 工艺工作流状态定义（V2 — 飞书图纸驱动版）"""

from typing import TypedDict, Optional, Any


class ERPState(TypedDict):
    """贯穿整个流程的状态

    只包含可序列化数据（纯 dict、str、int、list、bool）。
    运行时服务（浏览器、LLM 等）通过 run config 的 `configurable.ctx` 传递。
    """

    # ── 输入 ──
    input: dict
    tenant_config: dict                 # 租户配置纯字典（可序列化）

    # ── Phase 1: ERP检测 + 飞书拉图 ──
    session_id: Optional[str]
    prod_no: Optional[str]              # 当前处理的生产单号（关键关联键）
    new_orders: Optional[list[dict]]    # detect_new_orders 的输出
    pending_order_idx: int              # 当前处理的订单索引
    drawing_url: Optional[str]
    drawing_local_path: Optional[str]   # 本地缓存的图纸路径
    drawing_matched: bool               # 图纸是否匹配成功

    # ── Phase 2: Offline AI ──
    part_info: Optional[dict]           # L1: {name, material, hardness, qty, coating}
    features: Optional[list]            # L2: [{type, spec, tolerance, roughness}]
    process_plan: Optional[list]        # 14道工序
    cnc_code: Optional[dict]            # {takisawa: str, sodick: dict, segments: list, feature_code_map: dict}

    # ── Phase 3: Online ERP ──
    plan_saved: bool
    routing_saved: bool
    cnc_saved: bool

    # ── 全局 ──
    errors: list[str]
    checkpoint: int  # 使用 Checkpoint 枚举值（int）


from enum import IntEnum


class Checkpoint(IntEnum):
    """工作流检查点枚举 — 替代所有硬编码魔数"""
    START = 0
    LOGIN_DONE = 5
    ORDERS_DETECTED = 7                # V2 新增：检测到新生产单
    DRAWING_FETCHED = 10
    PROCESS_PLANNED = 18
    CNC_GENERATED = 20
    RECONNECTED = 22
    PLAN_FILLED = 25
    ROUTING_FILLED = 30
    LOGIN_FAILED = -1
