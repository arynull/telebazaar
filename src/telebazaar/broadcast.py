import time

from telebazaar import store as store_mod

RATE_LIMIT_SECONDS = 0.3


def rate_limit(pause: float = RATE_LIMIT_SECONDS) -> None:
    """Pause between sends to respect Telegram flood control."""
    time.sleep(pause)


def broadcast(
    conn, api, members, text, pause: float = RATE_LIMIT_SECONDS
) -> tuple[int, int]:
    """Send text to each member, rate-limited, logging one event per member.

    Returns (sent, failed). A failed send is logged as broadcast_failed and
    never aborts the campaign.
    """
    sent = 0
    failed = 0
    for index, member in enumerate(members):
        try:
            api.send_message(member["tg_id"], text)
        except Exception:
            failed += 1
            store_mod.log_event(
                conn,
                "broadcast_failed",
                str(member["tg_id"]),
                {"text": text},
            )
        else:
            sent += 1
            store_mod.log_event(
                conn,
                "broadcast_sent",
                str(member["tg_id"]),
                {"text": text},
            )
        if index < len(members) - 1:
            rate_limit(pause)
    conn.commit()
    return sent, failed
