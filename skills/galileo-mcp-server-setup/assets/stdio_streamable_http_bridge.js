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
const MAX_ENV_FILE_BYTES = 64 * 1024;
const MAX_API_KEY_FILE_BYTES = 16 * 1024;
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
        if (i + 1 >= value.length) throw new Error("trailing escape");
        i += 1;
        result += value[i];
      } else result += ch;
      continue;
    }
    if (ch === "'") state = "single";
    else if (ch === '"') state = "double";
    else if (ch === "\\") {
      if (i + 1 >= value.length) throw new Error("trailing escape");
      i += 1;
      result += value[i];
    } else result += ch;
  }
  if (state !== "normal") throw new Error("unterminated quote");
  return result;
}

function sameFileSnapshot(left, right) {
  return ["dev", "ino", "size", "mode", "uid", "nlink", "mtimeMs", "ctimeMs"].every(
    (field) => left[field] === right[field]
  );
}

function decodeUtf8(buffer, label) {
  const value = buffer.toString("utf8");
  if (!Buffer.from(value, "utf8").equals(buffer)) {
    throw new Error(label + " must contain valid UTF-8");
  }
  return value;
}

function readPrivateRegularFile(filePath, label, maxBytes) {
  const allowLoose = process.env.GALILEO_MCP_ALLOW_LOOSE_KEY_PERMS === "1";
  const pathStat = fs.lstatSync(filePath);
  if (pathStat.isSymbolicLink()) throw new Error(label + " must not be a symbolic link");

  const flags =
    fs.constants.O_RDONLY |
    (fs.constants.O_NOFOLLOW || 0) |
    (fs.constants.O_NONBLOCK || 0);
  let descriptor;
  try {
    descriptor = fs.openSync(filePath, flags);
    const before = fs.fstatSync(descriptor);
    if (!before.isFile()) throw new Error(label + " must be a regular file");
    if (before.nlink !== 1) throw new Error(label + " must have exactly one hard link");
    if (before.dev !== pathStat.dev || before.ino !== pathStat.ino) {
      throw new Error(label + " changed while it was being opened");
    }
    if (
      process.platform !== "win32" &&
      typeof process.getuid === "function" &&
      before.uid !== process.getuid()
    ) {
      throw new Error(label + " must be owned by the current user");
    }
    if (process.platform !== "win32" && (before.mode & 0o077) !== 0) {
      if (!allowLoose) {
        throw new Error(
          label +
            " must be owner-only; run chmod 600 or set " +
            "GALILEO_MCP_ALLOW_LOOSE_KEY_PERMS=1 for a disposable lab"
        );
      }
      warn(label + " is not owner-only; loose-permission lab override is active");
    }
    if (before.size > maxBytes) throw new Error(label + " exceeds its size limit");

    const contents = fs.readFileSync(descriptor);
    const after = fs.fstatSync(descriptor);
    if (contents.length > maxBytes) throw new Error(label + " exceeds its size limit");
    if (!sameFileSnapshot(before, after)) {
      throw new Error(label + " changed while it was being read");
    }
    return contents;
  } finally {
    if (typeof descriptor === "number") fs.closeSync(descriptor);
  }
}

function loadEnvFile(filePath) {
  let contents;
  try {
    contents = decodeUtf8(
      readPrivateRegularFile(filePath, ".env.galileo-mcp", MAX_ENV_FILE_BYTES),
      ".env.galileo-mcp"
    );
  } catch (err) {
    if (err && err.code === "ENOENT") return;
    fail("could not securely read .env.galileo-mcp: " + err.message);
  }
  if (contents.startsWith("\uFEFF")) contents = contents.slice(1);
  const lines = contents.split(/\r?\n/);
  for (let lineNumber = 0; lineNumber < lines.length; lineNumber += 1) {
    const line = lines[lineNumber];
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue;
    let value;
    try {
      value = parseShellWord(trimmed.slice(eq + 1).trim());
    } catch (_) {
      fail("invalid quoting in .env.galileo-mcp at line " + (lineNumber + 1));
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}

function readKeyFile(filePath) {
  const contents = readPrivateRegularFile(
    filePath,
    "GALILEO_API_KEY_FILE",
    MAX_API_KEY_FILE_BYTES
  );
  let value = decodeUtf8(contents, "GALILEO_API_KEY_FILE");
  if (value.endsWith("\r\n")) value = value.slice(0, -2);
  else if (value.endsWith("\n") || value.endsWith("\r")) value = value.slice(0, -1);
  if (!/^[\x21-\x7e]+$/.test(value)) {
    throw new Error("GALILEO_API_KEY_FILE must contain exactly one non-empty ASCII token line");
  }
  return value;
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
if (!/^[\x21-\x7e]+$/.test(apiKey)) {
  fail("GALILEO_API_KEY must be a non-empty ASCII token without whitespace");
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
  !loopbackHosts.has(endpointHostname)
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
let initializeMessage = null;
let initializedMessage = null;
let sessionRecoveryPromise = null;

class BridgeError extends Error {
  constructor(message, statusCode = 0) {
    super(message);
    this.statusCode = statusCode;
  }
}

function hasRequestId(message) {
  return Boolean(
    message &&
      typeof message === "object" &&
      !Array.isArray(message) &&
      Object.prototype.hasOwnProperty.call(message, "id")
  );
}

function isResponseMessage(message) {
  return Boolean(
    hasRequestId(message) &&
      typeof message.method === "undefined" &&
      (Object.prototype.hasOwnProperty.call(message, "result") ||
        Object.prototype.hasOwnProperty.call(message, "error"))
  );
}

function sameId(left, right) {
  return typeof left === typeof right && left === right;
}

function requestIdKey(id) {
  return typeof id + ":" + JSON.stringify(id);
}

function inputRequestIds(input) {
  const messages = Array.isArray(input) ? input : [input];
  return messages
    .filter(
      (message) =>
        message && typeof message.method === "string" && hasRequestId(message)
    )
    .map((message) => message.id);
}

function emitMessage(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
}

function emitBridgeError(input, err) {
  const statusCode = err && Number.isInteger(err.statusCode) ? err.statusCode : 0;
  const deliveredResponseKeys = new Set(
    err && Array.isArray(err.deliveredResponseKeys) ? err.deliveredResponseKeys : []
  );
  const requestIds = inputRequestIds(input).filter(
    (id) => !deliveredResponseKeys.has(requestIdKey(id))
  );
  if (requestIds.length > 0) {
    const errors = requestIds.map((id) => ({
      jsonrpc: "2.0",
      id,
      error: {
        code: -32000,
        message: "Galileo MCP transport error",
        data: statusCode ? { http_status: statusCode } : undefined,
      },
    }));
    emitMessage(Array.isArray(input) ? errors : errors[0]);
  } else if (inputRequestIds(input).length === 0) {
    warn("notification delivery failed" + (statusCode ? " (HTTP " + statusCode + ")" : ""));
  }
}

function errorWithDeliveredResponses(error, deliveredResponseKeys) {
  const statusCode = error && Number.isInteger(error.statusCode) ? error.statusCode : 0;
  const wrapped = new BridgeError(
    error && typeof error.message === "string" ? error.message : "MCP transport failed",
    statusCode
  );
  const keys = new Set(
    error && Array.isArray(error.deliveredResponseKeys)
      ? error.deliveredResponseKeys
      : []
  );
  for (const key of deliveredResponseKeys) keys.add(key);
  wrapped.deliveredResponseKeys = [...keys];
  return wrapped;
}

function updateProtocolState(input, message) {
  if (
    input.method === "initialize" &&
    isResponseMessage(message) &&
    sameId(input.id, message.id) &&
    message.result &&
    typeof message.result.protocolVersion === "string"
  ) {
    const value = message.result.protocolVersion;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      throw new BridgeError("MCP server returned an invalid protocol version");
    }
    protocolVersion = value;
  }
}

function parseJsonPayload(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (_) {
    throw new BridgeError("MCP server returned invalid JSON");
  }
  return parsed;
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
    this.onMessage(parseJsonPayload(data));
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

function stopServerEventStream() {
  if (eventReconnectTimer) clearTimeout(eventReconnectTimer);
  eventReconnectTimer = null;
  if (activeEventRequest) activeEventRequest.destroy();
  activeEventRequest = null;
}

function resetSessionState() {
  stopServerEventStream();
  sessionId = "";
  protocolVersion = "";
  eventReconnectAttempt = 0;
  eventStreamDisabled = false;
}

function isHandshakeMessage(input) {
  return Boolean(
    input &&
      !Array.isArray(input) &&
      (input.method === "initialize" || input.method === "notifications/initialized")
  );
}

function awaitSessionRecovery(requestSessionId) {
  if (sessionRecoveryPromise) return sessionRecoveryPromise;
  if (sessionId && sessionId !== requestSessionId) return Promise.resolve();
  return restartSession();
}

function postAfterRecovery(input, emitResponses) {
  if (sessionRecoveryPromise) {
    return sessionRecoveryPromise.then(() => postAfterRecovery(input, emitResponses));
  }
  return postMessage(input, { emitResponses, recoverSession: false });
}

function restartSession() {
  if (sessionRecoveryPromise) return sessionRecoveryPromise;
  if (!initializeMessage) {
    return Promise.reject(
      new BridgeError("MCP session expired before initialize replay")
    );
  }

  const recovery = (async () => {
    resetSessionState();
    await postMessage(initializeMessage, {
      emitResponses: false,
      recoverSession: false,
    });
    if (initializedMessage) {
      await postMessage(initializedMessage, {
        emitResponses: false,
        recoverSession: false,
      });
      startServerEventStream();
    }
  })();
  sessionRecoveryPromise = recovery.finally(() => {
    sessionRecoveryPromise = null;
  });
  return sessionRecoveryPromise;
}

function postMessage(input, options = {}) {
  const emitResponses = options.emitResponses !== false;
  const recoverSession = options.recoverSession !== false;
  if (recoverSession && sessionRecoveryPromise && !isHandshakeMessage(input)) {
    return sessionRecoveryPromise.then(() => postAfterRecovery(input, emitResponses));
  }
  const body = JSON.stringify(input);
  const requestSessionId = sessionId;
  const expectedResponseIds = inputRequestIds(input);
  const expectedResponseKeys = new Set(expectedResponseIds.map(requestIdKey));
  return new Promise((resolve, reject) => {
    let settled = false;
    let timedOut = false;
    let deadlineTimer = null;
    const deliveredResponseKeys = new Set();
    const clearDeadline = () => {
      if (deadlineTimer) clearTimeout(deadlineTimer);
      deadlineTimer = null;
    };
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearDeadline();
      callback(value);
    };
    const rejectOperation = (error) => {
      finish(reject, errorWithDeliveredResponses(error, deliveredResponseKeys));
    };
    const request = makeRequest("POST", body, (response) => {
      const status = response.statusCode || 0;
      if (
        status >= 200 &&
        status < 300 &&
        !Array.isArray(input) &&
        input.method === "initialize"
      ) {
        captureSession(response);
      }
      if (status >= 300 && status < 400) {
        response.resume();
        rejectOperation(new BridgeError("MCP redirects are disabled", status));
        return;
      }
      if (status < 200 || status >= 300) {
        response.resume();
        if (
          status === 404 &&
          requestSessionId &&
          recoverSession &&
          !isHandshakeMessage(input)
        ) {
          clearDeadline();
          const recovery = awaitSessionRecovery(requestSessionId);
          recovery
            .then(() => postAfterRecovery(input, emitResponses))
            .then(
              (value) => finish(resolve, value),
              (err) => rejectOperation(err)
            );
          return;
        }
        rejectOperation(new BridgeError("MCP server rejected request", status));
        return;
      }
      if (status === 202 || status === 204) {
        response.resume();
        if (expectedResponseKeys.size > 0) {
          rejectOperation(
            new BridgeError("MCP server accepted a request without a JSON-RPC response", status)
          );
        } else {
          finish(resolve);
        }
        return;
      }

      const contentType = String(response.headers["content-type"] || "")
        .split(";", 1)[0]
        .trim()
        .toLowerCase();
      if (contentType !== "application/json" && contentType !== "text/event-stream") {
        response.resume();
        rejectOperation(new BridgeError("MCP server returned an unsupported content type"));
        return;
      }
      let bytes = 0;
      let text = "";
      const matchingResponseKeys = new Set();
      const processMessage = (payload) => {
        const messages = Array.isArray(payload) ? payload : [payload];
        if (
          messages.length === 0 ||
          messages.some(
            (message) =>
              !message || typeof message !== "object" || Array.isArray(message)
          )
        ) {
          throw new BridgeError("MCP server returned an invalid JSON-RPC payload");
        }
        if (timedOut) return;
        const payloadResponseKeys = new Set();
        for (const message of messages) {
          updateProtocolState(input, message);
          if (isResponseMessage(message)) {
            const key = requestIdKey(message.id);
            if (expectedResponseKeys.has(key)) {
              matchingResponseKeys.add(key);
              payloadResponseKeys.add(key);
            }
          }
        }
        if (emitResponses) {
          emitMessage(payload);
          for (const key of payloadResponseKeys) deliveredResponseKeys.add(key);
        }
        if (
          contentType === "text/event-stream" &&
          (expectedResponseKeys.size === 0 ||
            matchingResponseKeys.size === expectedResponseKeys.size)
        ) {
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
      response.on("error", (err) => rejectOperation(err));
      response.on("end", () => {
        try {
          if (contentType === "text/event-stream") sse.end();
          else if (text.trim()) {
            processMessage(parseJsonPayload(text));
          }
          if (matchingResponseKeys.size !== expectedResponseKeys.size) {
            throw new BridgeError("MCP response did not include every request id");
          }
          finish(resolve);
        } catch (err) {
          rejectOperation(err);
        }
      });
    });
    deadlineTimer = setTimeout(() => {
      timedOut = true;
      const error = new BridgeError("MCP request timed out");
      rejectOperation(error);
      request.destroy();
    }, timeoutMs);
    deadlineTimer.unref();
    request.on("error", (err) => rejectOperation(err));
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
  const requestSessionId = sessionId;
  let request;
  request = makeRequest("GET", "", (response) => {
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
      if (status === 404 && requestSessionId) {
        const recovery = awaitSessionRecovery(requestSessionId);
        recovery
          .then(() => startServerEventStream())
          .catch((err) => warn(err.message || "could not restart MCP session"));
        return;
      }
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
  const messages = Array.isArray(message) ? message : [message];
  if (
    messages.length === 0 ||
    messages.some(
      (item) => !item || typeof item !== "object" || Array.isArray(item)
    )
  ) {
    emitMessage({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32600, message: "Invalid Request" },
    });
    return;
  }
  if (
    Array.isArray(message) &&
    messages.some((item) => isHandshakeMessage(item))
  ) {
    emitMessage({
      jsonrpc: "2.0",
      id: null,
      error: {
        code: -32600,
        message: "Initialize messages must not be batched",
      },
    });
    return;
  }
  const requestKeys = inputRequestIds(message).map(requestIdKey);
  if (new Set(requestKeys).size !== requestKeys.length) {
    emitMessage({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32600, message: "Batch request ids must be unique" },
    });
    return;
  }
  let operation;
  if (!Array.isArray(message) && message.method === "initialize") {
    if (initializationPromise) {
      emitMessage({
        jsonrpc: "2.0",
        id: hasRequestId(message) ? message.id : null,
        error: { code: -32600, message: "Initialize already received" },
      });
      return;
    }
    initializeMessage = message;
    initializationPromise = postMessage(message);
    readyPromise = initializationPromise;
    operation = initializationPromise;
  } else if (!Array.isArray(message) && message.method === "notifications/initialized") {
    initializedMessage = message;
    operation = readyPromise.then(() => postMessage(message)).then(() => startServerEventStream());
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
  stopServerEventStream();
  await Promise.allSettled([...pendingOperations]);
  await closeSession();
  process.exit(exitCode);
}

input.on("close", () => {
  shutdown(0);
});
process.on("SIGINT", () => shutdown(130));
process.on("SIGTERM", () => shutdown(143));
