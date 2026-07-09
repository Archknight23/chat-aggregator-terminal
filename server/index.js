import http from "node:http";
import fs from "node:fs/promises";
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { createHash } from "node:crypto";
import { LiveChat } from "youtube-chat";
import { WebSocket } from "ws";

const port = Number(process.env.YOUTUBE_PROXY_PORT || process.env.PORT || 4174);
const twitchAuthFileUrl = new URL("./.twitch-auth.json", import.meta.url);
const LOG_FILE = process.env.CHAT_AGGREGATOR_LOG || join(process.cwd(), "server", ".chat-aggregator-proxy.log");

// Mirror console.log to a tail-able log file. Stdout still works for dev
// (e.g. `npm run dev:all:https`); the file gives us a persistent record
// that survives `concurrently`'s collector and `kill -9`. Redact obvious
// secrets before writing.
const SECRET_KEYS = /(accessToken|refreshToken|clientSecret|authorization)/i;
function redact(obj) {
  if (obj == null) return obj;
  if (typeof obj === "string") {
    if (obj.length > 24 && /^[A-Za-z0-9_\-]+$/.test(obj)) return obj.slice(0, 6) + "...[redacted]";
    return obj;
  }
  if (Array.isArray(obj)) return obj.map(redact);
  if (typeof obj === "object") {
    const out = {};
    for (const [k, v] of Object.entries(obj)) {
      out[k] = SECRET_KEYS.test(k) ? "[redacted]" : redact(v);
    }
    return out;
  }
  return obj;
}
function logLine(level, ...args) {
  const ts = new Date().toISOString();
  const safeArgs = args.map((a) => (typeof a === "string" ? a : JSON.stringify(redact(a))));
  const line = `${ts} [${level}] ${safeArgs.join(" ")}\n`;
  try {
    appendFileSync(LOG_FILE, line);
  } catch (e) {
    // best-effort; never let logging crash the server
  }
  // Also write to the original console target (preserves dev experience).
  const original = level === "error" ? console.error : console.log;
  original(line.trimEnd());
}
try { mkdirSync(dirname(LOG_FILE), { recursive: true }); } catch {}
logLine("info", `proxy booting pid=${process.pid} port=${port} log=${LOG_FILE}`);

function json(data) {
  return JSON.stringify(data);
}

function send(res, statusCode, body, headers = {}) {
  res.writeHead(statusCode, {
    "Content-Type": "text/plain; charset=utf-8",
    ...headers,
  });
  res.end(body);
}

function sendJson(res, statusCode, data, headers = {}) {
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    ...headers,
  });
  res.end(json(data));
}

async function readJsonBody(req, maxBytes = 200_000) {
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buf.length;
    if (total > maxBytes) {
      throw new Error("body_too_large");
    }
    chunks.push(buf);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return null;
  return JSON.parse(raw);
}

async function readJsonFile(url) {
  try {
    const raw = await fs.readFile(url, "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function writeJsonFile(url, data) {
  await fs.writeFile(url, json(data), "utf8");
}

async function deleteFile(url) {
  try {
    await fs.unlink(url);
  } catch {
    // ignore
  }
}

function compactHttpBody(raw) {
  return String(raw || "")
    .replace(/<[^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 250);
}

function textFromChatItem(chatItem) {
  if (!Array.isArray(chatItem?.message)) return "";
  return chatItem.message
    .map((part) => {
      if (typeof part?.text === "string") return part.text;
      if (typeof part?.emojiText === "string") return part.emojiText;
      if (typeof part?.alt === "string") return part.alt;
      return "";
    })
    .join("");
}

function stableId({ liveId, username, text, timestamp }) {
  const payload = `${liveId}\n${username}\n${timestamp}\n${text}`;
  return createHash("sha1").update(payload).digest("hex");
}

const youtubeVideoIdPattern = /^[a-zA-Z0-9_-]{11}$/;

function extractYoutubeVideoId(input) {
  const raw = String(input || "").trim();
  if (!raw) return null;
  if (youtubeVideoIdPattern.test(raw)) return raw;

  try {
    const url = new URL(raw);
    const host = url.hostname.replace(/^www\./, "");
    if (host === "youtu.be") {
      const id = url.pathname.split("/").filter(Boolean)[0];
      return youtubeVideoIdPattern.test(id || "") ? id : null;
    }

    if (host.endsWith("youtube.com")) {
      const searchId = url.searchParams.get("v");
      if (youtubeVideoIdPattern.test(searchId || "")) return searchId;

      const parts = url.pathname.split("/").filter(Boolean);
      const videoPathIndex = parts.findIndex((part) =>
        ["embed", "live", "shorts"].includes(part)
      );
      if (videoPathIndex >= 0) {
        const id = parts[videoPathIndex + 1];
        return youtubeVideoIdPattern.test(id || "") ? id : null;
      }
    }
  } catch {
    // Not a URL; handled below by channel target normalization.
  }

  const looseMatch = raw.match(/(?:v=|youtu\.be\/|\/(?:embed|live|shorts)\/)([a-zA-Z0-9_-]{11})/);
  return looseMatch?.[1] || null;
}

function youtubeLiveUrlFromTarget(input) {
  const raw = String(input || "").trim();
  if (!raw) return null;

  try {
    const url = new URL(raw);
    const host = url.hostname.replace(/^www\./, "");
    if (!host.endsWith("youtube.com") && host !== "youtu.be") return null;
    if (extractYoutubeVideoId(raw)) return raw;

    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.at(-1) !== "live") {
      parts.push("live");
    }
    url.pathname = `/${parts.join("/")}`;
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    const target = raw.replace(/^\/+/, "").replace(/\/+$/, "");
    if (target.startsWith("@") || target.startsWith("channel/") || target.startsWith("c/") || target.startsWith("user/")) {
      return `https://www.youtube.com/${target}/live`;
    }
    return `https://www.youtube.com/@${target}/live`;
  }
}

async function resolveYoutubeLiveVideoId(target) {
  const direct = extractYoutubeVideoId(target);
  if (direct) return { videoId: direct, source: "direct" };

  const liveUrl = youtubeLiveUrlFromTarget(target);
  if (!liveUrl) return null;

  const res = await fetch(liveUrl, {
    redirect: "follow",
    headers: {
      "User-Agent":
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9",
    },
  });

  const redirectedId = extractYoutubeVideoId(res.url);
  if (redirectedId) {
    return { videoId: redirectedId, source: "redirect", resolvedUrl: res.url };
  }

  if (!res.ok) {
    throw new Error(`youtube_resolve_failed:${res.status}`);
  }

  const html = await res.text();
  const canonicalMatch = html.match(/<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)["']/i);
  const canonicalId = extractYoutubeVideoId(canonicalMatch?.[1]);
  if (canonicalId) {
    return { videoId: canonicalId, source: "canonical", resolvedUrl: canonicalMatch[1] };
  }

  const watchMatch = html.match(/(?:watch\?v=|\\u0026v=)([a-zA-Z0-9_-]{11})/);
  if (watchMatch?.[1]) {
    return { videoId: watchMatch[1], source: "html", resolvedUrl: liveUrl };
  }

  const videoIdMatch = html.match(/"videoId":"([a-zA-Z0-9_-]{11})"/);
  if (videoIdMatch?.[1]) {
    return { videoId: videoIdMatch[1], source: "html", resolvedUrl: liveUrl };
  }

  return null;
}

class TwitchEventSub {
  constructor({ broadcastStatus, broadcastEvent, onAuthUpdate }) {
    this.broadcastStatus = broadcastStatus;
    this.broadcastEvent = broadcastEvent;
    this.onAuthUpdate = onAuthUpdate;
    this.ws = null;
    this.sessionId = null;
    this.connected = false;
    this.auth = null;
    this.reconnectTimer = null;
    this.reconnectAttempt = 0;
    this.shouldReconnect = false;
    this.lastRefreshFailureAt = 0;
  }

  disableReconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.reconnectAttempt = 0;
  }

  getStatus() {
    return {
      connected: Boolean(this.connected && this.ws && this.ws.readyState === WebSocket.OPEN),
      login: this.auth?.login || null,
      userId: this.auth?.userId || null,
      scopes: this.auth?.scope || [],
      expiresAt: this.auth?.expiresAt || null,
      hasAuth: Boolean(this.auth?.accessToken),
      refreshConfigured: Boolean(this.auth?.refreshToken && this.auth?.clientSecret),
    };
  }

  async setAuth(auth) {
    this.auth = auth;
    await this.ensureValidToken();
  }

  stop() {
    this.disableReconnect();
    this.connected = false;
    this.sessionId = null;
    this.closeWs();
  }

  closeWs() {
    try {
      this.ws?.close?.();
    } catch {
      // ignore
    }
    this.ws = null;
  }

  scheduleReconnect(reason) {
    if (!this.shouldReconnect) return;
    if (!this.auth?.accessToken || !this.auth?.clientId) return;
    if (this.reconnectTimer) return;
    const backoffMs = Math.min(30000, 1000 * 2 ** this.reconnectAttempt);
    this.reconnectAttempt += 1;
    this.broadcastStatus({
      status: "reconnecting",
      reason: reason || "ws_closed",
      backoffMs,
    });
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect().catch((err) => {
        this.broadcastStatus({ status: "error", error: String(err?.message || err) });
        this.scheduleReconnect("connect_failed");
      });
    }, backoffMs);
  }

  async ensureValidToken() {
    if (!this.auth?.accessToken || !this.auth?.clientId) return false;

    const now = Date.now();
    if (this.auth.expiresAt && this.auth.expiresAt - now < 60_000 && this.auth.refreshToken) {
      const recentlyFailed = this.lastRefreshFailureAt && now - this.lastRefreshFailureAt < 5 * 60_000;
      if (!recentlyFailed) {
        await this.refreshToken();
      }
    }

    let validateRes;
    try {
      validateRes = await fetch("https://id.twitch.tv/oauth2/validate", {
        headers: {
          Authorization: `OAuth ${this.auth.accessToken}`,
        },
      });
    } catch (err) {
      this.broadcastStatus({
        status: "auth_validate_failed",
        error: String(err?.message || err),
      });
      return false;
    }

    if (!validateRes.ok) {
      this.broadcastStatus({
        status: "auth_invalid",
        error: `validate_failed:${validateRes.status}`,
      });
      if (validateRes.status === 401 || validateRes.status === 403) {
        this.disableReconnect();
        this.closeWs();
      }
      return false;
    }

    const validated = await validateRes.json();
    const expiresIn = Number(validated.expires_in);
    const updated = {
      ...this.auth,
      userId: validated.user_id,
      login: validated.login,
      scope: Array.isArray(validated.scopes) ? validated.scopes : [],
      expiresAt: Number.isFinite(expiresIn) ? Date.now() + expiresIn * 1000 : this.auth.expiresAt,
    };
    this.auth = updated;
    await this.onAuthUpdate(updated);
    return true;
  }

  async refreshToken() {
    if (!this.auth?.refreshToken || !this.auth?.clientId) return;

    const body = new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: this.auth.refreshToken,
      client_id: this.auth.clientId,
    });

    if (this.auth.clientSecret) {
      body.set("client_secret", this.auth.clientSecret);
    }

    const res = await fetch("https://id.twitch.tv/oauth2/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });

    if (!res.ok) {
      this.lastRefreshFailureAt = Date.now();
      const errText = await res.text();
      this.broadcastStatus({
        status: "auth_refresh_failed",
        error: `refresh_failed:${res.status}:${errText?.slice?.(0, 250) || ""}`,
      });
      return;
    }

    const token = await res.json();
    const updated = {
      ...this.auth,
      accessToken: token.access_token,
      refreshToken: token.refresh_token || this.auth.refreshToken,
      tokenType: token.token_type,
      scope: token.scope || this.auth.scope || [],
      obtainedAt: Date.now(),
      expiresAt: Date.now() + (Number(token.expires_in) || 0) * 1000,
    };

    this.auth = updated;
    await this.onAuthUpdate(updated);
    this.broadcastStatus({ status: "auth_refreshed" });
  }

  async connect(wsUrl = "wss://eventsub.wss.twitch.tv/ws") {
    this.shouldReconnect = true;
    if (!this.auth?.accessToken || !this.auth?.clientId) {
      this.broadcastStatus({ status: "auth_required" });
      return;
    }

    const tokenOk = await this.ensureValidToken();
    if (!tokenOk) return;
    if (!this.auth?.userId) {
      this.broadcastStatus({ status: "auth_required" });
      return;
    }

    this.connected = false;
    this.sessionId = null;
    this.closeWs();
    this.broadcastStatus({ status: "connecting" });

    const ws = new WebSocket(wsUrl);
    this.ws = ws;

    ws.addEventListener("open", () => {
      if (ws !== this.ws) return;
      this.connected = true;
      this.reconnectAttempt = 0;
      this.broadcastStatus({ status: "ws_open" });
    });

    ws.addEventListener("close", (ev) => {
      if (ws !== this.ws) return;
      this.connected = false;
      this.sessionId = null;
      this.broadcastStatus({ status: "ws_closed", code: ev?.code, reason: ev?.reason });
      this.scheduleReconnect("ws_closed");
    });

    ws.addEventListener("error", (err) => {
      if (ws !== this.ws) return;
      this.broadcastStatus({ status: "ws_error", error: String(err?.message || err) });
    });

    ws.addEventListener("message", (event) => {
      if (ws !== this.ws) return;
      try {
        const payload = JSON.parse(String(event.data || "{}"));
        this.handleWsMessage(payload).catch((err) => {
          this.broadcastStatus({ status: "error", error: String(err?.message || err) });
        });
      } catch (err) {
        this.broadcastStatus({ status: "error", error: String(err?.message || err) });
      }
    });
  }

  async handleWsMessage(message) {
    const messageType = message?.metadata?.message_type;

    if (messageType === "session_welcome") {
      this.sessionId = message?.payload?.session?.id || null;
      this.broadcastStatus({ status: "session_welcome", sessionId: this.sessionId });
      await this.createSubscriptions();
      return;
    }

    if (messageType === "session_keepalive") return;

    if (messageType === "session_reconnect") {
      const reconnectUrl = message?.payload?.session?.reconnect_url || null;
      this.broadcastStatus({ status: "session_reconnect" });
      if (reconnectUrl) {
        this.connect(reconnectUrl).catch((err) => {
          this.broadcastStatus({ status: "error", error: String(err?.message || err) });
          this.scheduleReconnect("session_reconnect_failed");
        });
      }
      return;
    }

    if (messageType === "notification") {
      const messageId = message?.metadata?.message_id || null;
      const subscriptionType = message?.metadata?.subscription_type || "unknown";
      const timestamp = message?.metadata?.message_timestamp || new Date().toISOString();
      const event = message?.payload?.event || {};

      this.broadcastEvent({
        type: "event",
        id: messageId || createHash("sha1").update(json(message)).digest("hex"),
        eventType: subscriptionType,
        timestamp,
        event,
      });
      return;
    }

    if (messageType === "revocation") {
      this.broadcastStatus({
        status: "revoked",
        subscriptionType: message?.metadata?.subscription_type,
        reason: message?.payload?.subscription?.status,
      });
      return;
    }
  }

  async createSubscriptions() {
    if (!this.sessionId) return;

    const broadcasterUserId = this.auth?.userId;
    if (!broadcasterUserId) return;

    const hasScope = (scope) => (this.auth?.scope || []).includes(scope);

    const subscriptions = [];
    if (hasScope("channel:read:redemptions")) {
      subscriptions.push({
        type: "channel.channel_points_custom_reward_redemption.add",
        version: "1",
        condition: { broadcaster_user_id: broadcasterUserId },
      });
    } else {
      this.broadcastStatus({
        status: "subscription_skipped",
        subscriptionType: "channel.channel_points_custom_reward_redemption.add",
        reason: "missing_scope:channel:read:redemptions",
      });
    }

    if (hasScope("channel:read:raids")) {
      subscriptions.push(
        {
          type: "channel.raid",
          version: "1",
          condition: { to_broadcaster_user_id: broadcasterUserId },
        },
        {
          type: "channel.raid",
          version: "1",
          condition: { from_broadcaster_user_id: broadcasterUserId },
        }
      );
    } else {
      this.broadcastStatus({
        status: "subscription_skipped",
        subscriptionType: "channel.raid",
        reason: "missing_scope:channel:read:raids",
      });
    }

    for (const sub of subscriptions) {
      await this.createSubscription(sub).catch((err) => {
        this.broadcastStatus({
          status: "subscription_error",
          subscriptionType: sub.type,
          error: String(err?.message || err),
        });
      });
    }
  }

  async createSubscription({ type, version, condition }) {
    const ok = await this.ensureValidToken();
    if (!ok) return;

    const res = await fetch("https://api.twitch.tv/helix/eventsub/subscriptions", {
      method: "POST",
      headers: {
        "Client-Id": this.auth.clientId,
        Authorization: `Bearer ${this.auth.accessToken}`,
        "Content-Type": "application/json",
      },
      body: json({
        type,
        version,
        condition,
        transport: {
          method: "websocket",
          session_id: this.sessionId,
        },
      }),
    });

    if (res.status === 409) {
      this.broadcastStatus({ status: "subscribed", subscriptionType: type, deduped: true });
      return;
    }

    if (!res.ok) {
      const errText = await res.text();
      this.broadcastStatus({
        status: "subscription_failed",
        subscriptionType: type,
        httpStatus: res.status,
        error: errText?.slice?.(0, 500) || String(errText),
      });
      return;
    }

    this.broadcastStatus({ status: "subscribed", subscriptionType: type });
  }
}

class TwitchManager {
  constructor() {
    this.clients = new Set();
    this.eventSub = new TwitchEventSub({
      broadcastStatus: (data) => this.broadcast({ type: "status", ...data }),
      broadcastEvent: (data) => this.broadcast(data),
      onAuthUpdate: async (auth) => {
        await writeJsonFile(twitchAuthFileUrl, auth);
      },
    });
  }

  async load() {
    const auth = await readJsonFile(twitchAuthFileUrl);
    if (auth?.accessToken && auth?.clientId) {
      try {
        await this.eventSub.setAuth(auth);
        await this.eventSub.connect();
      } catch (err) {
        this.broadcast({ type: "status", status: "auth_validate_failed", error: String(err?.message || err) });
      }
    }
  }

  addClient(res) {
    this.clients.add(res);
    this.sendTo(res, { type: "status", ...this.eventSub.getStatus() });
  }

  removeClient(res) {
    this.clients.delete(res);
  }

  sendTo(res, data) {
    try {
      res.write(`data: ${json(data)}\n\n`);
    } catch {
      this.clients.delete(res);
    }
  }

  broadcast(data) {
    for (const client of this.clients) {
      this.sendTo(client, data);
    }
  }

  getStatus() {
    return this.eventSub.getStatus();
  }

  async logout() {
    this.eventSub.stop();
    await deleteFile(twitchAuthFileUrl);
    this.broadcast({ type: "status", status: "logged_out" });
  }

  async exchangePkce({ clientId, code, codeVerifier, redirectUri }) {
    return this.exchangePkceWithSecret({ clientId, clientSecret: null, code, codeVerifier, redirectUri });
  }

  async startDeviceFlow({ clientId, scopes }) {
    if (!clientId) {
      throw new Error("missing_client_id");
    }
    const body = new FormData();
    body.set("client_id", clientId);
    body.set("scopes", Array.isArray(scopes) && scopes.length ? scopes.join(" ") : "channel:read:redemptions");

    const res = await fetch("https://id.twitch.tv/oauth2/device", {
      method: "POST",
      body,
    });
    if (!res.ok) {
      const errText = await res.text();
      logLine("info", "[twitch-device] start failed", {
        httpStatus: res.status,
        body: compactHttpBody(errText),
      });
      const detail = compactHttpBody(errText) || res.statusText || "upstream_error";
      throw new Error(`device_start_failed:${res.status}:${detail}`);
    }
    const data = await res.json();
    logLine("info", "[twitch-device] start ok", {
      expiresIn: Number(data.expires_in) || null,
      interval: Number(data.interval) || null,
      hasVerificationUri: Boolean(data.verification_uri),
    });
    return {
      deviceCode: data.device_code,
      userCode: data.user_code,
      verificationUri: data.verification_uri,
      expiresIn: Number(data.expires_in) || 1800,
      interval: Number(data.interval) || 5,
      scopes: Array.isArray(scopes) ? scopes : [],
    };
  }

  async pollDeviceFlow({ clientId, clientSecret, deviceCode, scopes }) {
    if (!clientId || !deviceCode) {
      throw new Error("missing_required_fields");
    }
    const body = new FormData();
    body.set("client_id", clientId);
    body.set("device_code", deviceCode);
    body.set("grant_type", "urn:ietf:params:oauth:grant-type:device_code");
    if (Array.isArray(scopes) && scopes.length) {
      body.set("scopes", scopes.join(" "));
    }
    if (clientSecret) body.set("client_secret", clientSecret);

    const res = await fetch("https://id.twitch.tv/oauth2/token", {
      method: "POST",
      body,
    });
    const raw = await res.text();
    let payload = null;
    try { payload = JSON.parse(raw); } catch { /* non-json */ }

    if (res.ok) {
      logLine("info", "[twitch-device] token poll ok", {
        scopeCount: Array.isArray(payload?.scope) ? payload.scope.length : 0,
        hasRefreshToken: Boolean(payload?.refresh_token),
      });
      const auth = {
        clientId,
        clientSecret: clientSecret || null,
        accessToken: payload.access_token,
        refreshToken: payload.refresh_token || null,
        tokenType: payload.token_type,
        scope: payload.scope || [],
        obtainedAt: Date.now(),
        expiresAt: Date.now() + (Number(payload.expires_in) || 0) * 1000,
        userId: null,
        login: null,
      };
      await writeJsonFile(twitchAuthFileUrl, auth);
      await this.eventSub.setAuth(auth);
      await this.eventSub.connect();
      this.broadcast({ type: "status", status: "auth_ok" });
      return { ok: true, status: this.eventSub.getStatus() };
    }

    if (!res.ok) {
      // Twitch is inconsistent about which field carries the error code on
      // the device-grant token endpoint: sometimes `error`, sometimes
      // `message` (raw string, e.g. "authorization_pending"). We also
      // accept the canonical RFC 8628 names. Anything we don't recognize
      // is fatal — the caller treats it as a hard error.
      const rawErr = String(
        payload?.error ||
        payload?.error_description ||
        payload?.message ||
        ""
      ).trim();
      const normalized = rawErr.toLowerCase().replace(/\s+/g, "_");
      const recoverable = new Set(["authorization_pending", "slow_down"]);
      const code = recoverable.has(normalized) ? normalized : (rawErr || `http_${res.status}`);
      logLine("info", "[twitch-device] token poll response", {
        httpStatus: res.status,
        code,
        recoverable: recoverable.has(normalized),
      });
      return {
        ok: false,
        error: code,
        errorDescription: payload?.error_description || raw?.slice?.(0, 250) || "",
        recoverable: recoverable.has(normalized),
        httpStatus: res.status,
      };
    }
  }

  async exchangePkceWithSecret({ clientId, clientSecret, code, codeVerifier, redirectUri }) {
    if (!clientId || !code || !codeVerifier || !redirectUri) {
      throw new Error("missing_required_fields");
    }

    const body = new URLSearchParams({
      client_id: clientId,
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
      code_verifier: codeVerifier,
    });

    if (clientSecret) {
      body.set("client_secret", clientSecret);
    }

    const res = await fetch("https://id.twitch.tv/oauth2/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });

    if (!res.ok) {
      const errText = await res.text();
      if (errText?.includes?.("missing client secret")) {
        throw new Error(
          "token_exchange_failed:missing_client_secret (Twitch requires a client secret for this app; paste it in Settings or switch the app to a public/PKCE client if available)."
        );
      }
      throw new Error(`token_exchange_failed:${res.status}:${errText?.slice?.(0, 250) || ""}`);
    }

    const token = await res.json();
    const auth = {
      clientId,
      clientSecret: clientSecret || null,
      accessToken: token.access_token,
      refreshToken: token.refresh_token || null,
      tokenType: token.token_type,
      scope: token.scope || [],
      obtainedAt: Date.now(),
      expiresAt: Date.now() + (Number(token.expires_in) || 0) * 1000,
      userId: null,
      login: null,
    };

    await writeJsonFile(twitchAuthFileUrl, auth);
    await this.eventSub.setAuth(auth);
    await this.eventSub.connect();
    this.broadcast({ type: "status", status: "auth_ok" });
    return this.eventSub.getStatus();
  }
}

class LiveRoom {
  constructor(liveId) {
    this.liveId = liveId;
    this.clients = new Set();
    this.started = false;
    this.liveChat = new LiveChat({ liveId });

    this.liveChat.on("chat", (chatItem) => {
      const messageText = textFromChatItem(chatItem);
      const username = chatItem?.author?.name || "Unknown";
      const timestamp = chatItem?.timestamp
        ? new Date(chatItem.timestamp).toISOString()
        : new Date().toISOString();

      const payload = {
        id: stableId({
          liveId: this.liveId,
          username,
          text: messageText,
          timestamp,
        }),
        username,
        text: messageText,
        timestamp,
      };

      this.broadcast(payload);
    });

    this.liveChat.on("error", (err) => {
      this.broadcast({ type: "error", error: String(err?.message || err) });
    });

    this.liveChat.on("end", (reason) => {
      this.broadcast({ type: "end", reason: reason || "ended" });
    });
  }

  async ensureStarted() {
    if (this.started) return;
    this.started = true;
    const ok = await this.liveChat.start();
    if (!ok) {
      this.broadcast({ type: "error", error: "Failed to start YouTube chat." });
    }
  }

  addClient(res) {
    this.clients.add(res);
  }

  removeClient(res) {
    this.clients.delete(res);
    if (this.clients.size === 0) {
      this.liveChat.stop();
    }
  }

  broadcast(data) {
    const line = `data: ${json(data)}\n\n`;
    for (const client of this.clients) {
      try {
        client.write(line);
      } catch {
        this.clients.delete(client);
      }
    }
  }
}

const rooms = new Map();

function getRoom(liveId) {
  const existing = rooms.get(liveId);
  if (existing) return existing;
  const room = new LiveRoom(liveId);
  rooms.set(liveId, room);
  return room;
}

const twitch = new TwitchManager();
await twitch.load();

// Viewer count fetching functions
async function fetchTwitchViewers(channel) {
  const auth = twitch.eventSub?.auth;
  if (!auth?.accessToken || !auth?.clientId) {
    return null;
  }

  try {
    const res = await fetch(
      `https://api.twitch.tv/helix/streams?user_login=${encodeURIComponent(channel)}`,
      {
        headers: {
          "Client-Id": auth.clientId,
          Authorization: `Bearer ${auth.accessToken}`,
        },
      }
    );
    if (!res.ok) return null;
    const data = await res.json();
    const stream = data?.data?.[0];
    return stream?.viewer_count ?? null;
  } catch {
    return null;
  }
}

async function fetchKickViewers(channel) {
  try {
    const res = await fetch(`https://kick.com/api/v2/channels/${encodeURIComponent(channel)}`);
    if (!res.ok) return null;
    const data = await res.json();
    // Kick returns livestream info with viewer count when live
    const viewers = data?.livestream?.viewer_count;
    return viewers !== undefined ? Number(viewers) : null;
  } catch {
    return null;
  }
}

// Outbound chat send — Twitch first (others return clear "not wired" until
// the corresponding OAuth flows are added).
async function sendTwitchChatMessage({ auth, text, channel }) {
  if (!auth?.accessToken || !auth?.clientId) {
    return { ok: false, error: "Not authenticated with Twitch. Open Settings and connect Twitch first." };
  }
  const hasScope = (scope) => (auth.scope || []).includes(scope);
  if (!hasScope("user:write:chat")) {
    return { ok: false, error: "Missing OAuth scope: user:write:chat. Re-authorize Twitch in Settings to grant the user:write:chat scope." };
  }

  // Resolve broadcaster id. We try the configured channel first; if absent,
  // fall back to the authenticated user's own channel.
  let broadcasterId = null;
  let senderId = auth.userId;
  if (channel) {
    broadcasterId = await getTwitchUserId(channel, auth);
  }
  if (!broadcasterId) {
    broadcasterId = auth.userId;
  }
  if (!broadcasterId || !senderId) {
    return { ok: false, error: "Could not resolve broadcaster / sender user id from Twitch auth." };
  }

  try {
    const res = await fetch("https://api.twitch.tv/helix/chat/messages", {
      method: "POST",
      headers: {
        "Client-Id": auth.clientId,
        Authorization: `Bearer ${auth.accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        broadcaster_id: broadcasterId,
        sender_id: senderId,
        message: String(text || "").slice(0, 500),
      }),
    });
    const helixText = await res.text();
    if (!res.ok) {
      let msg = `twitch_send_failed:${res.status}`;
      try {
        const j = JSON.parse(helixText);
        msg = j?.message || j?.error || msg;
      } catch {
        msg = helixText?.slice?.(0, 200) || msg;
      }
      logLine("info", `[helix] chat/messages ${res.status} body=${helixText.slice(0, 300)}`);
      return { ok: false, error: msg };
    }
    logLine("info", `[helix] chat/messages 200 body=${helixText.slice(0, 300)}`);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: String(err?.message || err) };
  }
}

async function getTwitchUserId(username, auth) {
  if (!auth?.accessToken || !auth?.clientId) return null;
  try {
    const res = await fetch(
      `https://api.twitch.tv/helix/users?login=${encodeURIComponent(username)}`,
      {
        headers: {
          "Client-Id": auth.clientId,
          Authorization: `Bearer ${auth.accessToken}`,
        },
      }
    );
    if (!res.ok) return null;
    const data = await res.json();
    return data?.data?.[0]?.id || null;
  } catch {
    return null;
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (req.method === "GET" && url.pathname === "/api/health") {
    return send(res, 200, "ok\n", {
      "Access-Control-Allow-Origin": "*",
    });
  }

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    });
    return res.end();
  }

  if (req.method === "GET" && url.pathname === "/api/twitch/status") {
    return sendJson(res, 200, twitch.getStatus(), {
      "Access-Control-Allow-Origin": "*",
    });
  }

  // Viewer count endpoints
  if (req.method === "GET" && url.pathname.startsWith("/api/viewers/twitch/")) {
    const channel = url.pathname.split("/api/viewers/twitch/")[1];
    if (!channel) {
      return sendJson(res, 400, { error: "Missing channel" }, { "Access-Control-Allow-Origin": "*" });
    }
    const viewers = await fetchTwitchViewers(decodeURIComponent(channel));
    return sendJson(res, 200, { viewers }, { "Access-Control-Allow-Origin": "*" });
  }

  if (req.method === "GET" && url.pathname.startsWith("/api/viewers/kick/")) {
    const channel = url.pathname.split("/api/viewers/kick/")[1];
    if (!channel) {
      return sendJson(res, 400, { error: "Missing channel" }, { "Access-Control-Allow-Origin": "*" });
    }
    const viewers = await fetchKickViewers(decodeURIComponent(channel));
    return sendJson(res, 200, { viewers }, { "Access-Control-Allow-Origin": "*" });
  }

  if (req.method === "GET" && url.pathname === "/api/youtube/live-video-id") {
    const target = url.searchParams.get("target") || url.searchParams.get("channel") || "";
    if (!target.trim()) {
      return sendJson(res, 400, { error: "Missing target" }, { "Access-Control-Allow-Origin": "*" });
    }

    try {
      const result = await resolveYoutubeLiveVideoId(target);
      if (!result?.videoId) {
        return sendJson(
          res,
          404,
          { error: "No active YouTube live video found for that target." },
          { "Access-Control-Allow-Origin": "*" }
        );
      }

      return sendJson(res, 200, result, { "Access-Control-Allow-Origin": "*" });
    } catch (err) {
      return sendJson(
        res,
        502,
        { error: String(err?.message || err) },
        { "Access-Control-Allow-Origin": "*" }
      );
    }
  }

  if (req.method === "POST" && url.pathname === "/api/twitch/pkce/exchange") {
    try {
      const payload = await readJsonBody(req);
      const clientId = String(payload?.clientId || "");
      const clientSecret = payload?.clientSecret ? String(payload.clientSecret) : "";
      const code = String(payload?.code || "");
      const codeVerifier = String(payload?.codeVerifier || "");
      const redirectUri = String(payload?.redirectUri || "");

      const status = await twitch.exchangePkceWithSecret({
        clientId,
        clientSecret: clientSecret ? clientSecret : null,
        code,
        codeVerifier,
        redirectUri,
      });
      return sendJson(res, 200, status, { "Access-Control-Allow-Origin": "*" });
    } catch (err) {
      return send(res, 400, `${String(err?.message || err)}\n`, { "Access-Control-Allow-Origin": "*" });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/twitch/device/start") {
    try {
      const payload = await readJsonBody(req);
      const clientId = String(payload?.clientId || "");
      const scopes = Array.isArray(payload?.scopes)
        ? payload.scopes.map((s) => String(s)).filter(Boolean)
        : null;
      const result = await twitch.startDeviceFlow({ clientId, scopes });
      return sendJson(res, 200, result, { "Access-Control-Allow-Origin": "*" });
    } catch (err) {
      return send(res, 400, `${String(err?.message || err)}\n`, { "Access-Control-Allow-Origin": "*" });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/twitch/device/poll") {
    try {
      const payload = await readJsonBody(req);
      const clientId = String(payload?.clientId || "");
      const clientSecret = payload?.clientSecret ? String(payload.clientSecret) : null;
      const deviceCode = String(payload?.deviceCode || "");
      const scopes = Array.isArray(payload?.scopes)
        ? payload.scopes.map((s) => String(s)).filter(Boolean)
        : null;
      const result = await twitch.pollDeviceFlow({ clientId, clientSecret, deviceCode, scopes });
      return sendJson(res, 200, result, { "Access-Control-Allow-Origin": "*" });
    } catch (err) {
      return send(res, 400, `${String(err?.message || err)}\n`, { "Access-Control-Allow-Origin": "*" });
    }
  }

  if ((req.method === "POST" || req.method === "GET") && url.pathname === "/api/twitch/logout") {
    await twitch.logout();
    return send(res, 200, "ok\n", { "Access-Control-Allow-Origin": "*" });
  }

  if (req.method === "POST" && url.pathname === "/api/twitch/raid") {
    try {
      const payload = await readJsonBody(req);
      let targetChannel = payload?.targetChannel;
      if (!targetChannel) {
        return sendJson(res, 400, { error: "Missing targetChannel" }, { "Access-Control-Allow-Origin": "*" });
      }

      targetChannel = targetChannel.replace(/^#/, "");

      const auth = twitch.eventSub?.auth;
      if (!auth?.accessToken || !auth?.clientId) {
        return sendJson(res, 401, { error: "Not authenticated with Twitch" }, { "Access-Control-Allow-Origin": "*" });
      }

      const hasScope = (scope) => (auth.scope || []).includes(scope);
      if (!hasScope("channel:manage:raids")) {
        return sendJson(res, 403, { error: "Missing required scope: channel:manage:raids" }, { "Access-Control-Allow-Origin": "*" });
      }

      const fromBroadcasterId = auth.userId;
      const toBroadcasterId = await getTwitchUserId(targetChannel, auth);

      if (!toBroadcasterId) {
        return sendJson(res, 404, { error: `Could not find Twitch user: ${targetChannel}` }, { "Access-Control-Allow-Origin": "*" });
      }

      const raidRes = await fetch(
        `https://api.twitch.tv/helix/raids?from_broadcaster_id=${fromBroadcasterId}&to_broadcaster_id=${toBroadcasterId}`,
        {
          method: "POST",
          headers: {
            "Client-Id": auth.clientId,
            Authorization: `Bearer ${auth.accessToken}`,
            "Content-Type": "application/json",
          },
        }
      );

      if (!raidRes.ok) {
        const errText = await raidRes.text();
        let errorMsg = "Raid failed";
        try {
          const errJson = JSON.parse(errText);
          errorMsg = errJson.message || errorMsg;
        } catch {
          errorMsg = errText || errorMsg;
        }
        return sendJson(res, raidRes.status, { error: errorMsg }, { "Access-Control-Allow-Origin": "*" });
      }

      return sendJson(res, 200, { status: "raid_initiated", targetChannel }, { "Access-Control-Allow-Origin": "*" });
    } catch (err) {
      return sendJson(res, 500, { error: String(err?.message || err) }, { "Access-Control-Allow-Origin": "*" });
    }
  }

  if (req.method === "GET" && (url.pathname === "/api/twitch/auth/start" || url.pathname === "/api/twitch/auth/callback")) {
    return send(
      res,
      410,
      "Deprecated: use the HTTPS frontend auth flow at https://localhost:5173/auth/twitch\n",
      { "Access-Control-Allow-Origin": "*" },
    );
  }

  // Outbound chat send. Auth-gated; returns clear actionable errors when
  // the corresponding OAuth/scope is missing. Currently wired for Twitch
  // (real call to Helix chat/messages). YouTube and Kick return explicit
  // "not configured" responses so the UI's failure badge has a real cause.
  if (req.method === "POST" && url.pathname.startsWith("/api/send/")) {
    const platform = url.pathname.split("/api/send/")[1];
    const startMs = Date.now();
    const contentLength = req.headers["content-length"] || "?";
    logLine("info", `[send] ${platform} req method=${req.method} content-length=${contentLength} ua=${req.headers["user-agent"] || "?"}`);
    let body;
    try {
      body = await readJsonBody(req);
    } catch (err) {
      logLine("info", `[send] ${platform} -> 400 invalid_body (${err.message}) in ${Date.now() - startMs}ms`);
      return sendJson(res, 400, { ok: false, error: `invalid_body:${err.message}` }, { "Access-Control-Allow-Origin": "*" });
    }
    const text = (body?.text || "").toString();
    if (!text.trim()) {
      logLine("info", `[send] ${platform} -> 400 empty_text in ${Date.now() - startMs}ms`);
      return sendJson(res, 400, { ok: false, error: "Missing or empty `text`." }, { "Access-Control-Allow-Origin": "*" });
    }
    if (text.length > 500) {
      logLine("info", `[send] ${platform} -> 400 too_long in ${Date.now() - startMs}ms`);
      return sendJson(res, 400, { ok: false, error: "Message exceeds 500-character platform limit." }, { "Access-Control-Allow-Origin": "*" });
    }

    if (platform === "twitch") {
      const auth = twitch.eventSub?.auth;
      logLine("info", `[send] ${platform} auth scopes=${JSON.stringify(auth?.scope)} userId=${auth?.userId}`);
      const result = await sendTwitchChatMessage({
        auth,
        text,
        channel: body?.channel || "",
      });
      logLine("info", `[send] ${platform} -> ${result.ok ? 200 : 400} ${JSON.stringify(result).slice(0, 200)} in ${Date.now() - startMs}ms`);
      return sendJson(res, result.ok ? 200 : 400, result, { "Access-Control-Allow-Origin": "*" });
    }

    if (platform === "youtube") {
      return sendJson(
        res,
        501,
        {
          ok: false,
          error:
            "Outbound YouTube chat is not wired up in this build. It requires a Google OAuth flow with the youtube.force-ssl scope, which the app does not yet have. Track / implement in a follow-up.",
        },
        { "Access-Control-Allow-Origin": "*" }
      );
    }

    if (platform === "kick") {
      return sendJson(
        res,
        501,
        {
          ok: false,
          error:
            "Outbound Kick chat is not wired up in this build. Kick has no public chat-posting API; outbound requires a logged-in browser session, which is out of scope here. Track / implement in a follow-up.",
        },
        { "Access-Control-Allow-Origin": "*" }
      );
    }

    return sendJson(res, 404, { ok: false, error: `unknown_platform:${platform}` }, { "Access-Control-Allow-Origin": "*" });
  }

  if (req.method === "GET" && url.pathname === "/api/twitch/sse") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });
    res.write("retry: 3000\n\n");

    twitch.addClient(res);

    const keepAlive = setInterval(() => {
      try {
        res.write(": ping\n\n");
      } catch {
        clearInterval(keepAlive);
      }
    }, 15000);

    req.on("close", () => {
      clearInterval(keepAlive);
      twitch.removeClient(res);
    });
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/youtube/sse") {
    const liveId = url.searchParams.get("liveId");
    if (!liveId) {
      return send(res, 400, "Missing required query param: liveId\n", {
        "Access-Control-Allow-Origin": "*",
      });
    }

    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });
    res.write("retry: 3000\n\n");

    const room = getRoom(liveId);
    room.addClient(res);
    await room.ensureStarted();

    const keepAlive = setInterval(() => {
      try {
        res.write(": ping\n\n");
      } catch {
        clearInterval(keepAlive);
      }
    }, 15000);

    req.on("close", () => {
      clearInterval(keepAlive);
      room.removeClient(res);
      if (room.clients.size === 0) {
        rooms.delete(liveId);
      }
    });
    return;
  }

  send(res, 404, "Not found\n", {
    "Access-Control-Allow-Origin": "*",
  });
});

server.listen(port, () => {
  logLine("info", `Proxy server listening on http://localhost:${port}`);
});
