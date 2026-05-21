const pageTitle = document.getElementById("pageTitle");
const clock = document.getElementById("clock");
const appShell = document.getElementById("appShell");
const entryShell = document.getElementById("entryShell");
const loginShell = document.getElementById("loginShell");

const startLoginBtn = document.getElementById("startLoginBtn");
const entryBars = Array.from(document.querySelectorAll("#entryBars span"));
const entryPulseText = document.getElementById("entryPulseText");

const adminLoginForm = document.getElementById("adminLoginForm");
const monitorLoginForm = document.getElementById("monitorLoginForm");
const personalLoginForm = document.getElementById("personalLoginForm");
const roleTabs = Array.from(document.querySelectorAll(".role-tab"));

const adminUsername = document.getElementById("adminUsername");
const adminPassword = document.getElementById("adminPassword");
const adminTotp = document.getElementById("adminTotp");
const adminLoginError = document.getElementById("adminLoginError");

const monitorUsername = document.getElementById("monitorUsername");
const monitorPassword = document.getElementById("monitorPassword");
const monitorLoginError = document.getElementById("monitorLoginError");

const personalUsername = document.getElementById("personalUsername");
const personalPassword = document.getElementById("personalPassword");
const personalLoginError = document.getElementById("personalLoginError");

const logoutBtn = document.getElementById("logoutBtn");
const userDisplayName = document.getElementById("userDisplayName");
const userRoleBadge = document.getElementById("userRoleBadge");
const connectState = document.getElementById("connectState");
const addDeviceBtn = document.getElementById("addDeviceBtn");
const addUserBtn = document.getElementById("addUserBtn");

const backToDevicesBtn = document.getElementById("backToDevicesBtn");
const deviceManualOpenBtn = document.getElementById("deviceManualOpenBtn");
const deviceOpenMessage = document.getElementById("deviceOpenMessage");
const deviceDetailTitle = document.getElementById("deviceDetailTitle");
const deviceDetailName = document.getElementById("deviceDetailName");
const deviceDetailStatus = document.getElementById("deviceDetailStatus");
const deviceDetailMode = document.getElementById("deviceDetailMode");
const deviceDetailHeartbeat = document.getElementById("deviceDetailHeartbeat");
const deviceDetailTodayPass = document.getElementById("deviceDetailTodayPass");

const navItems = Array.from(document.querySelectorAll(".nav-item"));
const views = Array.from(document.querySelectorAll(".view"));

const API_BASE = window.ACCESS_API_BASE || "http://127.0.0.1:8000";
const STORAGE_KEY = "access_console_session_v2";
const STATS_BASELINE_KEY = "access_console_stats_baseline_v1";
const DATA_REFRESH_MS = 3000;
const ATTENDANCE_STATUS_OPTIONS = ["正常", "迟到", "在岗", "早退", "缺勤", "请假"];

const VIEW_TITLES = {
  dashboard: "总览看板",
  devices: "设备管理",
  records: "通行记录",
  attendance: "考勤管理",
  myActivity: "我的考勤与通行记录",
  settings: "系统设置",
  deviceDetail: "设备详情",
};

const state = {
  users: [],
  token: null,
  user: null,
  devices: [],
  records: [],
  attendance: [],
  myActivity: null,
  events: [],
  statsBaseline: null,
  selectedDeviceId: null,
  deviceDetail: null,
  deviceRecords: [],
  currentRecordFilter: "all",
  activeView: null,
  refreshTimer: null,
  isRefreshing: false,
};

const loginContexts = [
  {
    form: adminLoginForm,
    username: adminUsername,
    password: adminPassword,
    totp: adminTotp,
    error: adminLoginError,
    requireTotp: true,
    label: "管理员",
  },
  {
    form: monitorLoginForm,
    username: monitorUsername,
    password: monitorPassword,
    totp: null,
    error: monitorLoginError,
    requireTotp: false,
    label: "监视员",
  },
  {
    form: personalLoginForm,
    username: personalUsername,
    password: personalPassword,
    totp: null,
    error: personalLoginError,
    requireTotp: false,
    label: "个人",
  },
];

function formatNow() {
  const now = new Date();
  const y = now.getFullYear();
  const m = `${now.getMonth() + 1}`.padStart(2, "0");
  const d = `${now.getDate()}`.padStart(2, "0");
  const h = `${now.getHours()}`.padStart(2, "0");
  const min = `${now.getMinutes()}`.padStart(2, "0");
  const s = `${now.getSeconds()}`.padStart(2, "0");
  return `${y}-${m}-${d} ${h}:${min}:${s}`;
}

function setHidden(el, hidden) {
  if (!el) return;
  el.classList.toggle("hidden", hidden);
}

function setLoginError(el, message = "") {
  if (!el) return;
  el.textContent = message;
  setHidden(el, !message);
}

function clearAllLoginErrors() {
  loginContexts.forEach((ctx) => setLoginError(ctx.error, ""));
}

function tablePlaceholder(cols, message) {
  return `<tr><td colspan="${cols}" class="muted">${message}</td></tr>`;
}

function setBackendState(text, ok) {
  connectState.textContent = text;
  connectState.classList.toggle("ok", !!ok);
}

function showIntro() {
  setHidden(appShell, true);
  setHidden(loginShell, true);
  setHidden(entryShell, false);
}

function showLogin() {
  setHidden(appShell, true);
  setHidden(entryShell, true);
  setHidden(loginShell, false);
}

function showApp() {
  setHidden(entryShell, true);
  setHidden(loginShell, true);
  setHidden(appShell, false);
}

function saveSession(token, user) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ access_token: token, user }));
}

function loadSession() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function clearSession() {
  stopDataRefresh();
  sessionStorage.removeItem(STORAGE_KEY);
}

function todayKey() {
  const now = new Date();
  const y = now.getFullYear();
  const m = `${now.getMonth() + 1}`.padStart(2, "0");
  const d = `${now.getDate()}`.padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function loadStatsBaseline() {
  try {
    const raw = localStorage.getItem(STATS_BASELINE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && parsed.date === todayKey() ? parsed : null;
  } catch {
    return null;
  }
}

function saveStatsBaseline(baseline) {
  state.statsBaseline = baseline;
  localStorage.setItem(STATS_BASELINE_KEY, JSON.stringify(baseline));
}

function getRawStats() {
  return {
    pass: state.records.filter((r) => r.result === "pass").length,
    reject: state.records.filter((r) => r.result === "reject").length,
  };
}

function normalizeRole(role) {
  const map = {
    admin: "管理员",
    operator: "监视员",
    monitor: "监视员",
    user: "个人用户",
    personal: "个人用户",
  };
  return map[role] || "访客";
}

function applyPermissions(permissions = []) {
  const allowed = new Set(permissions);
  const hideLocked = state.user?.role === "personal";
  let firstAllowedView = null;

  navItems.forEach((btn) => {
    if (!btn.dataset.tipBase) {
      btn.dataset.tipBase = btn.dataset.tip || btn.textContent.trim();
    }

    const viewName = btn.dataset.view;
    const permitted = allowed.has(viewName);

    btn.disabled = !permitted;
    btn.classList.toggle("locked", !permitted);
    btn.classList.toggle("role-hidden", hideLocked && !permitted);

    if (permitted) {
      btn.dataset.tip = btn.dataset.tipBase;
      if (!firstAllowedView) firstAllowedView = viewName;
    } else {
      btn.dataset.tip = `${btn.textContent.trim()}（权限不足）`;
    }
  });

  return firstAllowedView;
}

function setActiveView(viewName) {
  let resolvedView = viewName;
  const targetBtn = navItems.find((btn) => btn.dataset.view === viewName && !btn.disabled);

  if (!targetBtn && viewName !== "deviceDetail") {
    const fallbackBtn = navItems.find((btn) => !btn.disabled);
    if (!fallbackBtn) return;
    resolvedView = fallbackBtn.dataset.view;
  }

  views.forEach((v) => {
    v.classList.toggle("active", v.id === resolvedView);
  });

  navItems.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === resolvedView);
  });

  state.activeView = resolvedView;
  pageTitle.textContent = VIEW_TITLES[resolvedView] || resolvedView;
}

async function apiRequest(path, { method = "GET", body = null, auth = true } = {}) {
  const headers = {};
  if (auth) {
    if (!state.token) {
      const err = new Error("未登录");
      err.status = 401;
      throw err;
    }
    headers.Authorization = `Bearer ${state.token}`;
  }
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== null ? JSON.stringify(body) : undefined,
  });

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(data.detail || `请求失败 (${resp.status})`);
    err.status = resp.status;
    throw err;
  }

  return data;
}

async function apiLogin(username, password, totpCode = "") {
  return apiRequest("/api/auth/login", {
    method: "POST",
    auth: false,
    body: { username, password, totp_code: totpCode || null },
  });
}

async function apiMe(token) {
  const resp = await fetch(`${API_BASE}/api/auth/me`, {
    method: "GET",
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(data.detail || "会话失效");
    err.status = resp.status;
    throw err;
  }
  return data;
}

async function apiDevices() {
  return apiRequest("/api/devices");
}

async function apiAddDevice(payload) {
  return apiRequest("/api/devices", { method: "POST", body: payload });
}

async function apiCreateUser(payload) {
  return apiRequest("/api/users", { method: "POST", body: payload });
}

async function apiUsers() {
  return apiRequest("/api/users");
}

async function apiUpdateUser(userId, payload) {
  return apiRequest(`/api/users/${userId}`, {
    method: "PUT",
    body: payload,
  });
}

async function apiDeleteUser(userId) {
  return apiRequest(`/api/users/${userId}`, {
    method: "DELETE",
  });
}

async function apiRecords(filter = "all") {
  return apiRequest(`/api/records?result=${encodeURIComponent(filter)}`);
}

async function apiAttendance() {
  return apiRequest("/api/attendance");
}
async function apiMyActivity() {
  return apiRequest("/api/me/activity");
}

async function apiUpdateAttendanceStatus(payload) {
  return apiRequest("/api/attendance/status", { method: "PATCH", body: payload });
}

async function apiDeviceDetail(deviceId) {
  return apiRequest(`/api/devices/${encodeURIComponent(deviceId)}`);
}

async function apiDeviceRecords(deviceId) {
  return apiRequest(`/api/devices/${encodeURIComponent(deviceId)}/records`);
}

async function apiDeviceEvents(limit = 50) {
  return apiRequest(`/api/device-events?limit=${encodeURIComponent(limit)}`);
}

async function apiDeviceOpen(deviceId) {
  return apiRequest(`/api/devices/${encodeURIComponent(deviceId)}/open`, {
    method: "POST",
    body: {},
  });
}

function handleApiError(err, fallbackMessage = "后端请求失败") {
  if (err?.status === 401) {
    clearSession();
    state.token = null;
    state.user = null;
    showLogin();
    setLoginError(adminLoginError, "会话失效，请重新登录");
    setBackendState("会话失效", false);
    return;
  }

  if (err?.status === 403) {
    setBackendState("权限受限", false);
    return;
  }

  setBackendState(fallbackMessage, false);
}

function toEventText(record) {
  const action = record.result === "pass" ? "放行" : "拒绝";
  return `${record.device} ${action} ${record.person}`;
}

function syncEventsFromRecords() {
  state.events = state.records.slice(0, 10).map((r) => ({ t: r.time, text: toEventText(r) }));
  renderEvents();
}

async function refreshDevices() {
  state.devices = await apiDevices();
  renderDoors();
  renderStats();
}

async function refreshRecords(filter = state.currentRecordFilter) {
  state.currentRecordFilter = filter;
  state.records = await apiRecords(filter);
  renderRecords();
  renderStats();
  if (state.user?.role !== "admin") {
    syncEventsFromRecords();
  }
}

async function refreshAttendance() {
  state.attendance = await apiAttendance();
  renderAttendance();
}

async function refreshUsers() {
  if (state.user?.role !== "admin") return;
  state.users = await apiUsers();
  renderUsers();
}


async function refreshMyActivity() {
  state.myActivity = await apiMyActivity();
  renderMyActivity();
}

async function refreshDeviceEvents() {
  state.events = await apiDeviceEvents(10);
  renderEvents();
}

async function refreshAllData() {
  try {
    if (state.user?.role === "admin") {
      await refreshDevices();
      await refreshRecords(state.currentRecordFilter);
      await refreshDeviceEvents();
      await refreshAttendance();
      await refreshUsers();
    } else if (state.user?.role === "operator") {
      await refreshDevices();
      await refreshRecords(state.currentRecordFilter);
      await refreshDeviceEvents();
      await refreshAttendance();
    } else if (state.user?.role === "personal") {
      await refreshMyActivity();
    } else {
      await refreshRecords(state.currentRecordFilter);
      await refreshAttendance();
    }
    setBackendState("后端已连接", true);
  } catch (err) {
    handleApiError(err, "后端同步失败");
  }
}
async function refreshDeviceDetailData() {
  if (!state.selectedDeviceId) return;

  const [detail, records] = await Promise.all([
    apiDeviceDetail(state.selectedDeviceId),
    apiDeviceRecords(state.selectedDeviceId),
  ]);
  state.deviceDetail = detail;
  state.deviceRecords = records;
  renderDeviceDetail();
}

async function refreshCurrentViewData() {
  if (!state.token || !state.user || state.isRefreshing) return;

  state.isRefreshing = true;
  try {
    if (state.activeView === "dashboard") {
      if (state.user.role === "admin") {
        await refreshDevices();
        await refreshRecords(state.currentRecordFilter);
        await refreshDeviceEvents();
      } else if (state.user.role === "operator") {
        await refreshDevices();
        await refreshRecords(state.currentRecordFilter);
        await refreshDeviceEvents();
      } else if (state.user.role === "personal") {
        await refreshMyActivity();
      } else {
        await Promise.all([refreshRecords(state.currentRecordFilter), refreshAttendance()]);
      }
    } else if (state.activeView === "devices") {
      await refreshDevices();
    } else if (state.activeView === "records") {
      await refreshRecords(state.currentRecordFilter);
    } else if (state.activeView === "attendance") {
      await refreshAttendance();
    } else if (state.activeView === "myActivity") {
      await refreshMyActivity();
    } else if (state.activeView === "deviceDetail") {
      await refreshDeviceDetailData();
    }
  } catch (err) {
    handleApiError(err, "Background refresh failed");
  } finally {
    state.isRefreshing = false;
  }
}

function startDataRefresh() {
  stopDataRefresh();
  state.refreshTimer = setInterval(() => {
    refreshCurrentViewData();
  }, DATA_REFRESH_MS);
}

function stopDataRefresh() {
  if (!state.refreshTimer) return;
  clearInterval(state.refreshTimer);
  state.refreshTimer = null;
}

function applyUser(user, token, persist = true) {
  state.user = user;
  state.token = token;

  userDisplayName.textContent = user.display_name || user.displayName || user.username;
  userRoleBadge.textContent = normalizeRole(user.role);

  const firstAllowedView = applyPermissions(user.permissions || []);
  setActiveView(firstAllowedView);

  if (addDeviceBtn) {
    addDeviceBtn.classList.toggle("hidden", user.role !== "admin");
  }
  if (addUserBtn) {
    addUserBtn.classList.toggle("hidden", user.role !== "admin");
  }

  if (persist) {
    saveSession(token, user);
  }

  clearAllLoginErrors();
  loginContexts.forEach((ctx) => ctx.form && ctx.form.reset());
  showApp();

  refreshAllData();
  startDataRefresh();
}

function validateLoginInput(ctx, username, password, totpCode) {
  if (!username || !password) return `${ctx.label}账号和密码不能为空`;
  if (ctx.requireTotp && !/^\d{6}$/.test(totpCode)) return "管理员动态口令必须是 6 位数字";
  return "";
}

function setActiveLoginRole(roleKey, shouldFocus = true) {
  if (!roleKey) return;

  roleTabs.forEach((tab) => {
    const active = tab.dataset.roleTarget === roleKey;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", active ? "true" : "false");
  });

  loginContexts.forEach((ctx) => {
    const active = ctx.form?.dataset.role === roleKey;
    if (!ctx.form) return;
    setHidden(ctx.form, !active);
    ctx.form.classList.toggle("active", active);
    if (!active) setLoginError(ctx.error, "");
  });

  if (shouldFocus) {
    const targetCtx = loginContexts.find((ctx) => ctx.form?.dataset.role === roleKey);
    targetCtx?.username?.focus();
  }
}

function bindRoleTabs() {
  roleTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      setActiveLoginRole(tab.dataset.roleTarget, true);
    });
  });

  const initialRole = roleTabs.find((tab) => tab.classList.contains("active"))?.dataset.roleTarget || "admin";
  setActiveLoginRole(initialRole, false);
}

function bindEntry() {
  startLoginBtn.addEventListener("click", () => {
    showLogin();
    setActiveLoginRole("admin", true);
  });
}

function bindAuth() {
  loginContexts.forEach((ctx) => {
    ctx.form.addEventListener("submit", async (e) => {
      e.preventDefault();
      clearAllLoginErrors();

      const username = ctx.username.value.trim();
      const password = ctx.password.value;
      const totpCode = (ctx.totp ? ctx.totp.value : "").trim();

      const inputErr = validateLoginInput(ctx, username, password, totpCode);
      if (inputErr) {
        setLoginError(ctx.error, inputErr);
        return;
      }

      try {
        const result = await apiLogin(username, password, totpCode);
        applyUser(result.user, result.access_token, true);
      } catch (err) {
        setLoginError(ctx.error, err.message || "登录失败");
      }
    });
  });

  logoutBtn.addEventListener("click", () => {
    clearSession();
    state.token = null;
    state.user = null;
    showIntro();
  });
}

function bindPasswordToggles() {
  const toggles = Array.from(document.querySelectorAll(".password-toggle"));
  toggles.forEach((toggle) => {
    toggle.addEventListener("click", () => {
      const field = toggle.closest(".password-field");
      const input = field ? field.querySelector("input") : null;
      if (!input) return;

      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      toggle.textContent = isPassword ? "隐藏" : "显示";
      toggle.setAttribute("aria-label", isPassword ? "隐藏密码" : "显示密码");
    });
  });
}

function bindEntryAnimation() {
  if (!entryBars.length || !entryPulseText) return;

  let tick = 0;
  setInterval(() => {
    tick = (tick + 1) % 4;
    entryPulseText.textContent = `系统准备中${".".repeat(tick)}`;

    entryBars.forEach((bar, idx) => {
      const h = 14 + Math.floor(Math.random() * 24) + idx;
      bar.style.height = `${h}px`;
    });
  }, 360);
}

function getDeviceId(device) {
  return device.id || device.device_id || "--";
}

function getDeviceName(device) {
  return device.name || device.gate_name || getDeviceId(device);
}

function isDeviceOnline(device) {
  return device.online === true || device.is_online === true || device.status === "online";
}

function renderDeviceState(device) {
  const online = isDeviceOnline(device);
  return `<span class="dot ${online ? "online" : "offline"}"></span>${online ? "在线" : "离线"}`;
}

function renderDoors() {
  const doorList = document.getElementById("doorList");
  const deviceTable = document.getElementById("deviceTable");
  if (!doorList || !deviceTable) return;

  if (!state.devices || state.devices.length === 0) {
    doorList.innerHTML = '<p class="muted">暂无真实门点数据</p>';
    deviceTable.innerHTML = tablePlaceholder(6, "暂无真实设备数据");
    return;
  }

  doorList.innerHTML = state.devices
    .map((device) => {
      const id = getDeviceId(device);
      return `
        <article class="door-item">
          <strong>${getDeviceName(device)}</strong>
          <p class="muted"><small>${id} · ${device.mode || "UDP"}</small></p>
          <p>${renderDeviceState(device)}</p>
          <p class="muted"><small>最后报文 ${device.last_heartbeat || "--"}</small></p>
          <button class="ghost-btn inline-link device-link" data-device-id="${id}" type="button">查看设备页</button>
        </article>`;
    })
    .join("");

  deviceTable.innerHTML = state.devices
    .map((device) => {
      const id = getDeviceId(device);
      return `
        <tr>
          <td><button class="device-link table-link" data-device-id="${id}" type="button">${id}</button></td>
          <td><button class="device-link table-link" data-device-id="${id}" type="button">${getDeviceName(device)}</button></td>
          <td>${renderDeviceState(device)}</td>
          <td class="muted">${device.mode || "UDP"}</td>
          <td class="muted">${device.firmware || "unknown"}</td>
          <td class="muted">${device.last_heartbeat || "--"}</td>
        </tr>`;
    })
    .join("");
}

function renderUsers() {
  const userTable = document.getElementById("userTable");
  if (!userTable) return;

  if (!state.users || state.users.length === 0) {
    userTable.innerHTML = `<tr><td colspan="6" class="muted" style="text-align: center;">暂无用户数据</td></tr>`;
    return;
  }

  userTable.innerHTML = state.users.map(u => `
    <tr>
      <td>${u.id}</td>
      <td>${u.username}</td>
      <td>${u.display_name}</td>
      <td>
        <span class="tag ${u.role === 'admin' ? 'reject' : 'pass'}">${u.role}</span>
      </td>
      <td>
        <span class="dot ${u.is_active ? 'online' : 'offline'}"></span>
        ${u.is_active ? '正常' : '禁用'}
      </td>
      <td>
        <button class="ghost-btn edit-user-btn" data-user-id="${u.id}">编辑</button>
        <button class="ghost-btn delete-user-btn" style="color: #c92a2a;" data-user-id="${u.id}">删除</button>
      </td>
    </tr>
  `).join("");
}
function renderRecords() {
  const recordTable = document.getElementById("recordTable");

  if (!state.records.length) {
    recordTable.innerHTML = tablePlaceholder(6, "暂无通行记录");
    return;
  }

  recordTable.innerHTML = state.records
    .map(
      (r) => `
      <tr>
        <td>${r.time}</td>
        <td>${r.device}</td>
        <td>${r.person}</td>
        <td class="muted">${r.credential}</td>
        <td><span class="tag ${r.result}">${r.result === "pass" ? "放行" : "拒绝"}</span></td>
        <td class="muted">${r.reason}</td>
      </tr>`
    )
    .join("");
}

function renderAttendance() {
  const attendanceTable = document.getElementById("attendanceTable");

  if (!state.attendance.length) {
    attendanceTable.innerHTML = tablePlaceholder(7, "暂无考勤数据");
    return;
  }

  const canEdit = state.user?.role === "admin";

  attendanceTable.innerHTML = state.attendance
    .map(
      (row) => `
      <tr>
        <td>${row.name}</td>
        <td>${row.dept}</td>
        <td>${row.first_in}</td>
        <td>${row.last_out}</td>
        <td class="muted">${row.status}</td>
        <td>${row.main_gate}</td>
        <td>${
          canEdit
            ? `<button class="ghost-btn attendance-edit-btn" data-person-name="${row.name}" data-attendance-date="${row.attendance_date}" data-current-status="${row.status}" type="button">修改状态</button>`
            : '<span class="muted">-</span>'
        }</td>
      </tr>`
    )
    .join("");
}

function renderMyActivity() {
  const dateEl = document.getElementById("myActivityDate");
  const statusEl = document.getElementById("myAttendanceStatus");
  const firstInEl = document.getElementById("myFirstIn");
  const lastOutEl = document.getElementById("myLastOut");
  const mainGateEl = document.getElementById("myMainGate");
  const tableEl = document.getElementById("myRecordTable");

  if (!dateEl || !statusEl || !firstInEl || !lastOutEl || !mainGateEl || !tableEl) return;

  const data = state.myActivity;
  if (!data) {
    dateEl.textContent = "--";
    statusEl.textContent = "--";
    firstInEl.textContent = "--";
    lastOutEl.textContent = "--";
    mainGateEl.textContent = "--";
    tableEl.innerHTML = tablePlaceholder(5, "暂无通行记录");
    return;
  }

  dateEl.textContent = data.attendance_date || "--";
  statusEl.textContent = data.attendance_status || "--";
  firstInEl.textContent = data.first_in || "--";
  lastOutEl.textContent = data.last_out || "--";
  mainGateEl.textContent = data.main_gate || "--";

  if (!Array.isArray(data.records) || !data.records.length) {
    tableEl.innerHTML = tablePlaceholder(5, "当日暂无通行记录");
    return;
  }

  tableEl.innerHTML = data.records
    .map(
      (r) => `
      <tr>
        <td>${r.time}</td>
        <td>${r.device}</td>
        <td class="muted">${r.credential}</td>
        <td><span class="tag ${r.result}">${r.result === "pass" ? "放行" : "拒绝"}</span></td>
        <td class="muted">${r.reason}</td>
      </tr>`
    )
    .join("");
}
function renderDeviceDetail() {
  const deviceRecordTable = document.getElementById("deviceRecordTable");
  const detail = state.deviceDetail;

  if (!detail?.device) {
    deviceDetailTitle.textContent = "设备详情";
    deviceDetailName.textContent = "设备不存在";
    deviceDetailStatus.textContent = "--";
    deviceDetailMode.textContent = "--";
    deviceDetailHeartbeat.textContent = "--";
    deviceDetailTodayPass.textContent = "0";
    deviceRecordTable.innerHTML = tablePlaceholder(5, "暂无记录");
    return;
  }

  const d = detail.device;
  deviceDetailTitle.textContent = `${d.id} 设备详情`;
  deviceDetailName.textContent = d.name;
  deviceDetailStatus.innerHTML = `<span class="status-pill ${d.online ? "online" : "offline"}">${d.online ? "在线" : "离线"}</span>`;
  deviceDetailMode.textContent = d.mode;
  deviceDetailHeartbeat.textContent = d.last_heartbeat || "--";
  deviceDetailTodayPass.textContent = String(detail.today_pass ?? 0);

  if (!state.deviceRecords.length) {
    deviceRecordTable.innerHTML = tablePlaceholder(5, "该设备暂无通行记录");
    return;
  }

  deviceRecordTable.innerHTML = state.deviceRecords
    .map(
      (r) => `
      <tr>
        <td>${r.time}</td>
        <td>${r.person}</td>
        <td class="muted">${r.credential}</td>
        <td><span class="tag ${r.result}">${r.result === "pass" ? "放行" : "拒绝"}</span></td>
        <td class="muted">${r.reason}</td>
      </tr>`
    )
    .join("");
}

function renderEvents() {
  const eventList = document.getElementById("eventList");
  if (!state.events.length) {
    eventList.innerHTML = '<li><span class="muted">暂无事件</span><small>--</small></li>';
    return;
  }

  eventList.innerHTML = state.events
    .slice(0, 10)
    .map(
      (e) => `
      <li>
        <span>${e.text}</span>
        <small>${e.time || e.t || "--"}</small>
      </li>`
    )
    .join("");
}

function renderStats() {
  const online = state.devices.filter((d) => d.online).length;
  const offline = Math.max(0, state.devices.length - online);
  const raw = getRawStats();
  const baseline = state.statsBaseline?.date === todayKey() ? state.statsBaseline : null;
  const pass = Math.max(0, raw.pass - (baseline?.pass || 0));
  const reject = Math.max(0, raw.reject - (baseline?.reject || 0));

  document.getElementById("onlineCount").textContent = String(online);
  document.getElementById("offlineCount").textContent = String(offline);
  document.getElementById("passCount").textContent = String(pass);
  document.getElementById("alarmCount").textContent = String(reject);
}

function bindStatsReset() {
  const resetStatsBtn = document.getElementById("resetStatsBtn");
  if (!resetStatsBtn) return;

  resetStatsBtn.addEventListener("click", () => {
    const raw = getRawStats();
    saveStatsBaseline({
      date: todayKey(),
      pass: raw.pass,
      reject: raw.reject,
    });
    renderStats();
    setBackendState("今日通行和告警计数已置零", true);
  });
}

async function openDeviceDetail(deviceId) {
  state.selectedDeviceId = deviceId;
  deviceOpenMessage.textContent = "";
  setActiveView("deviceDetail");

  try {
    const [detail, records] = await Promise.all([apiDeviceDetail(deviceId), apiDeviceRecords(deviceId)]);
    state.deviceDetail = detail;
    state.deviceRecords = records;
    renderDeviceDetail();
  } catch (err) {
    handleApiError(err, "设备详情加载失败");
    state.deviceDetail = null;
    state.deviceRecords = [];
    renderDeviceDetail();
  }
}

function bindDeviceRouting() {
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest(".device-link");
    if (!trigger) return;
    const deviceId = trigger.dataset.deviceId;
    if (!deviceId) return;
    openDeviceDetail(deviceId);
  });
}

function bindDeviceActions() {
  backToDevicesBtn.addEventListener("click", () => {
    setActiveView("devices");
  });

  deviceManualOpenBtn.addEventListener("click", async () => {
    if (!state.selectedDeviceId) {
      deviceOpenMessage.textContent = "请先选择设备";
      return;
    }

    try {
      const resp = await apiDeviceOpen(state.selectedDeviceId);
      const stamp = resp.requested_at?.split("T")[1] || formatNow().split(" ")[1];
      deviceOpenMessage.textContent = `${stamp} ${resp.message}`;
    } catch (err) {
      handleApiError(err, "开门指令失败");
      deviceOpenMessage.textContent = err.message || "开门指令失败";
    }
  });
}

function bindDeviceAdminActions() {
  if (!addDeviceBtn) return;

  addDeviceBtn.addEventListener("click", async () => {
    const deviceId = (window.prompt("设备ID（示例: GATE-05）") || "").trim().toUpperCase();
    if (!deviceId) return;

    const name = (window.prompt("设备名称（示例: 东门通道）") || "").trim();
    if (!name) return;

    const mode = (window.prompt("连接方式（Wi-Fi / Serial）", "Wi-Fi") || "").trim();
    if (!mode) return;

    const onlineText = (window.prompt("是否在线？输入 yes 或 no", "yes") || "yes").trim().toLowerCase();
    const online = !(onlineText === "no" || onlineText === "n" || onlineText === "0");

    try {
      await apiAddDevice({
        device_id: deviceId,
        name,
        mode,
        online,
        firmware: "v1.0.0",
      });
      await refreshDevices();
      setBackendState(`设备 ${deviceId} 已创建`, true);
    } catch (err) {
      handleApiError(err, "新增设备失败");
      window.alert(err.message || "新增设备失败");
    }
  });
}


function bindUserAdminActions() {
  const addUserBtn = document.getElementById("addUserBtn");
  if (!addUserBtn) return;

  const userModal = document.getElementById("userModal");
  const userModalForm = document.getElementById("userModalForm");
  const closeUserModalBtn = document.getElementById("closeUserModalBtn");
  const cancelUserModalBtn = document.getElementById("cancelUserModalBtn");
  const userModalOverlay = document.getElementById("userModalOverlay");

  const mUserId = document.getElementById("modalUserId");
  const mUsername = document.getElementById("modalUsername");
  const mDisplayName = document.getElementById("modalDisplayName");
  const mRole = document.getElementById("modalRole");
  const mActive = document.getElementById("modalActive");
  const mPassword = document.getElementById("modalPassword");
  const mTitle = document.getElementById("userModalTitle");

  function openModal(isEdit, user = null) {
    userModalForm.reset();
    if (isEdit && user) {
      mTitle.textContent = "编辑用户";
      mUserId.value = user.id;
      mUsername.value = user.username;
      mUsername.disabled = true;
      mDisplayName.value = user.display_name;
      mRole.value = user.role;
      mActive.value = user.is_active ? "true" : "false";
      mPassword.required = false;
      mPassword.placeholder = "至少8位 (不填则不修改)";
    } else {
      mTitle.textContent = "新建用户";
      mUserId.value = "";
      mUsername.disabled = false;
      mPassword.required = true;
      mPassword.placeholder = "至少8位";
      mRole.value = "personal";
      mActive.value = "true";
    }
    userModal.classList.remove("hidden");
  }

  function closeModal() {
    userModal.classList.add("hidden");
  }

  closeUserModalBtn.addEventListener("click", closeModal);
  cancelUserModalBtn.addEventListener("click", closeModal);
  userModalOverlay.addEventListener("click", closeModal);

  addUserBtn.addEventListener("click", () => { console.log("addUserBtn clicked!");
    openModal(false);
  });

  document.addEventListener("click", async (event) => {
    const editBtn = event.target.closest(".edit-user-btn");
    if (editBtn) {
      const userId = parseInt(editBtn.dataset.userId, 10);
      const user = state.users.find(u => u.id === userId);
      if (user) openModal(true, user);
      return;
    }

    const deleteBtn = event.target.closest(".delete-user-btn");
    if (deleteBtn) {
      const userId = parseInt(deleteBtn.dataset.userId, 10);
      const user = state.users.find(u => u.id === userId);
      if (!user) return;

      if (window.confirm(`确定要删除用户 ${user.username} (${user.display_name}) 吗？此操作不可逆！`)) {
        try {
          await apiDeleteUser(userId);
          await refreshUsers();
          setBackendState(`用户 ${user.username} 已删除`, true);
        } catch (err) {
          handleApiError(err, "删除用户失败");
          window.alert(err.message || "删除用户失败");
        }
      }
    }
  });

  userModalForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const userId = mUserId.value;
    const isEdit = !!userId;
    const pwd = mPassword.value.trim();

    if (pwd && pwd.length < 8) {
      window.alert("密码长度至少8位");
      return;
    }

    try {
      if (isEdit) {
        const payload = {};
        const oldUser = state.users.find(u => u.id === parseInt(userId, 10));
        if (!oldUser) return;
        if (mDisplayName.value.trim() !== oldUser.display_name) payload.display_name = mDisplayName.value.trim();
        if (mRole.value !== oldUser.role) payload.role = mRole.value;
        const isActive = mActive.value === "true";
        if (isActive !== oldUser.is_active) payload.is_active = isActive;
        if (pwd) payload.password = pwd;

        if (Object.keys(payload).length > 0) {
          await apiUpdateUser(userId, payload);
          setBackendState(`用户 ${oldUser.username} 更新成功`, true);
        }
      } else {
        const payload = {
          username: mUsername.value.trim().toLowerCase(),
          display_name: mDisplayName.value.trim(),
          role: mRole.value,
          is_active: mActive.value === "true",
          password: pwd
        };
        const created = await apiCreateUser(payload);
        setBackendState(`用户 ${created.username} 创建成功`, true);
      }
      
      closeModal();
      await refreshUsers();
    } catch (err) {
      handleApiError(err, isEdit ? "更新用户失败" : "新建用户失败");
      window.alert(err.message || (isEdit ? "更新用户失败" : "新建用户失败"));
    }
  });
}
function bindAttendanceActions() {
  document.addEventListener("click", async (event) => {
    const btn = event.target.closest(".attendance-edit-btn");
    if (!btn) return;

    const personName = btn.dataset.personName;
    const attendanceDate = btn.dataset.attendanceDate;
    const currentStatus = btn.dataset.currentStatus || "正常";

    const statusInput = (window.prompt(`修改 ${personName} 的考勤状态\n可选：${ATTENDANCE_STATUS_OPTIONS.join("/")}`, currentStatus) || "").trim();
    if (!statusInput) return;

    if (!ATTENDANCE_STATUS_OPTIONS.includes(statusInput)) {
      window.alert(`状态无效，请使用：${ATTENDANCE_STATUS_OPTIONS.join("/")}`);
      return;
    }

    const note = (window.prompt("备注（可留空）", "") || "").trim();

    try {
      await apiUpdateAttendanceStatus({
        person_name: personName,
        status: statusInput,
        attendance_date: attendanceDate,
        note,
      });
      await refreshAttendance();
      setBackendState(`${personName} 状态已更新为 ${statusInput}`, true);
    } catch (err) {
      handleApiError(err, "考勤状态更新失败");
      window.alert(err.message || "考勤状态更新失败");
    }
  });
}

function bindViewSwitch() {
  navItems.forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      const view = btn.dataset.view;
      setActiveView(view);

      try {
        if (view === "devices") {
          await refreshDevices();
        } else if (view === "records") {
          await refreshRecords(state.currentRecordFilter);
        } else if (view === "attendance") {
          await refreshAttendance();
        } else if (view === "myActivity") {
          await refreshMyActivity();
        }
      } catch (err) {
        handleApiError(err, "页面刷新失败");
      }
    });
  });
}

function bindFilterChips() {
  const chips = Array.from(document.querySelectorAll(".chip"));
  const map = { 全部: "all", 放行: "pass", 拒绝: "reject" };

  chips.forEach((chip) => {
    chip.addEventListener("click", async () => {
      chips.forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");

      const filter = map[chip.textContent.trim()] || "all";
      try {
        await refreshRecords(filter);
      } catch (err) {
        handleApiError(err, "记录拉取失败");
      }
    });
  });
}

function bindButtonFeedback() {
  document.addEventListener("pointerover", (event) => {
    const btn = event.target.closest("button");
    if (!btn) return;

    btn.classList.add("touching");
    clearTimeout(btn._touchTimer);
    btn._touchTimer = setTimeout(() => {
      btn.classList.remove("touching");
    }, 220);
  });

  document.addEventListener("pointerout", (event) => {
    const btn = event.target.closest("button");
    if (!btn) return;

    const related = event.relatedTarget;
    if (related && btn.contains(related)) return;

    btn.classList.remove("touching");
    clearTimeout(btn._touchTimer);
  });
}

function tickClock() {
  clock.textContent = formatNow();
}

async function restoreSessionOrShowIntro() {
  const session = loadSession();
  if (!session || !session.access_token) {
    showIntro();
    return;
  }

  try {
    const user = await apiMe(session.access_token);
    applyUser(user, session.access_token, true);
  } catch {
    clearSession();
    showIntro();
  }
}

async function init() {
  state.statsBaseline = loadStatsBaseline();

  tickClock();
  setInterval(tickClock, 1000);

  bindViewSwitch();
  bindFilterChips();
  bindButtonFeedback();
  bindPasswordToggles();
  bindRoleTabs();
  bindEntry();
  bindEntryAnimation();
  bindAuth();
  bindDeviceRouting();
  bindDeviceActions();
  bindDeviceAdminActions();
  bindUserAdminActions();
  bindAttendanceActions();
  bindStatsReset();

  renderDoors();
  renderUsers();
  renderRecords();
  renderAttendance();
  renderMyActivity();
  renderEvents();
  renderStats();

  await restoreSessionOrShowIntro();
}

init();
