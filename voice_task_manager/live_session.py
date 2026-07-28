from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging
import os
import traceback
from typing import Any, Dict

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from .config import DEFAULT_VOICE, LIVE_MODEL
from .tools import call_tool, new_session_state

logger = logging.getLogger(__name__)

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


async def handle_live_socket(websocket: WebSocket) -> None:
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
