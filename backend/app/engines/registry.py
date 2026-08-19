"""Engine registry + dispatcher.

``start_all`` instantiates each engine, calls ``start``, and wires its subjects
to the bus so decoded JSON is dispatched to ``engine.handle``.

To add an engine: import its class and append an instance to ``build_engines``.
"""
from __future__ import annotations

import json
import logging

from nats.aio.msg import Msg

from app.bus.nats_bus import NatsBus
from app.engines.base import BaseEngine, EngineContext

log = logging.getLogger("dockiq.engines")

_engines: list[BaseEngine] = []


def build_engines() -> list[BaseEngine]:
    """Return the engine instances to run. Filled in as engines land."""
    engines: list[BaseEngine] = []

    # --- Phase 1 engines (wired as each lands) ---
    try:
        from app.engines.discovery.engine import DiscoveryEngine
        engines.append(DiscoveryEngine())
    except Exception:  # noqa: BLE001
        log.debug("discovery engine not available yet")

    try:
        from app.engines.classification.engine import ClassificationEngine
        engines.append(ClassificationEngine())
    except Exception:  # noqa: BLE001
        log.debug("classification engine not available yet")

    try:
        from app.engines.metrics.engine import MetricsEngine
        engines.append(MetricsEngine())
    except Exception:  # noqa: BLE001
        log.debug("metrics engine not available yet")

    try:
        from app.engines.logging.engine import LoggingEngine
        engines.append(LoggingEngine())
    except Exception:  # noqa: BLE001
        log.debug("logging engine not available yet")

    try:
        from app.engines.alert.engine import AlertEngine
        engines.append(AlertEngine())
    except Exception:  # noqa: BLE001
        log.debug("alert engine not available yet")

    # --- Phase 2 engines ---
    try:
        from app.engines.topology.engine import TopologyEngine
        engines.append(TopologyEngine())
    except Exception:  # noqa: BLE001
        log.debug("topology engine not available yet")

    try:
        from app.engines.anomaly.engine import AnomalyEngine
        engines.append(AnomalyEngine())
    except Exception:  # noqa: BLE001
        log.debug("anomaly engine not available yet")

    # --- Phase 3-5 engines ---
    try:
        from app.engines.dashboards.engine import DashboardEngine
        engines.append(DashboardEngine())
    except Exception:  # noqa: BLE001
        log.debug("dashboard engine not available yet")

    try:
        from app.engines.llm.engine import LLMEngine
        engines.append(LLMEngine())
    except Exception:  # noqa: BLE001
        log.debug("llm engine not available yet")

    try:
        from app.engines.healing.engine import HealingEngine
        engines.append(HealingEngine())
    except Exception:  # noqa: BLE001
        log.debug("healing engine not available yet")

    return engines


def _make_handler(engine: BaseEngine):
    async def _handler(msg: Msg) -> None:
        try:
            data = json.loads(msg.data.decode())
        except (ValueError, UnicodeDecodeError):
            engine.log.warning("dropping malformed message on %s", msg.subject)
            return
        try:
            await engine.handle(msg.subject, data)
        except Exception:  # noqa: BLE001 — keep the consumer alive
            engine.log.exception("handler failed for %s", msg.subject)

    return _handler


async def start_all(bus: NatsBus) -> None:
    global _engines
    _engines = build_engines()
    ctx = EngineContext(bus=bus)
    for engine in _engines:
        await engine.start(ctx)
        for subject in engine.subjects():
            await bus.subscribe(subject, _make_handler(engine))
        log.info("started engine %s (subjects=%s)", engine.name, engine.subjects())


async def stop_all() -> None:
    for engine in _engines:
        try:
            await engine.stop()
        except Exception:  # noqa: BLE001
            log.exception("error stopping engine %s", engine.name)
