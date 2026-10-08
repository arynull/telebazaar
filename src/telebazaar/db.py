import sqlite3
from pathlib import Path

SCHEMA_VERSION = "1"


def connect(data_dir) -> sqlite3.Connection:
    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(d / "telebazaar.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS products("
        "id INTEGER PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "description TEXT DEFAULT '', price_minor INTEGER NOT NULL, "
        "currency TEXT DEFAULT 'XTR', photo TEXT DEFAULT '', stock INTEGER DEFAULT 0, "
        "active INTEGER DEFAULT 1, tags TEXT DEFAULT '', created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS customers("
        "tg_id INTEGER PRIMARY KEY, name TEXT DEFAULT '', username TEXT DEFAULT '', "
        "phone TEXT DEFAULT '', created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS carts("
        "tg_id INTEGER PRIMARY KEY, items_json TEXT DEFAULT '[]', updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS orders("
        "id TEXT PRIMARY KEY, customer_tg_id INTEGER NOT NULL, "
        "items_json TEXT NOT NULL, "
        "total_minor INTEGER NOT NULL, currency TEXT DEFAULT 'XTR', "
        "status TEXT NOT NULL, "
        "invoice_payload TEXT DEFAULT '', "
        "telegram_payment_charge_id TEXT DEFAULT '', "
        "created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events("
        "id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref_id TEXT DEFAULT '', "
        "payload_json TEXT DEFAULT '{}', created_at TEXT)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
