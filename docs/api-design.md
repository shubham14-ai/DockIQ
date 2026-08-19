# API Design

The backend exposes a versioned REST API plus a WebSocket channel for live
updates. FastAPI auto-generates the OpenAPI spec, from which a typed frontend
client is generated.

---

## 1. Principles

- **Versioned:** everything under `/api/v1`. Breaking changes → `/api/v2`.
- **OpenAPI-first:** Pydantic models define request/response schemas; the spec is
  the contract. `GET /openapi.json`, docs at `/docs`.
- **Consistent envelope, pagination, errors** (below).
- **Tenant + RBAC scoped:** every request resolves a tenant and checks
  permissions; responses never leak cross-tenant data.
- **Idempotency:** mutating agent commands carry an idempotency key.

---

## 2. Auth

| Mechanism | Use |
|---|---|
| **OIDC/SSO** | interactive users (primary) |
| **Local users + JWT** | fallback / self-hosted |
| **API keys** | agents (enrollment), automation, CI webhooks |

- Bearer JWT in `Authorization: Bearer <token>` for users.
- `X-API-Key` (or bearer) for programmatic clients.
- See [Security](security.md).

---

## 3. Conventions

### Response envelope
```json
{ "data": { ... }, "meta": { "request_id": "...", "tenant": "default" } }
```
List responses:
```json
{ "data": [ ... ], "meta": { "page": 1, "page_size": 50, "total": 231 } }
```

### Pagination
`?page=1&page_size=50` (cursor pagination `?cursor=` for large/streaming sets).

### Errors (RFC-7807-ish)
```json
{ "error": { "type": "not_found", "title": "Container not found",
             "detail": "…", "status": 404, "request_id": "…" } }
```

### Filtering
Common query params: `?tenant=&host=&service=&role=&tech=&state=&since=&until=`.

---

## 4. REST surface (v1)

### Inventory
```
GET  /hosts
GET  /hosts/{id}
GET  /hosts/{id}/containers
POST /hosts/enroll                 # returns join token (RBAC: host:enroll)
GET  /containers
GET  /containers/{id}
GET  /containers/{id}/classification
POST /containers/{id}/classification    # manual override
GET  /images | /networks | /volumes
```

### Topology
```
GET  /topology                     # graph (nodes+edges), filterable
GET  /services/{id}/dependencies
GET  /services/{id}/dependents     # blast radius
```

### Metrics & logs (proxied, tenant-scoped)
```
GET  /metrics/query                # PromQL instant
GET  /metrics/query_range          # PromQL range
GET  /logs/query                   # LogQL
GET  /containers/{id}/logs         # tail/range
```

### Alerts
```
GET  /alerts
POST /alerts/{id}/ack
GET  /alert-rules | POST /alert-rules | PUT /alert-rules/{id} | DELETE …
GET  /incidents
POST /maintenance-windows | /silences
```

### Deployments
```
POST /deployments                  # trigger (manual)
GET  /deployments | GET /deployments/{id}
POST /deployments/{id}/rollback
GET  /releases?service=
POST /webhooks/{provider}          # github|gitlab|bitbucket|dockerhub|registry
```

### Self-healing
```
GET  /healing-policies | POST | PUT
GET  /healing-actions
POST /containers/{id}/heal         # manual, RBAC-gated
```

### Container actions (RBAC + policy gated)
```
POST /containers/{id}/restart
POST /containers/{id}/stop | /start
POST /containers/{id}/recreate     # image/version change
```

### LLM observability
```
POST /llm/ingest                   # SDK/OTel ingest
GET  /llm/cost | /llm/latency | /llm/vectordb
```

### Dashboards
```
GET  /dashboards
POST /dashboards/regenerate
GET  /dashboard-templates
```

### Platform / admin
```
GET/POST /users | /roles | /api-keys | /tenants
GET  /audit-log
GET  /healthz | /readyz            # DockIQ's own health
```

---

## 5. WebSocket

One authenticated connection per session: `GET /api/v1/ws` (JWT in query/subprotocol).

### Subscribe/unsubscribe
Client subscribes to topics it's viewing; server enforces tenant+RBAC:
```json
{ "action": "subscribe", "topics": ["events", "alerts", "deployments",
                                      "container:abc123", "topology"] }
```

### Server messages
```json
{ "topic": "alerts", "type": "alert.firing", "data": { ... } }
{ "topic": "events", "type": "container.started", "data": { ... } }
{ "topic": "deployments", "type": "deploy.progress", "data": { "step": "validating", ... } }
```

Backed by the [WS gateway](layers/02-backend.md#9-websocket-gateway) bridging NATS
subjects to sessions.

---

## 6. Agent-facing API/channel

Agents don't use the public REST API for telemetry; they use:
- **Enrollment:** `POST /agents/enroll` with a join token → client cert.
- **Control channel:** gRPC/WSS `[DECISION PENDING]` for heartbeat/commands.
- **Telemetry:** NATS + direct remote-write (VM) / push (Loki).

Documented in [Agent layer](layers/01-agent.md).

---

## 7. Versioning & compatibility

- Additive changes (new fields/endpoints) are non-breaking within `v1`.
- Breaking changes → `v2`, with `v1` supported through a deprecation window.
- The OpenAPI spec is the source of truth; the frontend client is regenerated on
  change.

---

## 8. Rate limiting & quotas

- Per-API-key and per-user rate limits.
- Query endpoints (metrics/logs) bounded (time range, series) to protect stores.
- Webhook endpoints validated + signature-checked per provider.

---

## 9. Phase

- **`[MVP]`** Inventory, metrics/logs query proxy, alerts (read + ack + basic
  rules), container restart/stop/start, auth, WS event/alert topics, health.
- **`[FUTURE]`** Topology, deployments/webhooks, healing policies, LLM, dashboards,
  full admin, advanced WS topics.
