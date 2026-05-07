# Splunk Connect for OTLP Reference

## Audited Release

- Splunkbase app: `8704`
- App/package ID: `splunk-connect-for-otlp`
- Release: `0.4.1`
- Published app record: May 6, 2026
- Splunk compatibility: `9.4` through `10.3`
- SHA256: `fde0d93532703e04ab5aa544815d52232ef62afae2c0a55e374dc74d2d58f9d1`
- MD5: `6190585a3c12cb9f273f7f9f11cdb3be`

GitHub release `v0.4.1` package hash matched the Splunkbase package metadata.
Upstream `go test ./...` passed against the inspected release source.

## Package Contents

Expected `0.4.1` package file list:

```text
splunk-connect-for-otlp/README/inputs.conf.spec
splunk-connect-for-otlp/default/app.conf
splunk-connect-for-otlp/default/data/ui/manager/splunk-connect-for-otlp.xml
splunk-connect-for-otlp/default/inputs.conf
splunk-connect-for-otlp/default/props.conf
splunk-connect-for-otlp/linux_x86_64/bin/splunk-connect-for-otlp
splunk-connect-for-otlp/metadata/default.meta
splunk-connect-for-otlp/windows_x86_64/bin/splunk-connect-for-otlp
```

Default `inputs.conf` values:

```ini
[splunk-connect-for-otlp]
start_by_shell = false
interval = 0
sourcetype = splunk-connect-for-otlp
grpc_port = 4317
http_port = 4318
listen_address = 0.0.0.0
enableSSL = 0
serverCert =
serverKey =
```

Default `props.conf`:

```ini
[splunk-connect-for-otlp]
INDEXED_EXTRACTIONS = HEC
```

There are no dashboards, saved searches, setup pages, Python files, KV Store
collections, custom REST handlers, or default `bin/` script. The package has
Linux x86_64 and Windows x86_64 binaries only. Validation should flag macOS
and uncertain Windows executable naming rather than assuming support.

## Modular Input Fields

Configure only fields actually present in the inspected package plus implicit
Splunk modular-input fields:

- `grpc_port`
- `http_port`
- `listen_address`
- `enableSSL`
- `serverCert`
- `serverKey`
- `disabled`
- `index`
- `host`
- `source`
- `sourcetype`
- `interval`

The skill rejects port `0` for real deployments even though upstream source
tests use it as a local fixture.

## REST Paths

Collection endpoint:

```text
/servicesNS/nobody/splunk-connect-for-otlp/data/inputs/splunk-connect-for-otlp
```

Stanza endpoint:

```text
/servicesNS/nobody/splunk-connect-for-otlp/data/inputs/splunk-connect-for-otlp/{input_name}
```

The stanza name corresponds to `splunk-connect-for-otlp://{input_name}`.

## HEC Token Dependency

Inbound OTLP requests must include the Splunk HEC auth format:

```text
Authorization: Splunk <HEC_TOKEN>
```

The inspected binary queries `data/inputs/http`, authenticates the supplied
token, validates allowed indexes, and emits HEC-shaped JSON to stdout. Token
creation, token rotation, default index, and allowed-index management remain
delegated to `splunk-hec-service-setup`.

## Sender Configuration

Preferred sender metadata:

- `com.splunk.index`
- `com.splunk.sourcetype`
- `com.splunk.source`
- `host.name`

OTLP HTTP paths must be signal-specific:

- `/v1/logs`
- `/v1/metrics`
- `/v1/traces`

gRPC senders use `host:4317`. HTTP senders use `http(s)://host:4318`.

## Conservative Repair IDs

Repair is intentionally narrow. The setup wrapper can apply low-risk state
changes or render handoffs, while the doctor report explains the operator step.

| Fix ID | Behavior |
| --- | --- |
| `APP_MISSING` | Install app `8704` through `splunk-app-install`. |
| `APP_OUTDATED` | Update app `8704` through `splunk-app-install`. |
| `APP_DISABLED` | Report required manual/app-management action. |
| `WRONG_TIER` | Report topology handoff. |
| `PLATFORM_UNSUPPORTED_LOCAL_BINARY` | Report Linux/Windows x86_64 package caveat. |
| `INPUT_MISSING` | Configure a default modular input with reviewed values. |
| `INPUT_DISABLED` | Enable the named modular input. |
| `BAD_PORT` | Reconfigure with ports `4317` and `4318`. |
| `PORT_CONFLICT` | Report listener conflict and keep Splunk config unchanged. |
| `BAD_LISTEN_ADDRESS` | Reconfigure to `0.0.0.0` or a supplied listen address. |
| `CLOUD_CLASSIC_REQUIRES_IDM_OR_HF` | Render heavy-forwarder/IDM handoff. |
| `TLS_FILES_MISSING` | Report cert/key file repair. |
| `TLS_SENDER_RECEIVER_MISMATCH` | Re-render sender assets matching receiver TLS mode. |
| `HEC_GLOBAL_DISABLED` | Delegate HEC enablement to `splunk-hec-service-setup`. |
| `HEC_TOKEN_MISSING` | Render a HEC handoff. |
| `HEC_TOKEN_DISABLED` | Delegate token enablement to `splunk-hec-service-setup`. |
| `HEC_ALLOWED_INDEX_MISSING` | Render a HEC allowed-index handoff. |
| `SENDER_INDEX_FORBIDDEN` | Re-render sender metadata with an allowed index. |
| `SENDER_AUTH_HEADER_MISSING` | Re-render sender examples with HEC auth header. |
| `SENDER_HTTP_PATH_INVALID` | Re-render sender HTTP paths. |
| `SENDER_PORT_MISMATCH` | Re-render sender endpoint ports. |
| `INTERNAL_EXEC_ERROR` | Report `_internal` error context. |
| `INTERNAL_BIND_FAILURE` | Report bind failure and port conflict checks. |
| `INTERNAL_AUTH_FAILURE` | Report HEC auth failure and sender/token checks. |
| `INTERNAL_INDEX_DENIED` | Report allowed-index mismatch. |

## Validation Checklist

- App installed, enabled, and version visible.
- Runtime platform has a packaged binary.
- Modular input stanzas exist and are enabled where expected.
- `grpc_port` and `http_port` are valid non-zero TCP ports.
- Listen address is explicit and reachable from expected sender networks.
- TLS receiver settings and sender scheme agree.
- HEC global input is enabled.
- HEC token exists, is enabled, and allows `com.splunk.index`.
- `_internal` has no recent bind, auth, ExecProcessor, ModularInputs, or
  index-denied errors for the app.
- A smoke search sees events routed to the expected index.
