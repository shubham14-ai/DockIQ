import { Link, useParams } from "react-router-dom";
import { listContainers } from "../api/containers";
import { getHost } from "../api/hosts";
import { useAuth } from "../auth/AuthContext";
import { roleAtLeast } from "../auth/roles";
import { CachePanel } from "../components/CachePanel";
import { LoadingError } from "../components/LoadingError";
import { RoleTechBadge } from "../components/RoleTechBadge";
import { StatusBadge } from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 5000;

export function HostDetail() {
  const { hostId = "" } = useParams();
  const { user } = useAuth();
  const canOperate = !!user && roleAtLeast(user.role, "operator");
  const host = usePolling(() => getHost(hostId), POLL_MS, [hostId]);
  const containers = usePolling(() => listContainers({ host_id: hostId }), POLL_MS, [hostId]);

  return (
    <div className="page">
      <header className="page-header">
        <Link to="/hosts" className="link back-link">
          ← Hosts
        </Link>
        <h1>{host.data?.name ?? hostId}</h1>
      </header>

      <LoadingError loading={host.loading && !host.data} error={host.error} />

      {host.data && (
        <section className="detail-grid">
          <div className="detail-item">
            <div className="detail-label">Status</div>
            <StatusBadge status={host.data.agent_status} />
          </div>
          <div className="detail-item">
            <div className="detail-label">Last Heartbeat</div>
            <div>{host.data.last_heartbeat ? new Date(host.data.last_heartbeat).toLocaleString() : "never"}</div>
          </div>
          <div className="detail-item">
            <div className="detail-label">OS / Arch</div>
            <div>
              {host.data.os ?? "?"} / {host.data.arch ?? "?"}
            </div>
          </div>
          <div className="detail-item">
            <div className="detail-label">Docker Version</div>
            <div>{host.data.docker_version ?? "?"}</div>
          </div>
          <div className="detail-item">
            <div className="detail-label">Agent Version</div>
            <div>{host.data.agent_version ?? "?"}</div>
          </div>
          <div className="detail-item">
            <div className="detail-label">Tenant</div>
            <div>{host.data.tenant_id}</div>
          </div>
        </section>
      )}

      {canOperate && <CachePanel hostId={hostId} />}

      <section>
        <h2>Containers</h2>
        <LoadingError
          loading={containers.loading && !containers.data}
          error={containers.error}
          empty={containers.data?.length === 0}
          emptyLabel="No containers reported for this host"
        />
        {containers.data && containers.data.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Classification</th>
                <th>State</th>
                <th>Image</th>
              </tr>
            </thead>
            <tbody>
              {containers.data.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link to={`/containers/${c.id}`} className="link">
                      {c.name}
                    </Link>
                  </td>
                  <td>
                    <RoleTechBadge
                      role={c.role ?? c.classification?.role}
                      tech={c.tech ?? c.classification?.tech}
                      confidence={c.classification?.confidence}
                    />
                  </td>
                  <td>
                    <StatusBadge status={c.state} />
                  </td>
                  <td className="mono">{c.image}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
