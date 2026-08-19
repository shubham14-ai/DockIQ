# Engine 8: Self-Healing Engine

> **Don't just alert — act.** Where most tools stop at "restart the container,"
> the Self-Healing Engine runs a graduated recovery ladder: restart → rollback →
> scale → clear cache → run recovery script → open incident.

Every action is **policy-gated, auditable, and confirmed by observation** (did it
actually fix the problem?).

---

## Purpose

- Automatically remediate known failure patterns to reduce MTTR.
- Escalate through increasingly impactful actions only as needed.
- Stay safe: bounded, policy-controlled, fully audited, human-overridable.

---

## The recovery ladder (from the brief)

```
Restart Container
      ↓ (still failing?)
Rollback Version
      ↓
Scale Service
      ↓
Clear Cache
      ↓
Run Recovery Script
      ↓
Open Incident   (escalate to humans)
```

Each rung is attempted only if the prior rung didn't resolve the condition and
policy permits the next. The ladder is **per-rule configurable** — some services
may only ever restart; others may rollback; databases may *never* be auto-acted
on beyond notify.

---

## Triggers

| Trigger | Source |
|---|---|
| Crash loop / repeated restarts | Events + Anomaly |
| Health-check failing | Health monitoring |
| OOM kills | Events (OOM) |
| Memory-leak trend | Anomaly (upward trend) |
| Error-rate spike after deploy | Deployment + Anomaly |
| Dependency-aware degradation | Topology + Alert |

Triggers arrive as Alert Engine signals tagged with a requested `heal` action, or
as direct self-healing rules.

---

## Internals

```
trigger (alert w/ heal request)
        │
        ▼
┌──────────────────────┐
│  Policy gate           │  is auto-heal allowed for this target/action? blast radius ok?
└──────────┬───────────┘
           ▼ allowed
┌──────────────────────┐
│  Ladder executor       │  pick next rung; issue command via command bus → Agent
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│  Verification          │  watch health/metrics for recovery window
└──────────┬───────────┘
     ┌──────┴───────┐
   fixed          not fixed → next rung (or open incident)
     │                              │
   record + resolve alert      escalate → Incident + notify
```

- **Policy gate:** central to safety. Policies specify, per role/tech/service:
  which actions are allowed, max frequency (e.g. ≤ 3 restarts/hour before
  escalation), blast-radius limits (don't scale-down below N), and time windows.
- **Verification loop:** after each action, watch the triggering condition for a
  recovery window. Fixed → stop, resolve, record. Not fixed → next rung.
- **Loop protection:** a rung that keeps failing (restart-loop) is not retried
  infinitely — it escalates. Prevents thrashing.
- **Dependency awareness:** uses [topology](03-topology-engine.md) to avoid
  healing in a harmful order (don't restart the DB every dependent is mid-request
  on) and to recover root cause before dependents.

---

## The actions

| Action | What it does | Notes / gating |
|---|---|---|
| **Restart** | restart the container | cheapest; frequency-capped |
| **Rollback** | recreate with previous known-good image/version | ties to [Deployment](../deployment/03-rollback-and-healing.md) |
| **Scale** | add/remove replicas | Compose/Swarm-aware `[FUTURE]`; min/max bounds |
| **Clear cache** | app-specific recovery hook (e.g. exec cache flush) | policy-gated, per-tech recipe |
| **Run recovery script** | bounded exec of a predefined script | allow-listed scripts only, time/resource-limited |
| **Open incident** | create incident, page humans | terminal escalation; always available |

Destructive/impactful actions (rollback, scale-down, script, cache flush) require
explicit policy opt-in per service. Nothing risky happens by default.

---

## Safety model

- **Off by default for destructive actions.** Restart may be enabled per policy;
  rollback/scale/script require deliberate opt-in.
- **Rate limits & circuit breakers** per target.
- **Full audit:** every action logs actor=self-healing, trigger, target, action,
  before/after, outcome → `audit_log`.
- **Human override:** operators can disable healing per service, or require
  approval (semi-automatic mode). `[FUTURE for approval workflow]`
- **Blast-radius checks** via topology before impactful actions.

---

## Data

`healing_policies` (per target: allowed rungs, limits), `healing_actions`
(instances: trigger, action, outcome), links to `incidents` and `audit_log`.

---

## Interfaces

- Consumes: alert/heal triggers, anomaly signals, `topology.updated`, health.
- Issues: commands via the command bus → Agent (restart/recreate/scale/script).
- Emits: `healing.action`, incident creation, alert resolution.
- API: CRUD `/healing-policies`, `GET /healing-actions`, `POST /containers/{id}/heal`
  (manual, RBAC-gated).

---

## Failure modes

| Failure | Handling |
|---|---|
| Action doesn't fix issue | Verification detects; escalate up the ladder |
| Restart/heal loop | Frequency cap + circuit breaker → escalate to incident |
| Command fails at agent | Retry (idempotent) then escalate |
| Wrong remediation | Policy limits blast radius; full audit; human override |
| Root cause is a dependency | Topology-aware ordering heals root first |

---

## Phase

- **`[MVP-lite]`** Restart-on-crash-loop / failing-health, frequency-capped, fully
  audited, with escalation to incident. (The safe base rung.)
- **`[FUTURE]`** Rollback, scale, clear-cache recipes, recovery scripts,
  verification loops, dependency-aware ordering, approval/semi-auto mode,
  circuit breakers.
