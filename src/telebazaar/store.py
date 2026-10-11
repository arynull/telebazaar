import json
import secrets
from datetime import UTC, datetime

ALLOWED_UPDATE_FIELDS = {
    "name",
    "price_minor",
    "currency",
    "stock",
    "description",
    "tags",
    "photo",
    "active",
}

LEGAL = {
    "pending_payment": {"paid", "cancelled"},
    "paid": {"shipped", "cancelled"},
}


STAGES = ("new", "active", "vip", "dormant", "blocked")


class IllegalTransition(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dict(row) -> dict:
    return dict(row) if row is not None else {}


def log_event(conn, kind, ref_id="", payload=None) -> None:
    if payload is None:
        payload_json = "{}"
    elif isinstance(payload, str):
        payload_json = payload
    else:
        payload_json = json.dumps(payload)
    conn.execute(
        "INSERT INTO events(kind, ref_id, payload_json, created_at) VALUES(?,?,?,?)",
        (kind, str(ref_id or ""), payload_json, _now()),
    )


def add_product(
    conn,
    sku,
    name,
    price_minor,
    currency="XTR",
    stock=0,
    description="",
    tags="",
    photo="",
    active=1,
):
    if not sku or not name:
        raise ValueError("sku and name required")
    if not isinstance(price_minor, int) or price_minor < 0:
        raise ValueError("price_minor must be non-negative int")
    if not isinstance(stock, int) or stock < 0:
        raise ValueError("stock must be non-negative int")
    cur = conn.execute("SELECT id FROM products WHERE sku=?", (sku,))
    if cur.fetchone():
        raise ValueError(f"duplicate sku: {sku}")
    conn.execute(
        "INSERT INTO products(sku,name,description,price_minor,currency,"
        "photo,stock,active,tags,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            sku,
            name,
            description or "",
            int(price_minor),
            currency or "XTR",
            photo or "",
            int(stock),
            int(active),
            tags or "",
            _now(),
        ),
    )
    log_event(conn, "product_added", sku, {"sku": sku})
    conn.commit()
    return sku


def get_product(conn, sku) -> dict:
    cur = conn.execute("SELECT * FROM products WHERE sku=?", (sku,))
    row = cur.fetchone()
    if row is None:
        raise KeyError(f"unknown sku: {sku}")
    return _dict(row)


def update_product(conn, sku, **fields) -> dict:
    get_product(conn, sku)
    sets = []
    vals = []
    for k, v in fields.items():
        if k not in ALLOWED_UPDATE_FIELDS:
            raise ValueError(f"bad field: {k}")
        if k in ("price_minor", "stock") and (not isinstance(v, int) or v < 0):
            raise ValueError(f"{k} must be non-negative int")
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return get_product(conn, sku)
    vals.append(sku)
    # Column names are checked against ALLOWED_UPDATE_FIELDS above and every
    # value is passed as a bound parameter, so this f-string is not injectable.
    conn.execute(
        f"UPDATE products SET {', '.join(sets)} WHERE sku=?",  # nosec
        vals,
    )
    log_event(conn, "product_updated", sku, {"fields": sorted(fields.keys())})
    conn.commit()
    return get_product(conn, sku)


def set_stock(conn, sku, n) -> dict:
    if not isinstance(n, int) or n < 0:
        raise ValueError("stock must be non-negative int")
    return update_product(conn, sku, stock=n)


def set_active(conn, sku, active) -> dict:
    return update_product(conn, sku, active=int(bool(active)))


def list_products(conn, active_only=True) -> list:
    if active_only:
        cur = conn.execute("SELECT * FROM products WHERE active=1 ORDER BY sku")
    else:
        cur = conn.execute("SELECT * FROM products ORDER BY sku")
    return [_dict(r) for r in cur.fetchall()]


def upsert_customer(conn, tg_id, name="", username="", phone="") -> dict:
    tg_id = int(tg_id)
    now = _now()
    cur = conn.execute("SELECT * FROM customers WHERE tg_id=?", (tg_id,))
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO customers(tg_id,name,username,phone,created_at)"
            " VALUES(?,?,?,?,?)",
            (tg_id, name or "", username or "", phone or "", now),
        )
    else:
        conn.execute(
            "UPDATE customers SET name=?, username=?, phone=? WHERE tg_id=?",
            (
                name or row["name"],
                username or row["username"],
                phone or row["phone"],
                tg_id,
            ),
        )
    log_event(conn, "customer_upserted", str(tg_id), {"tg_id": tg_id})
    conn.commit()
    cur = conn.execute("SELECT * FROM customers WHERE tg_id=?", (tg_id,))
    return _dict(cur.fetchone())


def _load_cart(conn, tg_id) -> list:
    cur = conn.execute("SELECT items_json FROM carts WHERE tg_id=?", (int(tg_id),))
    row = cur.fetchone()
    if row is None:
        return []
    try:
        items = json.loads(row["items_json"] or "[]")
    except Exception:
        items = []
    return items if isinstance(items, list) else []


def _save_cart(conn, tg_id, items) -> None:
    conn.execute(
        "INSERT INTO carts(tg_id, items_json, updated_at) VALUES(?,?,?)"
        " ON CONFLICT(tg_id) DO UPDATE SET items_json=excluded.items_json,"
        " updated_at=excluded.updated_at",
        (int(tg_id), json.dumps(items), _now()),
    )


def cart_add(conn, tg_id, sku, qty) -> list:
    qty = int(qty)
    if qty <= 0:
        raise ValueError("qty must be positive")
    prod = get_product(conn, sku)
    if not prod.get("active"):
        raise ValueError("product inactive")
    items = _load_cart(conn, tg_id)
    total = qty
    found = False
    for it in items:
        if it.get("sku") == sku:
            total = int(it.get("qty", 0)) + qty
            found = True
    if int(prod.get("stock", 0)) < total:
        raise ValueError("insufficient stock")
    if found:
        for it in items:
            if it.get("sku") == sku:
                it["qty"] = total
    else:
        items.append({"sku": sku, "qty": qty})
    _save_cart(conn, tg_id, items)
    log_event(conn, "cart_updated", str(tg_id), {"sku": sku, "qty": total})
    conn.commit()
    return cart_view(conn, tg_id)


def cart_view(conn, tg_id) -> list:
    items = _load_cart(conn, tg_id)
    out = []
    for it in items:
        sku = it.get("sku", "")
        qty = int(it.get("qty", 0))
        try:
            prod = get_product(conn, sku)
        except KeyError:
            continue
        out.append(
            {
                "sku": sku,
                "name": prod.get("name", ""),
                "qty": qty,
                "unit_price": int(prod.get("price_minor", 0)),
            }
        )
    return out


def cart_clear(conn, tg_id) -> None:
    _save_cart(conn, tg_id, [])
    log_event(conn, "cart_cleared", str(tg_id), {})
    conn.commit()


def _new_order_id(conn) -> str:
    for _ in range(20):
        oid = secrets.token_hex(6)
        cur = conn.execute("SELECT id FROM orders WHERE id=?", (oid,))
        if not cur.fetchone():
            return oid
    raise ValueError("could not allocate order id")


def create_order(conn, customer_tg_id, items):
    items = list(items)
    if not items:
        raise ValueError("empty order")
    lines = []
    total = 0
    currency = None
    for sku, qty in items:
        qty = int(qty)
        if qty <= 0:
            raise ValueError("qty must be positive")
        prod = get_product(conn, sku)
        if not prod.get("active"):
            raise ValueError(f"inactive product: {sku}")
        if int(prod.get("stock", 0)) < qty:
            raise ValueError(f"insufficient stock: {sku}")
        if currency is None:
            currency = prod.get("currency", "XTR") or "XTR"
        elif (prod.get("currency", "XTR") or "XTR") != currency:
            raise ValueError("mixed currencies")
        total += int(prod.get("price_minor", 0)) * qty
        lines.append(
            {
                "sku": sku,
                "name": prod.get("name", ""),
                "qty": qty,
                "unit_price": int(prod.get("price_minor", 0)),
            }
        )
    oid = _new_order_id(conn)
    payload = f"tb:{oid}"
    now = _now()
    for sku, qty in items:
        conn.execute("UPDATE products SET stock=stock-? WHERE sku=?", (int(qty), sku))
    conn.execute(
        "INSERT INTO orders(id,customer_tg_id,items_json,total_minor,currency,status,"
        "invoice_payload,telegram_payment_charge_id,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            oid,
            int(customer_tg_id),
            json.dumps(lines),
            int(total),
            currency,
            "pending_payment",
            payload,
            "",
            now,
            now,
        ),
    )
    _save_cart(conn, customer_tg_id, [])
    log_event(conn, "order_created", oid, {"total": int(total)})
    conn.commit()
    return oid


def get_order(conn, order_id) -> dict:
    cur = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    row = cur.fetchone()
    if row is None:
        raise KeyError(f"unknown order: {order_id}")
    return _dict(row)


def transition(conn, order_id, to) -> dict:
    order = get_order(conn, order_id)
    cur_status = order.get("status", "")
    allowed = LEGAL.get(cur_status, set())
    if to not in allowed:
        raise IllegalTransition(f"{cur_status} -> {to} not allowed")
    conn.execute(
        "UPDATE orders SET status=?, updated_at=? WHERE id=?", (to, _now(), order_id)
    )
    log_event(conn, "order_transition", order_id, {"from": cur_status, "to": to})
    conn.commit()
    return get_order(conn, order_id)


def mark_paid_by_payload(conn, payload, charge_id, total_amount, currency) -> dict:
    if not isinstance(payload, str) or not payload.startswith("tb:"):
        raise ValueError("bad payload")
    oid = payload[3:]
    if len(oid) != 12:
        raise ValueError("bad payload")
    try:
        int(oid, 16)
    except ValueError:
        raise ValueError("bad payload") from None
    order = get_order(conn, oid)
    if order.get("status") != "pending_payment":
        raise ValueError("order not pending payment")
    if int(total_amount) != int(order.get("total_minor", -1)):
        raise ValueError("amount mismatch")
    if currency and currency != order.get("currency"):
        raise ValueError("currency mismatch")
    conn.execute(
        "UPDATE orders SET status='paid', telegram_payment_charge_id=?,"
        " updated_at=? WHERE id=?",
        (charge_id or "", _now(), oid),
    )
    log_event(conn, "order_paid", oid, {"charge_id": charge_id or ""})
    conn.commit()
    return get_order(conn, oid)


def _normalize_tags(tags) -> list:
    if tags is None:
        return []
    parts = tags.split(",") if isinstance(tags, str) else tags
    out = []
    for t in parts:
        t = str(t).strip()
        if t and t not in out:
            out.append(t)
    return out


def _require_customer(conn, tg_id) -> dict:
    tg_id = int(tg_id)
    cur = conn.execute("SELECT * FROM customers WHERE tg_id=?", (tg_id,))
    row = cur.fetchone()
    if row is None:
        raise KeyError(f"unknown customer: {tg_id}")
    return _dict(row)


def list_customers(conn, stage=None, tag=None, limit=None) -> list:
    sql = "SELECT * FROM customers"
    conds = []
    params: list = []
    if stage:
        conds.append("stage=?")
        params.append(stage)
    if tag:
        conds.append("(',' || tags || ',') LIKE ?")
        params.append(f"%,{tag},%")
    if conds:
        sql = sql + " WHERE " + " AND ".join(conds)
    sql = sql + " ORDER BY tg_id"
    if limit is not None:
        sql = sql + " LIMIT ?"
        params.append(int(limit))
    cur = conn.execute(sql, tuple(params))
    return [_dict(r) for r in cur.fetchall()]


def get_customer_profile(conn, tg_id) -> dict:
    prof = _require_customer(conn, tg_id)
    cur = conn.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(total_minor), 0) AS t"
        " FROM orders WHERE customer_tg_id=?",
        (int(tg_id),),
    )
    agg = cur.fetchone()
    prof["order_count"] = int(agg["c"])
    prof["total_spent_minor"] = int(agg["t"])
    prof["notes"] = list_customer_notes(conn, tg_id)
    return prof


def set_customer_stage(conn, tg_id, stage) -> dict:
    _require_customer(conn, tg_id)
    if stage not in STAGES:
        raise ValueError(f"invalid stage: {stage}")
    tg_id = int(tg_id)
    conn.execute(
        "UPDATE customers SET stage=?, updated_at=? WHERE tg_id=?",
        (stage, _now(), tg_id),
    )
    log_event(conn, "customer_stage_set", str(tg_id), {"stage": stage})
    conn.commit()
    return get_customer_profile(conn, tg_id)


def tag_customer(conn, tg_id, add=None, remove=None) -> dict:
    _require_customer(conn, tg_id)
    tg_id = int(tg_id)
    cur = conn.execute("SELECT tags FROM customers WHERE tg_id=?", (tg_id,))
    tags = _normalize_tags(cur.fetchone()["tags"])
    add_tags = _normalize_tags(add)
    remove_tags = set(_normalize_tags(remove))
    for t in add_tags:
        if t not in tags:
            tags.append(t)
    if remove_tags:
        tags = [t for t in tags if t not in remove_tags]
    conn.execute(
        "UPDATE customers SET tags=?, updated_at=? WHERE tg_id=?",
        (",".join(tags), _now(), tg_id),
    )
    log_event(
        conn,
        "customer_tagged",
        str(tg_id),
        {"add": add_tags, "remove": sorted(remove_tags)},
    )
    conn.commit()
    return _require_customer(conn, tg_id)


def add_customer_note(conn, tg_id, text) -> dict:
    tg_id = int(tg_id)
    text = (text or "").strip()
    if not text:
        raise ValueError("note text required")
    _require_customer(conn, tg_id)
    cur = conn.execute(
        "INSERT INTO customer_notes(tg_id, note, created_at) VALUES(?,?,?)",
        (tg_id, text, _now()),
    )
    note_id = int(cur.lastrowid)
    log_event(conn, "customer_note_added", str(tg_id), {"note": text})
    conn.commit()
    return {"id": note_id, "tg_id": tg_id, "note": text}


def list_customer_notes(conn, tg_id, limit=None) -> list:
    sql = "SELECT * FROM customer_notes WHERE tg_id=? ORDER BY id DESC"
    params: list = [int(tg_id)]
    if limit is not None:
        sql = sql + " LIMIT ?"
        params.append(int(limit))
    cur = conn.execute(sql, tuple(params))
    return [_dict(r) for r in cur.fetchall()]


def _segment_members(conn, seg) -> list:
    return list_customers(
        conn,
        stage=seg.get("stage") or None,
        tag=seg.get("tag") or None,
    )


def create_segment(conn, name, tag="", stage="") -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("segment name required")
    if stage and stage not in STAGES:
        raise ValueError(f"invalid stage: {stage}")
    cur = conn.execute("SELECT name FROM segments WHERE name=?", (name,))
    if cur.fetchone():
        raise ValueError(f"duplicate segment: {name}")
    conn.execute(
        "INSERT INTO segments(name, tag, stage, created_at) VALUES(?,?,?,?)",
        (name, tag or "", stage or "", _now()),
    )
    log_event(conn, "segment_created", name, {"tag": tag or "", "stage": stage or ""})
    conn.commit()
    return get_segment(conn, name)


def list_segments(conn) -> list:
    cur = conn.execute("SELECT * FROM segments ORDER BY name")
    out = []
    for r in cur.fetchall():
        seg = _dict(r)
        seg["member_count"] = len(_segment_members(conn, seg))
        out.append(seg)
    return out


def get_segment(conn, name) -> dict:
    cur = conn.execute("SELECT * FROM segments WHERE name=?", (name,))
    row = cur.fetchone()
    if row is None:
        raise KeyError(f"unknown segment: {name}")
    seg = _dict(row)
    members = _segment_members(conn, seg)
    seg["member_count"] = len(members)
    seg["members"] = members
    return seg
