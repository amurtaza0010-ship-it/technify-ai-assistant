let adminJwt = localStorage.getItem("admin_jwt") || "";
const CFG = window.TAIA_CONFIG || {};
const ERP_API = CFG.ERP_API_URL || `http://${window.location.hostname}:8801`;
const FASTAPI_URL = CFG.AI_API_URL || `http://${window.location.hostname}:8000`;

const ADMIN_AUTH_URL = "/api/v1/auth/login";
const ADMIN_TEST_EMAIL = "admin@technify.edu";
const ADMIN_TEST_PASSWORD = "admin123";
const ADMIN_USER_ID = "ADM-0001";
const AUTO_REFRESH_MS = 15000;

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
    // Show RAG Chat sidebar link after login
    const ragLink = document.getElementById("ragChatSidebarLink");
    if (ragLink) ragLink.style.display = "";
  } else {
    loginPanel.style.display = "flex";
    dashboardContent.style.display = "none";
    // Hide RAG Chat sidebar link when not logged in
    const ragLink = document.getElementById("ragChatSidebarLink");
    if (ragLink) ragLink.style.display = "none";
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