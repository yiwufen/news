"""
Entity context filtering for LLM extraction prompt injection.

Controls token consumption by selecting only relevant entities from the knowledge base.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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


def filter_relevant_entities(
    document: "RawDocument",
    all_entities: dict[str, "Entity"],
    max_entities: int = 50,
    max_tokens_estimate: int = 2000,
) -> list[EntityContext]:
    """
    Filter entities relevant to the current document for prompt injection.

    Strategy:
    1. Exact match of canonical name in title/content → high priority
    2. Match of alias in title/content → medium priority
    3. Match of identifier (e.g., ticker) → high priority

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

    # Pre-compute lowercase text once for efficiency
    text_lower = f"{document.title} {document.content}".lower()
    scored_entities: list[tuple[float, "Entity"]] = []

    for entity in all_entities.values():
        score = _compute_relevance_score(entity, text_lower)
        if score > 0:
            scored_entities.append((score, entity))

    # Sort by relevance score (descending), then by name for stability
    scored_entities.sort(key=lambda x: (-x[0], x[1].canonical_name))
    selected = scored_entities[:max_entities]

    # Token budget control
    result: list[EntityContext] = []
    estimated_tokens = 0

    for score, entity in selected:
        entity_ctx = EntityContext(
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            identifiers=entity.identifiers,
            aliases=entity.aliases[:3],  # Limit aliases to control tokens
        )

        # Estimate: base 20 tokens + 5 tokens per alias
        entity_tokens = 20 + len(entity_ctx.aliases) * 5
        if estimated_tokens + entity_tokens > max_tokens_estimate:
            break

        estimated_tokens += entity_tokens
        result.append(entity_ctx)

    return result


def _compute_relevance_score(entity: "Entity", text_lower: str) -> float:
    """
    Compute relevance score between an entity and document text.

    Scoring:
    - Canonical name exact match: 10 points
    - Alias match: 5 points each
    - Identifier match (e.g., ticker): 8 points each

    Args:
        entity: The entity to score
        text_lower: Pre-lowercased document text for efficient matching
    """
    score = 0.0

    # Exact match of canonical name
    if entity.canonical_name and entity.canonical_name.lower() in text_lower:
        score += 10.0

    # Match aliases
    for alias in entity.aliases:
        if alias and alias.lower() in text_lower:
            score += 5.0

    # Match identifiers (e.g., stock tickers)
    for identifier in entity.identifiers.values():
        if identifier and identifier.lower() in text_lower:
            score += 8.0

    return score


def build_entity_context_section(entities: list[EntityContext]) -> str:
    """
    Build the entity context section for the extraction prompt.

    Args:
        entities: List of entity contexts to include

    Returns:
        Formatted prompt section string
    """
    if not entities:
        return ""

    section = "\n## 已知实体参考\n"
    section += "以下实体已在知识库中存在，抽取时请优先使用标准名称：\n\n"

    for entity in entities:
        # Format: "标准名称 (类型) [标识符]"
        identifiers_str = ""
        if entity.identifiers:
            key_id = next(iter(entity.identifiers.values()), "")
            if key_id:
                identifiers_str = f" [{key_id}]"

        section += f"- **{entity.canonical_name}** ({entity.entity_type}){identifiers_str}\n"

        # Add aliases if present
        if entity.aliases:
            section += f"  别名: {', '.join(entity.aliases)}\n"

    return section
