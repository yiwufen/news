# Claude Code 入口

本仓库的项目级规则统一维护在 [`docs/SHARED_RULES.md`](docs/SHARED_RULES.md)。  
`CLAUDE.md` 不再承载完整项目规范，只负责 Claude Code 的入口说明与规则索引。

## Claude Code 使用顺序

1. 先读 `docs/SHARED_RULES.md`
2. 按需加载 `.claude/rules/` 下的规则文件

## Claude 专属规则入口

- `.claude/rules/python.md`：Python 开发规则

其余历史规则文件已删除，避免旧的风险研判设计继续干扰当前“金融知识检索底座”方向。

## 维护原则

- 项目目标、系统架构、核心数据契约、开发 guardrails 一律回写到 `docs/SHARED_RULES.md`
- `.claude/rules/` 仅保留 Claude 机制需要的最小规则文件
- 迁移阶段默认把旧风险导向实现视为 `legacy`，新实现不得继续以其为核心扩展
- 若 `CLAUDE.md` 与共享规范不一致，以共享规范为准
