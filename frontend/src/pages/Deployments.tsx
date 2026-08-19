import { FormEvent, useState } from "react";
import { createDeployment, listDeployments, listReleases, rollbackDeployment } from "../api/deployments";
import { LoadingError } from "../components/LoadingError";
import type { Release } from "../api/types";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 10000;

const STATUS_CLASS: Record<string, string> = {
  promoted: "badge badge-ok",
  rolledback: "badge badge-warn",
  failed: "badge badge-danger",
};

export function Deployments() {
  const [target, setTarget] = useState("");
  const [image, setImage] = useState("");
  const [strategy, setStrategy] = useState("recreate");
  const [submitting, setSubmitting] = useState(false);
  const [rollingBack, setRollingBack] = useState<string | null>(null);
  const [releaseService, setReleaseService] = useState("");
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [releasesError, setReleasesError] = useState<string | undefined>(undefined);

  const deployments = usePolling(() => listDeployments(), POLL_MS);

  const handleDeploy = async (e: FormEvent) => {
    e.preventDefault();
    if (!target.trim() || !image.trim()) return;
    const ok = window.confirm(
      `Deploy "${image}" to "${target}"? This will recreate the container using a ${strategy} strategy.`,
    );
    if (!ok) return;
    setSubmitting(true);
    try {
      await createDeployment({ target: target.trim(), image: image.trim(), strategy });
      setTarget("");
      setImage("");
      deployments.refresh();
    } catch {
      // surfaced implicitly by the next poll's error state if it persists
    } finally {
      setSubmitting(false);
    }
  };

  const handleRollback = async (id: string, service: string) => {
    const ok = window.confirm(`Rollback deployment for "${service}"? This will recreate the container.`);
    if (!ok) return;
    setRollingBack(id);
    try {
      await rollbackDeployment(id);
      deployments.refresh();
    } catch {
      // surfaced implicitly by the next poll's error state if it persists
    } finally {
      setRollingBack(null);
    }
  };

  const handleLoadReleases = async () => {
    setReleasesError(undefined);
    try {
      const data = await listReleases(releaseService || undefined);
      setReleases(data);
    } catch (err) {
      setReleasesError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="page page-wide">
      <header className="page-header">
        <h1>Deployments</h1>
        <p className="page-subtitle">Deploy new images and roll back running services.</p>
      </header>

      <form className="deploy-form" onSubmit={handleDeploy}>
        <label>
          Target (container / service)
          <input
            type="text"
            placeholder="carevora-api"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            required
          />
        </label>
        <label>
          Image
          <input
            type="text"
            placeholder="ghcr.io/org/api:1.4.0"
            value={image}
            onChange={(e) => setImage(e.target.value)}
            required
          />
        </label>
        <label>
          Strategy
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            <option value="recreate">recreate</option>
            <option value="rolling">rolling</option>
          </select>
        </label>
        <button className="btn" type="submit" disabled={submitting}>
          {submitting ? "Deploying…" : "Deploy"}
        </button>
      </form>

      <LoadingError
        loading={deployments.loading && !deployments.data}
        error={deployments.error}
        empty={deployments.data?.length === 0}
        emptyLabel="No deployments recorded yet"
      />

      {deployments.data && deployments.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Service</th>
              <th>From</th>
              <th>To</th>
              <th>Strategy</th>
              <th>Status</th>
              <th>Started</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {deployments.data.map((d) => (
              <tr key={d.id}>
                <td>{d.service}</td>
                <td className="mono">{d.from_version ?? "—"}</td>
                <td className="mono">{d.to_version}</td>
                <td>{d.strategy}</td>
                <td>
                  <span className={STATUS_CLASS[d.status] ?? "badge badge-muted"}>{d.status}</span>
                </td>
                <td>{new Date(d.started_at).toLocaleString()}</td>
                <td>
                  {d.status !== "rolledback" && (
                    <button
                      className="btn btn-secondary"
                      disabled={rollingBack === d.id}
                      onClick={() => handleRollback(d.id, d.service)}
                    >
                      {rollingBack === d.id ? "Rolling back…" : "Rollback"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2 className="section-title">Releases</h2>
      <div className="filter-bar">
        <label>
          Service
          <input
            type="text"
            placeholder="carevora-api"
            value={releaseService}
            onChange={(e) => setReleaseService(e.target.value)}
          />
        </label>
        <button className="btn btn-secondary" onClick={handleLoadReleases}>
          Load releases
        </button>
      </div>
      {releasesError && <div className="state state-error">Error: {releasesError}</div>}
      {releases && releases.length === 0 && <div className="state state-empty">No releases found</div>}
      {releases && releases.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Service</th>
              <th>Version</th>
              <th>Image</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {releases.map((r, i) => (
              <tr key={i}>
                <td>{String(r.service ?? "—")}</td>
                <td className="mono">{String(r.version ?? "—")}</td>
                <td className="mono">{String(r.image ?? "—")}</td>
                <td>{r.created_at ? new Date(String(r.created_at)).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
