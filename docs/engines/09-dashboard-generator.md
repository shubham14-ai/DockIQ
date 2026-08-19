# Engine 9: Dashboard Generator

> **No manual Grafana setup.** Detect a technology → automatically create the
> right dashboard for it. A PostgreSQL container gets a PostgreSQL dashboard; a
> Redis container gets a Redis dashboard; a FastAPI service gets an API dashboard.

A core **differentiator** — existing solutions require humans to build dashboards
by hand.

---

## Purpose

- Turn [Classification](02-classification-engine.md) output into dashboards
  automatically.
- Provision per-technology, per-service, and fleet dashboards without human
  configuration.
- Keep dashboards in sync as containers appear, change technology (redeploy), or
  disappear.

---

## The core idea

```
Detect PostgreSQL  →  Create PostgreSQL Dashboard
Detect Redis       →  Create Redis Dashboard
Detect FastAPI     →  Create API Dashboard
```

Each supported technology has a **dashboard template**; when Classification tags a
container, the generator instantiates the matching template scoped to that
service, wired to the right metric/log queries via the shared labels.

---

## Inputs

| Input | Source |
|---|---|
| `classification.updated` (role/tech) | Classification Engine |
| Available metrics/labels | Metrics Engine (VictoriaMetrics) |
| Logs labels | Logging Engine (Loki) |
| Topology (for service+deps views) | Topology Engine |

---

## Outputs

- **Grafana dashboards** (provisioned JSON) per technology/service + fleet
  overview.
- Native DockIQ dashboards for DockIQ-specific views (classification breakdown,
  topology, deployment, LLM).
- Dashboard registry (which dashboards exist, for which targets).

---

## Internals

```
classification.updated (tech=postgres, service=orders-db)
        │
        ▼
┌─────────────────────────┐   template catalog (per tech/role)
│  Template resolver        │──▶ pick "postgres" template
└───────────┬─────────────┘
            ▼  bind variables: service, labels, host, tenant
┌─────────────────────────┐
│  Renderer                 │  produce Grafana dashboard JSON (or native spec)
└───────────┬─────────────┘
            ▼  provision (Grafana API / provisioning dir)
        Grafana + dashboard registry ──▶ UI (embedded)
```

- **Template catalog:** declarative templates per tech (`postgres`, `redis`,
  `kafka`, `fastapi`, `qdrant`, …) and per role (generic `api`, `worker`,
  `database`), plus a **fleet overview** and a **per-service** (service + its
  dependencies) template.
- **Variable binding:** templates use the shared labels (`service`, `role`,
  `tech`, `host`, `tenant`) so a single template renders correctly for any
  matching container — no per-container editing.
- **Provisioning:** dashboards pushed via Grafana's API / provisioning so they
  appear automatically and are embeddable in the DockIQ UI.
- **Lifecycle sync:** container gone → dashboard archived; tech changed on
  redeploy → dashboard swapped; new tech in catalog → backfill dashboards for
  existing matches.
- **Layering:** auto-generated dashboards are the baseline; users can clone/
  customize without losing the generated original (customizations tracked
  separately).

---

## Dashboard tiers

| Tier | Example | Scope |
|---|---|---|
| **Technology** | "PostgreSQL", "Redis", "Kafka" | all instances of a tech |
| **Service** | "orders-api + deps" | one service + its topology neighbors |
| **Fleet** | "All databases", "Fleet overview" | role/tenant-wide |
| **Deployment** | release timeline, version compare | per deploy |
| **LLM** | tokens/cost/latency | AI services |

---

## Template example (conceptual)

```yaml
template: postgres
match: { tech: postgres }
variables: [ service, host, tenant ]
panels:
  - title: Connections
    query: dockiq_pg_connections{service="$service"}
  - title: CPU / Memory
    query: dockiq_cpu_usage_ratio{service="$service"}
  - title: Disk usage & forecast
    query: dockiq_disk_usage_ratio{service="$service"}
  - title: Errors (logs)
    logql: '{service="$service"} |= "ERROR"'
```

Where deep app metrics aren't yet available, panels degrade gracefully to the
resource metrics that always exist (CPU/mem/net/disk), so *every* detected
service gets a useful dashboard immediately.

---

## Data

`dashboards` registry (target selector, template, grafana_uid, generated/custom),
template catalog (versioned).

---

## Interfaces

- Consumes: `classification.updated`, `topology.updated`, metric/label availability.
- Produces: Grafana dashboards (API/provisioning), native dashboard specs.
- API: `GET /dashboards`, `POST /dashboards/regenerate`, `GET /dashboard-templates`.

---

## Failure modes

| Failure | Handling |
|---|---|
| Grafana down | Queue provisioning; retry; native panels still work |
| No template for a tech | Fall back to role/generic template (resource metrics) |
| Metric not present | Panel degrades / hides; dashboard still renders |
| User customization vs regen | Keep custom clone separate; never clobber user edits |

---

## Phase

- **`[FUTURE]`** (Phase 3+). Depends on Classification + Metrics being solid.
  Start with generic role templates (api/worker/db resource dashboards) + a fleet
  overview, then add per-technology deep templates. LLM & deployment dashboards
  follow their engines.
