"""Declarative rule catalog for the Classification Engine.

Each :class:`Rule` maps one piece of evidence (an image-name substring, an
exposed/published port, or an environment-variable-key substring) to a
candidate ``(tech, role, weight)``. The scorer in ``engine.py`` sums the
weights of every rule that matches a container's facts; the technology with
the highest total wins, subject to a minimum confidence threshold.

Extending the catalog: add rules to ``RULES`` (and, for a brand new
technology, an entry in ``TECH_ROLES``). No other code changes needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Roles allowed downstream (dashboards/alerts/topology key off these).
Role = Literal[
    "api",
    "worker",
    "database",
    "queue",
    "cache",
    "frontend",
    "vectordb",
    "ai",
    "proxy",
    "unknown",
]

EvidenceType = Literal["image", "port", "env_key"]


@dataclass(frozen=True)
class Rule:
    evidence_type: EvidenceType
    pattern: str  # substring (image/env_key, case-insensitive) or exact port (str)
    tech: str
    weight: float


# Below this aggregate score, the container is classified as role="unknown"
# (tech is still recorded in evidence as the best guess).
CONFIDENCE_THRESHOLD = 0.45

# tech -> role. Every tech referenced in RULES must have an entry here.
TECH_ROLES: dict[str, Role] = {
    "fastapi": "api",
    "django": "api",
    "flask": "api",
    "express": "api",
    "nginx": "proxy",
    "traefik": "proxy",
    "postgres": "database",
    "mysql": "database",
    "mongodb": "database",
    "redis": "cache",
    "memcached": "cache",
    "elasticsearch": "database",
    "kafka": "queue",
    "rabbitmq": "queue",
    "nats": "queue",
    "qdrant": "vectordb",
    "chromadb": "vectordb",
    "milvus": "vectordb",
    "celery": "worker",
    "airflow": "worker",
    "prometheus": "worker",
    "grafana": "frontend",
    "loki": "database",
    "victoriametrics": "database",
}

RULES: list[Rule] = [
    # -- Web / API frameworks -----------------------------------------------
    Rule("image", "fastapi", "fastapi", 0.6),
    Rule("image", "uvicorn", "fastapi", 0.4),
    Rule("env_key", "FASTAPI", "fastapi", 0.3),
    Rule("port", "8000", "fastapi", 0.15),

    Rule("image", "django", "django", 0.6),
    Rule("env_key", "DJANGO_SETTINGS", "django", 0.4),
    Rule("env_key", "DJANGO_SECRET", "django", 0.3),
    Rule("port", "8000", "django", 0.1),

    Rule("image", "flask", "flask", 0.6),
    Rule("env_key", "FLASK_APP", "flask", 0.4),
    Rule("env_key", "FLASK_ENV", "flask", 0.3),
    Rule("port", "5000", "flask", 0.15),

    Rule("image", "node", "express", 0.25),
    Rule("image", "express", "express", 0.5),
    Rule("env_key", "NODE_ENV", "express", 0.3),
    Rule("env_key", "EXPRESS_", "express", 0.3),
    Rule("port", "3000", "express", 0.15),

    # -- Proxies --------------------------------------------------------------
    Rule("image", "nginx", "nginx", 0.7),
    Rule("port", "80", "nginx", 0.1),
    Rule("port", "443", "nginx", 0.1),

    Rule("image", "traefik", "traefik", 0.7),
    Rule("port", "8080", "traefik", 0.1),
    Rule("env_key", "TRAEFIK_", "traefik", 0.2),

    # -- Databases --------------------------------------------------------------
    Rule("image", "postgres", "postgres", 0.7),
    Rule("port", "5432", "postgres", 0.3),
    Rule("env_key", "POSTGRES_", "postgres", 0.3),
    Rule("env_key", "PGPASSWORD", "postgres", 0.2),
    Rule("env_key", "POSTGRES_DSN", "postgres", 0.2),

    Rule("image", "mysql", "mysql", 0.7),
    Rule("port", "3306", "mysql", 0.3),
    Rule("env_key", "MYSQL_", "mysql", 0.3),

    Rule("image", "mongo", "mongodb", 0.7),
    Rule("port", "27017", "mongodb", 0.3),
    Rule("env_key", "MONGO_", "mongodb", 0.3),

    Rule("image", "elasticsearch", "elasticsearch", 0.7),
    Rule("image", "elastic", "elasticsearch", 0.3),
    Rule("port", "9200", "elasticsearch", 0.3),
    Rule("env_key", "ELASTIC_", "elasticsearch", 0.2),

    Rule("image", "loki", "loki", 0.7),
    Rule("port", "3100", "loki", 0.3),

    Rule("image", "victoriametrics", "victoriametrics", 0.7),
    Rule("image", "victoria-metrics", "victoriametrics", 0.5),
    Rule("port", "8428", "victoriametrics", 0.3),

    # -- Caches --------------------------------------------------------------
    Rule("image", "redis", "redis", 0.7),
    Rule("port", "6379", "redis", 0.3),
    Rule("env_key", "REDIS_", "redis", 0.3),

    Rule("image", "memcached", "memcached", 0.7),
    Rule("port", "11211", "memcached", 0.3),

    # -- Messaging / queues --------------------------------------------------
    Rule("image", "kafka", "kafka", 0.7),
    Rule("port", "9092", "kafka", 0.3),
    Rule("env_key", "KAFKA_", "kafka", 0.3),

    Rule("image", "rabbitmq", "rabbitmq", 0.7),
    Rule("port", "5672", "rabbitmq", 0.3),
    Rule("env_key", "RABBITMQ_", "rabbitmq", 0.3),

    Rule("image", "nats", "nats", 0.6),
    Rule("port", "4222", "nats", 0.3),
    Rule("env_key", "NATS_", "nats", 0.2),

    # -- Vector DBs --------------------------------------------------------------
    Rule("image", "qdrant", "qdrant", 0.7),
    Rule("port", "6333", "qdrant", 0.3),
    Rule("env_key", "QDRANT_", "qdrant", 0.2),

    Rule("image", "chroma", "chromadb", 0.7),
    Rule("port", "8000", "chromadb", 0.1),
    Rule("env_key", "CHROMA_", "chromadb", 0.2),

    Rule("image", "milvus", "milvus", 0.7),
    Rule("port", "19530", "milvus", 0.3),

    # -- Workers / orchestration --------------------------------------------
    Rule("image", "celery", "celery", 0.6),
    Rule("env_key", "CELERY_BROKER", "celery", 0.4),
    Rule("env_key", "CELERY_", "celery", 0.2),

    Rule("image", "airflow", "airflow", 0.7),
    Rule("env_key", "AIRFLOW__", "airflow", 0.3),
    Rule("port", "8080", "airflow", 0.05),

    # -- Observability --------------------------------------------------------
    Rule("image", "prometheus", "prometheus", 0.7),
    Rule("port", "9090", "prometheus", 0.3),

    Rule("image", "grafana", "grafana", 0.7),
    Rule("port", "3000", "grafana", 0.1),
    Rule("env_key", "GF_", "grafana", 0.2),
]
