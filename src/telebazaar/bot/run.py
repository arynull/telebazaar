import contextlib
import logging
import signal
import sys

from telebazaar import db as db_mod
from telebazaar.bot.api import BotAPI
from telebazaar.bot.handlers import Handlers

log = logging.getLogger("telebazaar.bot")


def _get_offset(conn) -> int:
    try:
        cur = conn.execute("SELECT value FROM meta WHERE key='update_offset'")
        row = cur.fetchone()
        if row is None:
            return 0
        return int(row["value"])
    except Exception:
        return 0


def _set_offset(conn, offset: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('update_offset', ?)",
        (str(offset),),
    )
    conn.commit()


def run_bot(token, data_dir, merchant_ids) -> int:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    stop = {"flag": False}

    def _sig(signum, frame):
        stop["flag"] = True

    try:
        signal.signal(signal.SIGINT, _sig)
        signal.signal(signal.SIGTERM, _sig)
    except Exception:
        log.debug("signal handlers unavailable on this platform; continuing")
    conn = db_mod.connect(data_dir)
    db_mod.migrate(conn)
    api = BotAPI(token)
    handlers = Handlers(api, conn, merchant_ids or [])
    offset = _get_offset(conn)
    log.info("bot starting offset=%s", offset)
    while not stop["flag"]:
        try:
            updates = api.get_updates(offset=offset, timeout=30)
        except Exception as e:
            log.exception("get_updates failed: %s", e)
            continue
        if not updates:
            continue
        for upd in updates:
            try:
                uid = upd.get("update_id")
                handlers.handle_update(upd)
                if uid is not None:
                    offset = int(uid) + 1
            except Exception as e:
                log.exception("update failed: %s", e)
                with contextlib.suppress(Exception):
                    offset = int(upd.get("update_id", offset)) + 1
        try:
            _set_offset(conn, offset)
        except Exception as e:
            log.exception("offset persist failed: %s", e)
    log.info("bot stopped")
    return 0
