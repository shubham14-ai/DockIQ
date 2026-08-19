"""Deployment & Release layer (Phase 6).

Not a ``BaseEngine`` / not in the registry — this is an on-demand service
invoked by the API (``app/api/deployments.py``) rather than a background
loop. See ``service.py`` for ``deploy()`` / ``rollback()``.
"""
from __future__ import annotations
