"""Event type vocabulary mapping between user-facing terms and database unit_type values.

Delegates to the canonical ``UNIT_TYPE_ALIASES`` in ``schemas.enums`` so that
the mapping is maintained in a single place.
"""

from __future__ import annotations

import logging

from src.schemas.enums import UnitType, get_unit_type_synonyms, normalize_unit_type

logger = logging.getLogger(__name__)


def expand_event_types(user_types: list[str]) -> list[str]:
    """Expand user-facing event type terms to all known database variants.

    Each input term is normalized to a canonical ``UnitType`` via
    ``normalize_unit_type`` (alias + keyword pattern matching).  Terms that
    cannot be resolved to a known type are **dropped** instead of passed
    through, because raw Chinese strings will never match the English
    ``unit_type`` values stored in the database.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for term in user_types:
        canonical = normalize_unit_type(term)
        if canonical == UnitType.OTHER:
            logger.debug("expand_event_types: unmapped term '%s' dropped", term)
            continue
        for synonym in get_unit_type_synonyms(canonical):
            key = synonym.lower()
            if key not in seen:
                seen.add(key)
                expanded.append(synonym)
    return expanded
