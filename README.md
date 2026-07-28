# Voice-Controlled Task Manager

A local Gemini Live assistant with realtime voice conversation, camera vision,
task management, conversation context, and web-search fallback.

## Features

- Realtime microphone input and spoken Gemini responses
- Multi-turn conversation within one persistent Live API session
- Optional camera input for object identification and scene questions
- Local todo storage in `tasks.json`
- Task tools for adding, listing, completing, and deleting items
- Web search for current information
- Typed input as an alternative to voice

## Setup

1. Install Python 3.11 or newer.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Add your Gemini key to `.env`:

   ```dotenv
   GEMINI_API_KEY=your-key-here
   ```

## Run

```powershell
python realtime_voice_server.py
```

Open `http://127.0.0.1:8000`, click **Start conversation**, and allow
microphone access. Camera access is separate and remains off until you click
**Start camera**.

## Project Structure

```text
voice_task_manager/
  app.py             FastAPI routes and static-file mounting
  config.py          Paths, environment loading, and model settings
  live_session.py    Gemini Live WebSocket and media transport
  search_service.py  Web-search providers
  task_service.py    Local task persistence and operations
  tools.py           Gemini tool dispatch and session memory
static/
  css/styles.css     Application styling
  js/app.js          Browser session and media orchestration
  js/audio-utils.js  PCM conversion and audio utilities
  js/ui.js           Safe DOM rendering
  index.html         Page structure
realtime_voice_server.py
                     Compatibility launcher
```

## Data And Privacy

- The server runs locally on `127.0.0.1`.
- Tasks stay in the local `tasks.json` file.
- Microphone audio and camera frames are sent to Gemini while their respective
  controls are active.
- Camera frames are resized and sent once every two seconds.
- Stopping the camera or conversation stops the browser media tracks.

The older `customer_support_voice_agent.py` Streamlit prototype remains in the
repository for reference, but the FastAPI realtime application is the primary
app.
