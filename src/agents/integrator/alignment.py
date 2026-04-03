"""
实体对齐模块

按 .claude/rules/02-prompts.md 定义的实体对齐规则。
"""

import re
from difflib import SequenceMatcher


# === 公司名称后缀列表 ===

COMPANY_SUFFIXES = [
    "有限公司",
    "股份有限公司",
    "有限责任公司",
    "集团",
    "公司",
    "有限",
    "股份",
    "控股有限公司",
    "投资股份有限公司",
    "科技有限公司",
    "实业有限公司",
    "发展有限公司",
]


def normalize_entity_name(name: str) -> str:
    """标准化实体名称

    移除公司名称后缀，用于模糊匹配。

    Args:
        name: 原始实体名称

    Returns:
        标准化后的名称
    """
    normalized = name.strip()

    # 移除公司后缀（从长到短匹配）
    for suffix in sorted(COMPANY_SUFFIXES, key=len, reverse=True):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break

    # 移除括号及内容
    normalized = re.sub(r"[（）\(\)][^）\)]*[）\)]", "", normalized)

    # 移除空格
    normalized = normalized.replace(" ", "")

    return normalized


def calculate_similarity(name1: str, name2: str) -> float:
    """计算两个名称的相似度

    使用 SequenceMatcher 计算相似度。

    Args:
        name1: 名称1
        name2: 名称2

    Returns:
        相似度 (0-1)
    """
    # 先标准化
    n1 = normalize_entity_name(name1)
    n2 = normalize_entity_name(name2)

    # 完全相同
    if n1 == n2:
        return 1.0

    # 计算相似度
    return SequenceMatcher(None, n1, n2).ratio()


def is_same_entity(
    name1: str,
    name2: str,
    credit_code1: str | None = None,
    credit_code2: str | None = None,
    threshold: float = 0.9,
) -> tuple[bool, str]:
    """判断两个实体是否为同一实体

    对齐规则：
    1. 工商号优先：如果存在工商号，以工商号为唯一主键
    2. 名称匹配：标准化后匹配度 > 90% 且无冲突工商号 → 自动合并
    3. 冲突处理：名称相似但工商号不同 → 保留独立节点，标记"疑似关联"

    Args:
        name1: 名称1
        name2: 名称2
        credit_code1: 工商注册号1
        credit_code2: 工商注册号2
        threshold: 相似度阈值

    Returns:
        (是否同一实体, 原因说明)
    """
    # 规则1：工商号优先
    if credit_code1 and credit_code2:
        if credit_code1 == credit_code2:
            return True, "工商号相同"
        else:
            return False, "工商号不同"

    # 规则2：只有一个有工商号
    if credit_code1 or credit_code2:
        return False, "工商号信息不完整，无法合并"

    # 规则3：名称匹配
    similarity = calculate_similarity(name1, name2)
    if similarity >= threshold:
        return True, f"名称相似度 {similarity:.2%} >= {threshold:.0%}"

    return False, f"名称相似度 {similarity:.2%} < {threshold:.0%}"


def find_best_match(
    target_name: str,
    candidates: list[dict],
    threshold: float = 0.9,
) -> tuple[dict | None, float]:
    """在候选列表中找到最佳匹配

    Args:
        target_name: 目标名称
        candidates: 候选实体列表 [{"name": "xxx", "id": "xxx", "credit_code": "xxx"}, ...]
        threshold: 相似度阈值

    Returns:
        (最佳匹配实体, 相似度)
    """
    best_match: dict | None = None
    best_score = 0.0

    for candidate in candidates:
        score = calculate_similarity(target_name, candidate.get("name", ""))
        if score > best_score:
            best_score = score
            best_match = candidate

    if best_score >= threshold:
        return best_match, best_score

    return None, best_score


class EntityAlignment:
    """实体对齐管理器"""

    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold

    def align(
        self,
        entity_name: str,
        entity_type: str,
        credit_code: str | None = None,
        existing_entities: list[dict] | None = None,
    ) -> dict:
        """执行实体对齐

        Args:
            entity_name: 实体名称
            entity_type: 实体类型
            credit_code: 工商注册号
            existing_entities: 已存在的实体列表

        Returns:
            {
                "action": "create" | "merge" | "suspected",
                "matched_id": str | None,
                "similarity": float,
                "reason": str
            }
        """
        if not existing_entities:
            return {
                "action": "create",
                "matched_id": None,
                "similarity": 1.0,
                "reason": "无现有实体，创建新节点",
            }

        # 查找最佳匹配
        match, similarity = find_best_match(
            entity_name,
            existing_entities,
            self.threshold,
        )

        if match:
            # 检查工商号
            existing_credit = match.get("credit_code")
            is_same, reason = is_same_entity(
                entity_name,
                match.get("name", ""),
                credit_code,
                existing_credit,
                self.threshold,
            )

            if is_same:
                return {
                    "action": "merge",
                    "matched_id": match.get("id"),
                    "similarity": similarity,
                    "reason": reason,
                }
            else:
                return {
                    "action": "suspected",
                    "matched_id": match.get("id"),
                    "similarity": similarity,
                    "reason": f"疑似关联：{reason}",
                }

        return {
            "action": "create",
            "matched_id": None,
            "similarity": similarity,
            "reason": f"无匹配实体（最高相似度 {similarity:.2%}）",
        }
