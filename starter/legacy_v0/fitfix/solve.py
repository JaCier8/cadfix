"""Reference run inside the container (used as Harbor's solution/solve.sh): heuristic solver, tools only."""
import os

from .agents import solver
from .env import FitFixEnv

if __name__ == "__main__":
    env = FitFixEnv(os.environ.get("FITFIX_TASK_DIR", "/task"), os.environ.get("FITFIX_OUT_DIR", "/output"))
    solver(env)
    print(f"solver finished after {env.calls} tool calls")
