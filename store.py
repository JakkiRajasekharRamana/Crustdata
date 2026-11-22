"""SQLite persistence: call ledger, response cache, stage checkpoints (resume), evidence.

One file, no ORM. The DB lives outside OneDrive (PARTNERSCOUT_DB) to avoid sync locks.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")  # note: real env vars (e.g. set by tests) win over .env

DB_PATH = os.environ.get("PARTNERSCOUT_DB") or str(Path(__file__).parent / "data" / "partnerscout.db")

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, created_at REAL, request TEXT, status TEXT, error TEXT
);
-- Every external call, Crustdata and LLM alike (handbook: "model calls included").
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts REAL, service TEXT, endpoint TEXT,
  request_json TEXT, status INTEGER, credits REAL DEFAULT 0, cost_usd REAL DEFAULT 0,
  latency_ms INTEGER, cached INTEGER DEFAULT 0, attempt INTEGER DEFAULT 1, error TEXT
);
-- Raw response cache: re-running a demo costs zero credits and the raw record stays inspectable.
CREATE TABLE IF NOT EXISTS cache (
  key TEXT PRIMARY KEY, endpoint TEXT, fetched_at REAL, response_json TEXT
);
-- Stage checkpoints. A stage with a row is never recomputed: restart-safe, exactly-once.
CREATE TABLE IF NOT EXISTS stages (
  run_id TEXT, stage TEXT, item TEXT, output_json TEXT, ts REAL,
  PRIMARY KEY (run_id, stage, item)
);
CREATE TABLE IF NOT EXISTS evidence (
  claim_id TEXT PRIMARY KEY, run_id TEXT, company_id TEXT, category TEXT, claim TEXT,
  source_url TEXT, source_ref TEXT, quote TEXT, published_at TEXT, retrieved_at TEXT,
  status TEXT, confidence TEXT, agent TEXT, notes TEXT
);
-- Human approvals. Approving records intent only; PartnerScout never contacts anyone.
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, company_id TEXT, action TEXT, ts REAL, note TEXT
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def execute(sql: str, args: tuple = ()) -> sqlite3.Cursor:
    with _lock:
        c = conn().execute(sql, args)
        conn().commit()
        return c


def query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, args).fetchall()


# ---- runs ----
def create_run(run_id: str, request: str) -> None:
    execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?,NULL)", (run_id, time.time(), request, "running"))


def set_run_status(run_id: str, status: str, error: str | None = None) -> None:
    execute("UPDATE runs SET status=?, error=? WHERE run_id=?", (status, error, run_id))


# ---- stage checkpoints ----
def get_stage(run_id: str, stage: str, item: str = "_") -> object | None:
    rows = query("SELECT output_json FROM stages WHERE run_id=? AND stage=? AND item=?", (run_id, stage, item))
    return json.loads(rows[0]["output_json"]) if rows else None


def put_stage(run_id: str, stage: str, output: object, item: str = "_") -> None:
    execute(
        "INSERT OR REPLACE INTO stages VALUES (?,?,?,?,?)",
        (run_id, stage, item, json.dumps(output, default=str), time.time()),
    )


def list_stage(run_id: str, stage: str) -> dict[str, object]:
    rows = query("SELECT item, output_json FROM stages WHERE run_id=? AND stage=?", (run_id, stage))
    return {r["item"]: json.loads(r["output_json"]) for r in rows}


# ---- ledger totals ----
def ledger_totals(run_id: str) -> dict:
    r = query(
        "SELECT COALESCE(SUM(credits),0) c, COALESCE(SUM(cost_usd),0) u, COUNT(*) n, "
        "COALESCE(SUM(cached),0) hits FROM calls WHERE run_id=?",
        (run_id,),
    )[0]
    return {"credits": r["c"], "usd": r["u"], "calls": r["n"], "cache_hits": r["hits"]}
