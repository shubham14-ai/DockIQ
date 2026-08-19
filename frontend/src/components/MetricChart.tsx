import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MetricPoint } from "../api/metrics";

interface MetricChartProps {
  title: string;
  points: MetricPoint[];
  color: string;
  formatValue?: (v: number) => string;
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function MetricChart({ title, points, color, formatValue }: MetricChartProps) {
  const fmt = formatValue ?? ((v: number) => v.toFixed(2));
  const data = points.map((p) => ({ ts: p.timestamp, value: p.value }));
  const latest = points.length > 0 ? points[points.length - 1].value : undefined;

  return (
    <div className="metric-chart">
      <div className="metric-chart-header">
        <span className="metric-chart-title">{title}</span>
        {latest !== undefined && <span className="metric-chart-latest">{fmt(latest)}</span>}
      </div>
      <ResponsiveContainer width="100%" height={140}>
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`grad-${title}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.4} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="ts"
            tickFormatter={formatTime}
            stroke="var(--text-muted)"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            minTickGap={40}
          />
          <YAxis
            stroke="var(--text-muted)"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            width={40}
            tickFormatter={fmt}
          />
          <Tooltip
            contentStyle={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelFormatter={(ts) => formatTime(Number(ts))}
            formatter={(v: number) => fmt(v)}
          />
          <Area type="monotone" dataKey="value" stroke={color} fill={`url(#grad-${title})`} strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
