from __future__ import annotations

from typing import Any

from .search_service import web_search
from .task_service import (
    add_task,
    clear_completed,
    complete_task,
    delete_task,
    list_tasks,
    normalize_text,
)

def new_session_state() -> dict[str, Any]:
    return {
        "last_tool_name": None,
        "last_tool_result": None,
        "last_search_query": None,
        "last_search_results": [],
        "last_task_action": None,
        "last_listed_tasks": [],
        "last_follow_up_target": None,
    }


def get_last_context(session_state: dict[str, Any]) -> dict[str, Any]:
    last_search_results = session_state.get("last_search_results", [])
    compact_results = [
        {
            "index": item["index"],
            "title": item["title"],
            "snippet": item["snippet"],
            "url": item["url"],
        }
        for item in last_search_results[:5]
    ]
    return {
        "last_tool_name": session_state.get("last_tool_name"),
        "last_task_action": session_state.get("last_task_action"),
        "last_listed_tasks": session_state.get("last_listed_tasks"),
        "last_search_query": session_state.get("last_search_query"),
        "last_search_results": compact_results,
        "last_tool_result": session_state.get("last_tool_result"),
        "last_follow_up_target": session_state.get("last_follow_up_target"),
    }


def get_search_result_details(session_state: dict[str, Any], target: str) -> dict[str, Any]:
    cleaned = target.strip()
    if not cleaned:
        return {"ok": False, "message": "A result number or title is required."}

    results = session_state.get("last_search_results", [])
    if not results:
        return {"ok": False, "message": "There are no previous search results in memory yet."}

    selected = None
    if cleaned.isdigit():
        wanted = int(cleaned)
        for item in results:
            if item.get("index") == wanted:
                selected = item
                break
    else:
        target_norm = normalize_text(cleaned)
        for item in results:
            if normalize_text(item.get("title", "")) == target_norm:
                selected = item
                break
        if selected is None:
            for item in results:
                if target_norm in normalize_text(item.get("title", "")):
                    selected = item
                    break

    if selected is None:
        return {"ok": False, "message": "I could not match that to a previous search result."}

    return {"ok": True, "result": selected}


def get_follow_up_details(session_state: dict[str, Any]) -> dict[str, Any]:
    follow_up_target = session_state.get("last_follow_up_target")
    if not follow_up_target:
        return {
            "ok": False,
            "message": "There is no previous result or action to expand yet.",
        }

    if follow_up_target.get("kind") == "search_result":
        result = follow_up_target.get("result")
        if result:
            return {"ok": True, "result": result}

    if follow_up_target.get("kind") == "task_action":
        action = follow_up_target.get("action")
        if action:
            return {"ok": True, "result": action}

    return {
        "ok": False,
        "message": "I do not have a usable follow-up target in memory yet.",
    }


def get_listed_task_details(session_state: dict[str, Any], target: str) -> dict[str, Any]:
    cleaned = target.strip()
    if not cleaned:
        return {"ok": False, "message": "A task number or position is required."}

    tasks = session_state.get("last_listed_tasks", [])
    if not tasks:
        return {"ok": False, "message": "There is no recent task list in memory yet."}

    lowered = normalize_text(cleaned)
    ordinal_map = {
        "first": 1,
        "1": 1,
        "one": 1,
        "second": 2,
        "2": 2,
        "two": 2,
        "third": 3,
        "3": 3,
        "three": 3,
        "fourth": 4,
        "4": 4,
        "four": 4,
        "fifth": 5,
        "5": 5,
        "five": 5,
    }

    selected = None
    if lowered in ordinal_map:
        position = ordinal_map[lowered] - 1
        if 0 <= position < len(tasks):
            selected = tasks[position]
    elif cleaned.isdigit():
        wanted_id = int(cleaned)
        for task in tasks:
            if task.get("id") == wanted_id:
                selected = task
                break
    else:
        for task in tasks:
            if normalize_text(task.get("title", "")) == lowered:
                selected = task
                break
        if selected is None:
            for task in tasks:
                if lowered in normalize_text(task.get("title", "")):
                    selected = task
                    break

    if selected is None:
        return {"ok": False, "message": "I could not match that to the last shown tasks."}

    return {"ok": True, "task": selected}


def complete_listed_task(session_state: dict[str, Any], target: str) -> dict[str, Any]:
    lookup = get_listed_task_details(session_state, target)
    if not lookup.get("ok"):
        return lookup

    task = lookup["task"]
    result = complete_task(str(task["id"]))
    if result.get("ok"):
        result["resolved_task"] = task
    return result


def delete_listed_task(session_state: dict[str, Any], target: str) -> dict[str, Any]:
    lookup = get_listed_task_details(session_state, target)
    if not lookup.get("ok"):
        return lookup

    task = lookup["task"]
    result = delete_task(str(task["id"]))
    if result.get("ok"):
        result["resolved_task"] = task
    return result


def call_tool(name: str, args: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
    if name == "add_task":
        title = str(args.get("title", "")).strip()
        if not title:
            return {"ok": False, "message": "Task title is required."}
        raw_scheduled_for = args.get("scheduled_for")
        raw_schedule_text = args.get("schedule_text")
        scheduled_for = (
            str(raw_scheduled_for).strip() if raw_scheduled_for is not None else None
        )
        schedule_text = (
            str(raw_schedule_text).strip() if raw_schedule_text is not None else None
        )
        try:
            task = add_task(title, scheduled_for, schedule_text)
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "task": task}

    if name == "list_tasks":
        limit = int(args.get("limit", 8))
        return list_tasks(limit=max(1, min(limit, 20)))

    if name == "complete_task":
        target = str(args.get("target", "")).strip()
        if not target:
            return {"ok": False, "message": "Task number or title is required."}
        return complete_task(target)

    if name == "delete_task":
        target = str(args.get("target", "")).strip()
        if not target:
            return {"ok": False, "message": "Task number or title is required."}
        return delete_task(target)

    if name == "clear_completed":
        return clear_completed()

    if name == "search_web":
        query = str(args.get("query", "")).strip()
        return web_search(query)

    if name == "get_last_context":
        return get_last_context(session_state)

    if name == "get_search_result_details":
        target = str(args.get("target", "")).strip()
        return get_search_result_details(session_state, target)

    if name == "get_follow_up_details":
        return get_follow_up_details(session_state)

    if name == "get_listed_task_details":
        target = str(args.get("target", "")).strip()
        return get_listed_task_details(session_state, target)

    if name == "complete_listed_task":
        target = str(args.get("target", "")).strip()
        return complete_listed_task(session_state, target)

    if name == "delete_listed_task":
        target = str(args.get("target", "")).strip()
        return delete_listed_task(session_state, target)

    return {"ok": False, "message": f"Unknown tool: {name}"}
