"""ERP 工艺工作流 V3+ — 多Agent编排版

节点（ERP交互层）：
  - login / detect_new_orders / drawing_fetch
  - erp_reconnect / process_filler
  - routing_filler (已废弃，保留导入兼容)

Agent（AI推理层，由 supervisor_agent_run 节点调度）：
  - VisionAgent / CNCProgrammingAgent / ReviewAgent / SupervisorAgent
"""

from workflows.erp_process.nodes.login import node_login
from workflows.erp_process.nodes.detect_new_orders import node_detect_new_orders
from workflows.erp_process.nodes.drawing_fetch import node_fetch_drawing
from workflows.erp_process.nodes.erp_reconnect import node_erp_reconnect
from workflows.erp_process.nodes.process_filler import node_fill_plan
from workflows.erp_process.nodes.routing_filler import node_fill_routing

__all__ = [
    "node_login",
    "node_detect_new_orders",
    "node_fetch_drawing",
    "node_erp_reconnect",
    "node_fill_plan",
    "node_fill_routing",
]
