# Voice-Controlled Task Manager

This project is a Streamlit task manager that supports:

- typed commands like `add task buy milk`
- voice commands using Gemini audio understanding
- spoken confirmations using Gemini text-to-speech
- persistent local storage in `tasks.json`

## Features

- Add, list, complete, and delete tasks
- Quick action form for manual task entry
- Natural-language command parsing
- Local task persistence without a database
- Optional voice workflow when a Gemini API key is set

## Run

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Start the app:
   ```bash
   streamlit run customer_support_voice_agent.py
   ```

3. In the sidebar, enter your Gemini API key if you want:
   - voice transcription
   - smarter natural-language parsing
   - spoken audio responses

## Realtime voice mode

The Streamlit app is still push-to-talk. For low-latency voice conversation, use the separate realtime server:

```bash
set GEMINI_API_KEY=your-key-here
python realtime_voice_server.py
```

Then open:

```text
http://127.0.0.1:8000
```

This realtime mode:

- keeps a persistent Gemini Live session open
- streams microphone audio continuously
- plays assistant audio back automatically
- exposes local task tools so the voice assistant can add, list, complete, and delete tasks
- falls back to web search for questions that are not answered by local task data

## What this app is now

This can run as a local assistant on your machine:

- local browser UI
- local Python server
- local task storage in `tasks.json`
- Gemini API for voice and reasoning
- web search fallback for missing/current information

You do not need to host it publicly. It runs on `localhost`.

## Example Commands

- `add task prepare slides for monday`
- `show tasks`
- `complete task 1`
- `delete task buy milk`
- `clear completed`

## Notes

- Tasks are stored in `tasks.json` in the project folder.
- If no Gemini API key is configured, the app still works with rule-based text commands.
- Voice input depends on your installed Streamlit version supporting `st.audio_input`.
