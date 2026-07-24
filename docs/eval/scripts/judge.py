"""LLM-as-judge relevance labeling for retrieval evaluation.

For each (query, retrieved KU) pair, an advanced LLM assigns a 3-level
relevance grade:

    2 = relevant   — KU directly answers the query (entity/event/topic match)
    1 = partial    — KU mentions the entity but is off-topic, OR on-topic but
                     wrong entity
    0 = irrelevant — unrelated to the query

Grades are cached on disk (``golden_labels/<version>_labels.json``) keyed by
``(query_id, ku_id, judge_model)`` so reruns are incremental and resumable.

The judge model is configured via the ``EVAL_JUDGE_MODEL`` env var (default
``glm-5.1``), decoupled from the online/offline pipeline models.

Usage::

    from docs.eval.scripts.judge import LabelStore, label_query_hits
    store = LabelStore.load("v1")
    labels = label_query_hits(query_meta, ku_payloads, store, model="glm-5.1")
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "glm-5.1")
EVAL_DIR = Path(__file__).resolve().parents[1]
LABELS_DIR = EVAL_DIR / "golden_labels"

# Batch size: how many KUs to judge in one LLM call. Keeps the prompt small
# and lets the model emit a compact JSON list. Larger batches save API calls
# but risk the model losing focus on later items.
JUDGE_BATCH_SIZE = 10

GRADE_RELEVANT = 2
GRADE_PARTIAL = 1
GRADE_IRRELEVANT = 0
VALID_GRADES = (0, 1, 2)


SYSTEM_PROMPT = """\
你是一名严谨的金融资讯知识库相关性评估员。

你的任务是判断每条「知识单元」(KnowledgeUnit) 与一个查询的相关程度，给出三级评分：

  2 = relevant（相关）：知识单元直接回答查询，实体/事件/主题强相关。
  1 = partial（部分相关）：知识单元提及查询中的实体但主题偏题；或主题相关但实体不符。
  0 = irrelevant（不相关）：与查询完全无关。

评分依据（重要）：
- 仅根据知识单元自身内容判断，不要臆测外部信息。
- 实体精确性：查询的是「小米」，知识单元讲「美的」即使都是家电行业也算 partial 或 irrelevant。
- 主题匹配：查询意图（intent）决定相关性方向。RISK 意图要求内容涉及风险/违约/诉讼等；TIMELINE 意图要求有时序事件；COMPARATIVE 要求同时涉及对比双方。
- 过滤约束（硬性）：若查询携带时间范围(time_range)或事件类型(event_types)过滤，知识单元必须完全满足这些约束才可判为相关（grade≥1）。不满足任一过滤约束一律判 irrelevant(0)，即使实体/主题匹配。时间以知识单元的事件时间(event_time)为准；事件类型以知识单元的类型(unit_type)为准，落在过滤列表内即视为满足。
- 不要因为知识单元「看起来很重要」就给高分，必须严格对照查询。

输出格式：严格 JSON，不要任何额外文字。
```json
{"labels": [{"index": 0, "grade": 2, "reason": "一句话理由"}, ...]}
```
其中 index 是输入列表中该知识单元的序号（从 0 开始）。"""


@dataclass
class Label:
    query_id: str
    ku_id: str
    judge_model: str
    grade: int
    reason: str = ""


@dataclass
class LabelStore:
    """On-disk cache of judge labels, keyed by (query_id, ku_id, model)."""

    version: str
    labels: dict[tuple[str, str, str], Label] = field(default_factory=dict)

    @classmethod
    def load(cls, version: str) -> "LabelStore":
        path = LABELS_DIR / f"{version}_labels.json"
        store = cls(version=version)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for item in raw.get("labels", []):
                key = (item["query_id"], item["ku_id"], item["judge_model"])
                store.labels[key] = Label(
                    query_id=item["query_id"],
                    ku_id=item["ku_id"],
                    judge_model=item["judge_model"],
                    grade=int(item["grade"]),
                    reason=item.get("reason", ""),
                )
        return store

    def save(self) -> Path:
        LABELS_DIR.mkdir(parents=True, exist_ok=True)
        path = LABELS_DIR / f"{self.version}_labels.json"
        payload = {
            "version": self.version,
            "judge_model": DEFAULT_JUDGE_MODEL,
            "label_count": len(self.labels),
            "labels": [
                {
                    "query_id": lb.query_id,
                    "ku_id": lb.ku_id,
                    "judge_model": lb.judge_model,
                    "grade": lb.grade,
                    "reason": lb.reason,
                }
                for lb in self.labels.values()
            ],
        }
        # write atomically to avoid corruption on interrupt
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return path

    def get(self, query_id: str, ku_id: str, model: str) -> Label | None:
        return self.labels.get((query_id, ku_id, model))

    def upsert(self, label: Label) -> None:
        self.labels[(label.query_id, label.ku_id, label.judge_model)] = label


def _build_client() -> Any:
    """Build an Anthropic-compatible client for the judge model.

    Reuses the pipeline's LLM client factory (``src.llm.client``), which clears
    the conflicting ``ANTHROPIC_AUTH_TOKEN`` / ``ANTHROPIC_BASE_URL`` env vars
    that the SDK reads on init. The judge model is selected separately via
    ``EVAL_JUDGE_MODEL`` at call time — the client itself is model-agnostic.
    """
    from src.llm.client import create_offline_llm_client

    client, _ = create_offline_llm_client()
    return client


def _format_query_context(query: dict) -> str:
    """Render the query in a form the judge can understand."""
    parts = [f"查询文本: {query['query_text']}", f"意图(intent): {query['intent']}"]
    if query.get("entities"):
        parts.append(f"关注实体: {', '.join(query['entities'])}")
    if query.get("target_entity"):
        parts.append(f"目标实体: {query['target_entity']}")
    if query.get("time_range"):
        parts.append(f"时间范围: {query['time_range'][0]} ~ {query['time_range'][1]}")
    if query.get("event_types"):
        parts.append(f"事件类型过滤: {', '.join(query['event_types'])}")
    return "\n".join(parts)


def _format_ku(index: int, ku: dict) -> str:
    """Render one KU compactly for the judge prompt."""
    entities = ku.get("entities") or []
    mentions = ", ".join(
        e.get("mention", "") for e in entities if e.get("mention")
    ) or "（无）"
    evidence = ku.get("evidence") or []
    first_ev = evidence[0].get("text", "")[:200] if evidence else "（无）"
    time_ref = ku.get("time") or {}
    event_time = (time_ref.get("event_time") or "")[:10]
    published = (time_ref.get("published_at") or "")[:10]
    time_str = event_time or published or "（无）"

    return (
        f"[{index}] ku_id: {ku.get('ku_id', '?')}\n"
        f"    类型: {ku.get('unit_type', '?')} | 时间: {time_str}\n"
        f"    实体: {mentions}\n"
        f"    摘要: {ku.get('summary', '')}\n"
        f"    证据: {first_ev}"
    )


def _call_judge(
    client: Any,
    model: str,
    query: dict,
    batch: list[dict],
    max_retries: int = 2,
) -> list[dict]:
    """Call the judge LLM for one batch of KUs. Returns parsed label list."""
    user_prompt = (
        f"=== 查询 ===\n{_format_query_context(query)}\n\n"
        f"=== 知识单元列表（共 {len(batch)} 条）===\n"
        + "\n".join(_format_ku(i, ku) for i, ku in enumerate(batch))
        + "\n\n=== 任务 ===\n"
        f"对上述 {len(batch)} 条知识单元分别评分。输出 JSON："
        '{"labels": [{"index": 0, "grade": 0|1|2, "reason": "..."}, ...]}'
    )

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(
                getattr(b, "text", "") for b in getattr(resp, "content", []) or []
            )
            return _parse_judge_response(text, expected=len(batch))
        except Exception as err:  # noqa: BLE001 — network/API errors, retry
            last_err = err
            wait = 2 ** attempt
            logger.warning(
                "judge call failed (attempt %d/%d): %s — retrying in %ds",
                attempt + 1, max_retries + 1, err, wait,
            )
            time.sleep(wait)
    raise RuntimeError(f"judge call failed after {max_retries + 1} attempts: {last_err}")


def _parse_judge_response(text: str, expected: int) -> list[dict]:
    """Parse the JSON labels list from model output, robustly."""
    import re

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        logger.error("judge returned no JSON; raw: %s", text[:300])
        return []
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        logger.error("judge returned malformed JSON: %s", match.group()[:300])
        return []

    labels = data.get("labels", [])
    result: list[dict] = []
    for item in labels:
        grade = item.get("grade")
        try:
            grade = int(grade)
        except (TypeError, ValueError):
            continue
        if grade not in VALID_GRADES:
            continue
        result.append(
            {
                "index": int(item.get("index", -1)),
                "grade": grade,
                "reason": str(item.get("reason", ""))[:200],
            }
        )
    return result


def label_query_hits(
    query: dict,
    ku_payloads: list[dict],
    store: LabelStore,
    model: str = DEFAULT_JUDGE_MODEL,
    client: Any = None,
) -> dict[str, int]:
    """Judge all KUs for one query, using cache and batching.

    Returns a mapping ``ku_id -> grade`` for all judged KUs (including cached).
    Persists new labels into ``store`` (caller is responsible for ``save()``).
    """
    own_client = client is None
    if own_client:
        client = _build_client()

    query_id = query["id"]
    results: dict[str, int] = {}

    # Partition into cached vs needing judgment
    to_judge: list[dict] = []
    for ku in ku_payloads:
        cached = store.get(query_id, ku["ku_id"], model)
        if cached is not None:
            results[ku["ku_id"]] = cached.grade
        else:
            to_judge.append(ku)

    if to_judge:
        logger.info(
            "[%s] judging %d KUs (%d cached) with model=%s",
            query_id, len(to_judge), len(results), model,
        )

    # Batch the uncached KUs
    for start in range(0, len(to_judge), JUDGE_BATCH_SIZE):
        batch = to_judge[start : start + JUDGE_BATCH_SIZE]
        parsed = _call_judge(client, model, query, batch)

        # Map parsed labels back to ku_id by index
        indexed: dict[int, dict] = {p["index"]: p for p in parsed}
        for i, ku in enumerate(batch):
            entry = indexed.get(i)
            if entry is None:
                # Model skipped this index — default to irrelevant but flag it
                grade = GRADE_IRRELEVANT
                reason = "JUDGE_NO_RESPONSE"
                logger.warning(
                    "[%s] judge did not label ku_id=%s (index %d)",
                    query_id, ku["ku_id"], i,
                )
            else:
                grade = entry["grade"]
                reason = entry["reason"]
            results[ku["ku_id"]] = grade
            store.upsert(
                Label(
                    query_id=query_id,
                    ku_id=ku["ku_id"],
                    judge_model=model,
                    grade=grade,
                    reason=reason,
                )
            )

        # Checkpoint after each batch so progress survives interruption
        store.save()

    if own_client:
        client.close()

    return results


if __name__ == "__main__":
    # Smoke test: judge a single query with a couple of real KUs.
    import argparse
    import sqlite3

    parser = argparse.ArgumentParser(description="LLM judge smoke test")
    parser.add_argument("--query-id", default="Q01", help="Query ID from queries-v1.json")
    parser.add_argument("--limit", type=int, default=3, help="KUs to judge")
    parser.add_argument("--db", default="data/news.db")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    queries = json.loads((EVAL_DIR / "queries-v1.json").read_text(encoding="utf-8"))
    query = next(q for q in queries["queries"] if q["id"] == args.query_id)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT ku_id, payload FROM knowledge_units LIMIT ?", (args.limit,)
    ).fetchall()
    conn.close()
    ku_payloads = [json.loads(r["payload"]) for r in rows]

    store = LabelStore.load(queries["version"])
    grades = label_query_hits(query, ku_payloads, store)
    store.save()

    print(f"\nJudged {len(grades)} KUs for {args.query_id} ({query['query_text']}):")
    for ku_id, grade in grades.items():
        print(f"  {ku_id} -> grade {grade}")
