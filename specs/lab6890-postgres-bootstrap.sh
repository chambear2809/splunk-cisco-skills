#!/usr/bin/env bash
# lab_6890 / amd-halo — bootstrap PostgreSQL for DB Connect validation.
# Creates database labval_dbx, role labval_dbx, sample table, and password file.
#
# Password file: /tmp/labval_dbx_pg_password (chmod 600, splunk-owned).
# Create or rotate with: bash skills/shared/scripts/write_secret_file.sh /tmp/labval_dbx_pg_password
#
# Note: Debian PostgreSQL 17 cluster listens on 127.0.0.1:5436 (not 5432).

set -euo pipefail

PASS_FILE="${PASS_FILE:-/tmp/labval_dbx_pg_password}"
PG_PORT="${PG_PORT:-5436}"

if ! command -v psql >/dev/null 2>&1; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql postgresql-contrib
fi
sudo systemctl enable --now postgresql

if [[ ! -f "${PASS_FILE}" ]]; then
  openssl rand -base64 24 | tr -d '=+/' | head -c 24 | sudo tee "${PASS_FILE}" >/dev/null
  sudo chmod 600 "${PASS_FILE}"
  sudo chown splunk:splunk "${PASS_FILE}"
fi
DB_PASS="$(sudo tr -d '\n' < "${PASS_FILE}")"

if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='labval_dbx'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE labval_dbx WITH LOGIN PASSWORD '${DB_PASS}';"
else
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE ROLE labval_dbx LOGIN PASSWORD '${DB_PASS}';"
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='labval_dbx'" | grep -q 1; then
  sudo -u postgres createdb -O labval_dbx labval_dbx
fi

sudo -u postgres psql -v ON_ERROR_STOP=1 -d labval_dbx <<'SQL'
CREATE TABLE IF NOT EXISTS public.labval_events (
  id SERIAL PRIMARY KEY,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  event_type TEXT NOT NULL,
  message TEXT NOT NULL
);
GRANT ALL ON TABLE public.labval_events TO labval_dbx;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO labval_dbx;
TRUNCATE public.labval_events;
INSERT INTO public.labval_events (event_type, message, updated_at) VALUES
  ('bootstrap', 'lab validation seed row 1', NOW() - INTERVAL '10 minutes'),
  ('bootstrap', 'lab validation seed row 2', NOW() - INTERVAL '5 minutes'),
  ('bootstrap', 'lab validation seed row 3', NOW());
SQL

PG_HBA="$(sudo -u postgres psql -tAc 'SHOW hba_file')"
if ! sudo grep -q 'labval_dbx' "${PG_HBA}" 2>/dev/null; then
  echo "host    labval_dbx    labval_dbx    127.0.0.1/32    scram-sha-256" | sudo tee -a "${PG_HBA}" >/dev/null
  echo "host    labval_dbx    labval_dbx    ::1/128         scram-sha-256" | sudo tee -a "${PG_HBA}" >/dev/null
  sudo systemctl reload postgresql
fi

export PGPASSWORD="${DB_PASS}"
psql -h 127.0.0.1 -p "${PG_PORT}" -U labval_dbx -d labval_dbx -c 'SELECT count(*) AS rows FROM public.labval_events;'
unset PGPASSWORD
echo "OK: PostgreSQL lab database ready on port ${PG_PORT}."
