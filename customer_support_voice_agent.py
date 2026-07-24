from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

DATA_FILE = Path(__file__).with_name("tasks.json")
VOICE_OPTIONS = [
    "Kore",
    "Puck",
    "Aoede",
    "Charon",
    "Fenrir",
    "Leda",
    "Orus",
    "Zephyr",
]
COMMAND_MODEL = "gemini-3.6-flash"
TRANSCRIBE_MODEL = "gemini-3.6-flash"
TTS_MODEL = "gemini-3.1-flash-tts-preview"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_tasks() -> List[Dict[str, Any]]:
    if not DATA_FILE.exists():
        return []

    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_tasks(tasks: List[Dict[str, Any]]) -> None:
    DATA_FILE.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


def init_session_state() -> None:
    defaults = {
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "selected_voice": "Kore",
        "tasks": load_tasks(),
        "auto_voice_reply": True,
        "reply_style": "Concise",
        "last_result": None,
        "last_transcript": "",
        "last_input_mode": "text",
        "last_audio_path": None,
        "last_audio_text": "",
        "chat_messages": [],
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_client() -> Optional[genai.Client]:
    api_key = st.session_state.gemini_api_key.strip()
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def next_task_id(tasks: List[Dict[str, Any]]) -> int:
    return max((task["id"] for task in tasks), default=0) + 1


def add_task(tasks: List[Dict[str, Any]], title: str) -> Dict[str, Any]:
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


def find_task(
    tasks: List[Dict[str, Any]],
    task_id: Optional[int],
    title: Optional[str],
) -> Optional[Dict[str, Any]]:
    if task_id is not None:
        for task in tasks:
            if task["id"] == task_id:
                return task

    if title:
        target = normalize_text(title)
        for task in tasks:
            if normalize_text(task["title"]) == target:
                return task

        for task in tasks:
            if target in normalize_text(task["title"]):
                return task

    return None


def complete_task(
    tasks: List[Dict[str, Any]],
    task_id: Optional[int],
    title: Optional[str],
) -> Optional[Dict[str, Any]]:
    task = find_task(tasks, task_id, title)
    if not task:
        return None
    task["status"] = "done"
    task["completed_at"] = now_iso()
    save_tasks(tasks)
    return task


def delete_task(
    tasks: List[Dict[str, Any]],
    task_id: Optional[int],
    title: Optional[str],
) -> Optional[Dict[str, Any]]:
    task = find_task(tasks, task_id, title)
    if not task:
        return None
    tasks.remove(task)
    save_tasks(tasks)
    return task


def build_summary(tasks: List[Dict[str, Any]]) -> str:
    open_tasks = [task for task in tasks if task["status"] == "open"]
    done_tasks = [task for task in tasks if task["status"] == "done"]
    if not tasks:
        return "You have no tasks yet."
    if open_tasks:
        titles = ", ".join(f'{task["id"]}. {task["title"]}' for task in open_tasks[:5])
        return f"You have {len(open_tasks)} open tasks and {len(done_tasks)} completed tasks. Open tasks: {titles}."
    return f"All tasks are completed. You have {len(done_tasks)} completed tasks."


def build_spoken_task_list(tasks: List[Dict[str, Any]], style: str) -> str:
    open_tasks = [task for task in tasks if task["status"] == "open"]
    done_tasks = [task for task in tasks if task["status"] == "done"]

    if not tasks:
        return "You do not have any tasks yet."

    if not open_tasks:
        return f"All tasks are completed. You have {len(done_tasks)} completed tasks."

    limit = 3 if style == "Concise" else 6
    visible_tasks = open_tasks[:limit]
    spoken_items = [f'task {task["id"]}, {task["title"]}' for task in visible_tasks]

    if len(open_tasks) > limit:
        remainder = len(open_tasks) - limit
        trailing = f" There are also {remainder} more open tasks."
    else:
        trailing = ""

    joined = "; ".join(spoken_items)
    return (
        f"You have {len(open_tasks)} open tasks and {len(done_tasks)} completed tasks. "
        f"Open tasks are: {joined}.{trailing}"
    )


def build_spoken_response(result: Dict[str, Any], tasks: List[Dict[str, Any]]) -> str:
    style = st.session_state.reply_style
    action = result.get("action")
    task = result.get("task")

    if action == "add" and task:
        return f'Added task {task["id"]}. {task["title"]}.'

    if action == "complete" and task:
        return f'Completed task {task["id"]}. {task["title"]}.'

    if action == "delete" and task:
        return f'Deleted task {task["id"]}. {task["title"]}.'

    if action == "clear_completed":
        return result["message"]

    if action == "list":
        return build_spoken_task_list(tasks, style)

    return result["message"]


def build_assistant_reply(result: Dict[str, Any], tasks: List[Dict[str, Any]], input_mode: str) -> str:
    action = result.get("action")
    task = result.get("task")
    mode_prefix = "I heard you. " if input_mode == "voice" else ""

    if action == "add" and task:
        return f'{mode_prefix}Added task {task["id"]}, {task["title"]}. What would you like to do next?'

    if action == "complete" and task:
        return f'{mode_prefix}Completed task {task["id"]}, {task["title"]}. Anything else?'

    if action == "delete" and task:
        return f'{mode_prefix}Deleted task {task["id"]}, {task["title"]}. What is the next task?'

    if action == "clear_completed":
        return f'{mode_prefix}{result["message"]} What would you like to manage next?'

    if action == "list":
        return f'{mode_prefix}{build_spoken_task_list(tasks, st.session_state.reply_style)} What would you like to do with these tasks?'

    if result["ok"]:
        return f'{mode_prefix}{result["message"]} What would you like to do next?'

    return f'{mode_prefix}{result["message"]} You can say things like add task, show tasks, complete task 2, or delete task buy milk.'


def parse_with_rules(command: str, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    raw = command.strip()
    text = normalize_text(command)

    if not raw:
        return {"action": "unknown", "message": "Please say or type a command."}

    add_prefixes = ("add task ", "create task ", "new task ", "add ")
    complete_prefixes = ("complete task ", "finish task ", "done task ", "mark task ")
    delete_prefixes = ("delete task ", "remove task ")

    if text in {"show tasks", "list tasks", "what are my tasks", "read my tasks"}:
        return {"action": "list"}
    if text in {"clear completed", "remove completed tasks"}:
        return {"action": "clear_completed"}

    for prefix in add_prefixes:
        if text.startswith(prefix):
            title = raw[len(prefix):].strip()
            return {"action": "add", "title": title}

    for prefix in complete_prefixes:
        if text.startswith(prefix):
            target = raw[len(prefix):].strip()
            if target.isdigit():
                return {"action": "complete", "task_id": int(target)}
            return {"action": "complete", "title": target}

    for prefix in delete_prefixes:
        if text.startswith(prefix):
            target = raw[len(prefix):].strip()
            if target.isdigit():
                return {"action": "delete", "task_id": int(target)}
            return {"action": "delete", "title": target}

    if text.startswith("complete ") or text.startswith("finish "):
        target = raw.split(" ", 1)[1].strip()
        if target.isdigit():
            return {"action": "complete", "task_id": int(target)}
        return {"action": "complete", "title": target}

    if text.startswith("delete ") or text.startswith("remove "):
        target = raw.split(" ", 1)[1].strip()
        if target.isdigit():
            return {"action": "delete", "task_id": int(target)}
        return {"action": "delete", "title": target}

    guessed = find_task(tasks, None, raw)
    if guessed:
        return {"action": "complete", "task_id": guessed["id"]}

    return {
        "action": "unknown",
        "message": "I could not map that to add, list, complete, delete, or clear completed.",
    }


def parse_with_gemini(client: genai.Client, command: str, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    task_snapshot = [
        {"id": task["id"], "title": task["title"], "status": task["status"]}
        for task in tasks
    ]
    prompt = {
        "command": command,
        "tasks": task_snapshot,
        "schema": {
            "action": "add | list | complete | delete | clear_completed | unknown",
            "title": "string or null",
            "task_id": "integer or null",
            "message": "string or null",
        },
    }

    response = client.models.generate_content(
        model=COMMAND_MODEL,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are a voice command parser for a task manager. "
                "Return only JSON. Choose the action that best matches the command. "
                "If the command refers to a task by number or title, include task_id or title. "
                "If unclear, return action unknown with a short message."
            ),
            response_mime_type="application/json",
        ),
        contents=json.dumps(prompt),
    )

    content = response.text or "{}"
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid command parser response.")
    return parsed


def parse_command(command: str, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    client = get_client()
    if client:
        try:
            return parse_with_gemini(client, command, tasks)
        except Exception:
            pass
    return parse_with_rules(command, tasks)


def execute_command(command: str) -> Dict[str, Any]:
    tasks = st.session_state.tasks
    parsed = parse_command(command, tasks)
    action = parsed.get("action")

    if action == "add":
        title = (parsed.get("title") or "").strip()
        if not title:
            return {"ok": False, "action": "add", "message": "Task title is missing."}
        task = add_task(tasks, title)
        result = {"ok": True, "action": "add", "message": f'Added task {task["id"]}: {task["title"]}.', "task": task}
        result["speech_message"] = build_spoken_response(result, tasks)
        result["assistant_reply"] = build_assistant_reply(result, tasks, st.session_state.last_input_mode)
        return result

    if action == "list":
        result = {"ok": True, "action": "list", "message": build_summary(tasks), "tasks": tasks}
        result["speech_message"] = build_spoken_response(result, tasks)
        result["assistant_reply"] = build_assistant_reply(result, tasks, st.session_state.last_input_mode)
        return result

    if action == "complete":
        task = complete_task(tasks, parsed.get("task_id"), parsed.get("title"))
        if not task:
            result = {"ok": False, "action": "complete", "message": "I could not find that task to complete."}
            result["speech_message"] = build_spoken_response(result, tasks)
            result["assistant_reply"] = build_assistant_reply(result, tasks, st.session_state.last_input_mode)
            return result
        result = {"ok": True, "action": "complete", "message": f'Completed task {task["id"]}: {task["title"]}.', "task": task}
        result["speech_message"] = build_spoken_response(result, tasks)
        result["assistant_reply"] = build_assistant_reply(result, tasks, st.session_state.last_input_mode)
        return result

    if action == "delete":
        task = delete_task(tasks, parsed.get("task_id"), parsed.get("title"))
        if not task:
            result = {"ok": False, "action": "delete", "message": "I could not find that task to delete."}
            result["speech_message"] = build_spoken_response(result, tasks)
            result["assistant_reply"] = build_assistant_reply(result, tasks, st.session_state.last_input_mode)
            return result
        result = {"ok": True, "action": "delete", "message": f'Deleted task {task["id"]}: {task["title"]}.', "task": task}
        result["speech_message"] = build_spoken_response(result, tasks)
        result["assistant_reply"] = build_assistant_reply(result, tasks, st.session_state.last_input_mode)
        return result

    if action == "clear_completed":
        before = len(tasks)
        tasks[:] = [task for task in tasks if task["status"] != "done"]
        save_tasks(tasks)
        removed = before - len(tasks)
        result = {"ok": True, "action": "clear_completed", "message": f"Removed {removed} completed tasks."}
        result["speech_message"] = build_spoken_response(result, tasks)
        result["assistant_reply"] = build_assistant_reply(result, tasks, st.session_state.last_input_mode)
        return result

    result = {"ok": False, "action": action or "unknown", "message": parsed.get("message", "I could not understand that command.")}
    result["speech_message"] = build_spoken_response(result, tasks)
    result["assistant_reply"] = build_assistant_reply(result, tasks, st.session_state.last_input_mode)
    return result


def add_chat_turn(role: str, content: str) -> None:
    st.session_state.chat_messages.append({"role": role, "content": content})


def run_and_record_command(command: str, input_mode: str) -> None:
    cleaned = command.strip()
    if not cleaned:
        return

    st.session_state.last_input_mode = input_mode
    if input_mode == "text":
        st.session_state.last_transcript = ""
    add_chat_turn("user", cleaned)
    st.session_state.last_result = execute_command(cleaned)
    add_chat_turn("assistant", st.session_state.last_result["assistant_reply"])


def generate_audio(message: str) -> Optional[str]:
    client = get_client()
    if not client or not message.strip():
        return None

    response = client.models.generate_content(
        model=TTS_MODEL,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=st.session_state.selected_voice
                    )
                )
            ),
        ),
        contents=message,
    )

    audio_data = response.candidates[0].content.parts[0].inline_data.data
    audio_path = Path(tempfile.gettempdir()) / f"task_manager_{uuid.uuid4()}.wav"
    audio_path.write_bytes(audio_data)
    return str(audio_path)


def transcribe_audio_file(audio_file: Any) -> str:
    client = get_client()
    if not client:
        raise ValueError("Gemini API key is required for voice transcription.")

    suffix = Path(getattr(audio_file, "name", "voice.wav")).suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(audio_file.getbuffer())
        temp_path = Path(tmp.name)

    try:
        uploaded_file = client.files.upload(file=str(temp_path))
        response = client.models.generate_content(
            model=TRANSCRIBE_MODEL,
            contents=[
                "Transcribe this audio exactly. Return only the spoken words without extra commentary.",
                uploaded_file,
            ],
        )
        return (response.text or "").strip()
    finally:
        if temp_path.exists():
            temp_path.unlink()


def render_sidebar() -> None:
    with st.sidebar:
        st.title("Settings")
        st.session_state.gemini_api_key = st.text_input(
            "Gemini API Key",
            value=st.session_state.gemini_api_key,
            type="password",
            help="Required for speech-to-text, smart command parsing, and spoken responses.",
        )
        st.session_state.selected_voice = st.selectbox(
            "Voice",
            options=VOICE_OPTIONS,
            index=VOICE_OPTIONS.index(st.session_state.selected_voice),
        )
        st.session_state.auto_voice_reply = st.toggle(
            "Auto voice reply",
            value=st.session_state.auto_voice_reply,
            help="Generate and play a spoken response after each command.",
        )
        st.session_state.reply_style = st.segmented_control(
            "Reply style",
            options=["Concise", "Detailed"],
            default=st.session_state.reply_style,
        )
        st.caption(f"Task data file: `{DATA_FILE.name}`")

        if st.button("Reload Tasks"):
            st.session_state.tasks = load_tasks()
            st.session_state.last_result = {
                "ok": True,
                "action": "reload",
                "message": "Reloaded tasks from disk.",
                "speech_message": "Reloaded tasks from disk.",
                "assistant_reply": "Reloaded your tasks from disk. What would you like to do next?",
            }
            add_chat_turn("assistant", st.session_state.last_result["assistant_reply"])

        if st.button("Delete All Tasks"):
            st.session_state.tasks = []
            save_tasks(st.session_state.tasks)
            st.session_state.last_result = {
                "ok": True,
                "action": "delete_all",
                "message": "Deleted all tasks.",
                "speech_message": "Deleted all tasks.",
                "assistant_reply": "All tasks were deleted. You can start a new list whenever you want.",
            }
            add_chat_turn("assistant", st.session_state.last_result["assistant_reply"])


def render_task_table(tasks: List[Dict[str, Any]]) -> None:
    if not tasks:
        st.info("No tasks yet. Add one with text or voice.")
        return

    for task in tasks:
        status = "Open" if task["status"] == "open" else "Done"
        st.markdown(f'**{task["id"]}. {task["title"]}**')
        st.caption(f"Status: {status} | Created: {task['created_at']}")


def render_quick_actions() -> None:
    st.subheader("Quick Actions")

    with st.form("quick_add_form", clear_on_submit=True):
        new_task = st.text_input("Add a task", placeholder="Prepare weekly report")
        submitted = st.form_submit_button("Add Task")
        if submitted and new_task.strip():
            run_and_record_command(f"add task {new_task}", "text")

    open_tasks = [task for task in st.session_state.tasks if task["status"] == "open"]
    if open_tasks:
        labels = [f'{task["id"]}: {task["title"]}' for task in open_tasks]
        selected = st.selectbox("Complete a task", options=labels)
        if st.button("Mark Complete"):
            task_id = int(selected.split(":", 1)[0])
            run_and_record_command(f"complete task {task_id}", "text")


def render_chat_assistant() -> None:
    st.subheader("Task assistant")
    st.caption("Talk to it naturally. It can add, list, complete, and delete tasks.")

    if not st.session_state.chat_messages:
        suggestions = {
            ":material/add_task: Add a task": "Add task prepare the weekly report",
            ":material/format_list_bulleted: Show my tasks": "Show tasks",
            ":material/check_circle: Complete a task": "Complete task 1",
        }
        selected = st.pills(
            "Try asking",
            list(suggestions.keys()),
            label_visibility="collapsed",
        )
        if selected:
            run_and_record_command(suggestions[selected], "text")
            st.rerun()

    for message in st.session_state.chat_messages:
        avatar = ":material/person:" if message["role"] == "user" else ":material/smart_toy:"
        with st.chat_message(message["role"], avatar=avatar):
            st.write(message["content"])

    prompt = st.chat_input(
        "Ask the task assistant",
        accept_audio=True,
        submit_mode="disable",
    )

    if not prompt:
        return

    try:
        if getattr(prompt, "audio", None) is not None:
            transcript = transcribe_audio_file(prompt.audio)
            st.session_state.last_transcript = transcript
            run_and_record_command(transcript, "voice")
        elif getattr(prompt, "text", "").strip():
            run_and_record_command(prompt.text, "text")
    except Exception as exc:
        st.session_state.last_result = {
            "ok": False,
            "action": "error",
            "message": str(exc),
            "speech_message": str(exc),
            "assistant_reply": f"I ran into an error: {exc}",
        }
        add_chat_turn("assistant", st.session_state.last_result["assistant_reply"])

    st.rerun()


def render_last_result() -> None:
    result = st.session_state.last_result
    if not result:
        return

    with st.container(border=True):
        if result["ok"]:
            st.success(result["message"])
        else:
            st.error(result["message"])

        if st.session_state.last_transcript:
            st.caption(f'Last voice command: "{st.session_state.last_transcript}"')

        assistant_reply = result.get("assistant_reply")
        if assistant_reply:
            st.write(assistant_reply)

        speech_message = result.get("assistant_reply") or result.get("speech_message") or result["message"]

        if st.session_state.gemini_api_key and st.session_state.auto_voice_reply and speech_message:
            try:
                if st.session_state.last_audio_text != speech_message:
                    st.session_state.last_audio_path = generate_audio(speech_message)
                    st.session_state.last_audio_text = speech_message
            except Exception as exc:
                st.caption(f"Audio response unavailable: {exc}")
                return

            if st.session_state.last_audio_path:
                st.audio(
                    st.session_state.last_audio_path,
                    format="audio/wav",
                    autoplay=True,
                )

        if st.session_state.gemini_api_key and speech_message and st.button("Generate voice reply", icon=":material/volume_up:"):
            try:
                st.session_state.last_audio_path = generate_audio(speech_message)
                st.session_state.last_audio_text = speech_message
            except Exception as exc:
                st.caption(f"Audio response unavailable: {exc}")
                return

            st.audio(
                st.session_state.last_audio_path,
                format="audio/wav",
                autoplay=True,
            )


def run_streamlit() -> None:
    st.set_page_config(
        page_title="Voice-Controlled Task Manager",
        page_icon="🎙️",
        layout="wide",
    )

    init_session_state()
    render_sidebar()

    st.title("Voice-Controlled Task Manager")
    st.write("Manage tasks by chatting or speaking to the assistant. Tasks are saved locally in `tasks.json`.")

    left_col, right_col = st.columns([1, 1])

    with left_col:
        render_chat_assistant()
        render_last_result()

    with right_col:
        render_quick_actions()
        st.subheader("Tasks")
        render_task_table(st.session_state.tasks)


if __name__ == "__main__":
    run_streamlit()
