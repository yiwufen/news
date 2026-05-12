"""Entity Resolution quality evaluation.

Simulates entity resolution against a set of mention→expected_entity pairs,
measuring merge precision (no false merges) and merge recall (no missed merges).

Usage:
    uv run python scripts/eval_entity_resolution.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.entities import (
    Entity,
    EntityResolver,
    EntityRepository,
    normalize_entity_name,
)


# Ground truth: (mention, entity_type, expected_group)
# Mentions with the same expected_group SHOULD merge into one entity.
# Mentions with different expected_group SHOULD NOT merge.
GROUND_TRUTH: list[tuple[str, str, str]] = [
    # --- Same entity, different surface forms (should merge) ---
    ("比亚迪", "Company", "byd"),
    ("BYD", "Company", "byd"),
    ("宁德时代", "Company", "catl"),
    ("宁德时代股份有限公司", "Company", "catl"),
    ("腾讯控股", "Company", "tencent"),
    ("腾讯", "Company", "tencent"),  # type differs but should merge
    ("阿里巴巴", "Company", "alibaba"),
    ("Alibaba", "Company", "alibaba"),
    ("小米集团", "Company", "xiaomi"),
    ("小米", "Company", "xiaomi"),   # type differs but should merge
    ("华为", "Company", "huawei"),
    ("Huawei", "Company", "huawei"),
    ("台积电", "Company", "tsmc"),
    ("TSMC", "Company", "tsmc"),

    # --- Different entities, similar names (should NOT merge) ---
    ("美的集团", "Company", "midea_group"),
    ("美的置业", "Company", "midea_realestate"),
    ("恒大健康", "Company", "hengda_health"),
    ("恒大地产", "Company", "hengda_realestate"),
    ("小米金融", "Company", "xiaomi_finance"),
    ("吉利", "Company", "geely"),
    ("大吉利", "Company", "dajili"),
    ("百度", "Company", "baidu"),
    ("百度科技", "Company", "baidu_tech"),  # different from 百度
]


@dataclass
class EvalResult:
    total_pairs: int
    true_positives: int   # same group, correctly merged
    false_negatives: int  # same group, NOT merged (missed merge)
    true_negatives: int   # different group, correctly separate
    false_positives: int  # different group, incorrectly merged
    details: list[dict]

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def evaluate() -> EvalResult:
    """Run entity resolution on ground truth and measure quality."""
    repo = EntityRepository(":memory:")
    resolver = EntityResolver(repo)

    # Feed mentions one by one, tracking which entity each resolves to
    mention_to_entity: dict[str, str] = {}  # mention → entity_id
    entities_cache: dict[str, Entity] = {}

    now = datetime.now(UTC)

    for mention, entity_type, _group in GROUND_TRUTH:
        from src.knowledge_base import (
            EntityRef,
            EvidenceSpan,
            KnowledgeUnit,
            SourceRef,
            TimeRef,
        )

        unit = KnowledgeUnit(
            unit_kind="event",
            unit_type="market_analysis",
            summary="eval test",
            entities=[
                EntityRef(mention=mention, entity_type=entity_type)
            ],
            source=SourceRef(doc_id="eval_doc", source_name="eval"),
            evidence=[EvidenceSpan(text="eval evidence")],
            time=TimeRef(published_at=now, extracted_at=now),
        )
        resolver.resolve_units_with_cache([unit], entities_cache, persist=False)
        mention_to_entity[mention] = unit.entities[0].entity_id

    # Evaluate pairwise
    details: list[dict] = []
    tp = fp = tn = fn = 0

    entries = list(mention_to_entity.items())
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            m_a, eid_a = entries[i]
            m_b, eid_b = entries[j]
            _, _, group_a = GROUND_TRUTH[i]
            _, _, group_b = GROUND_TRUTH[j]

            same_group = group_a == group_b
            same_entity = eid_a == eid_b

            if same_group and same_entity:
                tp += 1
                status = "TP"
            elif same_group and not same_entity:
                fn += 1
                status = "FN"
            elif not same_group and same_entity:
                fp += 1
                status = "FP"
            else:
                tn += 1
                status = "TN"

            if status in ("FN", "FP"):
                details.append({
                    "mention_a": m_a,
                    "mention_b": m_b,
                    "expected_same": same_group,
                    "actual_same": same_entity,
                    "status": status,
                    "group_a": group_a,
                    "group_b": group_b,
                })

    total = tp + fp + tn + fn
    return EvalResult(
        total_pairs=total,
        true_positives=tp,
        false_negatives=fn,
        true_negatives=tn,
        false_positives=fp,
        details=details,
    )


def main() -> None:
    result = evaluate()

    print("=" * 60)
    print("  Entity Resolution Quality Report")
    print("=" * 60)
    print()
    print(f"  Total pairs evaluated:  {result.total_pairs}")
    print(f"  True Positives (merged correctly):    {result.true_positives}")
    print(f"  False Negatives (missed merges):      {result.false_negatives}")
    print(f"  True Negatives (kept separate):       {result.true_negatives}")
    print(f"  False Positives (wrong merges):       {result.false_positives}")
    print()
    print(f"  Precision:  {result.precision:.3f}  (no false merges)")
    print(f"  Recall:     {result.recall:.3f}  (no missed merges)")
    print(f"  F1:         {result.f1:.3f}")
    print()

    if result.details:
        print("  Errors:")
        for d in result.details:
            marker = "MERGED" if d["status"] == "FP" else "SPLIT"
            print(
                f"    [{d['status']}] {d['mention_a']!r} vs {d['mention_b']!r} "
                f"— expected_same={d['expected_same']}, actual={marker} "
                f"(groups: {d['group_a']}, {d['group_b']})"
            )
    else:
        print("  No errors — all pairs classified correctly.")
    print()

    # Save results
    out_dir = Path("eval")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "entity_resolution_eval.json"
    out_path.write_text(
        json.dumps(
            {
                "precision": result.precision,
                "recall": result.recall,
                "f1": result.f1,
                "true_positives": result.true_positives,
                "false_negatives": result.false_negatives,
                "true_negatives": result.true_negatives,
                "false_positives": result.false_positives,
                "total_pairs": result.total_pairs,
                "errors": result.details,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  Results saved to {out_path}")


if __name__ == "__main__":
    main()
