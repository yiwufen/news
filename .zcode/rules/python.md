# Python 开发规则

> 项目级规则以 `docs/SHARED_RULES.md` 为准；本文件保留 ZCode 侧 Python 约定。

## 环境管理

使用 `uv` 管理 Python 环境和依赖。

## 类型检查

提交前执行 `uv run pyright .` 确保无类型错误。

