from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import os
import traceback
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types

load_dotenv()

DATA_FILE = Path(__file__).with_name("tasks.json")
STATIC_DIR = Path(__file__).with_name("static")
LIVE_MODEL = "gemini-3.1-flash-live-preview"
DEFAULT_VOICE = "Kore"
logger = logging.getLogger("realtime_voice_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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


def fetch_json(url: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers=headers or {"User-Agent": "Voice-Controlled-Task-Manager/1.0"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def web_search(query: str) -> dict[str, Any]:
    cleaned = query.strip()
    if not cleaned:
        return {"ok": False, "message": "Search query is required."}

    results: list[dict[str, str]] = []

    try:
        ddg_url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {
                "q": cleaned,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            }
        )
        ddg = fetch_json(ddg_url)
        abstract = ddg.get("AbstractText", "").strip()
        abstract_url = ddg.get("AbstractURL", "").strip()
        heading = ddg.get("Heading", "").strip() or cleaned

        if abstract:
            results.append(
                {
                    "title": heading,
                    "snippet": abstract,
                    "url": abstract_url or "https://duckduckgo.com/",
                    "source": "duckduckgo_instant_answer",
                }
            )

        for topic in ddg.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(
                    {
                        "title": topic.get("FirstURL", cleaned).rsplit("/", 1)[-1].replace("_", " "),
                        "snippet": topic["Text"],
                        "url": topic.get("FirstURL", "https://duckduckgo.com/"),
                        "source": "duckduckgo_related_topic",
                    }
                )
            elif isinstance(topic, dict):
                for child in topic.get("Topics", [])[:3]:
                    if child.get("Text"):
                        results.append(
                            {
                                "title": child.get("FirstURL", cleaned).rsplit("/", 1)[-1].replace("_", " "),
                                "snippet": child["Text"],
                                "url": child.get("FirstURL", "https://duckduckgo.com/"),
                                "source": "duckduckgo_related_topic",
                            }
                        )
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)

    if not results:
        try:
            wiki_search_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": cleaned,
                    "format": "json",
                    "utf8": 1,
                }
            )
            wiki_search = fetch_json(wiki_search_url)
            hits = wiki_search.get("query", {}).get("search", [])
            for hit in hits[:3]:
                title = hit.get("title", cleaned)
                summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title)
                try:
                    summary = fetch_json(summary_url)
                except Exception:
                    continue
                extract = summary.get("extract", "").strip()
                if extract:
                    results.append(
                        {
                            "title": summary.get("title", title),
                            "snippet": extract,
                            "url": summary.get("content_urls", {})
                            .get("desktop", {})
                            .get("page", f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}"),
                            "source": "wikipedia_summary",
                        }
                    )
        except Exception as exc:
            logger.warning("Wikipedia search failed: %s", exc)

    if not results:
        return {
            "ok": False,
            "message": "No web results found or the network request failed.",
        }

    return {
        "ok": True,
        "query": cleaned,
        "results": [
            {
                "index": index + 1,
                **item,
            }
            for index, item in enumerate(results[:5])
        ],
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
        task = add_task(title)
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


def build_live_config(voice_name: str) -> types.LiveConnectConfig:
    system_instruction = (
        "You are a realtime voice assistant for a task manager. "
        "Keep replies short, helpful, and spoken naturally. "
        "When the user wants to add, list, complete, delete, or clear tasks, "
        "use the available tools instead of pretending. "
        "When the user refers to tasks with phrases like the first one, the second one, "
        "that task, or tell me more about the first one, use get_listed_task_details, "
        "complete_listed_task, or delete_listed_task when appropriate. "
        "For general knowledge questions or questions not answered by local task data, "
        "use the search_web tool and answer from the search results. "
        "If the user asks follow-up questions like give me more details, explain that, "
        "tell me more, or what about the first result, use get_follow_up_details, "
        "get_last_context, or get_search_result_details instead of saying you forgot. "
        "If the user just says tell me more with no target, first use get_follow_up_details. "
        "When camera frames are available, use the latest visual context to identify or "
        "describe objects the user points at. Be honest when an object is unclear, partially "
        "visible, or cannot be identified confidently, and ask the user to reposition it. "
        "Do not claim you searched unless you actually used the search_web tool. "
        "After each tool result, tell the user what happened and ask a short follow-up question when appropriate."
    )

    tool_definitions = [
        {
            "function_declarations": [
                {
                    "name": "add_task",
                    "description": "Create a new task.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "title": {
                                "type": "STRING",
                                "description": "The task title to create.",
                            }
                        },
                        "required": ["title"],
                    },
                },
                {
                    "name": "list_tasks",
                    "description": "List open tasks and counts.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "limit": {
                                "type": "INTEGER",
                                "description": "Maximum number of open tasks to include.",
                            }
                        },
                    },
                },
                {
                    "name": "complete_task",
                    "description": "Mark a task complete by number or title.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target": {
                                "type": "STRING",
                                "description": "The task number or title to complete.",
                            }
                        },
                        "required": ["target"],
                    },
                },
                {
                    "name": "delete_task",
                    "description": "Delete a task by number or title.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target": {
                                "type": "STRING",
                                "description": "The task number or title to delete.",
                            }
                        },
                        "required": ["target"],
                    },
                },
                {
                    "name": "clear_completed",
                    "description": "Delete all completed tasks.",
                    "parameters": {"type": "OBJECT", "properties": {}},
                },
                {
                    "name": "get_listed_task_details",
                    "description": "Get details for a task from the most recently shown task list using phrases like first, second, or a task title.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target": {
                                "type": "STRING",
                                "description": "The task reference, for example first, second, 3, or part of the task title.",
                            }
                        },
                        "required": ["target"],
                    },
                },
                {
                    "name": "complete_listed_task",
                    "description": "Complete a task from the most recently shown task list using references like first one or second one.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target": {
                                "type": "STRING",
                                "description": "The task reference, for example first, second, 3, or part of the task title.",
                            }
                        },
                        "required": ["target"],
                    },
                },
                {
                    "name": "delete_listed_task",
                    "description": "Delete a task from the most recently shown task list using references like first one or second one.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target": {
                                "type": "STRING",
                                "description": "The task reference, for example first, second, 3, or part of the task title.",
                            }
                        },
                        "required": ["target"],
                    },
                },
                {
                    "name": "search_web",
                    "description": "Search the web for current or missing information when local task data does not answer the question.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "query": {
                                "type": "STRING",
                                "description": "The web search query.",
                            }
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "get_last_context",
                    "description": "Get the most recent tool/search context for follow-up questions like more details or explain that.",
                    "parameters": {"type": "OBJECT", "properties": {}},
                },
                {
                    "name": "get_search_result_details",
                    "description": "Get details for one of the most recent web search results by result number or title.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "target": {
                                "type": "STRING",
                                "description": "The previous result number or title to expand, for example 1 or the result title.",
                            }
                        },
                        "required": ["target"],
                    },
                },
                {
                    "name": "get_follow_up_details",
                    "description": "Get the default follow-up target for vague requests like tell me more or explain that.",
                    "parameters": {"type": "OBJECT", "properties": {}},
                },
            ]
        }
    ]

    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name or DEFAULT_VOICE
                )
            )
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=True
            )
        ),
        input_audio_transcription={},
        output_audio_transcription={},
        system_instruction=system_instruction,
        tools=tool_definitions,
    )


app = FastAPI(title="Realtime Voice Task Manager")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws/live")
async def live_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("WebSocket accepted from client.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY is missing.")
        await websocket.send_json(
            {
                "type": "error",
                "message": "GEMINI_API_KEY is not set on the server.",
            }
        )
        await websocket.close()
        return

    client = genai.Client(api_key=api_key)

    try:
        config_message = await websocket.receive_json()
        logger.info("Received config message: %s", config_message)
    except Exception:
        logger.exception("Failed to receive initial config message.")
        await websocket.close()
        return

    voice_name = str(config_message.get("voice", DEFAULT_VOICE))
    config = build_live_config(voice_name)
    session_state = new_session_state()

    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            logger.info("Connected to Gemini Live model %s.", LIVE_MODEL)
            receive_task = asyncio.create_task(forward_gemini_to_browser(session, websocket, session_state))
            try:
                await forward_browser_to_gemini(session, websocket)
            finally:
                receive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receive_task
    except WebSocketDisconnect:
        logger.info("Browser WebSocket disconnected.")
        return
    except Exception as exc:
        logger.error("Live session failed: %s", exc)
        logger.debug(traceback.format_exc())
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        finally:
            await websocket.close()


async def forward_browser_to_gemini(session: Any, websocket: WebSocket) -> None:
    user_activity_open = False
    audio_chunk_count = 0
    audio_byte_count = 0
    video_frame_count = 0

    while True:
        message = await websocket.receive_json()
        message_type = message.get("type")
        if message_type not in {"audio", "video"}:
            logger.info("Browser message type: %s", message_type)

        if message_type == "audio":
            if not user_activity_open:
                continue
            audio_data = base64.b64decode(message["data"])
            audio_chunk_count += 1
            audio_byte_count += len(audio_data)
            await session.send_realtime_input(
                audio=types.Blob(data=audio_data, mime_type="audio/pcm;rate=16000")
            )
        elif message_type == "video":
            mime_type = str(message.get("mime_type", "image/jpeg"))
            if mime_type not in {"image/jpeg", "image/png"}:
                logger.warning("Rejected unsupported camera frame type: %s", mime_type)
                continue
            try:
                frame_data = base64.b64decode(message["data"], validate=True)
            except (KeyError, ValueError, binascii.Error):
                logger.warning("Rejected malformed camera frame.")
                continue
            if not frame_data or len(frame_data) > 2_000_000:
                logger.warning("Rejected camera frame with %d bytes.", len(frame_data))
                continue
            video_frame_count += 1
            if video_frame_count == 1 or video_frame_count % 10 == 0:
                logger.info(
                    "Forwarded camera frame %d (%d bytes).",
                    video_frame_count,
                    len(frame_data),
                )
            await session.send_realtime_input(
                video=types.Blob(data=frame_data, mime_type=mime_type)
            )
        elif message_type == "activity_start":
            if user_activity_open:
                logger.info("Ignoring duplicate activity_start from browser.")
                continue
            user_activity_open = True
            audio_chunk_count = 0
            audio_byte_count = 0
            logger.info("User speech turn started.")
            await session.send_realtime_input(activity_start=types.ActivityStart())
        elif message_type == "activity_end":
            if not user_activity_open:
                logger.info("Ignoring activity_end with no open user activity.")
                continue
            user_activity_open = False
            logger.info(
                "User speech turn ended with %d audio chunks (%d bytes).",
                audio_chunk_count,
                audio_byte_count,
            )
            await session.send_realtime_input(activity_end=types.ActivityEnd())
        elif message_type == "audio_end":
            logger.info("Ignoring audio_end because manual activity detection is enabled.")
        elif message_type == "text":
            text = str(message.get("text", "")).strip()
            if text:
                if user_activity_open:
                    logger.info("Closing stale user activity before text turn.")
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                    user_activity_open = False
                await session.send_realtime_input(activity_start=types.ActivityStart())
                await session.send_realtime_input(text=text)
                await session.send_realtime_input(activity_end=types.ActivityEnd())
        elif message_type == "ping":
            await websocket.send_json({"type": "pong"})
        else:
            logger.warning("Unknown browser message: %s", message)


async def forward_gemini_to_browser(session: Any, websocket: WebSocket, session_state: dict[str, Any]) -> None:
    turn_number = 0
    while True:
        turn_number += 1
        logger.info("Waiting for Gemini response turn %d.", turn_number)
        async for message in session.receive():
            await handle_gemini_message(session, websocket, session_state, message)


async def handle_gemini_message(
    session: Any,
    websocket: WebSocket,
    session_state: dict[str, Any],
    message: Any,
) -> None:
    if message.tool_call:
        logger.info("Gemini requested tool call(s).")
        responses = []
        for function_call in message.tool_call.function_calls:
            tool_result = call_tool(function_call.name, function_call.args or {}, session_state)
            session_state["last_tool_name"] = function_call.name
            session_state["last_tool_result"] = tool_result
            if function_call.name == "search_web" and tool_result.get("ok"):
                session_state["last_search_query"] = tool_result.get("query")
                session_state["last_search_results"] = tool_result.get("results", [])
                first_result = tool_result.get("results", [])
                if first_result:
                    session_state["last_follow_up_target"] = {
                        "kind": "search_result",
                        "result": first_result[0],
                    }
            if function_call.name in {"add_task", "list_tasks", "complete_task", "delete_task", "clear_completed"}:
                session_state["last_task_action"] = {
                    "name": function_call.name,
                    "result": tool_result,
                }
                session_state["last_follow_up_target"] = {
                    "kind": "task_action",
                    "action": session_state["last_task_action"],
                }
            if function_call.name == "list_tasks" and tool_result.get("tasks") is not None:
                session_state["last_listed_tasks"] = tool_result.get("tasks", [])
            if function_call.name == "get_listed_task_details" and tool_result.get("ok"):
                session_state["last_follow_up_target"] = {
                    "kind": "task_detail",
                    "task": tool_result.get("task"),
                }
            if function_call.name in {"complete_listed_task", "delete_listed_task"} and tool_result.get("ok"):
                session_state["last_follow_up_target"] = {
                    "kind": "task_detail",
                    "task": tool_result.get("resolved_task"),
                }
            if function_call.name == "get_search_result_details" and tool_result.get("ok"):
                session_state["last_follow_up_target"] = {
                    "kind": "search_result",
                    "result": tool_result.get("result"),
                }
            response_payload: Dict[str, Any] = {
                "name": function_call.name,
                "response": tool_result,
            }
            if getattr(function_call, "id", None):
                response_payload["id"] = function_call.id
            responses.append(response_payload)
            await websocket.send_json(
                {
                    "type": "tool_result",
                    "name": function_call.name,
                    "result": tool_result,
                }
            )

        if responses:
            await session.send_tool_response(function_responses=responses)

    server_content = message.server_content
    if not server_content:
        return

    if server_content.input_transcription and server_content.input_transcription.text:
        await websocket.send_json(
            {
                "type": "input_transcript",
                "text": server_content.input_transcription.text,
                "finished": server_content.input_transcription.finished,
            }
        )

    if server_content.output_transcription and server_content.output_transcription.text:
        await websocket.send_json(
            {
                "type": "output_transcript",
                "text": server_content.output_transcription.text,
                "finished": server_content.output_transcription.finished,
            }
        )

    if server_content.model_turn:
        for part in server_content.model_turn.parts or []:
            if part.text:
                await websocket.send_json({"type": "assistant_text", "text": part.text})
            if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                await websocket.send_json(
                    {
                        "type": "audio",
                        "mime_type": part.inline_data.mime_type,
                        "data": base64.b64encode(part.inline_data.data).decode("ascii"),
                    }
                )

    if server_content.turn_complete:
        logger.info("Gemini turn complete.")
        await websocket.send_json({"type": "turn_complete"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("realtime_voice_server:app", host="127.0.0.1", port=8000, reload=True)
