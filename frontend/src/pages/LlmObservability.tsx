import { getLlmCost, getLlmLatency, getLlmStatus } from "../api/llm";
import { LoadingError } from "../components/LoadingError";
import type { PromVectorSample } from "../api/types";
import { usePolling } from "../hooks/usePolling";

const POLL_MS = 15000;

interface Row {
  service: string;
  model: string;
  value: number;
}

function toRows(samples: PromVectorSample[] | undefined): Row[] {
  if (!samples) return [];
  return samples.map((s) => ({
    service: s.metric.service ?? "unknown",
    model: s.metric.model ?? "unknown",
    value: Number(s.value?.[1] ?? 0),
  }));
}

export function LlmObservability() {
  const status = usePolling(() => getLlmStatus(), POLL_MS);
  const cost = usePolling(() => getLlmCost(), POLL_MS);
  const latency = usePolling(() => getLlmLatency(), POLL_MS);

  const costRows = toRows(cost.data?.data?.result);
  const latencyRows = toRows(latency.data?.data?.result);
  const isEmpty = costRows.length === 0 && latencyRows.length === 0;

  return (
    <div className="page">
      <header className="page-header">
        <h1>LLM Observability</h1>
        <p className="page-subtitle">Cost and latency for LLM calls made by tracked services.</p>
      </header>

      {status.data && !status.data.enabled && (
        <div className="diagnostics-banner">LLM observability is not enabled on the backend.</div>
      )}

      <LoadingError
        loading={(cost.loading || latency.loading) && !cost.data && !latency.data}
        error={cost.error || latency.error}
      />

      {!cost.loading && !latency.loading && isEmpty && (
        <div className="state state-empty">
          No LLM spans recorded yet. Send spans to <code>POST /api/v1/llm/ingest</code> to populate this page.
        </div>
      )}

      {costRows.length > 0 && (
        <>
          <h2 className="section-title">Cost by service / model (USD)</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Service</th>
                <th>Model</th>
                <th>Cost (USD)</th>
              </tr>
            </thead>
            <tbody>
              {costRows.map((r, i) => (
                <tr key={i}>
                  <td>{r.service}</td>
                  <td className="mono">{r.model}</td>
                  <td>${r.value.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {latencyRows.length > 0 && (
        <>
          <h2 className="section-title">Average latency by service / model</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Service</th>
                <th>Model</th>
                <th>Latency (s)</th>
              </tr>
            </thead>
            <tbody>
              {latencyRows.map((r, i) => (
                <tr key={i}>
                  <td>{r.service}</td>
                  <td className="mono">{r.model}</td>
                  <td>{r.value.toFixed(3)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
