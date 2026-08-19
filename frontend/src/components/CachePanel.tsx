import { useState } from "react";
import {
  CACHE_TARGETS,
  DEFAULT_CACHE_TARGETS,
  pruneCache,
  scanCache,
  type CacheResult,
  type CacheTarget,
} from "../api/maintenance";

function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1);
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

const TARGET_LABEL: Record<CacheTarget, string> = {
  "build-cache": "Build cache",
  images: "Dangling images",
  containers: "Stopped containers",
  networks: "Unused networks",
  volumes: "Unused volumes",
};

/**
 * Cache-clearing panel with the two-step approval flow:
 *   Scan (safe, read-only)  →  review reclaimable space  →  Approve & clear.
 * The prune call only fires with `approve: true`, and the backend rejects it
 * otherwise — so nothing is deleted without a deliberate second click.
 */
export function CachePanel({ hostId }: { hostId: string }) {
  const [selected, setSelected] = useState<CacheTarget[]>(DEFAULT_CACHE_TARGETS);
  const [scan, setScan] = useState<CacheResult | null>(null);
  const [pruned, setPruned] = useState<CacheResult | null>(null);
  const [busy, setBusy] = useState<"scan" | "prune" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggle = (t: CacheTarget) => {
    setScan(null); // selection changed → previous scan no longer matches
    setPruned(null);
    setSelected((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));
  };

  const runScan = async () => {
    setBusy("scan");
    setError(null);
    setPruned(null);
    try {
      const res = await scanCache(hostId, selected);
      if (!res.ok) setError(res.error ?? "Scan failed (agent offline?)");
      setScan(res.ok ? res : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setBusy(null);
    }
  };

  const runPrune = async () => {
    const hasVolumes = selected.includes("volumes");
    const ok = window.confirm(
      `Clear cache on this host?\n\nTargets: ${selected.join(", ")}\n` +
        `Estimated reclaimable: ${formatBytes(scan?.reclaimable_bytes)}` +
        (hasVolumes
          ? "\n\n⚠ Volumes are selected — this can permanently delete data in unused volumes."
          : "") +
        "\n\nThis cannot be undone.",
    );
    if (!ok) return;

    setBusy("prune");
    setError(null);
    try {
      // approve: true is the required human-in-the-loop gate.
      const res = await pruneCache(hostId, { targets: selected, approve: true });
      if (!res.ok) setError(res.error ?? "Prune failed");
      setPruned(res);
      setScan(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Prune failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="cache-panel">
      <h2>Cache maintenance</h2>
      <p className="page-subtitle">
        Reclaim unwanted Docker cache. <strong>Scan</strong> is read-only; nothing is deleted until you review the
        result and click <strong>Approve &amp; clear</strong>.
      </p>

      <div className="cache-targets">
        {CACHE_TARGETS.map((t) => (
          <label key={t} className="cache-target">
            <input type="checkbox" checked={selected.includes(t)} onChange={() => toggle(t)} disabled={!!busy} />
            <span>{TARGET_LABEL[t]}</span>
            {t === "volumes" && <span className="badge badge-danger" style={{ marginLeft: 6 }}>data loss</span>}
          </label>
        ))}
      </div>

      <div className="cache-actions">
        <button className="btn" onClick={runScan} disabled={!!busy || selected.length === 0}>
          {busy === "scan" ? "Scanning…" : "Scan"}
        </button>
        <button
          className="btn btn-secondary"
          onClick={runPrune}
          disabled={!!busy || !scan || selected.length === 0}
          title={!scan ? "Run a scan first" : "Reclaim the space shown"}
        >
          {busy === "prune" ? "Clearing…" : "Approve & clear"}
        </button>
      </div>

      {error && <div className="diagnostics-banner">{error}</div>}

      {scan && (
        <div className="cache-result">
          <div className="cache-result-total">
            Reclaimable: <strong>{formatBytes(scan.reclaimable_bytes)}</strong>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Target</th>
                <th>Items</th>
                <th>Reclaimable</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(scan.targets ?? {}).map(([k, v]) => (
                <tr key={k}>
                  <td>{TARGET_LABEL[k as CacheTarget] ?? k}</td>
                  <td>{v.count ?? 0}</td>
                  <td>{formatBytes(v.reclaimable_bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pruned && (
        <div className="cache-result">
          <div className="cache-result-total">
            {pruned.ok ? (
              <>Reclaimed: <strong>{formatBytes(pruned.reclaimed_bytes)}</strong></>
            ) : (
              <span className="badge badge-danger">Failed</span>
            )}
          </div>
          {pruned.targets && (
            <table className="table">
              <thead>
                <tr>
                  <th>Target</th>
                  <th>Removed</th>
                  <th>Reclaimed</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(pruned.targets).map(([k, v]) => (
                  <tr key={k}>
                    <td>{TARGET_LABEL[k as CacheTarget] ?? k}</td>
                    <td>{v.removed ?? 0}</td>
                    <td>{formatBytes(v.reclaimed_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}
