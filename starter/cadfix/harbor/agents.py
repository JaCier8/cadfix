"""Custom Harbor agents (host side; needs `pip install harbor`). Use with
`harbor run -p harbor_tasks/judge --agent-import-path cadfix.harbor.agents:StopEarlyAgent` (run from the repo root,
or with the repo on PYTHONPATH).

StopEarlyAgent: the stop-early baseline. One inspection call inside the task container (get_task), then submit.
"""
from __future__ import annotations

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


class StopEarlyAgent(BaseAgent):
    # the task declares the cadfix MCP server; this agent calls the same tools in-process via cadfix.env.cli
    capabilities = AgentCapabilities(mcp_servers=True)

    @staticmethod
    def name() -> str:
        return "cadfix-stop-early"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        return

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        res = await environment.exec("python3 -m cadfix.env.cli get_task submit", timeout_sec=600)
        (self.logs_dir / "stop_early.txt").write_text(f"exit {res.return_code}\n{res.stdout or ''}\n{res.stderr or ''}")
