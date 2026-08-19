# Feature — Cache Maintenance (approval-gated prune)

**Goal:** Let an operator reclaim unwanted Docker cache (dangling images,
stopped containers, idle build cache, unused networks/volumes) from a host,
with a **mandatory human approval step** so nothing destructive ever runs on its
own.

> DockIQ *analyzes* the host; this feature lets it *act* on that analysis —
> safely, one deliberate approval at a time.

---

## 1. The flow

Clearing cache is destructive, so it is deliberately split into two calls:

```
Scan (read-only)  →  review reclaimable space  →  Approve & clear (destructive)
     dry_run=true                                    dry_run=false, approve=true
```

1. **Scan** — the agent runs `docker df` and reports how much each target
   *could* reclaim. Nothing is removed. Safe to call anytime.
2. **Approve & clear** — actually prunes, and **only runs when the request
   carries `approve: true`**. Without that flag the backend rejects the call
   with `422`. This is the human-in-the-loop gate.

The two steps are independent requests, so approval is an explicit, separate
action — not a checkbox buried in the same call that scanned.

---

## 2. What gets pruned

| Target | What it removes | Default? |
|---|---|---|
| `build-cache` | Idle BuildKit cache | ✅ |
| `images` | Dangling (untagged, unreferenced) images | ✅ |
| `containers` | Stopped containers | ✅ |
| `networks` | Unused user networks | ✅ |
| `volumes` | **Unused** volumes | ❌ opt-in |

**Volumes are never in the default set** — pruning them can permanently delete
data. A caller (or the UI operator) must name `"volumes"` explicitly, and the UI
flags it with a `data loss` badge and an extra confirmation line.

Images use `dangling_only=true` by default (only untagged layers — the
"unwanted" cache), not every unused image.

---

## 3. Where it lives

| Layer | File | Role |
|---|---|---|
| Agent | [`agent/commands.py`](../../agent/commands.py) | `prune` action: `_scan_reclaimable` (dry-run via `docker df`) and `_prune` (destructive). Volumes excluded from `DEFAULT_PRUNE_TARGETS`. |
| Backend transport | [`backend/app/agents/commander.py`](../../backend/app/agents/commander.py) | `prune` added to `VALID_ACTIONS`; `extra` passes `targets` / `dry_run` / `dangling_only` through NATS. |
| Backend API | [`backend/app/api/maintenance.py`](../../backend/app/api/maintenance.py) | `POST /hosts/{id}/cache/scan` and `POST /hosts/{id}/cache/prune`. Prune refuses without `approve: true`. |
| Frontend API | [`frontend/src/api/maintenance.ts`](../../frontend/src/api/maintenance.ts) | `scanCache` / `pruneCache`. |
| Frontend UI | [`frontend/src/components/CachePanel.tsx`](../../frontend/src/components/CachePanel.tsx) | Panel on **Host Detail**: target checkboxes → Scan → review table → Approve & clear (with `window.confirm`). |

The prune executes over the same NATS request/reply path the Self-Healing and
Deployment engines already use — the agent is the only component that touches the
Docker socket.

---

## 4. Safety & audit

- **Two API calls**, not one — approval is a separate deliberate action.
- **`approve: true` required** — the prune endpoint returns `422` otherwise.
- **Operator-gated** — both routes require the `operator` role (router-level
  dependency in [`main.py`](../../backend/app/main.py)); the UI panel is hidden
  for viewers.
- **Volumes opt-in only** — never touched unless explicitly requested.
- **Audited** — every prune is written to the `healing_actions` table with
  `action="prune"`, `trigger="manual"`, and a `detail` recording bytes reclaimed
  (or the error). It shows up alongside heals in the audit trail.

---

## 5. API reference

### `POST /api/v1/hosts/{host_id}/cache/scan`

```jsonc
// request (targets optional; defaults to the non-volume set)
{ "targets": ["build-cache", "images", "containers", "networks"] }

// response
{
  "ok": true, "host_id": "...", "dry_run": true,
  "reclaimable_bytes": 1610612736,
  "targets": {
    "build-cache": { "count": 12, "reclaimable_bytes": 1073741824 },
    "images":      { "count": 5,  "reclaimable_bytes": 536870912 }
  }
}
```

### `POST /api/v1/hosts/{host_id}/cache/prune`

```jsonc
// request — approve MUST be true, or the call is rejected with 422
{ "targets": ["build-cache", "images"], "dangling_only": true, "approve": true }

// response
{
  "ok": true, "host_id": "...", "dry_run": false,
  "reclaimed_bytes": 1610612736,
  "targets": { "images": { "removed": 5, "reclaimed_bytes": 536870912 } },
  "action_id": 42
}
```

---

## 6. Status & follow-ups

🏗️ **Backend + agent + UI implemented; live end-to-end run needs Docker Desktop.**
Verified without a daemon: backend imports (routes wired), frontend production
build passes.

Possible follow-ups:

- Surface prune actions on the Self-Healing audit page (they already persist to
  `healing_actions`).
- Optional scheduled/policy-driven prune (would still keep the approval gate, or
  require an explicit `semi`/`auto` opt-in like healing modes).
- Fuller image prune (`dangling_only=false`) as a separate, more-guarded toggle.
