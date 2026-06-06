#!/usr/bin/env python3
"""Render generic Splunk Browser RUM setup assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def init_payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {
        "realm": args.realm,
        "rumAccessToken": args.rum_token_reference,
        "applicationName": args.application_name,
        "deploymentEnvironment": args.environment,
        "version": args.version,
    }
    if args.enable_session_replay:
        payload["sessionReplay"] = {
            "enabled": True,
            "sampleRate": args.sample_rate,
            "privacy": {
                "maskAllText": str(args.mask_all_text).lower() == "true",
                "sensitivityRules": [
                    {"selector": "[data-private]", "rule": "mask"},
                    {"selector": "input[type=password]", "rule": "block"},
                ],
            },
        }
    return payload


def js_object(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2)


def cdn_snippet(args: argparse.Namespace) -> str:
    replay = ""
    if args.enable_session_replay:
        replay = '<script src="https://cdn.observability.splunkcloud.com/o11y-gdi-rum/v1/splunk-otel-web-session-recorder.js" crossorigin="anonymous"></script>\n'
    return f"""<!-- Place before the application bundle starts. -->
<script src="https://cdn.observability.splunkcloud.com/o11y-gdi-rum/v1/splunk-otel-web.js" crossorigin="anonymous"></script>
{replay}<script>
  SplunkRum.init({js_object(init_payload(args))});
</script>
"""


def npm_init(args: argparse.Namespace) -> str:
    replay_import = ""
    replay_comment = ""
    if args.enable_session_replay:
        replay_import = "\n// Import the Session Replay recorder package according to the current Splunk RUM docs."
        replay_comment = "\n// Review privacy and consent before enabling replay in production."
    return f"""import {{ SplunkRum }} from '@splunk/otel-web';{replay_import}

SplunkRum.init({js_object(init_payload(args))});
{replay_comment}
"""


def source_map_upload(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

: "${{SPLUNK_O11Y_TOKEN_FILE:?Set SPLUNK_O11Y_TOKEN_FILE to an Observability API token file}}"
: "${{ASSETS_DIR:=dist}}"
command -v splunk-rum >/dev/null 2>&1 || {{
  echo "Install the Splunk RUM CLI first: npm install -g @splunk/rum-cli" >&2
  exit 2
}}

export SPLUNK_REALM="{args.realm}"
export SPLUNK_ACCESS_TOKEN="$(<"${{SPLUNK_O11Y_TOKEN_FILE}}")"
trap 'unset SPLUNK_ACCESS_TOKEN' EXIT

splunk-rum sourcemaps inject --path "${{ASSETS_DIR}}"

splunk-rum sourcemaps upload \\
  --app-name "{args.application_name}" \\
  --app-version "{args.version}" \\
  --path "${{ASSETS_DIR}}"
"""


def webpack_plugin(args: argparse.Namespace) -> str:
    return f"""// Merge into webpack.config.js after installing @splunk/rum-build-plugins.
// Export SPLUNK_ACCESS_TOKEN in CI from SPLUNK_O11Y_TOKEN_FILE before the build.
const {{ SplunkRumWebpackPlugin }} = require('@splunk/rum-build-plugins');

module.exports = {{
  plugins: [
    new SplunkRumWebpackPlugin({{
      applicationName: '{args.application_name}',
      version: '{args.version}',
      sourceMaps: {{
        realm: '{args.realm}',
        token: process.env.SPLUNK_ACCESS_TOKEN,
        disableUpload: process.env.NODE_ENV !== 'production'
      }}
    }})
  ]
}};
"""


def next_snippet(args: argparse.Namespace) -> str:
    return f"""// next.config.js source-map handoff. Keep applicationName/version aligned with SplunkRum.init.
const nextConfig = {{
  productionBrowserSourceMaps: true,
  env: {{
    NEXT_PUBLIC_SPLUNK_RUM_REALM: '{args.realm}',
    NEXT_PUBLIC_SPLUNK_RUM_APP: '{args.application_name}',
    NEXT_PUBLIC_SPLUNK_RUM_ENV: '{args.environment}',
    NEXT_PUBLIC_SPLUNK_RUM_VERSION: '{args.version}'
  }}
}};

module.exports = nextConfig;
"""


def vite_env(args: argparse.Namespace) -> str:
    return f"""VITE_SPLUNK_RUM_REALM={args.realm}
VITE_SPLUNK_RUM_APP={args.application_name}
VITE_SPLUNK_RUM_ENV={args.environment}
VITE_SPLUNK_RUM_VERSION={args.version}
VITE_SPLUNK_RUM_TOKEN_REFERENCE={args.rum_token_reference}
"""


def csp(args: argparse.Namespace) -> str:
    return f"""Content-Security-Policy: script-src 'self' cdn.observability.splunkcloud.com; connect-src 'self' rum-ingest.{args.realm}.observability.splunkcloud.com; worker-src 'self' blob:;
"""


def apm_validation(args: argparse.Namespace) -> str:
    return f"""# RUM To APM Validation

Expected application: `{args.application_name}`
Environment: `{args.environment}`

Run after deployment:

```bash
curl -fsSI https://example.com | grep -i '^server-timing:.*traceparent'
```

If the header is missing, configure backend OpenTelemetry instrumentation to
emit `Server-Timing: traceparent` for page, XHR, and fetch responses. Use
`splunk-observability-k8s-auto-instrumentation-setup` for Kubernetes workloads
or a runtime APM setup path for VM/container applications.
"""


def plan(args: argparse.Namespace) -> str:
    replay = "enabled" if args.enable_session_replay else "disabled"
    return f"""# Splunk Browser RUM Plan

Application: `{args.application_name}`
Environment: `{args.environment}`
Version: `{args.version}`
Realm: `{args.realm}`
Framework hint: `{args.framework}`
Session Replay: `{replay}`

## Assets

- `cdn-snippet.html`: direct HTML/CDN instrumentation.
- `npm-init.ts`: source-level `@splunk/otel-web` initialization.
- `next.config.snippet.js`, `vite.env.example`, `webpack-sourcemap-plugin.js`: framework/build handoffs.
- `source-map-upload.sh`: server-to-server source-map upload helper.
- `csp-header.txt`: baseline CSP update.
- `rum-to-apm-validation.md`: trace linking check.

## Handoffs

- Dashboards: `splunk-observability-dashboard-builder`.
- Detectors and Synthetic follow-up: `splunk-observability-native-ops`.
- Kubernetes injection: `splunk-observability-k8s-frontend-rum-setup`.
"""


def metadata(args: argparse.Namespace, files: list[str]) -> dict[str, object]:
    return {
        "skill": "splunk-observability-browser-rum-setup",
        "application_name": args.application_name,
        "environment": args.environment,
        "version": args.version,
        "realm": args.realm,
        "framework": args.framework,
        "session_replay_enabled": args.enable_session_replay,
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="splunk-observability-browser-rum-rendered")
    parser.add_argument("--application-name", default="frontend")
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--realm", default="us0")
    parser.add_argument("--framework", default="generic")
    parser.add_argument("--rum-token-reference", default="${SPLUNK_RUM_TOKEN}")
    parser.add_argument("--enable-session-replay", action="store_true")
    parser.add_argument("--mask-all-text", default="true")
    parser.add_argument("--sample-rate", default="0.05")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    output = Path(args.output_dir).expanduser().resolve()
    files = [
        "browser-rum-plan.md",
        "cdn-snippet.html",
        "npm-init.ts",
        "next.config.snippet.js",
        "vite.env.example",
        "webpack-sourcemap-plugin.js",
        "source-map-upload.sh",
        "csp-header.txt",
        "rum-to-apm-validation.md",
        "metadata.json",
    ]
    write(output / "browser-rum-plan.md", plan(args))
    write(output / "cdn-snippet.html", cdn_snippet(args))
    write(output / "npm-init.ts", npm_init(args))
    write(output / "next.config.snippet.js", next_snippet(args))
    write(output / "vite.env.example", vite_env(args))
    write(output / "webpack-sourcemap-plugin.js", webpack_plugin(args))
    write(output / "source-map-upload.sh", source_map_upload(args))
    write(output / "csp-header.txt", csp(args))
    write(output / "rum-to-apm-validation.md", apm_validation(args))
    write(output / "metadata.json", json.dumps(metadata(args, files), indent=2, sort_keys=True))

    result = {"ok": True, "output_dir": str(output), "files": files, "metadata": metadata(args, files)}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Rendered Browser RUM setup assets to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
