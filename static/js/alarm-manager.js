const POLL_INTERVAL_MS = 10000;
const MAX_SNOOZE_MINUTES = 1440;

function taskAlarmTime(task) {
  if (
    task.status !== "open" ||
    task.alarm_dismissed_at ||
    !task.scheduled_for ||
    /^\d{4}-\d{2}-\d{2}$/.test(task.scheduled_for)
  ) {
    return null;
  }

  const timestamp = Date.parse(task.snoozed_until || task.scheduled_for);
  return Number.isNaN(timestamp) ? null : timestamp;
}

function displayTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "full",
    timeStyle: "short"
  }).format(parsed);
}

export function createAlarmManager({ onEvent = () => {} } = {}) {
  const modal = document.getElementById("alarmModal");
  const title = document.getElementById("alarmTaskTitle");
  const scheduledTime = document.getElementById("alarmScheduledTime");
  const error = document.getElementById("alarmError");
  const dismissButton = document.getElementById("dismissAlarmBtn");
  const customForm = document.getElementById("customSnoozeForm");
  const customMinutes = document.getElementById("customSnoozeMinutes");
  const enableButton = document.getElementById("enableAlarmsBtn");
  const permissionStatus = document.getElementById("alarmPermissionStatus");
  const presetButtons = [...document.querySelectorAll("[data-snooze-minutes]")];

  let activeTask = null;
  let audioContext = null;
  let soundTimer = null;

  function ensureAudioContext() {
    if (!audioContext || audioContext.state === "closed") {
      audioContext = new AudioContext();
    }
    if (audioContext.state === "suspended") {
      void audioContext.resume();
    }
  }

  function beep() {
    if (!audioContext || audioContext.state !== "running") {
      return;
    }
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    const now = audioContext.currentTime;
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(880, now);
    oscillator.frequency.exponentialRampToValueAtTime(660, now + 0.34);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.22, now + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.42);
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.start(now);
    oscillator.stop(now + 0.45);
  }

  function stopSound() {
    if (soundTimer) {
      window.clearInterval(soundTimer);
      soundTimer = null;
    }
  }

  function startSound() {
    ensureAudioContext();
    stopSound();
    beep();
    soundTimer = window.setInterval(beep, 1300);
  }

  function showNotification(task) {
    if (!("Notification" in window) || Notification.permission !== "granted") {
      return;
    }
    const notification = new Notification("Aura task reminder", {
      body: task.title,
      tag: `aura-task-${task.id}`,
      requireInteraction: true
    });
    notification.onclick = () => window.focus();
  }

  function showAlarm(task) {
    activeTask = task;
    error.textContent = "";
    title.textContent = task.title;
    scheduledTime.textContent = `Scheduled for ${displayTime(task.scheduled_for)}`;
    modal.hidden = false;
    startSound();
    showNotification(task);
    dismissButton.focus();
    onEvent(`Alarm started for ${task.title}.`);
  }

  function closeAlarm() {
    stopSound();
    modal.hidden = true;
    activeTask = null;
  }

  async function request(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "The alarm action failed.");
    }
    return payload;
  }

  async function snooze(minutes) {
    if (!activeTask) {
      return;
    }
    const safeMinutes = Number(minutes);
    if (!Number.isInteger(safeMinutes) || safeMinutes < 1 || safeMinutes > MAX_SNOOZE_MINUTES) {
      error.textContent = "Choose between 1 and 1440 minutes.";
      return;
    }

    try {
      await request(`/api/tasks/${activeTask.id}/snooze`, { minutes: safeMinutes });
      onEvent(`Snoozed ${activeTask.title} for ${safeMinutes} minutes.`);
      closeAlarm();
      await refresh();
    } catch (requestError) {
      error.textContent = requestError.message;
    }
  }

  async function dismiss() {
    if (!activeTask) {
      return;
    }
    try {
      await request(`/api/tasks/${activeTask.id}/dismiss-alarm`);
      onEvent(`Dismissed alarm for ${activeTask.title}.`);
      closeAlarm();
      await refresh();
    } catch (requestError) {
      error.textContent = requestError.message;
    }
  }

  async function refresh() {
    try {
      const response = await fetch("/api/tasks", { cache: "no-store" });
      if (!response.ok) {
        throw new Error("Could not load scheduled tasks.");
      }
      const tasks = await response.json();
      if (activeTask) {
        const current = tasks.find((task) => task.id === activeTask.id);
        if (!current || taskAlarmTime(current) === null) {
          closeAlarm();
        }
      }
      if (!activeTask) {
        const now = Date.now();
        const due = tasks
          .map((task) => ({ task, time: taskAlarmTime(task) }))
          .filter((item) => item.time !== null && item.time <= now)
          .sort((left, right) => left.time - right.time);
        if (due.length) {
          showAlarm(due[0].task);
        }
      }
    } catch (refreshError) {
      console.warn("Alarm scheduler refresh failed.", refreshError);
    }
  }

  async function enableAlarms() {
    ensureAudioContext();
    if ("Notification" in window && Notification.permission === "default") {
      await Notification.requestPermission();
    }
    const notifications =
      "Notification" in window && Notification.permission === "granted"
        ? " Browser notifications are enabled."
        : " Keep this page open to hear alarms.";
    permissionStatus.textContent = `Alarm sound is enabled.${notifications}`;
    enableButton.textContent = "Alarms enabled";
    await refresh();
  }

  function start() {
    document.addEventListener("pointerdown", ensureAudioContext, { once: true });
    enableButton.addEventListener("click", enableAlarms);
    dismissButton.addEventListener("click", dismiss);
    for (const button of presetButtons) {
      button.addEventListener("click", () => snooze(Number(button.dataset.snoozeMinutes)));
    }
    customForm.addEventListener("submit", (event) => {
      event.preventDefault();
      void snooze(Number(customMinutes.value));
    });
    void refresh();
    window.setInterval(refresh, POLL_INTERVAL_MS);
  }

  return { start, refresh };
}
