import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getProject } from "../api/projects";
import type { ProjectService } from "../api/types";
import { LoadingError } from "../components/LoadingError";
import { RoleTechBadge } from "../components/RoleTechBadge";
import { StatusBadge } from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 5000;

function stateSummary(counts: Record<string, number>): string {
  return Object.entries(counts)
    .map(([state, n]) => `${n} ${state}`)
    .join(" · ");
}

function ServiceRow({ svc }: { svc: ProjectService }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="service-block">
      <button className="service-head" onClick={() => setOpen((o) => !o)}>
        <span className="service-caret">{open ? "▾" : "▸"}</span>
        <span className="service-name">{svc.service}</span>
        <span className="badge badge-muted">{stateSummary(svc.state_counts)}</span>
      </button>

      {open && (
        <table className="table service-table">
          <thead>
            <tr>
              <th>Container</th>
              <th>Classification</th>
              <th>State</th>
              <th>Image</th>
            </tr>
          </thead>
          <tbody>
            {svc.containers.map((c) => (
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
                <td className="mono">{c.image_ref ?? c.image ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function ProjectDetail() {
  const { project = "" } = useParams();
  const detail = usePolling(() => getProject(project), POLL_MS, [project]);
  const p = detail.data;

  return (
    <div className="page">
      <header className="page-header">
        <Link to="/projects" className="link back-link">
          ← Projects
        </Link>
        <h1>{p?.standalone ? "Ungrouped / Standalone" : project}</h1>
      </header>

      <LoadingError loading={detail.loading && !p} error={detail.error} />

      {p && (
        <>
          <section className="detail-grid">
            <div className="detail-item">
              <div className="detail-label">Services</div>
              <div className="stat-inline">{p.service_count}</div>
            </div>
            <div className="detail-item">
              <div className="detail-label">Containers</div>
              <div className="stat-inline">{p.container_count}</div>
            </div>
            <div className="detail-item">
              <div className="detail-label">Images</div>
              <div className="stat-inline">{p.image_count}</div>
            </div>
            <div className="detail-item">
              <div className="detail-label">Hosts</div>
              <div className="stat-inline">{p.hosts.length}</div>
            </div>
            <div className="detail-item">
              <div className="detail-label">Health</div>
              <div className="badge-group">
                {Object.entries(p.health).map(([k, n]) => (
                  <span key={k} className="badge badge-muted">
                    {n} {k}
                  </span>
                ))}
              </div>
            </div>
          </section>

          <section>
            <h2>Services</h2>
            {p.services.map((svc) => (
              <ServiceRow key={svc.service} svc={svc} />
            ))}
          </section>

          <section>
            <h2>Images</h2>
            <table className="table">
              <thead>
                <tr>
                  <th>Image</th>
                  <th>Digest</th>
                  <th>Used by</th>
                  <th>Containers</th>
                </tr>
              </thead>
              <tbody>
                {p.images.map((img, i) => (
                  <tr key={`${img.image_ref}-${i}`}>
                    <td className="mono">{img.image_ref ?? "—"}</td>
                    <td className="mono">{img.image_digest?.slice(0, 19) ?? "—"}</td>
                    <td>{img.services.join(", ")}</td>
                    <td>{img.container_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h2>Config</h2>
            <section className="detail-grid">
              <div className="detail-item">
                <div className="detail-label">Compose files</div>
                <div className="mono">{p.config.config_files ?? "—"}</div>
              </div>
              <div className="detail-item">
                <div className="detail-label">Working dir</div>
                <div className="mono">{p.config.working_dir ?? "—"}</div>
              </div>
              <div className="detail-item">
                <div className="detail-label">Networks</div>
                <div className="badge-group">
                  {p.config.networks.length > 0
                    ? p.config.networks.map((n) => (
                        <span key={n} className="badge badge-muted">
                          {n}
                        </span>
                      ))
                    : "—"}
                </div>
              </div>
            </section>
          </section>
        </>
      )}
    </div>
  );
}
