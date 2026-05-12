# 实体解析五步修补 — Claude Code 实施方案

> **目标**：在现有贪心匹配框架内修补 5 个实现缺陷，补充黄金测试集，守住高精度底线。
> **预估**：1-1.5 天（含测试）
> **唯一修改文件**：`src/entities.py`（主逻辑）、`tests/unit/test_entity_resolution.py`（新增测试）

---

## 实施顺序与依赖关系

```
Patch 3（后缀剥离）  ← 无依赖，先做
    ↓ normalize 输出变化，影响 Patch 4 的索引 key
Patch 4（倒排索引）  ← 依赖 Patch 3 的 normalize 输出稳定
    ↓ _find_match 结构变化
Patch 1（跨语言）    ← 依赖 _find_match 结构
Patch 2（类型放宽）  ← 依赖 _find_match 结构
Patch 5（别名防膨胀）← 最后，独立
    ↓
Golden Test Suite    ← 所有 Patch 完成后统一验证
```

**建议执行顺序**：3 → 4 → 1 → 2 → 5 → 测试

---

## Patch 3：贪婪后缀剥离 → 单次最长匹配

**文件**：`src/entities.py`
**修改函数**：`normalize_entity_name()`（行 207-221）

**当前问题**：`while changed` 循环反复剥离后缀，"控股有限公司" → "控股" → ""。

**改动**：

```python
# 预编译正则（模块级常量，在 _ENTITY_SUFFIXES 之后）
_SUFFIX_PATTERN = re.compile(
    "(" + "|".join(re.escape(s) for s in sorted(_ENTITY_SUFFIXES, key=len, reverse=True)) + r")$"
)

def normalize_entity_name(name: str) -> str:
    """Normalize an entity name for conservative matching."""
    normalized = _strip_separators(name)
    if not normalized:
        return ""
    # Single-pass: strip the longest matching suffix once
    result, _ = _SUFFIX_PATTERN.subn("", normalized, count=1)
    return result if len(result) > 0 else normalized
```

**验证**：
- "控股有限公司" → "控股"（不再是 ""）
- "美的集团" → "美的"
- "宁德时代股份有限公司" → "宁德时代"
- "腾讯" → "腾讯"（无后缀，不变）

---

## Patch 4：倒排索引提速

**文件**：`src/entities.py`
**修改函数**：`resolve_units_with_cache()` 和 `_find_match()`

**当前问题**：每个 mention 遍历全部实体，O(M×E)。

**改动**：

在 `resolve_units_with_cache` 中预建索引：

```python
# 在 norm_cache 之后添加
name_index: dict[str, list[str]] = {}  # normalized_name → [entity_id, ...]
alias_index: dict[str, list[str]] = {}  # normalized_alias → [entity_id, ...]
for eid, e in entities_cache.items():
    nk = norm_cache[eid]
    if nk:
        name_index.setdefault(nk, []).append(eid)
    for alias in e.aliases:
        ak = normalize_entity_name(alias)
        if ak:
            alias_index.setdefault(ak, []).append(eid)
```

新实体创建后同步更新索引：

```python
# 在 entities_cache[matched.entity_id] = matched 之后
nk = normalize_entity_name(matched.canonical_name)
if nk:
    name_index.setdefault(nk, []).append(matched.entity_id)
```

`_find_match` 签名增加 `name_index` 和 `alias_index` 参数，layer 2/3 改为 O(1) 查找：

```python
def _find_match(
    self,
    mention: str,
    identifiers: dict[str, str],
    entities_cache: dict[str, Entity],
    norm_cache: dict[str, str],
    name_index: dict[str, list[str]],
    alias_index: dict[str, list[str]],
) -> Entity | None:
    normalized = normalize_entity_name(mention)

    # Layer 1: identifier match (unchanged, rare path)
    if identifiers:
        for entity in entities_cache.values():
            if entity.identifiers:
                for key, value in identifiers.items():
                    if entity.identifiers.get(key) == value:
                        return entity

    # Layer 2: normalized name exact match via index
    for eid in name_index.get(normalized, []):
        return entities_cache[eid]

    # Layer 3: normalized alias exact match via index
    for eid in alias_index.get(normalized, []):
        return entities_cache[eid]

    # Layer 4: SequenceMatcher fallback (保留，仅对未命中索引的 mention 执行)
    inferred_type = _infer_entity_type(mention)
    for entity in entities_cache.values():
        norm_name = norm_cache[entity.entity_id]
        similarity = SequenceMatcher(None, normalized, norm_name).ratio()
        if similarity >= 0.95 and entity.entity_type == inferred_type:
            return entity

    return None
```

---

## Patch 1：跨语言别名加入合并流程

**文件**：`src/entities.py`
**修改函数**：`_find_match()`（在 Patch 4 改造后的版本上）

**当前问题**：`_CROSS_LINGUAL_ALIASES` 仅在 `find_by_names` 使用，合并路径不调用。

**改动**：在 Layer 1（identifier）和 Layer 2（normalized name）之间插入 Layer 1.5：

```python
    # Layer 1.5: cross-lingual alias → resolve to Chinese name → match
    cross_lingual = EntityRepository._CROSS_LINGUAL_ALIASES.get(mention.strip().lower())
    if cross_lingual:
        cross_norm = normalize_entity_name(cross_lingual)
        for eid in name_index.get(cross_norm, []):
            return entities_cache[eid]
        for eid in alias_index.get(cross_norm, []):
            return entities_cache[eid]
```

**精度保障**：字典是硬编码高置信度映射，且使用精确匹配。

---

## Patch 2：类型推断从硬拒绝改为分层干预

**文件**：`src/entities.py`
**修改函数**：`_find_match()`

**当前问题**：Layer 4 的 `entity.entity_type == inferred_type` 硬拒绝，但 Layer 2/3 的精确匹配也被隐式要求类型一致（因为不同 mention 推断出不同类型会导致 normalized name 相同但走了 layer 4 被拒）。

**改动**：

- Layer 1, 1.5, 2, 3（精确匹配路径）：**完全不检查类型**。名称精确匹配置信度远高于基于字面的类型推断。
- Layer 4（SequenceMatcher 模糊匹配）：**保留类型硬约束**。0.95 模糊匹配 + 类型不同 = 确实不安全。

这个改动在 Patch 4 的代码结构中已经自然实现——Layer 2/3 是索引精确匹配直接 return，没有类型检查。只需确认 Layer 4 保留类型约束即可：

```python
    # Layer 4: SequenceMatcher fallback — 保留类型硬约束
    inferred_type = _infer_entity_type(mention)
    for entity in entities_cache.values():
        norm_name = norm_cache[entity.entity_id]
        similarity = SequenceMatcher(None, normalized, norm_name).ratio()
        if similarity >= 0.95 and entity.entity_type == inferred_type:
            return entity
```

**注**：实际上 Patch 4 的重构已经隐式解决了 Patch 2。精确匹配路径不再经过类型检查，只有模糊匹配路径保留类型约束。无需额外代码。

---

## Patch 5：别名池防膨胀与去重

**文件**：`src/entities.py`
**修改函数**：`resolve_units_with_cache()`

**当前问题**：`entity.aliases.append(mention)` 无去重无上限。

**改动**：在追加 alias 前增加拦截器：

```python
MAX_ALIASES = 10

# 在 resolve_units_with_cache 的 else 分支（匹配成功时）
else:
    # Alias dedup: skip if normalized form already exists
    mention_norm = normalize_entity_name(entity_ref.mention)
    existing_norms = {normalize_entity_name(a) for a in matched.aliases}
    if mention_norm not in existing_norms and entity_ref.mention not in matched.aliases:
        if len(matched.aliases) < MAX_ALIASES:
            matched.aliases.append(entity_ref.mention)
        # 同步更新 alias_index
        if mention_norm:
            alias_index.setdefault(mention_norm, []).append(matched.entity_id)

    if unit.ku_id not in matched.source_ku_ids:
        matched.source_ku_ids.append(unit.ku_id)
    matched.identifiers.update(entity_ref.identifiers)
    matched.updated_at = now
```

---

## Golden Test Suite

**新增文件**：`tests/unit/test_entity_resolution.py`

### 防误合测试（Precision Cases）

```python
import pytest
from src.entities import (
    Entity, EntityResolver, EntityRepository,
    normalize_entity_name, _infer_entity_type,
)
from datetime import UTC, datetime


class TestPrecision:
    """Must NOT merge — different real-world entities."""

    def test_geely_vs_dajili(self):
        """'吉利' vs '大吉利' — 子串但不同实体"""
        # normalize: '吉利' vs '大吉利' — 不同，不应精确匹配
        # SequenceMatcher('吉利', '大吉利') = 2*2/5 = 0.8 < 0.95 — 不应模糊匹配
        assert normalize_entity_name("吉利") != normalize_entity_name("大吉利")

    def test_midea_group_vs_midea_realestate(self):
        """'美的集团' vs '美的置业' — 不同实体"""
        # Patch 3 修复后：'美的集团' → '美的'，'美的置业' → '美的置业'
        assert normalize_entity_name("美的集团") != normalize_entity_name("美的置业")

    def test_hengda_health_vs_hengda_realestate(self):
        """'恒大健康' vs '恒大地产' — 同集团不同子公司"""
        assert normalize_entity_name("恒大健康") != normalize_entity_name("恒大地产")

    def test_over_stripping_prevention(self):
        """'控股有限公司' 不应变为空字符串"""
        result = normalize_entity_name("控股有限公司")
        assert result != "", f"过度剥离: '控股有限公司' → '{result}'"
        assert len(result) > 0


class TestRecall:
    """Must merge — same real-world entity."""

    def test_tencent_type_mismatch(self):
        """'腾讯' (Person) vs '腾讯控股' (Company) — 类型不同但应合并"""
        # _infer_entity_type('腾讯') = Person, _infer_entity_type('腾讯控股') = Company
        assert _infer_entity_type("腾讯") == "Person"
        assert _infer_entity_type("腾讯控股") == "Company"
        # 但 normalized name 精确匹配时应忽略类型
        assert normalize_entity_name("腾讯") == normalize_entity_name("腾讯控股")

    def test_byd_cross_lingual(self):
        """'BYD' → '比亚迪' — 跨语言别名"""
        assert "byd" in EntityRepository._CROSS_LINGUAL_ALIASES
        assert EntityRepository._CROSS_LINGUAL_ALIASES["byd"] == "比亚迪"

    def test_suffix_strip_preserves_core(self):
        """'宁德时代股份有限公司' → '宁德时代'，与 '宁德时代' 匹配"""
        assert normalize_entity_name("宁德时代股份有限公司") == "宁德时代"
        assert normalize_entity_name("宁德时代") == "宁德时代"

    def test_alias_dedup(self):
        """同实体的 normalized 相同别名不应重复追加"""
        entity = Entity(
            entity_type="Company",
            canonical_name="腾讯控股",
            aliases=["腾讯", "腾讯控股"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        # '腾讯控股(' normalized 应与 '腾讯控股' 相同，不应追加
        mention_norm = normalize_entity_name("腾讯控股(")
        existing_norms = {normalize_entity_name(a) for a in entity.aliases}
        assert mention_norm in existing_norms  # 已存在，不应追加


class TestNormalization:
    """Suffix stripping behavior."""

    def test_single_pass_not_recursive(self):
        """后缀只剥离一次，不会递归"""
        # '集团股份有限公司' → 剥离 '集团股份有限公司' → ''
        # 但如果长度保护生效，应保留核心部分
        result = normalize_entity_name("美的集团股份有限公司")
        assert result == "美的"  # 剥离 '集团股份有限公司'

    def test_no_suffix_unchanged(self):
        """无后缀的名称不变"""
        assert normalize_entity_name("腾讯") == "腾讯"
        assert normalize_entity_name("百度") == "百度"

    def test_english_suffix(self):
        """英文后缀也应剥离"""
        result = normalize_entity_name("Apple Inc")
        assert result == "apple"

    def test_empty_after_strip_preserved(self):
        """如果剥离后为空，保留原值"""
        result = normalize_entity_name("有限公司")
        assert len(result) > 0  # 不应返回空字符串
```

---

## Claude Code 执行流程

```
Step 1: 创建任务追踪
  → TaskCreate × 6（Patch 1-5 + 测试）

Step 2: Patch 3 — 后缀剥离
  → Read src/entities.py
  → Edit: 添加 _SUFFIX_PATTERN 常量
  → Edit: 重写 normalize_entity_name()
  → Bash: uv run pyright src/entities.py

Step 3: Patch 4 — 倒排索引
  → Edit: resolve_units_with_cache() 添加 name_index / alias_index
  → Edit: 重写 _find_match() 签名和内部逻辑
  → Bash: uv run pyright src/entities.py

Step 4: Patch 1 — 跨语言别名
  → Edit: _find_match() 插入 Layer 1.5
  → Bash: uv run pyright src/entities.py

Step 5: Patch 2 — 类型放宽
  → 确认 Patch 4 的重构已隐式解决（精确匹配路径无类型检查）
  → 无需额外代码

Step 6: Patch 5 — 别名防膨胀
  → Edit: resolve_units_with_cache() 的 else 分支
  → Bash: uv run pyright src/entities.py

Step 7: 测试
  → Write tests/unit/test_entity_resolution.py
  → Bash: uv run pytest tests/unit/test_entity_resolution.py -v
  → Bash: uv run pytest（全量回归）

Step 8: 检索评估（按 retrieval-code.md 规则）
  → Bash: uv run python scripts/eval_report.py --input eval/golden_dataset_v2.json
  → 对比基线指标
```

---

## 风险控制

| 风险 | 缓解措施 |
|------|---------|
| Patch 3 改变 normalize 输出 → 影响 FTS5 分词 | normalize 仅用于实体匹配，不用于 FTS5 索引（需确认） |
| Patch 4 改变 _find_match 签名 → 调用方需同步 | grep 所有调用方，确认仅 resolve_units_with_cache 调用 |
| Patch 1 跨语言字典覆盖不全 | 仅修复合并路径，不扩展字典；字典扩展是独立工作 |
| 别名上限导致信息丢失 | MAX_ALIASES=10 足够覆盖常见变体；canonical_name 不受影响 |
