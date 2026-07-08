let adminJwt = localStorage.getItem("admin_jwt") || "";
const CFG = window.TAIA_CONFIG || {};
const ERP_API = CFG.ERP_API_URL || `http://${window.location.hostname}:8801`;
const FASTAPI_URL = CFG.AI_API_URL || `http://${window.location.hostname}:8000`;

const ADMIN_AUTH_URL = "/api/v1/auth/login";
const ADMIN_TEST_EMAIL = "admin@technify.edu";
const ADMIN_TEST_PASSWORD = "admin123";
const ADMIN_USER_ID = "ADM-0001";
const AUTO_REFRESH_MS = 15000;
const RAG_MODE_KEY = "admin_rag_mode";

let allLogs = [];
let refreshInterval = null;
let latencyChart = null;
let intentChart = null;

window.onload = function () {
  initTheme();
  initSidebar();
  updateLoginPanel();
  if (adminJwt) {
    fetchLogs();
    startAutoRefresh();
    initRagPanel();
  }
};

function initTheme() {
  const savedTheme = localStorage.getItem("theme") || "light";
  document.documentElement.setAttribute("data-theme", savedTheme);
  updateThemeIcon(savedTheme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  const target = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", target);
  localStorage.setItem("theme", target);
  updateThemeIcon(target);
  updateCharts(getFilteredLogs());
}

function updateThemeIcon(theme) {
  const btn = document.getElementById("themeToggleBtn");
  if (!btn) return;
  btn.innerHTML =
    theme === "dark"
      ? '<i class="fas fa-sun"></i> Light Mode'
      : '<i class="fas fa-moon"></i> Dark Mode';
}

function parseJwtPayload(token) {
  try {
    const base64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function toggleSidebar() {
  const sidebar = document.getElementById("sidebar");
  const overlay = document.getElementById("sidebarOverlay");
  if (sidebar) sidebar.classList.toggle("open");
  if (overlay) overlay.classList.toggle("open");
}

function initSidebar() {
  const titleEl = document.getElementById("sidebarTitle");
  const userInfoEl = document.getElementById("adminUserInfo");
  const nameEl = document.getElementById("adminUserName");
  const roleEl = document.getElementById("adminUserRole");
  const avatarEl = document.getElementById("adminAvatar");

  const token = adminJwt || localStorage.getItem("taia_jwt") || "";
  const payload = token ? parseJwtPayload(token) : null;
  const role = (
    payload?.role ||
    localStorage.getItem("taia_role") ||
    ""
  ).toLowerCase();
  const name = payload?.name || payload?.sub || "Admin User";
  const userId = payload?.sub || ADMIN_USER_ID;

  if (titleEl) titleEl.textContent = "Admin Panel";
  if (!userInfoEl) return;

  if (token && (role === "admin" || adminJwt)) {
    userInfoEl.style.display = "block";
    if (nameEl) nameEl.textContent = name || userId;
    if (roleEl) roleEl.textContent = "admin";
    if (avatarEl) avatarEl.textContent = (name || userId).charAt(0).toUpperCase();
  } else if (token) {
    userInfoEl.style.display = "block";
    if (nameEl) nameEl.textContent = name || userId;
    if (roleEl) roleEl.textContent = role || "user";
    if (avatarEl) avatarEl.textContent = (name || userId).charAt(0).toUpperCase();
  } else {
    userInfoEl.style.display = "block";
    if (nameEl) nameEl.textContent = "Not signed in";
    if (roleEl) roleEl.textContent = "guest";
    if (avatarEl) avatarEl.textContent = "?";
  }
}

function updateLoginPanel() {
  const loginPanel = document.getElementById("adminLoginPanel");
  const dashboardContent = document.getElementById("dashboardContent");
  if (!loginPanel || !dashboardContent) return;

  if (adminJwt) {
    loginPanel.style.display = "none";
    dashboardContent.style.display = "block";
  } else {
    loginPanel.style.display = "flex";
    dashboardContent.style.display = "none";
  }
}

function showLoginError(message) {
  const err = document.getElementById("adminLoginError");
  if (!err) return;
  err.style.display = "block";
  err.textContent = message;
}

function startAutoRefresh() {
  stopAutoRefresh();
  refreshInterval = setInterval(() => fetchLogs(true), AUTO_REFRESH_MS);
}

function stopAutoRefresh() {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = null;
  }
}

function getChartColors() {
  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  return {
    text: isDark ? "#94a3b8" : "#64748b",
    grid: isDark ? "rgba(255,255,255,0.06)" : "rgba(15,23,42,0.06)",
    line: "#10A37F",
    fill: "rgba(16, 163, 127, 0.12)",
  };
}

function categorizeIntent(intent) {
  const value = (intent || "").toLowerCase();
  if (value.includes("attendance")) return "Attendance";
  if (value === "gpa" || value === "results") return "GPA";
  if (
    value.includes("fee") ||
    value.includes("finance") ||
    value === "fees"
  ) {
    return "Finance";
  }
  return "Other";
}

function getFilteredLogs() {
  const userFilter = (document.getElementById("filterUserId")?.value || "").trim().toLowerCase();
  const intentFilter = (document.getElementById("filterIntent")?.value || "").trim().toLowerCase();
  const roleFilter = (document.getElementById("filterRole")?.value || "").trim().toLowerCase();

  return allLogs.filter((log) => {
    const userMatch = !userFilter || (log.user_id || "").toLowerCase().includes(userFilter);
    const intentMatch = !intentFilter || (log.intent || "").toLowerCase().includes(intentFilter);
    const roleMatch = !roleFilter || (log.role || "").toLowerCase() === roleFilter;
    return userMatch && intentMatch && roleMatch;
  });
}

function applyFilters() {
  renderLogsTable(getFilteredLogs());
  updateStats(getFilteredLogs());
  updateCharts(getFilteredLogs());
}

function updateStats(logs) {
  document.getElementById("totalQueries").textContent = allLogs.length;
  document.getElementById("filteredCount").textContent = logs.length;

  let totalLatency = 0;
  let validLatencies = 0;
  logs.forEach((log) => {
    if (log.latency !== null && log.latency !== undefined) {
      totalLatency += parseFloat(log.latency);
      validLatencies++;
    }
  });

  document.getElementById("avgLatency").textContent =
    validLatencies > 0 ? (totalLatency / validLatencies).toFixed(2) : "-";
}

function setChartVisibility(chartWrapId, chartEmptyId, hasData) {
  const wrap = document.getElementById(chartWrapId);
  const empty = document.getElementById(chartEmptyId);
  if (wrap) wrap.style.display = hasData ? "block" : "none";
  if (empty) {
    empty.style.display = hasData ? "none" : "flex";
    empty.classList.toggle("hidden", hasData);
  }
}

function updateCharts(logs) {
  if (typeof Chart === "undefined") return;

  const colors = getChartColors();
  const lastTen = [...logs].slice(0, 10).reverse();
  const hasLatencyData =
    lastTen.length > 0 &&
    lastTen.some((log) => log.latency !== null && log.latency !== undefined);

  const intentCounts = { Attendance: 0, GPA: 0, Finance: 0, Other: 0 };
  logs.forEach((log) => {
    const category = categorizeIntent(log.intent);
    intentCounts[category]++;
  });
  const hasIntentData = logs.length > 0 && Object.values(intentCounts).some((n) => n > 0);

  setChartVisibility("latencyChartWrap", "latencyChartEmpty", hasLatencyData);
  setChartVisibility("intentChartWrap", "intentChartEmpty", hasIntentData);

  const latencyCtx = document.getElementById("latencyChart");
  if (latencyCtx) {
    if (latencyChart) {
      latencyChart.destroy();
      latencyChart = null;
    }

    if (hasLatencyData) {
      const latencyLabels = lastTen.map((log, index) => `#${log.id || index + 1}`);
      const latencyValues = lastTen.map((log) => parseFloat(log.latency) || 0);

      latencyChart = new Chart(latencyCtx, {
        type: "line",
        data: {
          labels: latencyLabels,
          datasets: [
            {
              label: "Latency (s)",
              data: latencyValues,
              borderColor: colors.line,
              backgroundColor: colors.fill,
              tension: 0.35,
              fill: true,
              pointRadius: 3,
              pointHoverRadius: 5,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: {
              ticks: { color: colors.text, font: { size: 10 } },
              grid: { color: colors.grid },
            },
            y: {
              beginAtZero: true,
              ticks: { color: colors.text, font: { size: 10 } },
              grid: { color: colors.grid },
            },
          },
        },
      });
    }
  }

  const intentCtx = document.getElementById("intentChart");
  if (intentCtx) {
    if (intentChart) {
      intentChart.destroy();
      intentChart = null;
    }

    if (hasIntentData) {
      intentChart = new Chart(intentCtx, {
        type: "doughnut",
        data: {
          labels: Object.keys(intentCounts),
          datasets: [
            {
              data: Object.values(intentCounts),
              backgroundColor: ["#10A37F", "#6366f1", "#f59e0b", "#94a3b8"],
              borderWidth: 0,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "bottom",
              labels: { color: colors.text, boxWidth: 10, padding: 10, font: { size: 10 } },
            },
          },
        },
      });
    }
  }
}

function renderLogsTable(logs) {
  const tbody = document.getElementById("logsTableBody");
  if (!tbody) return;

  tbody.innerHTML = "";

  if (logs.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="6" style="text-align: center; color: var(--text-secondary);">No logs match your filters.</td></tr>';
    return;
  }

  logs.forEach((log) => {
    const tr = document.createElement("tr");
    const date = new Date(log.timestamp);
    const formattedDate = date.toLocaleString();
    const roleLower = (log.role || "").toLowerCase();
    const roleColor =
      roleLower === "admin" ? "#ef4444" : roleLower === "faculty" ? "#8b5cf6" : "#3b82f6";

    tr.innerHTML = `
      <td>#${log.id}</td>
      <td style="color: var(--text-secondary);">${formattedDate}</td>
      <td style="font-family: monospace; font-size: 12px;">${log.user_id}</td>
      <td><span class="badge" style="background-color: ${roleColor};">${log.role}</span></td>
      <td><code style="font-size: 12px;">${log.intent || "-"}</code></td>
      <td style="color: #10b981; font-weight: 600;">${log.latency != null ? log.latency + "s" : "-"}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function handleAdminLogin(event) {
  event.preventDefault();

  const email = document.getElementById("adminEmail").value.trim();
  const password = document.getElementById("adminPassword").value;
  const loginBtn = document.getElementById("adminLoginBtn");
  const err = document.getElementById("adminLoginError");

  if (err) err.style.display = "none";

  if (password !== ADMIN_TEST_PASSWORD) {
    showLoginError("Invalid password. Use admin123 for local testing.");
    return;
  }

  const userId =
    !email || email.toLowerCase() === ADMIN_TEST_EMAIL.toLowerCase()
      ? ADMIN_USER_ID
      : email;

  const loginPayload = { user_id: userId, role: "admin" };

  const originalText = loginBtn.innerHTML;
  loginBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Signing in...';
  loginBtn.disabled = true;

  try {
    const response = await fetch(ADMIN_AUTH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(loginPayload),
    });

    let data;
    try {
      data = await response.json();
    } catch (parseErr) {
      console.error("Invalid JSON response:", parseErr);
      throw new Error("Invalid response from ERP server");
    }

    if (!response.ok) {
      throw new Error(data.detail || data.message || "Admin login failed");
    }

    localStorage.setItem("admin_jwt", data.token);
    location.reload();
  } catch (error) {
    console.error("Network error: ", error);
    const isNetworkError =
      error instanceof TypeError ||
      (error.message && error.message.toLowerCase().includes("failed to fetch"));
    showLoginError(
      isNetworkError
        ? "Cannot connect to the ERP server. Please make sure it is running (docker compose up -d erp)."
        : error.message || "Admin login failed."
    );
  } finally {
    loginBtn.innerHTML = originalText;
    loginBtn.disabled = false;
  }
}

function adminLogout() {
  adminJwt = "";
  localStorage.removeItem("admin_jwt");
  stopAutoRefresh();
  allLogs = [];

  if (latencyChart) {
    latencyChart.destroy();
    latencyChart = null;
  }
  if (intentChart) {
    intentChart.destroy();
    intentChart = null;
  }

  setChartVisibility("latencyChartWrap", "latencyChartEmpty", false);
  setChartVisibility("intentChartWrap", "intentChartEmpty", false);

  initSidebar();
  updateLoginPanel();

  const tbody = document.getElementById("logsTableBody");
  if (tbody) {
    tbody.innerHTML =
      '<tr><td colspan="6" style="text-align: center; color: var(--text-secondary);">Please sign in to view audit logs.</td></tr>';
  }
}

async function fetchLogs(silent = false) {
  const tbody = document.getElementById("logsTableBody");
  if (!tbody) return;

  if (!silent) {
    tbody.innerHTML =
      '<tr><td colspan="6" style="text-align: center;">Loading logs...</td></tr>';
  }

  adminJwt = localStorage.getItem("admin_jwt") || "";

  if (!adminJwt) {
    tbody.innerHTML =
      '<tr><td colspan="6" style="text-align: center; color: #ef4444;">Please sign in with your admin credentials above.</td></tr>';
    return;
  }

  try {
    const response = await fetch(`${FASTAPI_URL}/api/v1/admin/audit-logs`, {
      method: "GET",
      headers: { Authorization: `Bearer ${adminJwt}` },
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(
        err.detail || "Authentication failed. Please sign in again as Admin."
      );
    }

    allLogs = await response.json();
    applyFilters();
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #ef4444;">Error fetching logs: ${error.message}</td></tr>`;
  }
}

// ── Admin RAG (hybrid search over uploaded ERP data) ─────────────────────────

function isRagModeEnabled() {
  return localStorage.getItem(RAG_MODE_KEY) === "true";
}

function setRagModeEnabled(enabled) {
  localStorage.setItem(RAG_MODE_KEY, enabled ? "true" : "false");
}

function updateRagChatVisibility() {
  const section = document.getElementById("ragChatSection");
  if (section) {
    section.style.display = isRagModeEnabled() ? "block" : "none";
  }
}

function setRagStatus(message, type = "") {
  const el = document.getElementById("ragUploadStatus");
  if (!el) return;
  el.textContent = message;
  el.className = "rag-status" + (type ? ` ${type}` : "");
}

async function initRagPanel() {
  const toggle = document.getElementById("ragModeToggle");
  if (toggle) {
    toggle.checked = isRagModeEnabled();
  }
  updateRagChatVisibility();

  if (!adminJwt) return;

  try {
    const response = await fetch(`${FASTAPI_URL}/api/v1/admin/rag/status`, {
      headers: { Authorization: `Bearer ${adminJwt}` },
    });
    if (response.ok) {
      const data = await response.json();
      if (data.documents_indexed > 0) {
        setRagStatus(
          `${data.documents_indexed} document(s) indexed for RAG (hybrid BM25 + vector).`,
          "success"
        );
      }
    }
  } catch (err) {
    console.warn("RAG status check failed:", err);
  }
}

function onRagModeToggle() {
  const toggle = document.getElementById("ragModeToggle");
  setRagModeEnabled(!!toggle?.checked);
  updateRagChatVisibility();
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

  // ── Read checkbox state and append mode ──
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