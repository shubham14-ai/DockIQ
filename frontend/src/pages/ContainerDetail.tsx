import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getContainer } from "../api/containers";
import { getContainerLogs, queryRange, type MetricPoint } from "../api/metrics";
import { LoadingError } from "../components/LoadingError";
import { MetricChart } from "../components/MetricChart";
import { RoleTechBadge } from "../components/RoleTechBadge";
import { StatusBadge } from "../components/StatusBadge";
import { usePolling } from "../hooks/usePolling";
import type { LogLine } from "../api/types";

const METRICS_POLL_MS = 15_000;
const LOGS_POLL_MS = 3_000;
const CONTAINER_POLL_MS = 5_000;
const WINDOW_SECONDS = 30 * 60;
const STEP = "15s";
const LOG_LIMIT = 300;

function useMetric(promqlLabel: (id: string) => string, containerId: string) {
  return usePolling<MetricPoint[]>(
    () => {
      const end = Math.floor(Date.now() / 1000);
      const start = end - WINDOW_SECONDS;
      return queryRange({ query: promqlLabel(containerId), start, end, step: STEP });
    },
    METRICS_POLL_MS,
    [containerId],
  );
}

export function ContainerDetail() {
  const { containerId = "" } = useParams();
  const container = usePolling(() => getContainer(containerId), CONTAINER_POLL_MS, [containerId]);

  const cpu = useMetric((id) => `dockiq_cpu_usage_ratio{container_id="${id}"}`, containerId);
  const mem = useMetric((id) => `dockiq_mem_usage_ratio{container_id="${id}"}`, containerId);

  const [logs, setLogs] = useState<LogLine[]>([]);
  const [logsError, setLogsError] = useState<string | undefined>(undefined);
  const logRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);

  const fetchLogs = useCallback(async () => {
    try {
      const lines = await getContainerLogs(containerId, LOG_LIMIT);
      setLogs(lines);
      setLogsError(undefined);
    } catch (err) {
      setLogsError(err instanceof Error ? err.message : String(err));
    }
  }, [containerId]);

  useEffect(() => {
    fetchLogs();
    const id = setInterval(fetchLogs, LOGS_POLL_MS);
    return () => clearInterval(id);
  }, [fetchLogs]);

  useEffect(() => {
    if (autoScrollRef.current && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  const c = container.data;

  return (
    <div className="page">
      <header className="page-header">
        <Link to="/containers" className="link back-link">
          ← Containers
        </Link>
        <h1>{c?.name ?? containerId}</h1>
      </header>

      <LoadingError loading={container.loading && !c} error={container.error} />

      {c && (
        <section className="detail-grid">
          <div className="detail-item">
            <div className="detail-label">State</div>
            <StatusBadge status={c.state} />
          </div>
          <div className="detail-item">
            <div className="detail-label">Classification</div>
            <RoleTechBadge
              role={c.role ?? c.classification?.role}
              tech={c.tech ?? c.classification?.tech}
              confidence={c.classification?.confidence}
            />
          </div>
          <div className="detail-item">
            <div className="detail-label">Host</div>
            {c.host_id ? (
              <Link to={`/hosts/${c.host_id}`} className="link">
                {c.host_name ?? c.host_id}
              </Link>
            ) : (
              "—"
            )}
          </div>
          <div className="detail-item">
            <div className="detail-label">Image</div>
            <div className="mono">{c.image}</div>
          </div>
        </section>
      )}

      <section>
        <h2>Metrics (last 30m)</h2>
        <div className="chart-grid">
          <div>
            <LoadingError loading={cpu.loading && !cpu.data} error={cpu.error} empty={cpu.data?.length === 0} emptyLabel="No CPU data yet" />
            {cpu.data && cpu.data.length > 0 && (
              <MetricChart
                title="CPU usage"
                points={cpu.data}
                color="var(--accent)"
                formatValue={(v) => `${(v * 100).toFixed(0)}%`}
              />
            )}
          </div>
          <div>
            <LoadingError loading={mem.loading && !mem.data} error={mem.error} empty={mem.data?.length === 0} emptyLabel="No memory data yet" />
            {mem.data && mem.data.length > 0 && (
              <MetricChart
                title="Memory usage"
                points={mem.data}
                color="var(--accent-2)"
                formatValue={(v) => `${(v * 100).toFixed(0)}%`}
              />
            )}
          </div>
        </div>
      </section>

      <section>
        <h2>Logs</h2>
        <LoadingError loading={logs.length === 0 && !logsError} error={logsError} />
        <div
          className="log-panel"
          ref={logRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          }}
        >
          {logs.map((l, i) => (
            <div key={`${l.timestampNs}-${i}`} className="log-line">
              {l.line}
            </div>
          ))}
          {logs.length === 0 && !logsError && <div className="state state-empty">No log lines yet</div>}
        </div>
      </section>
    </div>
  );
}
