interface RoleTechBadgeProps {
  role?: string | null;
  tech?: string | null;
  confidence?: number | null;
}

export function RoleTechBadge({ role, tech, confidence }: RoleTechBadgeProps) {
  if (!role && !tech) {
    return <span className="badge badge-muted">unclassified</span>;
  }
  const title = confidence != null ? `confidence: ${(confidence * 100).toFixed(0)}%` : undefined;
  return (
    <span className="badge-group" title={title}>
      {role && <span className="badge badge-role">{role}</span>}
      {tech && <span className="badge badge-tech">{tech}</span>}
    </span>
  );
}
