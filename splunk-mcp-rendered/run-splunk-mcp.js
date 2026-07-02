#!/usr/bin/env node
"use strict";

// Cross-platform MCP bridge for Splunk MCP Server.
// Works on macOS, Linux, and Windows (Git Bash, native cmd/PowerShell).
// Requires: Node.js and a preinstalled, operator-vetted mcp-remote 0.1.38.

const fs = require("fs");
const net = require("net");
const path = require("path");
const { execFileSync, spawn } = require("child_process");

const scriptDir = __dirname;
const envFile = path.join(scriptDir, ".env.splunk-mcp");
const allowedEnvKeys = new Set([
  "SPLUNK_MCP_URL",
  "SPLUNK_MCP_GATEWAY_MODE",
  "SPLUNK_MCP_INSECURE_TLS",
  "SPLUNK_MCP_TOKEN",
  "SPLUNK_MCP_HEADER_AUTHORIZATION",
  "SPLUNK_MCP_HEADER_SPLUNK_TENANT",
  "SPLUNK_MCP_HEADER_X_SF_TOKEN",
  "SPLUNK_MCP_HEADER_X_SF_REALM",
]);

// Load .env.splunk-mcp if present (KEY=VALUE lines, no export, no quoting needed).
function parseShellWord(value) {
  let result = "";
  let state = "normal";
  for (let i = 0; i < value.length; i++) {
    const ch = value[i];
    if (state === "single") {
      if (ch === "'") {
        state = "normal";
      } else {
        result += ch;
      }
      continue;
    }
    if (state === "double") {
      if (ch === '"') {
        state = "normal";
      } else if (ch === "\\") {
        i += 1;
        if (i < value.length) result += value[i];
      } else {
        result += ch;
      }
      continue;
    }
    if (state === "ansi") {
      if (ch === "'") {
        state = "normal";
      } else if (ch === "\\") {
        i += 1;
        const next = value[i];
        if (next === "n") result += "\n";
        else if (next === "r") result += "\r";
        else if (next === "t") result += "\t";
        else if (next !== undefined) result += next;
      } else {
        result += ch;
      }
      continue;
    }
    if (ch === "'") {
      state = "single";
    } else if (ch === '"') {
      state = "double";
    } else if (ch === "$" && value[i + 1] === "'") {
      state = "ansi";
      i += 1;
    } else if (ch === "\\") {
      i += 1;
      if (i < value.length) result += value[i];
    } else {
      result += ch;
    }
  }
  if (state !== "normal") throw new Error("unterminated quoted value");
  return result;
}

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;
  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    if (!allowedEnvKeys.has(key)) {
      process.stderr.write("splunk-mcp: unsupported key in " + filePath + ": " + key + "\n");
      process.exit(1);
    }
    let val;
    try {
      val = parseShellWord(trimmed.slice(eq + 1).trim());
    } catch (error) {
      process.stderr.write("splunk-mcp: invalid value in " + filePath + " for " + key + ": " + error.message + "\n");
      process.exit(1);
    }
    // Pre-existing env vars take precedence.
    if (!(key in process.env)) {
      process.env[key] = val;
    }
  }
}

loadEnvFile(envFile);

const mcpUrl = process.env.SPLUNK_MCP_URL;
const gatewayMode = process.env.SPLUNK_MCP_GATEWAY_MODE || "platform";

if (!mcpUrl) {
  process.stderr.write("splunk-mcp: set SPLUNK_MCP_URL in " + envFile + "\n");
  process.exit(1);
}

function hasEnv(name) {
  return Boolean(process.env[name]);
}

function fail(message) {
  process.stderr.write("splunk-mcp: " + message + "\n");
  process.exit(1);
}

function validateRuntimeUrl(rawUrl) {
  let parsed;
  if (/[\u0000-\u001F\u007F]/.test(rawUrl)) {
    fail("SPLUNK_MCP_URL contains control characters");
  }
  try {
    parsed = new URL(rawUrl);
  } catch (_) {
    fail("SPLUNK_MCP_URL must be an absolute HTTPS URL");
  }
  if (parsed.username || parsed.password || !parsed.hostname || parsed.hash) {
    fail("SPLUNK_MCP_URL must include a host and must not contain userinfo");
  }
  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  const loopback = host === "localhost" ||
    (net.isIP(host) === 4 && host.startsWith("127.")) ||
    host === "::1" || host === "0:0:0:0:0:0:0:1";
  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && loopback)) {
    fail("SPLUNK_MCP_URL must use HTTPS; HTTP is allowed only for loopback");
  }
  if (process.env.SPLUNK_MCP_INSECURE_TLS === "1" && !loopback) {
    fail("SPLUNK_MCP_INSECURE_TLS=1 is restricted to loopback; configure a trusted CA for remote endpoints");
  }
}

validateRuntimeUrl(mcpUrl);

for (const name of [
  "SPLUNK_MCP_TOKEN",
  "SPLUNK_MCP_HEADER_AUTHORIZATION",
  "SPLUNK_MCP_HEADER_SPLUNK_TENANT",
  "SPLUNK_MCP_HEADER_X_SF_TOKEN",
  "SPLUNK_MCP_HEADER_X_SF_REALM",
]) {
  const value = process.env[name];
  if (value && (/\r|\n/.test(value) || value.length > 65536)) {
    fail(name + " contains a forbidden line break or exceeds 65536 characters");
  }
}

if (!["platform", "o11y", "combined"].includes(gatewayMode)) {
  fail("SPLUNK_MCP_GATEWAY_MODE must be platform, o11y, or combined");
}

if (gatewayMode === "platform") {
  if (!hasEnv("SPLUNK_MCP_TOKEN") && !hasEnv("SPLUNK_MCP_HEADER_AUTHORIZATION")) {
    fail("set SPLUNK_MCP_TOKEN or SPLUNK_MCP_HEADER_AUTHORIZATION in " + envFile);
  }
} else if (gatewayMode === "o11y") {
  if (!hasEnv("SPLUNK_MCP_HEADER_X_SF_TOKEN") || !hasEnv("SPLUNK_MCP_HEADER_X_SF_REALM")) {
    fail("set SPLUNK_MCP_HEADER_X_SF_TOKEN and SPLUNK_MCP_HEADER_X_SF_REALM in " + envFile);
  }
} else if (gatewayMode === "combined") {
  if (!hasEnv("SPLUNK_MCP_HEADER_AUTHORIZATION") && !hasEnv("SPLUNK_MCP_TOKEN")) {
    fail("set SPLUNK_MCP_HEADER_AUTHORIZATION or SPLUNK_MCP_TOKEN in " + envFile);
  }
  if (!hasEnv("SPLUNK_MCP_HEADER_SPLUNK_TENANT") || !hasEnv("SPLUNK_MCP_HEADER_X_SF_TOKEN") || !hasEnv("SPLUNK_MCP_HEADER_X_SF_REALM")) {
    fail("set SPLUNK_MCP_HEADER_SPLUNK_TENANT, SPLUNK_MCP_HEADER_X_SF_TOKEN, and SPLUNK_MCP_HEADER_X_SF_REALM in " + envFile);
  }
}

if (process.env.SPLUNK_MCP_INSECURE_TLS === "1") {
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
}

// Resolve a preinstalled, operator-vetted mcp-remote. Never download and
// execute a mutable npm package during MCP startup.
function findMcpRemote() {
  try {
    // On Windows `where`, on Unix `which` -- execFileSync with a
    // try/catch is cross-platform without requiring a shell.
    const result = execFileSync(
      process.platform === "win32" ? "where" : "which",
      ["mcp-remote"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }
    ).trim().split(/\r?\n/)[0].trim();
    if (result) return { cmd: result, args: [] };
  } catch (_) {
    // not found on PATH
  }
  fail("mcp-remote not found on PATH; install the vetted version with: npm install -g mcp-remote@0.1.38");
}

function readPackageMetadata(filePath) {
  let current = path.dirname(fs.realpathSync(filePath));
  while (true) {
    const candidate = path.join(current, "package.json");
    if (fs.existsSync(candidate)) {
      try {
        const metadata = JSON.parse(fs.readFileSync(candidate, "utf8"));
        if (metadata.name === "mcp-remote") return metadata;
      } catch (_) {
        // Keep walking; a parent package.json may be the package root.
      }
    }
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  if (process.platform !== "win32") return null;
  try {
    const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
    const npmRoot = execFileSync(npmCommand, ["root", "-g"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    const expectedShimDir = path.dirname(npmRoot).toLowerCase();
    if (path.dirname(path.resolve(filePath)).toLowerCase() !== expectedShimDir) return null;
    return JSON.parse(fs.readFileSync(path.join(npmRoot, "mcp-remote", "package.json"), "utf8"));
  } catch (_) {
    return null;
  }
}

const { cmd, args: prefixArgs } = findMcpRemote();
const mcpRemotePackage = readPackageMetadata(cmd);
if (!mcpRemotePackage || mcpRemotePackage.name !== "mcp-remote" || mcpRemotePackage.version !== "0.1.38") {
  fail("mcp-remote 0.1.38 is required; install it with: npm install -g mcp-remote@0.1.38");
}
// Pass literal placeholders so mcp-remote performs ${VAR} substitution
// at runtime against the inherited env. This keeps secret header values out
// of argv (visible to process listings).
const headerArgs = [];
const remoteArgs = [mcpUrl];
if (gatewayMode !== "platform") {
  remoteArgs.push("--transport", "http-only", "--allow-http");
}
function addHeader(name, placeholder) {
  headerArgs.push("--header", name + ": " + placeholder);
}
if (hasEnv("SPLUNK_MCP_HEADER_AUTHORIZATION")) {
  addHeader("Authorization", "${SPLUNK_MCP_HEADER_AUTHORIZATION}");
} else if (hasEnv("SPLUNK_MCP_TOKEN")) {
  addHeader("Authorization", "Bearer ${SPLUNK_MCP_TOKEN}");
}
if (hasEnv("SPLUNK_MCP_HEADER_SPLUNK_TENANT")) {
  addHeader("splunk_tenant", "${SPLUNK_MCP_HEADER_SPLUNK_TENANT}");
}
if (hasEnv("SPLUNK_MCP_HEADER_X_SF_TOKEN")) {
  addHeader("X-SF-TOKEN", "${SPLUNK_MCP_HEADER_X_SF_TOKEN}");
}
if (hasEnv("SPLUNK_MCP_HEADER_X_SF_REALM")) {
  addHeader("X-SF-REALM", "${SPLUNK_MCP_HEADER_X_SF_REALM}");
}

const child = spawn(
  cmd,
  [...prefixArgs, ...remoteArgs, ...headerArgs],
  { stdio: "inherit" }
);

child.on("error", function(err) {
  process.stderr.write(
    "splunk-mcp: failed to start mcp-remote: " + err.message + "\n" +
    "  Install it with: npm install -g mcp-remote@0.1.38\n"
  );
  process.exit(1);
});

child.on("exit", function(code, signal) {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code !== null ? code : 0);
  }
});
