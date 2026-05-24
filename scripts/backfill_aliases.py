"""Batch backfill entity aliases for existing entities with few aliases.

Usage:
    uv run python scripts/backfill_aliases.py [--dry-run] [--limit N] [--db data/news.db]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.alias_generator import AliasGenerator
from src.entities import Entity, EntityRepository, normalize_entity_name

logger = logging.getLogger(__name__)

_MAX_ALIASES = 10


def backfill_aliases(
    db_path: str = "data/news.db",
    dry_run: bool = False,
    limit: int | None = None,
) -> None:
    repo = EntityRepository(db_path)
    generator = AliasGenerator()

    entities = repo.get_all()
    # Filter: entities with fewer than 3 aliases
    candidates = [e for e in entities if len(e.aliases) < 3]
    if limit:
        candidates = candidates[:limit]

    print(f"Total entities: {len(entities)}")
    print(f"Candidates (aliases < 3): {len(candidates)}")
    if dry_run:
        print("[DRY RUN] No changes will be written.")
    print()

    updated_entities: list[Entity] = []

    updated_count = 0
    for entity in candidates:
        existing_aliases = set(entity.aliases)
        existing_norms = {normalize_entity_name(a) for a in entity.aliases}

        try:
            generated = generator.generate(
                entity.canonical_name,
                entity.entity_type or "",
                entity.identifiers,
            )
        except Exception as exc:
            logger.warning(
                "Generation failed for '%s': %s", entity.canonical_name, exc
            )
            continue

        new_aliases = []
        for alias in generated:
            norm = normalize_entity_name(alias)
            if (
                alias not in existing_aliases
                and norm not in existing_norms
                and len(entity.aliases) + len(new_aliases) < _MAX_ALIASES
            ):
                new_aliases.append(alias)
                existing_aliases.add(alias)
                existing_norms.add(norm)

        if new_aliases:
            print(f"  {entity.canonical_name} ({entity.entity_type})")
            print(f"    + {new_aliases}")
            entity.aliases.extend(new_aliases)
            updated_entities.append(entity)
            updated_count += 1

    print(f"\nUpdated: {updated_count} entities")

    if not dry_run and updated_entities:
        repo.save_batch(updated_entities)
        print("Saved to database.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill entity aliases via LLM")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without saving")
    parser.add_argument("--limit", type=int, default=None, help="Max entities to process")
    parser.add_argument("--db", default="data/news.db", help="Database path")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    backfill_aliases(
        db_path=args.db,
        dry_run=args.dry_run,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
