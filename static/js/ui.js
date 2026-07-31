export function addBubble(container, role, text) {
  container.querySelector(".welcome-message")?.remove();
  const node = document.createElement("div");
  node.className = `bubble ${role}`;
  node.textContent = text;
  container.appendChild(node);
  container.scrollTop = container.scrollHeight;
}

export function addEvent(container, text) {
  container.querySelector(".event-empty")?.remove();
  const node = document.createElement("div");
  node.className = "meta";
  node.textContent = text;
  container.appendChild(node);
  container.scrollTop = container.scrollHeight;
}

export function formatScheduledFor(value) {
  if (!value) {
    return "";
  }

  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const parsed = new Date(dateOnly ? `${value}T00:00:00` : value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  const options = dateOnly
    ? { dateStyle: "medium" }
    : { dateStyle: "medium", timeStyle: "short" };
  return new Intl.DateTimeFormat(undefined, options).format(parsed);
}

export function formatTaskAction(name, result) {
  if (result.ok === false) {
    return result.message || "The task action could not be completed.";
  }

  const task = result.task || result.resolved_task;
  const title = task?.title ? `"${task.title}"` : "the task";
  const schedule = formatScheduledFor(task?.scheduled_for);

  if (name === "add_task") {
    return schedule
      ? `Added ${title}, scheduled for ${schedule}.`
      : `Added ${title} to your tasks.`;
  }
  if (["complete_task", "complete_listed_task"].includes(name)) {
    return `Completed ${title}.`;
  }
  if (["delete_task", "delete_listed_task"].includes(name)) {
    return `Deleted ${title}.`;
  }
  if (name === "clear_completed") {
    const count = Number(result.removed || 0);
    return `Cleared ${count} completed ${count === 1 ? "task" : "tasks"}.`;
  }

  return "Task updated.";
}

export function renderTaskHistory(container, tasks) {
  const completed = tasks
    .filter((task) => task.status === "done")
    .sort((left, right) => String(right.completed_at || "").localeCompare(String(left.completed_at || "")));
  container.replaceChildren();

  if (!completed.length) {
    const empty = document.createElement("div");
    empty.className = "task-history-empty";
    empty.textContent = "Completed tasks will appear here.";
    container.appendChild(empty);
    return;
  }

  for (const task of completed) {
    const item = document.createElement("article");
    item.className = "task-history-item";
    const check = document.createElement("span");
    check.className = "task-history-check";
    check.textContent = "✓";
    check.setAttribute("aria-hidden", "true");

    const content = document.createElement("div");
    content.className = "task-history-content";
    const title = document.createElement("strong");
    title.textContent = task.title;
    const details = document.createElement("span");
    const completedAt = formatScheduledFor(task.completed_at);
    const scheduledFor = formatScheduledFor(task.scheduled_for);
    details.textContent = [
      completedAt ? `Completed ${completedAt}` : "Completed",
      scheduledFor ? `Originally scheduled ${scheduledFor}` : ""
    ].filter(Boolean).join(" · ");
    content.append(title, details);
    item.append(check, content);
    container.appendChild(item);
  }
}

export function renderToolResult(container, toolResult) {
  if (toolResult.name === "search_web") {
    container.querySelector(".search-history-empty")?.remove();
    const entry = document.createElement("article");
    entry.className = "search-history-entry";

    const heading = document.createElement("div");
    heading.className = "search-history-heading";
    const query = document.createElement("strong");
    query.textContent = toolResult.result.query || "Web search";
    const timestamp = document.createElement("time");
    const candidateDate = new Date(toolResult.recorded_at || Date.now());
    const recordedAt = Number.isNaN(candidateDate.getTime()) ? new Date() : candidateDate;
    timestamp.dateTime = recordedAt.toISOString();
    timestamp.textContent = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short"
    }).format(recordedAt);
    heading.append(query, timestamp);
    entry.appendChild(heading);

    const resultList = document.createElement("div");
    resultList.className = "search-result-list";
    const results = toolResult.result.results || [];
    if (!results.length) {
      const empty = document.createElement("div");
      empty.className = "search-result";
      empty.textContent = toolResult.result.message || "No web results.";
      resultList.appendChild(empty);
    }
    for (const item of results) {
      const card = document.createElement("div");
      card.className = "search-result";

      const title = document.createElement("a");
      title.textContent = item.title;
      title.href = item.url;
      title.target = "_blank";
      title.rel = "noreferrer";

      const source = document.createElement("div");
      source.className = "meta";
      source.textContent = item.source;

      const snippet = document.createElement("p");
      snippet.textContent = item.snippet;

      card.append(title, source, snippet);
      resultList.appendChild(card);
    }
    entry.appendChild(resultList);
    container.prepend(entry);
    while (container.children.length > 20) {
      container.lastElementChild.remove();
    }
    return;
  }

  if (toolResult.name === "list_tasks") {
    container.innerHTML = "";
    const list = toolResult.result.tasks || [];
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "task";
      empty.textContent = "No open tasks.";
      container.appendChild(empty);
    }
    for (const task of list) {
      const card = document.createElement("article");
      card.className = "task task-row";
      card.dataset.taskId = task.id;

      const checkLabel = document.createElement("label");
      checkLabel.className = "task-check";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.dataset.taskAction = "complete";
      checkbox.setAttribute("aria-label", `Mark ${task.title} as done`);
      const checkmark = document.createElement("span");
      checkmark.setAttribute("aria-hidden", "true");
      checkLabel.append(checkbox, checkmark);

      const content = document.createElement("div");
      content.className = "task-row-content";
      const title = document.createElement("strong");
      title.textContent = task.title;
      const schedule = formatScheduledFor(task.snoozed_until || task.scheduled_for);
      const scheduleLabel = task.snoozed_until ? "snoozed until" : "scheduled for";
      const meta = document.createElement("span");
      meta.textContent = schedule
        ? `Task ${task.id} · ${scheduleLabel} ${schedule}`
        : `Task ${task.id}`;
      content.append(title, meta);

      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "task-delete";
      deleteButton.dataset.taskAction = "delete";
      deleteButton.textContent = "Delete";
      deleteButton.setAttribute("aria-label", `Delete ${task.title}`);

      card.append(checkLabel, content, deleteButton);
      container.appendChild(card);
    }
    return;
  }

  const taskActions = [
    "add_task",
    "complete_task",
    "complete_listed_task",
    "delete_task",
    "delete_listed_task",
    "clear_completed"
  ];
  if (taskActions.includes(toolResult.name)) {
    container.querySelector(".empty-state")?.remove();
    const card = document.createElement("div");
    card.className = "task task-action";
    card.textContent = formatTaskAction(toolResult.name, toolResult.result);
    container.prepend(card);
  }
}
