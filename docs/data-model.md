# Data Model

The entities DockIQ persists, their relationships, and the conventions that tie
metrics, logs, and metadata together. PostgreSQL is the relational source of
truth; VictoriaMetrics and Loki hold time-series and logs keyed by shared labels.

---

## 1. Entity map

```
tenant 1───* host 1───* container ─1──1 classification
   │                        │  \
   │                        │   *─ detected_technology
   │                        │
   │                        *── topology_edge (src/dst container|service)
   │
   ├──* user ─*─ role ─*─ permission
   ├──* api_key
   ├──* alert_rule ─1─* alert ─*─ incident
   ├──* maintenance_window / silence
   ├──* deployment ─1─* deploy_validation
   │        └─* release (per service version) ─*─ rollback
   ├──* healing_policy ─1─* healing_action
   ├──* dashboard
   └──* audit_log
```

Everything hangs off `tenant`. Every table carries `tenant_id` (see
[Security §multi-tenancy](security.md#multi-tenancy)).

---

## 2. Core inventory tables

### `tenants`
`id, name, slug, created_at, settings(jsonb)`

### `hosts`
```
id, tenant_id, host_id(stable), name, docker_version, os, arch,
cpu_cores, mem_bytes, agent_version, agent_status(online|degraded|offline),
last_heartbeat, labels(jsonb), first_seen, last_seen
```

### `containers`
```
id(docker id), tenant_id, host_id, name, image_ref, image_digest,
state, status, command, compose_project, compose_service,
labels(jsonb), env(jsonb, redacted), exposed_ports(jsonb),
published_ports(jsonb), mounts(jsonb), networks(jsonb),
restart_policy, native_health, first_seen, last_seen
```

### `images`, `networks`, `volumes`
Standard Docker object metadata, tenant+host scoped, refreshed by Discovery.

---

## 3. Intelligence tables

### `classifications`
```
id, tenant_id, container_id, role(enum), tech(string), confidence(float),
evidence(jsonb), source(enum: passive|probe|override), overridden(bool),
classified_at
```
`role ∈ {api, worker, database, queue, cache, frontend, vectordb, ai, proxy, unknown}`

### `detected_technologies`
`id, tenant_id, container_id, tech, version, catalog_ref, detected_at`

### `topology_edges`
```
id, tenant_id, src_service, dst_service, src_container, dst_container,
kind(enum: declared|observed|inferred), proto, port, weight,
confidence, first_seen, last_seen
```

---

## 4. Operations tables

### `alert_rules`
```
id, tenant_id, name, target_selector(jsonb: {role,tech,service,host}),
condition(jsonb: {type: threshold|baseline|forecast|lograte, metric, op, value/sensitivity}),
for_duration, severity, actions(jsonb: notify[], heal), enabled, source(default|user)
```

### `alerts`
```
id, tenant_id, rule_id, target(container/service), state(pending|firing|acked|resolved),
severity, started_at, acked_at, acked_by, resolved_at, count, labels(jsonb), value
```

### `incidents`
`id, tenant_id, title, root_cause(alert_id), member_alerts[], state, opened_at, closed_at, notes`

### `maintenance_windows`, `silences`
Scope selectors + time ranges to suppress alerts.

### `deployments`
```
id, tenant_id, service, from_version, to_version, image_ref, strategy(rolling|bluegreen|canary),
trigger(webhook|manual|registry), risk_score(low|med|high), risk_reasons(jsonb),
status(pending|analyzing|deploying|validating|promoted|rolledback|failed),
started_at, finished_at, initiated_by
```

### `deploy_validations`
`id, deployment_id, check(health|smoke|metric|anomaly), result(pass|fail), detail(jsonb), at`

### `releases`
`id, tenant_id, service, version, image_digest, deployed_at, deployment_id, known_good(bool)`

### `rollbacks`
`id, tenant_id, deployment_id, to_release_id, reason, automatic(bool), at, outcome`

### `healing_policies`
`id, tenant_id, target_selector(jsonb), allowed_actions[], limits(jsonb: rate, blast_radius), mode(auto|semi|off)`

### `healing_actions`
`id, tenant_id, policy_id, trigger, target, action(enum), outcome(fixed|escalated|failed), started_at, verified_at`

### `dashboards`
`id, tenant_id, target_selector(jsonb), template, tier(tech|service|fleet|deploy|llm), grafana_uid, generated(bool), custom(bool)`

---

## 5. Platform tables

### `users`, `roles`, `permissions`, `user_roles`, `role_permissions`
RBAC. `permissions` are fine-grained (e.g. `container:restart`, `deployment:rollback`,
`alert:ack`, `host:enroll`). See [Security](security.md).

### `api_keys`
`id, tenant_id, name, hash, scopes[], created_by, last_used, expires_at` — used by
agents (enrollment) and automation.

### `audit_log`
```
id, tenant_id, actor(user|apikey|system|self-healing|deployment), action, target,
before(jsonb), after(jsonb), at, source_ip, result
```
Append-only; the backbone of change management + compliance.

### `events` (timeline)
```
id, tenant_id, host_id, container_id, type(create|start|stop|die|oom|health|image_update),
detail(jsonb), at
```
Recent window in Postgres (≈90d), then archived.

---

## 6. Metric conventions (VictoriaMetrics)

- **Namespace:** all metrics `dockiq_*`.
- **Shared labels on every series:**
  `tenant, host_id, container_id, container, image, service, role, tech`.
- **Role/tech injected** from Classification so fleet queries work
  (`{role="db"}`, `{tech="redis"}`).
- **Cardinality discipline:** no unbounded label values (no request IDs, no raw
  prompts). LLM per-request detail goes to traces, not TSDB labels.
- Key series listed in [Metrics Engine](engines/04-metrics-engine.md) and
  [LLM Observability](engines/10-llm-observability-engine.md).

## 7. Log conventions (Loki)

- **Labels indexed:** the shared convention (same as metrics) — content is not
  indexed (cheap).
- One-click correlation between a metric series and its logs because they share
  `container_id`/`service` labels.

---

## 8. Identity & keys

| Entity | Stable key | Notes |
|---|---|---|
| Host | `host_id` (machine-id derived) | survives agent restart/reinstall |
| Container | Docker container ID | recreated container = new ID (deploy tracked via `service`+`version`) |
| Service | `compose_service` or detected service name | aggregates replicas |
| Tenant | `tenant_id` | scopes everything |

---

## 9. Relationships to enforce

- `container.host_id → host.id`, `host.tenant_id → tenant.id`.
- `classification.container_id → container.id` (1:1 current, history retained).
- `alert.rule_id → alert_rule.id`; `alert.incident_id → incident.id` (nullable).
- `deployment.service` + `release.service` link version history.
- All FKs additionally constrained by matching `tenant_id`.

---

## 10. Migrations & versioning

- Schema managed with migrations (e.g. Alembic).
- JSONB used for evolving/flexible attributes (labels, evidence, conditions) to
  avoid churny migrations; promote a JSONB field to a column when it becomes a
  first-class query dimension.
