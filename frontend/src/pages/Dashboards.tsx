import { useState } from "react";
import { listDashboards, regenerateDashboards } from "../api/dashboards";
import { LoadingError } from "../components/LoadingError";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 15000;

export function Dashboards() {
  const [regenerating, setRegenerating] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const dashboards = usePolling(() => listDashboards(), POLL_MS);

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      await regenerateDashboards();
      dashboards.refresh();
    } catch {
      // surfaced implicitly by the next poll's error state if it persists
    } finally {
      setRegenerating(false);
    }
  };

  const selectedDashboard = dashboards.data?.find((d) => d.id === selected);

  return (
    <div className="page page-wide">
      <header className="page-header">
        <h1>Dashboards</h1>
        <p className="page-subtitle">Auto-generated Grafana dashboards for classified services.</p>
        <button className="btn" disabled={regenerating} onClick={handleRegenerate}>
          {regenerating ? "Regenerating…" : "Regenerate dashboards"}
        </button>
      </header>

      <LoadingError
        loading={dashboards.loading && !dashboards.data}
        error={dashboards.error}
        empty={dashboards.data?.length === 0}
        emptyLabel="No dashboards yet — click Regenerate to generate them."
      />

      {dashboards.data && dashboards.data.length > 0 && (
        <div className="card-grid">
          {dashboards.data.map((d) => (
            <div key={d.id} className={"card" + (selected === d.id ? " card-selected" : "")}>
              <div className="card-title">{d.title}</div>
              <div className="badge-group">
                <span className="badge badge-tech">{d.tech}</span>
                <span className="badge badge-muted">{d.tier}</span>
                {!d.generated && <span className="badge badge-warn">pending</span>}
              </div>
              <div className="card-actions">
                <a className="btn" href={d.grafana_url} target="_blank" rel="noreferrer">
                  Open in Grafana
                </a>
                <button className="btn btn-secondary" onClick={() => setSelected(selected === d.id ? null : d.id)}>
                  {selected === d.id ? "Hide preview" : "Preview"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedDashboard && (
        <div className="dashboard-embed">
          <iframe
            title={selectedDashboard.title}
            src={`${selectedDashboard.grafana_url}${selectedDashboard.grafana_url.includes("?") ? "&" : "?"}kiosk`}
          />
        </div>
      )}
    </div>
  );
}
