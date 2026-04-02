# 项目开发规则

## 环境管理

使用 `uv` 管理 Python 环境和依赖：

```bash
# 添加新依赖
uv add <package>

# 运行脚本
uv run python collectors/generate_news.py --count 10

# 查看统计
uv run python collectors/generate_news.py --stats
```

## 项目结构

```
d:/value/news/
├── collectors/
│   ├── config.py          # 实体池、事件类型、生成配置
│   ├── database.py        # SQLite 数据库操作
│   └── generate_news.py   # 模拟数据收集器（LLM 生成）
├── data/
│   └── news.db            # SQLite 数据库
├── .claude/rules/         # 开发规则
│   ├── python.md          # Python 开发规则
│   └── typecheck.md       # 类型检查规则
├── .env                   # API 配置
└── blueprint.md           # 系统架构蓝图
```

## 数据生成

```bash
# 测试生成 10 条
uv run python collectors/generate_news.py --count 10

# 完整生成 80 条
uv run python collectors/generate_news.py --count 80 --batch-size 10

# 查看统计
uv run python collectors/generate_news.py --stats
```

## 详细规则

- [Python 开发规则](.claude/rules/python.md)
