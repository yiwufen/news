from __future__ import annotations

from src.skills.payloads import (
    GUARANTEE_KEYWORDS,
    GUARANTEED_ROLE_KEYWORDS,
    GUARANTOR_ROLE_KEYWORDS,
    build_payload,
    normalize_supporting_evidence,
)
from src.skills.models import GuaranteeAnalysisPayload, SupportingEvidence


def test_guarantee_keyword_constants_keep_utf8_chinese_terms() -> None:
    assert "担保" in GUARANTEE_KEYWORDS
    assert "保证" in GUARANTEE_KEYWORDS
    assert "关联担保" in GUARANTEE_KEYWORDS
    assert "担保方" in GUARANTOR_ROLE_KEYWORDS
    assert "保证人" in GUARANTOR_ROLE_KEYWORDS
    assert "被担保方" in GUARANTEED_ROLE_KEYWORDS
    assert "债务人" in GUARANTEED_ROLE_KEYWORDS


def test_chinese_guarantee_roles_build_directed_edges() -> None:
    knowledge_units = [
        {
            "ku_id": "ku-1",
            "unit_kind": "event",
            "unit_type": "guarantee",
            "summary": "A 为 B 提供担保",
            "entities": [
                {"entity_id": "ent-a", "mention": "A 公司", "role": "担保方"},
                {"entity_id": "ent-b", "mention": "B 公司", "role": "被担保方"},
            ],
            "source": {"doc_id": "doc-1", "source_name": "test", "url": None},
            "evidence": [{"text": "A 公司为 B 公司提供担保。"}],
            "confidence": 0.9,
            "cluster_id": "clu-1",
            "conflict_status": "none",
        }
    ]
    clusters = [
        {
            "cluster_id": "clu-1",
            "cluster_type": "guarantee",
            "title": "A 为 B 提供担保",
            "summary": "A 为 B 提供担保",
            "entity_ids": ["ent-a", "ent-b"],
            "primary_entity_id": "ent-a",
            "member_ku_ids": ["ku-1"],
            "source_doc_ids": ["doc-1"],
        }
    ]
    entities = [
        {"entity_id": "ent-a", "canonical_name": "A 公司"},
        {"entity_id": "ent-b", "canonical_name": "B 公司"},
    ]
    evidence: list[SupportingEvidence] = normalize_supporting_evidence(knowledge_units)

    payload = build_payload(
        result=None,  # type: ignore[arg-type]
        skill_type="guarantee_analysis",
        knowledge_units=knowledge_units,
        event_clusters=clusters,
        entities=entities,
        target_entity="A 公司",
        sorted_clusters=clusters,
        supporting_evidence=evidence,
    )

    assert isinstance(payload, GuaranteeAnalysisPayload)
    assert payload.guarantee_edges == [
        {
            "source_id": "ent-a",
            "source_name": "A 公司",
            "target_id": "ent-b",
            "target_name": "B 公司",
            "cluster_id": "clu-1",
            "cluster_title": "A 为 B 提供担保",
            "source_doc_ids": ["doc-1"],
        }
    ]
