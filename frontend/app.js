(function () {
  const STORAGE_TOKEN_KEY = "bookflow.token";
  const STORAGE_USER_ID_KEY = "bookflow.user_id";
  const STORAGE_USERNAME_KEY = "bookflow.username";
  const STORAGE_DEVICE_ID_KEY = "bookflow.device_id";
  const SESSION_ID_KEY = "bookflow.session_id";
  const INTERACTION_BUMP_KEY = "bookflow.interaction.bump.v1";
  const INTERACTION_BUMP_CHANNEL = "bookflow.interaction.bump.channel.v1";
  const FLASH_TOAST_KEY = "bookflow.toast.flash.v1";
  let toastLayerEl = null;
  let toastHideTimer = 0;

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
    escapeHtml,
    makeFeedReaderUrl,
    makeBookUrl,
  };
})();
