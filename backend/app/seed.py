from __future__ import annotations
from app.db import connect
from app.services.cutoff_service import DEFAULT_CUTOFF_TIME, POLICY_ROLL


SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tills (
  id INTEGER PRIMARY KEY,
  till_code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cash_lines (
  id INTEGER PRIMARY KEY,
  line_no TEXT NOT NULL UNIQUE,
  till_code TEXT NOT NULL,
  business_day TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  amount REAL NOT NULL,
  pay_method TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  late_flag INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS close_batches (
  id INTEGER PRIMARY KEY,
  batch_no TEXT NOT NULL UNIQUE,
  business_day TEXT NOT NULL,
  system_total REAL NOT NULL,
  declared_cash REAL NOT NULL,
  variance REAL NOT NULL,
  line_count INTEGER NOT NULL,
  status TEXT NOT NULL,
  sealed_at TEXT NOT NULL,
  note TEXT,
  late_count INTEGER NOT NULL DEFAULT 0,
  late_total REAL NOT NULL DEFAULT 0,
  cutoff_time TEXT,
  cutoff_policy TEXT
);
CREATE TABLE IF NOT EXISTS variance_rows (
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL,
  business_day TEXT NOT NULL,
  variance REAL NOT NULL,
  disposition TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS variance_holds (
  id INTEGER PRIMARY KEY,
  business_day TEXT NOT NULL,
  reason TEXT
);
CREATE TABLE IF NOT EXISTS reopen_requests (
  id INTEGER PRIMARY KEY,
  business_day TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'none'
);
'''

# 既有库的轻量迁移：CREATE TABLE IF NOT EXISTS 不会给旧表补列。
MIGRATIONS = (
    "ALTER TABLE cash_lines ADD COLUMN late_flag INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE close_batches ADD COLUMN late_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE close_batches ADD COLUMN late_total REAL NOT NULL DEFAULT 0",
    "ALTER TABLE close_batches ADD COLUMN cutoff_time TEXT",
    "ALTER TABLE close_batches ADD COLUMN cutoff_policy TEXT",
)


def _migrate(conn) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(cash_lines)").fetchall()}
    if "late_flag" not in existing:
        conn.execute(MIGRATIONS[0])
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(close_batches)").fetchall()}
    for ddl, column in (
        (MIGRATIONS[1], "late_count"),
        (MIGRATIONS[2], "late_total"),
        (MIGRATIONS[3], "cutoff_time"),
        (MIGRATIONS[4], "cutoff_policy"),
    ):
        if column not in existing:
            conn.execute(ddl)


def seed_if_empty() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        n = conn.execute("SELECT COUNT(*) c FROM tills").fetchone()["c"]
        if n:
            return
        conn.execute("INSERT INTO settings(key, value) VALUES ('business_day', ?)", ("2026-11-16",))
        conn.execute(
            "INSERT INTO settings(key, value) VALUES ('cutoff_time', ?)", (DEFAULT_CUTOFF_TIME,)
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES ('cutoff_policy', ?)", (POLICY_ROLL,)
        )
        tills = [
            ("TILL-A", "一号收银"),
            ("TILL-B", "二号收银"),
            ("TILL-C", "三号收银"),
        ]
        for code, title in tills:
            conn.execute("INSERT INTO tills(till_code, title) VALUES (?,?)", (code, title))
        lines = [
            ("CL-0001", "TILL-A", "2026-11-16", "2026-11-16T09:12:00Z", 35.5, "现金", "早市"),
            ("CL-0002", "TILL-A", "2026-11-16", "2026-11-16T10:05:00Z", 128.0, "微信", None),
            ("CL-0003", "TILL-B", "2026-11-16", "2026-11-16T11:20:00Z", 66.0, "现金", None),
            ("CL-0004", "TILL-B", "2026-11-16", "2026-11-16T14:02:00Z", 210.0, "支付宝", None),
            ("CL-0005", "TILL-C", "2026-11-16", "2026-11-16T16:40:00Z", 49.9, "现金", None),
            ("CL-0006", "TILL-A", "2026-11-15", "2026-11-15T18:10:00Z", 88.0, "现金", "昨日"),
        ]
        for row in lines:
            conn.execute(
                '''INSERT INTO cash_lines(line_no, till_code, business_day, occurred_at, amount, pay_method, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (*row, row[3]),
            )
        conn.commit()
    finally:
        conn.close()
