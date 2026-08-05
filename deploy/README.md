# Server deployment (RHEL / podman)

Runs the **read-only API** (`backend.src.mobile_server`) in a container: the
token-protected `/api/mobile/*` sync endpoints plus the analysis and
investigations routers, backed by the shared SQLite database. This process
never contacts Oura — data ingestion is a separate concern (see the project
roadmap for the Oura API v2 puller).

## Build

From the repository root:

```bash
podman build -t ouracle -f deploy/Containerfile .
```

## Configure

```bash
mkdir -p ~/.config/ouracle
cp deploy/env.example ~/.config/ouracle/env
# Generate and paste a token:
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
$EDITOR ~/.config/ouracle/env
```

`OURACLE_MOBILE_TOKEN` is required; setting it implicitly enables the
API. All state (SQLite DB, config JSON, logs) lives in the `ouracle-data`
volume mounted at `/data` (`OURACLE_DATA_DIR`).

## Run as a service (quadlet)

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/ouracle.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start ouracle
loginctl enable-linger $USER
```

## Quick run (no systemd)

```bash
podman run --rm -p 8037:8037 \
  -v ouracle-data:/data:Z \
  -e OURACLE_MOBILE_TOKEN=your-token \
  ouracle
```

## Verify

```bash
curl -H "Authorization: Bearer your-token" http://localhost:8037/api/mobile/ping
```

Expect `{"status":"ok", ...}` with `latest_day: null` until data has been
ingested into the volume's database.

## Seeding data

Until the API v2 puller lands, copy an existing `oura_database.db` (from the
desktop app's data dir) into the volume:

```bash
podman volume inspect ouracle-data --format '{{.Mountpoint}}'
cp /path/to/oura_database.db "$(podman volume inspect ouracle-data --format '{{.Mountpoint}}')/"
```

Restart the container afterwards.

## Notes

- Container runs as non-root (uid 1001), read-only rootfs, `NoNewPrivileges`.
- Healthcheck hits `/api/mobile/ping` with the configured token via stdlib
  urllib every 60s.
- Bind the published port to a VPN/Tailscale interface or firewall it — the
  static token is the only authentication layer.
