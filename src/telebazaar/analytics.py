"""Read-only analytics over existing orders/products/customers.

Every function is pure: it only reads existing data through the store
helpers and never writes, creates tables, or mutates the database.
"""

import json
from datetime import datetime

from telebazaar import store

PAID_STATUSES = ("paid", "shipped")


def _parse_dt(value):
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _paid_orders(conn) -> list:
    return [o for o in store.list_orders(conn) if o.get("status") in PAID_STATUSES]


def _items(order) -> list:
    try:
        items = json.loads(order.get("items_json") or "[]")
    except (TypeError, ValueError):
        return []
    return items if isinstance(items, list) else []


def summary(conn) -> dict:
    orders = store.list_orders(conn)
    paid = [o for o in orders if o.get("status") in PAID_STATUSES]
    revenue_minor = sum(int(o.get("total_minor", 0) or 0) for o in paid)
    paid_count = len(paid)
    pending_count = sum(1 for o in orders if o.get("status") == "pending_payment")
    return {
        "revenue_minor": revenue_minor,
        "order_count": len(orders),
        "avg_order_value_minor": revenue_minor // paid_count if paid_count else 0,
        "paid_count": paid_count,
        "pending_count": pending_count,
    }


def top_products(conn, limit=5) -> list:
    limit = int(limit)
    if limit < 0:
        limit = 0
    names = {
        p["sku"]: p.get("name", "")
        for p in store.list_products(conn, active_only=False)
    }
    agg: dict[str, dict] = {}
    for order in _paid_orders(conn):
        for item in _items(order):
            sku = item.get("sku")
            if not sku:
                continue
            qty = int(item.get("qty", 0) or 0)
            unit_price = int(item.get("unit_price", 0) or 0)
            entry = agg.setdefault(
                sku,
                {
                    "sku": sku,
                    "name": item.get("name") or names.get(sku, ""),
                    "qty": 0,
                    "revenue_minor": 0,
                },
            )
            entry["qty"] += qty
            entry["revenue_minor"] += qty * unit_price
    rows = sorted(agg.values(), key=lambda r: (-r["qty"], r["sku"]))
    return rows[:limit]


def _bucket_key(dt, by) -> str:
    if by == "week":
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}"
    return dt.date().isoformat()


def revenue(conn, by="day", buckets=14) -> list:
    if by not in ("day", "week"):
        raise ValueError(f"invalid bucket: {by}")
    buckets = int(buckets)
    if buckets <= 0:
        return []
    agg: dict[str, int] = {}
    for order in _paid_orders(conn):
        dt = _parse_dt(order.get("created_at"))
        if dt is None:
            continue
        key = _bucket_key(dt, by)
        agg[key] = agg.get(key, 0) + int(order.get("total_minor", 0) or 0)
    ordered = sorted(agg.items())
    return [
        {"bucket": key, "revenue_minor": total} for key, total in ordered[-buckets:]
    ]


def repeat(conn) -> list:
    agg: dict[int, dict] = {}
    for order in _paid_orders(conn):
        tg_id = int(order.get("customer_tg_id"))
        entry = agg.setdefault(
            tg_id, {"tg_id": tg_id, "orders": 0, "total_spent_minor": 0}
        )
        entry["orders"] += 1
        entry["total_spent_minor"] += int(order.get("total_minor", 0) or 0)
    rows = [r for r in agg.values() if r["orders"] >= 2]
    rows.sort(key=lambda r: (-r["total_spent_minor"], r["tg_id"]))
    return rows
