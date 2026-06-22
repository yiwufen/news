"""Unit tests for KnowledgeGraphSync.prune_orphans.

These tests use an in-memory fake Neo4j session that records cypher + params
and returns canned results, mirroring the RecordingSession pattern in
tests/integration/test_continuous_pipeline.py. They verify the three prune
paths: edge migration with property union, edge creation on the live node,
re-stamp when the live id is not yet a node, and hard-delete of truly removed
entities.
"""

from __future__ import annotations

from typing import Any

from src.knowledge_graph_sync import KnowledgeGraphSync


class _Result:
    """Minimal stand-in for neo4j.Result exposing .data()."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def data(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeSession:
    """Records every cypher + params pair; returns scripted results.

    The ``responder`` callable maps a query substring to a list of row dicts,
    letting each test shape what prune_orphans sees at each step.
    """

    def __init__(self, responder: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responder = responder

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def run(self, query: str, **params: Any) -> _Result:
        self.calls.append((query, params))
        rows = self._responder(query, params)
        return _Result(rows)


class _FakeConnection:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self) -> _FakeSession:
        return self._session


def _queries_matching(calls: list[tuple[str, dict]], needle: str) -> list[tuple[str, dict]]:
    return [(q, p) for q, p in calls if needle in q]


def test_prune_refuses_empty_live_ids() -> None:
    """An empty live set must refuse rather than wipe the whole graph."""

    class NeverCalledSession(_FakeSession):
        def run(self, query: str, **params: Any) -> _Result:  # pragma: no cover
            raise AssertionError("session.run must not be called on empty live set")

    sync = KnowledgeGraphSync(connection=_FakeConnection(NeverCalledSession(lambda *_: [])))  # type: ignore[arg-type]
    result = sync.prune_orphans([])
    assert result["nodes_deleted"] == 0
    assert result["orphan_count"] == 0
    assert any("empty" in e for e in result["errors"])


def test_prune_migrates_edges_and_merges_when_live_target_exists() -> None:
    """Orphan edges to a cluster the live node also reaches are union-merged."""

    # Scenario: orphan o1 -> cluster c1 (ku=[k1]), live l1 -> c1 (ku=[k2]).
    # After prune: l1's edge carries ku=[k2,k1], orphan o1 is DETACH DELETEd.
    live_ids = ["ent_live_1"]
    name_to_live_id = {"北方稀土": "ent_live_1"}

    def responder(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        # orphan discovery: one orphan whose name resolves to a live node
        # already present in the graph.
        if "NOT o.id IN $live_ids" in query:
            return [{
                "orphan_id": "ent_orphan_1",
                "name": "北方稀土",
                "live_id_in_graph": "ent_live_1",
            }]
        # orphan's outgoing edges
        if "MATCH (o:Entity {id: $orphan_id})-[r:INVOLVED_IN]->(c:EventCluster)" in query:
            return [{"cluster_id": "c1", "member_ku_ids": ["k1"], "source_doc_ids": ["d1"]}]
        # does live node already have an edge to this cluster? yes.
        if "MATCH (live:Entity {id: $live_id})-[r:INVOLVED_IN]->(c:EventCluster {id: $cluster_id})" in query and "RETURN" in query:
            return [{"member_ku_ids": ["k2"], "source_doc_ids": ["d2"]}]
        return []

    session = _FakeSession(responder)
    sync = KnowledgeGraphSync(connection=_FakeConnection(session))
    result = sync.prune_orphans(live_ids, name_to_live_id=name_to_live_id)

    assert result["orphan_count"] == 1
    assert result["nodes_deleted"] == 1
    assert result["edges_merged"] == 1
    assert result["edges_migrated"] == 0
    assert result["errors"] == []

    # The union SET must carry both ku ids (order preserved: live first).
    union_sets = _queries_matching(session.calls, "SET r.member_ku_ids = $member_ku_ids")
    assert union_sets, "expected a union SET on the live edge"
    _, union_params = union_sets[0]
    assert union_params["member_ku_ids"] == ["k2", "k1"]
    assert union_params["source_doc_ids"] == ["d2", "d1"]

    # The orphan node is DETACH DELETEd.
    assert any(
        "DETACH DELETE o" in q and params.get("orphan_id") == "ent_orphan_1"
        for q, params in session.calls
    )


def test_prune_creates_fresh_edge_when_live_node_lacks_it() -> None:
    """Orphan edge to a cluster the live node does NOT reach: create the edge."""

    live_ids = ["ent_live_1"]
    name_to_live_id = {"麦格米特": "ent_live_1"}

    def responder(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if "NOT o.id IN $live_ids" in query:
            return [{
                "orphan_id": "ent_orphan_1",
                "name": "麦格米特",
                "live_id_in_graph": "ent_live_1",
            }]
        if "MATCH (o:Entity {id: $orphan_id})-[r:INVOLVED_IN]->(c:EventCluster)" in query:
            return [{"cluster_id": "c_new", "member_ku_ids": ["k9"], "source_doc_ids": ["d9"]}]
        # live node has NO edge to c_new
        if "MATCH (live:Entity {id: $live_id})-[r:INVOLVED_IN]->(c:EventCluster {id: $cluster_id})" in query and "RETURN" in query:
            return []
        return []

    session = _FakeSession(responder)
    sync = KnowledgeGraphSync(connection=_FakeConnection(session))
    result = sync.prune_orphans(live_ids, name_to_live_id=name_to_live_id)

    assert result["edges_migrated"] == 1
    assert result["edges_merged"] == 0
    assert result["nodes_deleted"] == 1
    # A MERGE edge-create on the live node should have fired.
    creates = _queries_matching(session.calls, "MERGE (live)-[r:INVOLVED_IN]->(c)")
    assert creates
    _, create_params = creates[0]
    assert create_params["member_ku_ids"] == ["k9"]
    assert create_params["source_doc_ids"] == ["d9"]


def test_prune_restamps_orphan_when_live_id_not_in_graph() -> None:
    """Live id known from SQLite but not yet a node: re-stamp the orphan id."""

    live_ids = ["ent_live_new"]
    name_to_live_id = {"长鑫科技": "ent_live_new"}

    def responder(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if "NOT o.id IN $live_ids" in query:
            # live_id_in_graph is None: no same-named node in graph.
            return [{
                "orphan_id": "ent_orphan_old",
                "name": "长鑫科技",
                "live_id_in_graph": None,
            }]
        return []

    session = _FakeSession(responder)
    sync = KnowledgeGraphSync(connection=_FakeConnection(session))
    result = sync.prune_orphans(live_ids, name_to_live_id=name_to_live_id)

    assert result["nodes_deleted"] == 1
    restamps = _queries_matching(session.calls, "SET o.id = $live_id")
    assert restamps
    _, restamp_params = restamps[0]
    assert restamp_params["orphan_id"] == "ent_orphan_old"
    assert restamp_params["live_id"] == "ent_live_new"
    # No DETACH DELETE should have fired for this orphan (re-stamp path).
    assert not any(
        "DETACH DELETE" in q and params.get("orphan_id") == "ent_orphan_old"
        for q, params in session.calls
    )


def test_prune_hard_deletes_truly_removed_entity() -> None:
    """No same-name live entity at all: DETACH DELETE the orphan + edges."""

    live_ids = ["ent_unrelated"]
    # name_to_live_id does NOT contain the orphan's name -> truly deleted.

    def responder(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if "NOT o.id IN $live_ids" in query:
            return [{
                "orphan_id": "ent_gone",
                "name": "宇树科技",
                "live_id_in_graph": None,
            }]
        return []

    session = _FakeSession(responder)
    sync = KnowledgeGraphSync(connection=_FakeConnection(session))
    result = sync.prune_orphans(live_ids)  # no name_to_live_id

    assert result["nodes_deleted"] == 1
    assert result["orphan_count"] == 1
    deletes = _queries_matching(session.calls, "DETACH DELETE o")
    assert any(params.get("orphan_id") == "ent_gone" for _, params in deletes)


def test_prune_collects_errors_without_aborting() -> None:
    """A failing step is recorded; other orphans still processed."""

    live_ids = ["ent_live_1"]
    name_to_live_id = {"A": "ent_live_1"}

    def responder(query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if "NOT o.id IN $live_ids" in query:
            return [
                {"orphan_id": "ent_bad", "name": "A", "live_id_in_graph": "ent_live_1"},
                {"orphan_id": "ent_ok", "name": "A", "live_id_in_graph": "ent_live_1"},
            ]
        # First orphan's edge lookup blows up; second succeeds (empty).
        if "MATCH (o:Entity {id: $orphan_id})-[r:INVOLVED_IN]->(c:EventCluster)" in query:
            if params.get("orphan_id") == "ent_bad":
                raise RuntimeError("boom")
            return []
        return []

    session = _FakeSession(responder)
    sync = KnowledgeGraphSync(connection=_FakeConnection(session))
    result = sync.prune_orphans(live_ids, name_to_live_id=name_to_live_id)

    assert result["orphan_count"] == 2
    # ent_ok still gets cleaned up even though ent_bad errored.
    assert any(
        "DETACH DELETE" in q and params.get("orphan_id") == "ent_ok"
        for q, params in session.calls
    )
    assert any("ent_bad" in e for e in result["errors"])
