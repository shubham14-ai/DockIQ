interface StatusBadgeProps {
  status: string;
}

const STATUS_CLASS: Record<string, string> = {
  online: "badge badge-ok",
  running: "badge badge-ok",
  ok: "badge badge-ok",
  offline: "badge badge-danger",
  exited: "badge badge-danger",
  degraded: "badge badge-warn",
  restarting: "badge badge-warn",
  paused: "badge badge-warn",
  unknown: "badge badge-muted",
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const cls = STATUS_CLASS[status?.toLowerCase()] ?? "badge badge-muted";
  return <span className={cls}>{status}</span>;
}
