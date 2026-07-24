from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import traceback
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


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
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

    return {"ok": False, "message": f"Unknown tool: {name}"}


def build_live_config(voice_name: str) -> types.LiveConnectConfig:
    system_instruction = (
        "You are a realtime voice assistant for a task manager. "
        "Keep replies short, helpful, and spoken naturally. "
        "When the user wants to add, list, complete, delete, or clear tasks, "
        "use the available tools instead of pretending. "
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
            ]
        }
    ]

    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        explicit_vad_signal=True,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name or DEFAULT_VOICE
                )
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

    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            logger.info("Connected to Gemini Live model %s.", LIVE_MODEL)
            receive_task = asyncio.create_task(forward_gemini_to_browser(session, websocket))
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
    while True:
        message = await websocket.receive_json()
        message_type = message.get("type")
        logger.info("Browser message type: %s", message_type)

        if message_type == "audio":
            audio_data = base64.b64decode(message["data"])
            await session.send_realtime_input(
                audio=types.Blob(data=audio_data, mime_type="audio/pcm;rate=16000")
            )
        elif message_type == "activity_start":
            await session.send_realtime_input(activity_start=types.ActivityStart())
        elif message_type == "activity_end":
            await session.send_realtime_input(activity_end=types.ActivityEnd())
        elif message_type == "audio_end":
            await session.send_realtime_input(audio_stream_end=True)
        elif message_type == "text":
            text = str(message.get("text", "")).strip()
            if text:
                await session.send_realtime_input(text=text)
        elif message_type == "ping":
            await websocket.send_json({"type": "pong"})
        else:
            logger.warning("Unknown browser message: %s", message)


async def forward_gemini_to_browser(session: Any, websocket: WebSocket) -> None:
    async for message in session.receive():
        if message.tool_call:
            logger.info("Gemini requested tool call(s).")
            responses = []
            for function_call in message.tool_call.function_calls:
                tool_result = call_tool(function_call.name, function_call.args or {})
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
            continue

        if server_content.input_transcription and server_content.input_transcription.text:
            logger.info("Input transcription: %s", server_content.input_transcription.text)
            await websocket.send_json(
                {
                    "type": "input_transcript",
                    "text": server_content.input_transcription.text,
                    "finished": server_content.input_transcription.finished,
                }
            )

        if server_content.output_transcription and server_content.output_transcription.text:
            logger.info("Output transcription: %s", server_content.output_transcription.text)
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
                    logger.info("Assistant text part received.")
                    await websocket.send_json({"type": "assistant_text", "text": part.text})
                if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                    logger.info("Assistant audio chunk received.")
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
