"""
Critic Agent 提示词定义

按 .claude/rules/02-prompts.md 定义。
"""

SYSTEM_PROMPT = """你是一个事实核查员。你的任务是验证报告的准确性。

## 核查流程
1. 读取最终报告与原始情报微粒
2. 验证每个断言是否有引用依据
3. 驳回无依据的"幻觉"结论

## 驳回条件
- 断言无 Particle_ID 支撑
- 结论与情报微粒内容矛盾
- 时间线逻辑错误（用 T2 事件预警 T1 风险）

## 通过条件
- 所有关键断言有溯源
- 风险传导路径可追溯
- 冲突观点已明确标注

## 输出格式
返回 JSON 格式的核查结果：
{
    "passed": true/false,
    "issues": [
        {
            "type": "MISSING_SOURCE" | "CONTRADICTION" | "TEMPORAL_ERROR",
            "description": "问题描述",
            "location": "问题位置"
        }
    ],
    "suggestions": ["修改建议"]
}
"""


def build_verification_prompt(
    report: dict,
    particles: list[dict],
) -> str:
    """构建核查提示词

    Args:
        report: 待核查的报告
        particles: 原始情报微粒

    Returns:
        核查提示词
    """
    import json

    report_text = json.dumps(report, ensure_ascii=False, indent=2)
    particles_text = "\n\n".join(
        [
            f"""### Particle: {p.get('id', 'N/A')}
- 事件时间: {p.get('event_time', 'N/A')}
- 事件类型: {p.get('event_type', 'N/A')}
- 描述: {p.get('description', 'N/A')}
- 来源文档: {', '.join(p.get('source_doc_ids', []))}"""
            for p in particles
        ]
    )

    return f"""请核查以下风险分析报告。

## 待核查报告
```json
{report_text}
```

## 原始情报微粒
{particles_text if particles_text else "无情报微粒"}

## 核查要求
1. 检查每个结论是否有 Particle_ID 支撑
2. 检查是否存在时间线逻辑错误
3. 检查是否存在与情报微粒矛盾的内容
4. 返回 JSON 格式的核查结果
"""
