interface LoadingErrorProps {
  loading: boolean;
  error?: string;
  empty?: boolean;
  emptyLabel?: string;
}

/** Renders a loading/error/empty placeholder; returns null when there's real content to show. */
export function LoadingError({ loading, error, empty, emptyLabel = "No data" }: LoadingErrorProps) {
  if (error) {
    return <div className="state state-error">Error: {error}</div>;
  }
  if (loading) {
    return <div className="state state-loading">Loading…</div>;
  }
  if (empty) {
    return <div className="state state-empty">{emptyLabel}</div>;
  }
  return null;
}
