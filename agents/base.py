"""
WorkflowAgent ABC — 所有工作流 Agent 的统一接口

设计目标：
  - 单 Agent 工作流和多 Agent 工作流对外接口一致
  - Supervisor 不关心内部实现，只通过 agent_name/run() 调度
  - 新增工作流 = 继承此类 + 实现 run()，零侵入
"""

from abc import ABC, abstractmethod
from typing import Optional
from typing import Any


class WorkflowAgent(ABC):
    """所有工作流 Agent 的基类"""

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Agent 唯一标识名，用于 Supervisor 调度"""

    @property
    @abstractmethod
    def agent_description(self) -> str:
        """Agent 能力描述，供上层 LLM 理解用途"""

    @abstractmethod
    def input_schema(self) -> dict:
        """JSON Schema 描述输入格式"""

    @abstractmethod
    def run(self, input_data: dict, thread_id: Optional[str] = None) -> dict:
        """执行工作流，返回结果"""

    @property
    def agent_tool(self) -> dict:
        """将本 Agent 暴露为 tool schema，供 Supervisor 使用"""
        return {
            "name": self.agent_name,
            "description": self.agent_description,
            "input_schema": self.input_schema(),
        }
