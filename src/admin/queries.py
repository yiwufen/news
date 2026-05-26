"""Lightweight paginated SQL queries for admin list views.

These queries bypass Pydantic model deserialization for speed on list pages.
Detail endpoints load the full `payload` JSON column.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------


def count_entities(db_path: str) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM entities").fetchone()
        return row["cnt"]


def count_knowledge_units(db_path: str) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM knowledge_units").fetchone()
        return row["cnt"]


def count_event_clusters(db_path: str) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM event_clusters").fetchone()
        return row["cnt"]


def count_articles(db_path: str) -> int:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM news_articles").fetchone()
        return row["cnt"]


# ---------------------------------------------------------------------------
# Paginated list queries
# ---------------------------------------------------------------------------


def paginated_entities(
    db_path: str,
    page: int,
    page_size: int,
    search: str = "",
) -> tuple[int, list[dict[str, Any]]]:
    with _connect(db_path) as conn:
        where = ""
        params: list[Any] = []
        if search:
            where = "WHERE canonical_name LIKE ?"
            params.append(f"%{search}%")

        total = conn.execute(f"SELECT COUNT(*) AS cnt FROM entities {where}", params).fetchone()["cnt"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT entity_id, canonical_name, entity_type, updated_at
            FROM entities {where}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()
        return total, [dict(r) for r in rows]


def paginated_knowledge_units(
    db_path: str,
    page: int,
    page_size: int,
    search: str = "",
    unit_type: str = "",
    entity_id: str = "",
) -> tuple[int, list[dict[str, Any]]]:
    with _connect(db_path) as conn:
        clauses: list[str] = []
        params: list[Any] = []

        if search:
            clauses.append("summary LIKE ?")
            params.append(f"%{search}%")
        if unit_type:
            clauses.append("unit_type = ?")
            params.append(unit_type)
        if entity_id:
            clauses.append("entity_ids LIKE ?")
            params.append(f'%"{entity_id}"%')

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        total = conn.execute(f"SELECT COUNT(*) AS cnt FROM knowledge_units {where}", params).fetchone()["cnt"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT ku_id, unit_kind, unit_type, summary, published_at, conflict_status, status
            FROM knowledge_units {where}
            ORDER BY published_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()
        return total, [dict(r) for r in rows]


def paginated_event_clusters(
    db_path: str,
    page: int,
    page_size: int,
    cluster_type: str = "",
    entity_id: str = "",
) -> tuple[int, list[dict[str, Any]]]:
    import json

    with _connect(db_path) as conn:
        clauses: list[str] = []
        params: list[Any] = []

        if cluster_type:
            clauses.append("cluster_type = ?")
            params.append(cluster_type)
        if entity_id:
            # Search in cluster_entity_map for the entity
            clauses.append(
                "cluster_id IN (SELECT cluster_id FROM cluster_entity_map WHERE entity_id = ?)"
            )
            params.append(entity_id)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        total = conn.execute(f"SELECT COUNT(*) AS cnt FROM event_clusters {where}", params).fetchone()["cnt"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT cluster_id, cluster_type, conflict_status, updated_at, payload
            FROM event_clusters {where}
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()

        items = []
        for r in rows:
            payload = json.loads(r["payload"])
            items.append({
                "cluster_id": r["cluster_id"],
                "cluster_type": r["cluster_type"],
                "title": payload.get("title", ""),
                "member_count": payload.get("member_count", 0),
                "source_count": payload.get("source_count", 0),
                "conflict_status": r["conflict_status"],
                "updated_at": r["updated_at"],
            })
        return total, items


def paginated_articles(
    db_path: str,
    page: int,
    page_size: int,
    search: str = "",
    category: str = "",
    source_name: str = "",
) -> tuple[int, list[dict[str, Any]]]:
    with _connect(db_path) as conn:
        clauses: list[str] = []
        params: list[Any] = []

        if search:
            clauses.append("title LIKE ?")
            params.append(f"%{search}%")
        if category:
            clauses.append("category = ?")
            params.append(category)
        if source_name:
            clauses.append("source_name = ?")
            params.append(source_name)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        total = conn.execute(f"SELECT COUNT(*) AS cnt FROM news_articles {where}", params).fetchone()["cnt"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT id, doc_id, title, publish_time, source_name, category, credibility_tier
            FROM news_articles {where}
            ORDER BY publish_time DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()
        return total, [dict(r) for r in rows]


def paginated_processing_log(
    db_path: str,
    page: int,
    page_size: int,
) -> tuple[int, list[dict[str, Any]]]:
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM knowledge_processing_log").fetchone()["cnt"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            """
            SELECT doc_id, status, knowledge_units_count, entities_count, clusters_count,
                   error_message, updated_at
            FROM knowledge_processing_log
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            [page_size, offset],
        ).fetchall()
        return total, [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Detail queries (load full payload / row)
# ---------------------------------------------------------------------------


def get_entity_detail(db_path: str, entity_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT payload FROM entities WHERE entity_id = ?", [entity_id]).fetchone()
        if not row:
            return None
        import json
        return json.loads(row["payload"])


def get_ku_detail(db_path: str, ku_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT payload FROM knowledge_units WHERE ku_id = ?", [ku_id]).fetchone()
        if not row:
            return None
        import json
        return json.loads(row["payload"])


def get_cluster_detail(db_path: str, cluster_id: str) -> dict[str, Any] | None:
    import json

    with _connect(db_path) as conn:
        row = conn.execute("SELECT payload FROM event_clusters WHERE cluster_id = ?", [cluster_id]).fetchone()
        if not row:
            return None
        return json.loads(row["payload"])


def get_article_detail(db_path: str, doc_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM news_articles WHERE doc_id = ?", [doc_id]).fetchone()
        if not row:
            return None
        return dict(row)


# ---------------------------------------------------------------------------
# Cross-reference queries
# ---------------------------------------------------------------------------


def get_ku_related_entities(db_path: str, ku_id: str) -> list[dict[str, Any]]:
    """Return entities referenced by a knowledge unit via its entity_ids JSON column."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT entity_ids FROM knowledge_units WHERE ku_id = ?", [ku_id]).fetchone()
        if not row:
            return []
        import json
        try:
            ids = json.loads(row["entity_ids"])
        except (TypeError, json.JSONDecodeError):
            return []
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        rows = conn.execute(
            f"""SELECT e.entity_id, e.canonical_name, e.entity_type
                FROM entities e WHERE e.entity_id IN ({placeholders})""",
            ids,
        ).fetchall()
        return [dict(r) for r in rows]


def get_entity_related_kus(
    db_path: str, entity_id: str, page: int, page_size: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Return knowledge units that reference a given entity."""
    with _connect(db_path) as conn:
        total = conn.execute(
            """SELECT COUNT(*) AS cnt FROM knowledge_units ku, json_each(ku.entity_ids) je
               WHERE je.value = ?""",
            [entity_id],
        ).fetchone()["cnt"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            """SELECT ku.ku_id, ku.unit_type, ku.unit_kind, ku.summary, ku.published_at, ku.conflict_status
               FROM knowledge_units ku, json_each(ku.entity_ids) je
               WHERE je.value = ?
               ORDER BY ku.published_at DESC
               LIMIT ? OFFSET ?""",
            [entity_id, page_size, offset],
        ).fetchall()
        return total, [dict(r) for r in rows]


def get_entity_related_clusters(
    db_path: str, entity_id: str, page: int, page_size: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Return event clusters that involve a given entity."""
    import json
    with _connect(db_path) as conn:
        total = conn.execute(
            """SELECT COUNT(*) AS cnt FROM cluster_entity_map WHERE entity_id = ?""",
            [entity_id],
        ).fetchone()["cnt"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            """SELECT ec.cluster_id, ec.cluster_type, ec.conflict_status, ec.updated_at, ec.payload
               FROM event_clusters ec
               JOIN cluster_entity_map cem ON ec.cluster_id = cem.cluster_id
               WHERE cem.entity_id = ?
               ORDER BY ec.updated_at DESC
               LIMIT ? OFFSET ?""",
            [entity_id, page_size, offset],
        ).fetchall()

        items = []
        for r in rows:
            payload = json.loads(r["payload"])
            items.append({
                "cluster_id": r["cluster_id"],
                "cluster_type": r["cluster_type"],
                "title": payload.get("title", ""),
                "member_count": payload.get("member_count", 0),
                "conflict_status": r["conflict_status"],
                "updated_at": r["updated_at"],
            })
        return total, items


def get_cluster_member_kus(
    db_path: str, cluster_id: str, page: int, page_size: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Return knowledge units that belong to a given cluster."""
    with _connect(db_path) as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM knowledge_units WHERE cluster_id = ?",
            [cluster_id],
        ).fetchone()["cnt"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            """SELECT ku_id, unit_type, unit_kind, summary, published_at, conflict_status
               FROM knowledge_units
               WHERE cluster_id = ?
               ORDER BY published_at DESC
               LIMIT ? OFFSET ?""",
            [cluster_id, page_size, offset],
        ).fetchall()
        return total, [dict(r) for r in rows]


def get_cluster_related_entities(db_path: str, cluster_id: str) -> list[dict[str, Any]]:
    """Return entities associated with a given cluster."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT e.entity_id, e.canonical_name, e.entity_type
               FROM entities e
               JOIN cluster_entity_map cem ON e.entity_id = cem.entity_id
               WHERE cem.cluster_id = ?""",
            [cluster_id],
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Dashboard / stats
# ---------------------------------------------------------------------------


def get_entity_type_counts(db_path: str) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT entity_type, COUNT(*) AS cnt FROM entities GROUP BY entity_type ORDER BY cnt DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_ku_kind_counts(db_path: str) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT unit_kind, COUNT(*) AS cnt FROM knowledge_units GROUP BY unit_kind"
        ).fetchall()
        return [dict(r) for r in rows]


def get_article_category_counts(db_path: str) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS cnt FROM news_articles GROUP BY category ORDER BY cnt DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_article_time_range(db_path: str) -> dict[str, str | None]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT MIN(publish_time) AS start, MAX(publish_time) AS end FROM news_articles"
        ).fetchone()
        return {"start": row["start"], "end": row["end"]}


def get_processing_summary(db_path: str) -> dict[str, Any]:
    with _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS cnt FROM knowledge_processing_log WHERE status = 'processed'").fetchone()["cnt"]
        failed = conn.execute("SELECT COUNT(*) AS cnt FROM knowledge_processing_log WHERE status = 'failed'").fetchone()["cnt"]
        pending = conn.execute("SELECT COUNT(*) AS cnt FROM knowledge_processing_log WHERE status = 'pending'").fetchone()["cnt"]
        last = conn.execute(
            "SELECT updated_at FROM knowledge_processing_log WHERE status = 'processed' ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return {
            "total_processed": total,
            "total_failed": failed,
            "total_pending": pending,
            "last_processed_at": last["updated_at"] if last else None,
        }
