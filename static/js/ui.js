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

export function formatTaskAction(name, result) {
  if (result.ok === false) {
    return result.message || "The task action could not be completed.";
  }

  const task = result.task || result.resolved_task;
  const title = task?.title ? `"${task.title}"` : "the task";

  if (name === "add_task") {
    return `Added ${title} to your tasks.`;
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

export function renderToolResult(container, toolResult) {
  if (toolResult.name === "search_web") {
    container.innerHTML = "";
    const results = toolResult.result.results || [];
    if (!results.length) {
      const empty = document.createElement("div");
      empty.className = "task";
      empty.textContent = toolResult.result.message || "No web results.";
      container.appendChild(empty);
      return;
    }
    for (const item of results) {
      const card = document.createElement("div");
      card.className = "task";

      const title = document.createElement("strong");
      title.textContent = item.title;

      const source = document.createElement("div");
      source.className = "meta";
      source.textContent = item.source;

      const snippet = document.createElement("div");
      snippet.textContent = item.snippet;

      const link = document.createElement("a");
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = item.url;

      card.append(title, source, snippet, link);
      container.appendChild(card);
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
      const card = document.createElement("div");
      card.className = "task";
      card.textContent = `${task.id}. ${task.title} (${task.status})`;
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
