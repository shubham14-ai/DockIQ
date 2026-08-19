# Security

DockIQ has deep access to infrastructure — it reads everything and can *act* on
hosts. Security is therefore first-class, not an afterthought. This doc covers
authn/z, RBAC, multi-tenancy, secrets, the agent trust model, and the threat
model.

---

## 1. The core risk

The **agent holds the keys to the host**: it needs the Docker socket, and (for
operations) the ability to restart/recreate containers and run recovery scripts.
Compromise of the agent or its command channel = compromise of the host.
Everything below exists to contain that risk.

---

## 2. Authentication

| Principal | Method |
|---|---|
| **Interactive users** | OIDC/SSO (primary), local users + JWT (fallback) |
| **Agents** | one-time join token → mTLS client certificate |
| **Automation / CI** | scoped API keys (`X-API-Key`) |

- JWTs are short-lived; refresh via the OIDC provider.
- Join tokens are single-use, short-TTL, and minted only by users with
  `host:enroll`.
- API keys are hashed at rest, scoped, and expirable.

---

## 3. Authorization (RBAC)

Reused from DockMon-style RBAC, made fine-grained.

- **Permissions** are granular actions:
  `host:enroll`, `container:view`, `container:restart`, `container:recreate`,
  `deployment:trigger`, `deployment:rollback`, `alert:ack`, `alert:rule:edit`,
  `healing:policy:edit`, `user:manage`, `tenant:manage`, …
- **Roles** bundle permissions (e.g. `viewer`, `operator`, `deployer`, `admin`,
  `owner`).
- **Every endpoint declares required permission(s)**; the backend enforces before
  any engine runs.
- **Destructive actions** (restart, recreate, rollback, scale-down, script, heal)
  require explicit permissions and are always audited.

Default roles (starting point):
| Role | Can |
|---|---|
| viewer | read inventory/metrics/logs/topology/alerts |
| operator | + ack alerts, restart/stop/start containers |
| deployer | + trigger deploys, rollback |
| admin | + manage rules, policies, users, integrations |
| owner | + manage tenants, billing `[FUTURE]` |

---

## 4. Multi-tenancy

Every persisted entity carries `tenant_id`; isolation is enforced at every layer:

| Layer | Isolation |
|---|---|
| **PostgreSQL** | row-level scoping (all queries filtered by tenant; optionally RLS) |
| **NATS** | per-tenant accounts + subject prefixes (`dockiq.<tenant>.…`); an agent cannot read another tenant's streams |
| **VictoriaMetrics / Loki** | `tenant` label on every series/stream; queries tenant-scoped (native multitenancy where available) |
| **API/WS** | tenant resolved from auth; responses filtered; WS fan-out filtered |

- **v1:** a single implicit `default` tenant; the scoping exists so SaaS
  multi-tenant (`[FUTURE]`) is a config change, not a rewrite.
- Cross-tenant access is impossible by construction, not just by convention.

---

## 5. Agent trust model

```
[ Operator ] --OIDC/JWT--> [ Backend ] --mTLS--> [ Agent ] --socket--> [ Docker ]
```

- **Enrollment:** join token → the backend issues a client cert bound to
  tenant+host. The socket is never exposed to the network.
- **mTLS everywhere:** agent↔backend and agent↔NATS use mutual TLS.
- **Command authorization:** the agent executes only commands that are
  authorized/signed by the control plane and permitted by policy; each command
  has an idempotency key (no replay double-execution).
- **Least privilege for the socket:**
  - **Monitoring tier:** socket mounted read-only (`:ro`) — no mutations.
  - **Operations tier:** write access required for restart/recreate/scale; this
    is a deliberate, documented privilege escalation the operator opts into.
- **Bounded execution:** `run_script`/`clear_cache` use allow-listed scripts with
  time/resource limits; arbitrary remote code execution is not offered.

---

## 6. Secrets handling

- **Env var redaction:** Discovery captures container env for classification, but
  **secret-like keys** (matching `*PASSWORD*`, `*SECRET*`, `*TOKEN*`, `*KEY*`,
  `*_DSN`, `*_URL` with creds, …) are **redacted or hashed** before storage.
  Classification uses key *names* and safe values only.
- **Drift comparison** compares secrets by presence/reference, never value.
- **DockIQ's own secrets** (DB creds, JWT signing key, OIDC client secret) come
  from env/files or a secret manager; never committed.
- **Vault integration** for secret management is a `[FUTURE]` enterprise feature.

---

## 7. Data protection

- **In transit:** TLS for all external traffic (UI, API); mTLS for agents/NATS.
- **At rest:** rely on host/disk encryption for stores; PostgreSQL is the
  sensitive store (inventory, audit) and is the priority for backup + encryption.
- **PII:** DockIQ stores infrastructure metadata, not end-user PII; logs *may*
  contain PII from apps — retention limits + access control mitigate, and log
  redaction rules are a `[FUTURE]` option.

---

## 8. Audit & change management

- **`audit_log`** records every mutating action (manual *and* automatic:
  self-healing, rollback, deploy) with actor, target, before/after, result, IP.
- Append-only; the basis for change management, incident review, and compliance.
- Deployment approvals `[FUTURE]` and incident integrations (Jira/ServiceNow)
  `[FUTURE]` build on this.

---

## 9. Threat model (summary)

| Threat | Mitigation |
|---|---|
| Stolen agent cert | Per-host cert, revocable; mTLS; tenant/subject scoping limits blast radius |
| Malicious/compromised backend | Agents only accept authorized commands; audit; least-privilege socket tier |
| Cross-tenant data leak | Tenant scoping at every layer (DB/NATS/TSDB/API); enforced, not conventional |
| Replay of commands | Idempotency keys; agent dedupe |
| Prompt-injection via monitored content (labels/logs) | Observed content is **data, never instructions**; engines don't execute text from containers |
| Secret exposure via env capture | Redaction/hashing at ingest |
| Runaway self-healing | Policies off-by-default for destructive actions, rate limits, circuit breakers, audit |
| Webhook spoofing | Per-provider signature verification on `/webhooks/*` |
| DoS via query | Rate limits + bounded metric/log queries |

> **Prompt-injection note:** DockIQ ingests untrusted content (container labels,
> logs, image metadata, app-provided LLM data). This content is **always treated
> as data**. No engine interprets it as a command; self-healing/deploy actions
> come only from authorized rules/operators, never from monitored text.

---

## 10. Phase

- **`[MVP]`** OIDC + local auth, RBAC with default roles, mTLS agents, tenant
  scoping (single default tenant), env redaction, audit log, signed webhooks
  (when webhooks land).
- **`[FUTURE]`** Full multi-tenant SaaS isolation, Vault, log redaction rules,
  deployment approval workflows, cert rotation automation, RLS.
