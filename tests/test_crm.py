import json

import pytest

from telebazaar import cli, db, store


@pytest.fixture
def run_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEBAZAAR_DATA_DIR", str(tmp_path))

    def _run(*argv):
        return cli.main(list(argv))

    return _run


def _seed(tmp_path):
    conn = db.connect(tmp_path)
    db.migrate(conn)
    store.upsert_customer(conn, 111, "Alice", "alice")
    store.upsert_customer(conn, 222, "Bob", "bob")
    conn.execute(
        "UPDATE customers SET stage='active', tags='vip,repeat' WHERE tg_id=111"
    )
    conn.execute("UPDATE customers SET stage='new', tags='lead' WHERE tg_id=222")
    conn.commit()
    store.add_product(conn, "SKU-1", "Widget", 1500, "XTR", 10)
    store.create_order(conn, 111, [("SKU-1", 2)])
    store.create_order(conn, 111, [("SKU-1", 1)])
    conn.close()


def test_customers_list_happy(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("customers", "list") == 0
    out = capsys.readouterr().out
    assert "111 Alice active vip,repeat" in out
    assert "222 Bob new lead" in out


def test_customers_list_filters(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    run_cli("customers", "list", "--stage", "active")
    out = capsys.readouterr().out
    assert "111" in out
    assert "222" not in out

    run_cli("customers", "list", "--tag", "vip")
    out = capsys.readouterr().out
    assert "111" in out
    assert "222" not in out

    run_cli("customers", "list", "--limit", "1")
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1


def test_customers_show_happy(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("customers", "show", "111") == 0
    prof = json.loads(capsys.readouterr().out)
    assert prof["tg_id"] == 111
    assert prof["name"] == "Alice"
    assert prof["stage"] == "active"
    assert prof["tags"] == "vip,repeat"
    assert prof["order_count"] == 2
    assert prof["total_spent_minor"] == 4500
    assert isinstance(prof["notes"], list)


def test_customers_set_stage_happy(run_cli, tmp_path):
    _seed(tmp_path)
    assert run_cli("customers", "set-stage", "111", "vip") == 0
    conn = db.connect(tmp_path)
    stage = conn.execute("SELECT stage FROM customers WHERE tg_id=111").fetchone()[
        "stage"
    ]
    event = conn.execute(
        "SELECT kind FROM events WHERE kind='customer_stage_set'"
    ).fetchone()
    conn.close()
    assert stage == "vip"
    assert event is not None


def test_customers_set_stage_bad_stage_exit_2(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("customers", "set-stage", "111", "bogus") == 2
    assert "invalid stage: bogus" in capsys.readouterr().err
    conn = db.connect(tmp_path)
    stage = conn.execute("SELECT stage FROM customers WHERE tg_id=111").fetchone()[
        "stage"
    ]
    conn.close()
    assert stage == "active"


def test_customers_tag_happy(run_cli, tmp_path):
    _seed(tmp_path)
    assert run_cli("customers", "tag", "222", "--add", "hot") == 0
    assert run_cli("customers", "tag", "222", "--remove", "lead") == 0
    conn = db.connect(tmp_path)
    tags = conn.execute("SELECT tags FROM customers WHERE tg_id=222").fetchone()["tags"]
    conn.close()
    assert "hot" in tags
    assert "lead" not in tags


def test_customers_note_and_notes(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("customers", "note", "111", "first follow-up") == 0
    assert run_cli("customers", "note", "111", "second call") == 0
    assert run_cli("customers", "notes", "111", "--limit", "1") == 0
    out = capsys.readouterr().out
    assert "second call" in out
    assert "first follow-up" not in out

    conn = db.connect(tmp_path)
    count = conn.execute("SELECT COUNT(*) FROM customer_notes").fetchone()[0]
    event = conn.execute(
        "SELECT kind FROM events WHERE kind='customer_note_added'"
    ).fetchone()
    conn.close()
    assert count == 2
    assert event is not None


def test_customers_segment_happy(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("customers", "segment", "create", "VIPs", "--tag", "vip") == 0
    assert run_cli("customers", "segment", "list") == 0
    out = capsys.readouterr().out
    assert "VIPs" in out

    assert run_cli("customers", "segment", "show", "VIPs") == 0
    seg = json.loads(capsys.readouterr().out)
    assert seg["name"] == "VIPs"
    assert seg["member_count"] == 1
    assert seg["members"][0]["tg_id"] == 111


def test_customers_segment_create_bad_stage_exit_2(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("customers", "segment", "create", "Bad", "--stage", "bogus") == 2
    assert "invalid stage: bogus" in capsys.readouterr().err


def test_customers_unknown_customer_exit_1(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("customers", "show", "999") == 1
    assert "unknown customer" in capsys.readouterr().err
