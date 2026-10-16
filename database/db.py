#!/usr/bin/env python3
r"""Database layer for the Agentic AI Project Management System.

Single place your teammate's agents import from:
    from database.db import (
        create_project, get_project, get_projects,
        save_tasks, get_project_tasks,
        get_employees, get_employee,
        save_assignments, get_employee_workload,
    )

Rules enforced here (not in agent code):
- Parameterized queries only (no f-string SQL).
- Foreign keys ON for every connection.
- One transaction per multi-write call (all-or-nothing).
- Assignments live ONLY in tasks.assigned_employee_id (NULL = unassigned).
- Task deadlines must be <= parent project deadline.
"""
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "projectops.db"

ACTIVE_STATUSES = ("todo", "in_progress")
TASK_STATUSES = ("todo", "in_progress", "completed", "blocked", "cancelled")
PROJECT_STATUSES = ("planning", "active", "completed", "on_hold", "cancelled")


def _connect(db_path=None):
    """Open a connection with FK enforcement + dict-like rows."""
    con = sqlite3.connect(str(db_path or DEFAULT_DB))
    con.execute("PRAGMA foreign_keys = ON")
    con.row_factory = sqlite3.Row
    return con


def _dict(row):
    return dict(row) if row is not None else None


# ---------- projects ----------

def create_project(name, description, deadline, status="planning", db_path=None):
    """Create a project. Returns the new project_id."""
    if not name or not deadline:
        raise ValueError("name and deadline are required")
    if status not in PROJECT_STATUSES:
        raise ValueError(f"bad status {status!r}, must be one of {PROJECT_STATUSES}")
    con = _connect(db_path)
    try:
        with con:
            cur = con.execute(
                "INSERT INTO projects (name, deadline, status, description)"
                " VALUES (?, ?, ?, ?)",
                (name, deadline, status, description or ""),
            )
        return cur.lastrowid
    finally:
        con.close()


def get_project(project_id, db_path=None):
    """One project as a dict, or None if missing."""
    con = _connect(db_path)
    try:
        return _dict(con.execute(
            "SELECT project_id, name, deadline, status, description"
            " FROM projects WHERE project_id = ?", (project_id,)).fetchone())
    finally:
        con.close()


def get_projects(db_path=None):
    """All projects as a list of dicts."""
    con = _connect(db_path)
    try:
        return [_dict(r) for r in con.execute(
            "SELECT project_id, name, deadline, status, description"
            " FROM projects ORDER BY project_id")]
    finally:
        con.close()


# ---------- tasks ----------

def save_tasks(project_id, tasks, db_path=None):
    """Insert many tasks for one project. Returns [new task_ids].

    tasks: list of dicts with keys:
      task_name (required), required_role (required), estimated_hours (required),
      status='todo', deadline=None (-> project deadline), assigned_employee_id=None
    """
    if not tasks:
        return []
    con = _connect(db_path)
    try:
        proj = con.execute(
            "SELECT project_id, deadline FROM projects WHERE project_id = ?",
            (project_id,)).fetchone()
        if proj is None:
            raise ValueError(f"project {project_id} does not exist")
        new_ids = []
        with con:  # single transaction: all tasks or none
            for t in tasks:
                if not t.get("task_name") or not t.get("required_role"):
                    raise ValueError(f"task needs task_name + required_role: {t!r}")
                hours = t.get("estimated_hours", 0)
                if not isinstance(hours, int) or hours <= 0:
                    raise ValueError(f"estimated_hours must be a positive int: {t!r}")
                status = t.get("status", "todo")
                if status not in TASK_STATUSES:
                    raise ValueError(f"bad task status {status!r}")
                deadline = t.get("deadline") or proj["deadline"]
                if deadline > proj["deadline"]:
                    raise ValueError(
                        f"task deadline {deadline} exceeds project deadline {proj['deadline']}")
                emp = t.get("assigned_employee_id")
                # NOTE: no role-vs-skill fit check here by design.
                # The Assignment Agent decides which role fits which
                # required_role; the DB only guarantees the row exists.
                if emp is not None and con.execute(
                        "SELECT 1 FROM employees WHERE employee_id = ?", (emp,)).fetchone() is None:
                    raise ValueError(f"employee {emp} does not exist")
                cur = con.execute(
                    "INSERT INTO tasks (project_id, task_name, required_role,"
                    " estimated_hours, status, assigned_employee_id, deadline)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (project_id, t["task_name"], t["required_role"],
                     hours, status, emp, deadline))
                new_ids.append(cur.lastrowid)
        return new_ids
    finally:
        con.close()


def get_project_tasks(project_id, db_path=None):
    """All tasks of one project as a list of dicts."""
    con = _connect(db_path)
    try:
        return [_dict(r) for r in con.execute(
            "SELECT task_id, project_id, task_name, required_role,"
            " estimated_hours, status, assigned_employee_id, deadline"
            " FROM tasks WHERE project_id = ? ORDER BY task_id", (project_id,))]
    finally:
        con.close()


# ---------- employees ----------

def get_employees(db_path=None):
    """All employees as a list of dicts."""
    con = _connect(db_path)
    try:
        return [_dict(r) for r in con.execute(
            "SELECT employee_id, name, role, available_hours, email"
            " FROM employees ORDER BY employee_id")]
    finally:
        con.close()


def get_employee(employee_id, db_path=None):
    """One employee as a dict, or None if missing."""
    con = _connect(db_path)
    try:
        return _dict(con.execute(
            "SELECT employee_id, name, role, available_hours, email"
            " FROM employees WHERE employee_id = ?", (employee_id,)).fetchone())
    finally:
        con.close()


# ---------- assignments + workload ----------

def save_assignments(assignments, db_path=None):
    """Assign/unassign tasks. Returns number of rows updated.

    assignments: list of dicts {"task_id": int, "employee_id": int | None}.
    employee_id None = unassign (sets NULL). One transaction.
    """
    if not assignments:
        return 0
    con = _connect(db_path)
    try:
        with con:
            n = 0
            for a in assignments:
                tid, emp = a["task_id"], a.get("employee_id")
                # NOTE: no role-vs-skill fit check here by design (see above).
                if con.execute(
                        "SELECT 1 FROM tasks WHERE task_id = ?", (tid,)).fetchone() is None:
                    raise ValueError(f"task {tid} does not exist")
                if emp is not None and con.execute(
                        "SELECT 1 FROM employees WHERE employee_id = ?", (emp,)).fetchone() is None:
                    raise ValueError(f"employee {emp} does not exist")
                con.execute(
                    "UPDATE tasks SET assigned_employee_id = ? WHERE task_id = ?",
                    (emp, tid))
                n += 1
        return n
    finally:
        con.close()


def get_employee_workload(employee_id, db_path=None):
    """Active load vs capacity for one employee.

    Active = SUM(estimated_hours) of their todo + in_progress tasks.
    Returns dict {employee_id, name, available_hours, active_hours,
                  active_tasks, overloaded}. Raises ValueError if missing.
    """
    con = _connect(db_path)
    try:
        emp = con.execute(
            "SELECT employee_id, name, role, available_hours FROM employees"
            " WHERE employee_id = ?", (employee_id,)).fetchone()
        if emp is None:
            raise ValueError(f"employee {employee_id} does not exist")
        row = con.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(estimated_hours), 0) AS h"
            " FROM tasks WHERE assigned_employee_id = ?"
            " AND status IN ('todo', 'in_progress')", (employee_id,)).fetchone()
        return {
            "employee_id": emp["employee_id"],
            "name": emp["name"],
            "role": emp["role"],
            "available_hours": emp["available_hours"],
            "active_hours": row["h"],
            "active_tasks": row["n"],
            "overloaded": row["h"] > emp["available_hours"],
        }
    finally:
        con.close()
