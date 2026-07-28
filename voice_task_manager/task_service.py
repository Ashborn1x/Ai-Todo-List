from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from .config import DATA_FILE

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_tasks() -> list[dict[str, Any]]:
    if not DATA_FILE.exists():
        return []

    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_tasks(tasks: list[dict[str, Any]]) -> None:
    DATA_FILE.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def next_task_id(tasks: list[dict[str, Any]]) -> int:
    return max((task["id"] for task in tasks), default=0) + 1


def add_task(title: str) -> dict[str, Any]:
    tasks = load_tasks()
    task = {
        "id": next_task_id(tasks),
        "title": title.strip(),
        "status": "open",
        "created_at": now_iso(),
        "completed_at": None,
    }
    tasks.append(task)
    save_tasks(tasks)
    return task


def find_task(tasks: list[dict[str, Any]], target: str) -> Optional[dict[str, Any]]:
    cleaned = target.strip()
    if not cleaned:
        return None

    if cleaned.isdigit():
        task_id = int(cleaned)
        for task in tasks:
            if task["id"] == task_id:
                return task

    normalized = normalize_text(cleaned)
    for task in tasks:
        if normalize_text(task["title"]) == normalized:
            return task

    for task in tasks:
        if normalized in normalize_text(task["title"]):
            return task

    return None


def list_tasks(limit: int = 8) -> dict[str, Any]:
    tasks = load_tasks()
    open_tasks = [task for task in tasks if task["status"] == "open"]
    done_tasks = [task for task in tasks if task["status"] == "done"]
    visible = open_tasks[:limit]
    summary = [
        {"id": task["id"], "title": task["title"], "status": task["status"]}
        for task in visible
    ]
    return {
        "open_count": len(open_tasks),
        "completed_count": len(done_tasks),
        "tasks": summary,
    }


def complete_task(target: str) -> dict[str, Any]:
    tasks = load_tasks()
    task = find_task(tasks, target)
    if not task:
        return {"ok": False, "message": "Task not found."}
    task["status"] = "done"
    task["completed_at"] = now_iso()
    save_tasks(tasks)
    return {"ok": True, "task": task}


def delete_task(target: str) -> dict[str, Any]:
    tasks = load_tasks()
    task = find_task(tasks, target)
    if not task:
        return {"ok": False, "message": "Task not found."}
    tasks.remove(task)
    save_tasks(tasks)
    return {"ok": True, "task": task}


def clear_completed() -> dict[str, Any]:
    tasks = load_tasks()
    before = len(tasks)
    tasks = [task for task in tasks if task["status"] != "done"]
    save_tasks(tasks)
    return {"removed": before - len(tasks)}
