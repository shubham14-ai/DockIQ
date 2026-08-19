import { apiGet } from "./client";
import type { LogLine, LokiQueryRangeResponse, PromQueryRangeResponse } from "./types";

export interface MetricPoint {
  timestamp: number; // unix seconds
  value: number;
}

export interface QueryRangeParams {
  query: string;
  start: number; // unix seconds
  end: number; // unix seconds
  step: string; // e.g. "15s"
}

/** Runs a PromQL range query and flattens the first matrix series into points. */
export async function queryRange(params: QueryRangeParams): Promise<MetricPoint[]> {
  const res = await apiGet<PromQueryRangeResponse>("/metrics/query_range", {
    query: params.query,
    start: params.start,
    end: params.end,
    step: params.step,
  });

  const series = res.data?.result?.[0];
  if (!series) return [];

  return series.values.map(([ts, val]) => ({
    timestamp: ts,
    value: Number.parseFloat(val),
  }));
}

export async function getContainerLogs(containerId: string, limit = 200): Promise<LogLine[]> {
  const res = await apiGet<LokiQueryRangeResponse>(`/containers/${encodeURIComponent(containerId)}/logs`, {
    limit,
  });

  const streams = res.data?.result ?? [];
  const lines: LogLine[] = [];
  for (const stream of streams) {
    for (const [ts, line] of stream.values) {
      lines.push({ timestampNs: ts, line });
    }
  }
  // Loki returns newest-first per stream typically; sort ascending by time for a tail view.
  lines.sort((a, b) => (a.timestampNs < b.timestampNs ? -1 : a.timestampNs > b.timestampNs ? 1 : 0));
  return lines;
}
