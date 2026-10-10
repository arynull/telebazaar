import argparse
import contextlib
import json
import sys
from pathlib import Path

from telebazaar import __version__
from telebazaar import config as config_mod
from telebazaar import db as db_mod
from telebazaar import store as store_mod

SAMPLE_CONFIG = 'bot_token = ""\nmerchant_ids = []\n'


def _conn():
    d = config_mod.ensure_dirs()
    conn = db_mod.connect(d)
    db_mod.migrate(conn)
    return conn


def _err(msg) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if n <= 0:
        raise argparse.ArgumentTypeError(
            f"must be a positive integer: {value!r}"
        ) from None
    return n


def cmd_init(args) -> int:
    d = config_mod.ensure_dirs()
    conn = db_mod.connect(d)
    db_mod.migrate(conn)
    conn.close()
    path = Path(d) / "config.toml"
    if not path.exists():
        path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    print(str(d))
    return 0


def cmd_doctor(args) -> int:
    d = config_mod.data_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        writable = "yes"
    except Exception:
        writable = "no"
    print(f"data_dir: {d}")
    print(f"writable: {writable}")
    try:
        conn = db_mod.connect(d)
        db_mod.migrate(conn)
        cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
        row = cur.fetchone()
        ver = row["value"] if row else "unknown"
        conn.close()
    except Exception as e:
        ver = f"error: {e}"
    print(f"schema_version: {ver}")
    cfg = config_mod.load_config()
    token_set = "yes" if cfg.get("bot_token") else "no"
    print(f"token_set: {token_set}")
    print(f"merchant_ids: {len(cfg.get('merchant_ids', []))}")
    return 0


def cmd_catalog_add(args) -> int:
    try:
        conn = _conn()
        store_mod.add_product(
            conn,
            args.sku,
            args.name,
            int(args.price),
            currency=args.currency,
            stock=int(args.stock),
            description=args.description or "",
            tags=args.tags or "",
            photo=args.photo or "",
        )
        conn.close()
    except (ValueError, KeyError) as e:
        return _err(e)
    print(f"added {args.sku}", file=sys.stderr)
    return 0


def cmd_catalog_list(args) -> int:
    conn = _conn()
    products = store_mod.list_products(conn, active_only=not args.all)
    conn.close()
    for p in products:
        print(f"{p['sku']} {p['name']} {p['price_minor']} {p['stock']} {p['active']}")
    return 0


def cmd_catalog_show(args) -> int:
    conn = _conn()
    try:
        p = store_mod.get_product(conn, args.sku)
    except KeyError as e:
        conn.close()
        return _err(e)
    conn.close()
    print(json.dumps(p, indent=2))
    return 0


def cmd_catalog_set_stock(args) -> int:
    conn = _conn()
    try:
        store_mod.set_stock(conn, args.sku, int(args.n))
    except (ValueError, KeyError) as e:
        conn.close()
        return _err(e)
    conn.close()
    return 0


def cmd_catalog_deactivate(args) -> int:
    conn = _conn()
    try:
        store_mod.set_active(conn, args.sku, 0)
    except (ValueError, KeyError) as e:
        conn.close()
        return _err(e)
    conn.close()
    return 0


def cmd_orders_create(args) -> int:
    skus = args.sku or []
    qtys = args.qty or []
    if len(skus) != len(qtys) or not skus:
        return _err("provide matching --sku/--qty pairs")
    try:
        pairs = [(s, int(q)) for s, q in zip(skus, qtys, strict=True)]
    except ValueError:
        return _err("qty must be integer")
    conn = _conn()
    try:
        with contextlib.suppress(Exception):
            store_mod.upsert_customer(conn, int(args.customer), name="", username="")
        oid = store_mod.create_order(conn, int(args.customer), pairs)
    except (ValueError, KeyError) as e:
        conn.close()
        return _err(e)
    finally:
        with contextlib.suppress(Exception):
            conn.close()
    sys.stdout.write(oid + "\n")
    return 0


def cmd_orders_show(args) -> int:
    conn = _conn()
    try:
        order = store_mod.get_order(conn, args.id)
    except KeyError as e:
        conn.close()
        return _err(e)
    conn.close()
    print(json.dumps(order, indent=2))
    return 0


def cmd_orders_list(args) -> int:
    limit = getattr(args, "limit", None)
    conn = _conn()
    if args.status:
        sql = "SELECT * FROM orders WHERE status=? ORDER BY created_at DESC"
        params = (args.status,)
    else:
        sql = "SELECT * FROM orders ORDER BY created_at DESC"
        params = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (*params, limit)
    cur = conn.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        print(f"{r['id']} {r['customer_tg_id']} {r['status']} {r['total_minor']}")
    return 0


def _transition_cmd(order_id, to) -> int:
    conn = _conn()
    try:
        store_mod.transition(conn, order_id, to)
    except (store_mod.IllegalTransition, ValueError, KeyError) as e:
        conn.close()
        return _err(e)
    conn.close()
    print(to, file=sys.stderr)
    return 0


def cmd_bot_run(args) -> int:
    cfg = config_mod.load_config()
    token = config_mod.get_token(cfg)
    if not token:
        print(
            "error: bot token missing. Set TELEBAZAAR_BOT_TOKEN or config.toml",
            file=sys.stderr,
        )
        return 2
    from telebazaar.bot.run import run_bot

    d = config_mod.ensure_dirs()
    return run_bot(token, d, cfg.get("merchant_ids", []))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="telebazaar")
    p.add_argument("--version", action="version", version=f"telebazaar {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("init")
    sp.set_defaults(func=cmd_init)
    sp = sub.add_parser("doctor")
    sp.set_defaults(func=cmd_doctor)
    sp = sub.add_parser("catalog")
    csub = sp.add_subparsers(dest="catalog_cmd", required=True)
    a = csub.add_parser("add")
    a.add_argument("--sku", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--price", required=True)
    a.add_argument("--currency", default="XTR")
    a.add_argument("--stock", default=0)
    a.add_argument("--description", default="")
    a.add_argument("--tags", default="")
    a.add_argument("--photo", default="")
    a.set_defaults(func=cmd_catalog_add)
    a = csub.add_parser("list")
    a.add_argument("--all", action="store_true")
    a.set_defaults(func=cmd_catalog_list)
    a = csub.add_parser("show")
    a.add_argument("sku")
    a.set_defaults(func=cmd_catalog_show)
    a = csub.add_parser("set-stock")
    a.add_argument("sku")
    a.add_argument("n")
    a.set_defaults(func=cmd_catalog_set_stock)
    a = csub.add_parser("deactivate")
    a.add_argument("sku")
    a.set_defaults(func=cmd_catalog_deactivate)
    sp = sub.add_parser("orders")
    osub = sp.add_subparsers(dest="orders_cmd", required=True)
    a = osub.add_parser("create")
    a.add_argument("--customer", required=True)
    a.add_argument("--sku", action="append", default=[])
    a.add_argument("--qty", action="append", default=[])
    a.set_defaults(func=cmd_orders_create)
    a = osub.add_parser("show")
    a.add_argument("id")
    a.set_defaults(func=cmd_orders_show)
    a = osub.add_parser("list")
    a.add_argument("--status", default="")
    a.add_argument("--limit", type=_positive_int, default=None)
    a.set_defaults(func=cmd_orders_list)
    a = osub.add_parser("pay")
    a.add_argument("id")
    a.set_defaults(func=lambda ns: _transition_cmd(ns.id, "paid"))
    a = osub.add_parser("ship")
    a.add_argument("id")
    a.set_defaults(func=lambda ns: _transition_cmd(ns.id, "shipped"))
    a = osub.add_parser("cancel")
    a.add_argument("id")
    a.set_defaults(func=lambda ns: _transition_cmd(ns.id, "cancelled"))
    sp = sub.add_parser("bot")
    bsub = sp.add_subparsers(dest="bot_cmd", required=True)
    a = bsub.add_parser("run")
    a.set_defaults(func=cmd_bot_run)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (store_mod.IllegalTransition, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
