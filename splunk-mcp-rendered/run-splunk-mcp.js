#!/usr/bin/env node
"use strict";

// Cross-platform MCP bridge for Splunk MCP Server.
// Works on macOS, Linux, and Windows (Git Bash, native cmd/PowerShell).
// Requires: node (comes with mcp-remote) and npx mcp-remote.

const fs = require("fs");
const path = require("path");
const { execFileSync, spawn } = require("child_process");

const scriptDir = __dirname;
const envFile = path.join(scriptDir, ".env.splunk-mcp");

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
    const val = parseShellWord(trimmed.slice(eq + 1).trim());
    // Pre-existing env vars take precedence.
    if (!(key in process.env)) {
      process.env[key] = val;
    }
  }
}

loadEnvFile(envFile);

const mcpUrl = process.env.SPLUNK_MCP_URL;
const mcpToken = process.env.SPLUNK_MCP_TOKEN;

if (!mcpUrl) {
  process.stderr.write("splunk-mcp: set SPLUNK_MCP_URL in " + envFile + "\n");
  process.exit(1);
}
if (!mcpToken) {
  process.stderr.write("splunk-mcp: set SPLUNK_MCP_TOKEN in " + envFile + "\n");
  process.exit(1);
}

if (process.env.SPLUNK_MCP_INSECURE_TLS === "1") {
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
}

// Resolve mcp-remote: prefer global install, fall back to npx.
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
  // Fall back to npx (always available if Node.js is installed).
  return { cmd: process.platform === "win32" ? "npx.cmd" : "npx", args: ["mcp-remote"] };
}

const { cmd, args: prefixArgs } = findMcpRemote();
// Pass the literal placeholder so mcp-remote performs ${VAR} substitution
// at runtime against the inherited env. This keeps SPLUNK_MCP_TOKEN out of
// argv (visible to `ps`) while still sending the real bearer value
// upstream. mcpToken is read above only to fail fast if it is unset.
const tokenHeader = "Authorization: Bearer ${SPLUNK_MCP_TOKEN}";
void mcpToken;
const child = spawn(
  cmd,
  [...prefixArgs, mcpUrl, "--header", tokenHeader],
  { stdio: "inherit" }
);

child.on("error", function(err) {
  process.stderr.write(
    "splunk-mcp: failed to start mcp-remote: " + err.message + "\n" +
    "  Install it with: npm install -g mcp-remote\n"
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
