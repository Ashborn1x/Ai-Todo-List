from voice_task_manager.app import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("voice_task_manager.app:app", host="127.0.0.1", port=8000, reload=True)
