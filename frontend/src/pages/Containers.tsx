import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { listContainers } from "../api/containers";
import { listHosts } from "../api/hosts";
import { LoadingError } from "../components/LoadingError";
import { RoleTechBadge } from "../components/RoleTechBadge";
import { StatusBadge } from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 5000;

export function Containers() {
  const [roleFilter, setRoleFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");

  const containers = usePolling(
    () =>
      listContainers({
        role: roleFilter || undefined,
        state: stateFilter || undefined,
      }),
    POLL_MS,
    [roleFilter, stateFilter],
  );
  const hosts = usePolling(listHosts, POLL_MS);

  const hostNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const h of hosts.data ?? []) map[h.id] = h.name;
    return map;
  }, [hosts.data]);

  return (
    <div className="page">
      <header className="page-header">
        <h1>Containers</h1>
      </header>

      <div className="filter-bar">
        <label>
          Role
          <input
            type="text"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            placeholder="e.g. db"
          />
        </label>
        <label>
          State
          <select value={stateFilter} onChange={(e) => setStateFilter(e.target.value)}>
            <option value="">any</option>
            <option value="running">running</option>
            <option value="exited">exited</option>
            <option value="paused">paused</option>
            <option value="restarting">restarting</option>
          </select>
        </label>
      </div>

      <LoadingError
        loading={containers.loading && !containers.data}
        error={containers.error}
        empty={containers.data?.length === 0}
        emptyLabel="No containers match"
      />

      {containers.data && containers.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Host</th>
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
                  {c.host_id ? (
                    <Link to={`/hosts/${c.host_id}`} className="link">
                      {c.host_name ?? hostNameById[c.host_id] ?? c.host_id}
                    </Link>
                  ) : (
                    "—"
                  )}
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
    </div>
  );
}
