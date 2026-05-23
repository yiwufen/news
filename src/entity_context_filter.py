"""
Entity context filtering for LLM extraction prompt injection.

Controls token consumption by selecting only relevant entities from the knowledge base.
Uses Aho-Corasick automaton for efficient longest-match entity detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import ahocorasick

if TYPE_CHECKING:
    from src.entities import Entity
    from src.knowledge_base import RawDocument


@dataclass
class EntityContext:
    """Entity context injected into LLM extraction prompt."""

    canonical_name: str
    entity_type: str
    identifiers: dict[str, str] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)


def _build_automaton(
    all_entities: dict[str, "Entity"],
) -> tuple[ahocorasick.Automaton, dict[str, str]]:
    """Build Aho-Corasick automaton from entity names/aliases.

    Returns:
        (automaton, name_to_entity_id) — automaton maps lowercase names to entity_id.
        name_to_entity_id maps each lowercase name back to entity_id.
    """
    automaton = ahocorasick.Automaton()
    # name_lower → entity_id; last write wins for duplicate names across entities
    name_to_entity_id: dict[str, str] = {}

    for entity_id, entity in all_entities.items():
        if entity.canonical_name:
            key = entity.canonical_name.lower()
            name_to_entity_id[key] = entity_id
            automaton.add_word(key, key)

        for alias in entity.aliases:
            if alias:
                key = alias.lower()
                if key not in name_to_entity_id:
                    name_to_entity_id[key] = entity_id
                    automaton.add_word(key, key)

    automaton.make_automaton()
    return automaton, name_to_entity_id


def filter_relevant_entities(
    document: "RawDocument",
    all_entities: dict[str, "Entity"],
    max_entities: int = 50,
    max_tokens_estimate: int = 2000,
) -> list[EntityContext]:
    """Filter entities relevant to the current document for prompt injection.

    Uses Aho-Corasick automaton for O(text_length) matching with longest-match
    semantics. Separately checks identifiers (tickers, etc.) via substring match.

    Args:
        document: The raw document being processed
        all_entities: All entities from the knowledge base (entity_id -> Entity)
        max_entities: Maximum number of entities to inject
        max_tokens_estimate: Token budget for entity context section

    Returns:
        List of EntityContext objects sorted by relevance
    """
    if not all_entities:
        return []

    text_lower = f"{document.title} {document.content}".lower()

    automaton, name_to_entity_id = _build_automaton(all_entities)

    # Collect matched entity_ids with hit details
    entity_hits: dict[str, list[tuple[int, str]]] = {}  # entity_id → [(length, matched_name)]

    for end_index, matched_name in automaton.iter(text_lower):
        entity_id = name_to_entity_id[matched_name]
        length = len(matched_name)
        entity_hits.setdefault(entity_id, []).append((length, matched_name))

    # Also match identifiers (tickers, etc.) via substring
    for entity in all_entities.values():
        for identifier in entity.identifiers.values():
            if identifier and identifier.lower() in text_lower:
                entity_hits.setdefault(entity.entity_id, []).append(
                    (len(identifier), identifier),
                )

    # Score entities: longest match × hit count, with bonus for canonical name
    scored: list[tuple[float, "Entity"]] = []
    for entity_id, hits in entity_hits.items():
        entity = all_entities[entity_id]
        max_len = max(h[0] for h in hits)
        hit_count = len(hits)
        # Canonical name match gets bonus
        canonical_bonus = 2.0 if any(
            h[1] == entity.canonical_name.lower() for h in hits
        ) else 0.0
        score = max_len * hit_count + canonical_bonus
        scored.append((score, entity))

    scored.sort(key=lambda x: (-x[0], x[1].canonical_name))
    selected = scored[:max_entities]

    # Token budget control
    result: list[EntityContext] = []
    estimated_tokens = 0

    for score, entity in selected:
        entity_ctx = EntityContext(
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type or "",
            identifiers=entity.identifiers,
            aliases=entity.aliases[:3],
        )

        entity_tokens = 20 + len(entity_ctx.aliases) * 5
        if estimated_tokens + entity_tokens > max_tokens_estimate:
            break

        estimated_tokens += entity_tokens
        result.append(entity_ctx)

    return result


def build_entity_context_section(entities: list[EntityContext]) -> str:
    """Build the entity context section for the extraction prompt."""
    if not entities:
        return ""

    section = "\n## 已知实体参考\n"
    section += "以下实体已在知识库中存在，抽取时请优先使用标准名称：\n\n"

    for entity in entities:
        identifiers_str = ""
        if entity.identifiers:
            key_id = next(iter(entity.identifiers.values()), "")
            if key_id:
                identifiers_str = f" [{key_id}]"

        section += f"- **{entity.canonical_name}** ({entity.entity_type}){identifiers_str}\n"

        if entity.aliases:
            section += f"  别名: {', '.join(entity.aliases)}\n"

    return section
