from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import STATIC_DIR
from .live_session import handle_live_socket
from .task_service import (
    complete_task,
    delete_task,
    dismiss_task_alarm,
    get_all_tasks,
    snooze_task_alarm,
)


class SnoozeRequest(BaseModel):
    minutes: int = Field(ge=1, le=1440)

app = FastAPI(title="Realtime Voice Task Manager")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws/live")
async def live_socket(websocket: WebSocket) -> None:
    await handle_live_socket(websocket)


@app.get("/api/tasks")
def tasks() -> list[dict]:
    return get_all_tasks()


@app.post("/api/tasks/{task_id}/snooze")
def snooze(task_id: int, request: SnoozeRequest) -> dict:
    result = snooze_task_alarm(task_id, request.minutes)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.post("/api/tasks/{task_id}/dismiss-alarm")
def dismiss_alarm(task_id: int) -> dict:
    result = dismiss_task_alarm(task_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@app.post("/api/tasks/{task_id}/complete")
def complete(task_id: int) -> dict:
    result = complete_task(str(task_id))
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@app.delete("/api/tasks/{task_id}")
def delete(task_id: int) -> dict:
    result = delete_task(str(task_id))
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result
