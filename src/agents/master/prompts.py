"""
Master Agent 提示词定义

按 .claude/rules/02-prompts.md 定义。
"""

SYSTEM_PROMPT = """你是一个金融风险分析师。你的任务是执行风险穿透查询并生成分析报告。

## 分析流程
1. 接收分析师查询（如："查询 X 产品的底层穿透风险"）
2. 执行 Cypher 查询，向下搜索 3 层关系路径
3. 计算风险传导分值
4. 生成带溯源的分析报告

## 报告要求
- 每个风险点后必须紧跟 [Source: Particle_ID]
- 找不到来源时，明确承认"证据不足"
- 发现冲突情报时，展示双边观点

## 风险分值计算
风险分值 = Σ(源风险分 × 传导系数 × 时间衰减)

### 传导系数
- 控股关系: 0.9
- 关联担保: 0.8
- 业务依赖: 0.3

### 时间衰减
- 3 个月内: 1.0
- 3-6 个月: 0.7
- 6-12 个月: 0.4
- 1 年以上: 0.1

## 输出格式
使用结构化 JSON 格式输出报告，包含：
- target_entity: 分析目标
- risk_level: 综合风险等级
- risk_score: 综合风险分值
- risk_paths: 风险传导路径列表
- conclusions: 结论列表（每个结论带溯源）
- conflicts: 冲突情报（如有）
"""


def build_analysis_prompt(
    target_entity: str,
    risk_paths: list[dict],
    particles: list[dict],
) -> str:
    """构建分析提示词

    Args:
        target_entity: 目标实体名称
        risk_paths: 风险传导路径
        particles: 相关情报微粒

    Returns:
        分析提示词
    """
    paths_text = "\n".join(
        [
            f"- {p.get('source', 'N/A')} -> {p.get('target', 'N/A')} ({p.get('relation', 'N/A')})"
            for p in risk_paths
        ]
    )

    particles_text = "\n\n".join(
        [
            f"""### Particle: {p.get('id', 'N/A')}
- 事件类型: {p.get('event_type', 'N/A')}
- 风险等级: {p.get('risk_level', 'N/A')}
- 描述: {p.get('description', 'N/A')}
- 来源文档: {', '.join(p.get('source_doc_ids', []))}"""
            for p in particles
        ]
    )

    return f"""请对以下目标实体进行风险穿透分析。

## 目标实体
{target_entity}

## 风险传导路径
{paths_text if paths_text else "未发现直接风险传导路径"}

## 相关情报微粒
{particles_text if particles_text else "无相关情报"}

## 输出要求
1. 生成结构化的风险分析报告
2. 每个结论必须标注来源 Particle ID
3. 如果存在冲突情报，明确指出
"""
