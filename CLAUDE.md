# Claude Code 入口

本仓库的项目级规则统一维护在 [`docs/SHARED_RULES.md`](docs/SHARED_RULES.md)。  
`CLAUDE.md` 不再承载完整项目规范，只负责 Claude Code 的入口说明与规则索引。

## Claude Code 使用顺序

1. 先读 `docs/SHARED_RULES.md`
2. 再读 `PROGRESS.md`
3. 按需加载 `.claude/rules/` 下的规则文件

## Claude 专属规则入口

- `.claude/rules/01-taxonomy.md`：金融语义与枚举标准
- `.claude/rules/02-prompts.md`：Agent Prompt 模板
- `.claude/rules/03-risk-logic.md`：风险传导算法
- `.claude/rules/04-intent-retrieval.md`：意图解析与检索规范
- `.claude/rules/python.md`：Python 开发规则

## 维护原则

- 项目目标、系统架构、核心数据契约、开发 guardrails 一律回写到 `docs/SHARED_RULES.md`
- `.claude/rules/` 仅保留 Claude 机制需要的规则文件或对共享规范的补充
- 若 `CLAUDE.md` 与共享规范不一致，以共享规范为准
