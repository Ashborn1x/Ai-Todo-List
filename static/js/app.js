import {
  calculateRms,
  decodeBase64ToInt16,
  downsampleBuffer,
  floatTo16BitPCM,
  int16ToBase64
} from "./audio-utils.js";
import { addBubble, addEvent, renderTaskHistory, renderToolResult } from "./ui.js?v=10";
import { createAlarmManager } from "./alarm-manager.js?v=1";
import { populateCountryOptions, selectedCountryName } from "./country-options.js?v=1";

const connectBtn = document.getElementById("connectBtn");
const disconnectBtn = document.getElementById("disconnectBtn");
const sendTextBtn = document.getElementById("sendTextBtn");
const textInput = document.getElementById("textInput");
const voiceSelect = document.getElementById("voiceSelect");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const startCameraBtn = document.getElementById("startCameraBtn");
const stopCameraBtn = document.getElementById("stopCameraBtn");
const cameraStatus = document.getElementById("cameraStatus");
const cameraStage = document.getElementById("cameraStage");
const cameraPreview = document.getElementById("cameraPreview");
const cameraCanvas = document.getElementById("cameraCanvas");
const orbStage = document.querySelector(".orb-stage");
const conversation = document.getElementById("conversation");
const tasks = document.getElementById("tasks");
const taskHistory = document.getElementById("taskHistory");
const searchHistory = document.getElementById("searchHistory");
const events = document.getElementById("events");
const viewTitle = document.getElementById("viewTitle");
const navButtons = [...document.querySelectorAll("[data-nav]")];
const viewPanels = [...document.querySelectorAll("[data-view]")];
const newRequestButtons = [...document.querySelectorAll("[data-new-request]")];
const refreshTasksBtn = document.getElementById("refreshTasksBtn");
const clearSearchHistoryBtn = document.getElementById("clearSearchHistoryBtn");
const sidebar = document.getElementById("sidebar");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const mobileMenuBtn = document.getElementById("mobileMenuBtn");
const closeSidebarBtn = document.getElementById("closeSidebarBtn");
const countryInput = document.getElementById("countryInput");
const localContext = document.getElementById("localContext");
const alarmManager = createAlarmManager({
  onEvent: (message) => addEvent(events, message)
});
const SEARCH_HISTORY_KEY = "aura-search-history";
const SEARCH_HISTORY_LIMIT = 20;
const TASK_MUTATION_TOOLS = [
  "add_task",
  "complete_task",
  "complete_listed_task",
  "delete_task",
  "delete_listed_task",
  "clear_completed"
];

let socket = null;
let audioContext = null;
let playbackContext = null;
let mediaStream = null;
let mediaSource = null;
let processor = null;
let captureSink = null;
let playbackCursor = 0;
let assistantSpeakingUntil = 0;
let microphoneBlockedByAssistant = false;
let assistantPlaybackTimer = null;
let assistantTurnActive = false;
let assistantResponseComplete = false;
let speaking = false;
let silenceFrames = 0;
let speechFrames = 0;
let disconnecting = false;
let noiseFloor = 0.003;
let calibratedFrames = 0;
let pendingTailFrames = 0;
let preSpeechChunks = [];
let cameraStream = null;
let cameraFrameTimer = null;
let cameraFrameCount = 0;
const CALIBRATION_FRAMES = 12;
const MIN_NOISE_FLOOR = 0.0025;
const SPEECH_RATIO = 2.0;
const MIN_SPEECH_RMS = 0.008;
const REQUIRED_SPEECH_FRAMES = 2;
const SILENCE_FRAME_LIMIT = 14;
const PRE_SPEECH_CHUNKS = 6;
const POST_SPEECH_CHUNKS = 4;
const CAMERA_FRAME_INTERVAL_MS = 2000;
const VIEW_TITLES = {
  assistant: "Aura Assistant",
  tasks: "Task Management",
  history: "Interaction History",
  settings: "Settings & Preferences"
};

function getBrowserDisplayContext() {
  const locale = navigator.language || "en-US";
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  let region = "";

  try {
    region = new Intl.Locale(locale).region || "";
  } catch {
    region = "";
  }

  return {
    timezone,
    locale,
    region
  };
}

function getSessionUserContext() {
  const context = getBrowserDisplayContext();
  return {
    region: countryInput.value || context.region,
    country: selectedCountryName(countryInput),
    utc_offset_minutes: -new Date().getTimezoneOffset()
  };
}

function updateLocalContext() {
  const context = getBrowserDisplayContext();
  const country = selectedCountryName(countryInput) || "System default";
  localContext.textContent =
    `Selected country: ${country} · Browser timezone: ${context.timezone} · Locale: ${context.locale}`;
}

function initializeUserContext() {
  const context = getBrowserDisplayContext();
  populateCountryOptions(countryInput, context.locale);

  let savedCountry = "";
  try {
    savedCountry = window.localStorage.getItem("aura-country") || "";
  } catch {
    savedCountry = "";
  }

  const savedCode = savedCountry.toUpperCase();
  if (savedCode.length === 2 && countryInput.querySelector(`option[value="${savedCode}"]`)) {
    countryInput.value = savedCode;
  } else if (savedCountry) {
    const legacyOption = [...countryInput.options].find(
      (option) => option.textContent === savedCountry
    );
    countryInput.value = legacyOption?.value || context.region || "";
  } else {
    countryInput.value = context.region || "";
  }

  updateLocalContext();
}

initializeUserContext();
countryInput.addEventListener("change", () => {
  try {
    window.localStorage.setItem("aura-country", countryInput.value);
  } catch {
    // Location context still works for this session when storage is unavailable.
  }
  updateLocalContext();
});

function showEmptySearchHistory() {
  const empty = document.createElement("div");
  empty.className = "search-history-empty";
  const label = document.createElement("span");
  label.textContent = "Search";
  const title = document.createElement("strong");
  title.textContent = "No searches yet";
  const description = document.createElement("p");
  description.textContent = "Ask Aura to search the web and the results will appear here.";
  empty.append(label, title, description);
  searchHistory.replaceChildren(empty);
}

function readSearchHistory() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(SEARCH_HISTORY_KEY) || "[]");
    return Array.isArray(stored) ? stored.slice(0, SEARCH_HISTORY_LIMIT) : [];
  } catch {
    return [];
  }
}

function restoreSearchHistory() {
  const stored = readSearchHistory();
  if (!stored.length) {
    showEmptySearchHistory();
    return;
  }
  searchHistory.replaceChildren();
  for (const item of [...stored].reverse()) {
    renderToolResult(searchHistory, item);
  }
}

function recordSearchResult(payload) {
  const entry = {
    name: "search_web",
    result: payload.result,
    recorded_at: new Date().toISOString()
  };
  renderToolResult(searchHistory, entry);
  try {
    const stored = readSearchHistory();
    stored.unshift(entry);
    window.localStorage.setItem(
      SEARCH_HISTORY_KEY,
      JSON.stringify(stored.slice(0, SEARCH_HISTORY_LIMIT))
    );
  } catch {
    // The current session still displays history if browser storage is unavailable.
  }
}

restoreSearchHistory();

async function refreshTaskListFromApi() {
  try {
    const response = await fetch("/api/tasks", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Could not load tasks.");
    }
    const allTasks = await response.json();
    renderToolResult(tasks, {
      name: "list_tasks",
      result: {
        tasks: allTasks.filter((task) => task.status === "open")
      }
    });
    renderTaskHistory(taskHistory, allTasks);
  } catch (error) {
    console.warn("Task list refresh failed.", error);
    addEvent(events, error.message);
  }
}

async function updateTaskFromChecklist(taskId, action) {
  const method = action === "delete" ? "DELETE" : "POST";
  const path = action === "delete"
    ? `/api/tasks/${taskId}`
    : `/api/tasks/${taskId}/complete`;
  const response = await fetch(path, { method });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "The task could not be updated.");
  }
  await refreshTaskListFromApi();
  await alarmManager.refresh();
}

function showView(viewName) {
  const target = VIEW_TITLES[viewName] ? viewName : "assistant";
  for (const panel of viewPanels) {
    const active = panel.dataset.view === target;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  }
  for (const button of navButtons) {
    button.classList.toggle("active", button.dataset.nav === target);
  }
  viewTitle.textContent = VIEW_TITLES[target];
  void ensureAudioCaptureActive();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setMobileSidebarOpen(open, restoreFocus = false) {
  const shouldOpen = open && window.matchMedia("(max-width: 820px)").matches;
  sidebar.classList.toggle("mobile-open", shouldOpen);
  sidebarBackdrop.hidden = !shouldOpen;
  document.body.classList.toggle("sidebar-open", shouldOpen);
  mobileMenuBtn.setAttribute("aria-expanded", String(shouldOpen));
  if (shouldOpen) {
    closeSidebarBtn.focus();
  } else if (restoreFocus) {
    mobileMenuBtn.focus();
  }
}

function setStatus(text, connected) {
  statusText.textContent = text;
  statusDot.classList.toggle("live", connected);
  let voiceState = "idle";
  if (connected && text === "Assistant speaking") {
    voiceState = "speaking";
  } else if (connected && text === "Listening to you") {
    voiceState = "listening";
  } else if (connected) {
    voiceState = "ready";
  }
  orbStage.dataset.voiceState = voiceState;
}

function updateLiveState() {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    setStatus("Disconnected", false);
    return;
  }

  if (disconnecting) {
    setStatus("Stopping...", false);
    return;
  }

  if (assistantTurnActive || microphoneBlockedByAssistant) {
    setStatus("Assistant speaking", true);
    return;
  }

  if (speaking) {
    setStatus("Listening to you", true);
    return;
  }

  setStatus("Ready for you", true);
}

function setConnectionButtons({ connecting = false, connected = false, stopping = false } = {}) {
  connectBtn.disabled = connecting || connected || stopping;
  disconnectBtn.disabled = !connected && !stopping;
  voiceSelect.disabled = connecting || connected || stopping;
  countryInput.disabled = connecting || connected || stopping;
  sendTextBtn.disabled = !connected || stopping;
  textInput.disabled = !connected || stopping;
  startCameraBtn.disabled = !connected || stopping || Boolean(cameraStream);
  stopCameraBtn.disabled = stopping || !cameraStream;
}

function playPcm16(base64, sampleRate = 24000) {
  if (!playbackContext) {
    playbackContext = new AudioContext();
    playbackCursor = playbackContext.currentTime;
  }

  const pcm = decodeBase64ToInt16(base64);
  const audioBuffer = playbackContext.createBuffer(1, pcm.length, sampleRate);
  const channel = audioBuffer.getChannelData(0);
  for (let i = 0; i < pcm.length; i += 1) {
    channel[i] = pcm[i] / 32768;
  }

  const source = playbackContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(playbackContext.destination);
  const startAt = Math.max(playbackContext.currentTime, playbackCursor);
  source.start(startAt);
  playbackCursor = startAt + audioBuffer.duration;
  assistantSpeakingUntil = Math.max(assistantSpeakingUntil, playbackCursor + 0.25);
  assistantTurnActive = true;
  assistantResponseComplete = false;
  syncAssistantPlaybackBlock();
  updateLiveState();
}

function resetVoiceDetection() {
  speaking = false;
  silenceFrames = 0;
  speechFrames = 0;
  pendingTailFrames = 0;
  preSpeechChunks = [];
  calibratedFrames = 0;
  noiseFloor = MIN_NOISE_FLOOR;
}

function closeUserSpeechTurn(reason) {
  if (!speaking) {
    silenceFrames = 0;
    speechFrames = 0;
    pendingTailFrames = 0;
    preSpeechChunks = [];
    return;
  }

  speaking = false;
  silenceFrames = 0;
  speechFrames = 0;
  pendingTailFrames = 0;
  preSpeechChunks = [];
  if (socket && socket.readyState === WebSocket.OPEN && !disconnecting) {
    socket.send(JSON.stringify({ type: "activity_end" }));
  }
  addEvent(events, reason);
  updateLiveState();
}

function setMicrophoneBlocked(blocked) {
  const changed = microphoneBlockedByAssistant !== blocked;
  microphoneBlockedByAssistant = blocked;
  if (!mediaStream) {
    updateLiveState();
    return;
  }
  for (const track of mediaStream.getAudioTracks()) {
    track.enabled = !blocked;
  }
  if (changed && !blocked) {
    resetVoiceDetection();
    addEvent(events, "Microphone ready for your next request.");
  }
  updateLiveState();
}

function syncAssistantPlaybackBlock() {
  if (assistantPlaybackTimer) {
    window.clearTimeout(assistantPlaybackTimer);
    assistantPlaybackTimer = null;
  }

  if (!playbackContext || playbackContext.state === "closed") {
    if (assistantResponseComplete) {
      assistantTurnActive = false;
    }
    setMicrophoneBlocked(false);
    return;
  }

  const remainingMs = Math.max(0, (assistantSpeakingUntil - playbackContext.currentTime) * 1000);
  if (remainingMs <= 0) {
    if (assistantResponseComplete) {
      assistantTurnActive = false;
      setMicrophoneBlocked(false);
    }
    return;
  }

  if (!microphoneBlockedByAssistant) {
    closeUserSpeechTurn("Paused mic while assistant audio was playing.");
    setMicrophoneBlocked(true);
  }

  assistantPlaybackTimer = window.setTimeout(() => {
    assistantPlaybackTimer = null;
    syncAssistantPlaybackBlock();
  }, remainingMs + 60);
}

function sendAudioChunk(base64Audio) {
  if (!socket || socket.readyState !== WebSocket.OPEN || disconnecting) {
    return;
  }
  socket.send(JSON.stringify({ type: "audio", data: base64Audio }));
}

function sendCameraFrame() {
  if (
    !cameraStream ||
    !socket ||
    socket.readyState !== WebSocket.OPEN ||
    disconnecting ||
    cameraPreview.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
  ) {
    return;
  }

  const sourceWidth = cameraPreview.videoWidth;
  const sourceHeight = cameraPreview.videoHeight;
  if (!sourceWidth || !sourceHeight) {
    return;
  }

  const scale = Math.min(1, 640 / sourceWidth);
  cameraCanvas.width = Math.round(sourceWidth * scale);
  cameraCanvas.height = Math.round(sourceHeight * scale);
  const context = cameraCanvas.getContext("2d", { alpha: false });
  context.drawImage(cameraPreview, 0, 0, cameraCanvas.width, cameraCanvas.height);
  const dataUrl = cameraCanvas.toDataURL("image/jpeg", 0.72);
  socket.send(JSON.stringify({
    type: "video",
    mime_type: "image/jpeg",
    data: dataUrl.split(",", 2)[1]
  }));
  cameraFrameCount += 1;
  cameraStatus.textContent = `Camera on · frame ${cameraFrameCount}`;
}

async function startCamera() {
  if (cameraStream || !socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }

  startCameraBtn.disabled = true;
  cameraStatus.textContent = "Requesting camera…";
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 640 },
        height: { ideal: 480 }
      },
      audio: false
    });
    cameraPreview.srcObject = cameraStream;
    await cameraPreview.play();
    cameraFrameCount = 0;
    cameraStage.classList.add("active");
    cameraStatus.textContent = "Camera on";
    cameraFrameTimer = window.setInterval(sendCameraFrame, CAMERA_FRAME_INTERVAL_MS);
    sendCameraFrame();
    addEvent(events, "Camera started. Ask what the assistant sees.");
  } catch (error) {
    cameraStream = null;
    cameraStatus.textContent = "Camera unavailable";
    addEvent(events, `Could not start camera: ${error.message}`);
  }
  setConnectionButtons({ connected: socket && socket.readyState === WebSocket.OPEN });
}

function stopCamera(showEvent = true) {
  if (cameraFrameTimer) {
    window.clearInterval(cameraFrameTimer);
    cameraFrameTimer = null;
  }
  if (cameraStream) {
    for (const track of cameraStream.getTracks()) {
      track.stop();
    }
  }
  cameraStream = null;
  cameraPreview.srcObject = null;
  cameraStage.classList.remove("active");
  cameraStatus.textContent = "Camera off";
  cameraFrameCount = 0;
  if (showEvent) {
    addEvent(events, "Camera stopped.");
  }
  setConnectionButtons({
    connected: Boolean(socket && socket.readyState === WebSocket.OPEN && !disconnecting),
    stopping: disconnecting
  });
}

function processMicrophoneFrame(input) {
  if (
    !audioContext ||
    !socket ||
    socket.readyState !== WebSocket.OPEN ||
    disconnecting ||
    microphoneBlockedByAssistant
  ) {
    return;
  }

  const rms = calculateRms(input);

  if (!speaking) {
    if (calibratedFrames < CALIBRATION_FRAMES) {
      noiseFloor = Math.max(MIN_NOISE_FLOOR, (noiseFloor * calibratedFrames + rms) / (calibratedFrames + 1));
      calibratedFrames += 1;
    } else {
      noiseFloor = Math.max(MIN_NOISE_FLOOR, noiseFloor * 0.98 + rms * 0.02);
    }
  }

  const dynamicThreshold = Math.max(MIN_SPEECH_RMS, noiseFloor * SPEECH_RATIO);
  const speechDetected = rms >= dynamicThreshold;

  if (speechDetected) {
    silenceFrames = 0;
    speechFrames += 1;
    if (!speaking && speechFrames >= REQUIRED_SPEECH_FRAMES) {
      speaking = true;
      pendingTailFrames = 0;
      socket.send(JSON.stringify({ type: "activity_start" }));
      addEvent(events, "Speech detected.");
      updateLiveState();
    }
  } else {
    speechFrames = 0;
    if (speaking) {
      silenceFrames += 1;
      if (silenceFrames >= SILENCE_FRAME_LIMIT) {
        speaking = false;
        silenceFrames = 0;
        pendingTailFrames = POST_SPEECH_CHUNKS;
      }
    }
  }

  const downsampled = downsampleBuffer(input, audioContext.sampleRate, 16000);
  const pcm16 = floatTo16BitPCM(downsampled);
  const base64Audio = int16ToBase64(pcm16);
  preSpeechChunks.push(base64Audio);
  if (preSpeechChunks.length > PRE_SPEECH_CHUNKS) {
    preSpeechChunks.shift();
  }

  if (speaking) {
    if (speechFrames === REQUIRED_SPEECH_FRAMES) {
      for (const chunk of preSpeechChunks) {
        sendAudioChunk(chunk);
      }
      preSpeechChunks = [];
    }
    sendAudioChunk(base64Audio);
    return;
  }

  if (pendingTailFrames > 0) {
    sendAudioChunk(base64Audio);
    pendingTailFrames -= 1;
    if (pendingTailFrames === 0) {
      socket.send(JSON.stringify({ type: "activity_end" }));
      addEvent(events, "Speech segment ended.");
      preSpeechChunks = [];
    }
  }
}

async function ensureAudioCaptureActive() {
  if (
    !audioContext ||
    audioContext.state === "closed" ||
    !socket ||
    socket.readyState !== WebSocket.OPEN
  ) {
    return;
  }

  if (audioContext.state === "suspended") {
    try {
      await audioContext.resume();
    } catch (error) {
      console.warn("Could not resume microphone capture.", error);
    }
  }
}

async function startMicrophone() {
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    }
  });
  audioContext = new AudioContext();
  mediaSource = audioContext.createMediaStreamSource(mediaStream);
  calibratedFrames = 0;
  noiseFloor = MIN_NOISE_FLOOR;
  speechFrames = 0;
  silenceFrames = 0;
  speaking = false;
  pendingTailFrames = 0;
  preSpeechChunks = [];

  captureSink = audioContext.createGain();
  captureSink.gain.value = 0;
  captureSink.connect(audioContext.destination);

  if (audioContext.audioWorklet && typeof AudioWorkletNode === "function") {
    await audioContext.audioWorklet.addModule(
      "/static/js/microphone-processor.js?v=1"
    );
    processor = new AudioWorkletNode(audioContext, "microphone-capture");
    processor.port.onmessage = (event) => {
      processMicrophoneFrame(event.data);
    };
  } else {
    processor = audioContext.createScriptProcessor(2048, 1, 1);
    processor.onaudioprocess = (event) => {
      processMicrophoneFrame(event.inputBuffer.getChannelData(0));
    };
  }

  mediaSource.connect(processor);
  processor.connect(captureSink);
  await ensureAudioCaptureActive();
}

function stopMicrophone() {
  speaking = false;
  silenceFrames = 0;
  speechFrames = 0;
  calibratedFrames = 0;
  pendingTailFrames = 0;
  preSpeechChunks = [];
  assistantTurnActive = false;
  assistantResponseComplete = false;
  setMicrophoneBlocked(false);
  if (assistantPlaybackTimer) {
    window.clearTimeout(assistantPlaybackTimer);
    assistantPlaybackTimer = null;
  }
  if (processor) {
    if (processor.port) {
      processor.port.onmessage = null;
    }
    if ("onaudioprocess" in processor) {
      processor.onaudioprocess = null;
    }
    processor.disconnect();
    processor = null;
  }
  if (captureSink) {
    captureSink.disconnect();
    captureSink = null;
  }
  if (mediaSource) {
    mediaSource.disconnect();
    mediaSource = null;
  }
  if (mediaStream) {
    for (const track of mediaStream.getTracks()) {
      track.stop();
    }
    mediaStream = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
  updateLiveState();
}

function stopPlayback() {
  playbackCursor = 0;
  assistantSpeakingUntil = 0;
  assistantResponseComplete = false;
  if (!assistantTurnActive) {
    setMicrophoneBlocked(false);
  }
  if (assistantPlaybackTimer) {
    window.clearTimeout(assistantPlaybackTimer);
    assistantPlaybackTimer = null;
  }
  if (playbackContext && playbackContext.state !== "closed") {
    playbackContext.close();
  }
  playbackContext = null;
  updateLiveState();
}

function finalizeDisconnect(message) {
  stopCamera(false);
  stopMicrophone();
  stopPlayback();
  socket = null;
  disconnecting = false;
  setStatus("Disconnected", false);
  setConnectionButtons({ connected: false });
  addEvent(events, message);
}

async function connect() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  disconnecting = false;
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/live`);
  setStatus("Connecting...", false);
  setConnectionButtons({ connecting: true });

  socket.onopen = async () => {
    socket.send(JSON.stringify({
      type: "config",
      voice: voiceSelect.value,
      user_context: getSessionUserContext()
    }));
    setConnectionButtons({ connected: true });
    setStatus("Allow microphone access...", true);
    addEvent(events, "Connected. Waiting for microphone permission.");

    try {
      await startMicrophone();
    } catch (error) {
      addEvent(events, `Microphone unavailable: ${error.message}`);
      const failedSocket = socket;
      if (failedSocket) {
        failedSocket.onclose = null;
      }
      finalizeDisconnect("Conversation stopped because the microphone is unavailable.");
      if (
        failedSocket &&
        [WebSocket.CONNECTING, WebSocket.OPEN].includes(failedSocket.readyState)
      ) {
        failedSocket.close(1008, "Microphone permission required");
      }
      return;
    }

    addEvent(events, "Microphone streaming started.");
    updateLiveState();
  };

  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "input_transcript") {
      if (payload.finished && payload.text) {
        addBubble(conversation, "user", payload.text);
      }
    } else if (payload.type === "output_transcript") {
      if (payload.finished && payload.text) {
        addBubble(conversation, "assistant", payload.text);
      }
    } else if (payload.type === "assistant_text") {
      addEvent(events, `Assistant text: ${payload.text}`);
    } else if (payload.type === "tool_result") {
      addEvent(events, `Tool ${payload.name}: ${JSON.stringify(payload.result)}`);
      if (payload.name === "search_web") {
        recordSearchResult(payload);
      } else if (payload.name === "list_tasks") {
        renderToolResult(tasks, payload);
      } else if (TASK_MUTATION_TOOLS.includes(payload.name)) {
        void refreshTaskListFromApi();
      }
      if (TASK_MUTATION_TOOLS.includes(payload.name)) {
        void alarmManager.refresh();
      }
    } else if (payload.type === "audio") {
      playPcm16(payload.data);
    } else if (payload.type === "turn_complete") {
      assistantResponseComplete = true;
      syncAssistantPlaybackBlock();
      addEvent(events, "Response received; waiting for audio playback to finish.");
    } else if (payload.type === "error") {
      addEvent(events, `Error: ${payload.message}`);
      addBubble(
        conversation,
        "assistant",
        `The live conversation hit an error: ${payload.message}`
      );
      setStatus("Connection error", false);
    }
  };

  socket.onerror = (event) => {
    console.error("WebSocket error", event);
    addEvent(events, "WebSocket error. Check the browser console and server terminal.");
  };

  socket.onclose = (event) => {
    finalizeDisconnect(`Conversation stopped. Code=${event.code} Reason=${event.reason || "none"}`);
  };
}

function disconnect() {
  if (disconnecting) {
    return;
  }

  disconnecting = true;
  setStatus("Stopping...", false);
  setConnectionButtons({ stopping: true });
  stopCamera(false);
  stopMicrophone();

  if (!socket) {
    finalizeDisconnect("Conversation stopped locally.");
    return;
  }

  if (socket.readyState === WebSocket.OPEN) {
    window.setTimeout(() => {
      if (socket && socket.readyState !== WebSocket.CLOSED) {
        socket.close(1000, "Stopped by user");
      }
    }, 50);
    return;
  }

  if (socket.readyState === WebSocket.CONNECTING) {
    socket.close(1000, "Stopped during connect");
    return;
  }

  finalizeDisconnect("Conversation stopped locally.");
}

connectBtn.addEventListener("click", connect);
disconnectBtn.addEventListener("click", disconnect);
startCameraBtn.addEventListener("click", startCamera);
stopCameraBtn.addEventListener("click", () => stopCamera());
for (const button of navButtons) {
  button.addEventListener("click", (event) => {
    event.preventDefault();
    showView(button.dataset.nav);
    setMobileSidebarOpen(false);
  });
}
for (const button of newRequestButtons) {
  button.addEventListener("click", () => {
    showView("assistant");
    setMobileSidebarOpen(false);
    window.setTimeout(() => textInput.focus(), 100);
  });
}
mobileMenuBtn.addEventListener("click", () => setMobileSidebarOpen(true));
closeSidebarBtn.addEventListener("click", () => setMobileSidebarOpen(false, true));
sidebarBackdrop.addEventListener("click", () => setMobileSidebarOpen(false, true));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && sidebar.classList.contains("mobile-open")) {
    setMobileSidebarOpen(false, true);
  }
});
window.addEventListener("resize", () => {
  if (window.innerWidth > 820 && sidebar.classList.contains("mobile-open")) {
    setMobileSidebarOpen(false);
  }
});
refreshTasksBtn.addEventListener("click", () => void refreshTaskListFromApi());
tasks.addEventListener("change", async (event) => {
  const checkbox = event.target.closest('[data-task-action="complete"]');
  if (!checkbox?.checked) {
    return;
  }
  const row = checkbox.closest("[data-task-id]");
  checkbox.disabled = true;
  try {
    await updateTaskFromChecklist(row.dataset.taskId, "complete");
  } catch (error) {
    checkbox.checked = false;
    checkbox.disabled = false;
    addEvent(events, error.message);
  }
});
tasks.addEventListener("click", async (event) => {
  const button = event.target.closest('[data-task-action="delete"]');
  if (!button) {
    return;
  }
  const row = button.closest("[data-task-id]");
  const title = row.querySelector(".task-row-content strong")?.textContent || "this task";
  if (!window.confirm(`Delete "${title}"?`)) {
    return;
  }
  button.disabled = true;
  try {
    await updateTaskFromChecklist(row.dataset.taskId, "delete");
  } catch (error) {
    button.disabled = false;
    addEvent(events, error.message);
  }
});
clearSearchHistoryBtn.addEventListener("click", () => {
  try {
    window.localStorage.removeItem(SEARCH_HISTORY_KEY);
  } catch {
    // The visible history can still be cleared without browser storage.
  }
  showEmptySearchHistory();
});
sendTextBtn.addEventListener("click", () => {
  if (!socket || socket.readyState !== WebSocket.OPEN || disconnecting) {
    return;
  }

  const text = textInput.value.trim();
  if (!text) {
    return;
  }

  addBubble(conversation, "user", text);
  socket.send(JSON.stringify({ type: "text", text }));
  textInput.value = "";
});
textInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    sendTextBtn.click();
  }
});
alarmManager.start();
void refreshTaskListFromApi();
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    void ensureAudioCaptureActive();
  }
});
window.addEventListener("focus", () => {
  void ensureAudioCaptureActive();
});
