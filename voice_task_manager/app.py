from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR
from .live_session import handle_live_socket

app = FastAPI(title="Realtime Voice Task Manager")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws/live")
async def live_socket(websocket: WebSocket) -> None:
    await handle_live_socket(websocket)
