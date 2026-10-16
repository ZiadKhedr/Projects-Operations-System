#!/usr/bin/env python3
r"""Migrate D:\ProjectOpsAI\database\projectops.db to the simplified 3-table schema.

- Drops legacy complex tables (no duplicate tables/records).
- Creates employees / projects / tasks only.
- Task assignments live ONLY in tasks.assigned_employee_id (NULL = unassigned).
- Enforces foreign keys, runs verification queries.
Usage: python setup_simple_db.py
"""
import sqlite3
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "projectops.db"

EMPLOYEES = [
    (1, "Ahmed El-Sayed", "Backend Developer", 30),
    (2, "Mariam Adel", "Frontend Developer", 20),
    (3, "Youssef Naguib", "AI Engineer", 15),
    (4, "Salma Ibrahim", "QA Engineer", 25),
    (5, "Menna Khalil", "UI/UX Designer", 10),
    (6, "Karim Mansour", "Backend Developer", 35),
    (7, "Heba Fathy", "Frontend Developer", 24),
    (8, "Omar Farouk", "AI Engineer", 20),
    (9, "Mahmoud Samy", "QA Engineer", 28),
    (10, "Dina Tarek", "UI/UX Designer", 16),
]

PROJECTS = [
    (1, "E-commerce Website", "2026-12-15", "active", "Full-stack online store with catalog, cart and payments."),
    (2, "Customer Support AI Assistant", "2026-11-30", "planning", "LLM chatbot with RAG over help-center docs."),
]

# (task_id, project_id, task_name, required_role, estimated_hours, status, assigned_employee_id, deadline)
TASKS = [
    (1, 1, "Database schema design", "Backend Developer", 12, "completed", 1, "2026-07-20"),
    (2, 1, "REST API development", "Backend Developer", 20, "in_progress", 1, "2026-10-20"),
    (3, 1, "Frontend product page", "Frontend Developer", 15, "in_progress", 2, "2026-11-10"),
    (4, 1, "Payment integration", "Backend Developer", 10, "todo", None, "2026-12-01"),
    (5, 2, "Chatbot model training", "AI Engineer", 18, "in_progress", 3, "2026-10-15"),
    (6, 2, "Training data preparation", "Backend Developer", 8, "todo", None, "2026-09-30"),
    (7, 2, "Automated testing", "QA Engineer", 10, "todo", 4, "2026-11-15"),
    (8, 2, "Chat widget UI", "UI/UX Designer", 12, "todo", 5, "2026-11-20"),
]

LEGACY_TABLES = [
    "activity_logs", "project_risks", "task_assignments",
    "task_dependencies", "tasks", "projects",
    "employee_skills", "employees",
]

SCHEMA_SQL = """
CREATE TABLE employees (
    employee_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    available_hours INTEGER NOT NULL CHECK (available_hours >= 0)
);
CREATE TABLE projects (
    project_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    deadline TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('planning', 'active', 'completed', 'on_hold', 'cancelled')),
    description TEXT DEFAULT ''
);
CREATE TABLE tasks (
    task_id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects (project_id) ON DELETE CASCADE,
    task_name TEXT NOT NULL,
    required_role TEXT NOT NULL,
    estimated_hours INTEGER NOT NULL CHECK (estimated_hours > 0),
    status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'completed', 'blocked', 'cancelled')),
    assigned_employee_id INTEGER REFERENCES employees (employee_id) ON DELETE SET NULL,
    deadline TEXT NOT NULL
);
CREATE INDEX idx_tasks_project ON tasks (project_id);
CREATE INDEX idx_tasks_assignee ON tasks (assigned_employee_id);
CREATE INDEX idx_tasks_status ON tasks (status);
CREATE INDEX idx_tasks_deadline ON tasks (deadline);
"""


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(DB_PATH))
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        with con:
            for tbl in LEGACY_TABLES:
                con.execute(f"DROP TABLE IF EXISTS {tbl}")
            con.executescript(SCHEMA_SQL)
        con.execute("PRAGMA foreign_keys = ON")

        with con:
            con.executemany(
                "INSERT INTO employees (employee_id, name, role, available_hours) VALUES (?, ?, ?, ?)",
                EMPLOYEES,
            )
            con.executemany(
                "INSERT INTO projects (project_id, name, deadline, status, description) VALUES (?, ?, ?, ?, ?)",
                PROJECTS,
            )
            con.executemany(
                "INSERT INTO tasks (task_id, project_id, task_name, required_role, estimated_hours, status, assigned_employee_id, deadline)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                TASKS,
            )

        # ---- verification ----
        print(f"Database: {DB_PATH}")
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        print("Tables:", tables)
        assert tables == ["employees", "projects", "tasks"], f"Unexpected tables: {tables}"

        cols = [r[1] for r in con.execute("PRAGMA table_info(employees)")]
        assert "assigned_tasks" not in cols, "employees.assigned_tasks must NOT exist"
        print("Employees columns:", cols)

        fk_violations = con.execute("PRAGMA foreign_key_check").fetchall()
        assert not fk_violations, fk_violations
        print("Foreign keys: OK (0 violations)")

        for tbl, expected in (("employees", 10), ("projects", 2), ("tasks", 8)):
            n = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            assert n == expected, f"{tbl}: expected {expected}, got {n}"
            print(f"{tbl}: {n} rows OK")

        orphan_tasks = con.execute(
            "SELECT COUNT(*) FROM tasks t LEFT JOIN projects p ON p.project_id = t.project_id WHERE p.project_id IS NULL"
        ).fetchone()[0]
        orphan_emp = con.execute(
            "SELECT COUNT(*) FROM tasks WHERE assigned_employee_id IS NOT NULL AND assigned_employee_id NOT IN (SELECT employee_id FROM employees)"
        ).fetchone()[0]
        assert orphan_tasks == 0 and orphan_emp == 0
        print("All foreign keys reference existing records: OK")

        print("\n-- Tasks assigned to employee 1 (Emma Thompson) --")
        for row in con.execute(
            "SELECT task_id, task_name, required_role, estimated_hours, status FROM tasks WHERE assigned_employee_id = 1 ORDER BY task_id"
        ):
            print(row)

        print("\n-- Unassigned tasks (assigned_employee_id IS NULL) --")
        for row in con.execute(
            "SELECT task_id, task_name, required_role, estimated_hours, status, project_id FROM tasks WHERE assigned_employee_id IS NULL ORDER BY task_id"
        ):
            print(row)

        print("\n-- Workload vs availability --")
        for name, avail, load in con.execute(
            "SELECT e.name, e.available_hours, COALESCE(SUM(t.estimated_hours), 0) "
            "FROM employees e LEFT JOIN tasks t ON t.assigned_employee_id = e.employee_id "
            "AND t.status IN ('todo', 'in_progress') "
            "GROUP BY e.employee_id ORDER BY e.employee_id"
        ):
            flag = "OVERLOAD" if load > avail else "ok"
            print(f"{name}: {load}h assigned / {avail}h available [{flag}]")

        print("\nSimplified database ready and verified.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
