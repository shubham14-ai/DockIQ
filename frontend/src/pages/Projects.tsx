import { useMemo } from "react";
import { Link } from "react-router-dom";
import { listProjects } from "../api/projects";
import { listHosts } from "../api/hosts";
import type { ProjectSummary } from "../api/types";
import { LoadingError } from "../components/LoadingError";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 5000;

// Order + label for the health rollup mini-bar.
const HEALTH_ORDER: { key: string; cls: string; label: string }[] = [
  { key: "healthy", cls: "badge-ok", label: "healthy" },
  { key: "degraded", cls: "badge-warn", label: "degraded" },
  { key: "down", cls: "badge-danger", label: "down" },
  { key: "unknown", cls: "badge-muted", label: "unknown" },
];

function HealthBar({ health }: { health: Record<string, number> }) {
  const total = Object.values(health).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="health-bar" title={JSON.stringify(health)}>
      {HEALTH_ORDER.map(({ key, cls }) => {
        const n = health[key] ?? 0;
        if (n === 0) return null;
        return (
          <span
            key={key}
            className={`health-seg ${cls}`}
            style={{ width: `${(n / total) * 100}%` }}
          />
        );
      })}
    </div>
  );
}

export function Projects() {
  const projects = usePolling(() => listProjects(), POLL_MS);
  const hosts = usePolling(listHosts, POLL_MS);

  const hostNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const h of hosts.data ?? []) map[h.id] = h.name;
    return map;
  }, [hosts.data]);

  const running = (p: ProjectSummary) => p.state_counts["running"] ?? 0;

  return (
    <div className="page">
      <header className="page-header">
        <h1>Projects</h1>
      </header>

      <LoadingError
        loading={projects.loading && !projects.data}
        error={projects.error}
        empty={projects.data?.length === 0}
        emptyLabel="No projects discovered yet"
      />

      {projects.data && projects.data.length > 0 && (
        <div className="project-grid">
          {projects.data.map((p) => (
            <Link
              key={p.project}
              to={`/projects/${encodeURIComponent(p.project)}`}
              className="project-card"
            >
              <div className="project-card-head">
                <span className={"project-name" + (p.standalone ? " project-name-muted" : "")}>
                  {p.standalone ? "Ungrouped / Standalone" : p.project}
                </span>
                <span className="badge badge-muted">{p.service_count} svc</span>
              </div>

              <HealthBar health={p.health} />

              <div className="project-stats">
                <span>
                  {running(p)}/{p.container_count} running
                </span>
                <span>{p.image_count} images</span>
                <span>
                  {p.hosts.length} host{p.hosts.length === 1 ? "" : "s"}
                </span>
              </div>

              {p.hosts.length > 0 && (
                <div className="project-hosts">
                  {p.hosts.map((h) => (
                    <span key={h} className="badge badge-muted">
                      {hostNameById[h] ?? h}
                    </span>
                  ))}
                </div>
              )}

              {p.techs.length > 0 && (
                <div className="project-hosts">
                  {p.techs.slice(0, 6).map((t) => (
                    <span key={t} className="badge badge-tech">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
