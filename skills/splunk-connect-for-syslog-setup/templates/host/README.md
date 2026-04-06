# SC4S Host Templates

These files are the base templates for host-managed SC4S deployments.

## Files

- `env_file.example` — minimal SC4S environment variables
- `docker-compose.yml` — compose-based container deployment
- `sc4s.service` — systemd unit for Docker or Podman

## Placeholder Conventions

The render script replaces placeholders such as:

- `{{SC4S_ROOT}}`
- `{{SC4S_IMAGE}}`
- `{{SC4S_PERSIST_VOLUME}}`
- `{{RUNTIME_BIN}}`
- `{{PORTS_BLOCK}}`
- `{{HEC_BASE_URL}}`, `{{HEC_TOKEN}}`

## Notes

- `env_file.example` is intentionally token-safe and uses placeholders.
- The rendered host output writes a local-only `env_file` with mode `600` when
  a HEC token file is supplied.
- Compose mode publishes syslog listener ports directly and uses relative paths
  (`./env_file`, `./local`, `./archive`, `./tls`) so the rendered directory can
  be installed or upgraded in place.
- `compose-up.sh` pulls images before running `compose up -d`.
- `systemd-install.sh` syncs rendered files into `SC4S_ROOT`, preserves
  unrelated files already present there, and then reloads and restarts `sc4s`.
- The default repo-local render path is `./sc4s-rendered/`, which is gitignored.
  When a real HEC token is being rendered, custom output directories inside the
  repo are blocked to reduce accidental secret commits.
- Systemd mode uses host networking by default, matching the upstream Podman and
  Docker systemd guidance.
