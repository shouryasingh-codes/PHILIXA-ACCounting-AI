// =============================================================================
// PHILIXA 6.0: Frontend Application & State Machine
// Multi-Tenant SaaS Auth, CSRF Protection, Workspace Switching & RBAC
// =============================================================================

// --- Authentication & Session State ---
const authState = {
  status: "loading", // "loading" | "unauthenticated" | "unverified" | "authenticated"
  user: null, // { id, email, is_verified, is_active }
  activeOrganization: null, // { id, name, slug, workspace_type, plan }
  role: null, // "owner" | "admin" | "member"
  sessionId: null, // string
  memberships: [], // Array<{ organization_id, organization_name, slug, role, status, joined_at }>
  csrfToken: null, // string
  view: "loading", // "login" | "register" | "verify-pending" | "forgot-password" | "reset-password" | "invite-accept" | "dashboard"
};

// --- Copilot Dashboard State ---
const state = {
  clients: [],
  commitments: [],
  metrics: { total_meetings: 0 },
  priorities: { tasks: [], risks: [] },
  selectedClientId: null,
  pendingConfirmationMeetingId: null,
  workspaceScope: 'team', // 'team' or 'me'
  extractedDiffs: [], // Array<{ id, type, subtype, title, dueDate, priority, clientName, sourceQuote, selected, rawItem }>
  diffFilter: 'all', // 'all' | 'commitment' | 'risk' | 'memory'
  editingDiffId: null,
  copilotTokensUsed: 1420, // Base system prompt & portfolio memory context
  copilotMaxTokens: 8192,
};

// --- DOM Elements Index ---
const els = {
  // Auth Overlays & Views
  authModal: document.querySelector("#authModal"),
  authTitle: document.querySelector("#authTitle"),
  authSubtitle: document.querySelector("#authSubtitle"),

  viewLogin: document.querySelector("#viewLogin"),
  loginForm: document.querySelector("#loginForm"),
  loginEmail: document.querySelector("#loginEmail"),
  loginPassword: document.querySelector("#loginPassword"),
  loginSubmitBtn: document.querySelector("#loginSubmitBtn"),
  demoLoginBtn: document.querySelector("#demoLoginBtn"),
  loginError: document.querySelector("#loginError"),
  linkToRegister: document.querySelector("#linkToRegister"),
  linkToForgotPassword: document.querySelector("#linkToForgotPassword"),
  linkToVerifyEmail: document.querySelector("#linkToVerifyEmail"),

  viewRegister: document.querySelector("#viewRegister"),
  registerForm: document.querySelector("#registerForm"),
  typeCompany: document.querySelector("#typeCompany"),
  typeIndividual: document.querySelector("#typeIndividual"),
  labelTypeCompany: document.querySelector("#labelTypeCompany"),
  labelTypeIndividual: document.querySelector("#labelTypeIndividual"),
  registerWorkspaceName: document.querySelector("#registerWorkspaceName"),
  registerEmail: document.querySelector("#registerEmail"),
  registerPassword: document.querySelector("#registerPassword"),
  registerSubmitBtn: document.querySelector("#registerSubmitBtn"),
  registerError: document.querySelector("#registerError"),
  linkToLoginFromRegister: document.querySelector("#linkToLoginFromRegister"),

  viewVerifyEmail: document.querySelector("#viewVerifyEmail"),
  verifyMessage: document.querySelector("#verifyMessage"),
  verifyEmailDisplay: document.querySelector("#verifyEmailDisplay"),
  verifyEmailForm: document.querySelector("#verifyEmailForm"),
  verifyTokenInput: document.querySelector("#verifyTokenInput"),
  verifyTokenSubmitBtn: document.querySelector("#verifyTokenSubmitBtn"),
  linkToLoginFromVerify: document.querySelector("#linkToLoginFromVerify"),

  viewForgotPassword: document.querySelector("#viewForgotPassword"),
  forgotPasswordMessage: document.querySelector("#forgotPasswordMessage"),
  forgotPasswordForm: document.querySelector("#forgotPasswordForm"),
  forgotPasswordEmail: document.querySelector("#forgotPasswordEmail"),
  forgotPasswordSubmitBtn: document.querySelector("#forgotPasswordSubmitBtn"),
  linkToResetWithToken: document.querySelector("#linkToResetWithToken"),
  linkToLoginFromForgot: document.querySelector("#linkToLoginFromForgot"),

  viewResetPassword: document.querySelector("#viewResetPassword"),
  resetPasswordMessage: document.querySelector("#resetPasswordMessage"),
  resetPasswordForm: document.querySelector("#resetPasswordForm"),
  resetTokenInput: document.querySelector("#resetTokenInput"),
  resetNewPassword: document.querySelector("#resetNewPassword"),
  resetConfirmPassword: document.querySelector("#resetConfirmPassword"),
  resetPasswordSubmitBtn: document.querySelector("#resetPasswordSubmitBtn"),
  linkToLoginFromReset: document.querySelector("#linkToLoginFromReset"),

  viewInviteAccept: document.querySelector("#viewInviteAccept"),
  inviteAcceptMessage: document.querySelector("#inviteAcceptMessage"),
  acceptInviteForm: document.querySelector("#acceptInviteForm"),
  inviteTokenInput: document.querySelector("#inviteTokenInput"),
  invitePasswordInput: document.querySelector("#invitePasswordInput"),
  inviteAcceptSubmitBtn: document.querySelector("#inviteAcceptSubmitBtn"),
  linkToLoginFromInvite: document.querySelector("#linkToLoginFromInvite"),

  workspaceSelect: document.querySelector("#workspaceSelect"),
  scopeSelectorWrap: document.querySelector("#scopeSelectorWrap"),
  scopeSelect: document.querySelector("#scopeSelect"),
  topbarPlanBadge: document.querySelector("#topbarPlanBadge"),
  topbarTitle: document.querySelector("#topbarTitle"),
  topbarCopilotBtn: document.querySelector("#topbarCopilotBtn"),
  manageMembersBtn: document.querySelector("#manageMembersBtn"),
  userEmailDisplay: document.querySelector("#userEmailDisplay"),
  logoutBtn: document.querySelector("#logoutBtn"),
  avatarBtn: document.querySelector("#avatarBtn"),
  avatarMenu: document.querySelector("#avatarMenu"),
  avatarDropdownContainer: document.querySelector("#avatarDropdownContainer"),

  // Workspace Members Modal
  memberModal: document.querySelector("#memberModal"),
  memberModalOrgName: document.querySelector("#memberModalOrgName"),
  closeMemberModalBtn: document.querySelector("#closeMemberModalBtn"),
  inviteSection: document.querySelector("#inviteSection"),
  inviteResultMsg: document.querySelector("#inviteResultMsg"),
  inviteMemberForm: document.querySelector("#inviteMemberForm"),
  inviteMemberEmail: document.querySelector("#inviteMemberEmail"),
  inviteMemberRole: document.querySelector("#inviteMemberRole"),
  inviteMemberSubmitBtn: document.querySelector("#inviteMemberSubmitBtn"),
  memberCountBadge: document.querySelector("#memberCountBadge"),
  memberListRows: document.querySelector("#memberListRows"),

  // Verdict Cards
  verdictCardClients: document.querySelector("#verdictCardClients"),
  verdictCardPending: document.querySelector("#verdictCardPending"),
  verdictCardMeetings: document.querySelector("#verdictCardMeetings"),
  verdictCardRisks: document.querySelector("#verdictCardRisks"),

  // Tablet Switcher Tabs
  tabletWorkbenchTabs: document.querySelector("#tabletWorkbenchTabs"),
  tabMobileIntake: document.querySelector("#tabMobileIntake"),
  tabMobileDiffs: document.querySelector("#tabMobileDiffs"),
  diffCountPillMobile: document.querySelector("#diffCountPillMobile"),

  // Dashboard Core Elements
  notePanel: document.querySelector("#notePanel"),
  diffWorkbench: document.querySelector("#diffWorkbench"),
  healthDot: document.querySelector("#healthDot"),
  healthText: document.querySelector("#healthText"),
  clientCount: document.querySelector("#clientCount"),
  pendingCount: document.querySelector("#pendingCount"),
  // UI Filters
  topClientSelect: document.querySelector("#topClientSelect"),
  viewClientProfileBtn: document.querySelector("#viewClientProfileBtn"),
  deleteSelectedClientBtn: document.querySelector("#deleteSelectedClientBtn"),
  
  // Client Profile Modal
  clientProfileModal: document.querySelector("#clientProfileModal"),
  closeClientProfileBtn: document.querySelector("#closeClientProfileBtn"),
  profileWhatsapp: document.querySelector("#profileWhatsapp"),
  profileEmail: document.querySelector("#profileEmail"),
  saveClientContactBtn: document.querySelector("#saveClientContactBtn"),
  profileContactMsg: document.querySelector("#profileContactMsg"),
  communicationFeed: document.querySelector("#communicationFeed"),
  rawNotes: document.querySelector("#rawNotes"),
  meetingDate: document.querySelector("#meetingDate"),
  knownClient: document.querySelector("#knownClient"),
  processNotes: document.querySelector("#processNotes"),
  processResult: document.querySelector("#processResult"),
  diffPillFilters: document.querySelector("#diffPillFilters"),
  diffTotalCount: document.querySelector("#diffTotalCount"),
  countAll: document.querySelector("#countAll"),
  countCommitments: document.querySelector("#countCommitments"),
  countRisks: document.querySelector("#countRisks"),
  countMemory: document.querySelector("#countMemory"),
  diffActionBar: document.querySelector("#diffActionBar"),
  diffDiscardAllBtn: document.querySelector("#diffDiscardAllBtn"),
  diffSyncSelectedBtn: document.querySelector("#diffSyncSelectedBtn"),
  diffApprovedCount: document.querySelector("#diffApprovedCount"),

  editTranscriptPanel: document.querySelector("#editTranscriptPanel"),
  editTranscriptText: document.querySelector("#editTranscriptText"),
  saveTranscriptBtn: document.querySelector("#saveTranscriptBtn"),
  confirmPanel: document.querySelector("#confirmPanel"),
  confirmClientSelect: document.querySelector("#confirmClientSelect"),
  newClientName: document.querySelector("#newClientName"),
  newClientEmail: document.querySelector("#newClientEmail"),
  newClientPhone: document.querySelector("#newClientPhone"),
  confirmClient: document.querySelector("#confirmClient"),
  loadSelectedMemory: document.querySelector("#loadSelectedMemory"),
  memoryContent: document.querySelector("#memoryContent"),
  commitmentFilter: document.querySelector("#commitmentFilter"),
  commitmentRows: document.querySelector("#commitmentRows"),
  taskList: document.querySelector("#taskList"),
  riskList: document.querySelector("#riskList"),
  
  // Team Performance
  teamPerformanceSection: document.querySelector("#teamPerformanceSection"),
  teamPerformanceBody: document.querySelector("#teamPerformanceBody"),

  // Persistent Copilot Sidecar
  copilotSidecar: document.querySelector("#copilotSidecar"),
  closeCopilotBtn: document.querySelector("#closeCopilotBtn"),
  openCopilotBtn: document.querySelector("#openCopilotBtn"),
  copilotGroundedClient: document.querySelector("#copilotGroundedClient"),
  copilotTokenText: document.querySelector("#copilotTokenText"),
  copilotTokenFill: document.querySelector("#copilotTokenFill"),
  copilotMessages: document.querySelector("#copilotMessages"),
  copilotInput: document.querySelector("#copilotInput"),
  sendCopilotBtn: document.querySelector("#sendCopilotBtn"),

  toast: document.querySelector("#toast"),
  askClientSection: document.querySelector("#askClientSection"),
  askClientInput: document.querySelector("#askClientInput"),
  askClientBtn: document.querySelector("#askClientBtn"),
  askClientResult: document.querySelector("#askClientResult"),
  themeToggleBtn: document.querySelector("#themeToggleBtn"),
  sidebarToggleBtn: document.querySelector("#sidebarToggleBtn"),
  logoToggleBtn: document.querySelector("#logoToggleBtn"),
  settingsBtn: document.querySelector("#settingsBtn"),
  settingsModal: document.querySelector("#settingsModal"),
  closeSettingsBtn: document.querySelector("#closeSettingsBtn"),
  prefOptIn: document.querySelector("#prefOptIn"),
  prefContact: document.querySelector("#prefContact"),
  prefQuietStart: document.querySelector("#prefQuietStart"),
  prefQuietEnd: document.querySelector("#prefQuietEnd"),
  saveSettingsBtn: document.querySelector("#saveSettingsBtn"),
  deleteAccountBtn: document.querySelector("#deleteAccountBtn"),
  tabTextBtn: document.querySelector("#tabTextBtn"),
  tabAudioBtn: document.querySelector("#tabAudioBtn"),
  viewText: document.querySelector("#viewText"),
  viewAudio: document.querySelector("#viewAudio"),
  audioFileInput: document.querySelector("#audioFileInput"),
  uploadFileName: document.querySelector("#uploadFileName"),
  processAudio: document.querySelector("#processAudio"),
  meetingDateAudio: document.querySelector("#meetingDateAudio"),
  audioStatusBox: document.querySelector("#audioStatusBox"),
  audioStatusText: document.querySelector("#audioStatusText"),
  audioStatusDetails: document.querySelector("#audioStatusDetails"),
  uploadBox: document.querySelector("#uploadBox"),
};

// --- Single-Flight Refresh Queue ---
let isRefreshing = false;
let refreshQueue = [];

function processRefreshQueue(error = null) {
  refreshQueue.forEach(({ resolve, reject, retryFn }) => {
    if (error) {
      reject(error);
    } else {
      retryFn().then(resolve).catch(reject);
    }
  });
  refreshQueue = [];
}

// --- CSRF Cookie Helper ---
function getCsrfToken() {
  if (authState.csrfToken) {
    return authState.csrfToken;
  }
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  if (match && match[1]) {
    return decodeURIComponent(match[1]);
  }
  return null;
}

// --- Universal Secure Fetch Wrapper ---
async function fetchWithAuth(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});

  // Attach X-CSRF-Token on mutating requests
  if (!["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) {
    const token = getCsrfToken();
    if (token && !headers.has("X-CSRF-Token")) {
      headers.set("X-CSRF-Token", token);
    }
  }

  const fetchConfig = {
    ...options,
    method,
    headers,
    credentials: "include", // Mandatory for HttpOnly session cookies
  };

  let response = await fetch(url, fetchConfig);

  const isAuthBypassUrl =
    url.includes("/auth/login") ||
    url.includes("/auth/refresh") ||
    url.includes("/auth/register") ||
    url.includes("/auth/verify-email") ||
    url.includes("/auth/forgot-password") ||
    url.includes("/auth/reset-password");

  // Handle 401 Unauthorized with Single-Flight Refresh
  if (response.status === 401 && !isAuthBypassUrl && !options._retry) {
    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        refreshQueue.push({
          resolve,
          reject,
          retryFn: () => fetchWithAuth(url, { ...options, _retry: true }),
        });
      });
    }

    isRefreshing = true;

    try {
      const refreshHeaders = new Headers({ "Content-Type": "application/json" });
      const csrf = getCsrfToken();
      if (csrf) refreshHeaders.set("X-CSRF-Token", csrf);

      const refreshRes = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "include",
        headers: refreshHeaders,
      });

      if (!refreshRes.ok) {
        throw new Error(`Refresh returned status ${refreshRes.status}`);
      }

      const refreshData = await refreshRes.json();
      if (refreshData.csrf_token) {
        authState.csrfToken = refreshData.csrf_token;
      }

      isRefreshing = false;
      processRefreshQueue(null);

      // Replay original request
      return fetchWithAuth(url, { ...options, _retry: true });
    } catch (refreshErr) {
      isRefreshing = false;
      processRefreshQueue(refreshErr);
      handleSessionExpired();
      throw new Error("Session expired. Please log in again.");
    }
  }

  return response;
}

// Expose globally for other modules (e.g. philixa-voice.js)
window.fetchWithAuth = fetchWithAuth;
window.getBusinessChatScope = () => authState.status === 'authenticated' ? {
  user_id:authState.user?.id, organization_id:authState.activeOrganization?.id, session_id:authState.sessionId
} : null;

// --- Standardized JSON API Client ---
async function api(path, options = {}) {
  const headers = options.headers ? new Headers(options.headers) : new Headers();
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetchWithAuth(path, { ...options, headers });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.message || detail;
    } catch {
      detail = response.statusText || detail;
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

// --- UI Feedback & Utilities ---
function showToast(message, isError = false) {
  if (!els.toast) return;
  els.toast.textContent = message;
  els.toast.classList.toggle("error", isError);
  els.toast.classList.add("show");
  window.setTimeout(() => els.toast.classList.remove("show"), 2800);
}
window.showToast = showToast;

function todayIso() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatShortDate(dateString) {
  if (!dateString || typeof dateString !== "string") return dateString || "Unknown";
  const match = dateString.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return dateString;
  const d = new Date(match[1], match[2] - 1, match[3]);
  if (isNaN(d)) return dateString;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

let currentAudio = null;
async function playTTS(text) {
  try {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
    const res = await fetchWithAuth("/api/v1/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      console.log("TTS not enabled or failed", res.status);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    currentAudio = new Audio(url);
    currentAudio.play();
  } catch (err) {
    console.error("TTS Error:", err);
  }
}

// =============================================================================
// AUTH STATE MACHINE & VIEW CONTROLLER
// =============================================================================

// Reveal the app after auth check — always called, even on error, to prevent black screen
function revealApp() {
  const loader = document.getElementById('initialLoader');
  if (loader) {
    loader.style.opacity = '0';
    setTimeout(() => loader.remove(), 300);
  }
}

function showAuthOverlay(viewName) {
  authState.view = viewName;
  if (!els.authModal) return;
  els.authModal.classList.remove("hidden");

  // Hide all views
  const views = [
    els.viewLogin,
    els.viewRegister,
    els.viewVerifyEmail,
    els.viewForgotPassword,
    els.viewResetPassword,
    els.viewInviteAccept,
  ];
  views.forEach((v) => {
    if (v) v.classList.add("hidden");
  });

  // Clear alerts
  document.querySelectorAll(".alert-box").forEach((el) => {
    el.classList.add("hidden");
    el.textContent = "";
  });

  if (viewName === "login") {
    els.viewLogin?.classList.remove("hidden");
    if (els.authTitle) els.authTitle.textContent = "Sign in to Philixa";
    if (els.authSubtitle) els.authSubtitle.textContent = "AI Copilot for Banking Relationship Managers";
  } else if (viewName === "register") {
    els.viewRegister?.classList.remove("hidden");
    if (els.authTitle) els.authTitle.textContent = "Create your Workspace";
    if (els.authSubtitle) els.authSubtitle.textContent = "Start intelligent relationship management today";
  } else if (viewName === "verify-email" || viewName === "verify-pending") {
    els.viewVerifyEmail?.classList.remove("hidden");
    if (els.authTitle) els.authTitle.textContent = "Verify your Email";
    if (els.authSubtitle) els.authSubtitle.textContent = "Enter your verification code or token";
  } else if (viewName === "forgot-password") {
    els.viewForgotPassword?.classList.remove("hidden");
    if (els.authTitle) els.authTitle.textContent = "Forgot Password";
    if (els.authSubtitle) els.authSubtitle.textContent = "We will send instructions to reset your password";
  } else if (viewName === "reset-password") {
    els.viewResetPassword?.classList.remove("hidden");
    if (els.authTitle) els.authTitle.textContent = "Set New Password";
    if (els.authSubtitle) els.authSubtitle.textContent = "Choose a strong password for your account";
  } else if (viewName === "invite-accept") {
    els.viewInviteAccept?.classList.remove("hidden");
    if (els.authTitle) els.authTitle.textContent = "Accept Workspace Invitation";
    if (els.authSubtitle) els.authSubtitle.textContent = "Join your team in Philixa";
  }
}

function hideAuthOverlay() {
  if (!els.authModal) return;
  els.authModal.classList.add("hidden");
}

function handleSessionExpired() {
  localStorage.setItem("p6_logged_in", "false");
  document.documentElement.classList.add("not-logged-in");
  authState.status = "unauthenticated";
  authState.user = null;
  authState.activeOrganization = null;
  authState.role = null;
  
  if (!["invite-accept", "verify-email", "verify-pending", "reset-password"].includes(authState.view)) {
    showAuthOverlay("login");
    showToast("Session expired. Please log in again.", true);
  }
}

// --- Session Bootstrap ---
async function bootstrapSession() {
  try {
    const data = await api("/api/v1/auth/me");
    
    if (!data.user.is_verified) {
      localStorage.setItem("p6_logged_in", "false");
      document.documentElement.classList.add("not-logged-in");
      authState.status = "unverified";
      authState.user = data.user;
      if (els.verifyEmailDisplay) {
        els.verifyEmailDisplay.textContent = data.user.email;
      }
      showAuthOverlay("verify-pending");
      return;
    }

    // Auth Success
    localStorage.setItem("p6_logged_in", "true");
    document.documentElement.classList.remove("not-logged-in");
    
    authState.status = "authenticated";
    authState.user = data.user;
    authState.activeOrganization = data.active_organization;
    authState.role = data.role;
    authState.sessionId = data.session_id;
    authState.memberships = data.memberships || [];

    hideAuthOverlay();
    renderWorkspaceNav();
    applyRolePermissions();
    window.dispatchEvent(new Event('business-auth-ready'));
    await refreshAll();

    if (state.selectedClientId) {
      await loadMemory(state.selectedClientId);
    }
  } catch (err) {
    console.log("[Auth] Session not active or expired:", err.message);
    
    // Auth Failed
    localStorage.setItem("p6_logged_in", "false");
    document.documentElement.classList.add("not-logged-in");
    
    authState.status = "unauthenticated";
    
    // Do not override deep-link auth views (like invite-accept, reset-password) with login
    if (["invite-accept", "verify-email", "verify-pending", "reset-password"].includes(authState.view)) {
      showAuthOverlay(authState.view);
    } else {
      showAuthOverlay("login");
    }
  }
}

// --- Render Nav & RBAC ---
function renderWorkspaceNav() {
  if (!els.workspaceSelect) return;

  const currentOrgId = authState.activeOrganization?.id;
  const memberships = authState.memberships || [];

  if (memberships.length === 0 && authState.activeOrganization) {
    els.workspaceSelect.innerHTML = `<option value="${authState.activeOrganization.id}" selected>${escapeHtml(authState.activeOrganization.name)}</option>`;
  } else {
    els.workspaceSelect.innerHTML = memberships
      .map(
        (m) =>
          `<option value="${m.organization_id}" ${m.organization_id === currentOrgId ? "selected" : ""}>${escapeHtml(m.organization_name || m.slug)} (${m.role})</option>`
      )
      .join("");
  }

  if (els.topbarPlanBadge && authState.activeOrganization) {
    const plan = authState.activeOrganization.plan || "free";
    // Show subtle plan badge — only plan name, no workspace type clutter
    els.topbarPlanBadge.textContent = plan.charAt(0).toUpperCase() + plan.slice(1).toLowerCase();
  }

  if (authState.user) {
    const email = authState.user.email || "";
    const rawName = authState.user.name || authState.user.display_name || email.split("@")[0].replace(/[_.-]/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    const displayName = rawName;
    // Show name (not email) in dropdown header
    const userNameEl = document.getElementById("userNameDisplay");
    if (userNameEl) userNameEl.textContent = displayName;
    // Show full email only inside avatar dropdown (privacy-safe)
    if (els.userEmailDisplay) els.userEmailDisplay.textContent = email;
    // Avatar button shows up-to-2-letter initials
    if (els.avatarBtn) {
      const initials = displayName.split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase() || email.charAt(0).toUpperCase();
      els.avatarBtn.textContent = initials;
    }
  }
}

function applyRolePermissions() {
  const role = (authState.role || "member").toLowerCase();
  const isOwner = role === "owner";
  const isAdmin = role === "admin" || isOwner;

  // Manage members button: visible only to owner and admin
  if (els.manageMembersBtn) {
    els.manageMembersBtn.style.display = isAdmin ? "" : "none";
  }

  // Scope toggle: visible only to owner and admin
  if (els.scopeSelectorWrap) {
    els.scopeSelectorWrap.style.display = isAdmin ? "flex" : "none";
  }

  // Generic data-min-role and data-rbac DOM gating
  document.querySelectorAll("[data-rbac], [data-min-role]").forEach((el) => {
    const required = (el.dataset.minRole || el.dataset.rbac || "").toLowerCase();
    if (required === "owner" && !isOwner) {
      el.classList.add("hidden");
      el.style.display = "none";
    } else if ((required === "admin" || required === "admin-only") && !isAdmin) {
      el.classList.add("hidden");
      el.style.display = "none";
    } else {
      el.classList.remove("hidden");
      el.style.display = "";
    }
  });
}

// =============================================================================
// AUTHENTICATION FORM HANDLERS
// =============================================================================

async function handleLogin(e) {
  e.preventDefault();
  if (els.loginError) els.loginError.classList.add("hidden");

  const email = els.loginEmail.value.trim();
  const password = els.loginPassword.value;

  if (!email || !password) {
    showAuthError(els.loginError, "Email and password are required.");
    return;
  }

  try {
    els.loginSubmitBtn.disabled = true;
    els.loginSubmitBtn.textContent = "Signing In...";

    const res = await api("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });

    if (res.csrf_token) {
      authState.csrfToken = res.csrf_token;
    }

    await bootstrapSession();
    showToast("Signed in successfully!");
  } catch (err) {
    showAuthError(els.loginError, err.message);
  } finally {
    els.loginSubmitBtn.disabled = false;
    els.loginSubmitBtn.textContent = "Sign In";
  }
}

async function handleDemoLogin(e) {
  e.preventDefault();
  if (els.loginError) els.loginError.classList.add("hidden");
  
  if (els.demoLoginBtn) {
    els.demoLoginBtn.disabled = true;
    els.demoLoginBtn.textContent = "Provisioning Demo Workspace...";
  }

  try {
    const res = await api("/api/v1/auth/demo-login", {
      method: "POST"
    });
    // Set CSRF token
    if (res.csrf_token) {
      localStorage.setItem("csrf_token", res.csrf_token);
    }
    await bootstrapSession(); // Reload state with new session
  } catch (err) {
    showAuthError(els.loginError, err.message);
  } finally {
    if (els.demoLoginBtn) {
      els.demoLoginBtn.disabled = false;
      els.demoLoginBtn.textContent = "Try Demo (For Recruiters/Guests)";
    }
  }
}

async function handleRegister(e) {
  e.preventDefault();
  if (els.registerError) els.registerError.classList.add("hidden");

  const workspaceType = els.typeIndividual?.checked ? "individual" : "company";
  const workspaceName = els.registerWorkspaceName.value.trim();
  const email = els.registerEmail.value.trim();
  const password = els.registerPassword.value;

  if (!workspaceName || !email || !password) {
    showAuthError(els.registerError, "All fields are required.");
    return;
  }

  try {
    els.registerSubmitBtn.disabled = true;
    els.registerSubmitBtn.textContent = "Creating Account...";

    await api("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        workspace_name: workspaceName,
        workspace_type: workspaceType,
      }),
    });

    if (els.verifyEmailDisplay) {
      els.verifyEmailDisplay.textContent = email;
    }
    showAuthOverlay("verify-pending");
    showToast("Workspace created! Please verify your email.");
  } catch (err) {
    showAuthError(els.registerError, err.message);
  } finally {
    els.registerSubmitBtn.disabled = false;
    els.registerSubmitBtn.textContent = "Create Account & Workspace";
  }
}

async function handleVerifyEmail(e) {
  e.preventDefault();
  const token = els.verifyTokenInput.value.trim();
  if (!token) return;

  try {
    els.verifyTokenSubmitBtn.disabled = true;
    els.verifyTokenSubmitBtn.textContent = "Verifying...";

    await api(`/api/v1/auth/verify-email?token=${encodeURIComponent(token)}`, {
      method: "POST",
    });

    showToast("Email verified successfully! You can now log in.");
    showAuthOverlay("login");
  } catch (err) {
    showAuthError(els.verifyMessage, err.message);
  } finally {
    els.verifyTokenSubmitBtn.disabled = false;
    els.verifyTokenSubmitBtn.textContent = "Verify Account";
  }
}

async function handleForgotPassword(e) {
  e.preventDefault();
  const email = els.forgotPasswordEmail.value.trim();
  if (!email) return;

  try {
    els.forgotPasswordSubmitBtn.disabled = true;
    els.forgotPasswordSubmitBtn.textContent = "Sending...";

    await api("/api/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    });

    showAuthOverlay("reset-password");
    if (document.querySelector("#resetEmail")) {
      document.querySelector("#resetEmail").value = email;
    }
    showAuthSuccess(
      document.querySelector("#resetPasswordMessage"),
      "If that email exists, a token was sent. Please enter it below."
    );
  } catch (err) {
    showAuthError(els.forgotPasswordMessage, err.message);
  } finally {
    els.forgotPasswordSubmitBtn.disabled = false;
    els.forgotPasswordSubmitBtn.textContent = "Send Reset Token";
  }
}

async function handleResetPassword(e) {
  e.preventDefault();
  const token = els.resetTokenInput.value.trim();
  const newPassword = els.resetNewPassword.value;
  const confirmPassword = els.resetConfirmPassword.value;

  if (newPassword !== confirmPassword) {
    showAuthError(els.resetPasswordMessage, "Passwords do not match.");
    return;
  }

  try {
    els.resetPasswordSubmitBtn.disabled = true;
    els.resetPasswordSubmitBtn.textContent = "Updating...";

    await api("/api/v1/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password: newPassword }),
    });

    showToast("Password reset successfully. Please log in.");
    showAuthOverlay("login");
  } catch (err) {
    showAuthError(els.resetPasswordMessage, err.message);
  } finally {
    els.resetPasswordSubmitBtn.disabled = false;
    els.resetPasswordSubmitBtn.textContent = "Update Password";
  }
}

async function handleAcceptInvite(e) {
  e.preventDefault();
  const token = els.inviteTokenInput.value.trim();
  const password = els.invitePasswordInput ? els.invitePasswordInput.value.trim() : "";
  if (!token) return;

  try {
    els.inviteAcceptSubmitBtn.disabled = true;
    els.inviteAcceptSubmitBtn.textContent = "Joining...";

    await api(`/api/v1/workspaces/invite/accept`, {
      method: "POST",
      body: JSON.stringify({ token, password }),
    });

    showToast("Joined workspace successfully!");
    await bootstrapSession();
  } catch (err) {
    if (err.message.includes("already exists")) {
        showAuthError(els.inviteAcceptMessage, err.message + " Use the 'Sign in with different account' link below.");
    } else {
        showAuthError(els.inviteAcceptMessage, err.message);
    }
  } finally {
    els.inviteAcceptSubmitBtn.disabled = false;
    els.inviteAcceptSubmitBtn.textContent = "Join Workspace";
  }
}

async function handleLogout() {
  try {
    await api("/api/v1/auth/logout", { method: "POST" });
  } catch (err) {
    console.warn("Logout request failed:", err);
  }
  localStorage.setItem("p6_logged_in", "false");
  document.documentElement.classList.add("not-logged-in");
  authState.status = "unauthenticated";
  authState.user = null;
  authState.activeOrganization = null;
  authState.role = null;
  authState.memberships = [];
  state.clients = [];
  state.commitments = [];
  showAuthOverlay("login");
  showToast("Logged out successfully.");
}

function showAuthError(element, message) {
  if (!element) return;
  element.className = "alert-box error";
  element.textContent = `⚠️ ${message}`;
  element.classList.remove("hidden");
}

function showAuthSuccess(element, message) {
  if (!element) return;
  element.className = "alert-box success";
  element.textContent = `✅ ${message}`;
  element.classList.remove("hidden");
}

// =============================================================================
// WORKSPACE SWITCHING & MEMBER MANAGEMENT
// =============================================================================

async function handleSwitchWorkspace(orgId) {
  if (!orgId || orgId === authState.activeOrganization?.id) return;

  try {
    showToast("Switching workspace...");
    const res = await api("/api/v1/workspaces/switch", {
      method: "POST",
      body: JSON.stringify({ organization_id: orgId }),
    });

    if (res.csrf_token) {
      authState.csrfToken = res.csrf_token;
    }

    state.clients = [];
    state.commitments = [];
    state.selectedClientId = null;
    state.pendingConfirmationMeetingId = null;

    await bootstrapSession();
    showToast(`Switched workspace to ${res.active_organization.name}`);
  } catch (err) {
    showToast(err.message, true);
    renderWorkspaceNav();
  }
}

function openMemberModal() {
  if (!els.memberModal) return;
  els.memberModal.classList.remove("hidden");
  if (els.memberModalOrgName && authState.activeOrganization) {
    els.memberModalOrgName.textContent = authState.activeOrganization.name;
  }
  loadWorkspaceMembers();
}

function closeMemberModal() {
  if (!els.memberModal) return;
  els.memberModal.classList.add("hidden");
}

async function loadWorkspaceMembers() {
  if (!els.memberListRows) return;
  els.memberListRows.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:15px;"><span class="muted">Loading members...</span></td></tr>`;

  try {
    const payload = await api("/api/v1/workspaces/members");
    const members = Array.isArray(payload) ? payload : (payload.members || []);

    if (els.memberCountBadge) {
      els.memberCountBadge.textContent = members.length;
    }

    if (members.length === 0) {
      els.memberListRows.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center; padding:15px;">No members found.</td></tr>`;
      return;
    }

    const isOwner = authState.role === "owner";
    const currentUserId = authState.user?.id;

    els.memberListRows.innerHTML = members
      .map((m) => {
        const isSelf = m.user_id === currentUserId;
        const joinedDate = m.joined_at ? formatShortDate(m.joined_at) : "N/A";
        
        let roleCell = `<span class="role-badge role-${m.role.toLowerCase()}">${escapeHtml(m.role)}</span>`;
        if (isOwner && !isSelf) {
          roleCell = `
            <select class="member-role-select" data-user-id="${m.user_id}">
              <option value="member" ${m.role === "member" ? "selected" : ""}>Member</option>
              <option value="admin" ${m.role === "admin" ? "selected" : ""}>Admin</option>
              <option value="owner" ${m.role === "owner" ? "selected" : ""}>Owner</option>
            </select>
          `;
        }

        let actionCell = `<span class="muted">—</span>`;
        if ((isOwner || authState.role === "admin") && !isSelf && m.role !== "owner") {
          actionCell = `<button class="btn-remove-member" data-user-id="${m.user_id}" data-email="${escapeHtml(m.email)}">Remove</button>`;
        }

        return `
          <tr>
            <td>
              <strong>${escapeHtml(m.email)}</strong>
              ${isSelf ? '<span class="muted" style="font-size:11px;"> (You)</span>' : ""}
            </td>
            <td>${roleCell}</td>
            <td><span class="status-pill done">${escapeHtml(m.status || "active")}</span></td>
            <td>${escapeHtml(joinedDate)}</td>
            <td>${actionCell}</td>
          </tr>
        `;
      })
      .join("");

    // Bind role change listeners
    els.memberListRows.querySelectorAll(".member-role-select").forEach((select) => {
      select.addEventListener("change", async (e) => {
        const userId = e.target.dataset.userId;
        const newRole = e.target.value;
        await handleUpdateMemberRole(userId, newRole);
      });
    });

    // Bind remove member listeners
    els.memberListRows.querySelectorAll(".btn-remove-member").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const userId = e.target.dataset.userId;
        const email = e.target.dataset.email;
        await handleRemoveMember(userId, email);
      });
    });
  } catch (err) {
    els.memberListRows.innerHTML = `<tr><td colspan="5" class="error" style="color:var(--danger); padding:15px;">Failed to load members: ${escapeHtml(err.message)}</td></tr>`;
  }
}

async function handleInviteMember(e) {
  e.preventDefault();
  const email = els.inviteMemberEmail.value.trim();
  const role = els.inviteMemberRole.value;

  if (!email) return;

  try {
    els.inviteMemberSubmitBtn.disabled = true;
    els.inviteMemberSubmitBtn.textContent = "Inviting...";

    await api("/api/v1/workspaces/invite", {
      method: "POST",
      body: JSON.stringify({ email, role }),
    });

    showAuthSuccess(els.inviteResultMsg, `Invitation dispatched to ${email}!`);
    els.inviteMemberEmail.value = "";
    await loadWorkspaceMembers();
  } catch (err) {
    showAuthError(els.inviteResultMsg, err.message);
  } finally {
    els.inviteMemberSubmitBtn.disabled = false;
    els.inviteMemberSubmitBtn.textContent = "Send Invite";
  }
}

async function handleUpdateMemberRole(userId, newRole) {
  try {
    await api(`/api/v1/workspaces/members/${userId}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role: newRole }),
    });
    showToast(`Member role updated to ${newRole}.`);
    await loadWorkspaceMembers();
  } catch (err) {
    showToast(err.message, true);
    await loadWorkspaceMembers();
  }
}

async function handleRemoveMember(userId, email) {
  const confirmed = window.confirm(`Are you sure you want to remove ${email} from this workspace?`);
  if (!confirmed) return;

  try {
    await api(`/api/v1/workspaces/members/${userId}`, {
      method: "DELETE",
    });
    showToast(`Removed ${email} from workspace.`);
    await loadWorkspaceMembers();
  } catch (err) {
    showToast(err.message, true);
  }
}

// =============================================================================
// COPILOT CORE DASHBOARD FUNCTIONS
// =============================================================================

async function checkHealth() {
  try {
    const payload = await fetch("/health").then((res) => res.json());
    if (els.healthDot) els.healthDot.className = "status-dot ok";
    if (els.healthText) els.healthText.textContent = `API ${payload.status} - DB ${payload.database}`;
  } catch {
    if (els.healthDot) els.healthDot.className = "status-dot error";
    if (els.healthText) els.healthText.textContent = "API offline";
  }
}

function clientNameById(clientId) {
  const match = state.clients.find((client) => client.id === Number(clientId));
  if (!match) return `Client #${clientId}`;
  let displayName = match.name;
  const isAdmin = authState.role === "owner" || authState.role === "admin";
  if (isAdmin && state.workspaceScope === "team" && match.owner_email) {
    displayName += ` (${match.owner_email})`;
  }
  return displayName;
}

function updateMetrics() {
  if (els.clientCount) els.clientCount.textContent = state.clients.length;
  if (els.pendingCount) {
    els.pendingCount.textContent = state.commitments.filter((item) => item.status === "pending").length;
  }
  // Use real meeting count from backend metrics API
  const meetingsLogged = document.getElementById('meetingsLoggedCount');
  if (meetingsLogged) {
    meetingsLogged.textContent = state.metrics.total_meetings || 0;
  }
  if (els.topClientSelect) els.topClientSelect.value = state.selectedClientId || "";
}

function renderClientOptions() {
  const isAdmin = authState.role === "owner" || authState.role === "admin";
  const clientOptions = state.clients
    .map((client) => {
      // Show only client name — never expose email in dropdown labels (privacy)
      let displayName = escapeHtml(client.name);
      // For admins in team scope, show owner initial only, not full email
      if (isAdmin && state.workspaceScope === "team" && client.owner_email) {
        const ownerInitial = client.owner_email.charAt(0).toUpperCase();
        displayName += ` · ${ownerInitial}`;
      }
      return `<option value="${client.id}">${displayName}</option>`;
    })
    .join("");
  if (els.knownClient) els.knownClient.innerHTML = `<option value="">Auto identify client</option>${clientOptions}`;
  if (els.confirmClientSelect) els.confirmClientSelect.innerHTML = `<option value="">Select existing client</option>${clientOptions}`;
  if (els.topClientSelect) {
    els.topClientSelect.innerHTML = `<option value="">@client (All)</option>${clientOptions}`;
    els.topClientSelect.value = state.selectedClientId || "";
  }
  if (els.deleteSelectedClientBtn) {
    const show = state.selectedClientId ? "flex" : "none";
    els.deleteSelectedClientBtn.style.display = show;
    if (els.viewClientProfileBtn) {
      els.viewClientProfileBtn.style.display = show;
    }
  }
}

function renderClients() {
  renderClientOptions();
  updateMetrics();
}

function renderCommitments() {
  if (!els.commitmentRows) return;
  if (!state.commitments.length) {
    els.commitmentRows.innerHTML = `<tr><td colspan="6"><div class="empty-state" style="padding:20px; background:transparent;">No commitments loaded.</div></td></tr>`;
    updateMetrics();
    return;
  }
  els.commitmentRows.innerHTML = state.commitments
    .map((item) => {
      const nextStatus = item.status === "pending" ? "completed" : "pending";
      const label = item.status === "pending" ? "Complete" : "Reopen";
      const pillClass = item.status === "completed" ? "done" : "";
      return `
        <tr>
          <td>${escapeHtml(clientNameById(item.client_id))}</td>
          <td>
            <div class="commitment-title">${escapeHtml(item.description)}</div>
            <div class="client-meta">Owner: ${escapeHtml(item.owner || "RM")} - Confidence: ${Math.round((item.extraction_confidence || 0) * 100)}%</div>
          </td>
          <td>${escapeHtml(formatShortDate(item.due_date || item.due_date_text))}</td>
          <td><span class="status-pill urgency-${escapeHtml(item.urgency_level || "medium")}">${escapeHtml(item.urgency_level || "medium")}</span></td>
          <td><span class="status-pill ${pillClass}">${escapeHtml(item.status)}</span></td>
          <td><button class="link-button" type="button" data-commitment-id="${item.id}" data-next-status="${nextStatus}">${label}</button></td>
        </tr>
      `;
    })
    .join("");
  updateMetrics();
}

function renderProcessResult(payload) {
  if (!els.processResult) return;
  const created = payload.commitments_created || [];
  const updated = payload.commitments_updated || [];
  const pending = payload.pending_commitments || [];
  const risks = payload.warnings || [];
  const summary = payload.meeting_summary || "";
  const clientName = clientNameById(payload.client_id) || "Grounded Client";

  state.extractedDiffs = [];
  let counter = 1;

  created.forEach((item) => {
    state.extractedDiffs.push({
      id: `diff_${counter++}`,
      type: "commitment",
      subtype: "New Commitment",
      title: typeof item === "string" ? item : (item.description || item.title || "Commitment"),
      dueDate: typeof item === "object" ? (item.due_date || item.due_date_text || "") : "",
      priority: typeof item === "object" ? (item.urgency_level || item.priority || "Medium") : "Medium",
      clientName: clientName,
      sourceQuote: typeof item === "object" ? (item.source_quote || item.verbatim_quote || "") : "",
      selected: true,
      rawItem: item,
    });
  });

  updated.forEach((item) => {
    state.extractedDiffs.push({
      id: `diff_${counter++}`,
      type: "commitment",
      subtype: "Updated Commitment",
      title: typeof item === "string" ? item : (item.description || item.title || "Commitment update"),
      dueDate: typeof item === "object" ? (item.due_date || item.due_date_text || "") : "",
      priority: typeof item === "object" ? (item.urgency_level || item.priority || "Medium") : "Medium",
      clientName: clientName,
      sourceQuote: typeof item === "object" ? (item.source_quote || item.verbatim_quote || "") : "",
      selected: true,
      rawItem: item,
    });
  });

  pending.forEach((item) => {
    // Prevent duplicate: don't show pending commitments that were just created or updated in this same meeting
    const isAlreadyCreated = created.some(c => (c.id && c.id === item.id) || c.description === item.description);
    const isAlreadyUpdated = updated.some(u => (u.id && u.id === item.id) || u.description === item.description);
    if (isAlreadyCreated || isAlreadyUpdated) return;

    state.extractedDiffs.push({
      id: `diff_${counter++}`,
      type: "commitment",
      subtype: "Pending Commitment",
      title: typeof item === "string" ? item : (item.description || item.title || "Pending Commitment"),
      dueDate: typeof item === "object" ? (item.due_date || item.due_date_text || "") : "",
      priority: typeof item === "object" ? (item.urgency_level || item.priority || "Medium") : "Medium",
      clientName: clientName,
      sourceQuote: typeof item === "object" ? (item.source_quote || item.verbatim_quote || "") : "",
      selected: true,
      rawItem: item,
    });
  });

  risks.forEach((item) => {
    state.extractedDiffs.push({
      id: `diff_${counter++}`,
      type: "risk",
      subtype: "Risk Signal",
      title: typeof item === "string" ? item : (item.description || item.warning || "Identified risk factor"),
      dueDate: "",
      priority: "High",
      clientName: clientName,
      sourceQuote: typeof item === "object" ? (item.source_quote || "") : "",
      selected: true,
      rawItem: item,
    });
  });

  if (summary) {
    state.extractedDiffs.push({
      id: `diff_${counter++}`,
      type: "memory",
      subtype: "Memory Brief",
      title: summary,
      dueDate: "",
      priority: "Low",
      clientName: clientName,
      sourceQuote: "",
      selected: true,
      rawItem: { summary },
    });
  }

  state.diffFilter = "all";
  state.editingDiffId = null;
  renderDiffStream(true);

  // Auto-switch to Extracted Diffs tab on tablet/mobile screens
  if (window.innerWidth < 1024 && state.extractedDiffs.length > 0) {
    els.tabMobileDiffs?.click();
  }

  if (payload.requires_client_confirmation) {
    state.pendingConfirmationMeetingId = payload.meeting_id;
    if (els.confirmPanel) els.confirmPanel.classList.remove("hidden");
    const suggestedName = payload.extraction?.client_identification?.suggested_client_name || "";
    if (els.newClientName) els.newClientName.value = suggestedName;
    const suggestedEmail = payload.extraction?.client_identification?.suggested_client_email || "";
    if (els.newClientEmail) els.newClientEmail.value = suggestedEmail;
    const suggestedPhone = payload.extraction?.client_identification?.suggested_client_whatsapp_phone || "";
    if (els.newClientPhone) els.newClientPhone.value = suggestedPhone;
  } else {
    state.pendingConfirmationMeetingId = null;
    if (els.confirmPanel) els.confirmPanel.classList.add("hidden");
    state.selectedClientId = payload.client_id;
  }
}

function renderDiffStream(shouldFocusFirst = false) {
  if (!els.processResult) return;

  const total = state.extractedDiffs.length;
  const countCommitments = state.extractedDiffs.filter((d) => d.type === "commitment").length;
  const countRisks = state.extractedDiffs.filter((d) => d.type === "risk").length;
  const countMemory = state.extractedDiffs.filter((d) => d.type === "memory").length;
  const approvedCount = state.extractedDiffs.filter((d) => d.selected).length;

  // Update count indicators
  if (els.diffTotalCount) els.diffTotalCount.textContent = total;
  if (els.diffCountPillMobile) els.diffCountPillMobile.textContent = total;
  if (els.countAll) els.countAll.textContent = total;
  if (els.countCommitments) els.countCommitments.textContent = countCommitments;
  if (els.countRisks) els.countRisks.textContent = countRisks;
  if (els.countMemory) els.countMemory.textContent = countMemory;
  if (els.diffApprovedCount) els.diffApprovedCount.textContent = approvedCount;

  // Update filter pill active states
  if (els.diffPillFilters) {
    els.diffPillFilters.querySelectorAll(".pill-filter-btn").forEach((btn) => {
      const filter = btn.dataset.filter;
      btn.classList.toggle("active", filter === state.diffFilter);
      if (filter === "risk") btn.classList.toggle("filter-risk", filter === state.diffFilter);
      if (filter === "memory") btn.classList.toggle("filter-memory", filter === state.diffFilter);
    });
  }

  // Show / Hide Action Bar
  if (els.diffActionBar) {
    els.diffActionBar.style.display = total > 0 ? "flex" : "none";
    if (els.diffSyncSelectedBtn) {
      els.diffSyncSelectedBtn.disabled = approvedCount === 0;
    }
  }

  if (total === 0) {
    els.processResult.innerHTML = `
      <div class="empty-state" style="border: 1px dashed var(--line); border-radius: 8px; margin: auto 0; padding: 28px 16px;">
        Process a meeting note with AI to review and sync structured commitments, risks, and memory.
      </div>
    `;
    return;
  }

  const filtered = state.diffFilter === "all"
    ? state.extractedDiffs
    : state.extractedDiffs.filter((d) => d.type === state.diffFilter);

  if (filtered.length === 0) {
    els.processResult.innerHTML = `
      <div class="empty-state" style="border: 1px dashed var(--line); border-radius: 8px; margin: auto 0; padding: 28px 16px;">
        No items in category "${state.diffFilter}".
      </div>
    `;
    return;
  }

  els.processResult.innerHTML = filtered
    .map((item, index) => {
      const isEditing = state.editingDiffId === item.id;
      return `
        <div class="diff-card ${item.selected ? "selected" : "unselected"}"
             data-diff-id="${item.id}"
             tabindex="0"
             role="checkbox"
             aria-checked="${item.selected}">
          <div class="diff-checkbox-box" title="Toggle selection (Spacebar)">
            ${item.selected ? `<svg style="width:12px;height:12px;stroke:currentColor;stroke-width:2.5;fill:none;" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>` : ""}
          </div>
          <div class="diff-content">
            <div class="diff-header-row">
              <span class="diff-type-badge ${item.type}">${escapeHtml(item.subtype || item.type)}</span>
              <div class="diff-actions-inline">
                ${item.priority ? `
                  <span style="font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; ${item.priority === "High" ? "background:#fff1f2; color:#9f1239;" : (item.priority === "Medium" ? "background:#fffbeb; color:#92400e;" : "background:#f1f5f9; color:#475569;")}">
                    ${escapeHtml(item.priority)}
                  </span>
                ` : ""}
                <button type="button" class="diff-icon-btn btn-edit" title="Edit title" data-action="edit" data-id="${item.id}">✎</button>
                <button type="button" class="diff-icon-btn btn-dismiss" title="Dismiss item" data-action="dismiss" data-id="${item.id}">✕</button>
              </div>
            </div>
            ${isEditing ? `
              <input type="text" class="diff-title-input" value="${escapeHtml(item.title)}" data-action="save-edit" data-id="${item.id}" autofocus />
            ` : `
              <div class="diff-title">${escapeHtml(item.title)}</div>
            `}
            ${item.sourceQuote ? `<div class="diff-quote" title="${escapeHtml(item.sourceQuote)}">"${escapeHtml(item.sourceQuote)}"</div>` : ""}
            <div class="diff-meta-row">
              ${item.type === "commitment" ? `
                <div style="display:inline-flex; align-items:center; gap:4px;" onclick="event.stopPropagation()">
                  <span>📅 Due:</span>
                  <input type="date" class="diff-date-input" value="${escapeHtml(item.dueDate)}" data-action="change-date" data-id="${item.id}" />
                </div>
              ` : ""}
              <span>👤 <strong>${escapeHtml(item.clientName)}</strong></span>
            </div>
          </div>
        </div>
      `;
    })
    .join("");

  // Programmatic keyboard focus trapping to first diff card upon extraction completion
  if (shouldFocusFirst) {
    const firstCard = els.processResult.querySelector(".diff-card");
    if (firstCard) {
      window.setTimeout(() => firstCard.focus(), 50);
    }
  }
}

function toggleDiffSelected(id) {
  state.extractedDiffs = state.extractedDiffs.map((d) =>
    d.id === id ? { ...d, selected: !d.selected } : d
  );
  renderDiffStream(false);
}

function dismissDiffItem(id) {
  state.extractedDiffs = state.extractedDiffs.filter((d) => d.id !== id);
  if (state.editingDiffId === id) state.editingDiffId = null;
  renderDiffStream(false);
  showToast("Item dismissed.");
}

function setEditingDiff(id) {
  state.editingDiffId = state.editingDiffId === id ? null : id;
  renderDiffStream(false);
}

function updateDiffField(id, field, value) {
  state.extractedDiffs = state.extractedDiffs.map((d) =>
    d.id === id ? { ...d, [field]: value } : d
  );
}

function discardAllDiffs() {
  state.extractedDiffs = [];
  state.editingDiffId = null;
  renderDiffStream(false);
  showToast("All extracted diffs discarded.");
}

async function syncSelectedDiffs() {
  const selected = state.extractedDiffs.filter((d) => d.selected);
  if (!selected.length) {
    showToast("No diff items selected to sync.", true);
    return;
  }
  showToast(`✓ Synced ${selected.length} items to client memory.`);
  state.extractedDiffs = [];
  state.editingDiffId = null;
  renderDiffStream(false);
  await refreshAll();
  if (state.selectedClientId) {
    await loadMemory(state.selectedClientId);
  }
}

function renderMemory(payload) {
  if (!els.memoryContent) return;
  const commitments = payload.pending_commitments || [];
  const concerns = payload.major_concerns || [];
  const notes = payload.recent_relationship_notes || [];
  const brief = payload.pre_meeting_brief || {};
  els.memoryContent.innerHTML = `
    <div class="brief-card">
      <div class="brief-card-header">
        <div>
          <span class="eyebrow">AI briefing</span>
          <h4>${escapeHtml(brief.title || "Client Brief")}</h4>
        </div>
        <span class="status-pill done">${escapeHtml(payload.client_name)}</span>
      </div>
      <div class="brief-grid">
        <div class="brief-block">
          <span class="brief-label">Last Meeting</span>
          <strong>${escapeHtml(brief.last_meeting || "No recent meeting")}</strong>
        </div>
        <div class="brief-block">
          <span class="brief-label">Pending</span>
          ${
            brief.pending && brief.pending.length
              ? `<ul>${brief.pending.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
              : `<span class="muted">No pending commitment.</span>`
          }
        </div>
        <div class="brief-block">
          <span class="brief-label">Products</span>
          ${
            payload.products_owned && payload.products_owned.length
              ? `<strong>${payload.products_owned.map(escapeHtml).join(", ")}</strong>`
              : `<span class="muted">None recorded.</span>`
          }
        </div>
        <div class="brief-block">
          <span class="brief-label">Concern</span>
          <strong>${escapeHtml(brief.concern || "No major concern captured")}</strong>
        </div>
        <div class="brief-block">
          <span class="brief-label">Suggested Talking Point</span>
          <p>${escapeHtml(brief.suggested_talking_point || "Start with a quick recap and next step.")}</p>
        </div>
      </div>
    </div>
    <div class="panel-heading accordion-toggle" data-target="accordionDetailedHistory" style="margin-top: 15px; padding: 10px 0; border-top: 1px dashed var(--line); border-bottom: none;">
      <div style="pointer-events: none; width: 100%;">
        <h4 style="display:flex; align-items:center; justify-content: space-between; font-size: 13px; margin:0; color: var(--text);">
          View Detailed History <span class="accordion-icon" style="font-size: 10px;">▼</span>
        </h4>
      </div>
    </div>
    <div class="accordion-content collapsed" id="accordionDetailedHistory">
      <div class="memory-block narrative-block" style="margin-top: 10px;">
        <h4>AI Memory Narrative</h4>
        <p>${escapeHtml(payload.rolling_summary || payload.last_meeting_summary || "No rolling summary yet.")}</p>
      </div>
      <div class="memory-block">
        <h4>Last meeting summary</h4>
        <p>${escapeHtml(payload.last_meeting_summary || "No recent summary.")}</p>
      </div>
      <div class="memory-block">
        <h4>Pending commitments</h4>
        ${commitments.length ? `<ul>${commitments.map((item) => `<li>${escapeHtml(item.description)} - ${escapeHtml(formatShortDate(item.due_date || item.due_date_text))}</li>`).join("")}</ul>` : `<span class="muted">No pending commitments.</span>`}
      </div>
      <div class="memory-block">
        <h4>Concerns</h4>
        ${concerns.length ? `<ul>${concerns.map((item) => `<li>${escapeHtml(item.description || item)}</li>`).join("")}</ul>` : `<span class="muted">No concerns captured.</span>`}
      </div>
      <div class="memory-block">
        <h4>Recent notes</h4>
        ${notes.length ? `<ul>${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>` : `<span class="muted">No recent notes.</span>`}
      </div>
    </div>
  `;
}

async function loadPriorities() {
  try {
    const payload = await api("/api/v1/dashboard/priorities");
    state.priorities.tasks = payload.tasks || [];
    state.priorities.risks = payload.risks || [];
    renderTasks();
    renderRisks();
  } catch (err) {
    console.warn("Priorities load error:", err);
  }
}

function renderTasks() {
  if (!els.taskList) return;
  const tasks = state.priorities.tasks;
  if (!tasks.length) {
    els.taskList.innerHTML = `<div class="empty-state">✅ All caught up! No pressing tasks for today.</div>`;
    return;
  }
  const today = todayIso();
  els.taskList.innerHTML = tasks
    .map((task) => {
      const due = task.due_date || "";
      let variant = "upcoming";
      let badgeLabel = due ? `Due ${due}` : "No due date";
      if (task.is_overdue || (due && due < today)) {
        variant = "overdue";
        badgeLabel = `Overdue — ${due}`;
      } else if (task.is_due_today || due === today) {
        variant = "due-today";
        badgeLabel = "Due today";
      }
      return `
        <div class="task-card ${variant}">
          <div class="task-card-title">${escapeHtml(task.description)}</div>
          <div class="task-card-meta">
            <span class="task-badge ${variant}">${escapeHtml(badgeLabel)}</span>
            <span class="client-meta">${escapeHtml(task.client_name || `Client #${task.client_id}`)}</span>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderRisks() {
  if (!els.riskList) return;
  const risks = state.priorities.risks;
  const riskCount = risks.length;
  
  const header = document.getElementById('riskSignalsHeader');
  const badge = document.getElementById('riskSignalsBadge');
  if (header && badge) {
    header.style.color = 'var(--ink)'; // High contrast AAA in both light and dark
    if (!riskCount) {
      badge.style.cssText = 'font-size: 12px; font-weight: 600; background: var(--success-bg); color: var(--success-text); border: 1px solid var(--success-border); padding: 2px 10px; border-radius: 9999px; display: inline-flex; align-items: center; gap: 6px; letter-spacing: normal;';
      badge.innerHTML = `<span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--success-base);"></span>0 Active Risks - All Clear`;
    } else {
      badge.style.cssText = 'font-size: 12px; font-weight: 600; background: var(--danger-bg); color: var(--danger-text); border: 1px solid var(--danger-border); padding: 2px 10px; border-radius: 9999px; display: inline-flex; align-items: center; gap: 6px; letter-spacing: normal;';
      badge.innerHTML = `<span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--danger-base); box-shadow: 0 0 0 2px rgba(244,63,94,0.25);"></span>${riskCount} Action Required`;
    }
  }

  const stripCount = document.getElementById('riskSignalsStripCount');
  const stripBadge = document.getElementById('riskSignalsStripBadge');
  if (stripCount && stripBadge) {
    stripCount.textContent = riskCount;
    if (!riskCount) {
      stripBadge.className = 'verdict-badge emerald';
      stripBadge.textContent = 'All clear';
    } else {
      stripBadge.className = 'verdict-badge rose';
      stripBadge.textContent = `${riskCount} Active`;
    }
  }

  if (!riskCount) {
    els.riskList.innerHTML = `<div class="empty-state" style="padding:20px; background:transparent;">🛡️ All clear. No active risk signals detected.</div>`;
    return;
  }
  els.riskList.innerHTML = risks
    .map((risk) => {
      const severity = (risk.severity_level || "medium").toLowerCase();
      const confidence = Math.round((risk.confidence || 0) * 100);
      return `
        <div class="risk-card ${severity}">
          <div class="risk-card-title">${escapeHtml(risk.description)}</div>
          <div class="risk-card-meta">
            <span class="risk-badge ${severity}">${escapeHtml(severity)}</span>
            <span class="task-badge ${risk.requires_review ? "overdue" : "upcoming"}">${risk.requires_review ? "Review needed" : "Monitoring"}</span>
            <span class="client-meta">${escapeHtml(risk.client_name || `Client #${risk.client_id}`)} &mdash; ${confidence}% confidence</span>
          </div>
        </div>
      `;
    })
    .join("");
}

async function loadTeamPerformance() {
  if (authState.role !== "owner" && authState.role !== "admin") {
    if (els.teamPerformanceSection) els.teamPerformanceSection.style.display = "none";
    return;
  }
  if (state.workspaceScope !== "team") {
    if (els.teamPerformanceSection) els.teamPerformanceSection.style.display = "none";
    return;
  }
  
  try {
    const data = await api("/api/v1/dashboard/team-performance");
    if (!els.teamPerformanceSection || !els.teamPerformanceBody) return;
    
    els.teamPerformanceSection.style.display = "block";
    els.teamPerformanceBody.innerHTML = data.members.map(member => {
      const completionRate = member.total_commitments > 0 
        ? Math.round((member.completed_commitments / member.total_commitments) * 100) 
        : 100;
        
      const barColor = completionRate >= 80 ? "#10b981" : (completionRate >= 50 ? "#f59e0b" : "#ef4444");
      
      return `
        <tr>
          <td><strong>${escapeHtml(member.email)}</strong></td>
          <td>${member.total_clients}</td>
          <td>${member.total_meetings}</td>
          <td>
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="flex: 1; height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden;">
                <div style="width: ${completionRate}%; height: 100%; background: ${barColor};"></div>
              </div>
              <span style="font-size: 12px; font-weight: 600; min-width: 30px;">${completionRate}%</span>
              <span style="font-size: 11px; color: var(--muted); margin-left: 10px;">
                (${member.completed_commitments}/${member.total_commitments} done, ${member.pending_commitments} pending)
              </span>
            </div>
          </td>
        </tr>
      `;
    }).join("");
  } catch (error) {
    console.error("Failed to load team performance:", error);
    if (els.teamPerformanceSection && els.teamPerformanceBody) {
      els.teamPerformanceSection.style.display = "block";
      els.teamPerformanceBody.innerHTML = `<tr><td colspan="4" style="color:red; padding:20px;">Error loading team performance: ${error.message}</td></tr>`;
    }
  }
}

async function loadClients() {
  state.clients = await api(`/api/v1/clients?scope=${state.workspaceScope}`);
  if (!state.selectedClientId && state.clients.length) {
    state.selectedClientId = state.clients[0].id;
  }
  renderClients();
}

async function loadCommitments() {
  const filter = els.commitmentFilter ? els.commitmentFilter.value : "";
  const queryParams = new URLSearchParams();
  if (filter) queryParams.append("status", filter);
  queryParams.append("scope", state.workspaceScope);
  const payload = await api(`/api/v1/commitments?${queryParams.toString()}`);
  state.commitments = payload.commitments || [];
  renderCommitments();
}

async function loadMemory(clientId = state.selectedClientId) {
  if (!clientId) {
    showToast("Select a client first.", true);
    return;
  }
  const payload = await api(`/api/v1/clients/${clientId}/memory`);
  state.selectedClientId = Number(clientId);
  state.clients = state.clients.map((client) =>
    client.id === state.selectedClientId
      ? {
          ...client,
          rolling_summary: payload.rolling_summary,
          last_meeting_summary: payload.last_meeting_summary,
        }
      : client
  );
  renderMemory(payload);
  if (els.askClientSection) els.askClientSection.classList.remove("hidden");
  if (els.askClientInput) els.askClientInput.value = "";
  if (els.askClientResult) {
    els.askClientResult.innerHTML = "";
    els.askClientResult.classList.add("hidden");
  }
  renderClients();
}

async function askClient() {
  if (!state.selectedClientId || !els.askClientInput) return;
  const query = els.askClientInput.value.trim();
  if (!query) return;

  els.askClientResult.classList.remove("hidden");
  els.askClientResult.innerHTML = `<span class="muted">Asking AI...</span>`;

  try {
    const payload = await api(`/api/v1/clients/${state.selectedClientId}/ask`, {
      method: "POST",
      body: JSON.stringify({ query }),
    });

    let answerHtml = `<p>${escapeHtml(payload.answer)}</p>`;
    if (payload.source_meetings && payload.source_meetings.length > 0) {
      answerHtml += `<p class="muted" style="margin-top: 0.5rem; font-size: 0.8rem;">Sources: Meetings ${payload.source_meetings.join(", ")}</p>`;
    }
    els.askClientResult.innerHTML = answerHtml;
  } catch (err) {
    els.askClientResult.innerHTML = `<span class="error" style="color: var(--danger)">${escapeHtml(err.message)}</span>`;
  }
}

async function loadMetrics() {
  try {
    const data = await api("/api/v1/dashboard/metrics");
    if (data && data.metrics) {
      state.metrics = data.metrics;
    }
  } catch (err) {
    console.warn("Failed to load metrics:", err);
  }
}

async function refreshAll() {
  try {
    await Promise.all([
      checkHealth(),
      loadMetrics(),
      loadClients(),
      loadCommitments(),
      loadPriorities(),
      loadTeamPerformance()
    ]);
  } catch (err) {
    console.warn("Failed during refreshAll:", err);
  }

  // Hide Zoho-style content loader and show actual content
  const loader = document.getElementById("contentLoader");
  const content = document.getElementById("dashboardMainContent");
  if (loader && content) {
    loader.style.display = "none";
    content.style.display = "block";
  }
}

async function withLoading(button, label, fn) {
  if (!button || button.disabled) return;
  const original = button.textContent;
  button.disabled = true;
  button.classList.add("loading");
  button.textContent = label;
  try {
    await fn();
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
    button.textContent = original;
  }
}

async function processNotes() {
  if (els.editTranscriptPanel) els.editTranscriptPanel.classList.add("hidden");
  const rawNotes = els.rawNotes ? els.rawNotes.value.trim() : "";
  if (!rawNotes) {
    showToast("Paste meeting notes first.", true);
    return;
  }
  const body = {
    raw_notes: rawNotes,
    meeting_date: els.meetingDate?.value || undefined,
    known_client_id: els.knownClient?.value ? Number(els.knownClient.value) : undefined,
  };
  const payload = await api("/api/v1/meeting-notes/process", {
    method: "POST",
    body: JSON.stringify(body),
  });
  
  // Refresh state first so new clients/data are available to renderProcessResult
  await refreshAll();
  renderProcessResult(payload);
  
  if (payload.client_id) {
    await loadMemory(payload.client_id);
  }
  showToast("Meeting notes processed.");
}

async function confirmClient() {
  if (!state.pendingConfirmationMeetingId) {
    showToast("No meeting needs confirmation.", true);
    return;
  }
  const existingClientId = els.confirmClientSelect?.value;
  const newClientName = els.newClientName?.value.trim();
  const newClientEmail = els.newClientEmail?.value.trim();
  const newClientPhone = els.newClientPhone?.value.trim();
  if (!existingClientId && !newClientName) {
    showToast("Select a client or enter a new name.", true);
    return;
  }
  const payload = await api(`/api/v1/meeting-notes/${state.pendingConfirmationMeetingId}/confirm-client`, {
    method: "POST",
    body: JSON.stringify({
      client_id: existingClientId ? Number(existingClientId) : undefined,
      new_client_name: newClientName || undefined,
      new_client_email: newClientEmail || undefined,
      new_client_whatsapp_phone: newClientPhone || undefined,
    }),
  });
  if (els.newClientName) els.newClientName.value = "";
  if (els.newClientEmail) els.newClientEmail.value = "";
  if (els.newClientPhone) els.newClientPhone.value = "";
  if (els.confirmPanel) els.confirmPanel.classList.add("hidden");
  
  await refreshAll();
  renderProcessResult(payload);
  
  if (payload.client_id) {
    await loadMemory(payload.client_id);
  }
  showToast("Client confirmed.");
}

async function updateCommitmentStatus(commitmentId, status) {
  await api(`/api/v1/commitments/${commitmentId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
  await loadCommitments();
  if (state.selectedClientId) {
    await loadMemory(state.selectedClientId);
  }
  showToast(`Commitment marked ${status}.`);
}

async function saveTranscript() {
  const meetingId = els.editTranscriptPanel?.dataset.meetingId;
  const rawNotes = els.editTranscriptText?.value.trim();

  if (!meetingId) {
    showToast("Meeting ID missing.", true);
    return;
  }
  if (!rawNotes) {
    showToast("Transcript cannot be empty.", true);
    return;
  }

  els.editTranscriptPanel.classList.add("hidden");
  if (els.processResult) {
    els.processResult.innerHTML = `
      <div style="display: flex; align-items: center; gap: 10px; padding: 10px;">
        <span class="status-dot pulsing" style="background: var(--blue);"></span>
        <strong style="color: var(--blue);">Reprocessing transcript via AI... This may take a few seconds.</strong>
      </div>
    `;
  }

  await api(`/api/v1/meeting-notes/${meetingId}/transcript`, {
    method: "PATCH",
    body: JSON.stringify({ raw_notes: rawNotes }),
  });

  // Polling loop with fetchWithAuth
  const pollInterval = setInterval(async () => {
    try {
      const meeting = await api(`/api/v1/meeting-notes/${meetingId}`);
      if (meeting.status === "processed") {
        clearInterval(pollInterval);
        renderProcessResult({
          meeting_id: meeting.id,
          client_status: meeting.client_identification_status || "identified",
          client_id: meeting.client_id,
          requires_client_confirmation: false,
          meeting_summary: meeting.summary,
          commitments_created: [],
          commitments_updated: [],
          pending_commitments: meeting.commitments || [],
          warnings: [],
        });
        await refreshAll();
        if (meeting.client_id) {
          await loadMemory(meeting.client_id);
        }
        showToast("Transcript successfully reprocessed.");
      } else if (meeting.status === "client_identification_required") {
        clearInterval(pollInterval);
        state.pendingConfirmationMeetingId = meetingId;
        if (els.newClientName) els.newClientName.value = meeting.suggested_name || "";
        if (els.newClientEmail) els.newClientEmail.value = meeting.suggested_email || "";
        if (els.newClientPhone) els.newClientPhone.value = meeting.suggested_whatsapp_phone || "";
        if (els.confirmPanel) els.confirmPanel.classList.remove("hidden");
        await refreshAll();
        showToast("Client identification required.");
      } else if (meeting.status === "manual_review_required" || meeting.status === "failed") {
        clearInterval(pollInterval);
        if (els.editTranscriptPanel) els.editTranscriptPanel.classList.remove("hidden");
        if (els.processResult) {
          els.processResult.innerHTML = '<span class="muted">Reprocessing failed again. Please check your text.</span>';
        }
        showToast("Failed to process notes.", true);
      }
    } catch (err) {
      console.error("Polling error:", err);
    }
  }, 2000);
}

async function processAudio() {
  const file = els.audioFileInput.files[0];
  if (!file) throw new Error("Please select an audio file first.");
  if (file.size > 50 * 1024 * 1024) throw new Error("File is too large. Maximum size is 50MB.");

  const dateValue = els.meetingDateAudio.value;
  if (!dateValue) throw new Error("Please select a meeting date.");

  els.processAudio.disabled = true;
  if (els.editTranscriptPanel) els.editTranscriptPanel.classList.add("hidden");
  els.processAudio.textContent = "Uploading...";
  els.audioStatusBox.classList.remove("hidden");
  els.audioStatusText.textContent = "Uploading...";
  els.audioStatusDetails.textContent = "Please wait while the file is sent to the server.";

  const formData = new FormData();
  formData.append("file", file);
  formData.append("meeting_date", dateValue);

  const knownClientId = els.knownClient ? els.knownClient.value : "";
  if (knownClientId) {
    formData.append("known_client_id", knownClientId);
  }

  try {
    const result = await api("/api/v1/audio/upload", {
      method: "POST",
      body: formData,
    });

    els.audioStatusText.textContent = "Audio Uploaded & Queued!";
    els.audioStatusDetails.textContent = `Meeting ID: ${result.meeting_id} is now ${result.status}. The AI is processing it in the background. Please wait...`;

    els.audioFileInput.value = "";
    els.uploadFileName.textContent = "Click to select audio file";
    els.processAudio.textContent = "Upload & Process";

    showToast("Audio queued for processing.");

    // Polling loop
    const meetingId = result.meeting_id;
    const pollInterval = setInterval(async () => {
      try {
        const meeting = await api(`/api/v1/meeting-notes/${meetingId}`);
        if (meeting.status === "processed") {
          clearInterval(pollInterval);
          els.audioStatusText.textContent = "Audio Processed!";
          els.audioStatusDetails.textContent = "Processing complete. Your summary and follow-ups are shown below.";
          els.processAudio.disabled = false;

          renderProcessResult({
            meeting_id: meeting.id,
            client_status: meeting.client_identification_status || "identified",
            client_id: meeting.client_id,
            requires_client_confirmation: false,
            meeting_summary: meeting.summary,
            commitments_created: [],
            commitments_updated: [],
            pending_commitments: meeting.commitments || [],
            warnings: [],
          });

          await refreshAll();
          if (meeting.client_id) {
            await loadMemory(meeting.client_id);
          }
        } else if (meeting.status === "client_identification_required") {
          clearInterval(pollInterval);
          els.audioStatusText.textContent = "Client Identification Required!";
          els.audioStatusDetails.textContent = "Please confirm the client name to continue.";
          els.processAudio.disabled = false;

          state.pendingConfirmationMeetingId = meetingId;
          if (els.newClientName) els.newClientName.value = meeting.suggested_name || "";
          if (els.newClientEmail) els.newClientEmail.value = meeting.suggested_email || "";
          if (els.newClientPhone) els.newClientPhone.value = meeting.suggested_whatsapp_phone || "";
          if (els.confirmPanel) els.confirmPanel.classList.remove("hidden");
          await refreshAll();
        } else if (meeting.status === "manual_review_required" || meeting.status === "failed") {
          clearInterval(pollInterval);
          els.audioStatusText.textContent = "Audio Needs Review";
          els.audioStatusDetails.textContent = "PHILIXA could not detect usable speech or safely create a summary.";
          els.processAudio.disabled = false;
          if (els.editTranscriptText) els.editTranscriptText.value = meeting.raw_notes || "";
          if (els.editTranscriptPanel) {
            els.editTranscriptPanel.dataset.meetingId = meeting.id;
            els.editTranscriptPanel.classList.remove("hidden");
          }
          renderProcessResult({
            meeting_id: meeting.id,
            client_status: "manual review required",
            client_id: meeting.client_id,
            requires_client_confirmation: false,
            meeting_summary: meeting.summary,
            commitments_created: [],
            commitments_updated: [],
            pending_commitments: [],
            warnings: ["No usable meeting summary or follow-ups were saved."],
          });
          showToast("Audio transcript needs manual review.", true);
        }
      } catch (err) {
        console.error("Audio polling error", err);
      }
    }, 5000);
  } catch (error) {
    els.processAudio.disabled = false;
    els.processAudio.textContent = "Upload & Process";
    els.audioStatusBox.classList.add("hidden");
    throw error;
  }
}

async function openSettings() {
  if (!els.settingsModal) return;
  els.settingsModal.classList.remove("hidden");
  try {
    const payload = await api("/api/v1/preferences");
    if (els.prefOptIn) els.prefOptIn.checked = payload.is_opted_in;
    if (els.prefContact) els.prefContact.value = payload.whatsapp_number || "";
    if (els.prefQuietStart) els.prefQuietStart.value = payload.quiet_hours_start || "";
    if (els.prefQuietEnd) els.prefQuietEnd.value = payload.quiet_hours_end || "";
  } catch (err) {
    showToast(err.message, true);
  }
}

function closeSettings() {
  if (els.settingsModal) els.settingsModal.classList.add("hidden");
}

async function saveSettings() {
  const body = {
    is_opted_in: els.prefOptIn?.checked || false,
    whatsapp_number: els.prefContact?.value.trim() || null,
    quiet_hours_start: els.prefQuietStart?.value || null,
    quiet_hours_end: els.prefQuietEnd?.value || null,
  };
  try {
    await api("/api/v1/preferences", {
      method: "PUT",
      body: JSON.stringify(body),
    });
    showToast("Preferences saved.");
    closeSettings();
  } catch (err) {
    showToast(err.message, true);
  }
}

// =============================================================================
// LIVE RECORDING & WEBSOCKET TICKET INTEGRATION
// =============================================================================

let liveWs = null;
let liveAudioContext = null;
let liveAudioStream = null;
let liveWorkletNode = null;
let isLiveRecording = false;
let _liveSampleRate = 16000;

async function startLiveRecording(diarize = false) {
  if (isLiveRecording) return;

  try {
    // 1. Mint short-lived 60s ticket from backend
    let ticket;
    try {
      const ticketRes = await api("/api/v1/ws-ticket", { method: "POST" });
      ticket = ticketRes.ticket || ticketRes.token;
      if (!ticket) throw new Error("Ticket payload missing ticket property");
    } catch (ticketErr) {
      console.error("[Live] Ticket generation error:", ticketErr);
      showToast("Live recording authentication failed. Please re-login.", true);
      return;
    }

    // 2. Microphone stream
    liveAudioStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    liveAudioContext = new (window.AudioContext || window.webkitAudioContext)();
    _liveSampleRate = liveAudioContext.sampleRate || 16000;

    try {
      await liveAudioContext.audioWorklet.addModule("/static/pcm-processor.js");
    } catch (err) {
      console.error("[Live] AudioWorklet load failed:", err);
      showToast("Audio processor failed to load. Please refresh.", true);
      if (liveAudioContext) liveAudioContext.close();
      liveAudioContext = null;
      return;
    }

    const source = liveAudioContext.createMediaStreamSource(liveAudioStream);
    liveWorkletNode = new AudioWorkletNode(liveAudioContext, "pcm-processor");

    // 3. Connect WebSocket with ticket
    connectLiveWebSocket(ticket, _liveSampleRate, diarize);

    // 4. Pipe PCM chunks to WebSocket
    liveWorkletNode.port.onmessage = (event) => {
      if (liveWs?.readyState === WebSocket.OPEN) {
        liveWs.send(event.data);
      }
    };

    source.connect(liveWorkletNode);
    liveWorkletNode.connect(liveAudioContext.destination);

    isLiveRecording = true;
    updateLiveUI("recording");
  } catch (err) {
    console.error("[Live] Recording start error:", err);
    updateLiveUI("error", err.message);
  }
}

function connectLiveWebSocket(ticket, sampleRate, diarize = false) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/api/v1/live/transcribe?ticket=${encodeURIComponent(ticket)}&sample_rate=${sampleRate}&diarize=${diarize}`;
  
  liveWs = new WebSocket(wsUrl);
  liveWs.binaryType = "arraybuffer";

  liveWs.onopen = () => {
    console.log("[Live] WebSocket connected via secure ticket.");
    updateLiveUI("recording");
  };

  liveWs.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.action === "processing") {
        const statusEl = document.getElementById("liveStatusText");
        if (statusEl) statusEl.textContent = "⏳ Processing audio...";
        return;
      }
      // Server auto-stopped due to idle timeout (no audio for 2 minutes)
      if (data.action === "timeout") {
        if (liveWs) liveWs.close(1000, "Idle timeout");
        liveWs = null;
        updateLiveUI("stopped");
        showToast(`⏱️ ${data.error || "Recording auto-stopped: no audio detected."}`, true);
        return;
      }
      // Server blocked this action (e.g. demo account restriction)
      if (data.action === "error") {
        if (liveWs) liveWs.close(1000, "Server error");
        liveWs = null;
        updateLiveUI("stopped");
        showToast(`🚫 ${data.error || "An error occurred."}`, true);
        return;
      }
      if (data.action === "stopped") {
        if (liveWs) liveWs.close(1000, "Clean close after stop");
        liveWs = null;
        updateLiveUI("stopped");

        if (data.confirmed && data.confirmed.trim()) {
          const rawNotesEl = document.getElementById("rawNotes");
          if (rawNotesEl) rawNotesEl.value = data.confirmed.trim();
          const tabTextBtn = document.getElementById("tabTextBtn");
          if (tabTextBtn) tabTextBtn.click();
          showToast("✅ Transcript ready! Review and click Process Notes.");
        } else {
          showToast("⚠️ No audio recorded or transcription failed.", true);
        }
      }
    } catch (parseErr) {
      console.error("[Live] WS message parse error:", parseErr);
    }
  };

  liveWs.onclose = (event) => {
    console.log(`[Live] WebSocket closed (code: ${event.code}).`);
    if (event.code === 1008) {
      console.error("[Live] WS 1008 Policy Violation:", event.reason);
      showToast(`Live recording error: ${event.reason || "Authentication rejected"}`, true);
      stopLiveRecording();
      return;
    }
    if (isLiveRecording && event.code !== 1000) {
      // Reconnect with a fresh ticket
      setTimeout(async () => {
        if (isLiveRecording) {
          try {
            const ticketRes = await api("/api/v1/ws-ticket", { method: "POST" });
            const freshTicket = ticketRes.ticket || ticketRes.token;
            if (freshTicket) {
              connectLiveWebSocket(freshTicket, sampleRate, diarize);
            }
          } catch (_) {}
        }
      }, 2000);
    }
  };

  liveWs.onerror = (err) => {
    console.error("[Live] WebSocket error:", err);
  };
}

function stopLiveRecording() {
  isLiveRecording = false;

  if (liveWorkletNode) {
    try {
      liveWorkletNode.disconnect();
    } catch (_) {}
    liveWorkletNode = null;
  }
  if (liveAudioContext) {
    try {
      liveAudioContext.close();
    } catch (_) {}
    liveAudioContext = null;
  }
  if (liveAudioStream) {
    try {
      liveAudioStream.getTracks().forEach((t) => t.stop());
    } catch (_) {}
    liveAudioStream = null;
  }

  if (liveWs?.readyState === WebSocket.OPEN) {
    liveWs.send(JSON.stringify({ action: "stop" }));
    const stopBtn = document.getElementById("stopLiveBtn");
    if (stopBtn) {
      stopBtn.textContent = "Saving...";
      stopBtn.disabled = true;
    }
  } else {
    liveWs = null;
    updateLiveUI("stopped");
  }
}

function updateLiveUI(uiState, message = "") {
  const states = {
    recording: { text: "🔴 Recording...", startDisabled: true, stopDisabled: false },
    stopped: { text: "⏸ Ready", startDisabled: false, stopDisabled: true },
    error: { text: `❌ ${message}`, startDisabled: false, stopDisabled: true },
  };
  const s = states[uiState] || states.stopped;
  const statusEl = document.getElementById("liveStatusText");
  const soloBtn = document.getElementById("startSoloBtn");
  const meetingBtn = document.getElementById("startMeetingBtn");
  const stopBtn = document.getElementById("stopLiveBtn");
  if (statusEl) statusEl.textContent = s.text;
  if (soloBtn) soloBtn.disabled = s.startDisabled;
  if (meetingBtn) meetingBtn.disabled = s.startDisabled;
  if (stopBtn) {
    stopBtn.disabled = s.stopDisabled;
    if (uiState === "stopped") stopBtn.textContent = "Stop & Save";
  }
}

// =============================================================================
// EVENT BINDINGS & INITIALIZATION
// =============================================================================

function bindEvents() {
  // Auth Form Handlers
  els.loginForm?.addEventListener("submit", handleLogin);
  els.demoLoginBtn?.addEventListener("click", handleDemoLogin);
  els.registerForm?.addEventListener("submit", handleRegister);
  els.verifyEmailForm?.addEventListener("submit", handleVerifyEmail);
  els.forgotPasswordForm?.addEventListener("submit", handleForgotPassword);
  els.resetPasswordForm?.addEventListener("submit", handleResetPassword);
  els.acceptInviteForm?.addEventListener("submit", handleAcceptInvite);

  // Auth View Switching Links
  els.linkToRegister?.addEventListener("click", () => showAuthOverlay("register"));
  els.linkToLoginFromRegister?.addEventListener("click", () => showAuthOverlay("login"));
  els.linkToForgotPassword?.addEventListener("click", () => showAuthOverlay("forgot-password"));
  els.linkToLoginFromForgot?.addEventListener("click", () => showAuthOverlay("login"));
  els.linkToVerifyEmail?.addEventListener("click", () => showAuthOverlay("verify-email"));
  els.linkToLoginFromVerify?.addEventListener("click", () => showAuthOverlay("login"));
  els.linkToResetWithToken?.addEventListener("click", () => showAuthOverlay("reset-password"));
  els.linkToLoginFromReset?.addEventListener("click", () => showAuthOverlay("login"));
  els.linkToLoginFromInvite?.addEventListener("click", () => showAuthOverlay("login"));

  // Register Segmented Control Toggle
  els.typeCompany?.addEventListener("change", () => {
    els.labelTypeCompany?.classList.add("active");
    els.labelTypeIndividual?.classList.remove("active");
  });
  els.typeIndividual?.addEventListener("change", () => {
    els.labelTypeIndividual?.classList.add("active");
    els.labelTypeCompany?.classList.remove("active");
  });

  // Topbar Workspace & Members Actions
  els.workspaceSelect?.addEventListener("change", (e) => handleSwitchWorkspace(e.target.value));
  els.scopeSelect?.addEventListener("change", async (e) => {
    state.workspaceScope = e.target.value;
    state.selectedClientId = null;
    await Promise.all([
      loadClients(),
      loadCommitments(),
      loadTeamPerformance()
    ]);
    showToast("Workspace view updated");
  });
  els.manageMembersBtn?.addEventListener("click", openMemberModal);
  els.closeMemberModalBtn?.addEventListener("click", closeMemberModal);
  els.inviteMemberForm?.addEventListener("submit", handleInviteMember);
  els.logoutBtn?.addEventListener("click", handleLogout);

  // Client Selection
  els.topClientSelect?.addEventListener("change", (e) => {
    const val = e.target.value;
    if (val) {
      state.selectedClientId = parseInt(val, 10);
      loadMemory().catch((err) => showToast(err.message, true));
    } else {
      state.selectedClientId = null;
      if (els.memoryContent) {
        els.memoryContent.innerHTML = `<div class="empty-state">Select a client to view instant context.</div>`;
      }
      if (els.askClientSection) els.askClientSection.classList.add("hidden");
    }
    if (els.deleteSelectedClientBtn) {
      const show = !!state.selectedClientId;
      els.deleteSelectedClientBtn.style.display = show ? "flex" : "none";
      if (els.viewClientProfileBtn) {
        els.viewClientProfileBtn.style.display = show ? "flex" : "none";
      }
      const divider = document.getElementById("deleteClientDivider");
      if (divider) divider.style.display = show ? "block" : "none";
    }
    updateMetrics();
  });

  els.deleteSelectedClientBtn?.addEventListener("click", async () => {
    if (!state.selectedClientId) return;
    const client = state.clients.find(c => c.id === state.selectedClientId);
    if (!client) return;
    if (!window.confirm(`Are you sure you want to delete the client "${client.name}"? This will permanently delete all associated meetings and commitments.`)) return;

    try {
      const btn = els.deleteSelectedClientBtn;
      btn.disabled = true;
      btn.textContent = "Deleting...";
      await api(`/api/v1/clients/${state.selectedClientId}`, { method: "DELETE" });
      showToast(`Client "${client.name}" deleted successfully.`);
      state.selectedClientId = null;
      await bootstrapSession(); // Reload data
    } catch (err) {
      showToast(`Failed to delete client: ${err.message}`, true);
    } finally {
      const btn = els.deleteSelectedClientBtn;
      btn.disabled = false;
      btn.textContent = "Delete";
    }
  });

  // Process & Confirm Notes
  els.processNotes?.addEventListener("click", () =>
    withLoading(els.processNotes, "Processing…", () => processNotes()).catch((err) => showToast(err.message, true))
  );

  // Hotkey Disambiguation & Global Shortcuts (Recommendation 4 & 5)
  document.addEventListener("keydown", (e) => {
    const isCmdOrCtrl = e.metaKey || e.ctrlKey;

    // Escape closes sidecar dock or open modals
    if (e.key === "Escape") {
      if (document.body.dataset.sidecarOpen === "true") {
        toggleCopilotSidecar(false);
      }
      return;
    }

    // Toggle Left Sidebar Collapse (Cmd+[)
    if (isCmdOrCtrl && e.key === "[") {
      e.preventDefault();
      document.querySelector(".app-shell")?.classList.toggle("sidebar-collapsed");
      return;
    }

    // Toggle AI Copilot Sidecar (Cmd+Shift+L, Cmd+/, or Cmd+J)
    if (
      (isCmdOrCtrl && e.shiftKey && (e.key === "L" || e.key === "l")) ||
      (isCmdOrCtrl && e.key === "/") ||
      (isCmdOrCtrl && (e.key === "J" || e.key === "j"))
    ) {
      e.preventDefault();
      toggleCopilotSidecar();
      return;
    }

    // Batch Diff Sync (Cmd+Shift+Enter or Cmd+S)
    if ((isCmdOrCtrl && e.shiftKey && e.key === "Enter") || (isCmdOrCtrl && (e.key === "s" || e.key === "S"))) {
      if (state.extractedDiffs && state.extractedDiffs.length > 0) {
        e.preventDefault();
        syncSelectedDiffs();
        return;
      }
    }

    // Process Meeting Notes Intake (Cmd+Enter exclusively)
    if (isCmdOrCtrl && !e.shiftKey && e.key === "Enter") {
      // If focused inside Copilot or other specific modals, ignore
      if (document.activeElement && document.activeElement.id === "copilotInput") {
        return;
      }
      e.preventDefault();
      if (els.processNotes && !els.processNotes.disabled && !els.processNotes.classList.contains("loading")) {
        els.processNotes.click();
      }
      return;
    }
  });

  // Diff Review Category Filter Pills
  els.diffPillFilters?.addEventListener("click", (e) => {
    const btn = e.target.closest(".pill-filter-btn");
    if (!btn) return;
    state.diffFilter = btn.dataset.filter || "all";
    renderDiffStream(false);
  });

  // Diff Review Card Stream Interaction (Fitts's Law Full-Card Toggle, Micro-Actions)
  els.processResult?.addEventListener("click", (e) => {
    // 1. Inline edit button
    const editBtn = e.target.closest('button[data-action="edit"]');
    if (editBtn) {
      e.stopPropagation();
      setEditingDiff(editBtn.dataset.id);
      return;
    }

    // 2. Dismiss item button
    const dismissBtn = e.target.closest('button[data-action="dismiss"]');
    if (dismissBtn) {
      e.stopPropagation();
      dismissDiffItem(dismissBtn.dataset.id);
      return;
    }

    // 3. Ignore date inputs or text inputs
    if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") {
      return;
    }

    // 4. Full card click toggles selection
    const card = e.target.closest(".diff-card");
    if (card && card.dataset.diffId) {
      toggleDiffSelected(card.dataset.diffId);
    }
  });

  // Diff Review Keyboard Accessibility (Spacebar toggles card, Enter/Esc finishes edit)
  els.processResult?.addEventListener("keydown", (e) => {
    const card = e.target.closest(".diff-card");
    if (!card) return;

    if (e.key === " " && e.target.tagName !== "INPUT") {
      e.preventDefault();
      toggleDiffSelected(card.dataset.diffId);
    } else if (e.key === "Enter" && e.target.dataset.action === "save-edit") {
      e.preventDefault();
      state.editingDiffId = null;
      renderDiffStream(false);
    } else if (e.key === "Escape" && e.target.dataset.action === "save-edit") {
      e.preventDefault();
      state.editingDiffId = null;
      renderDiffStream(false);
    }
  });

  // Finish inline edit on blur/focusout
  els.processResult?.addEventListener("focusout", (e) => {
    if (e.target.dataset && e.target.dataset.action === "save-edit") {
      state.editingDiffId = null;
      renderDiffStream(false);
    }
  });

  // Diff Review Inputs (Title inline editing, Due date change)
  els.processResult?.addEventListener("input", (e) => {
    if (e.target.dataset.action === "save-edit") {
      updateDiffField(e.target.dataset.id, "title", e.target.value);
    } else if (e.target.dataset.action === "change-date") {
      updateDiffField(e.target.dataset.id, "dueDate", e.target.value);
    }
  });

  // Diff Review Action Bar
  els.diffDiscardAllBtn?.addEventListener("click", discardAllDiffs);
  els.diffSyncSelectedBtn?.addEventListener("click", syncSelectedDiffs);

  // Tablet Switcher Tabs (< 1024px)
  els.tabMobileIntake?.addEventListener("click", () => {
    els.tabMobileIntake.classList.add("active");
    els.tabMobileDiffs?.classList.remove("active");
    if (els.notePanel) els.notePanel.classList.remove("tablet-hidden");
    if (els.diffWorkbench) els.diffWorkbench.classList.add("tablet-hidden");
  });

  els.tabMobileDiffs?.addEventListener("click", () => {
    els.tabMobileDiffs.classList.add("active");
    els.tabMobileIntake?.classList.remove("active");
    if (els.diffWorkbench) els.diffWorkbench.classList.remove("tablet-hidden");
    if (els.notePanel) els.notePanel.classList.add("tablet-hidden");
  });

  // Verdict Cards Interaction (Click & Keyboard Accessibility)
  const bindVerdictAction = (cardEl, action) => {
    if (!cardEl) return;
    cardEl.addEventListener("click", action);
    cardEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        action();
      }
    });
  };

  bindVerdictAction(els.verdictCardClients, () => {
    els.topClientSelect?.focus();
    showToast("Selected Global Client Filter");
  });
  bindVerdictAction(els.verdictCardPending, () => {
    document.querySelector("#commitmentPanel")?.scrollIntoView({ behavior: "smooth" });
  });
  bindVerdictAction(els.verdictCardMeetings, () => {
    els.rawNotes?.focus();
  });
  bindVerdictAction(els.verdictCardRisks, () => {
    document.querySelector("#day4Panel")?.scrollIntoView({ behavior: "smooth" });
  });

  els.confirmClient?.addEventListener("click", () =>
    withLoading(els.confirmClient, "Confirming…", () => confirmClient()).catch((err) => showToast(err.message, true))
  );
  els.loadSelectedMemory?.addEventListener("click", () =>
    withLoading(els.loadSelectedMemory, "Loading…", () => loadMemory()).catch((err) => showToast(err.message, true))
  );
  els.saveTranscriptBtn?.addEventListener("click", () =>
    withLoading(els.saveTranscriptBtn, "Saving...", () => saveTranscript()).catch((err) => {
      showToast(err.message, true);
      if (els.editTranscriptPanel) els.editTranscriptPanel.classList.remove("hidden");
      if (els.processResult) {
        els.processResult.innerHTML = '<span class="muted">Reprocessing failed. Please try again.</span>';
      }
    })
  );

  // Commitments
  els.commitmentFilter?.addEventListener("change", () =>
    loadCommitments().catch((err) => showToast(err.message, true))
  );
  els.commitmentRows?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-commitment-id]");
    if (!button) return;
    updateCommitmentStatus(Number(button.dataset.commitmentId), button.dataset.nextStatus).catch((err) =>
      showToast(err.message, true)
    );
  });

  // Ask AI
  let askAiRec = null;
  let isAskAiListening = false;
  const askClientVoiceBtn = document.querySelector('#askClientVoiceBtn');
  
  if ('webkitSpeechRecognition' in window) {
    askAiRec = new webkitSpeechRecognition();
    askAiRec.continuous = false;
    askAiRec.interimResults = false;
    askAiRec.lang = 'en-IN';
    
    const stopListeningUI = () => {
      isAskAiListening = false;
      if (els.askClientInput) els.askClientInput.placeholder = 'Ask AI about this client...';
      if (askClientVoiceBtn) askClientVoiceBtn.style.color = '';
    };

    askAiRec.onresult = (e) => {
      if (els.askClientInput) {
        els.askClientInput.value = e.results[0][0].transcript;
        els.askClientBtn?.click();
      }
      stopListeningUI();
    };
    
    askAiRec.onerror = (e) => {
      console.error("Speech recognition error:", e.error);
      if (e.error !== "no-speech") {
        showToast(`Voice recognition error: ${e.error}`, true);
      }
      stopListeningUI();
    };
    
    askAiRec.onend = () => {
      stopListeningUI();
    };
  }

  if (askClientVoiceBtn) {
    askClientVoiceBtn.addEventListener('click', () => {
      if (askAiRec) {
        if (isAskAiListening) {
          askAiRec.stop();
          return;
        }
        try {
          if (els.askClientInput) {
            els.askClientInput.value = '';
            els.askClientInput.placeholder = 'Listening...';
          }
          askClientVoiceBtn.style.color = 'var(--danger)';
          isAskAiListening = true;
          askAiRec.start();
        } catch (err) {
          console.warn("Speech API start error:", err);
          isAskAiListening = false;
          if (els.askClientInput) els.askClientInput.placeholder = 'Ask AI about this client...';
          askClientVoiceBtn.style.color = '';
        }
      } else {
        showToast('Voice recognition is not supported in this browser. Please use Chrome or Edge.', true);
      }
    });
  }

  els.askClientBtn?.addEventListener("click", () =>
    withLoading(els.askClientBtn, "Asking…", () => askClient()).catch((err) => showToast(err.message, true))
  );
  els.askClientInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") els.askClientBtn?.click();
  });

  // Settings
  els.settingsBtn?.addEventListener("click", openSettings);
  els.closeSettingsBtn?.addEventListener("click", closeSettings);
  els.saveSettingsBtn?.addEventListener("click", () =>
    withLoading(els.saveSettingsBtn, "Saving…", () => saveSettings())
  );
  els.deleteAccountBtn?.addEventListener("click", async () => {
    if (window.confirm("Are you sure you want to permanently delete your account? This action cannot be undone.")) {
      try {
        const btn = els.deleteAccountBtn;
        btn.disabled = true;
        btn.textContent = "Deleting...";
        await api("/api/v1/auth/me", { method: "DELETE" });
        showToast("Account deleted successfully.", true);
        setTimeout(() => { window.location.href = "/"; }, 1000);
      } catch (err) {
        showToast(`Failed to delete account: ${err.message}`, true);
        els.deleteAccountBtn.disabled = false;
        els.deleteAccountBtn.textContent = "Permanently Delete Account";
      }
    }
  });
  els.settingsModal?.addEventListener("click", (e) => {
    if (e.target === els.settingsModal) closeSettings();
  });

  // Audio Upload UI Tabs
  els.tabTextBtn?.addEventListener("click", () => {
    els.tabTextBtn.classList.add("active");
    els.tabAudioBtn?.classList.remove("active");
    document.getElementById("tabLiveBtn")?.classList.remove("active");
    document.getElementById("tabFastDictationBtn")?.classList.remove("active");

    if (els.viewText) {
      els.viewText.classList.add("active");
      els.viewText.classList.remove("hidden");
      els.viewText.style.display = "";
    }
    if (els.viewAudio) {
      els.viewAudio.classList.remove("active");
      els.viewAudio.classList.add("hidden");
    }
    const viewLive = document.getElementById("viewLive");
    if (viewLive) viewLive.style.display = "none";
    const viewFastDictation = document.getElementById("viewFastDictation");
    if (viewFastDictation) viewFastDictation.style.display = "none";
  });

  els.tabAudioBtn?.addEventListener("click", () => {
    els.tabAudioBtn.classList.add("active");
    els.tabTextBtn?.classList.remove("active");
    document.getElementById("tabLiveBtn")?.classList.remove("active");
    document.getElementById("tabFastDictationBtn")?.classList.remove("active");

    if (els.viewAudio) {
      els.viewAudio.classList.add("active");
      els.viewAudio.classList.remove("hidden");
      els.viewAudio.style.display = "";
    }
    if (els.viewText) {
      els.viewText.classList.remove("active");
      els.viewText.classList.add("hidden");
    }
    const viewLive = document.getElementById("viewLive");
    if (viewLive) viewLive.style.display = "none";
    const viewFastDictation = document.getElementById("viewFastDictation");
    if (viewFastDictation) viewFastDictation.style.display = "none";
  });

  const tabLiveBtn = document.getElementById("tabLiveBtn");
  if (tabLiveBtn) {
    tabLiveBtn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      tabLiveBtn.classList.add("active");
      if (els.viewText) {
        els.viewText.classList.remove("active");
        els.viewText.classList.add("hidden");
        els.viewText.style.display = "none";
      }
      if (els.viewAudio) {
        els.viewAudio.classList.remove("active");
        els.viewAudio.classList.add("hidden");
        els.viewAudio.style.display = "none";
      }
      const viewFastDictation = document.getElementById("viewFastDictation");
      if (viewFastDictation) viewFastDictation.style.display = "none";
      const viewLive = document.getElementById("viewLive");
      if (viewLive) {
        viewLive.classList.remove("hidden");
        viewLive.style.display = "block";
      }
    });
  }

  const tabFastDictationBtn = document.getElementById("tabFastDictationBtn");
  if (tabFastDictationBtn) {
    tabFastDictationBtn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      tabFastDictationBtn.classList.add("active");
      if (els.viewText) {
        els.viewText.classList.remove("active");
        els.viewText.classList.add("hidden");
        els.viewText.style.display = "none";
      }
      if (els.viewAudio) {
        els.viewAudio.classList.remove("active");
        els.viewAudio.classList.add("hidden");
        els.viewAudio.style.display = "none";
      }
      const viewLive = document.getElementById("viewLive");
      if (viewLive) viewLive.style.display = "none";
      const viewFastDictation = document.getElementById("viewFastDictation");
      if (viewFastDictation) {
        viewFastDictation.classList.remove("hidden");
        viewFastDictation.style.display = "block";
      }
    });
  }

  // Audio File Selection & Drag-Drop
  els.audioFileInput?.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) {
      els.uploadFileName.textContent = file.name;
      els.processAudio.disabled = false;
    } else {
      els.uploadFileName.textContent = "Click to select audio file";
      els.processAudio.disabled = true;
    }
  });

  if (els.uploadBox) {
    ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
      els.uploadBox.addEventListener(
        eventName,
        (e) => {
          e.preventDefault();
          e.stopPropagation();
        },
        false
      );
    });
    ["dragenter", "dragover"].forEach((eventName) => {
      els.uploadBox.addEventListener(eventName, () => els.uploadBox.classList.add("dragover"), false);
    });
    ["dragleave", "drop"].forEach((eventName) => {
      els.uploadBox.addEventListener(eventName, () => els.uploadBox.classList.remove("dragover"), false);
    });
    els.uploadBox.addEventListener("drop", (e) => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files.length > 0 && els.audioFileInput) {
        els.audioFileInput.files = files;
        els.audioFileInput.dispatchEvent(new Event("change"));
      }
    });
  }

  els.processAudio?.addEventListener("click", () => {
    processAudio().catch((err) => {
      showToast(err.message, true);
      if (els.processAudio) {
        els.processAudio.disabled = false;
        els.processAudio.textContent = "Upload & Process";
      }
      if (els.audioStatusBox) els.audioStatusBox.classList.add("hidden");
    });
  });

  // Live Recording Buttons
  document.getElementById("startSoloBtn")?.addEventListener("click", () => startLiveRecording(false));
  document.getElementById("startMeetingBtn")?.addEventListener("click", () => startLiveRecording(true));
  document.getElementById("stopLiveBtn")?.addEventListener("click", () => stopLiveRecording());
  els.tabFastDictationBtn?.addEventListener("click", () => switchTab("tabFastDictationBtn", "viewFastDictation"));

  // Sidebar Toggles
  const handleSidebarToggle = () => {
    if (window.innerWidth <= 768) {
      document.body.classList.toggle("mobile-sidebar-open");
    } else {
      document.querySelector(".mfd-layout")?.classList.toggle("sidebar-collapsed");
    }
  };
  document.getElementById("sidebarToggleBtn")?.addEventListener("click", handleSidebarToggle);
  document.getElementById("logoToggleBtn")?.addEventListener("click", handleSidebarToggle);

  document.getElementById("mobileNavToggleBtn")?.addEventListener("click", () => {
    document.body.classList.toggle("mobile-sidebar-open");
  });

  // Ensure mobile backdrop exists and dismisses sidebar on tap
  let mobileBackdrop = document.getElementById("mobileSidebarBackdrop");
  if (!mobileBackdrop) {
    mobileBackdrop = document.createElement("div");
    mobileBackdrop.id = "mobileSidebarBackdrop";
    mobileBackdrop.className = "mobile-backdrop";
    document.body.appendChild(mobileBackdrop);
  }
  mobileBackdrop.addEventListener("click", () => {
    document.body.classList.remove("mobile-sidebar-open");
  });

  // ===== MOBILE BOTTOM NAV TAB SWITCHING =====
  const setupMobileBottomNav = () => {
    const bnavBtns = document.querySelectorAll(".mfd-bnav-btn");

    const switchMobileTab = (tabName) => {
      const tabSections = document.querySelectorAll(".mfd-tab-section");
      bnavBtns.forEach(b => b.classList.toggle("active", b.dataset.tab === tabName));
      tabSections.forEach(s => s.classList.toggle("active", s.dataset.tab === tabName));
      document.querySelector(".mfd-main")?.scrollTo({ top: 0, behavior: "smooth" });
    };

    bnavBtns.forEach(btn => {
      btn.addEventListener("click", () => switchMobileTab(btn.dataset.tab));
    });

    // On resize to desktop: remove active class so all sections show normally
    window.addEventListener("resize", () => {
      if (window.innerWidth > 768) {
        document.querySelectorAll(".mfd-tab-section").forEach(s => {
          // On desktop, all sections should be visible (no active hiding)
          s.style.display = "";
        });
      }
    });
  };
  setupMobileBottomNav();


  // Theme Toggle
  els.themeToggleBtn?.addEventListener("click", () => {
    document.documentElement.classList.toggle("dark-theme");
    const isDark = document.documentElement.classList.contains("dark-theme");
    localStorage.setItem("theme", isDark ? "dark" : "light");
    els.themeToggleBtn.innerHTML = isDark ? '<span class="icon">🌙</span> Toggle Theme' : '<span class="icon">☀️</span> Toggle Theme';
  });

  // Avatar Dropdown Toggle Logic
  if (els.avatarBtn && els.avatarMenu) {
    els.avatarBtn.addEventListener("click", (e) => {
      e.stopPropagation(); // Prevent document click from immediately closing it
      const isHidden = els.avatarMenu.classList.contains("hidden");
      els.avatarMenu.classList.toggle("hidden", !isHidden);
      els.avatarBtn.setAttribute("aria-expanded", isHidden ? "true" : "false");
    });
  }

  // Close avatar dropdown when clicking outside
  document.addEventListener("click", (e) => {
    if (
      els.avatarMenu && 
      !els.avatarMenu.classList.contains("hidden") &&
      els.avatarDropdownContainer &&
      !els.avatarDropdownContainer.contains(e.target)
    ) {
      els.avatarMenu.classList.add("hidden");
      if (els.avatarBtn) {
        els.avatarBtn.setAttribute("aria-expanded", "false");
      }
    }
  });

  // Handle URL Query Deep Links (e.g. Email verification, reset password, workspace invite tokens)
  handleUrlDeepLinks();
}

function handleUrlDeepLinks() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");
  const action = params.get("action");

  if (action === "verify-email" || (token && !action && window.location.pathname.includes("verify"))) {
    if (token) {
      if (els.verifyTokenInput) els.verifyTokenInput.value = token;
      api(`/api/v1/auth/verify-email?token=${encodeURIComponent(token)}`, { method: "POST" })
        .then(() => {
          showToast("Email verified successfully! You can now log in.");
          showAuthOverlay("login");
        })
        .catch((err) => {
          showAuthOverlay("verify-email");
          showAuthError(els.verifyMessage, err.message);
        });
    } else {
      showAuthOverlay("verify-email");
    }
  } else if (action === "reset-password" || (token && !action && window.location.pathname.includes("reset"))) {
    showAuthOverlay("reset-password");
    if (els.resetTokenInput && token) els.resetTokenInput.value = token;
  } else if (action === "invite-accept" || action === "invite accept" || params.get("invite")) {
    const inviteToken = token || params.get("invite");
    showAuthOverlay("invite-accept");
    if (els.inviteTokenInput && inviteToken) els.inviteTokenInput.value = inviteToken;
  }
}

// --- Dynamic Copilot Token Budget Counter ---
function updateCopilotTokenBudget(additionalTokens = 0) {
  state.copilotTokensUsed = Math.min(state.copilotMaxTokens, (state.copilotTokensUsed || 1420) + additionalTokens);
  const formattedUsed = Number(state.copilotTokensUsed).toLocaleString();
  const formattedMax = Number(state.copilotMaxTokens).toLocaleString();
  const pct = Math.min(100, Math.max(5, Math.round((state.copilotTokensUsed / state.copilotMaxTokens) * 100)));
  if (els.copilotTokenText) {
    els.copilotTokenText.textContent = `${formattedUsed} / ${formattedMax}`;
  }
  if (els.copilotTokenFill) {
    els.copilotTokenFill.style.width = `${pct}%`;
  }
}

// --- Persistent Copilot Sidecar Dock Controller (Recommendation 5) ---
function toggleCopilotSidecar(forceOpen) {
  const sidecar = els.copilotSidecar;
  if (!sidecar) return;
  const isCurrentlyOpen = document.body.dataset.sidecarOpen === "true" || sidecar.classList.contains("open");
  const willOpen = typeof forceOpen === "boolean" ? forceOpen : !isCurrentlyOpen;

  document.body.dataset.sidecarOpen = willOpen ? "true" : "false";
  sidecar.classList.toggle("open", willOpen);

  if (willOpen) {
    // Update Grounded Client Dossier Context
    const clientName = state.selectedClientId ? clientNameById(state.selectedClientId) : "All Portfolio Clients";
    if (els.copilotGroundedClient) {
      els.copilotGroundedClient.textContent = clientName;
    }
    // Update token budget display with grounding context
    updateCopilotTokenBudget(0);
    // Automatically focus prompt input
    window.setTimeout(() => els.copilotInput?.focus(), 100);
  }
}
window.toggleCopilotSidecar = toggleCopilotSidecar;

function initCopilot() {
  els.topbarCopilotBtn?.addEventListener("click", () => toggleCopilotSidecar());
  els.openCopilotBtn?.addEventListener("click", () => toggleCopilotSidecar());
  els.closeCopilotBtn?.addEventListener("click", () => toggleCopilotSidecar(false));

  async function sendCopilotMessage() {
    if (!els.copilotInput || !els.copilotMessages) return;
    const text = els.copilotInput.value.trim();
    if (!text) return;

    // Track estimated user query tokens
    const queryTokens = Math.ceil(text.length / 3.8);
    updateCopilotTokenBudget(queryTokens);

    // Add user bubble
    const userMsg = document.createElement("div");
    userMsg.className = "chat-bubble user-bubble";
    userMsg.textContent = text;
    els.copilotMessages.appendChild(userMsg);
    
    els.copilotInput.value = "";
    els.copilotMessages.scrollTop = els.copilotMessages.scrollHeight;

    // AI thinking indicator
    const aiLoadingMsg = document.createElement("div");
    aiLoadingMsg.className = "chat-bubble ai-bubble";
    aiLoadingMsg.innerHTML = '<span class="loading-dots">Thinking...</span>';
    els.copilotMessages.appendChild(aiLoadingMsg);
    els.copilotMessages.scrollTop = els.copilotMessages.scrollHeight;

    try {
      const data = await api("/api/v1/dashboard/copilot/ask", {
        method: "POST",
        body: JSON.stringify({ query: text, chat_history: [] }),
      });

      const answerTokens = Math.ceil((data.answer || "").length / 3.8);
      updateCopilotTokenBudget(answerTokens);

      aiLoadingMsg.textContent = data.answer;

      if (data.source_type === "sql") {
        aiLoadingMsg.innerHTML += '<br><small style="color:var(--muted);font-size:10px;">✨ Generated via Database Search</small>';
      } else if (data.source_type === "vector") {
        aiLoadingMsg.innerHTML += '<br><small style="color:var(--muted);font-size:10px;">✨ Generated via Vector Search</small>';
      }
    } catch (e) {
      aiLoadingMsg.textContent = "Error connecting to copilot: " + e.message;
    }
    els.copilotMessages.scrollTop = els.copilotMessages.scrollHeight;
  }

  els.sendCopilotBtn?.addEventListener("click", sendCopilotMessage);
  els.copilotInput?.addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendCopilotMessage();
  });
}

// --- App Boot Lifecycle ---
async function init() {
  try {
    if (els.meetingDate) els.meetingDate.value = todayIso();
    if (els.meetingDateAudio) els.meetingDateAudio.value = todayIso();

    // Load saved theme
    const savedTheme = localStorage.getItem("theme");
    if (savedTheme === "dark") {
      document.documentElement.classList.add("dark-theme");
      if (els.themeToggleBtn) {
        els.themeToggleBtn.innerHTML = '<span class="icon">🌙</span> Toggle Theme';
      }
    }

    // Tablet initial panel setup (< 1024px)
    const syncTabletView = () => {
      if (window.innerWidth < 1024) {
        const isDiffActive = els.tabMobileDiffs?.classList.contains("active");
        if (isDiffActive) {
          if (els.diffWorkbench) els.diffWorkbench.classList.remove("tablet-hidden");
          if (els.notePanel) els.notePanel.classList.add("tablet-hidden");
        } else {
          if (els.tabMobileIntake) els.tabMobileIntake.classList.add("active");
          if (els.diffWorkbench) els.diffWorkbench.classList.add("tablet-hidden");
          if (els.notePanel) els.notePanel.classList.remove("tablet-hidden");
        }
      } else {
        if (els.diffWorkbench) els.diffWorkbench.classList.remove("tablet-hidden");
        if (els.notePanel) els.notePanel.classList.remove("tablet-hidden");
      }
    };

    syncTabletView();
    window.addEventListener("resize", syncTabletView);

    updateCopilotTokenBudget(0);
    bindEvents();
    initCopilot();
    await bootstrapSession();
  } finally {
    // ALWAYS reveal the app — no matter what error occurs, screen will never stay dark
    revealApp();
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

// Initialize audio upload capability check
async function bootstrapApp() {
  try {
    const res = await fetch('/health');
    const health = await res.json();
    if (health && health.enable_audio_upload === false) {
      const tabBtn = document.getElementById('tabAudioBtn');
      if (tabBtn) tabBtn.style.display = 'none';
      const viewAudio = document.getElementById('viewAudio');
      if (viewAudio) viewAudio.style.display = 'none';
    }
  } catch (e) {
    console.error("Failed to load app config:", e);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootstrapApp);
} else {
  bootstrapApp();
}

// Handle Google SSO
async function handleGoogleCredentialResponse(response) {
  try {
    const res = await fetch("/api/v1/auth/google", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ id_token: response.credential })
    });
    const data = await res.json();
    if (!res.ok) {
      showAuthError(document.getElementById("loginError"), data.detail || "Google Sign-In failed.");
      return;
    }
    await bootstrapSession();
  } catch (err) {
    console.error(err);
    showAuthError(document.getElementById("loginError"), "A network error occurred during Google Sign-In.");
  }
}
window.handleGoogleCredentialResponse = handleGoogleCredentialResponse;

// --- Client Profile Logic ---
let currentProfileClientId = null;

function openClientProfile() {
  if (!state.selectedClientId) return;
  currentProfileClientId = state.selectedClientId;
  
  if (els.clientProfileModal) els.clientProfileModal.classList.remove("hidden");
  
  const client = state.clients.find(c => c.id === currentProfileClientId);
  if (client) {
    document.getElementById("clientProfileModalTitle").textContent = client.name + " - Profile";
  }
  
  fetchClientDetails(currentProfileClientId);
  fetchClientCommunications(currentProfileClientId);
}

function closeClientProfile() {
  if (els.clientProfileModal) els.clientProfileModal.classList.add("hidden");
  currentProfileClientId = null;
}

async function fetchClientDetails(clientId) {
  try {
    const res = await api(`/api/v1/clients/${clientId}`);
    if (els.profileWhatsapp) els.profileWhatsapp.value = res.whatsapp_phone || "";
    if (els.profileEmail) els.profileEmail.value = res.email || "";
  } catch (err) {
    console.error("Failed to fetch client details", err);
  }
}

async function fetchClientCommunications(clientId) {
  if (!els.communicationFeed) return;
  els.communicationFeed.innerHTML = '<div class="empty-state">Loading history...</div>';
  try {
    const logs = await api(`/api/v1/clients/${clientId}/communications`);
    if (!logs || logs.length === 0) {
      els.communicationFeed.innerHTML = '<div class="empty-state">No communication history found.</div>';
      return;
    }
    
    els.communicationFeed.innerHTML = logs.map(log => {
      const date = new Date(log.created_at).toLocaleString();
      return `
        <div class="comm-log-item">
          <div class="comm-log-header">
            <span class="comm-log-channel ${log.channel}">${log.channel}</span>
            <span>${date}</span>
            <span class="comm-log-status ${log.status}">${log.status}</span>
          </div>
          <div class="comm-log-content">${escapeHtml(log.message_content)}</div>
          ${log.error_message ? `<div style="color:#dc2626; font-size:12px; margin-top:5px;">Error: ${escapeHtml(log.error_message)}</div>` : ''}
        </div>
      `;
    }).join('');
  } catch (err) {
    els.communicationFeed.innerHTML = '<div class="empty-state" style="color:#dc2626;">Failed to load history.</div>';
    console.error(err);
  }
}

async function saveClientContactInfo() {
  if (!currentProfileClientId) return;
  const payload = {
    whatsapp_phone: els.profileWhatsapp.value.trim() || null,
    email: els.profileEmail.value.trim() || null
  };
  
  try {
    els.saveClientContactBtn.disabled = true;
    els.saveClientContactBtn.textContent = "Saving...";
    
    await api(`/api/v1/clients/${currentProfileClientId}`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
    
    showToast("Contact info updated successfully.");
    if (els.profileContactMsg) els.profileContactMsg.classList.add("hidden");
    
    // Update local state if needed
    const client = state.clients.find(c => c.id === currentProfileClientId);
    if (client) {
      client.whatsapp_phone = payload.whatsapp_phone;
      client.email = payload.email;
    }
  } catch (err) {
    if (els.profileContactMsg) {
      els.profileContactMsg.textContent = err.message || "Failed to update contact info.";
      els.profileContactMsg.classList.remove("hidden");
      els.profileContactMsg.classList.add("error");
    }
  } finally {
    els.saveClientContactBtn.disabled = false;
    els.saveClientContactBtn.textContent = "Save Contact Info";
  }
}

els.viewClientProfileBtn?.addEventListener("click", openClientProfile);
els.closeClientProfileBtn?.addEventListener("click", closeClientProfile);
els.saveClientContactBtn?.addEventListener("click", saveClientContactInfo);

// Update visibility logic for View Profile Button
els.topClientSelect?.addEventListener("change", (e) => {
    const show = !!state.selectedClientId;
    if (els.viewClientProfileBtn) {
        els.viewClientProfileBtn.style.display = show ? "flex" : "none";
    }
});
