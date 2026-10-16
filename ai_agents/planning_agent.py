#!/usr/bin/env python3
r"""Planning Agent for the Agentic AI Project Management System.

Built with the OpenAI Agents SDK.
- Model is served via OpenRouter (set OPENROUTER_API_KEY).
- Tracing goes to OpenAI tracing (set OPENAI_API_KEY) -- NOT disabled,
  so every run appears in your OpenAI traces dashboard.
- All data access goes through database/db.py (no raw SQL here).

Run from the project root (D:\ProjectOpsAI):
    set OPENROUTER_API_KEY=sk-or-...
    set OPENAI_API_KEY=sk-...
    python agents\planning_agent.py "Build a booking website, deadline 2027-03-01"
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import Agent, Runner, function_tool
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from database.db import (
    create_project,
    get_employees,
    get_project_tasks,
    get_projects,
    save_tasks,
)


def _load_dotenv():
    """Minimal .env loader (KEY=value per line, no dependency needed)."""
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

MODEL_NAME = os.environ.get(
    "PLANNING_MODEL", "nvidia/nemotron-3.5-super-vl:free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

VALID_ROLES = (
    "Backend Developer",
    "Frontend Developer",
    "AI Engineer",
    "QA Engineer",
    "UI/UX Designer",
)

INSTRUCTIONS = """\
You are the Planning Agent of an AI project-management system. Your job is to
turn a short project brief into a concrete plan stored in the database.

Available roles (you MUST use exactly these strings for required_role):
Backend Developer, Frontend Developer, AI Engineer, QA Engineer, UI/UX Designer.

Workflow for every request:
1. If the brief is vague, first call get_employees_tool to see team roles/capacity
   and get_projects_tool to avoid duplicating an existing project.
2. Call create_project_tool with (name, description, deadline). Dates are YYYY-MM-DD.
3. Break the work into 6-10 granular tasks. Each task needs: task_name,
   required_role (one of the 5 above), a realistic estimated_hours integer,
   and a deadline on or BEFORE the project deadline. Leave every task unassigned
   (assigned_employee_id null) with status "todo" -- the Assignment Agent owns staffing.
4. Persist them with ONE save_tasks_tool call, then read them back with
   get_project_tasks_tool to verify.
5. Reply with a short summary: project id, task list (role/hours/deadline each),
   total estimated hours, and finish with the exact line:
   READY_FOR_ASSIGNMENT project_id=<id>
"""


def _model():
    """Chat-Completions model via OpenRouter (free-tier models don't do Responses API).

    Needs OPENROUTER_API_KEY at run time. Tracing still goes to OpenAI.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    client = AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    return OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client)


# ---------- tools: thin wrappers over database/db.py ----------

@function_tool
def create_project_tool(name: str, description: str, deadline: str) -> int:
    """Create a new project row. Returns the new project_id. Use once per brief."""
    return create_project(name, description, deadline)


@function_tool
def save_tasks_tool(project_id: int, tasks: list) -> list:
    """Save the full task breakdown for a project in one transaction.

    Each task: {"task_name": str, "required_role": str, "estimated_hours": int,
    "deadline": "YYYY-MM-DD"}. Returns the new task_ids.
    """
    return save_tasks(project_id, tasks)


@function_tool
def get_project_tasks_tool(project_id: int) -> list:
    """Read back all tasks of a project to verify what was saved."""
    return get_project_tasks(project_id)


@function_tool
def get_employees_tool() -> list:
    """List the 10 employees with their roles and available hours."""
    return get_employees()


@function_tool
def get_projects_tool() -> list:
    """List existing projects to avoid creating duplicates."""
    return get_projects()


def build_planning_agent() -> Agent:
    """Construct the agent. Import-safe: key only required when called."""
    # Tracing is intentionally left ENABLED (the SDK default): traces are sent
    # to OpenAI tracing, which authenticates with OPENAI_API_KEY.
    return Agent(
        name="Planning Agent",
        instructions=INSTRUCTIONS,
        tools=[
            create_project_tool,
            save_tasks_tool,
            get_project_tasks_tool,
            get_employees_tool,
            get_projects_tool,
        ],
        model=_model(),
    )


async def _run(brief: str) -> str:
    agent = build_planning_agent()
    result = await Runner.run(agent, brief, context={"workflow_name": "project-planning"})
    return result.final_output


def main() -> None:
    brief = " ".join(sys.argv[1:]) or (
        "Build a small online booking website for a clinic,"
        " with admin panel, deadline 2027-03-01")
    print(asyncio.run(_run(brief)))


if __name__ == "__main__":
    main()
