# Feature Plan — Project (Compose Stack) Grouping

**Goal:** In Docker Desktop / `docker compose`, containers are grouped into
**projects** (compose stacks). DockIQ should show the same grouping so you can
analyze infrastructure at three levels:

```
Host → Project (compose stack) → Service → Container → Image
```

…and inspect config + health at the **project level**, **container level**, and
**image level**.

---

## 1. What already exists (foundation)

The heavy lifting for grouping is **already in place** — no new collection needed
for the core feature:

| Piece | Where | Status |
|---|---|---|
| `com.docker.compose.project` label captured | `agent/internal/collectors/discovery.go:106` | ✅ |
| `com.docker.compose.service` label captured | `discovery.go:107` | ✅ |
| Persisted as columns | `Container.compose_project` / `compose_service` (`backend/app/store/models.py:70`) | ✅ |
| Full labels/env/ports/mounts/networks stored | `Container.labels` … (JSONB) | ✅ |
| Per-container `image_ref` + `image_digest` | `Container` model | ✅ |
| Classification (role/tech) per container | `Classification` model | ✅ |

**The gap is aggregation + presentation**, plus (optionally) a real **image
inventory** (Docker Desktop's "Images" tab), which DockIQ does not collect today.

**A "project" = the value of the `com.docker.compose.project` label.** Containers
with no such label are **standalone** (show them in an "Ungrouped / Standalone"
bucket). (Optional later: also recognize Swarm stacks via
`com.docker.stack.namespace`.)

---

## 2. The hierarchy we're building

```
Project  (e.g. "dockiq", "myshop")
  ├── config       compose files, working dir, networks, volumes, label facts
  ├── rollup       #containers by state, health, hosts spanned, total CPU/mem
  ├── Service  (e.g. "backend", "postgres")     ← com.docker.compose.service
  │     └── Container(s)   ← replicas of that service
  │           └── Image    ← image_ref + digest
  └── Images used  (distinct images across the project)
```

**Scoping decision — project identity key:** a compose project name can repeat on
different hosts. Recommend keying a project as **`(tenant_id, project_name)`** and
letting a project *span hosts* (so "one stack across N hosts" reads naturally),
while surfacing the host breakdown inside the project. Alternative:
`(tenant_id, host_id, project_name)` if you want strict per-host stacks. **← decision needed**

---

## 3. Backend work

### 3a. Projects API (Phase A — core, derive from existing data)
New router `backend/app/api/projects.py`, wired in `main.py` like the others.

- `GET /projects` → one row per project (aggregated from `Container` +
  `Classification`):
  - `project`, `hosts` (list), `service_count`, `container_count`,
    `state_counts` `{running, exited, …}`, `health_rollup`
    (healthy/degraded/down), `images` (distinct count), `tech` set,
    `last_seen`.
  - Filters: `host_id`, `state`.
- `GET /projects/{project}` → detail:
  - `services[]` → each with its containers (reuse existing `ContainerOut`),
    per-service state/health rollup.
  - `images[]` → distinct `image_ref`/`image_digest` used, with which services
    use them.
  - `config` → project-level label facts pulled from any member container's
    labels: `com.docker.compose.project.config_files`,
    `com.docker.compose.project.working_dir`, networks, volumes.
  - `standalone` handling: a synthetic project id (e.g. `"(standalone)"`) so the
    UI can show ungrouped containers in the same list.

Implementation: pure SQL aggregation over `containers` grouped by
`compose_project` — small helper module (e.g. `app/engines/grouping/` or just a
service function). No schema change required for Phase A.

### 3b. Project-scoped metrics & alerts (Phase C)
- Metrics: project → member container ids → existing VictoriaMetrics queries
  (`app/api/metrics.py`) summed/averaged. Add `project` as a query dimension or a
  `GET /projects/{project}/metrics` convenience endpoint.
- Alerts: filter `Alert` by target ∈ project's containers/services; add a
  `project` label to alerts so the Alert page can filter by stack. Alert rules
  already support a `service` selector (`AlertRule.target_selector`) — extend the
  selector schema to accept `project`.
- Topology: `topology` engine already emits service edges — filter the graph to a
  single project's services for the project detail view.

### 3c. Image inventory (Phase B — new collection, the one real gap)
Docker Desktop's per-image view (size, dangling, in-use, tags) needs data we
don't collect. Two levels:

- **Derived (cheap, no agent change):** "images used by this project" from the
  containers' `image_ref` — good enough to *list* images per project. Ship in
  Phase A.
- **Full inventory (agent change):** new collector
  `agent/internal/collectors/images.go` calling `ImageList` → publish an `images`
  payload (id, repo tags, digest, size, created, dangling). New `Image` model +
  `images` API + join "which containers/projects use this image." Enables an
  **Images page** and "unused image" cleanup insights.

---

## 4. Frontend work

### 4a. Projects list page (Phase A)
- New nav item **"Projects"** in `frontend/src/components/Layout.tsx`; route in
  `App.tsx` (`/projects`, `/projects/:project`).
- `frontend/src/pages/Projects.tsx` + `src/api/projects.ts` + types.
- **Docker-Desktop-style grouped view:** a list of expandable project cards.
  Collapsed row shows: project name, host(s), container count with a
  state/health mini-bar (e.g. `5 running · 1 exited`), tech chips. Expand → nested
  **services**, each expandable to its **containers** (reuse `StatusBadge`,
  `RoleTechBadge`). Standalone containers under an "Ungrouped" group.

### 4b. Project detail page (Phase A/C)
- Header: project name, aggregated health, host badges.
- Tabs/sections: **Services** (grouped container table) · **Images** (distinct
  images used) · **Config** (compose files, networks, volumes, key labels) ·
  **Metrics** (aggregated CPU/mem charts, Phase C) · **Alerts** (project-scoped,
  Phase C) · **Topology** (project subgraph, Phase C).
- Deep-links to existing `ContainerDetail` and `HostDetail` pages.

### 4c. Images page (Phase B)
- New `Images.tsx` listing the full image inventory with tags/size/in-use, and a
  reverse link (image → containers/projects using it).

---

## 5. Phasing & effort

| Phase | Scope | New collection? | Rough effort | Value |
|---|---|---|---|---|
| **A** ✅ **DONE** | Projects list + detail, services/containers grouping, images *derived* from containers | No | S–M | ⭐⭐⭐ core ask |
| **B** | Full Image inventory (agent collector + model + API + Images page) | Yes (Python agent) | M | ⭐⭐ |
| **C** | Project-scoped metrics rollups, alerts, topology subgraph | No | M | ⭐⭐ |
| **D** | Project-level actions (start/stop/restart whole stack) — ties into Self-Healing/Deployment layer | Yes (agent commands) | M–L | ⭐ later |

**Recommendation:** ship **Phase A** first — it fully delivers the "see project
groups like Docker Desktop, drill into services/containers/images" requirement
using data we already have, with no agent changes and no DB migration.

---

## 6. Open decisions (before build)

1. **Project identity:** span hosts (`tenant+project`) or per-host
   (`tenant+host+project`)? *(Recommend: span hosts, show host breakdown.)*
2. **Standalone containers:** one "Ungrouped" bucket, or hide from Projects view
   and keep them only on the Containers page? *(Recommend: show as a bucket.)*
3. **Images now or later:** derived-only in Phase A, or pull Phase B (full agent
   image collector) into the first release?
4. **Swarm stacks:** support `com.docker.stack.namespace` too, or compose-only for v1?
5. **Materialize projects?** Derive-on-read (simple, always fresh) vs a `projects`
   table (faster, enables project-level settings/alerts ownership). *(Recommend:
   derive-on-read for Phase A.)*
```
