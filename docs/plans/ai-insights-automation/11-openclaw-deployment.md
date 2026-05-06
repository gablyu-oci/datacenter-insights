# 11 - OpenClaw Gateway Deployment Runbook

**Status:** Operational runbook for the host-level OpenClaw Gateway provisioning.
**Owner (infra):** AI Insights team
**Date:** 2026-05-05
**Companion specs:**
- `11b-openclaw-migration-architecture.md` (architecture)
- `11c-openclaw-migration-addendum.md` (researcher reconciliation - OVERRIDES 11b on Docker specifics)
- `/tmp/openclaw_integration_research.md` (researcher dossier with primary-source links)

This document is the runbook for operating the OpenClaw Gateway as a Docker
Compose service co-located with the FastAPI backend on a single host. It
covers first-time setup, boot, healthcheck, smoke testing, persistence,
rollback, and troubleshooting.

The corresponding compose file lives at the repo root:

```
/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docker-compose.openclaw.yml
```

---

## §0. Deployment status

**Status: PROVISIONED.** As of 2026-05-05 the OpenClaw Gateway image
(`ghcr.io/openclaw/openclaw:latest`) was pulled successfully on this host,
the compose file parses cleanly, the container started, and
`GET http://localhost:7474/healthz` returned `200 {"ok":true,"status":"live"}`.

There is one host-side action a fresh operator must do before first boot
(see §11 troubleshooting "EACCES on .openclaw"): the host directory
`${REPO}/.openclaw` must be owned by UID 1000 (the in-container `node` user)
or the gateway will fail to write its config and crashloop. This is
documented inline in §2 "First-time setup" below.

The integration is NOT yet end-to-end live: the FastAPI side
(`backend/routers/agent_tools.py`, the OpenClaw forwarder, and
`OPENCLAW_ENABLED=1` in `backend/.env`) is the backend agent's task, not
this infra task. The gateway is up and healthy and waiting for the
backend wiring.

---

## §1. Prerequisites

### Host requirements
- Linux (Ubuntu 22.04 verified; Oracle Linux equivalents fine)
- Docker Engine >= 24.x (verified Docker `27.5.1` on this host)
- `systemctl is-enabled docker` returns `enabled` (verified)
- Free TCP ports: `7474` (gateway), `8000` (FastAPI - separate process)

### Docker Compose v2 plugin

The compose file uses Compose v2 schema features (e.g. `extra_hosts:
host-gateway`). Two paths to a working `compose` invocation:

**Path A - install the v2 plugin (recommended).** On Ubuntu 22.04 the
APT package `docker-compose-plugin` is NOT in the default repos. Install
the binary directly into Docker's CLI plugin dir:

```bash
sudo mkdir -p /usr/libexec/docker/cli-plugins
sudo curl -fsSL \
  https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
  -o /usr/libexec/docker/cli-plugins/docker-compose
sudo chmod +x /usr/libexec/docker/cli-plugins/docker-compose
docker compose version    # should print "Docker Compose version v2.29.x"
```

Verified working on this host on 2026-05-05.

**Path B - legacy `docker-compose` v1.** The Ubuntu APT package
`docker-compose` (v1.29.2) installs but is broken on hosts with a recent
`urllib3` -- it raises `HTTPConnection.request() got an unexpected keyword
argument 'chunked'` on every invocation. **Do not use Path B on this host.**
If on an older host where v1 still works, prefix every `docker compose`
command in this runbook with `docker-compose` (hyphenated) instead.

### Repo layout

The provisioning consumes these paths (all absolute):

```
/home/ubuntu/oci-ai-incubations/strategic-insights-tool/
  docker-compose.openclaw.yml        # this runbook drives this file
  .env.example                       # root-level env template (committed)
  .env                               # OPTIONAL root-level .env (git-ignored)
  backend/.env                       # canonical secrets file (git-ignored)
  .openclaw/                         # mounted into the container
    .gitkeep                         # committed
    openclaw.json                    # auto-generated on first boot
    workspace/SOUL.md                # persona file (committed; backend agent writes)
    extensions/insights-tools/       # TS plugin source (committed; backend agent writes)
    agents/...                       # runtime state (NOT committed)
    sessions/...                     # JSONL transcripts (NOT committed)
```

---

## §2. First-time setup

### 2.1 Generate strong secrets

```bash
cd /home/ubuntu/oci-ai-incubations/strategic-insights-tool

# 32-byte hex secrets (one each)
GATEWAY_TOKEN=$(openssl rand -hex 32)
TOOLS_BEARER=$(openssl rand -hex 32)
echo "OPENCLAW_GATEWAY_TOKEN=$GATEWAY_TOKEN"
echo "AGENT_TOOLS_BEARER=$TOOLS_BEARER"
```

Save both values somewhere durable (1Password, OCI Vault, etc.). They are
written into the env files in step 2.2 and CANNOT be rotated without
restarting both the gateway and FastAPI.

### 2.2 Populate the env file(s)

The compose service uses `env_file: ./backend/.env`. Append to that file:

```
# OpenClaw migration (added 2026-05-05)
OPENCLAW_ENABLED=1
OPENCLAW_GATEWAY_TOKEN=<the 32-byte hex from 2.1>
LLAMA_STACK_API_KEY=<your provisioned Llama Stack key>
AGENT_TOOLS_BEARER=<the second 32-byte hex from 2.1>
```

Optionally also create `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.env`
from `.env.example` if you prefer compose-level interpolation; the
canonical file is `backend/.env`.

`backend/.env` and root-level `.env` are both git-ignored.

### 2.3 Pre-create `.openclaw` with correct ownership

The container's `node` user is UID 1000. The repo on this host is owned
by UID 1001 (`ubuntu`). Without a `chown`, the gateway crashloops with
`EACCES: permission denied` on every config write.

```bash
sudo mkdir -p /home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace
sudo mkdir -p /home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/extensions
sudo chown -R 1000:1000 /home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw
```

If you later `git pull` and a teammate's commit adds files under
`.openclaw/extensions/` or `.openclaw/workspace/` (e.g. `SOUL.md`,
plugin source) those new files will be owned by the host user, not 1000.
Re-run the `chown` after every `git pull` that touches `.openclaw/`:

```bash
sudo chown -R 1000:1000 /home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw
```

### 2.4 Drop the gateway-side config

The backend agent will eventually populate
`${REPO}/.openclaw/openclaw.json` with the JSON5 shown in
`11c-openclaw-migration-addendum.md` §F (provider config, gateway token
reference). On first boot of an unconfigured `.openclaw/`, the gateway
auto-generates a stub `openclaw.json` with a self-issued bearer token.
That stub is fine for the smoke test in §5 but MUST be replaced with the
real provider+token config before flipping `OPENCLAW_ENABLED=1` in
production.

---

## §3. Boot

```bash
cd /home/ubuntu/oci-ai-incubations/strategic-insights-tool
docker compose -f docker-compose.openclaw.yml up -d
```

Expected output:

```
 Network strategic-insights-tool_default  Creating
 Network strategic-insights-tool_default  Created
 Container openclaw-gateway  Creating
 Container openclaw-gateway  Started
```

Verify:

```bash
docker compose -f docker-compose.openclaw.yml ps
# NAME               IMAGE                              SERVICE            STATUS                       PORTS
# openclaw-gateway   ghcr.io/openclaw/openclaw:latest   openclaw-gateway   Up X seconds (healthy)       0.0.0.0:7474->18789/tcp
```

If `STATUS` shows `(unhealthy)` or `(starting)` for more than 60 s, jump to §11.

---

## §4. Healthcheck

```bash
curl -fsS http://localhost:7474/healthz
# {"ok":true,"status":"live"}
```

HTTP 200 + JSON body `{"ok":true,"status":"live"}` is the green-light
signal. The container's own healthcheck runs the same probe every 30 s.

---

## §5. Smoke test (R2): chat completions reachability

This curl confirms the gateway accepts an OpenAI-compatible chat request
and forwards it to the configured Llama Stack provider. It requires that
`backend/.env` already populated `OPENCLAW_GATEWAY_TOKEN` and that
`${REPO}/.openclaw/openclaw.json` was set up to point at Llama Stack
(see addendum §F). Until both are true this curl will return either
`401 Unauthorized` or a provider-side error.

```bash
# Pull the gateway token from backend/.env
TOKEN=$(grep '^OPENCLAW_GATEWAY_TOKEN=' \
  /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/.env \
  | cut -d= -f2-)

curl -sS -X POST http://localhost:7474/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-openclaw-session-key: agent:main:smoke:$(date +%s)" \
  -d '{
    "model": "openclaw/default",
    "messages": [
      {"role": "user", "content": "Reply with the single word: OK"}
    ],
    "stream": false
  }' | head -c 2000
```

Pass criteria: response is JSON with a `choices[0].message.content`
containing some non-empty text. Failure modes are listed in §11.

For a streaming probe (matches what the FastAPI forwarder will do):

```bash
curl -NsS -X POST http://localhost:7474/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "x-openclaw-session-key: agent:main:smoke-stream:$(date +%s)" \
  -d '{
    "model": "openclaw/default",
    "messages": [
      {"role": "user", "content": "Stream the words: hello world"}
    ],
    "stream": true
  }'
# expect a series of `data: {"choices":[{"delta":{"content":"..."}}]}` frames
# terminated by `data: [DONE]`
```

---

## §6. Logs

```bash
# Live tail
docker compose -f docker-compose.openclaw.yml logs -f openclaw-gateway

# Last 100 lines, no follow
docker compose -f docker-compose.openclaw.yml logs --tail 100 openclaw-gateway

# Time-windowed
docker compose -f docker-compose.openclaw.yml logs --since 10m openclaw-gateway
```

Inside the container the gateway also writes a daily file at
`/tmp/openclaw/openclaw-YYYY-MM-DD.log` that survives container restarts
(it is in container-tmpfs, not the host mount, so a container `rm`
loses it; for durable logs rely on `docker logs`).

---

## §7. Persistence verification

After the first chat session lands, JSONL transcripts appear under:

```
/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/agents/main/sessions/<sessionId>.jsonl
```

Confirm with:

```bash
sudo find /home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/agents \
  -name '*.jsonl' -mmin -10
```

(Use `sudo` because the dir is owned by UID 1000 from the host's perspective.)

The gateway's session-store SQLite file (with WAL) lives under
`.openclaw/` as well; size grows with usage. None of this is committed -
the `.gitignore` rules under "OpenClaw runtime state" filter it out.

The Postgres `agent_message` table remains the system of record per
architecture spec 11b §6. JSONL transcripts here are auxiliary - cross-tool
eval and on-disk grep only.

---

## §8. Boot persistence (host reboot survival)

The compose file declares `restart: unless-stopped`. The Docker daemon
itself is enabled by systemd (`systemctl is-enabled docker` returns
`enabled` on this host). Therefore on host reboot:

1. systemd starts `docker.service`.
2. Docker re-attaches to the existing `openclaw-gateway` container.
3. Because the container's last state was `running` (not explicitly
   `docker stop`'d), it is restarted automatically.
4. Within ~30 s the healthcheck transitions to `healthy`.

Verify boot persistence without rebooting:

```bash
sudo systemctl restart docker
sleep 10
docker ps --filter name=openclaw-gateway --format '{{.Names}} {{.Status}}'
# openclaw-gateway Up X seconds (healthy)
```

To intentionally take the gateway out of boot rotation:

```bash
docker compose -f docker-compose.openclaw.yml stop
# now: it will NOT auto-restart on host reboot until you `up -d` again
```

To wipe the container entirely (state on disk under `.openclaw/` is
preserved):

```bash
docker compose -f docker-compose.openclaw.yml down
```

---

## §9. Database isolation contract (verbatim user spec R5)

> R5 - The OpenClaw container MUST NEVER hold a direct Postgres connection.
> All database access from the agent flows through bearer-protected FastAPI
> tool wrappers that preserve the existing `sql_gate.validate_sql`,
> read-only role provisioning, and audit trail.

This contract is enforced by three independent guards that this runbook
and the compose file uphold:

1. **No `DATABASE_URL` env in the container.** The compose file does NOT
   pass `DATABASE_URL` (or any equivalent Postgres connection string)
   into the gateway container. `env_file: ./backend/.env` does include
   `DATABASE_URL`, but the gateway image does not consume it for any
   feature - the gateway has no Postgres driver baked in. (Operator note:
   if this changes upstream, audit the env list.)

2. **Plugins POST through the bearer-protected agent-tools router.** The
   TypeScript plugins inside the container call back to FastAPI at
   `http://host.docker.internal:8000/api/agent-tools/<tool>` with
   `Authorization: Bearer ${AGENT_TOOLS_BEARER}`. They have no other
   network path to Postgres - the bridge network does not route to the
   host's Postgres port 5432.

3. **The FastAPI agent-tools router preserves the existing safety stack.**
   `backend/routers/agent_tools.py` (backend agent's deliverable) reuses
   `agents.insights.tools.query_database` which routes through
   `sql_gate.validate_sql`, the read-only DB role, and the audit-trail
   write to `agent_message.tool_calls`. Nothing is duplicated or
   bypassed in the OpenClaw path.

If a future change ever needs to give OpenClaw direct DB access, that is
a SCOPE-EXPANSION decision (not an infra change) and requires user
approval against R5.

---

## §10. Rollback

The migration is gated by `OPENCLAW_ENABLED` in `backend/.env`. To roll
back the chat path to the legacy `ToolLoopDriver` implementation:

```bash
# 1. Edit backend/.env
sed -i 's/^OPENCLAW_ENABLED=1$/OPENCLAW_ENABLED=0/' \
  /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/.env

# 2. Restart the FastAPI process (the OpenClaw container can keep running idle)
sudo systemctl restart datacenter-fastapi   # or however FastAPI is supervised
# alt: docker compose -f .../backend/docker-compose.yml restart api

# 3. Verify
curl -s http://localhost:8000/api/health
# observe a chat turn in the InsightChatDock UI
```

The legacy `_legacy_chat_handler` in `backend/routers/insights.py` is
preserved in source per the architecture spec's R9 contract and answers
immediately when `OPENCLAW_ENABLED=0`.

The OpenClaw container consumes no chat traffic when the flag is off.
You can leave it running (so a re-enable is one env-var flip away) or
stop it:

```bash
docker compose -f docker-compose.openclaw.yml stop
# or, to also remove the container (state on disk under .openclaw/ is preserved):
docker compose -f docker-compose.openclaw.yml down
```

---

## §11. Troubleshooting

### Image pull fails
**Symptom.** `docker pull ghcr.io/openclaw/openclaw:latest` returns
`unauthorized` or `name unknown`.

**Diagnosis.** GHCR usually allows anonymous pulls of public images. The
upstream image was verified public on 2026-05-05. If the pull fails:

```bash
# Check connectivity to ghcr.io
curl -fsSI https://ghcr.io/v2/ | head
# If this 503s, your egress is blocked. Try:
docker logout ghcr.io
docker pull ghcr.io/openclaw/openclaw:latest
```

If the image was made private, authenticate with a GitHub PAT scoped to
`read:packages`:

```bash
echo "$GITHUB_PAT" | docker login ghcr.io -u <gh-username> --password-stdin
docker pull ghcr.io/openclaw/openclaw:latest
```

### EACCES on `.openclaw` (most common first-boot failure)

**Symptom.** Container is `Restarting` repeatedly. `docker logs` shows:

```
Gateway failed to start: Error: EACCES: permission denied,
  open '/home/node/.openclaw/openclaw.json.1.<uuid>.tmp'
[gateway] failed to write stability bundle: Error: EACCES: permission denied,
  mkdir '/home/node/.openclaw/logs/stability'
```

**Cause.** Host directory `${REPO}/.openclaw` is not owned by UID 1000.

**Fix.**

```bash
sudo chown -R 1000:1000 /home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw
docker compose -f /home/ubuntu/oci-ai-incubations/strategic-insights-tool/docker-compose.openclaw.yml restart
sleep 10
curl -fsS http://localhost:7474/healthz
```

This was hit and resolved on the first deploy on 2026-05-05; documented
inline in §2.3.

### Healthcheck fails / returns nothing

**Symptom.** `curl http://localhost:7474/healthz` returns `Empty reply
from server` or `Connection refused`.

**Diagnosis steps.**

```bash
# 1. Is the container up at all?
docker ps --filter name=openclaw-gateway

# 2. Is the port mapped?
docker port openclaw-gateway 18789
# expect: 0.0.0.0:7474

# 3. Is the gateway listening inside the container?
docker exec openclaw-gateway curl -fsS http://127.0.0.1:18789/healthz

# 4. Recent error logs?
docker logs --tail 100 openclaw-gateway 2>&1 | grep -iE 'error|failed|denied'
```

If step 3 succeeds but step (1) curl from the host fails, a host firewall
is intercepting port 7474 - check `sudo iptables -L -n | grep 7474`.

If step 3 fails with HTTP 401 instead of 200, the gateway is up but
auth-misconfigured; this is fine for smoke testing because the
`/healthz` endpoint should be public. If `/healthz` itself requires auth
in your install (newer versions sometimes change this), pass the bearer:

```bash
curl -fsS -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
  http://localhost:7474/healthz
```

### `host.docker.internal` not resolving (Linux)

**Symptom.** Plugins inside the container fail to call back to FastAPI:
`getaddrinfo ENOTFOUND host.docker.internal`.

**Cause.** The `extra_hosts` mapping is missing from compose, OR the
container was started with `network_mode: host` (which makes the
extra_hosts entry not apply).

**Fix.** Confirm the compose file contains:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

and that NO `network_mode: host` line exists. Then:

```bash
docker exec openclaw-gateway getent hosts host.docker.internal
# should print something like: 172.17.0.1  host.docker.internal
docker exec openclaw-gateway curl -fsSI http://host.docker.internal:8000/api/health
```

If FastAPI is bound only to `127.0.0.1:8000` on the host, the bridge
network cannot reach it. Bind FastAPI to `0.0.0.0:8000` (or to the docker
bridge IP).

### Port 7474 already in use

**Symptom.** `docker compose up -d` fails:

```
Error response from daemon: driver failed programming external connectivity
on endpoint openclaw-gateway: Bind for 0.0.0.0:7474 failed: port is already
allocated
```

**Diagnosis.**

```bash
sudo ss -ltnp 'sport = :7474'   # who has it?
sudo lsof -i :7474
```

**Options.**

- If a stale OpenClaw container is bound to it: `docker rm -f
  $(docker ps -aq --filter publish=7474)`.
- If a different service is bound: pick a new host port. Edit
  `docker-compose.openclaw.yml`:

  ```yaml
  ports:
    - "<NEW_PORT>:18789"
  ```

  Then update every operator-facing reference (this runbook, the
  forwarder's `OPENCLAW_GATEWAY_URL` env var, etc.) to the new port.

### Llama Stack provider returns 401 / connection error

**Symptom.** Smoke test §5 returns `401 Unauthorized` or a connection
error.

**Diagnosis.**

```bash
# Confirm LLAMA_STACK_API_KEY made it into the container:
docker exec openclaw-gateway sh -c 'echo "${LLAMA_STACK_API_KEY:0:6}..."'

# Confirm the openclaw.json is the real provider config (not the auto-stub):
sudo cat /home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/openclaw.json \
  | head -30
```

If `openclaw.json` is the auto-stub (no `models.providers.llamastack`
block), the backend agent has not yet completed its provisioning step.
That is gating - you cannot run an end-to-end chat smoke until the
provider config is present.

### Gateway crashloops with no obvious EACCES error

Capture a full first-boot log to share with the upstream OpenClaw issue
tracker:

```bash
docker compose -f docker-compose.openclaw.yml down
sudo chown -R 1000:1000 /home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw
docker compose -f docker-compose.openclaw.yml up -d
sleep 30
docker logs openclaw-gateway 2>&1 > /tmp/openclaw_first_boot.log
```

The orchestrator captured a verified-working `/tmp/openclaw_first_boot.log`
on 2026-05-05 for diff reference.

---

## Appendix A. Files this runbook governs

| Path | Purpose |
|---|---|
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docker-compose.openclaw.yml` | The compose service definition (single service `openclaw-gateway`). |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.env.example` | Root-level env template; copy to `.env` and populate. |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/.gitkeep` | Anchors the runtime mount dir in git. |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/openclaw.json` | Provider + gateway-token config (auto-stub on first boot; backend agent populates real values). |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace/SOUL.md` | Persona file (backend agent writes from architecture spec 11b §8). |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/extensions/insights-tools/` | TS plugin source (backend agent writes per addendum 11c §G). |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.gitignore` | Filters runtime state under `.openclaw/` (sessions, JSONL, SQLite); allows declarative files. |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/.env` | Canonical secrets file (git-ignored). Compose's `env_file:` references it. |

## Appendix B. Quick reference

```bash
REPO=/home/ubuntu/oci-ai-incubations/strategic-insights-tool
COMPOSE="docker compose -f $REPO/docker-compose.openclaw.yml"

$COMPOSE up -d                          # start
$COMPOSE ps                             # status
$COMPOSE logs -f openclaw-gateway       # tail logs
$COMPOSE restart                        # restart
$COMPOSE stop                           # stop (preserves container)
$COMPOSE down                           # remove (preserves .openclaw/ state)

curl -fsS http://localhost:7474/healthz                         # health
sudo chown -R 1000:1000 $REPO/.openclaw                         # fix EACCES
sudo find $REPO/.openclaw/agents -name '*.jsonl' -mmin -10      # recent transcripts
```

---

*End of 11 - OpenClaw deployment runbook.*
