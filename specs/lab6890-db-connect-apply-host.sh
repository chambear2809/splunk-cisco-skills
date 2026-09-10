#!/usr/bin/env bash
# lab_6890 / amd-halo — apply DB Connect identity, connection, and inputs via REST.
# Run on the Splunk host as a user that can sudo to splunk and read admin password file.
#
# Prerequisites:
#   - PostgreSQL lab database (see specs/lab6890-postgres-bootstrap.sh)
#   - /tmp/labval_dbx_pg_password (chmod 600, splunk-owned)
#   - splunk_app_db_connect + Splunk_JDBC_postgress installed
#   - Task server running on Java 17
#
# Never pass database passwords on the command line; read from password_file only.

set -euo pipefail

SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
PASS_FILE="${PASS_FILE:-/tmp/labval_dbx_pg_password}"
ADMIN_PASS_FILE="${ADMIN_PASS_FILE:-${SPLUNK_HOME}/var/run/.labval_admin_pass}"
REST_BASE="https://127.0.0.1:8089/servicesNS/nobody/splunk_app_db_connect/db_connect/dbxproxy"

[[ -r "${PASS_FILE}" ]] || { echo "ERROR: missing password file: ${PASS_FILE}" >&2; exit 1; }
[[ -r "${ADMIN_PASS_FILE}" ]] || { echo "ERROR: missing admin password file: ${ADMIN_PASS_FILE}" >&2; exit 1; }

ADMIN_PASS="$(tr -d '\r\n' < "${ADMIN_PASS_FILE}")"
DB_PASS="$(tr -d '\r\n' < "${PASS_FILE}")"

curl_json() {
  curl -sk -u "admin:${ADMIN_PASS}" -H "Content-Type: application/json" "$@"
}

echo "Creating index labval_dbx (ignore if exists)..."
curl -sk -u "admin:${ADMIN_PASS}" -X POST "https://127.0.0.1:8089/services/data/indexes" \
  -d name=labval_dbx -d datatype=event -d maxTotalDataSizeMB=512 >/dev/null 2>&1 || true

echo "Creating identity labval_pg_identity..."
curl_json -X POST "${REST_BASE}/identities" \
  -d "{\"name\":\"labval_pg_identity\",\"username\":\"labval_dbx\",\"password\":\"${DB_PASS}\"}" >/dev/null

echo "Creating connection labval_pg_local (postgres @ 127.0.0.1:5436)..."
curl_json -X POST "${REST_BASE}/connections" \
  -d '{"name":"labval_pg_local","connection_type":"postgres","host":"127.0.0.1","port":5436,"database":"labval_dbx","identity":"labval_pg_identity","jdbcUrl":"jdbc:postgresql://127.0.0.1:5436/labval_dbx","jdbcUseSSL":false,"useConnectionPool":true}' >/dev/null

echo "Creating batch input labval_events_batch..."
curl_json -X POST "${REST_BASE}/inputs" \
  -d '{"disabled":false,"timestamp_format":"","template_name":"","timestampType":"current","mode":"batch","query":"SELECT id, updated_at, event_type, message FROM public.labval_events","connection":"labval_pg_local","name":"labval_events_batch","description":"lab validation batch input","interval":"120","sourcetype":"dbx:labval_events","index":"labval_dbx"}' >/dev/null || true

echo "Creating rising input labval_events_delta..."
curl_json -X POST "${REST_BASE}/inputs" \
  -d '{"disabled":false,"timestamp_format":"","template_name":"","timestampType":"current","index_time_mode":"current","mode":"rising","query":"SELECT id, updated_at, event_type, message FROM public.labval_events WHERE updated_at > ? ORDER BY updated_at ASC","connection":"labval_pg_local","name":"labval_events_delta","description":"lab validation rising input","interval":"120","sourcetype":"dbx:labval_events","index":"labval_dbx","rising_column_name":"updated_at","rising_column_index":2,"checkpoint":{"value":"1970-01-01 00:00:00+00","appVersion":"4.3.0","columnType":93,"timestamp":"1970-01-01T00:00:00.000+00:00"}}' >/dev/null || true

echo "Verifying dbxquery..."
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" login -auth "admin:${ADMIN_PASS}" >/dev/null 2>&1
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" search \
  '| dbxquery connection="labval_pg_local" query="SELECT count(*) AS cnt FROM public.labval_events"' \
  -auth "admin:${ADMIN_PASS}" | tail -5

echo "OK: DB Connect lab objects applied."
