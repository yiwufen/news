# LLM 提示词设计原则

> 适用于本项目中所有 LLM prompt 的设计与优化，包括知识抽取（`src/knowledge_extractor.py`）、实体描述（`src/entity_description.py`）、实体上下文注入（`src/entity_context_filter.py`）等。
>
> 本项目使用 tool-use (function calling) 模式，输出为结构化 JSON，不是纯文本补全。

## 原则 1：Schema 优先于 prompt 文本

凡是能用 JSON schema 的 `enum`、`description`、`pattern`、`minItems` 等字段约束的，不要只在 system prompt 里用自然语言描述。

- Schema 是硬约束，模型填参数时优先参考 schema 定义
- Prompt 文本是软引导，用于传达 schema 无法表达的判断逻辑

**具体场景**：`EXTRACTION_TOOL_SCHEMA` 中 `relation_type` 应在 schema `enum` 里枚举，而不是只在 prompt 里列清单。`unit_type` 同理。

**反面**：在 prompt 里写"relation_type 只能从以下列表中选择"，但 schema 的 `type: "string"` 没有任何约束——模型会忽略 prompt 列表。

## 原则 2：正反例优先于抽象规则

每个容易出错的边界 case，给 1 个正例 + 1 个反例，比多写 5 行规则有效。

- 优先针对召回率最低的类型补充示例（当前基线：broad_topic 55.6%、entity_only 58.8%）
- 示例应使用项目中的实际字段名（`unit_type`、`mention`、`evidence`）

**具体场景**：在 `SYSTEM_PROMPT` 的实体排除规则后，附上 2-3 个边界 case 的正反例，帮助模型区分"苹果公司(Company)"和"苹果产业链(抽象概念，不提取)"。

**反面**：只写"仅限人物、组织、国家、核心技术/产品"但没有示例，模型对"产业链""板块""赛道"等词的处理不可预测。

## 原则 3：显式优先级声明

当规则 A 和规则 B 可能冲突时，必须写明谁优先。没有优先级的规则在边界 case 上行为不可预测。

**具体场景**：当前 prompt 中"不要漏掉实体"和"宁可漏掉也不要抓非实体"存在隐含冲突。应显式声明：

```
提取优先级（遇到边界 case 时按此顺序裁决）
1. 准确性 > 召回率（宁缺毋滥）
2. 具体实体 > 抽象概念
3. 有时间锚点的动态陈述 > 静态背景
```

**反面**：同时写"尽量提取所有相关实体"和"不确定的不要提取"但不说明哪个优先。

## 原则 4：输入首尾效应

模型对输入文本的开头和结尾注意力最强（primacy + recency effect）。最重要的输入应放在首部或尾部。

**具体场景**：`build_extraction_prompt` 中，正文（`content`）是最重要的输入，应放在 prompt 的最前面或最后面，不要被文档元信息夹在中间。元信息（doc_id、title 等）用紧凑的 key-value 格式即可。

**反面**：prompt 结构为"元信息 → 正文 → 已知实体参考"，正文被挤到中间。

## 原则 5：可验证的自洽性检查

要求模型做输出自检时，检查项必须可客观验证（字符串匹配、枚举包含、非空等），不要使用主观判断。

**具体场景**：以下自检项是有效的：
- `relation_hint.subject_mention` 是否在 `entities` 列表的 `mention` 中出现
- `evidence.text` 是否是正文的子串
- `unit_type` 是否在枚举范围内

以下自检项是无效的：
- "提取的实体是否足够重要"
- "事件是否有足够的影响力"

**反面**：要求模型"检查提取结果是否全面准确"——这种主观检查不会改善输出质量。

## 原则 6：Prompt 只做感知，不做认知

Extraction prompt 只负责准确识别和提取（感知）。实体消歧、冲突裁决、归并、推理等认知任务交给后处理模块。

- Prompt 阶段不应要求模型做别名归并——单篇新闻没有全局视角，消歧由 `src/entities.py` 后处理负责
- Prompt 阶段不应要求模型裁决冲突——由 `src/conflict_detection.py` 负责
- Prompt 阶段不应要求模型做事件归并——由 `src/event_merging.py` 负责

**具体场景**：`entity_context_filter.py` 注入已知实体列表是正确的（帮助模型使用标准名称），但不应在 prompt 中要求模型"将别名统一归并为主称"——这和后处理消歧逻辑冲突，增加调试难度。

## 原则 7：不要用 XML 标签隔离

Tool-use 模式下，结构化输出已天然隔离在 function call 参数中，不需要 XML 输出标签（`<output>`、`<thinking>` 等）。

- 如果需要 chain-of-thought 推理，使用 Claude 的 extended thinking 参数（`thinking`），不是手写 XML 标签
- 输入隔离：markdown section header（`## 正文`）已经足够，XML 输入标签（`<news_article>`）在 tool-use 模式下是冗余的

**反面**：在 tool-use prompt 中要求"输出必须包裹在 `<output>` 标签中"——模型需要同时满足 function call 格式和 XML 格式，增加出错概率。
