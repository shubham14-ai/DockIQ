"""Classification Engine.

Consumes ``discovery`` inventory snapshots and, for each container, scores
the evidence in the payload itself (image name, labels, exposed ports, env
var keys) against the rule catalog in ``catalog.py``. It does NOT read the
``containers`` table first — classification is derived purely from the
message so it never blocks on Discovery's write landing first.

See docs/phase1-agent-protocol.md for the payload contract and
docs/engines/02-classification-engine.md for the design.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.bus.subjects import DISCOVERY, wildcard
from app.engines.base import BaseEngine, EngineContext
from app.engines.classification.catalog import (
    CONFIDENCE_THRESHOLD,
    RULES,
    TECH_ROLES,
)
from app.store.db import SessionLocal
from app.store.models import Classification, Container

log = logging.getLogger("dockiq.engine.classification")

OVERRIDE_TECH_LABEL = "com.dockiq.tech"
OVERRIDE_ROLE_LABEL = "com.dockiq.role"


@dataclass
class ClassificationResult:
    tech: str | None
    role: str
    confidence: float
    source: str  # override|passive
    evidence: dict = field(default_factory=dict)


def _extract_ports(ports: dict | None) -> set[str]:
    """Pull raw port numbers out of a discovery ``ports`` map.

    Payload shape: ``{"8000/tcp": 8000}`` — the key's numeric prefix and the
    published-port value are both considered evidence.
    """
    found: set[str] = set()
    for key, value in (ports or {}).items():
        proto_part = str(key).split("/", 1)[0]
        if proto_part.isdigit():
            found.add(proto_part)
        if value is not None:
            found.add(str(value))
    return found


def classify(
    image: str | None,
    labels: dict | None,
    ports: dict | None,
    env: dict | None,
) -> ClassificationResult:
    labels = labels or {}

    # Overrides are always authoritative.
    override_tech = labels.get(OVERRIDE_TECH_LABEL)
    override_role = labels.get(OVERRIDE_ROLE_LABEL)
    if override_tech or override_role:
        tech = override_tech
        role = override_role or TECH_ROLES.get(override_tech or "", "unknown")
        return ClassificationResult(
            tech=tech,
            role=role,
            confidence=1.0,
            source="override",
            evidence={
                "override_labels": {
                    k: v
                    for k, v in labels.items()
                    if k in (OVERRIDE_TECH_LABEL, OVERRIDE_ROLE_LABEL)
                }
            },
        )

    image_l = (image or "").lower()
    port_set = _extract_ports(ports)
    env_keys_upper = {str(k).upper() for k in (env or {}).keys()}

    scores: dict[str, float] = {}
    matched: dict[str, list[dict]] = {}

    for rule in RULES:
        hit = False
        if rule.evidence_type == "image" and rule.pattern.lower() in image_l:
            hit = True
        elif rule.evidence_type == "port" and rule.pattern in port_set:
            hit = True
        elif rule.evidence_type == "env_key" and any(
            rule.pattern in k for k in env_keys_upper
        ):
            hit = True

        if hit:
            scores[rule.tech] = scores.get(rule.tech, 0.0) + rule.weight
            matched.setdefault(rule.tech, []).append(
                {"type": rule.evidence_type, "pattern": rule.pattern, "weight": rule.weight}
            )

    if not scores:
        return ClassificationResult(
            tech=None, role="unknown", confidence=0.0, source="passive", evidence={}
        )

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_tech, best_score = ranked[0]
    best_score = min(best_score, 1.0)

    candidates = [
        {"tech": t, "score": round(min(s, 1.0), 3)} for t, s in ranked[:5]
    ]
    evidence = {"matched": matched.get(best_tech, []), "candidates": candidates}

    if best_score < CONFIDENCE_THRESHOLD:
        return ClassificationResult(
            tech=best_tech,
            role="unknown",
            confidence=round(best_score, 3),
            source="passive",
            evidence=evidence,
        )

    return ClassificationResult(
        tech=best_tech,
        role=TECH_ROLES.get(best_tech, "unknown"),
        confidence=round(best_score, 3),
        source="passive",
        evidence=evidence,
    )


class ClassificationEngine(BaseEngine):
    name = "classification"

    def subjects(self) -> list[str]:
        return [wildcard(DISCOVERY)]

    async def start(self, ctx: EngineContext) -> None:
        await super().start(ctx)
        self.log.info("classification engine started")

    async def handle(self, subject: str, data: dict) -> None:
        tenant_id = data.get("tenant_id")
        host_id = data.get("host_id")
        containers = data.get("containers") or []
        if not tenant_id:
            self.log.warning("discovery snapshot missing tenant_id, dropping")
            return

        async with SessionLocal() as session:
            for c in containers:
                container_id = c.get("id")
                if not container_id:
                    continue
                result = classify(
                    image=c.get("image"),
                    labels=c.get("labels"),
                    ports=c.get("ports"),
                    env=c.get("env"),
                )
                await self._upsert_classification(
                    session, tenant_id, host_id, container_id, c, result
                )
            await session.commit()

        self.log.debug(
            "classified %d container(s) from host=%s", len(containers), host_id
        )

    async def stop(self) -> None:
        self.log.info("classification engine stopped")

    async def _upsert_classification(
        self,
        session,
        tenant_id: str,
        host_id: str | None,
        container_id: str,
        raw_container: dict,
        result: ClassificationResult,
    ) -> None:
        values = dict(
            container_id=container_id,
            tenant_id=tenant_id,
            role=result.role,
            tech=result.tech,
            confidence=result.confidence,
            evidence=result.evidence,
            source=result.source,
            overridden=result.source == "override",
        )

        async def _do_upsert() -> None:
            stmt = pg_insert(Classification).values(**values)
            update_cols = {
                k: stmt.excluded[k] for k in values if k != "container_id"
            }
            update_cols["classified_at"] = func.now()
            stmt = stmt.on_conflict_do_update(
                index_elements=[Classification.container_id], set_=update_cols
            )
            await session.execute(stmt)

        try:
            async with session.begin_nested():
                await _do_upsert()
        except IntegrityError:
            # Classification carries a FK to containers.id. We intentionally
            # classify from the message alone (not waiting on Discovery's
            # write), so on a first-seen container we may race Discovery's
            # own upsert. Self-heal by inserting a minimal container stub
            # (never overwriting an existing row) and retry once.
            await self._ensure_container_stub(
                session, tenant_id, host_id, container_id, raw_container
            )
            async with session.begin_nested():
                await _do_upsert()

    async def _ensure_container_stub(
        self,
        session,
        tenant_id: str,
        host_id: str | None,
        container_id: str,
        raw_container: dict,
    ) -> None:
        stub = dict(
            id=container_id,
            tenant_id=tenant_id,
            host_id=host_id,
            name=raw_container.get("name") or container_id[:12],
        )
        stmt = pg_insert(Container).values(**stub)
        stmt = stmt.on_conflict_do_nothing(index_elements=[Container.id])
        async with session.begin_nested():
            await session.execute(stmt)
