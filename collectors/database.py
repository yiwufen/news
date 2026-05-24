"""
数据收集器 - 数据库模块

SQLite 数据库操作：建表、插入、查询。
"""

import sqlite3
import json
from pathlib import Path
from typing import Any, Literal


class Database:
    """SQLite 数据库管理类"""

    # 统一字段顺序，避免重复
    ARTICLE_FIELDS = (
        "doc_id", "title", "content", "publish_time",
        "source_name", "source_type", "credibility_tier",
        "category", "raw_tags"
    )

    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        """初始化数据库表结构"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 新闻文章表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    publish_time TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_type TEXT,
                    credibility_tier INTEGER DEFAULT 2,
                    category TEXT NOT NULL,
                    raw_tags TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_publish_time ON news_articles(publish_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_category ON news_articles(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_source ON news_articles(source_name)")

            # 情报微粒表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS intelligence_particles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    particle_id TEXT UNIQUE NOT NULL,
                    slice_window TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_summary TEXT NOT NULL,
                    entities TEXT NOT NULL,
                    source_doc_ids TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_particles_slice ON intelligence_particles(slice_window)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_particles_type ON intelligence_particles(event_type)")

            conn.commit()

    def _prepare_article_data(self, article: dict) -> tuple:
        """准备文章数据元组"""
        return (
            article["doc_id"],
            article["title"],
            article["content"],
            article["publish_time"],
            article["source_name"],
            article.get("source_type"),
            article.get("credibility_tier", 2),
            article["category"],
            json.dumps(article.get("raw_tags", []), ensure_ascii=False)
        )

    def insert_article(self, article: dict) -> int:
        """插入单篇文章，返回行 ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO news_articles ({', '.join(self.ARTICLE_FIELDS)}) VALUES ({', '.join('?' * len(self.ARTICLE_FIELDS))})",
                self._prepare_article_data(article)
            )
            conn.commit()
            return cursor.lastrowid or 0

    def insert_articles_batch(self, articles: list[dict]) -> int:
        """批量插入文章，返回成功数量"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            data = [self._prepare_article_data(a) for a in articles]
            cursor.executemany(
                f"INSERT OR IGNORE INTO news_articles ({', '.join(self.ARTICLE_FIELDS)}) VALUES ({', '.join('?' * len(self.ARTICLE_FIELDS))})",
                data
            )
            conn.commit()
            return cursor.rowcount

    def get_article_count(self) -> int:
        """获取文章总数（轻量级查询）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM news_articles")
            return cursor.fetchone()[0]

    def get_article_by_doc_id(self, doc_id: str) -> dict | None:
        """根据 doc_id 获取文章"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM news_articles WHERE doc_id = ?", (doc_id,))
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None

    def get_all_articles(
        self,
        limit: int | None = None,
        order: Literal["ASC", "DESC"] = "ASC",
    ) -> list[dict]:
        """获取所有文章"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            sql = f"SELECT * FROM news_articles ORDER BY publish_time {order}"
            if limit:
                cursor.execute(f"{sql} LIMIT ?", (limit,))
            else:
                cursor.execute(sql)
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def iter_articles(
        self,
        order: Literal["ASC", "DESC"] = "ASC",
    ):
        """Stream articles one at a time using a server-side cursor."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM news_articles ORDER BY publish_time {order}")
            while True:
                row = cursor.fetchone()
                if row is None:
                    break
                yield self._row_to_dict(row)

    def get_statistics(self) -> dict[str, Any]:
        """获取数据库统计信息"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), MIN(publish_time), MAX(publish_time) FROM news_articles")
            total, min_time, max_time = cursor.fetchone()

            cursor.execute("SELECT category, COUNT(*) FROM news_articles GROUP BY category")
            by_category = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute("SELECT source_name, COUNT(*) FROM news_articles GROUP BY source_name")
            by_source = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                "total_articles": total,
                "by_category": by_category,
                "by_source": by_source,
                "time_range": {"start": min_time, "end": max_time}
            }

    def clear_all(self):
        """清空所有数据"""
        with self._get_connection() as conn:
            conn.cursor().execute("DELETE FROM news_articles")
            conn.cursor().execute("DELETE FROM intelligence_particles")
            conn.commit()

    # === 情报微粒操作 ===

    def insert_particle(self, particle: dict) -> int:
        """插入情报微粒，返回行 ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO intelligence_particles
                   (particle_id, slice_window, event_type, event_summary, entities, source_doc_ids)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    particle["particle_id"],
                    particle["slice_window"],
                    particle["event_type"],
                    particle["event_summary"],
                    json.dumps(particle.get("entities", []), ensure_ascii=False),
                    json.dumps(particle.get("source_doc_ids", []), ensure_ascii=False),
                )
            )
            conn.commit()
            return cursor.lastrowid or 0

    def insert_particles_batch(self, particles: list[dict]) -> int:
        """批量插入情报微粒，返回成功数量"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            data = [
                (
                    p["particle_id"],
                    p["slice_window"],
                    p["event_type"],
                    p["event_summary"],
                    json.dumps(p.get("entities", []), ensure_ascii=False),
                    json.dumps(p.get("source_doc_ids", []), ensure_ascii=False),
                )
                for p in particles
            ]
            cursor.executemany(
                """INSERT OR IGNORE INTO intelligence_particles
                   (particle_id, slice_window, event_type, event_summary, entities, source_doc_ids)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                data
            )
            conn.commit()
            return cursor.rowcount

    def get_particle_count(self) -> int:
        """获取情报微粒总数"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM intelligence_particles")
            return cursor.fetchone()[0]

    def get_particles_by_slice(self, slice_window: str) -> list[dict]:
        """按时间切片获取微粒"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM intelligence_particles WHERE slice_window = ? ORDER BY id",
                (slice_window,)
            )
            return [self._row_to_particle(row) for row in cursor.fetchall()]

    def get_all_particles(self, limit: int | None = None) -> list[dict]:
        """获取所有情报微粒"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            sql = "SELECT * FROM intelligence_particles ORDER BY slice_window DESC"
            if limit:
                cursor.execute(f"{sql} LIMIT ?", (limit,))
            else:
                cursor.execute(sql)
            return [self._row_to_particle(row) for row in cursor.fetchall()]

    def _row_to_particle(self, row: sqlite3.Row) -> dict:
        """将数据库行转换为情报微粒字典"""
        return {
            "id": row["id"],
            "particle_id": row["particle_id"],
            "slice_window": row["slice_window"],
            "event_type": row["event_type"],
            "event_summary": row["event_summary"],
            "entities": json.loads(row["entities"]),
            "source_doc_ids": json.loads(row["source_doc_ids"]),
            "created_at": row["created_at"],
        }

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """将数据库行转换为字典"""
        return {
            "id": row["id"],
            "doc_id": row["doc_id"],
            "title": row["title"],
            "content": row["content"],
            "publish_time": row["publish_time"],
            "source_name": row["source_name"],
            "source_type": row["source_type"],
            "credibility_tier": row["credibility_tier"],
            "category": row["category"],
            "raw_tags": json.loads(row["raw_tags"]) if row["raw_tags"] else [],
            "created_at": row["created_at"]
        }
