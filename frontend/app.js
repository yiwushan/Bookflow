(function () {
  const STORAGE_TOKEN_KEY = "bookflow.token";
  const STORAGE_USER_ID_KEY = "bookflow.user_id";
  const STORAGE_DEVICE_ID_KEY = "bookflow.device_id";
  const SESSION_ID_KEY = "bookflow.session_id";
  const DEFAULT_TOKEN = "local-dev-token";
  const DEFAULT_USER_ID = "11111111-1111-1111-1111-111111111111";

  function getStoredToken() {
    return window.localStorage.getItem(STORAGE_TOKEN_KEY) || DEFAULT_TOKEN;
  }

  function getStoredUserId() {
    const raw = String(window.localStorage.getItem(STORAGE_USER_ID_KEY) || "").trim();
    if (isUuidLike(raw)) {
      return raw;
    }
    window.localStorage.setItem(STORAGE_USER_ID_KEY, DEFAULT_USER_ID);
    return DEFAULT_USER_ID;
  }

  function saveConfig(token, userId) {
    const cleanToken = String(token || "").trim() || DEFAULT_TOKEN;
    const candidateUserId = String(userId || "").trim();
    const cleanUserId = isUuidLike(candidateUserId) ? candidateUserId : DEFAULT_USER_ID;
    window.localStorage.setItem(STORAGE_TOKEN_KEY, cleanToken);
    window.localStorage.setItem(STORAGE_USER_ID_KEY, cleanUserId);
    return { token: cleanToken, userId: cleanUserId };
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
    const token = cfg.token || getStoredToken();
    const headers = {
      Authorization: `Bearer ${token}`,
    };
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
    saveConfig,
    parseQuery,
    setQuery,
    isUuidLike,
    apiFetch,
    buildInteractionEvent,
    sendInteractionEvents,
    fetchChunkContextBatch,
    escapeHtml,
    makeFeedReaderUrl,
    makeBookUrl,
  };
})();
