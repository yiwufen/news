# AGENTS.md

本仓库的项目级规则统一以 [`docs/SHARED_RULES.md`](docs/SHARED_RULES.md) 为唯一真源。

## 进入仓库后先看什么

1. 先读 `docs/SHARED_RULES.md`
2. 再看 `PROGRESS.md` 了解当前完成度与待办
3. 涉及 Claude 目录规则时，再看 `.claude/rules/`

## 必须遵守的项目约定

- 使用 `uv` 管理环境与依赖
- 不修改运行接口语义：`run_pipeline()`、`run_continuous()`
- 涉及项目规则、数据契约、流程约束时，以共享规范为准
- 迁移阶段默认把 `IntelligenceParticle`、`RiskReport` 与旧风险图逻辑视为 `legacy`，新实现不得继续围绕它们扩展
- 如必须复用旧实现，只能通过显式适配层接入，不要让新核心模型直接依赖旧模型
- 完成功能后更新 `PROGRESS.md`
- 提交前至少运行：

```bash
uv run pytest
uv run pyright .
```

## Codex 侧执行约定

- 优先复用现有模块和文档，不额外复制一份项目规则
- 代码或注释如果需要引用规范，优先引用 `docs/SHARED_RULES.md`
- 若 `.claude/rules/` 与共享规范看起来重复，以共享规范为准，并仅把 `.claude/rules/` 视为 Claude 的机制适配层
