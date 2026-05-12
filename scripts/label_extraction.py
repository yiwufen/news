#!/usr/bin/env python3
"""Generate a pre-filled labeling template from real documents.

Samples documents from the database, runs LLM extraction, and outputs
a template JSON where annotators only need to mark ✅/❌ and add missing items.

Usage:
    # Sample 20 docs, pre-extract, output template
    uv run python scripts/label_extraction.py --sample 20 --output eval/extraction_label_template.json

    # Dry run (no API call, just sample docs)
    uv run python scripts/label_extraction.py --sample 5 --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import UTC, datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src.knowledge_base import RawDocument
from src.knowledge_extractor import KnowledgeExtractor


def sample_documents(db_path: str, n: int) -> list[dict]:
    """Sample N diverse documents from the database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get all doc_ids that have at least one knowledge unit
    rows = conn.execute("""
        SELECT DISTINCT na.doc_id, na.title, na.content, na.source_name, na.publish_time
        FROM news_articles na
        INNER JOIN knowledge_units ku
            ON json_extract(ku.payload, '$.source.doc_id') = na.doc_id
        WHERE length(na.content) > 100
        ORDER BY RANDOM()
        LIMIT ?
    """, (n * 3,)).fetchall()

    conn.close()

    # Randomly sample from the pool
    sampled = random.sample(list(rows), min(n, len(rows)))
    return [dict(r) for r in sampled]


def run_extraction(doc: dict, extractor: KnowledgeExtractor) -> dict:
    """Run extraction on a single document, return structured pre-fill."""
    raw = RawDocument(
        doc_id=doc["doc_id"],
        source_type="news",
        title=doc["title"],
        content=doc["content"],
        source_name=doc["source_name"],
        published_at=datetime.fromisoformat(doc["publish_time"]),
        ingested_at=datetime.now(UTC),
    )

    try:
        units = extractor.extract(raw)
    except Exception as exc:
        return {"error": str(exc), "units": []}

    pre_filled_units = []
    for unit in units:
        pre_filled_units.append({
            "summary": unit.summary,
            "unit_type": unit.unit_type,
            "entities": [
                {
                    "mention": e.mention,
                    "entity_type": e.entity_type,
                    "label": "",  # annotator fills: "correct" / "wrong_type" / "should_remove"
                }
                for e in unit.entities
            ],
            "relation_hints": [
                {
                    "subject_mention": rh.subject_mention,
                    "relation_type": rh.relation_type,
                    "object_mention": rh.object_mention,
                    "label": "",  # annotator fills: "correct" / "should_remove"
                }
                for rh in unit.relation_hints
                if rh.subject_mention and rh.object_mention
            ],
        })

    return {"error": None, "units": pre_filled_units}


def build_template(doc: dict, extraction_result: dict) -> dict:
    """Build a single labeling template entry."""
    return {
        "test_id": f"label_{doc['doc_id'][:12]}",
        "status": "unlabeled",  # annotator sets: "labeled" / "skipped"
        "document": {
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "content": doc["content"][:500],  # truncate for readability
            "source_name": doc["source_name"],
            "published_at": doc["publish_time"],
        },
        "pre_extracted": extraction_result.get("units", []),
        "error": extraction_result.get("error"),
        # Annotator adds missing entities/relations here
        "annotations": {
            "missing_entities": [],
            "missing_relations": [],
            "notes": "",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate pre-filled labeling template")
    parser.add_argument("--sample", type=int, default=20, help="Number of documents to sample")
    parser.add_argument("--output", type=str, default="eval/extraction_label_template.json")
    parser.add_argument("--db", type=str, default="data/news.db")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="Only sample, don't call LLM")
    args = parser.parse_args()

    random.seed(args.seed)

    print(f"Sampling {args.sample} documents from {args.db}...")
    docs = sample_documents(args.db, args.sample)
    print(f"  Sampled {len(docs)} documents")

    if not docs:
        print("No documents found.")
        return

    if args.dry_run:
        print("\nDry run — showing sampled documents:")
        for i, doc in enumerate(docs):
            print(f"  [{i+1}] {doc['doc_id']}: {doc['title'][:50]}")
        return

    extractor = KnowledgeExtractor()
    templates: list[dict] = []
    errors = 0

    for i, doc in enumerate(docs):
        pct = (i + 1) / len(docs) * 100
        print(f"[{pct:5.1f}%] Extracting {doc['doc_id']}: {doc['title'][:40]}...", end=" ", flush=True)

        result = run_extraction(doc, extractor)
        if result["error"]:
            print(f"ERROR ({result['error'][:50]})")
            errors += 1
        else:
            n_units = len(result["units"])
            n_ents = sum(len(u["entities"]) for u in result["units"])
            n_rels = sum(len(u["relation_hints"]) for u in result["units"])
            print(f"OK ({n_units} units, {n_ents} entities, {n_rels} relations)")

        templates.append(build_template(doc, result))

    output = {
        "version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "description": "Pre-filled extraction labeling template — annotator marks label fields",
        "instructions": {
            "entity_label": 'Set to "correct" (entity is right), "wrong_type" (entity exists but type wrong), or "should_remove" (not an entity)',
            "relation_label": 'Set to "correct" or "should_remove"',
            "missing_entities": 'Add entities the LLM missed: [{"mention": "X", "entity_type": "Company"}]',
            "missing_relations": 'Add relations the LLM missed: [{"subject_mention": "A", "relation_type": "投资", "object_mention": "B"}]',
            "status": 'Set to "labeled" when done, "skipped" to skip',
        },
        "templates": templates,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nTemplate saved to {args.output}")
    print(f"  Total: {len(templates)} documents")
    print(f"  Errors: {errors}")
    print(f"\nNext steps:")
    print(f"  1. Open {args.output} in a text editor")
    print(f"  2. Fill in the label fields for each entity/relation")
    print(f"  3. Run: uv run python scripts/eval_extraction.py --convert-labeled {args.output}")


if __name__ == "__main__":
    main()
