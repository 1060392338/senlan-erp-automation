"""
SupervisorAgent — 上层调度 Agent

职责：
  - 自动发现所有 WorkflowAgent 子类
  - 将 Agent 暴露为 tools，供 LLM 调用
  - 按任务路由到对应 Agent

当前实现：关键词匹配
未来实现：LLM 决策 + 多 Agent 编排
"""

from agents.base import WorkflowAgent
from typing import Any, Optional


class SupervisorAgent:
    def __init__(self):
        self._agents: dict[str, WorkflowAgent] = {}
        self._discover()

    def _discover(self):
        """自动扫描 workflows/ 目录发现 WorkflowAgent 子类"""
        import importlib
        from pathlib import Path

        workflows_dir = Path(__file__).parent.parent / "workflows"
        if not workflows_dir.exists():
            return

        for entry in workflows_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            agent_mod_path = entry / "agent.py"
            if not agent_mod_path.exists():
                continue

            try:
                module = importlib.import_module(
                    f"workflows.{entry.name}.agent"
                )
                for attr_name in dir(module):
                    cls = getattr(module, attr_name)
                    if (
                        isinstance(cls, type)
                        and issubclass(cls, WorkflowAgent)
                        and cls is not WorkflowAgent
                    ):
                        agent = cls()
                        self._agents[agent.agent_name] = agent
            except Exception as e:
                print(f"[Supervisor] 加载 {entry.name}/agent.py 失败: {e}")

    @property
    def agents(self) -> dict[str, WorkflowAgent]:
        return dict(self._agents)

    def get_agent_tools(self) -> list[dict]:
        """所有 Agent 暴露为 tools，供 LLM 调用"""
        return [a.agent_tool for a in self._agents.values()]

    def route(self, task: str) -> list[dict]:
        """
        根据任务描述路由到对应 Agent（当前简单实现）
        返回: [{"agent": name, "order": 1}, ...]
        """
        results = []
        for name, agent in self._agents.items():
            if any(kw in task for kw in [name, agent.agent_description[:10]]):
                results.append({"agent": name, "order": len(results) + 1})
        if not results:
            results = [{"agent": "erp_process_agent", "order": 1}]
        return results

    def run_task(self, task: str, input_data: Optional[dict] = None) -> list[dict]:
        """按任务串行执行 Agent"""
        route = self.route(task)
        results = []
        for r in route:
            agent = self._agents.get(r["agent"])
            if agent:
                result = agent.run(input_data or {})
                results.append({r["agent"]: result})
        return results
