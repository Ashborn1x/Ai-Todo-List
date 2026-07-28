export function addBubble(container, role, text) {
  const node = document.createElement("div");
  node.className = `bubble ${role}`;
  node.textContent = text;
  container.appendChild(node);
  container.scrollTop = container.scrollHeight;
}

export function addEvent(container, text) {
  const node = document.createElement("div");
  node.className = "meta";
  node.textContent = text;
  container.appendChild(node);
  container.scrollTop = container.scrollHeight;
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

  if (["add_task", "complete_task", "delete_task", "clear_completed"].includes(toolResult.name)) {
    const card = document.createElement("div");
    card.className = "task";
    card.textContent = `${toolResult.name}: ${JSON.stringify(toolResult.result)}`;
    container.prepend(card);
  }
}
