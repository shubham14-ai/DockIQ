# Quickstart (Phase 0)

Get the DockIQ control plane running and enroll your first agent. This matches
the **Phase 0** scaffold in the repo (`docker-compose.yml`, `backend/`, `agent/`).

> Phase 0 = foundation: stack up, agent enrolls, heartbeats flow, host shows
> `online`. It is **not** yet monitoring containers (that's Phase 1).

---

## Prerequisites
- Docker + Docker Compose
- Python 3.12+ (for running the agent or backend locally)

## 1. Start the control plane

```bash
cp .env.example .env
docker compose up -d --build
```

This starts: **backend** (FastAPI), **nats** (JetStream), **victoriametrics**,
**loki**, **postgres**, and **grafana**.

Check health:
```bash
curl http://localhost:8080/healthz
curl http://localhost:8080/readyz     # verifies DB + NATS reachable
```
API docs: <http://localhost:8080/docs>

## 2. Enroll an agent

Get a join token from the backend (Phase 0 uses a simple dev token flow):
```bash
curl -s -X POST http://localhost:8080/api/v1/agents/enroll \
  -H 'Content-Type: application/json' \
  -d '{"host_name":"my-docker-host"}'
# → { "host_id": "...", "tenant_id": "default", "nats_url": "nats://nats:4222", "token": "..." }
```

## 3. Run the agent

**Local test (same host as the control plane)** — the agent enrolls itself; you
don't need the manual token from step 2:
```bash
docker compose --profile agent up -d --build agent
```

**Remote host** — set the control plane + advertised NATS address, then:
```bash
cd agent
CONTROL_PLANE_URL=https://dockiq.example.com NATS_URL=nats://dockiq.example.com:4222 \
  docker compose -f docker-compose.agent.yml up -d
```

**Run directly** (needs Python 3.12+; run from the repo root so `agent` imports):
```bash
pip install -r agent/requirements.txt && \
CONTROL_PLANE_URL=http://localhost:8080 HOST_NAME=my-docker-host python -m agent.main
```

## 4. Verify

```bash
curl http://localhost:8080/api/v1/hosts
# → the host appears with agent_status "online" and a recent last_heartbeat
```

You should see heartbeats arriving in the backend logs:
```bash
docker compose logs -f backend | grep heartbeat
```

---

## What's running (Phase 0)

```
localhost:8080   backend (API + /docs)
localhost:4222   nats (client)   · 8222 monitoring
localhost:8428   victoriametrics
localhost:3100   loki
localhost:5432   postgres
localhost:3000   grafana
```

## Next
- **Phase 1** adds Discovery/Classification/Metrics/Logging/Alert — see
  [Roadmap](roadmap.md). The agent gains container discovery + stats + log
  shipping there.
- Architecture: [Overview](01-architecture-overview.md) · Agent:
  [layers/01-agent.md](layers/01-agent.md) · Backend:
  [layers/02-backend.md](layers/02-backend.md).
