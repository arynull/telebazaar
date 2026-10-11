from datetime import date

from telebazaar import analytics, cli, store


def _add(conn, sku, price=1000, stock=100, name="Widget"):
    store.add_product(conn, sku, name, price, "XTR", stock)
    return sku


def _order(conn, customer, items, status="paid", created_at=None):
    oid = store.create_order(conn, customer, list(items.items()))
    if status == "shipped":
        store.transition(conn, oid, "paid")
        store.transition(conn, oid, "shipped")
    elif status == "paid":
        store.transition(conn, oid, "paid")
    if created_at is not None:
        conn.execute("UPDATE orders SET created_at=? WHERE id=?", (created_at, oid))
        conn.commit()
    return oid


def test_summary_empty_store_zeros(conn):
    result = analytics.summary(conn)
    assert result == {
        "revenue_minor": 0,
        "order_count": 0,
        "avg_order_value_minor": 0,
        "paid_count": 0,
        "pending_count": 0,
    }
    assert analytics.top_products(conn) == []
    assert analytics.revenue(conn) == []
    assert analytics.repeat(conn) == []


def test_summary_revenue_paid_vs_pending(conn):
    _add(conn, "SKU-1", price=1000)
    _add(conn, "SKU-2", price=2000)
    _order(conn, 111, {"SKU-1": 1}, status="paid")
    _order(conn, 111, {"SKU-2": 1}, status="pending_payment")
    result = analytics.summary(conn)
    assert result["revenue_minor"] == 1000
    assert result["order_count"] == 2
    assert result["avg_order_value_minor"] == 1000
    assert result["paid_count"] == 1
    assert result["pending_count"] == 1


def test_top_products_ordering_and_limit(conn):
    _add(conn, "A", price=100)
    _add(conn, "B", price=200)
    _add(conn, "C", price=300)
    _add(conn, "D", price=400)
    _order(conn, 111, {"A": 1, "B": 2}, status="paid")
    _order(conn, 111, {"B": 1, "C": 2}, status="shipped")
    _order(conn, 222, {"D": 9}, status="pending_payment")
    rows = analytics.top_products(conn)
    assert [r["sku"] for r in rows] == ["B", "C", "A"]
    assert rows[0]["qty"] == 3
    assert rows[0]["revenue_minor"] == 600
    assert analytics.top_products(conn, limit=2) == rows[:2]


def test_revenue_buckets_sum_to_total(conn):
    _add(conn, "SKU-1", price=1000)
    _add(conn, "SKU-2", price=500)
    _order(
        conn,
        111,
        {"SKU-1": 1},
        status="paid",
        created_at="2026-10-05T10:00:00+00:00",
    )
    _order(
        conn,
        222,
        {"SKU-2": 2},
        status="paid",
        created_at="2026-10-06T11:00:00+00:00",
    )
    _order(
        conn,
        222,
        {"SKU-2": 1},
        status="shipped",
        created_at="2026-10-06T12:00:00+00:00",
    )
    _order(
        conn,
        333,
        {"SKU-1": 5},
        status="pending_payment",
        created_at="2026-10-07T13:00:00+00:00",
    )
    total = analytics.summary(conn)["revenue_minor"]
    day_buckets = analytics.revenue(conn, by="day")
    assert sum(b["revenue_minor"] for b in day_buckets) == total == 2500
    assert [b["bucket"] for b in day_buckets] == ["2026-10-05", "2026-10-06"]
    assert [b["revenue_minor"] for b in day_buckets] == [1000, 1500]
    week_buckets = analytics.revenue(conn, by="week")
    assert sum(b["revenue_minor"] for b in week_buckets) == total
    year, week, _ = date(2026, 10, 5).isocalendar()
    assert [b["bucket"] for b in week_buckets] == [f"{year}-W{week:02d}"]
    assert analytics.revenue(conn, by="day", buckets=1) == day_buckets[-1:]


def test_repeat_customers(conn):
    _add(conn, "SKU-1", price=1000)
    _add(conn, "SKU-2", price=2500)
    _order(conn, 111, {"SKU-1": 1}, status="paid")
    _order(conn, 111, {"SKU-2": 1}, status="paid")
    _order(conn, 222, {"SKU-1": 1}, status="paid")
    _order(conn, 222, {"SKU-1": 1}, status="paid")
    _order(conn, 222, {"SKU-1": 1}, status="paid")
    _order(conn, 333, {"SKU-2": 2}, status="paid")
    _order(conn, 444, {"SKU-1": 1}, status="pending_payment")
    _order(conn, 444, {"SKU-1": 1}, status="pending_payment")
    assert analytics.repeat(conn) == [
        {"tg_id": 111, "orders": 2, "total_spent_minor": 3500},
        {"tg_id": 222, "orders": 3, "total_spent_minor": 3000},
    ]


def test_cli_analytics_and_existing_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TELEBAZAAR_DATA_DIR", str(tmp_path))
    assert (
        cli.main(
            [
                "catalog",
                "add",
                "--sku",
                "SKU-1",
                "--name",
                "Widget",
                "--price",
                "1000",
                "--stock",
                "10",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            ["orders", "create", "--customer", "123", "--sku", "SKU-1", "--qty", "2"]
        )
        == 0
    )
    assert cli.main(["orders", "list"]) == 0
    assert cli.main(["analytics", "summary"]) == 0
    assert '"revenue_minor": 0' in capsys.readouterr().out
    assert cli.main(["analytics", "top-products", "--limit", "5"]) == 0
    assert cli.main(["analytics", "revenue", "--by", "day"]) == 0
    assert cli.main(["analytics", "repeat"]) == 0
    capsys.readouterr()
