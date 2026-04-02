# Python 开发规则

## 环境管理

使用 `uv` 管理 Python 环境和依赖。

## 类型检查

提交前执行 `uv run pyright .` 确保无类型错误。

## 代码风格

- 使用 Python 3.10+ 语法：`list[str]`、`match-case`、`@dataclass(frozen=True)`
