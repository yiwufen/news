"""Tests for UnitType closed-set normalization (32-class financial taxonomy).

Covers the removal of the legacy ``announcement``/``other`` buckets and the
addition of ``shareholding_change``/``rating_change``/``strategic_cooperation``/
``disclosure``/``non_financial``. See ``docs/graph_edge_design.md`` §3.
"""

from __future__ import annotations

import pytest

from src.schemas.enums import (
    UnitType,
    _CANONICAL_VALUES,
    derive_edge_nature,
    derive_edge_scope,
    is_known_unit_type,
    normalize_relation_type,
    normalize_unit_type,
)


class TestClosedSetShape:
    """The closed set must be exactly 32 members, with no buckets."""

    def test_member_count_is_32(self) -> None:
        assert len(list(UnitType)) == 32

    def test_no_announcement_member(self) -> None:
        assert not hasattr(UnitType, "ANNOUNCEMENT")
        assert "announcement" not in _CANONICAL_VALUES

    def test_no_other_member(self) -> None:
        assert not hasattr(UnitType, "OTHER")
        assert "other" not in _CANONICAL_VALUES

    @pytest.mark.parametrize(
        "name,value",
        [
            ("SHAREHOLDING_CHANGE", "shareholding_change"),
            ("RATING_CHANGE", "rating_change"),
            ("STRATEGIC_COOPERATION", "strategic_cooperation"),
            ("DISCLOSURE", "disclosure"),
            ("NON_FINANCIAL", "non_financial"),
        ],
    )
    def test_new_members_exist(self, name: str, value: str) -> None:
        assert hasattr(UnitType, name)
        assert UnitType[name].value == value


class TestNormalizeExactCanonical:
    """Every canonical value round-trips through normalize_unit_type."""

    @pytest.mark.parametrize("ut", list(UnitType))
    def test_canonical_round_trip(self, ut: UnitType) -> None:
        assert normalize_unit_type(ut.value) is ut


class TestNormalizeAliases:
    """Aliases resolve to the right canonical type."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # shareholding_change — the key correction from investment
            ("减持", UnitType.SHAREHOLDING_CHANGE),
            ("增持", UnitType.SHAREHOLDING_CHANGE),
            ("大宗交易", UnitType.SHAREHOLDING_CHANGE),
            ("配售", UnitType.SHAREHOLDING_CHANGE),
            # legacy announcement aliases now route to disclosure
            ("公告", UnitType.DISCLOSURE),
            ("声明", UnitType.DISCLOSURE),
            ("澄清", UnitType.DISCLOSURE),
            ("停牌", UnitType.DISCLOSURE),
            # rating_change
            ("目标价", UnitType.RATING_CHANGE),
            ("评级调整", UnitType.RATING_CHANGE),
            ("首次覆盖", UnitType.RATING_CHANGE),
            # strategic_cooperation
            ("战略合作", UnitType.STRATEGIC_COOPERATION),
            ("签署协议", UnitType.STRATEGIC_COOPERATION),
            ("签约", UnitType.STRATEGIC_COOPERATION),
            # legacy canonical strings still work
            ("财务业绩", UnitType.FINANCIAL_PERFORMANCE),
            ("资产重组", UnitType.RESTRUCTURING),
            ("投资", UnitType.INVESTMENT),
            ("股权质押", UnitType.EQUITY_PLEDGE),
        ],
    )
    def test_alias_resolution(self, raw: str, expected: UnitType) -> None:
        assert normalize_unit_type(raw) is expected

    def test_legacy_announcement_string_routes_to_disclosure(self) -> None:
        """The exact legacy canonical value 'announcement' must not raise and
        must land on disclosure (its bucket role is gone)."""
        assert normalize_unit_type("announcement") is UnitType.DISCLOSURE

    def test_legacy_other_string_routes_to_disclosure(self) -> None:
        assert normalize_unit_type("other") is UnitType.DISCLOSURE


class TestNormalizeKeywordFallback:
    """Substring keyword matching still works for noisy LLM output."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("某公司股东减持股份", UnitType.SHAREHOLDING_CHANGE),
            ("机构下调评级", UnitType.RATING_CHANGE),
            ("双方签署协议", UnitType.STRATEGIC_COOPERATION),
            ("公司澄清传闻", UnitType.DISCLOSURE),
        ],
    )
    def test_keyword_match(self, raw: str, expected: UnitType) -> None:
        assert normalize_unit_type(raw) is expected


class TestNormalizeUnrecognisedFallback:
    """Unrecognised values fall back to disclosure, NOT to a removed bucket."""

    def test_unknown_string_falls_back_to_disclosure(self) -> None:
        assert normalize_unit_type("totally_unknown_xyz") is UnitType.DISCLOSURE

    def test_empty_string_falls_back_to_disclosure(self) -> None:
        assert normalize_unit_type("") is UnitType.DISCLOSURE

    def test_whitespace_falls_back_to_disclosure(self) -> None:
        assert normalize_unit_type("   ") is UnitType.DISCLOSURE


class TestIsKnownUnitType:
    """is_known_unit_type distinguishes real matches from the disclosure fallback."""

    @pytest.mark.parametrize(
        "raw",
        [
            "financial_performance",
            "减持",
            "目标价",
            "投资",
            "澄清",
        ],
    )
    def test_known_terms_are_true(self, raw: str) -> None:
        assert is_known_unit_type(raw) is True

    @pytest.mark.parametrize("raw", ["", "   ", "totally_unknown_xyz", "胡乱词"])
    def test_unknown_terms_are_false(self, raw: str) -> None:
        assert is_known_unit_type(raw) is False


class TestKeywordOrdering:
    """shareholding_change keywords must take priority over investment's '持'."""

    def test_zhichang_not_mismatched_to_investment(self) -> None:
        # '减持' contains no '投资', but guard against future regressions
        assert normalize_unit_type("减持计划公告") is UnitType.SHAREHOLDING_CHANGE


class TestDeriveEdgeScope:
    """derive_edge_scope — the coarse "whose affair" filter for multi-hop."""

    @pytest.mark.parametrize("et", ["Company", "Product"])
    def test_corporate_types(self, et: str) -> None:
        assert derive_edge_scope(et) == "corporate"

    @pytest.mark.parametrize("et", ["Organization", "Person", "Asset", "Unknown"])
    def test_environment_types(self, et: str) -> None:
        assert derive_edge_scope(et) == "environment"

    def test_none_is_environment(self) -> None:
        # admin path may pass partial entities; missing type must not crash
        assert derive_edge_scope(None) == "environment"


class TestDeriveEdgeNature:
    """derive_edge_nature — action vs reaction for causal-chain pruning."""

    @pytest.mark.parametrize(
        "ct",
        [
            "stock_price_change",
            "price_change",
            "sector_performance",
            "market_analysis",
            "industry_analysis",
            "rating_change",
        ],
    )
    def test_reaction_types(self, ct: str) -> None:
        assert derive_edge_nature(ct) == "reaction"

    @pytest.mark.parametrize(
        "ct",
        [
            "financial_performance",
            "investment",
            "restructuring",
            "regulatory_action",
            "debt_default",
            "policy_announcement",
            "military_action",
        ],
    )
    def test_action_types(self, ct: str) -> None:
        assert derive_edge_nature(ct) == "action"

    def test_unknown_type_defaults_to_action(self) -> None:
        # An unrecognised cluster_type is treated as an action (happened),
        # not silently dropped as a reaction.
        assert derive_edge_nature("totally_unknown") == "action"


class TestNormalizeRelationType:
    """normalize_relation_type — free-text relation_type → direct edge (type, subtype).

    Stable structural relations map to one of OWNERSHIP/GOVERNANCE/COMMERCIAL/RISK;
    one-off events return (None, None) and stay in EventCluster.
    """

    @pytest.mark.parametrize(
        "raw,edge_type,subtype",
        [
            ("控股", "OWNERSHIP", "股权控制"),
            ("增持", "OWNERSHIP", "股权变动"),
            ("减持", "OWNERSHIP", "股权变动"),
            ("高管任职", "GOVERNANCE", "任职"),
            ("监管", "GOVERNANCE", "监管"),
            ("合作", "COMMERCIAL", "合作"),
            ("投资", "COMMERCIAL", "投资"),
            ("供应", "COMMERCIAL", "供应"),
            ("并购", "COMMERCIAL", "并购"),
            ("收购", "COMMERCIAL", "收购"),
            ("竞争", "RISK", "竞争"),
            ("诉讼", "RISK", "诉讼"),
            ("制裁", "RISK", "制裁"),
            ("处罚", "RISK", "处罚"),
        ],
    )
    def test_stable_relations_map_to_direct_edge(
        self, raw: str, edge_type: str, subtype: str
    ) -> None:
        result = normalize_relation_type(raw)
        assert result == (edge_type, subtype)

    @pytest.mark.parametrize("raw", ["袭击", "签署", "谴责", "威胁", "反对"])
    def test_one_off_events_return_none(self, raw: str) -> None:
        # These must NOT become direct edges — they stay as events.
        assert normalize_relation_type(raw) == (None, None)

    @pytest.mark.parametrize("raw", ["", "   ", "未知关系", "totally_unknown"])
    def test_unknown_or_empty_returns_none(self, raw: str) -> None:
        # Conservative: when in doubt, don't create a direct edge.
        assert normalize_relation_type(raw) == (None, None)

    def test_whitespace_is_stripped(self) -> None:
        assert normalize_relation_type(" 控股 ") == ("OWNERSHIP", "股权控制")

    def test_all_four_edge_types_are_covered(self) -> None:
        """Sanity: each of the 4 direct-edge types has at least one mapping."""
        from src.schemas.enums import _RELATION_TYPE_TO_DIRECT_EDGE

        covered = {
            mapped[0] for mapped in _RELATION_TYPE_TO_DIRECT_EDGE.values() if mapped
        }
        assert covered == {"OWNERSHIP", "GOVERNANCE", "COMMERCIAL", "RISK"}
