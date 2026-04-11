(function () {
  const STORAGE_TOKEN_KEY = "bookflow.token";
  const STORAGE_USER_ID_KEY = "bookflow.user_id";
  const STORAGE_USERNAME_KEY = "bookflow.username";
  const STORAGE_DEVICE_ID_KEY = "bookflow.device_id";
  const SESSION_ID_KEY = "bookflow.session_id";
  const INTERACTION_BUMP_KEY = "bookflow.interaction.bump.v1";
  const INTERACTION_BUMP_CHANNEL = "bookflow.interaction.bump.channel.v1";
  const FLASH_TOAST_KEY = "bookflow.toast.flash.v1";
  const PWA_SW_URL = "/app/sw.js";
  const PWA_SW_SCOPE = "/app/";
  const PWA_SPLASH_SESSION_KEY = "bookflow.pwa.splash.v1";
  const PWA_SPLASH_MIN_MS = 560;
  const PWA_SPLASH_MAX_MS = 1400;
  let toastLayerEl = null;
  let toastHideTimer = 0;
  let pwaBooted = false;
  let pwaSwRegisterStarted = false;
  let pwaInstallPromptEvent = null;
  let pwaSplashClosing = false;
  const pwaInstallButtons = new Set();

  function getStoredToken() {
    return String(window.localStorage.getItem(STORAGE_TOKEN_KEY) || "").trim();
  }

  function getStoredUserId() {
    const raw = String(window.localStorage.getItem(STORAGE_USER_ID_KEY) || "").trim();
    return isUuidLike(raw) ? raw : "";
  }

  function getStoredUsername() {
    return String(window.localStorage.getItem(STORAGE_USERNAME_KEY) || "").trim();
  }

  function saveConfig(token, userId) {
    const cleanToken = String(token || "").trim();
    const candidateUserId = String(userId || "").trim();
    const cleanUserId = isUuidLike(candidateUserId) ? candidateUserId : getStoredUserId();
    if (cleanToken) {
      window.localStorage.setItem(STORAGE_TOKEN_KEY, cleanToken);
    } else {
      window.localStorage.removeItem(STORAGE_TOKEN_KEY);
    }
    if (cleanUserId) {
      window.localStorage.setItem(STORAGE_USER_ID_KEY, cleanUserId);
    } else {
      window.localStorage.removeItem(STORAGE_USER_ID_KEY);
    }
    return { token: cleanToken, userId: cleanUserId };
  }

  function isLoggedIn() {
    const token = getStoredToken();
    const userId = getStoredUserId();
    return !!token && isUuidLike(userId);
  }

  function setAuthSession(input) {
    const src = input && typeof input === "object" ? input : {};
    const token = String(src.token || "").trim();
    const userId = String(src.user_id || src.userId || "").trim();
    const username = String(src.username || src.user_name || src.userName || "").trim();
    if (!token || !isUuidLike(userId)) {
      return false;
    }
    window.localStorage.setItem(STORAGE_TOKEN_KEY, token);
    window.localStorage.setItem(STORAGE_USER_ID_KEY, userId);
    if (username) {
      window.localStorage.setItem(STORAGE_USERNAME_KEY, username);
    } else {
      window.localStorage.removeItem(STORAGE_USERNAME_KEY);
    }
    return true;
  }

  function clearAuthSession() {
    window.localStorage.removeItem(STORAGE_TOKEN_KEY);
    window.localStorage.removeItem(STORAGE_USER_ID_KEY);
    window.localStorage.removeItem(STORAGE_USERNAME_KEY);
  }

  function parseQuery() {
    const out = {};
    const url = new URL(window.location.href);
    for (const [key, value] of url.searchParams.entries()) {
      out[key] = value;
    }
    return out;
  }

  function isUuidLike(value) {
    const text = String(value || "").trim();
    // 仅校验 UUID 字符串形态（8-4-4-4-12），不强制版本/variant 位，
    // 以兼容本地默认 user_id（1111...）等历史数据。
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(text);
  }

  function fallbackUuid() {
    const rand = Math.random().toString(16).slice(2).padEnd(12, "0").slice(0, 12);
    return `00000000-0000-4000-8000-${rand}`;
  }

  function makeUuid() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return fallbackUuid();
  }

  function getSessionId() {
    const existing = window.sessionStorage.getItem(SESSION_ID_KEY);
    if (existing) {
      return existing;
    }
    const next = `s_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
    window.sessionStorage.setItem(SESSION_ID_KEY, next);
    return next;
  }

  function getDeviceId() {
    const existing = window.localStorage.getItem(STORAGE_DEVICE_ID_KEY);
    if (existing) {
      return existing;
    }
    const next = `d_${Math.random().toString(16).slice(2, 14)}`;
    window.localStorage.setItem(STORAGE_DEVICE_ID_KEY, next);
    return next;
  }

  function isLoginPath(pathname) {
    const path = String(pathname || "").trim();
    return path === "/app/login" || path === "/app/login/" || path === "/app/login.html";
  }

  function setQuery(next) {
    const url = new URL(window.location.href);
    Object.keys(next || {}).forEach((key) => {
      const value = next[key];
      if (value === null || value === undefined || value === "") {
        url.searchParams.delete(key);
      } else {
        url.searchParams.set(key, String(value));
      }
    });
    window.history.replaceState({}, "", url.toString());
  }

  async function apiFetch(path, options) {
    const cfg = options || {};
    const token = cfg.token !== undefined ? String(cfg.token || "").trim() : getStoredToken();
    const deviceId = getDeviceId();
    const headers = {};
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    if (deviceId) {
      headers["X-BookFlow-Device-ID"] = deviceId;
    }
    if (cfg.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    const resp = await window.fetch(path, {
      method: cfg.method || "GET",
      headers,
      body: cfg.body !== undefined ? JSON.stringify(cfg.body) : undefined,
    });
    let payload;
    try {
      payload = await resp.json();
    } catch (e) {
      payload = { error: { code: "INVALID_RESPONSE", message: "non-json response" } };
    }
    if (!resp.ok) {
      if (resp.status === 401) {
        clearAuthSession();
        if (!cfg.skipAuthRedirect && !isLoginPath(window.location.pathname)) {
          const next = encodeURIComponent(`${window.location.pathname}${window.location.search || ""}`);
          window.location.href = `/app/login.html?next=${next}`;
        }
      }
      const err = new Error(payload?.error?.message || `HTTP ${resp.status}`);
      err.status = resp.status;
      err.payload = payload;
      throw err;
    }
    return payload;
  }

  function buildInteractionEvent(input) {
    const src = input || {};
    const eventType = String(src.eventType || "");
    const userId = String(src.userId || "");
    const bookId = String(src.bookId || "");
    const chunkId = String(src.chunkId || "");
    const positionInChunk = Number(src.positionInChunk || 0);
    const payload = src.payload && typeof src.payload === "object" ? src.payload : {};
    const eventTs = new Date().toISOString();
    const eventId = makeUuid();
    const idempotencyKey = [
      "web",
      eventType,
      chunkId || "unknown_chunk",
      Date.now(),
      Math.random().toString(16).slice(2, 10),
    ].join("_");
    return {
      event_id: eventId,
      event_type: eventType,
      event_ts: eventTs,
      user_id: userId,
      session_id: getSessionId(),
      book_id: bookId,
      chunk_id: chunkId,
      position_in_chunk: Number.isFinite(positionInChunk) ? Math.max(0, Math.min(1, positionInChunk)) : 0,
      idempotency_key: idempotencyKey,
      client: {
        platform: "web",
        app_version: "0.2.0-mvp",
        device_id: getDeviceId(),
      },
      payload,
    };
  }

  async function sendInteractionEvents(events, options) {
    const list = Array.isArray(events) ? events : [];
    if (!list.length) {
      return { accepted: 0, deduplicated: 0, rejected: 0, results: [] };
    }
    return apiFetch("/v1/interactions", {
      method: "POST",
      body: { events: list },
      token: options?.token,
    });
  }

  async function authLogin(username, password) {
    const payload = await apiFetch("/v1/auth/login", {
      method: "POST",
      token: "",
      skipAuthRedirect: true,
      body: {
        username: String(username || "").trim(),
        password: String(password || ""),
        device_id: getDeviceId(),
      },
    });
    setAuthSession(payload);
    return payload;
  }

  async function authSession() {
    return apiFetch("/v1/auth/session", {
      method: "GET",
      skipAuthRedirect: true,
    });
  }

  async function authLogout() {
    try {
      await apiFetch("/v1/auth/logout", {
        method: "POST",
        skipAuthRedirect: true,
      });
    } catch (err) {
      void err;
    }
    clearAuthSession();
  }

  function normalizeCount(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) {
      return 0;
    }
    return Math.max(0, Math.trunc(num));
  }

  function normalizeDelta(value) {
    const num = Number(value || 0);
    if (!Number.isFinite(num)) {
      return 0;
    }
    return Math.trunc(num);
  }

  function publishInteractionDelta(input) {
    const src = input && typeof input === "object" ? input : {};
    const bookId = String(src.bookId || "").trim();
    const chunkId = String(src.chunkId || "").trim();
    if (!bookId || !chunkId) {
      return null;
    }
    const rawDeltas = src.deltas && typeof src.deltas === "object" ? src.deltas : {};
    const deltas = {};
    ["like_count", "comment_count", "complete_count"].forEach((field) => {
      const raw = Number(rawDeltas[field] || 0);
      if (!Number.isFinite(raw) || raw === 0) {
        return;
      }
      deltas[field] = Math.trunc(raw);
    });
    if (!Object.keys(deltas).length) {
      return null;
    }

    const payload = {
      schema: "bookflow.interaction.bump.v1",
      id: `b_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`,
      at: Date.now(),
      source: String(src.source || "web"),
      book_id: bookId,
      chunk_id: chunkId,
      deltas,
    };
    try {
      window.localStorage.setItem(INTERACTION_BUMP_KEY, JSON.stringify(payload));
    } catch (err) {
      void err;
    }
    try {
      if (typeof window.BroadcastChannel === "function") {
        const bc = new window.BroadcastChannel(INTERACTION_BUMP_CHANNEL);
        bc.postMessage(payload);
        bc.close();
      }
    } catch (err) {
      void err;
    }
    return payload;
  }

  function subscribeInteractionDelta(handler) {
    if (typeof handler !== "function") {
      return () => {};
    }

    const invoke = (payload) => {
      if (!payload || typeof payload !== "object") {
        return;
      }
      if (String(payload.schema || "") !== "bookflow.interaction.bump.v1") {
        return;
      }
      const deltas = payload.deltas && typeof payload.deltas === "object" ? payload.deltas : {};
      const next = {
        id: String(payload.id || ""),
        at: Number(payload.at || 0) || 0,
        source: String(payload.source || ""),
        bookId: String(payload.book_id || ""),
        chunkId: String(payload.chunk_id || ""),
        deltas: {
          like_count: normalizeDelta(deltas.like_count),
          comment_count: normalizeDelta(deltas.comment_count),
          complete_count: normalizeDelta(deltas.complete_count),
        },
      };
      if (!next.bookId || !next.chunkId) {
        return;
      }
      if (!(next.deltas.like_count || next.deltas.comment_count || next.deltas.complete_count)) {
        return;
      }
      handler(next);
    };

    const onStorage = (evt) => {
      if (evt.key !== INTERACTION_BUMP_KEY || !evt.newValue) {
        return;
      }
      try {
        invoke(JSON.parse(evt.newValue));
      } catch (err) {
        void err;
      }
    };
    window.addEventListener("storage", onStorage);

    let bc = null;
    let onBroadcast = null;
    try {
      if (typeof window.BroadcastChannel === "function") {
        bc = new window.BroadcastChannel(INTERACTION_BUMP_CHANNEL);
        onBroadcast = (evt) => {
          invoke(evt && evt.data);
        };
        bc.addEventListener("message", onBroadcast);
      }
    } catch (err) {
      void err;
      bc = null;
    }

    return () => {
      window.removeEventListener("storage", onStorage);
      if (bc && onBroadcast) {
        bc.removeEventListener("message", onBroadcast);
        bc.close();
      }
    };
  }

  async function fetchChunkContextBatch(input, options) {
    const src = input || {};
    const chunkIds = Array.isArray(src.chunkIds)
      ? src.chunkIds.map((x) => String(x || "").trim()).filter((x) => x)
      : [];
    if (!chunkIds.length) {
      return { items: [], requested_count: 0, found_count: 0, not_found_chunk_ids: [], trace_id: null };
    }
    const params = new URLSearchParams();
    params.set("chunk_ids", chunkIds.join(","));
    if (src.bookId) {
      params.set("book_id", String(src.bookId));
    }
    if (src.cacheStats) {
      params.set("cache_stats", "1");
    }
    if (src.cacheReset) {
      params.set("cache_reset", "1");
    }
    return apiFetch(`/v1/chunk_context_batch?${params.toString()}`, { token: options?.token });
  }

  function normalizeToastType(raw) {
    const text = String(raw || "").trim().toLowerCase();
    if (text === "error") {
      return "error";
    }
    if (text === "info") {
      return "info";
    }
    return "success";
  }

  function normalizeToastDuration(raw, fallback = 1800) {
    const num = Number(raw);
    if (!Number.isFinite(num)) {
      return fallback;
    }
    return Math.max(800, Math.min(8000, Math.trunc(num)));
  }

  function ensureToastLayer() {
    if (toastLayerEl && toastLayerEl.isConnected) {
      return toastLayerEl;
    }
    const layer = window.document.createElement("div");
    layer.className = "toast-layer";
    layer.setAttribute("aria-live", "polite");
    layer.setAttribute("aria-atomic", "true");
    window.document.body.appendChild(layer);
    toastLayerEl = layer;
    return layer;
  }

  function clearToastTimer() {
    if (!toastHideTimer) {
      return;
    }
    window.clearTimeout(toastHideTimer);
    toastHideTimer = 0;
  }

  function showToast(message, options) {
    const text = String(message || "").trim();
    if (!text) {
      return null;
    }
    const cfg = options && typeof options === "object" ? options : {};
    const type = normalizeToastType(cfg.type);
    const duration = normalizeToastDuration(cfg.duration, 1800);
    const layer = ensureToastLayer();

    clearToastTimer();
    layer.innerHTML = "";
    const toast = window.document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");
    toast.textContent = text;
    layer.appendChild(toast);

    window.requestAnimationFrame(() => {
      toast.classList.add("show");
    });

    toastHideTimer = window.setTimeout(() => {
      toast.classList.remove("show");
      window.setTimeout(() => {
        if (toast.parentElement === layer) {
          layer.removeChild(toast);
        }
      }, 180);
    }, duration);
    return toast;
  }

  function setFlashToast(message, options) {
    const text = String(message || "").trim();
    if (!text) {
      return false;
    }
    const cfg = options && typeof options === "object" ? options : {};
    const payload = {
      message: text,
      type: normalizeToastType(cfg.type),
      duration: normalizeToastDuration(cfg.duration, 2000),
      at: Date.now(),
    };
    try {
      window.sessionStorage.setItem(FLASH_TOAST_KEY, JSON.stringify(payload));
      return true;
    } catch (err) {
      void err;
      return false;
    }
  }

  function consumeFlashToast(maxAgeMs = 12000) {
    try {
      const raw = window.sessionStorage.getItem(FLASH_TOAST_KEY);
      window.sessionStorage.removeItem(FLASH_TOAST_KEY);
      if (!raw) {
        return null;
      }
      const payload = JSON.parse(raw);
      if (!payload || typeof payload !== "object") {
        return null;
      }
      const message = String(payload.message || "").trim();
      if (!message) {
        return null;
      }
      const at = Number(payload.at || 0);
      if (Number.isFinite(at) && at > 0 && Date.now() - at > Math.max(1000, Number(maxAgeMs) || 12000)) {
        return null;
      }
      return {
        message,
        type: normalizeToastType(payload.type),
        duration: normalizeToastDuration(payload.duration, 2000),
      };
    } catch (err) {
      void err;
      return null;
    }
  }

  function showFlashToast() {
    const payload = consumeFlashToast();
    if (!payload) {
      return null;
    }
    showToast(payload.message, payload);
    return payload;
  }

  function isStandaloneDisplay() {
    const iosStandalone = window.navigator && window.navigator.standalone === true;
    const mediaStandalone = typeof window.matchMedia === "function"
      ? window.matchMedia("(display-mode: standalone)").matches
      : false;
    return iosStandalone || mediaStandalone;
  }

  function currentAppRouteClass() {
    const path = String(window.location && window.location.pathname ? window.location.pathname : "");
    if (path === "/app" || path === "/app/" || path === "/" || path === "/app/feed") {
      return "app-route-feed";
    }
    if (path === "/app/reader" || path === "/app/reader.html") {
      return "app-route-reader";
    }
    if (path === "/app/book" || path === "/app/book.html") {
      return "app-route-book";
    }
    if (path === "/app/toc" || path === "/app/toc.html") {
      return "app-route-toc";
    }
    if (path === "/app/login" || path === "/app/login/" || path === "/app/login.html") {
      return "app-route-login";
    }
    return "app-route-generic";
  }

  function applyDisplayModeClasses() {
    const root = window.document.documentElement;
    const body = window.document.body;
    if (!(root instanceof HTMLElement)) {
      return;
    }
    const standalone = isStandaloneDisplay();
    root.classList.toggle("app-standalone", standalone);
    root.classList.toggle("app-browser", !standalone);
    if (body instanceof HTMLElement) {
      body.classList.toggle("app-standalone", standalone);
      body.classList.toggle("app-browser", !standalone);
      [
        "app-route-feed",
        "app-route-reader",
        "app-route-book",
        "app-route-toc",
        "app-route-login",
        "app-route-generic",
      ].forEach((name) => body.classList.remove(name));
      body.classList.add(currentAppRouteClass());
    }
  }

  function shouldShowPwaSplash() {
    if (!isStandaloneDisplay()) {
      return false;
    }
    try {
      if (window.sessionStorage.getItem(PWA_SPLASH_SESSION_KEY) === "1") {
        return false;
      }
    } catch (err) {
      void err;
    }
    try {
      const nav = window.performance && typeof window.performance.getEntriesByType === "function"
        ? window.performance.getEntriesByType("navigation")[0]
        : null;
      if (nav && String(nav.type || "") === "back_forward") {
        return false;
      }
    } catch (err) {
      void err;
    }
    return true;
  }

  function markPwaSplashSeen() {
    try {
      window.sessionStorage.setItem(PWA_SPLASH_SESSION_KEY, "1");
    } catch (err) {
      void err;
    }
  }

  function mountPwaSplash() {
    if (!shouldShowPwaSplash()) {
      return;
    }
    const body = window.document.body;
    if (!(body instanceof HTMLElement)) {
      return;
    }
    if (window.document.getElementById("pwaSplashLayer")) {
      return;
    }

    markPwaSplashSeen();
    pwaSplashClosing = false;
    const startedAt = Date.now();
    body.classList.add("pwa-splash-active");

    const splash = window.document.createElement("section");
    splash.id = "pwaSplashLayer";
    splash.className = "pwa-splash";
    splash.setAttribute("role", "status");
    splash.setAttribute("aria-live", "polite");
    splash.innerHTML = [
      '<div class="pwa-splash-card">',
      '  <div class="pwa-splash-logo" aria-hidden="true">BF</div>',
      '  <h1 class="pwa-splash-title">BookFlow</h1>',
      '  <p class="pwa-splash-subtitle">正在进入阅读工作台...</p>',
      "  <div class=\"pwa-splash-loader\" aria-hidden=\"true\"></div>",
      "</div>",
    ].join("");
    body.appendChild(splash);

    const closeSplash = () => {
      if (pwaSplashClosing) {
        return;
      }
      pwaSplashClosing = true;
      splash.classList.add("closing");
      window.setTimeout(() => {
        if (splash.parentElement) {
          splash.parentElement.removeChild(splash);
        }
        body.classList.remove("pwa-splash-active");
      }, 240);
    };

    const settle = () => {
      const elapsed = Date.now() - startedAt;
      const remain = Math.max(0, PWA_SPLASH_MIN_MS - elapsed);
      window.setTimeout(closeSplash, remain);
    };

    if (window.document.readyState === "complete") {
      settle();
    } else {
      window.addEventListener("load", settle, { once: true });
    }
    window.setTimeout(closeSplash, PWA_SPLASH_MAX_MS);
  }

  function isLocalhostHostname(hostname) {
    const text = String(hostname || "").trim().toLowerCase();
    if (!text) {
      return false;
    }
    if (text === "localhost" || text === "[::1]") {
      return true;
    }
    if (/^127(?:\.\d{1,3}){3}$/.test(text)) {
      return true;
    }
    return text.endsWith(".localhost");
  }

  function isPwaSecureContext() {
    if (window.isSecureContext) {
      return true;
    }
    const loc = window.location || {};
    return isLocalhostHostname(loc.hostname);
  }

  function canPromptPwaInstall() {
    return !!pwaInstallPromptEvent;
  }

  function updateInstallButton(button) {
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
    if (isStandaloneDisplay()) {
      button.hidden = false;
      button.disabled = true;
      button.classList.remove("is-ready");
      button.textContent = "已安装";
      return;
    }
    if (!isPwaSecureContext()) {
      button.hidden = false;
      button.disabled = true;
      button.classList.remove("is-ready");
      button.textContent = "需 HTTPS";
      return;
    }
    if (canPromptPwaInstall()) {
      button.hidden = false;
      button.disabled = false;
      button.classList.add("is-ready");
      button.textContent = "安装应用";
      return;
    }
    button.hidden = false;
    button.disabled = false;
    button.classList.remove("is-ready");
    button.textContent = "安装应用";
  }

  function refreshInstallButtons() {
    pwaInstallButtons.forEach((button) => {
      if (!(button instanceof HTMLButtonElement) || !button.isConnected) {
        pwaInstallButtons.delete(button);
        return;
      }
      updateInstallButton(button);
    });
  }

  function bindPwaInstallButton(button) {
    if (!(button instanceof HTMLButtonElement)) {
      return () => {};
    }
    pwaInstallButtons.add(button);
    updateInstallButton(button);

    const onClick = async () => {
      if (isStandaloneDisplay()) {
        showToast("已安装，可从主屏幕直接打开。", { type: "info", duration: 1600 });
        return;
      }
      if (!canPromptPwaInstall()) {
        if (!isPwaSecureContext()) {
          showToast("安装模式需要 HTTPS（或 localhost）。", { type: "info", duration: 2200 });
          return;
        }
        showToast("请稍后再试，或使用浏览器菜单“添加到主屏幕”。", { type: "info", duration: 2200 });
        return;
      }

      const promptEvent = pwaInstallPromptEvent;
      pwaInstallPromptEvent = null;
      refreshInstallButtons();
      try {
        await promptEvent.prompt();
        const choice = await promptEvent.userChoice;
        const accepted = String(choice?.outcome || "") === "accepted";
        if (accepted) {
          showToast("已发起安装。", { type: "success", duration: 1700 });
        } else {
          showToast("已取消安装。", { type: "info", duration: 1400 });
        }
      } catch (err) {
        void err;
        showToast("安装失败，请使用浏览器菜单安装。", { type: "error", duration: 2400 });
      } finally {
        refreshInstallButtons();
      }
    };

    button.addEventListener("click", onClick);
    return () => {
      button.removeEventListener("click", onClick);
      pwaInstallButtons.delete(button);
    };
  }

  function registerServiceWorker() {
    if (pwaSwRegisterStarted) {
      return;
    }
    pwaSwRegisterStarted = true;
    if (!("serviceWorker" in window.navigator)) {
      return;
    }
    if (!isPwaSecureContext()) {
      return;
    }
    const start = () => {
      window.navigator.serviceWorker.register(PWA_SW_URL, { scope: PWA_SW_SCOPE }).catch((err) => {
        console.warn("BookFlow PWA service worker registration failed:", err);
      });
    };
    if (window.document.readyState === "complete") {
      start();
      return;
    }
    window.addEventListener("load", start, { once: true });
  }

  function bootPwa() {
    if (pwaBooted) {
      return;
    }
    pwaBooted = true;

    applyDisplayModeClasses();
    mountPwaSplash();

    window.addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      pwaInstallPromptEvent = event;
      refreshInstallButtons();
    });

    window.addEventListener("appinstalled", () => {
      pwaInstallPromptEvent = null;
      refreshInstallButtons();
      showToast("安装完成，可从主屏幕直接打开。", { type: "success", duration: 2000 });
    });

    if (typeof window.matchMedia === "function") {
      try {
        const mq = window.matchMedia("(display-mode: standalone)");
        const onModeChange = () => {
          applyDisplayModeClasses();
          refreshInstallButtons();
        };
        if (typeof mq.addEventListener === "function") {
          mq.addEventListener("change", onModeChange);
        } else if (typeof mq.addListener === "function") {
          mq.addListener(onModeChange);
        }
      } catch (err) {
        void err;
      }
    }

    registerServiceWorker();
  }

  function initPwa(options) {
    bootPwa();
    const cfg = options && typeof options === "object" ? options : {};
    const button = cfg.installButton instanceof HTMLButtonElement
      ? cfg.installButton
      : (cfg.installButtonId ? window.document.getElementById(String(cfg.installButtonId)) : null);
    if (button instanceof HTMLButtonElement) {
      return bindPwaInstallButton(button);
    }
    refreshInstallButtons();
    return () => {};
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function makeFeedReaderUrl(item, userId) {
    const params = new URLSearchParams();
    params.set("chunk_id", item.chunk_id || "");
    if (item.book_id) {
      params.set("book_id", item.book_id);
    }
    if (userId) {
      params.set("user_id", userId);
    }
    return `/app/reader?${params.toString()}`;
  }

  function makeBookUrl(bookId, userId) {
    const params = new URLSearchParams();
    params.set("book_id", bookId || "");
    if (userId) {
      params.set("user_id", userId);
    }
    return `/app/book?${params.toString()}`;
  }

  window.BookFlowApp = {
    getStoredToken,
    getStoredUserId,
    getStoredUsername,
    getDeviceId,
    saveConfig,
    parseQuery,
    setQuery,
    isUuidLike,
    isLoggedIn,
    setAuthSession,
    clearAuthSession,
    authLogin,
    authSession,
    authLogout,
    apiFetch,
    buildInteractionEvent,
    sendInteractionEvents,
    publishInteractionDelta,
    subscribeInteractionDelta,
    fetchChunkContextBatch,
    showToast,
    setFlashToast,
    consumeFlashToast,
    showFlashToast,
    initPwa,
    escapeHtml,
    makeFeedReaderUrl,
    makeBookUrl,
  };
})();
