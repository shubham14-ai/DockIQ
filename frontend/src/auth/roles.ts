// Mirrors the backend RBAC role order (app/auth/roles.py).
export const ROLES = ["viewer", "operator", "deployer", "admin", "owner"] as const;

export function roleAtLeast(role: string, minimum: string): boolean {
  return ROLES.indexOf(role as never) >= ROLES.indexOf(minimum as never);
}
