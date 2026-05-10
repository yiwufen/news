"""Event type vocabulary mapping between user-facing terms and database unit_type values.

Delegates to the canonical ``UNIT_TYPE_ALIASES`` in ``schemas.enums`` so that
the mapping is maintained in a single place.
"""

from __future__ import annotations

from src.schemas.enums import UnitType, _UNIT_TYPE_ALIASES, get_unit_type_synonyms


def expand_event_types(user_types: list[str]) -> list[str]:
    """Expand user-facing event type terms to all known database variants.

    Each input term is first normalized to a canonical ``UnitType``, then all
    known synonyms for that type are returned.  Unknown terms pass through
    unchanged so that future database values still work without a mapping update.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for term in user_types:
        canonical = _UNIT_TYPE_ALIASES.get(term.lower())
        if canonical is not None:
            for synonym in get_unit_type_synonyms(canonical):
                key = synonym.lower()
                if key not in seen:
                    seen.add(key)
                    expanded.append(synonym)
        else:
            key = term.lower()
            if key not in seen:
                seen.add(key)
                expanded.append(term)
    return expanded
