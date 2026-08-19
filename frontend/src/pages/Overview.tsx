import { Link } from "react-router-dom";
import { listAlerts } from "../api/alerts";
import { listContainers } from "../api/containers";
import { listHosts } from "../api/hosts";
import { LoadingError } from "../components/LoadingError";
import { StatusBadge } from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 5000;

function count<T>(items: T[], key: (item: T) => string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const item of items) {
    const k = key(item);
    out[k] = (out[k] ?? 0) + 1;
  }
  return out;
}

export function Overview() {
  const hosts = usePolling(listHosts, POLL_MS);
  const containers = usePolling(() => listContainers(), POLL_MS);
  const alerts = usePolling(() => listAlerts({ state: "firing" }), POLL_MS);

  const hostStatusCounts = hosts.data ? count(hosts.data, (h) => h.agent_status) : {};
  const containerRoleCounts = containers.data
    ? count(containers.data, (c) => c.role ?? c.classification?.role ?? "unknown")
    : {};
  const activeAlertCount = alerts.data?.length ?? 0;

  const anyLoading = hosts.loading && containers.loading && alerts.loading;
  const firstError = hosts.error || containers.error || alerts.error;

  return (
    <div className="page">
      <header className="page-header">
        <h1>Fleet Overview</h1>
      </header>

      <LoadingError loading={anyLoading} error={firstError} />

      <section className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Hosts</div>
          <div className="stat-value">{hosts.data?.length ?? "—"}</div>
          <div className="stat-breakdown">
            {Object.entries(hostStatusCounts).map(([status, n]) => (
              <StatusBadge key={status} status={`${status} (${n})`} />
            ))}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Containers</div>
          <div className="stat-value">{containers.data?.length ?? "—"}</div>
          <div className="stat-breakdown">
            {Object.entries(containerRoleCounts).map(([role, n]) => (
              <span key={role} className="badge badge-role">
                {role} ({n})
              </span>
            ))}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-label">Active Alerts</div>
          <div className={"stat-value" + (activeAlertCount > 0 ? " stat-value-alert" : "")}>
            {activeAlertCount}
          </div>
          <div className="stat-breakdown">
            <Link to="/alerts" className="link">
              View alerts →
            </Link>
          </div>
        </div>
      </section>

      <section>
        <h2>Hosts</h2>
        {hosts.data && hosts.data.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Last Heartbeat</th>
                <th>OS / Arch</th>
              </tr>
            </thead>
            <tbody>
              {hosts.data.map((h) => (
                <tr key={h.id}>
                  <td>
                    <Link to={`/hosts/${h.id}`} className="link">
                      {h.name}
                    </Link>
                  </td>
                  <td>
                    <StatusBadge status={h.agent_status} />
                  </td>
                  <td>{h.last_heartbeat ? new Date(h.last_heartbeat).toLocaleString() : "never"}</td>
                  <td>
                    {h.os ?? "?"} / {h.arch ?? "?"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <LoadingError loading={hosts.loading} error={hosts.error} empty emptyLabel="No hosts enrolled yet" />
        )}
      </section>
    </div>
  );
}
