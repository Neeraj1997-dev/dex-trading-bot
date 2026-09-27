"""Audit logging for all trading actions."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.logging import get_logger
from app.models.documents import AuditLogDoc
from app.services.notify.whatsapp import get_notifier

logger = get_logger(__name__)


async def write_audit(
    action: str,
    actor: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLogDoc:
    # Never log secrets
    safe = dict(details or {})
    for key in list(safe.keys()):
        lower = key.lower()
        if any(s in lower for s in ("key", "secret", "password", "private", "mnemonic")):
            safe[key] = "[REDACTED]"

    doc = AuditLogDoc(
        action=action,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        details=safe,
    )
    await doc.insert()
    logger.info("audit", action=action, actor=actor, entity_type=entity_type, entity_id=entity_id)

    try:
        await get_notifier().notify_action(action, safe)
    except Exception as exc:
        logger.warning("whatsapp_notify_failed", action=action, error=str(exc))

    return doc
