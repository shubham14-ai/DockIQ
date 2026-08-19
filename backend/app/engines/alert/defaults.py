"""Default alert rules seeded per tenant when the Alert Engine starts.

Each entry is the keyword-arg dict used to construct an ``app.store.models.AlertRule``
row (minus ``tenant_id``, which the engine fills in at seed time). ``target_selector``
of ``{}`` means "applies to every container" (zero-config defaults per the design doc);
narrower selectors (``{"role": "db"}``, ``{"tech": "postgres"}``) can be added later
without touching the engine.

``condition`` shapes:
  - {"type": "threshold", "metric": "<promql>", "op": ">", "value": <float>}
      Evaluated periodically against VictoriaMetrics. ``metric`` is a full PromQL
      expression (not just a series name) so rules can be as specific as needed.
  - {"type": "health", "status": "unhealthy"}
      Evaluated inline as `health` events arrive.
  - {"type": "event", "event_type": "oom" | "die" | "crash_loop"}
      Evaluated inline as `events` arrive.
"""
from __future__ import annotations

DEFAULT_RULES: list[dict] = [
    {
        "name": "high-memory-usage",
        "target_selector": {},
        "condition": {
            "type": "threshold",
            "metric": "dockiq_mem_usage_ratio",
            "op": ">",
            "value": 0.9,
        },
        "for_seconds": 120,
        "severity": "warning",
        "actions": {"notify": []},
        "source": "default",
    },
    {
        "name": "high-cpu-usage",
        "target_selector": {},
        "condition": {
            "type": "threshold",
            "metric": "dockiq_cpu_usage_ratio",
            "op": ">",
            "value": 0.9,
        },
        "for_seconds": 120,
        "severity": "warning",
        "actions": {"notify": []},
        "source": "default",
    },
    {
        "name": "container-down",
        "target_selector": {},
        "condition": {
            "type": "threshold",
            "metric": "dockiq_container_up",
            "op": "==",
            "value": 0,
        },
        "for_seconds": 30,
        "severity": "critical",
        "actions": {"notify": []},
        "source": "default",
    },
    {
        "name": "container-unhealthy",
        "target_selector": {},
        "condition": {"type": "health", "status": "unhealthy"},
        "for_seconds": 0,
        "severity": "warning",
        "actions": {"notify": []},
        "source": "default",
    },
    {
        "name": "oom-kill",
        "target_selector": {},
        "condition": {"type": "event", "event_type": "oom"},
        "for_seconds": 0,
        "severity": "critical",
        "actions": {"notify": []},
        "source": "default",
    },
    {
        "name": "container-crash-loop",
        "target_selector": {},
        "condition": {
            "type": "event",
            "event_type": "crash_loop",
            "min_starts": 3,
            "window_seconds": 300,
        },
        "for_seconds": 0,
        "severity": "warning",
        "actions": {"notify": []},
        "source": "default",
    },
]
