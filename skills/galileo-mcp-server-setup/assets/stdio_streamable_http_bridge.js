#!/usr/bin/env node
"use strict";

// Dependency-free MCP stdio -> Streamable HTTP bridge. Secrets are read from
// process environment or owner-only files and are never copied into argv/logs.

const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");
const readline = require("readline");

const scriptDir = __dirname;
const envFile = path.join(scriptDir, ".env.galileo-mcp");
const DEFAULT_MAX_BODY_BYTES = 16 * 1024 * 1024;
const DEFAULT_TIMEOUT_MS = 60 * 1000;
const DEFAULT_SSE_RECONNECT_BASE_MS = 250;
const DEFAULT_SSE_RECONNECT_MAX_MS = 30 * 1000;
const DEFAULT_SSE_STABLE_MS = 30 * 1000;

function fail(message) {
  process.stderr.write("galileo-mcp: " + message + "\n");
  process.exit(1);
}

function warn(message) {
  process.stderr.write("galileo-mcp: " + message + "\n");
}

function parseShellWord(value) {
  let result = "";
  let state = "normal";
  for (let i = 0; i < value.length; i += 1) {
    const ch = value[i];
    if (state === "single") {
      if (ch === "'") state = "normal";
      else result += ch;
      continue;
    }
    if (state === "double") {
      if (ch === '"') state = "normal";
      else if (ch === "\\") {
        i += 1;
        if (i < value.length) result += value[i];
      } else result += ch;
      continue;
    }
    if (ch === "'") state = "single";
    else if (ch === '"') state = "double";
    else if (ch === "\\") {
      i += 1;
      if (i < value.length) result += value[i];
    } else result += ch;
  }
  return result;
}

function ownerOnly(filePath) {
  if (process.platform === "win32") return true;
  const mode = fs.statSync(filePath).mode & 0o777;
  return (mode & 0o077) === 0;
}

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;
  if (
    !ownerOnly(filePath) &&
    process.env.GALILEO_MCP_ALLOW_LOOSE_KEY_PERMS !== "1"
  ) {
    fail(
      "refusing non-owner-only .env.galileo-mcp; run chmod 600 or set " +
        "GALILEO_MCP_ALLOW_LOOSE_KEY_PERMS=1 for a disposable lab"
    );
  }
  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue;
    const value = parseShellWord(trimmed.slice(eq + 1).trim());
    if (!(key in process.env)) process.env[key] = value;
  }
}

function readKeyFile(filePath) {
  if (!ownerOnly(filePath) && process.env.GALILEO_MCP_ALLOW_LOOSE_KEY_PERMS !== "1") {
    fail(
      "refusing non-owner-only GALILEO_API_KEY_FILE; run chmod 600 or set " +
        "GALILEO_MCP_ALLOW_LOOSE_KEY_PERMS=1 for a disposable lab"
    );
  }
  return fs.readFileSync(filePath, "utf8").trim();
}

function positiveInteger(name, fallback) {
  const value = process.env[name];
  if (!value) return fallback;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    fail(name + " must be a positive integer");
  }
  return parsed;
}

loadEnvFile(envFile);

if (!process.env.GALILEO_MCP_URL) {
  fail("set GALILEO_MCP_URL in " + envFile);
}

let apiKey = process.env.GALILEO_API_KEY || "";
if (!apiKey && process.env.GALILEO_API_KEY_FILE) {
  try {
    apiKey = readKeyFile(process.env.GALILEO_API_KEY_FILE);
  } catch (err) {
    fail("could not read GALILEO_API_KEY_FILE: " + err.message);
  }
}
if (!apiKey) {
  fail("set GALILEO_API_KEY or GALILEO_API_KEY_FILE in " + envFile);
}

let endpoint;
try {
  endpoint = new URL(process.env.GALILEO_MCP_URL);
} catch (_) {
  fail("GALILEO_MCP_URL must be an absolute HTTP(S) URL");
}

if (!['http:', 'https:'].includes(endpoint.protocol)) {
  fail("GALILEO_MCP_URL must use HTTP or HTTPS");
}
if (endpoint.username || endpoint.password || endpoint.search || endpoint.hash) {
  fail("GALILEO_MCP_URL must not contain credentials, a query, or a fragment");
}
function normalizeUrlHostname(hostname) {
  const normalized = hostname.toLowerCase();
  if (normalized.startsWith("[") && normalized.endsWith("]")) {
    return normalized.slice(1, -1);
  }
  return normalized;
}

const endpointHostname = normalizeUrlHostname(endpoint.hostname);
const loopbackHosts = new Set(["127.0.0.1", "::1", "localhost"]);
if (
  endpoint.protocol !== "https:" &&
  !loopbackHosts.has(endpointHostname) &&
  process.env.GALILEO_MCP_ALLOW_HTTP !== "1"
) {
  fail("GALILEO_MCP_URL must use HTTPS outside loopback testing");
}

const maxBodyBytes = positiveInteger("GALILEO_MCP_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES);
const timeoutMs = positiveInteger("GALILEO_MCP_TIMEOUT_MS", DEFAULT_TIMEOUT_MS);
const reconnectBaseMs = positiveInteger(
  "GALILEO_MCP_SSE_RECONNECT_BASE_MS",
  DEFAULT_SSE_RECONNECT_BASE_MS
);
const reconnectMaxMs = positiveInteger(
  "GALILEO_MCP_SSE_RECONNECT_MAX_MS",
  DEFAULT_SSE_RECONNECT_MAX_MS
);
const stableStreamMs = positiveInteger("GALILEO_MCP_SSE_STABLE_MS", DEFAULT_SSE_STABLE_MS);
const insecureTls = process.env.GALILEO_MCP_INSECURE_TLS === "1";
let sessionId = "";
let protocolVersion = "";
let activeEventRequest = null;
let eventReconnectTimer = null;
let eventReconnectAttempt = 0;
let eventStreamDisabled = false;
let shuttingDown = false;

class BridgeError extends Error {
  constructor(message, statusCode = 0) {
    super(message);
    this.statusCode = statusCode;
  }
}

function hasRequestId(message) {
  return Object.prototype.hasOwnProperty.call(message, "id");
}

function sameId(left, right) {
  return typeof left === typeof right && left === right;
}

function emitMessage(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
}

function emitBridgeError(input, err) {
  const statusCode = err && Number.isInteger(err.statusCode) ? err.statusCode : 0;
  if (hasRequestId(input)) {
    emitMessage({
      jsonrpc: "2.0",
      id: input.id,
      error: {
        code: -32000,
        message: "Galileo MCP transport error",
        data: statusCode ? { http_status: statusCode } : undefined,
      },
    });
  } else {
    warn("notification delivery failed" + (statusCode ? " (HTTP " + statusCode + ")" : ""));
  }
}

function updateProtocolState(input, message) {
  if (
    input.method === "initialize" &&
    sameId(input.id, message.id) &&
    message.result &&
    typeof message.result.protocolVersion === "string"
  ) {
    protocolVersion = message.result.protocolVersion;
  }
}

function parseJsonMessages(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (_) {
    throw new BridgeError("MCP server returned invalid JSON");
  }
  return Array.isArray(parsed) ? parsed : [parsed];
}

class SseDecoder {
  constructor(onMessage) {
    this.onMessage = onMessage;
    this.buffer = "";
    this.dataLines = [];
    this.eventBytes = 0;
  }

  push(chunk) {
    this.buffer += chunk;
    let newline;
    while ((newline = this.buffer.indexOf("\n")) !== -1) {
      let line = this.buffer.slice(0, newline);
      this.buffer = this.buffer.slice(newline + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      this.line(line);
    }
    if (Buffer.byteLength(this.buffer) > maxBodyBytes) {
      throw new BridgeError("MCP SSE line exceeds body limit");
    }
  }

  line(line) {
    if (line === "") {
      this.dispatch();
      return;
    }
    this.eventBytes += Buffer.byteLength(line) + 1;
    if (this.eventBytes > maxBodyBytes) {
      throw new BridgeError("MCP SSE event exceeds body limit");
    }
    if (line.startsWith(":")) return;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") {
      this.dataLines.push(value);
    }
  }

  dispatch() {
    if (this.dataLines.length === 0) {
      this.eventBytes = 0;
      return;
    }
    const data = this.dataLines.join("\n");
    this.dataLines = [];
    this.eventBytes = 0;
    for (const message of parseJsonMessages(data)) this.onMessage(message);
  }

  end() {
    if (this.buffer) this.line(this.buffer.replace(/\r$/, ""));
    this.buffer = "";
    this.dispatch();
  }
}

function requestHeaders(method, bodyLength) {
  const headers = {
    Accept: "application/json, text/event-stream",
    "Galileo-API-Key": apiKey,
  };
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    headers["Content-Length"] = String(bodyLength);
  }
  if (sessionId) headers["Mcp-Session-Id"] = sessionId;
  if (protocolVersion) headers["MCP-Protocol-Version"] = protocolVersion;
  return headers;
}

function requestOptions(method, bodyLength) {
  return {
    protocol: endpoint.protocol,
    hostname: endpointHostname,
    port: endpoint.port || undefined,
    path: endpoint.pathname,
    method,
    headers: requestHeaders(method, bodyLength),
    timeout: timeoutMs,
    rejectUnauthorized: !insecureTls,
  };
}

function captureSession(response) {
  const value = response.headers["mcp-session-id"];
  if (Array.isArray(value)) sessionId = value[0] || sessionId;
  else if (typeof value === "string" && value) sessionId = value;
}

function makeRequest(method, body, onResponse) {
  const client = endpoint.protocol === "https:" ? https : http;
  const request = client.request(requestOptions(method, Buffer.byteLength(body)), onResponse);
  request.on("timeout", () => request.destroy(new BridgeError("MCP request timed out")));
  if (body) request.write(body);
  request.end();
  return request;
}

function postMessage(input) {
  const body = JSON.stringify(input);
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      callback(value);
    };
    const request = makeRequest("POST", body, (response) => {
      captureSession(response);
      const status = response.statusCode || 0;
      if (status >= 300 && status < 400) {
        response.resume();
        finish(reject, new BridgeError("MCP redirects are disabled", status));
        return;
      }
      if (status < 200 || status >= 300) {
        response.resume();
        finish(reject, new BridgeError("MCP server rejected request", status));
        return;
      }
      if (status === 202 || status === 204) {
        response.resume();
        finish(resolve);
        return;
      }

      const contentType = String(response.headers["content-type"] || "")
        .split(";", 1)[0]
        .trim()
        .toLowerCase();
      let bytes = 0;
      let text = "";
      let matchingResponseSeen = false;
      const processMessage = (message) => {
        if (!message || typeof message !== "object") return;
        updateProtocolState(input, message);
        emitMessage(message);
        if (hasRequestId(input) && sameId(input.id, message.id)) {
          matchingResponseSeen = true;
          if (contentType === "text/event-stream") {
            finish(resolve);
            setImmediate(() => response.destroy());
          }
        } else if (!hasRequestId(input) && contentType === "text/event-stream") {
          finish(resolve);
          setImmediate(() => response.destroy());
        }
      };
      const sse = new SseDecoder(processMessage);

      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        try {
          if (contentType === "text/event-stream") {
            sse.push(chunk);
          } else {
            bytes += Buffer.byteLength(chunk);
            if (bytes > maxBodyBytes) {
              throw new BridgeError("MCP response exceeds body limit");
            }
            text += chunk;
          }
        } catch (err) {
          response.destroy(err);
        }
      });
      response.on("error", (err) => finish(reject, err));
      response.on("end", () => {
        try {
          if (contentType === "text/event-stream") sse.end();
          else if (text.trim()) {
            for (const message of parseJsonMessages(text)) processMessage(message);
          }
          if (hasRequestId(input) && !matchingResponseSeen) {
            throw new BridgeError("MCP response did not include the request id");
          }
          finish(resolve);
        } catch (err) {
          finish(reject, err);
        }
      });
    });
    request.on("error", (err) => finish(reject, err));
  });
}

function disableServerEventStream(message) {
  eventStreamDisabled = true;
  if (eventReconnectTimer) clearTimeout(eventReconnectTimer);
  eventReconnectTimer = null;
  if (message) warn(message);
}

function scheduleServerEventReconnect(request, connectedAt = 0) {
  if (activeEventRequest === request) activeEventRequest = null;
  if (shuttingDown || eventStreamDisabled || eventReconnectTimer || !sessionId) return;
  if (connectedAt && Date.now() - connectedAt >= stableStreamMs) {
    eventReconnectAttempt = 0;
  }
  const exponent = Math.min(eventReconnectAttempt, 16);
  const delay = Math.min(reconnectBaseMs * (2 ** exponent), reconnectMaxMs);
  eventReconnectAttempt += 1;
  eventReconnectTimer = setTimeout(() => {
    eventReconnectTimer = null;
    startServerEventStream();
  }, delay);
  eventReconnectTimer.unref();
}

function startServerEventStream() {
  if (
    !sessionId ||
    activeEventRequest ||
    eventReconnectTimer ||
    eventStreamDisabled ||
    shuttingDown
  ) return;
  let request;
  request = makeRequest("GET", "", (response) => {
    captureSession(response);
    const status = response.statusCode || 0;
    if (status >= 300 && status < 400) {
      response.resume();
      if (activeEventRequest === request) activeEventRequest = null;
      disableServerEventStream("server event-stream redirect rejected (HTTP " + status + ")");
      return;
    }
    if ([400, 401, 403, 404, 405].includes(status)) {
      response.resume();
      if (activeEventRequest === request) activeEventRequest = null;
      disableServerEventStream();
      return;
    }
    if (status < 200 || status >= 300) {
      response.resume();
      warn("server event stream unavailable (HTTP " + status + ")");
      scheduleServerEventReconnect(request);
      return;
    }
    const contentType = String(response.headers["content-type"] || "")
      .split(";", 1)[0]
      .trim()
      .toLowerCase();
    if (contentType !== "text/event-stream") {
      response.resume();
      if (activeEventRequest === request) activeEventRequest = null;
      disableServerEventStream("server event stream returned an unsupported content type");
      return;
    }
    const connectedAt = Date.now();
    const sse = new SseDecoder(emitMessage);
    response.setEncoding("utf8");
    response.on("data", (chunk) => {
      try {
        sse.push(chunk);
      } catch (err) {
        response.destroy(err);
      }
    });
    response.on("end", () => {
      try {
        sse.end();
      } catch (_) {
        warn("server event stream contained invalid data");
      }
      scheduleServerEventReconnect(request, connectedAt);
    });
    response.on("error", () => {
      if (!shuttingDown) warn("server event stream closed unexpectedly");
      scheduleServerEventReconnect(request, connectedAt);
    });
  });
  activeEventRequest = request;
  request.on("error", () => {
    if (!shuttingDown) warn("could not open server event stream");
    scheduleServerEventReconnect(request);
  });
}

function closeSession() {
  if (!sessionId) return Promise.resolve();
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve();
    };
    const request = makeRequest("DELETE", "", (response) => {
      response.resume();
      response.on("end", finish);
    });
    request.on("error", finish);
    setTimeout(() => {
      request.destroy();
      finish();
    }, Math.min(timeoutMs, 1000)).unref();
  });
}

let initializationPromise = null;
let readyPromise = Promise.resolve();
const pendingOperations = new Set();
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

function trackOperation(operation, message) {
  const handled = operation.catch((err) => emitBridgeError(message, err));
  pendingOperations.add(handled);
  handled.finally(() => pendingOperations.delete(handled));
  return operation;
}

input.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  if (Buffer.byteLength(trimmed) > maxBodyBytes) {
    emitMessage({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32600, message: "Request exceeds message limit" },
    });
    return;
  }
  let message;
  try {
    message = JSON.parse(trimmed);
  } catch (_) {
    emitMessage({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32700, message: "Parse error" },
    });
    return;
  }
  if (!message || typeof message !== "object" || Array.isArray(message)) {
    emitMessage({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32600, message: "Invalid Request" },
    });
    return;
  }
  let operation;
  if (message.method === "initialize") {
    if (initializationPromise) {
      emitMessage({
        jsonrpc: "2.0",
        id: hasRequestId(message) ? message.id : null,
        error: { code: -32600, message: "Initialize already received" },
      });
      return;
    }
    initializationPromise = postMessage(message).then(() => startServerEventStream());
    readyPromise = initializationPromise;
    operation = initializationPromise;
  } else if (message.method === "notifications/initialized") {
    operation = readyPromise.then(() => postMessage(message));
    readyPromise = operation;
  } else {
    // Once initialize/initialized completes, requests and notifications run
    // concurrently. This lets notifications/cancelled bypass the request it
    // needs to cancel while preserving handshake ordering.
    operation = readyPromise.then(() => postMessage(message));
  }
  trackOperation(operation, message);
});

async function shutdown(exitCode) {
  if (shuttingDown) return;
  shuttingDown = true;
  if (eventReconnectTimer) clearTimeout(eventReconnectTimer);
  eventReconnectTimer = null;
  if (activeEventRequest) activeEventRequest.destroy();
  await Promise.allSettled([...pendingOperations]);
  await closeSession();
  process.exit(exitCode);
}

input.on("close", () => {
  shutdown(0);
});
process.on("SIGINT", () => shutdown(130));
process.on("SIGTERM", () => shutdown(143));
