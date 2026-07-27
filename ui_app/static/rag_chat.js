let adminJwt = localStorage.getItem("admin_jwt") || "";
const CFG = window.TAIA_CONFIG || {};
const FASTAPI_URL = CFG.AI_API_URL || `http://${window.location.hostname}:8000`;
const RAG_MODE_KEY = "admin_rag_mode";

if (!adminJwt) {
  window.location.href = "/admin";
}

function initTheme() {
  const savedTheme = localStorage.getItem("theme") || "light";
  document.documentElement.setAttribute("data-theme", savedTheme);
}

initTheme();

function isRagModeEnabled() {
  return localStorage.getItem(RAG_MODE_KEY) === "true";
}

function setRagModeEnabled(enabled) {
  localStorage.setItem(RAG_MODE_KEY, enabled ? "true" : "false");
}

function setRagStatus(message, type = "") {
  const el = document.getElementById("ragUploadStatus");
  if (!el) return;
  el.textContent = message;
  el.className = "rag-status" + (type ? ` ${type}` : "");
}

window.onload = function () {
  const toggle = document.getElementById("ragModeToggle");
  if (toggle) {
    toggle.checked = isRagModeEnabled();
  }
  if (!adminJwt) return;
  fetch(`${FASTAPI_URL}/api/v1/admin/rag/status`, {
    headers: { Authorization: `Bearer ${adminJwt}` },
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.documents_indexed > 0) {
        setRagStatus(
          `${data.documents_indexed} document(s) indexed for RAG (hybrid BM25 + vector).`,
          "success"
        );
      }
    })
    .catch(console.warn);
};

function onRagModeToggle() {
  const toggle = document.getElementById("ragModeToggle");
  setRagModeEnabled(!!toggle?.checked);
  if (toggle?.checked) {
    setRagStatus("RAG mode enabled — questions below use uploaded ERP data.", "success");
  } else {
    setRagStatus("RAG mode disabled — use Main Chat for mock ERP queries.");
  }
}

async function handleRagUpload(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file || !adminJwt) return;

  const allowed = [".csv", ".xlsx", ".json", ".pdf", ".docx"];
  const lower = file.name.toLowerCase();
  if (!allowed.some((ext) => lower.endsWith(ext))) {
    setRagStatus("Please upload a .csv, .xlsx, .json, .pdf, or .docx file.", "error");
    return;
  }

  setRagStatus("Uploading and indexing…");

  const formData = new FormData();
  formData.append("file", file);

  const appendCheckbox = document.getElementById("ragAppendMode");
  const mode = appendCheckbox?.checked ? "append" : "replace";
  formData.append("mode", mode);

  try {
    const response = await fetch(`${FASTAPI_URL}/api/v1/admin/rag/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${adminJwt}` },
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Upload failed");
    }
    setRagStatus(
      `Success: ${data.documents_indexed} document(s) indexed (total: ${data.total_documents || data.documents_indexed}).`,
      "success"
    );
    const toggle = document.getElementById("ragModeToggle");
    if (toggle) {
      toggle.checked = true;
      onRagModeToggle();
    }
  } catch (err) {
    setRagStatus(`Upload error: ${err.message}`, "error");
  }
}

function appendRagMessage(text, role) {
  const container = document.getElementById("ragChatMessages");
  if (!container) return null;
  const div = document.createElement("div");
  div.className = `rag-msg ${role}`;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

async function sendRagQuery(event) {
  event.preventDefault();
  if (!isRagModeEnabled()) {
    setRagStatus("Enable RAG Mode to query uploaded data.", "error");
    return;
  }

  const input = document.getElementById("ragChatInput");
  const sendBtn = document.getElementById("ragSendBtn");
  const msg = (input?.value || "").trim();
  if (!msg || !adminJwt) return;

  appendRagMessage(msg, "user");
  input.value = "";
  if (sendBtn) sendBtn.disabled = true;

  const assistantEl = appendRagMessage("…", "assistant");
  let fullText = "";

  try {
    const response = await fetch(`${FASTAPI_URL}/api/v1/chat/rag`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${adminJwt}`,
        "x-session-id": `admin_rag_${Date.now()}`,
      },
      body: JSON.stringify({ message: msg }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || "RAG query failed");
    }
    if (!response.body) {
      throw new Error("No response body");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (payload === "[DONE]") continue;
        let data;
        try {
          data = JSON.parse(payload);
        } catch {
          continue;
        }
        if (data.text) {
          fullText += data.text;
          if (assistantEl) assistantEl.textContent = fullText;
        }
      }
    }

    if (!fullText && assistantEl) {
      assistantEl.textContent = "No response received.";
    }
  } catch (err) {
    if (assistantEl) {
      assistantEl.textContent = `Error: ${err.message}`;
    }
  } finally {
    if (sendBtn) sendBtn.disabled = false;
  }
}