import { Link } from "react-router-dom";
import { listHosts } from "../api/hosts";
import { LoadingError } from "../components/LoadingError";
import { StatusBadge } from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 5000;

export function Hosts() {
  const hosts = usePolling(listHosts, POLL_MS);

  return (
    <div className="page">
      <header className="page-header">
        <h1>Hosts</h1>
      </header>

      <LoadingError
        loading={hosts.loading && !hosts.data}
        error={hosts.error}
        empty={hosts.data?.length === 0}
        emptyLabel="No hosts enrolled yet"
      />

      {hosts.data && hosts.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Last Heartbeat</th>
              <th>OS / Arch</th>
              <th>Docker Version</th>
              <th>Agent Version</th>
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
                <td>{h.docker_version ?? "?"}</td>
                <td>{h.agent_version ?? "?"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
