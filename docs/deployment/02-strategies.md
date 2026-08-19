# Deployment Strategies

DockIQ supports three deployment strategies. The Deployment Engine picks (or the
operator chooses) based on risk, service type, and topology.

---

## 1. Rolling Deployment

Replace replicas incrementally so the service stays up throughout.

```
Container v1 (3 replicas)
Replace:
   1 → v2
   2 → v2
   3 → v2
```

- **How DockIQ does it:** for each replica, pull `v2`, recreate, wait for health
  + a brief metric watch, then proceed to the next. Stop and roll back if any
  step fails.
- **Benefits:** zero downtime, low risk, no extra capacity needed.
- **Best for:** stateless services with N replicas; the default for most API/
  worker services.
- **Watch-outs:** mixed versions run simultaneously (must be compatible);
  schema/contract changes need care.

---

## 2. Blue-Green Deployment

Stand up the new version fully alongside the old, then switch traffic.

```
Blue Environment (current)      Green Environment (new version)
              \                 /
               Switch traffic ──┘
```

- **How DockIQ does it:**
  1. Deploy **Green** (full new version) beside **Blue**.
  2. Run **health checks** + **smoke tests** against Green.
  3. **Switch routing** (Nginx/Traefik) from Blue → Green.
  4. Keep Blue warm briefly for instant rollback, then retire.
- **Benefits:** instant cutover, instant rollback (flip back to Blue), no mixed
  versions serving traffic.
- **Cost:** needs ~2× capacity during the switch.
- **Best for:** higher-risk releases, services where mixed versions are unsafe.

DockIQ integrates with **Nginx/Traefik** for the traffic switch and uses the
Metrics/Health engines for the go/no-go decision.

---

## 3. Canary Deployment

Send a small slice of traffic to the new version, watch, then promote or roll
back.

```
90% Traffic → v1
10% Traffic → v2
```

- **How DockIQ does it:**
  1. Route a small percentage (e.g. 10%) to `v2`.
  2. **Monitor** error rate, latency, resource usage — compared to `v1` and to
     the pre-deploy **baseline** (Anomaly Engine).
  3. **Automatically promote** (increase share to 100%) if healthy, or **roll
     back** if regressed.
- **Monitored signals:** error rate, latency, resource usage.
- **Benefits:** limits blast radius; catches regressions with minimal user
  impact; data-driven promotion.
- **Best for:** high-traffic, high-risk services where you want statistical
  confidence before full rollout.

Canary promotion/rollback is **automatic** — it uses the same anomaly baselines
that power alerting to judge whether `v2` is actually worse.

---

## 4. Choosing a strategy

| Situation | Suggested strategy |
|---|---|
| Stateless service, low risk | Rolling |
| Mixed versions unsafe / higher risk | Blue-Green |
| High traffic, want statistical confidence | Canary |
| Stateful (DB) | Usually manual/blocked; not auto-deployed |

The pre-flight **risk score** (see [Deployment Layer §5](01-deployment-layer.md#5-deployment-intelligence))
can auto-suggest a safer strategy (e.g. push a HIGH-risk change to canary).

---

## 5. What all strategies share

Every strategy runs the same **validation gate** before promotion:
- container status + Docker health checks
- API endpoint + dependency connectivity (DB/Redis/queue)
- a **metric/anomaly watch window** (error rate, latency, resources vs baseline)

Pass → promote. Fail → **smart rollback** (see
[Rollback & Healing](03-rollback-and-healing.md)).

---

## 6. Traffic routing integration

- **Traefik / Nginx** are the initial supported routers for blue-green/canary
  traffic control (label/weight based).
- Routing changes are issued as agent commands and verified.
- `[FUTURE]` service-mesh integration, Swarm/K8s-native routing.

---

## 7. Phase

- **`[FUTURE]`** Rolling first (simplest, needs only recreate + health), then
  blue-green (needs routing integration), then canary (needs routing + baseline
  comparison). All part of the Deployment phase (Phase 6).
