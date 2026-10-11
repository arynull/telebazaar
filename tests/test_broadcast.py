import pytest

from telebazaar import broadcast as broadcast_mod
from telebazaar import cli, db, store
from telebazaar.bot.handlers import Handlers


class FakeBotAPI:
    def __init__(self, token="test-token", fail=None):
        self.token = token
        self.fail = set(fail or [])
        self.calls = []

    def send_message(self, chat_id, text, reply_markup=None):
        self.calls.append((chat_id, text))
        if chat_id in self.fail:
            raise RuntimeError("send failed")
        return {"ok": True}


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
    conn.execute("UPDATE customers SET stage='vip', tags='vip' WHERE tg_id=222")
    conn.commit()
    store.create_segment(conn, "VIPs", tag="vip")
    conn.close()


def _broadcast_events(tmp_path, kind):
    conn = db.connect(tmp_path)
    rows = conn.execute("SELECT ref_id FROM events WHERE kind=?", (kind,)).fetchall()
    conn.close()
    return rows


def test_broadcast_dry_lists_members(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("broadcast", "--segment", "VIPs", "--text", "Hello", "--dry") == 0
    out = capsys.readouterr().out
    assert "DRY 2 recipients" in out
    assert "111 Alice active vip,repeat" in out
    assert "222 Bob vip vip" in out
    assert _broadcast_events(tmp_path, "broadcast_sent") == []


def test_broadcast_requires_confirmation_no_sends(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("broadcast", "--segment", "VIPs", "--text", "Hello") == 2
    err = capsys.readouterr().err
    assert "2 recipients" in err
    assert "--yes" in err
    assert _broadcast_events(tmp_path, "broadcast_sent") == []


def test_broadcast_unknown_segment_exit_1(run_cli, tmp_path, capsys):
    _seed(tmp_path)
    assert run_cli("broadcast", "--segment", "NOPE", "--text", "Hi", "--dry") == 1
    assert "unknown segment" in capsys.readouterr().err


def test_broadcast_yes_missing_token_exit_2(run_cli, tmp_path, monkeypatch, capsys):
    _seed(tmp_path)
    monkeypatch.delenv("TELEBAZAAR_BOT_TOKEN", raising=False)
    assert run_cli("broadcast", "--segment", "VIPs", "--text", "Hi", "--yes") == 2
    err = capsys.readouterr().err
    assert "bot token missing" in err
    assert _broadcast_events(tmp_path, "broadcast_sent") == []


def test_broadcast_yes_sends_to_each_member(run_cli, tmp_path, monkeypatch, capsys):
    _seed(tmp_path)
    monkeypatch.setenv("TELEBAZAAR_BOT_TOKEN", "test-token")
    fake = FakeBotAPI()
    monkeypatch.setattr("telebazaar.bot.api.BotAPI", lambda token: fake)
    assert (
        run_cli("broadcast", "--segment", "VIPs", "--text", "Hello everyone", "--yes")
        == 0
    )
    assert fake.calls == [(111, "Hello everyone"), (222, "Hello everyone")]
    assert "SENT 2/FAILED 0" in capsys.readouterr().out
    assert len(_broadcast_events(tmp_path, "broadcast_sent")) == 2


def test_broadcast_yes_failure_summary(run_cli, tmp_path, monkeypatch, capsys):
    _seed(tmp_path)
    monkeypatch.setenv("TELEBAZAAR_BOT_TOKEN", "test-token")
    fake = FakeBotAPI(fail=[222])
    monkeypatch.setattr("telebazaar.bot.api.BotAPI", lambda token: fake)
    assert run_cli("broadcast", "--segment", "VIPs", "--text", "Hi", "--yes") == 0
    assert "SENT 1/FAILED 1" in capsys.readouterr().out
    assert len(_broadcast_events(tmp_path, "broadcast_sent")) == 1
    assert len(_broadcast_events(tmp_path, "broadcast_failed")) == 1


def test_broadcast_rate_limit_called(run_cli, tmp_path, monkeypatch, capsys):
    _seed(tmp_path)
    monkeypatch.setenv("TELEBAZAAR_BOT_TOKEN", "test-token")
    fake = FakeBotAPI()
    monkeypatch.setattr("telebazaar.bot.api.BotAPI", lambda token: fake)
    pauses = []
    monkeypatch.setattr(
        "telebazaar.broadcast.rate_limit",
        lambda pause=0.3: pauses.append(pause),
    )
    assert run_cli("broadcast", "--segment", "VIPs", "--text", "Hi", "--yes") == 0
    capsys.readouterr()
    assert pauses == [0.3]


def test_broadcast_function_rate_limits_between_sends(tmp_path, monkeypatch):
    conn = db.connect(tmp_path)
    db.migrate(conn)
    pauses = []
    monkeypatch.setattr(
        "telebazaar.broadcast.rate_limit",
        lambda pause=0.3: pauses.append(pause),
    )
    fake = FakeBotAPI()
    members = [{"tg_id": 1}, {"tg_id": 2}, {"tg_id": 3}]
    sent, failed = broadcast_mod.broadcast(conn, fake, members, "Hi")
    conn.close()
    assert (sent, failed) == (3, 0)
    assert pauses == [0.3, 0.3]


def test_bot_broadcast_merchant_only(tmp_path):
    conn = db.connect(tmp_path)
    db.migrate(conn)
    store.upsert_customer(conn, 111, "Alice", "alice")
    store.create_segment(conn, "All", tag="")
    conn.commit()
    fake = FakeBotAPI()
    handlers = Handlers(fake, conn, merchant_ids=[999])

    update = {
        "message": {
            "chat": {"id": 777},
            "from": {"id": 999},
            "text": "/broadcast All Hello there",
        }
    }
    handlers.handle_update(update)
    assert fake.calls == [
        (111, "Hello there"),
        (777, "Broadcast sent: SENT 1/FAILED 0"),
    ]

    fake.calls.clear()
    update = {
        "message": {
            "chat": {"id": 777},
            "from": {"id": 123},
            "text": "/broadcast All Hello there",
        }
    }
    handlers.handle_update(update)
    assert fake.calls == [(777, "not authorized")]
    conn.close()
