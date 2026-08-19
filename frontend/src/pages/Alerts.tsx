import { useState } from "react";
import { ackAlert, listAlerts } from "../api/alerts";
import { LoadingError } from "../components/LoadingError";
import { StatusBadge } from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 5000;

const SEVERITY_CLASS: Record<string, string> = {
  critical: "badge badge-danger",
  warning: "badge badge-warn",
  info: "badge badge-muted",
};

export function Alerts() {
  const [stateFilter, setStateFilter] = useState("firing");
  const [acking, setAcking] = useState<string | null>(null);

  const alerts = usePolling(() => listAlerts({ state: stateFilter || undefined }), POLL_MS, [stateFilter]);

  const handleAck = async (id: string) => {
    setAcking(id);
    try {
      await ackAlert(id);
      alerts.refresh();
    } catch {
      // surfaced implicitly by the next poll's error state if it persists
    } finally {
      setAcking(null);
    }
  };

  return (
    <div className="page">
      <header className="page-header">
        <h1>Alerts</h1>
      </header>

      <div className="filter-bar">
        <label>
          State
          <select value={stateFilter} onChange={(e) => setStateFilter(e.target.value)}>
            <option value="">any</option>
            <option value="firing">firing</option>
            <option value="acked">acked</option>
            <option value="resolved">resolved</option>
          </select>
        </label>
      </div>

      <LoadingError
        loading={alerts.loading && !alerts.data}
        error={alerts.error}
        empty={alerts.data?.length === 0}
        emptyLabel="No alerts"
      />

      {alerts.data && alerts.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Target</th>
              <th>Summary</th>
              <th>State</th>
              <th>Started</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {alerts.data.map((a) => (
              <tr key={a.id}>
                <td>
                  <span className={SEVERITY_CLASS[a.severity] ?? "badge badge-muted"}>{a.severity}</span>
                </td>
                <td className="mono">{a.target}</td>
                <td>{a.summary}</td>
                <td>
                  <StatusBadge status={a.state} />
                </td>
                <td>{new Date(a.started_at).toLocaleString()}</td>
                <td>
                  {a.state === "firing" && (
                    <button className="btn" disabled={acking === a.id} onClick={() => handleAck(a.id)}>
                      {acking === a.id ? "Acking…" : "Ack"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
