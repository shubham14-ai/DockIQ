import { useState } from "react";
import { listHealingActions, listHealingPolicies, updateHealingPolicy } from "../api/healing";
import { LoadingError } from "../components/LoadingError";
import { StatusBadge } from "../components/StatusBadge";
import type { HealingMode } from "../api/types";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 10000;
const MODES: HealingMode[] = ["off", "auto", "semi"];

const MODE_CLASS: Record<string, string> = {
  off: "badge badge-ok",
  semi: "badge badge-warn",
  auto: "badge badge-danger",
};

export function SelfHealing() {
  const [updating, setUpdating] = useState<string | null>(null);
  const policies = usePolling(() => listHealingPolicies(), POLL_MS);
  const actions = usePolling(() => listHealingActions(), POLL_MS);

  const handleModeChange = async (id: string, mode: HealingMode) => {
    if (mode === "auto") {
      const ok = window.confirm(
        "Setting this policy to AUTO allows DockIQ to automatically restart or recreate containers without human approval. Continue?",
      );
      if (!ok) return;
    }
    setUpdating(id);
    try {
      await updateHealingPolicy(id, mode);
      policies.refresh();
    } catch {
      // surfaced implicitly by the next poll's error state if it persists
    } finally {
      setUpdating(null);
    }
  };

  return (
    <div className="page page-wide">
      <header className="page-header">
        <h1>Self-Healing</h1>
        <p className="page-subtitle">
          Control how DockIQ responds to detected issues. <strong>off</strong> is the safe default — nothing is
          changed automatically. <strong>auto</strong> lets DockIQ restart or recreate containers on its own;
          <strong> semi</strong> requires confirmation before acting.
        </p>
      </header>

      <div className="diagnostics-banner">
        Warning: enabling <strong>auto</strong> mode allows DockIQ to restart containers automatically, without a
        human in the loop. Use <strong>semi</strong> if you want a review step, or <strong>off</strong> to disable
        healing entirely.
      </div>

      <LoadingError
        loading={policies.loading && !policies.data}
        error={policies.error}
        empty={policies.data?.length === 0}
        emptyLabel="No healing policies configured"
      />

      {policies.data && policies.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Policy</th>
              <th>Mode</th>
              <th>Allowed actions</th>
              <th>Max / hour</th>
              <th>Enabled</th>
            </tr>
          </thead>
          <tbody>
            {policies.data.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>
                  <span className={MODE_CLASS[p.mode] ?? "badge badge-muted"} style={{ marginRight: 8 }}>
                    {p.mode}
                  </span>
                  <select
                    value={p.mode}
                    disabled={updating === p.id}
                    onChange={(e) => handleModeChange(p.id, e.target.value as HealingMode)}
                  >
                    {MODES.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="mono">{p.allowed_actions.join(", ") || "—"}</td>
                <td>{p.max_per_hour}</td>
                <td>
                  <StatusBadge status={p.enabled ? "ok" : "unknown"} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2 className="section-title">Recent actions</h2>
      <p className="page-subtitle">
        Heal actions (restart/recreate) and operator-approved cache prunes, most recent first.
      </p>
      <LoadingError
        loading={actions.loading && !actions.data}
        error={actions.error}
        empty={actions.data?.length === 0}
        emptyLabel="No actions recorded yet"
      />
      {actions.data && actions.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Trigger</th>
              <th>Action</th>
              <th>Target</th>
              <th>Outcome</th>
              <th>Detail</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {actions.data.map((a) => (
              <tr key={a.id}>
                <td>{a.trigger}</td>
                <td className="mono">{a.action}</td>
                <td className="mono">{a.target}</td>
                <td>
                  <StatusBadge status={a.outcome} />
                </td>
                <td>{a.detail ?? "—"}</td>
                <td>{new Date(a.started_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
