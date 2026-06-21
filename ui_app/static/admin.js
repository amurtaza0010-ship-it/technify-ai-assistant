let adminJwt = localStorage.getItem("admin_jwt") || "";
const ERP_API = `http://${window.location.hostname}:8001`;
const FASTAPI_URL = `http://${window.location.hostname}:8000`;

const ADMIN_TEST_EMAIL = "admin@technify.edu";
const ADMIN_TEST_PASSWORD = "admin123";
const ADMIN_USER_ID = "ADM-0001";

window.onload = function () {
  initTheme();
  initSidebar();
  updateLoginPanel();
  if (adminJwt) {
    fetchLogs();
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

  if (titleEl) {
    titleEl.textContent = "Admin Panel";
  }

  if (!userInfoEl) return;

  if (token && (role === "admin" || adminJwt)) {
    userInfoEl.style.display = "block";
    if (nameEl) nameEl.textContent = name || userId;
    if (roleEl) roleEl.textContent = "admin";
    if (avatarEl) {
      avatarEl.textContent = (name || userId).charAt(0).toUpperCase();
    }
  } else if (token) {
    userInfoEl.style.display = "block";
    if (nameEl) nameEl.textContent = name || userId;
    if (roleEl) roleEl.textContent = role || "user";
    if (avatarEl) {
      avatarEl.textContent = (name || userId).charAt(0).toUpperCase();
    }
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
    loginPanel.style.display = "block";
    dashboardContent.style.display = "none";
  }
}

function showLoginError(message) {
  const err = document.getElementById("adminLoginError");
  if (!err) return;
  err.style.display = "block";
  err.textContent = message;
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
    email.toLowerCase() === ADMIN_TEST_EMAIL.toLowerCase() || email === ""
      ? ADMIN_USER_ID
      : email;

  const originalText = loginBtn.innerHTML;
  loginBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Signing in...';
  loginBtn.disabled = true;

  try {
    const response = await fetch(`${ERP_API}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, role: "admin" }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Admin login failed");
    }

    adminJwt = data.token;
    localStorage.setItem("admin_jwt", adminJwt);
    localStorage.setItem("taia_jwt", adminJwt);
    localStorage.setItem("taia_role", "admin");

    initSidebar();
    updateLoginPanel();
    fetchLogs();
  } catch (error) {
    showLoginError(error.message || "Could not connect to Mock ERP on port 8001.");
  } finally {
    loginBtn.innerHTML = originalText;
    loginBtn.disabled = false;
  }
}

function adminLogout() {
  adminJwt = "";
  localStorage.removeItem("admin_jwt");
  initSidebar();
  updateLoginPanel();

  const tbody = document.getElementById("logsTableBody");
  if (tbody) {
    tbody.innerHTML =
      '<tr><td colspan="6" style="text-align: center; color: var(--text-secondary);">Please sign in to view audit logs.</td></tr>';
  }
}

async function fetchLogs() {
  const tbody = document.getElementById("logsTableBody");
  if (!tbody) return;

  tbody.innerHTML =
    '<tr><td colspan="6" style="text-align: center;">Loading logs...</td></tr>';

  adminJwt = localStorage.getItem("admin_jwt") || "";

  if (!adminJwt) {
    tbody.innerHTML =
      '<tr><td colspan="6" style="text-align: center; color: #ef4444;">Please sign in with your admin credentials above.</td></tr>';
    return;
  }

  const headers = {
    Authorization: `Bearer ${adminJwt}`,
  };

  try {
    const response = await fetch(`${FASTAPI_URL}/api/v1/admin/audit-logs`, {
      method: "GET",
      headers,
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(
        err.detail || "Authentication failed. Please sign in again as Admin."
      );
    }

    const logs = await response.json();

    document.getElementById("totalQueries").textContent = logs.length;

    let totalLatency = 0;
    let validLatencies = 0;

    tbody.innerHTML = "";
    if (logs.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="6" style="text-align: center;">No logs found.</td></tr>';
      document.getElementById("avgLatency").textContent = "-";
      return;
    }

    logs.forEach((log) => {
      if (log.latency !== null && log.latency !== undefined) {
        totalLatency += parseFloat(log.latency);
        validLatencies++;
      }

      const tr = document.createElement("tr");
      const date = new Date(log.timestamp);
      const formattedDate = date.toLocaleString();
      const roleColor =
        (log.role || "").toLowerCase() === "admin" ? "#ef4444" : "#3b82f6";

      tr.innerHTML = `
                <td>#${log.id}</td>
                <td style="color: #888;">${formattedDate}</td>
                <td style="font-family: monospace;">${log.user_id}</td>
                <td><span class="badge" style="background-color: ${roleColor};">${log.role}</span></td>
                <td>${log.intent || "-"}</td>
                <td style="color: #10b981;">${log.latency ? log.latency + "s" : "-"}</td>
            `;
      tbody.appendChild(tr);
    });

    if (validLatencies > 0) {
      const avg = (totalLatency / validLatencies).toFixed(2);
      document.getElementById("avgLatency").textContent = avg;
    } else {
      document.getElementById("avgLatency").textContent = "-";
    }
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #ef4444;">Error fetching logs: ${error.message}</td></tr>`;
  }
}
