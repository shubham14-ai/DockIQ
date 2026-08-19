# DockIQ Backend (Phase 0)

FastAPI control plane. In Phase 0 it: creates the schema, connects to NATS,
enrolls agents, and tracks host liveness from heartbeats.

## Run (via the root stack)
```bash
docker compose up -d --build
```
API docs: <http://localhost:8080/docs>

## Layout
```
app/
├── main.py            # app + lifespan (init db, connect bus, start consumers)
├── core/config.py     # env-driven settings
├── core/logging.py
├── store/db.py        # async engine, Base, init_db
├── store/models.py    # Tenant, Host
├── bus/nats_bus.py    # NATS pub/sub wrapper
├── services/heartbeat.py  # heartbeat consumer + offline sweeper
└── api/
    ├── health.py      # /healthz, /readyz
    ├── agents.py      # POST /api/v1/agents/enroll
    ├── hosts.py       # GET /api/v1/hosts, /hosts/{id}
    └── schemas.py
```

## Local dev (without Docker)
Requires Python 3.12+, a reachable Postgres and NATS:
```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://dockiq:dockiq@localhost:5432/dockiq
export NATS_URL=nats://localhost:4222
export NATS_ADVERTISE_URL=nats://localhost:4222
uvicorn app.main:app --reload --port 8080
```

## Endpoints (Phase 0)
| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | liveness |
| GET | `/readyz` | readiness (Postgres + NATS) |
| POST | `/api/v1/agents/enroll` | enroll an agent → host_id + NATS address |
| GET | `/api/v1/hosts` | list hosts + liveness |
| GET | `/api/v1/hosts/{id}` | host detail |

Phase 1 adds the Discovery/Classification/Metrics/Logging/Alert engines — see
[../docs/roadmap.md](../docs/roadmap.md).
