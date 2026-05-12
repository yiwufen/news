#!/usr/bin/env python3
"""Entity extraction quality evaluation script.

Usage:
    # Full eval (requires API key)
    uv run python scripts/eval_extraction.py

    # Validate dataset format only
    uv run python scripts/eval_extraction.py --validate-only

    # Custom dataset
    uv run python scripts/eval_extraction.py --input path/to/dataset.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from src.knowledge_base import RawDocument
from src.knowledge_extractor import KnowledgeExtractor
from src.entities import normalize_entity_name, is_valid_entity_mention

# Relation type synonyms — LLM may use any of these interchangeably
_RELATION_SYNONYMS: dict[str, set[str]] = {
    "并购": {"并购", "收购", "合并", "兼并"},
    "诉讼": {"诉讼", "起诉", "控告", "提告"},
    "高管任职": {"高管任职", "任职", "任命", "就职"},
    "控股": {"控股", "控制", "全资控股"},
    "制裁": {"制裁", "禁运"},
    "谴责": {"谴责", "强烈谴责"},
    "威胁": {"威胁", "恐吓"},
    "反对": {"反对", "抗议"},
    "签署": {"签署", "签订", "签约", "供应"},
}

# Bidirectional relation types — (A, rel, B) is equivalent to (B, rel, A)
_BIDIRECTIONAL_RELATIONS: frozenset[str] = frozenset({"合作", "签署", "竞争"})

# Build reverse lookup: synonym → canonical type
_RELATION_CANONICAL: dict[str, str] = {}
for canonical, synonyms in _RELATION_SYNONYMS.items():
    for s in synonyms:
        _RELATION_CANONICAL[s] = canonical


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EntityExpectation:
    mention: str
    entity_type: str


@dataclass
class RelationExpectation:
    subject_mention: str
    relation_type: str
    object_mention: str


@dataclass
class TestCase:
    test_id: str
    category: str
    description: str
    document: dict
    expected_entities: list[EntityExpectation]
    forbidden_entities: list[str]
    expected_relations: list[RelationExpectation]


@dataclass
class CaseResult:
    test_id: str
    category: str
    description: str
    extracted_entity_mentions: list[str]
    extracted_relations: list[tuple[str, str, str]]  # (subj, rel, obj)
    entity_hits: list[str] = field(default_factory=list)
    entity_misses: list[str] = field(default_factory=list)
    entity_fps: list[str] = field(default_factory=list)
    relation_hits: list[tuple[str, str, str]] = field(default_factory=list)
    relation_misses: list[tuple[str, str, str]] = field(default_factory=list)
    relation_fps: list[tuple[str, str, str]] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Loading & validation
# ---------------------------------------------------------------------------

def load_dataset(path: Path) -> list[TestCase]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    cases: list[TestCase] = []
    for item in data["test_cases"]:
        expected = item["expected"]
        cases.append(TestCase(
            test_id=item["test_id"],
            category=item["category"],
            description=item["description"],
            document=item["document"],
            expected_entities=[
                EntityExpectation(**e) for e in expected.get("entities", [])
            ],
            forbidden_entities=expected.get("forbidden_entities", []),
            expected_relations=[
                RelationExpectation(**r) for r in expected.get("relations", [])
            ],
        ))
    return cases


def validate_dataset(path: Path) -> bool:
    try:
        cases = load_dataset(path)
        categories: dict[str, int] = defaultdict(int)
        total_entities = 0
        total_forbidden = 0
        total_relations = 0

        for case in cases:
            categories[case.category] += 1
            total_entities += len(case.expected_entities)
            total_forbidden += len(case.forbidden_entities)
            total_relations += len(case.expected_relations)

        print(f"Dataset: {path}")
        print(f"  Total cases:    {len(cases)}")
        print(f"  Expected entities:  {total_entities}")
        print(f"  Forbidden entities: {total_forbidden}")
        print(f"  Expected relations: {total_relations}")
        print(f"  Categories:")
        for cat, count in sorted(categories.items()):
            print(f"    {cat}: {count}")
        print("  Validation: OK")
        return True
    except Exception as exc:
        print(f"  Validation FAILED: {exc}")
        return False


# ---------------------------------------------------------------------------
# Extraction & scoring
# ---------------------------------------------------------------------------

def run_extraction(
    case: TestCase,
    extractor: KnowledgeExtractor,
    apply_filter: bool = False,
) -> CaseResult:
    doc = RawDocument(
        doc_id=case.document["doc_id"],
        source_type="news",
        title=case.document["title"],
        content=case.document["content"],
        source_name=case.document["source_name"],
        published_at=datetime.fromisoformat(case.document["published_at"]),
        ingested_at=datetime.now(UTC),
    )

    result = CaseResult(
        test_id=case.test_id,
        category=case.category,
        description=case.description,
        extracted_entity_mentions=[],
        extracted_relations=[],
    )

    try:
        units = extractor.extract(doc)
    except Exception as exc:
        result.error = str(exc)
        return result

    for unit in units:
        for e in unit.entities:
            if apply_filter and not is_valid_entity_mention(e.mention):
                continue
            if e.mention not in result.extracted_entity_mentions:
                result.extracted_entity_mentions.append(e.mention)
        for rh in unit.relation_hints:
            if rh.subject_mention and rh.object_mention:
                triple = (rh.subject_mention, rh.relation_type, rh.object_mention)
                if triple not in result.extracted_relations:
                    result.extracted_relations.append(triple)

    score_entity(case, result)
    score_relation(case, result)
    return result


def _normalize_mention(mention: str) -> str:
    return mention.strip().lower()


def _mention_matches(extracted: str, expected: str) -> bool:
    """Check if an extracted mention matches an expected mention.

    Uses both exact match and corporate-suffix-normalized match.
    E.g. "宁德时代新能源科技股份有限公司" matches "宁德时代".
    """
    if _normalize_mention(extracted) == _normalize_mention(expected):
        return True
    ext_norm = normalize_entity_name(extracted)
    exp_norm = normalize_entity_name(expected)
    if ext_norm and exp_norm and ext_norm == exp_norm:
        return True
    # Substring containment: "阿里巴巴集团控股有限公司" contains "阿里巴巴"
    ext_low = _normalize_mention(extracted)
    exp_low = _normalize_mention(expected)
    if exp_low in ext_low or ext_low in exp_low:
        return True
    return False


def _canonical_relation(relation_type: str) -> str:
    """Normalize relation type via synonym mapping."""
    rt = relation_type.strip()
    return _RELATION_CANONICAL.get(rt, rt)


def score_entity(case: TestCase, result: CaseResult) -> None:
    for expected in case.expected_entities:
        hit = any(
            _mention_matches(ext, expected.mention)
            for ext in result.extracted_entity_mentions
        )
        if hit:
            result.entity_hits.append(expected.mention)
        else:
            result.entity_misses.append(expected.mention)

    for forbidden in case.forbidden_entities:
        hit = any(
            _mention_matches(ext, forbidden)
            for ext in result.extracted_entity_mentions
        )
        if hit:
            result.entity_fps.append(forbidden)


def _relation_matches(
    ext_s: str, ext_r_canonical: str, ext_o: str,
    exp_s: str, exp_r_canonical: str, exp_o: str,
) -> bool:
    """Check if an extracted relation matches an expected relation.

    Supports bidirectional matching for symmetric relations like 合作, 签署.
    """
    if ext_r_canonical != exp_r_canonical:
        return False
    s_match = _mention_matches(ext_s, exp_s)
    o_match = _mention_matches(ext_o, exp_o)
    if s_match and o_match:
        return True
    # Bidirectional: (A, rel, B) matches expected (B, rel, A)
    if exp_r_canonical in _BIDIRECTIONAL_RELATIONS:
        if _mention_matches(ext_s, exp_o) and _mention_matches(ext_o, exp_s):
            return True
    return False


def score_relation(case: TestCase, result: CaseResult) -> None:
    # Build normalized extracted relation set
    extracted_norm = []
    for s, r, o in result.extracted_relations:
        extracted_norm.append((s, _canonical_relation(r), o))

    for expected in case.expected_relations:
        exp_canonical = _canonical_relation(expected.relation_type)
        found = False
        for es, er_canonical, eo in extracted_norm:
            if _relation_matches(es, er_canonical, eo, expected.subject_mention, exp_canonical, expected.object_mention):
                found = True
                break
        if found:
            result.relation_hits.append(
                (expected.subject_mention, expected.relation_type, expected.object_mention)
            )
        else:
            result.relation_misses.append(
                (expected.subject_mention, expected.relation_type, expected.object_mention)
            )

    # FP: extracted relations not matching any expected
    expected_canonical = [
        (
            expected.subject_mention,
            _canonical_relation(expected.relation_type),
            expected.object_mention,
        )
        for expected in case.expected_relations
    ]
    for s, r, o in result.extracted_relations:
        r_canonical = _canonical_relation(r)
        is_expected = any(
            _mention_matches(s, e_s)
            and r_canonical == e_r
            and _mention_matches(o, e_o)
            for e_s, e_r, e_o in expected_canonical
        )
        if not is_expected:
            result.relation_fps.append((s, r, o))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(results: list[CaseResult]) -> None:
    total_entities_expected = 0
    total_entities_hit = 0
    total_entities_extracted = 0
    total_fps = 0
    total_forbidden = 0
    total_relations_expected = 0
    total_relations_hit = 0
    total_relations_extracted = 0
    errors: list[CaseResult] = []
    failures: list[str] = []

    category_stats: dict[str, dict] = defaultdict(lambda: {
        "ent_expected": 0, "ent_hit": 0, "ent_extracted": 0,
        "fps": 0, "forbidden": 0,
        "rel_expected": 0, "rel_hit": 0, "rel_extracted": 0,
    })

    for r in results:
        cs = category_stats[r.category]

        ent_hit = len(r.entity_hits)
        ent_miss = len(r.entity_misses)
        ent_extracted = len(r.extracted_entity_mentions)
        fps = len(r.entity_fps)
        forbidden = len([1])

        total_entities_expected += ent_hit + ent_miss
        total_entities_hit += ent_hit
        total_entities_extracted += ent_extracted
        total_fps += fps
        total_forbidden += len(r.entity_fps)

        cs["ent_expected"] += ent_hit + ent_miss
        cs["ent_hit"] += ent_hit
        cs["ent_extracted"] += ent_extracted
        cs["fps"] += fps

        rel_hit = len(r.relation_hits)
        rel_miss = len(r.relation_misses)
        rel_extracted = len(r.extracted_relations)

        total_relations_expected += rel_hit + rel_miss
        total_relations_hit += rel_hit
        total_relations_extracted += rel_extracted

        cs["rel_expected"] += rel_hit + rel_miss
        cs["rel_hit"] += rel_hit
        cs["rel_extracted"] += rel_extracted

        if r.error:
            errors.append(r)

        if r.entity_misses:
            for m in r.entity_misses:
                failures.append(f"[{r.test_id}] Expected entity \"{m}\" not found")
        if r.entity_fps:
            for fp in r.entity_fps:
                failures.append(f"[{r.test_id}] Forbidden entity \"{fp}\" was extracted")
        if r.relation_misses:
            for s, rel, o in r.relation_misses:
                failures.append(f"[{r.test_id}] Expected relation \"{s} --[{rel}]--> {o}\" not found")
        if r.relation_fps:
            for s, rel, o in r.relation_fps:
                failures.append(f"[{r.test_id}] Unexpected relation \"{s} --[{rel}]--> {o}\"")

    # Print report
    print()
    print("=" * 60)
    print("  Entity Extraction Eval Report")
    print("=" * 60)
    print(f"Total cases: {len(results)}")
    if errors:
        print(f"Errors:      {len(errors)}")
    print()

    # Entity metrics
    ent_precision = total_entities_hit / total_entities_extracted if total_entities_extracted else 0
    ent_recall = total_entities_hit / total_entities_expected if total_entities_expected else 0
    fp_rate = total_fps / total_forbidden if total_forbidden else 0

    print("--- Entity Metrics ---")
    print(f"Precision: {ent_precision:.1%}  ({total_entities_hit}/{total_entities_extracted})")
    print(f"Recall:    {ent_recall:.1%}  ({total_entities_hit}/{total_entities_expected})")
    print(f"FP Rate:   {fp_rate:.1%}  ({total_fps} forbidden entities extracted)")
    print()

    # Relation metrics
    rel_precision = total_relations_hit / total_relations_extracted if total_relations_extracted else 0
    rel_recall = total_relations_hit / total_relations_expected if total_relations_expected else 0

    print("--- Relation Metrics ---")
    print(f"Precision: {rel_precision:.1%}  ({total_relations_hit}/{total_relations_extracted})")
    print(f"Recall:    {rel_recall:.1%}  ({total_relations_hit}/{total_relations_expected})")
    print()

    # Per-category breakdown
    print("--- Per-Category Breakdown ---")
    for cat in sorted(category_stats):
        cs = category_stats[cat]
        p = cs["ent_hit"] / cs["ent_extracted"] if cs["ent_extracted"] else 0
        r = cs["ent_hit"] / cs["ent_expected"] if cs["ent_expected"] else 0
        fp = cs["fps"]
        rp = cs["rel_hit"] / cs["rel_extracted"] if cs["rel_extracted"] else 0
        rr = cs["rel_hit"] / cs["rel_expected"] if cs["rel_expected"] else 0
        line = f"  {cat:25s}  Entity P={p:.0%} R={r:.0%} FP={fp}"
        if cs["rel_expected"] or cs["rel_extracted"]:
            line += f"  Rel P={rp:.0%} R={rr:.0%}"
        print(line)
    print()

    # Errors
    if errors:
        print("--- Errors ---")
        for r in errors:
            print(f"  [{r.test_id}] {r.error}")
        print()

    # Failures
    if failures:
        print("--- Failed Cases ---")
        for f in failures:
            print(f"  {f}")
        print()

    print("=" * 60)


# ---------------------------------------------------------------------------
# Convert labeled template to eval format
# ---------------------------------------------------------------------------

def convert_labeled(labeled_path: Path, output_path: Path) -> None:
    """Convert a labeled template from label_extraction.py to eval dataset format."""
    with open(labeled_path, encoding="utf-8") as f:
        data = json.load(f)

    test_cases: list[dict] = []
    skipped = 0

    for tmpl in data.get("templates", []):
        if tmpl.get("status") != "labeled":
            skipped += 1
            continue

        expected_entities: list[dict] = []
        forbidden_entities: list[str] = []
        expected_relations: list[dict] = []

        # Process pre-extracted units
        for unit in tmpl.get("pre_extracted", []):
            for ent in unit.get("entities", []):
                label = ent.get("label", "")
                if label == "correct":
                    expected_entities.append({
                        "mention": ent["mention"],
                        "entity_type": ent["entity_type"],
                    })
                elif label == "wrong_type":
                    # Keep entity but the type was wrong — still counts as expected
                    expected_entities.append({
                        "mention": ent["mention"],
                        "entity_type": ent["entity_type"],
                    })
                elif label == "should_remove":
                    forbidden_entities.append(ent["mention"])

            for rel in unit.get("relation_hints", []):
                label = rel.get("label", "")
                if label == "correct":
                    expected_relations.append({
                        "subject_mention": rel["subject_mention"],
                        "relation_type": rel["relation_type"],
                        "object_mention": rel["object_mention"],
                    })

        # Add annotator's missing items
        annotations = tmpl.get("annotations", {})
        for ent in annotations.get("missing_entities", []):
            expected_entities.append(ent)
        for rel in annotations.get("missing_relations", []):
            expected_relations.append(rel)

        test_cases.append({
            "test_id": tmpl["test_id"],
            "category": "real_labeled",
            "description": tmpl["document"]["title"][:60],
            "document": tmpl["document"],
            "expected": {
                "entities": expected_entities,
                "forbidden_entities": forbidden_entities,
                "relations": expected_relations,
            },
        })

    output = {
        "version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "description": "Converted from labeled template — real document extraction eval",
        "test_cases": test_cases,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Converted {len(test_cases)} labeled cases to {output_path}")
    if skipped:
        print(f"  Skipped {skipped} unlabeled/skipped cases")
    print(f"\nRun evaluation:")
    print(f"  uv run python scripts/eval_extraction.py --input {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Entity extraction quality eval")
    parser.add_argument(
        "--input", type=Path, default=Path("eval/extraction_eval.json"),
        help="Path to eval dataset JSON",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Only validate the dataset format, do not run extraction",
    )
    parser.add_argument(
        "--convert-labeled", type=Path, default=None,
        help="Convert a labeled template (from label_extraction.py) to eval format",
    )
    parser.add_argument(
        "--with-filter", action="store_true",
        help="Apply Python post-filter (is_valid_entity_mention) after LLM extraction",
    )
    args = parser.parse_args()

    if args.convert_labeled:
        convert_labeled(args.convert_labeled, args.input)
        return
        ok = validate_dataset(args.input)
        sys.exit(0 if ok else 1)

    if not args.input.exists():
        print(f"Dataset not found: {args.input}")
        sys.exit(1)

    cases = load_dataset(args.input)
    validate_dataset(args.input)
    if args.with_filter:
        print("  Post-filter: ENABLED (simulating pipeline)")
    print()

    extractor = KnowledgeExtractor()
    results: list[CaseResult] = []

    for i, case in enumerate(cases):
        pct = (i + 1) / len(cases) * 100
        print(f"[{pct:5.1f}%] {case.test_id}: {case.description}...", end=" ", flush=True)
        result = run_extraction(case, extractor, apply_filter=args.with_filter)
        if result.error:
            print(f"ERROR ({result.error[:60]})")
        else:
            print(
                f"entities={len(result.extracted_entity_mentions)} "
                f"hits={len(result.entity_hits)} "
                f"misses={len(result.entity_misses)} "
                f"fps={len(result.entity_fps)} "
                f"rels={len(result.extracted_relations)}"
            )
        results.append(result)

    print_report(results)


if __name__ == "__main__":
    main()
