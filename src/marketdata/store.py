"""marketdata SQLite 存储。

独立于知识库的 ``data/market.db``：缓存性质、可丢弃重建。WAL 模式 +
短连接（每次操作新开连接），避免多线程共享连接的锁问题。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.marketdata.models import Instrument, KlineBar, Quote

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
    secid      TEXT PRIMARY KEY,
    symbol     TEXT NOT NULL,
    market     INTEGER NOT NULL,
    name       TEXT NOT NULL,
    pinyin     TEXT,
    asset_type TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_instruments_symbol ON instruments(symbol);
CREATE INDEX IF NOT EXISTS idx_instruments_name ON instruments(name);

CREATE TABLE IF NOT EXISTS quote_snapshot (
    secid       TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    name        TEXT NOT NULL,
    price       REAL, change_val REAL, change_pct REAL,
    open        REAL, high REAL, low REAL, pre_close REAL,
    volume      REAL, amount REAL,
    market_time TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    source      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kline_daily (
    secid      TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open  REAL NOT NULL,
    high  REAL NOT NULL,
    low   REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    amount REAL NOT NULL,
    PRIMARY KEY (secid, trade_date)
);
"""

UNIVERSE_SYNC_KEY = "universe_synced_at"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MarketStore:
    """market.db 的同步存取层；异步调用方需自行下放线程。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # meta
    # ------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, value),
            )

    # ------------------------------------------------------------------
    # instruments
    # ------------------------------------------------------------------

    def replace_instruments(self, items: list[Instrument]) -> int:
        """全量替换主数据（原子），并记录同步时间。"""
        now = _now_iso()
        with self._connect() as conn:
            conn.execute("DELETE FROM instruments")
            conn.executemany(
                "INSERT INTO instruments"
                " (secid, symbol, market, name, pinyin, asset_type, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        i.secid,
                        i.symbol,
                        i.market,
                        i.name,
                        i.pinyin,
                        i.asset_type,
                        now,
                    )
                    for i in items
                ],
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (UNIVERSE_SYNC_KEY, now),
            )
        return len(items)

    def upsert_instrument(self, item: Instrument) -> None:
        """suggest 兜底命中后回写，让下次解析走本地。"""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO instruments"
                " (secid, symbol, market, name, pinyin, asset_type, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    item.secid,
                    item.symbol,
                    item.market,
                    item.name,
                    item.pinyin,
                    item.asset_type,
                    _now_iso(),
                ),
            )

    def get_instrument(self, secid: str) -> Instrument | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT secid, symbol, market, name, pinyin, asset_type"
                " FROM instruments WHERE secid = ?",
                (secid,),
            ).fetchone()
        return _row_to_instrument(row) if row else None

    def find_by_symbol(self, symbol: str) -> list[Instrument]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT secid, symbol, market, name, pinyin, asset_type"
                " FROM instruments WHERE symbol = ? ORDER BY asset_type, secid",
                (symbol,),
            ).fetchall()
        return [_row_to_instrument(r) for r in rows]

    def find_by_name(self, name: str) -> list[Instrument]:
        """精确名 + 包含名两段检索，精确命中优先。"""
        with self._connect() as conn:
            exact = conn.execute(
                "SELECT secid, symbol, market, name, pinyin, asset_type"
                " FROM instruments WHERE name = ? ORDER BY asset_type, secid",
                (name,),
            ).fetchall()
            if exact:
                return [_row_to_instrument(r) for r in exact]
            like = conn.execute(
                "SELECT secid, symbol, market, name, pinyin, asset_type"
                " FROM instruments WHERE name LIKE ?"
                " ORDER BY LENGTH(name), asset_type, secid LIMIT ?",
                (f"%{name}%", 20),
            ).fetchall()
        return [_row_to_instrument(r) for r in like]

    def find_by_pinyin_prefix(self, prefix: str) -> list[Instrument]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT secid, symbol, market, name, pinyin, asset_type"
                " FROM instruments WHERE pinyin LIKE ?"
                " ORDER BY asset_type, secid LIMIT 20",
                (f"{prefix}%",),
            ).fetchall()
        return [_row_to_instrument(r) for r in rows]

    def count_instruments(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # quote_snapshot
    # ------------------------------------------------------------------

    def upsert_snapshots(self, quotes: list[Quote]) -> None:
        now = _now_iso()
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO quote_snapshot"
                " (secid, symbol, name, price, change_val, change_pct, open,"
                "  high, low, pre_close, volume, amount, market_time,"
                "  fetched_at, source)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        q.secid,
                        q.symbol,
                        q.name,
                        q.price,
                        q.change,
                        q.change_pct,
                        q.open,
                        q.high,
                        q.low,
                        q.pre_close,
                        q.volume,
                        q.amount,
                        q.market_time.isoformat(),
                        now,
                        q.source,
                    )
                    for q in quotes
                ],
            )

    def get_snapshots(self, secids: list[str]) -> dict[str, dict[str, object]]:
        if not secids:
            return {}
        placeholders = ",".join("?" for _ in secids)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT secid, symbol, name, price, change_val, change_pct,"
                " open, high, low, pre_close, volume, amount, market_time,"
                " fetched_at, source FROM quote_snapshot"
                f" WHERE secid IN ({placeholders})",
                secids,
            ).fetchall()
        result: dict[str, dict[str, object]] = {}
        for r in rows:
            result[r[0]] = {
                "secid": r[0],
                "symbol": r[1],
                "name": r[2],
                "price": r[3],
                "change": r[4],
                "change_pct": r[5],
                "open": r[6],
                "high": r[7],
                "low": r[8],
                "pre_close": r[9],
                "volume": r[10],
                "amount": r[11],
                "market_time": r[12],
                "fetched_at": r[13],
                "source": r[14],
                "stale": True,  # 快照表读出的一律视为可能过期
                "as_of": r[12],  # 数据时间（交易所行情时间）
            }
        return result

    # ------------------------------------------------------------------
    # kline_daily
    # ------------------------------------------------------------------

    def insert_klines(self, bars: list[KlineBar]) -> int:
        """只插入本地缺失的日期（主键冲突忽略），返回新插入行数。"""
        if not bars:
            return 0
        with self._connect() as conn:
            cur = conn.executemany(
                "INSERT OR IGNORE INTO kline_daily"
                " (secid, trade_date, open, high, low, close, volume, amount)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        b.secid,
                        b.trade_date,
                        b.open,
                        b.high,
                        b.low,
                        b.close,
                        b.volume,
                        b.amount,
                    )
                    for b in bars
                ],
            )
            return cur.rowcount

    def replace_klines(self, secid: str, bars: list[KlineBar]) -> None:
        """除权重拉时整段替换该 secid 的日K。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM kline_daily WHERE secid = ?", (secid,))
            conn.executemany(
                "INSERT OR REPLACE INTO kline_daily"
                " (secid, trade_date, open, high, low, close, volume, amount)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        b.secid,
                        b.trade_date,
                        b.open,
                        b.high,
                        b.low,
                        b.close,
                        b.volume,
                        b.amount,
                    )
                    for b in bars
                ],
            )

    def select_klines(
        self, secid: str, start: str | None = None, end: str | None = None
    ) -> list[KlineBar]:
        """升序返回区间内日K；不限区间时返回全部。"""
        clauses = ["secid = ?"]
        params: list[object] = [secid]
        if start:
            clauses.append("trade_date >= ?")
            params.append(start)
        if end:
            clauses.append("trade_date <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT secid, trade_date, open, high, low, close, volume,"
                f" amount FROM kline_daily WHERE {where} ORDER BY trade_date",
                params,
            ).fetchall()
        return [
            KlineBar(
                secid=r[0],
                trade_date=r[1],
                open=r[2],
                high=r[3],
                low=r[4],
                close=r[5],
                volume=r[6],
                amount=r[7],
            )
            for r in rows
        ]

    def max_kline_date(self, secid: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(trade_date) FROM kline_daily WHERE secid = ?",
                (secid,),
            ).fetchone()
        return row[0] if row and row[0] else None

    def tail_klines(self, secid: str, n: int = 2) -> list[KlineBar]:
        """最近 n 根（升序返回），供增量合并时的除权比对。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT secid, trade_date, open, high, low, close, volume,"
                " amount FROM kline_daily WHERE secid = ?"
                " ORDER BY trade_date DESC LIMIT ?",
                (secid, n),
            ).fetchall()
        bars = [
            KlineBar(
                secid=r[0],
                trade_date=r[1],
                open=r[2],
                high=r[3],
                low=r[4],
                close=r[5],
                volume=r[6],
                amount=r[7],
            )
            for r in rows
        ]
        return list(reversed(bars))


def _row_to_instrument(r: tuple) -> Instrument:
    return Instrument(
        secid=r[0],
        symbol=r[1],
        market=int(r[2]),
        name=r[3],
        pinyin=r[4],
        asset_type=r[5],
    )
