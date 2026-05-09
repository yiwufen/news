# User Testing Personas

每个画像代表一种用户类型。Agent 会话轮换使用画像以确保覆盖不同使用模式。

---

## P1: Financial Analyst (analyst)

| Attribute | Value |
|-----------|-------|
| **Key** | `analyst` |
| **Role** | 买方/卖方分析师 |
| **Technical Level** | 高 — 理解 JSON，熟悉 CLI |
| **Primary Goal** | 检索特定公司、事件、关系的准确全面知识 |
| **Query Style** | 精确实体名、具体时间范围、关注时间线和关系 |
| **Tolerance for Error** | 低 — 需要准确数据撰写报告 |

### Typical Queries

```bash
knowledge-cli search --entities "小米集团" --intent ENTITY_TIMELINE --time-range 2025-04-01:2026-04-13
knowledge-cli search --entities "腾讯控股" --intent RELATIONSHIP_QUERY --target-entity "美团" --hops 2
knowledge-cli search --entities "恒大集团" --intent EVENT_ANALYSIS --event-types "债务违约"
knowledge-cli search --entities "比亚迪" --intent ENTITY_OVERVIEW
```

### What This Persona Cares About

- **Completeness**: 遗漏关键事件不可接受
- **Entity Resolution**: 混淆两家相似公司是严重错误
- **Cluster Quality**: 关联事件是否正确聚合
- **Temporal Accuracy**: 日期是否准确

---

## P2: AI Agent Developer (developer)

| Attribute | Value |
|-----------|-------|
| **Key** | `developer` |
| **Role** | 将 knowledge-cli 集成到更大 Agent 系统的开发者 |
| **Technical Level** | 极高 — 检查 JSON 结构、错误处理、边界条件 |
| **Primary Goal** | 可靠地将 knowledge-cli 集成到程序化调用链中 |
| **Query Style** | 压力测试边界条件、遍历所有 intent 类型、检查 schema 稳定性 |
| **Tolerance for Error** | 中 — 预期有粗糙之处但需要可预测行为 |

### Typical Queries

```bash
knowledge-cli search --entities ""                           # 空实体
knowledge-cli search --entities "小米集团" --top-k 0          # 极小 top-k
knowledge-cli search --entities "小米集团" --top-k 1000       # 极大 top-k
knowledge-cli search --entities "不存在公司" --intent ENTITY_OVERVIEW  # 不存在实体
knowledge-cli search --entities "小米集团" --no-graph          # 无图谱
knowledge-cli search --entities "小米集团" --hops 5            # 最大跳数
knowledge-cli search --entities "小米集团" --time-range 2026-01-01:2026-01-01  # 零长度时间
```

### What This Persona Cares About

- **Schema Consistency**: 所有输入下 JSON 结构是否一致
- **Error Messages**: 错误信息是否清晰可操作
- **Graceful Degradation**: 无崩溃、无乱码输出
- **Response Predictability**: 相同输入是否给出相同输出
- **Argument Validation**: 无效输入是否快速失败并给出明确提示

---

## P3: Casual Business Reader (casual)

| Attribute | Value |
|-----------|-------|
| **Key** | `casual` |
| **Role** | 偶尔查阅公司信息的商务人士 |
| **Technical Level** | 低 — 只想要答案，CLI 有门槛 |
| **Primary Goal** | 快速了解一家公司或一个话题 |
| **Query Style** | 模糊、用常见名称（非正式名）、可能含简称 |
| **Tolerance for Error** | 高 — 预期不完美但空结果令人沮丧 |

### Typical Queries

```bash
knowledge-cli search --entities "小米"            # 简称
knowledge-cli search --entities "字节跳动"          # 可能不在库中
knowledge-cli search --entities "腾讯"             # 单字简称
knowledge-cli search --entities "恒大"             # 热门困境公司
knowledge-cli search --entities "苹果" --time-range 2025-01-01:2025-12-31
```

### What This Persona Cares About

- **Tolerance**: 输入不精确时是否仍能给出有用结果
- **Understandability**: 结果是否可理解（不是原始 JSON 堆砌）
- **Responsiveness**: 系统响应是否够快
- **Discoverability**: 不理解所有参数时能否找到所需信息

---

## Persona Rotation Strategy

新会话启动时：
1. 检查 `docs/user-testing/session-log.md` 中的最近会话
2. 选择最近最少使用的画像
3. 平局时按 P1 > P2 > P3 顺序
