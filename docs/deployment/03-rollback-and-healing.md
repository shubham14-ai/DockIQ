# Smart Rollback, Drift & Dependency Validation

The safety net of the deployment layer. Rollback is described as *"one of the
most valuable features"* in the brief — DockIQ makes it **automatic and
intelligent**.

---

## 1. Smart Rollback Engine

Automatically restore the previous known-good version when a release goes bad.

### Triggers
```
Error rate spike
Memory leak
Crash loop
Health-check failures
Response time degradation
```

These come from the Metrics, Health, Anomaly, and Logging engines — the same
signals that power alerting, now judged **against the pre-deploy baseline**.

### Flow
```
Version v2 Deployed
      ↓
Issues Detected  (error rate ↑ / latency ↑ / crash loop / health fail)
      ↓
Automatic Rollback
      ↓
v1 Restored
```

### How DockIQ executes it
1. Deployment records the **previous known-good** image/version + config before
   changing anything.
2. During the validation window, watch trigger signals.
3. On a trigger: issue `recreate` commands to restore `v1` (image + config), or
   flip routing back to Blue (blue-green) / drop canary weight to 0.
4. **Verify** the rollback restored health (same validation gate).
5. **Open an incident** and notify; record the failed release + rollback in
   history/audit.

### Safety
- Rollback is **bounded and audited** like any self-healing action.
- Stateful services (DBs) are **not** auto-rolled-back by default (data risk) —
  they alert + escalate instead.
- Rollback ties into the [Self-Healing ladder](../engines/08-self-healing-engine.md)
  (rollback is a rung).

---

## 2. Configuration Drift Detection

Catch environment mismatches *before* they cause a bad deploy.

```
Dev Environment  ≠  Production Environment
```

### What is compared
```
Environment variables · Docker Compose · Network configuration · Volumes · Secrets
```

### How it works
- Capture the effective config of the current (prod) deployment and the incoming
  release (from the trigger/compose/registry metadata).
- Diff across the dimensions above; secrets compared by presence/reference, never
  by value (see [Security](../security.md)).
- Classify drift severity (benign vs risky, e.g. a changed `DATABASE_URL` or a
  removed volume is high-risk).
- **Alert before deployment**; high-risk drift can **block** or downgrade the
  strategy (force canary).

Drift also feeds the **risk score** in
[pre-flight analysis](01-deployment-layer.md#5-deployment-intelligence).

---

## 3. Infrastructure Dependency Validation

Never deploy into a broken dependency graph.

### Before release, check
```
PostgreSQL · Redis · Kafka · Vector DB · External APIs
```
```
If dependency is unhealthy → Deployment Blocked
```

### How it works
- Use the [Topology Engine](../engines/03-topology-engine.md) to enumerate the
  service's dependencies.
- Check each dependency's current health (Health/Metrics engines): is Postgres
  up and accepting connections? is Redis responsive? is the queue reachable? are
  external APIs responding?
- If a required dependency is unhealthy → **block the deploy** and surface why.
- Optional soft mode: warn but allow, for non-critical deps.

This closes a common failure: deploying a service whose database is already down,
then blaming the new version.

---

## 4. How these combine (pre-flight → deploy → post-deploy)

```
PRE-FLIGHT
  ├─ dependency validation   → block if a required dep is unhealthy
  ├─ drift detection         → alert/block/force-canary on risky drift
  └─ risk score              → choose/suggest strategy
        │ ok
        ▼
DEPLOY (rolling / blue-green / canary)
        │
        ▼
POST-DEPLOY VALIDATION
  ├─ health + smoke tests
  └─ metric/anomaly watch (error rate, latency, resources vs baseline)
        │
   ┌────┴─────┐
 pass       fail → SMART ROLLBACK → restore v1 → verify → open incident
   │
 promote + record
```

---

## 5. Records & audit

Every deploy, validation result, and rollback is persisted:
- `deployments`, `deploy_validations`, `rollbacks`, `releases` (version history).
- All linked to `audit_log` (who/what/when, automatic vs manual).
- Powers the [deployment dashboard](01-deployment-layer.md#7-deployment-dashboard)
  and post-incident review.

---

## 6. Failure modes

| Failure | Handling |
|---|---|
| Rollback also fails | Escalate to incident immediately; page humans; freeze further auto-deploys for the service |
| Baseline unavailable (new service) | Validation falls back to health + thresholds |
| Drift diff incomplete (missing prod config) | Warn "drift unknown"; treat as elevated risk |
| Dependency check false-negative | Soft mode + human override; topology confidence surfaced |
| Stateful service regression | Never auto-rollback data; alert + escalate |

---

## 7. Phase

- **`[FUTURE]`** Part of the Deployment phase (Phase 6). Recommended order:
  known-good capture + automatic rollback on health failure → metric/anomaly-based
  rollback → dependency validation → drift detection → risk scoring.
