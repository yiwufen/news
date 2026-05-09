"""
黄金数据集标注工具：LLM 预标注 + 人工校验 CLI。

用法:
    uv run python scripts/eval_label.py --input eval/golden_dataset_v1.json --output eval/golden_dataset_v1_labeled.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from anthropic.types import Message, ToolUseBlock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm import create_offline_llm_client, get_offline_max_tokens

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LABEL_TOOL_SCHEMA: dict[str, Any] = {
    "name": "label_retrieval_result",
    "description": "对检索结果的相关性进行评分",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "integer",
                "description": "相关性评分: 0=完全无关, 1=部分相关, 2=相关但排序不佳, 3=精准相关",
            },
            "reason": {
                "type": "string",
                "description": "评分理由（一句话）",
            },
        },
        "required": ["score", "reason"],
    },
}

LLM_LABEL_SYSTEM_PROMPT = """你是金融检索质量评估专家。你需要评估检索结果对查询的相关性。

# 评分标准
- 0: 完全无关。检索结果与查询意图无关。
- 1: 部分相关。有一些相关结果，但噪声占主导。
- 2: 相关但排序不佳。相关结果存在但排名靠后或缺少重要结果。
- 3: 精准相关。前几个结果准确且覆盖了查询意图。

# 评估维度
1. Top-5 结果中有多少与查询实体/事件相关
2. Ground truth KU 是否在结果中、排名是否靠前
3. 是否有明显不相关的噪声结果
"""


def _build_label_prompt(
    query_text: str,
    query_type: str,
    ground_truth_summary: str,
    top_results: list[dict[str, Any]],
    gt_rank: int | None,
) -> str:
    top_descriptions = []
    for i, res in enumerate(top_results[:10], start=1):
        summary = res.get("summary", "")[:80]
        gt_marker = " << GROUND TRUTH" if res.get("is_ground_truth") else ""
        top_descriptions.append(f"  {i}. [score={res.get('score', 0):.1f}] {summary}{gt_marker}")

    gt_status = f"排名第 {gt_rank}" if gt_rank else "未找到"

    return f"""请评估以下检索结果的质量。

## 查询
- 查询文本: {query_text}
- 查询类型: {query_type}

## Ground Truth KU
- 摘要: {ground_truth_summary}
- 在检索结果中的位置: {gt_status}

## Top 检索结果
{chr(10).join(top_descriptions)}

请给出 0-3 的相关性评分。"""


def llm_label_query(
    query_data: dict[str, Any],
    ground_truth_ku: dict[str, Any],
    client: Any,
    model: str,
) -> tuple[int, str] | None:
    """用 LLM 对单条查询的检索结果打分。"""
    top_results = []
    for ku_id in query_data["retrieval"]["top_ku_ids"][:10]:
        score = query_data["retrieval"]["scores"].get(ku_id, 0.0)
        is_gt = ku_id == ground_truth_ku["ku_id"]
        top_results.append({
            "ku_id": ku_id,
            "summary": ground_truth_ku["summary"] if is_gt else ku_id,
            "score": score,
            "is_ground_truth": is_gt,
        })

    # 如果结果中不是 ground truth 的 KU，我们没有它们的摘要
    # 用 ku_id 占位，LLM 仍可根据 ground truth 位置和排名评分
    prompt = _build_label_prompt(
        query_text=query_data["query_text"],
        query_type=query_data["query_type"],
        ground_truth_summary=ground_truth_ku["summary"],
        top_results=top_results,
        gt_rank=query_data["retrieval"]["ground_truth_rank"],
    )

    try:
        response: Message = client.messages.create(
            model=model,
            max_tokens=256,
            system=LLM_LABEL_SYSTEM_PROMPT,
            tools=[LABEL_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "label_retrieval_result"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == "label_retrieval_result":
                payload = block.input
                if isinstance(payload, str):
                    payload = json.loads(payload)
                score = int(payload.get("score", 0))  # type: ignore[arg-type]
                reason = str(payload.get("reason", ""))
                return (max(0, min(3, score)), reason)
    except Exception as exc:
        logger.warning("LLM 标注失败: %s", exc)
    return None


def load_ku_summaries(db_path: str) -> dict[str, str]:
    """从数据库加载所有 KU 的摘要，用于标注展示。"""
    from src.knowledge_base import KnowledgeUnitRepository
    repo = KnowledgeUnitRepository(db_path)
    return {ku.ku_id: ku.summary for ku in repo.get_all()}


def human_label_cli(
    item: dict[str, Any],
    query_idx: int,
    query: dict[str, Any],
    ku_summaries: dict[str, str],
) -> int | None:
    """交互式人工标注 CLI。"""
    gt_ku = item["ground_truth_ku"]

    print(f"\n{'=' * 60}")
    print(f"  Item: {item['item_id']} | Query {query_idx + 1}/{len(item['queries'])}")
    print(f"{'=' * 60}")
    print(f"\n  Ground Truth KU: {gt_ku['ku_id']}")
    print(f"  类型: {gt_ku['unit_kind']} / {gt_ku['unit_type']}")
    print(f"  摘要: {gt_ku['summary'][:100]}...")
    print(f"  实体: {', '.join(gt_ku['entity_mentions'][:5])}")
    print(f"  时间: {gt_ku.get('event_time') or gt_ku.get('published_at', '?')}")

    print(f"\n  查询: \"{query['query_text']}\"")
    print(f"  类型: {query['query_type']} | 难度: {query['difficulty']}")

    gt_rank = query["retrieval"]["ground_truth_rank"]
    gt_found = query["retrieval"]["ground_truth_found"]
    rank_str = f"第 {gt_rank} 名" if gt_rank else "未找到"
    print(f"  Ground truth 排名: {rank_str}")
    print(f"  规则预标注: {query.get('pre_label', '?')}")
    if query.get("llm_label") is not None:
        print(f"  LLM 预标注: {query.get('llm_label')} — {query.get('llm_reason', '')}")

    print(f"\n  Top-5 检索结果:")
    for rank, ku_id in enumerate(query["retrieval"]["top_ku_ids"][:5], start=1):
        score = query["retrieval"]["scores"].get(ku_id, 0.0)
        summary = ku_summaries.get(ku_id, str(ku_id))[:60]
        gt_marker = " <<GT>>" if ku_id == gt_ku["ku_id"] else ""
        print(f"    {rank}. [score={score:.1f}] {summary}{gt_marker}")

    print(f"\n  评分: 0=无关 1=部分相关 2=相关排序差 3=精准")
    print(f"  Enter=接受预标注 | s=跳过 | q=退出")

    try:
        raw = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if raw == "q":
        return None
    if raw == "s":
        return -1  # 跳过标记
    if raw == "" or raw == str(query["pre_label"]):
        return query["pre_label"]
    if raw in ("0", "1", "2", "3"):
        return int(raw)

    print(f"  无效输入，使用预标注: {query['pre_label']}")
    return query["pre_label"]


def main() -> None:
    parser = argparse.ArgumentParser(description="黄金数据集标注工具")
    parser.add_argument("--input", required=True, help="输入 JSON 路径")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    parser.add_argument("--db", default="data/news.db", help="数据库路径（加载 KU 摘要）")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 预标注")
    parser.add_argument("--only-disputed", action="store_true", help="只展示预标注不一致的样本")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    dataset = json.loads(input_path.read_text(encoding="utf-8"))
    logger.info("加载 %d items, %d queries", len(dataset["items"]),
                sum(len(it["queries"]) for it in dataset["items"]))

    # 加载 KU 摘要（用于展示非 ground truth 的检索结果）
    logger.info("加载 KU 摘要...")
    ku_summaries = load_ku_summaries(args.db)
    logger.info("加载 %d 条 KU 摘要", len(ku_summaries))

    # 如果输出已存在，加载已标注数据（断点续标）
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        existing_items = {it["item_id"]: it for it in existing.get("items", [])}
        # 合并已标注数据
        for item in dataset["items"]:
            if item["item_id"] in existing_items:
                old_item = existing_items[item["item_id"]]
                for q in item["queries"]:
                    for old_q in old_item["queries"]:
                        if old_q.get("human_label") is not None and old_q["query_text"] == q["query_text"]:
                            q["human_label"] = old_q["human_label"]
                            q["human_notes"] = old_q.get("human_notes")
        logger.info("恢复已有标注")

    # LLM 预标注
    if not args.skip_llm:
        client, model = create_offline_llm_client()
        logger.info("LLM 预标注中...")
        total_labeled = 0
        for item in dataset["items"]:
            gt_ku = item["ground_truth_ku"]
            for query in item["queries"]:
                if query.get("llm_label") is not None:
                    continue
                result = llm_label_query(query, gt_ku, client, model)
                if result:
                    query["llm_label"] = result[0]
                    query["llm_reason"] = result[1]
                    total_labeled += 1
        logger.info("LLM 预标注完成: %d queries", total_labeled)

    # 人工校验
    total = sum(len(it["queries"]) for it in dataset["items"])
    labeled = sum(
        1 for it in dataset["items"] for q in it["queries"] if q.get("human_label") is not None
    )
    print(f"\n=== 黄金数据集标注工具 ===")
    print(f"总查询: {total} | 已标注: {labeled} | 待标注: {total - labeled}")
    if args.only_disputed:
        print("模式: 只展示预标注不一致的样本")

    current = 0
    for item in dataset["items"]:
        for qidx, query in enumerate(item["queries"]):
            current += 1
            if query.get("human_label") is not None:
                continue

            # 只展示有分歧的样本
            if args.only_disputed:
                pre = query.get("pre_label", 0)
                llm = query.get("llm_label")
                if llm is not None and llm == pre:
                    continue

            label = human_label_cli(item, qidx, query, ku_summaries)
            if label is None:
                # 退出前保存
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"\n已保存进度到 {output_path}")
                return

            if label == -1:
                continue  # 跳过

            query["human_label"] = label

            # 即时保存
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    # 保存最终结果
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    final_labeled = sum(
        1 for it in dataset["items"] for q in it["queries"] if q.get("human_label") is not None
    )
    print(f"\n标注完成: {final_labeled}/{total}")


if __name__ == "__main__":
    main()
