import pytest

from telebazaar import store


def _add(conn, sku="SKU-1", price=1000, stock=10, currency="XTR", **kw):
    store.add_product(conn, sku, kw.pop("name", "Widget"), price, currency, stock, **kw)
    return sku


def test_add_product_happy(conn):
    sku = store.add_product(conn, "SKU-1", "Widget", 1500, "XTR", 5, "desc", "a,b")
    assert sku == "SKU-1"
    prod = store.get_product(conn, "SKU-1")
    assert prod["name"] == "Widget"
    assert prod["price_minor"] == 1500
    assert prod["currency"] == "XTR"
    assert prod["stock"] == 5
    assert prod["active"] == 1


def test_add_product_duplicate_sku(conn):
    _add(conn, sku="SKU-1")
    with pytest.raises(ValueError, match="duplicate sku"):
        store.add_product(conn, "SKU-1", "Other", 500)


def test_add_product_negative_price(conn):
    with pytest.raises(ValueError, match="price_minor"):
        store.add_product(conn, "SKU-2", "Widget", -1)


def test_cart_add_happy(conn):
    _add(conn, sku="SKU-1", price=1500, stock=10)
    view = store.cart_add(conn, 111, "SKU-1", 2)
    assert view == [{"sku": "SKU-1", "name": "Widget", "qty": 2, "unit_price": 1500}]


def test_cart_add_insufficient_stock(conn):
    _add(conn, sku="SKU-1", stock=3)
    with pytest.raises(ValueError, match="insufficient stock"):
        store.cart_add(conn, 111, "SKU-1", 4)


def test_create_order_happy_and_stock_decrement(conn):
    _add(conn, sku="SKU-1", price=1500, stock=10)
    oid = store.create_order(conn, 111, [("SKU-1", 3)])
    order = store.get_order(conn, oid)
    assert order["status"] == "pending_payment"
    assert order["total_minor"] == 4500
    assert order["currency"] == "XTR"
    assert order["invoice_payload"] == f"tb:{oid}"
    assert store.get_product(conn, "SKU-1")["stock"] == 7


def test_create_order_mixed_currency_error(conn):
    _add(conn, sku="SKU-1", currency="XTR")
    _add(conn, sku="SKU-2", currency="USD")
    with pytest.raises(ValueError, match="mixed currencies"):
        store.create_order(conn, 111, [("SKU-1", 1), ("SKU-2", 1)])


def test_transition_legal(conn):
    _add(conn, sku="SKU-1", stock=5)
    oid = store.create_order(conn, 111, [("SKU-1", 1)])
    assert store.transition(conn, oid, "paid")["status"] == "paid"
    assert store.transition(conn, oid, "shipped")["status"] == "shipped"


def test_transition_illegal(conn):
    _add(conn, sku="SKU-1", stock=5)
    oid = store.create_order(conn, 111, [("SKU-1", 1)])
    with pytest.raises(store.IllegalTransition, match="not allowed"):
        store.transition(conn, oid, "shipped")


def test_mark_paid_by_payload_happy(conn):
    _add(conn, sku="SKU-1", price=1500, stock=5)
    oid = store.create_order(conn, 111, [("SKU-1", 2)])
    order = store.get_order(conn, oid)
    paid = store.mark_paid_by_payload(
        conn, order["invoice_payload"], "charge-1", order["total_minor"], "XTR"
    )
    assert paid["status"] == "paid"
    assert paid["telegram_payment_charge_id"] == "charge-1"


def test_mark_paid_by_payload_amount_mismatch(conn):
    _add(conn, sku="SKU-1", price=1500, stock=5)
    oid = store.create_order(conn, 111, [("SKU-1", 2)])
    order = store.get_order(conn, oid)
    with pytest.raises(ValueError, match="amount mismatch"):
        store.mark_paid_by_payload(
            conn,
            order["invoice_payload"],
            "charge-1",
            order["total_minor"] + 1,
            "XTR",
        )


def test_upsert_customer_create_and_update(conn):
    created = store.upsert_customer(conn, 555, "Alice", "alice", "111")
    assert created["tg_id"] == 555
    assert created["name"] == "Alice"
    assert created["username"] == "alice"
    assert created["phone"] == "111"

    updated = store.upsert_customer(conn, 555, "Alice B")
    assert updated["tg_id"] == 555
    assert updated["name"] == "Alice B"
    assert updated["username"] == "alice"
    assert updated["phone"] == "111"
