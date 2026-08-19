"""RBAC roles, ordered by privilege. Higher index = more privilege."""
from __future__ import annotations

ROLES = ["viewer", "operator", "deployer", "admin", "owner"]
_RANK = {r: i for i, r in enumerate(ROLES)}


def rank(role: str) -> int:
    return _RANK.get(role, -1)


def has_at_least(role: str, minimum: str) -> bool:
    return rank(role) >= rank(minimum)


# What each role can do (documentation + coarse gating reference):
#   viewer   — read everything
#   operator — + ack alerts, manual heal, restart containers
#   deployer — + deployments, rollback, healing policies
#   admin    — + users, API keys, dashboards regen, alert rules
#   owner    — + tenant management
