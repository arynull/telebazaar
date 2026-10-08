import contextlib
import json
import logging

from telebazaar import store as store_mod

log = logging.getLogger("telebazaar.bot")


def _cb(s: str) -> str:
    b = s.encode("utf-8")
    if len(b) <= 64:
        return s
    while len(b) > 64:
        s = s[:-1]
        b = s.encode("utf-8")
    return s


def _add_cb(sku: str) -> str:
    return _cb(f"add:{sku[:60]}")


class Handlers:
    def __init__(self, api, store, merchant_ids=None):
        self.api = api
        self.conn = store
        self.merchant_ids = {int(x) for x in (merchant_ids or [])}

    def _is_merchant(self, user_id) -> bool:
        try:
            return int(user_id) in self.merchant_ids
        except Exception:
            return False

    def handle_update(self, update: dict) -> None:
        try:
            if "pre_checkout_query" in update:
                self._on_pre_checkout(update["pre_checkout_query"])
            elif "callback_query" in update:
                self._on_callback(update["callback_query"])
            elif "message" in update:
                self._on_message(update["message"])
        except Exception as e:
            log.exception("handle_update failed: %s", e)
            try:
                chat_id = self._extract_chat_id(update)
                if chat_id is not None:
                    self.api.send_message(chat_id, "Something went wrong. Try again.")
            except Exception:
                pass

    def _extract_chat_id(self, update):
        try:
            if "message" in update:
                return update["message"]["chat"]["id"]
            if "callback_query" in update:
                return update["callback_query"]["message"]["chat"]["id"]
            if "pre_checkout_query" in update:
                return update["pre_checkout_query"]["from"]["id"]
        except Exception:
            return None
        return None

    def _ensure_customer(self, user) -> int:
        uid = int(user.get("id"))
        name = (user.get("first_name", "") + " " + user.get("last_name", "")).strip()
        username = user.get("username", "") or ""
        store_mod.upsert_customer(self.conn, uid, name=name, username=username)
        return uid

    def _on_message(self, msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        user = msg.get("from", {}) or {}
        if "successful_payment" in msg:
            self._on_successful_payment(msg, chat_id)
            return
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        cmd = text.split()[0].split("@")[0]
        if cmd == "/start":
            if user:
                with contextlib.suppress(Exception):
                    self._ensure_customer(user)
            self.api.send_message(chat_id, "Welcome to the shop! Use /shop to browse.")
        elif cmd == "/shop":
            self._cmd_shop(chat_id, user)
        elif cmd == "/cart":
            self._cmd_cart(chat_id, user)
        elif cmd == "/myorders":
            self._cmd_myorders(chat_id, user)
        elif cmd == "/orders":
            self._cmd_orders(chat_id, user)
        elif cmd == "/order":
            parts = text.split()
            if len(parts) < 2:
                self.api.send_message(chat_id, "Usage: /order <id>")
                return
            self._cmd_order(chat_id, user, parts[1].strip())

    def _cmd_shop(self, chat_id, user) -> None:
        if user:
            with contextlib.suppress(Exception):
                self._ensure_customer(user)
        products = store_mod.list_products(self.conn, active_only=True)
        if not products:
            self.api.send_message(chat_id, "Shop is empty.")
            return
        for chunk in [products[i : i + 8] for i in range(0, len(products), 8)]:
            lines = []
            buttons = []
            for p in chunk:
                lines.append(
                    f"{p['name']} — {p['price_minor']} {p.get('currency', 'XTR')}"
                )
                buttons.append(
                    [
                        {
                            "text": f"\u2795 {p['name']} \u2014 {p['price_minor']}",
                            "callback_data": _add_cb(p["sku"]),
                        }
                    ]
                )
            self.api.send_message(
                chat_id, "\n".join(lines), reply_markup={"inline_keyboard": buttons}
            )

    def _cmd_cart(self, chat_id, user) -> None:
        try:
            tg_id = int(user.get("id"))
        except Exception:
            self.api.send_message(chat_id, "Cart is empty.")
            return
        lines = store_mod.cart_view(self.conn, tg_id)
        if not lines:
            self.api.send_message(chat_id, "Cart is empty.")
            return
        total = sum(int(x["qty"]) * int(x["unit_price"]) for x in lines)
        text_lines = [
            f"{x['name']} x{x['qty']} = {int(x['qty']) * int(x['unit_price'])}"
            for x in lines
        ]
        text_lines.append(f"Total: {total}")
        kb = {
            "inline_keyboard": [
                [{"text": "\U0001f4b3 Checkout", "callback_data": _cb("checkout")}],
                [{"text": "Clear", "callback_data": _cb("cart:clear")}],
            ]
        }
        self.api.send_message(chat_id, "\n".join(text_lines), reply_markup=kb)

    def _cmd_myorders(self, chat_id, user) -> None:
        try:
            tg_id = int(user.get("id"))
        except Exception:
            self.api.send_message(chat_id, "No orders.")
            return
        cur = self.conn.execute(
            "SELECT id, status, total_minor FROM orders "
            "WHERE customer_tg_id=? ORDER BY created_at DESC LIMIT 5",
            (tg_id,),
        )
        rows = cur.fetchall()
        if not rows:
            self.api.send_message(chat_id, "No orders.")
            return
        lines = [f"{r['id']} — {r['status']} — {r['total_minor']}" for r in rows]
        self.api.send_message(chat_id, "\n".join(lines))

    def _cmd_orders(self, chat_id, user) -> None:
        try:
            uid = int(user.get("id"))
        except Exception:
            self.api.send_message(chat_id, "not authorized")
            return
        if not self._is_merchant(uid):
            self.api.send_message(chat_id, "not authorized")
            return
        cur = self.conn.execute(
            "SELECT id, status, total_minor FROM orders "
            "WHERE status NOT IN ('shipped','cancelled') "
            "ORDER BY created_at DESC LIMIT 10"
        )
        rows = cur.fetchall()
        if not rows:
            self.api.send_message(chat_id, "No open orders.")
            return
        lines = [f"{r['id']} — {r['status']} — {r['total_minor']}" for r in rows]
        self.api.send_message(chat_id, "\n".join(lines))

    def _cmd_order(self, chat_id, user, order_id: str) -> None:
        try:
            uid = int(user.get("id"))
        except Exception:
            self.api.send_message(chat_id, "not authorized")
            return
        if not self._is_merchant(uid):
            self.api.send_message(chat_id, "not authorized")
            return
        try:
            order = store_mod.get_order(self.conn, order_id)
        except KeyError:
            self.api.send_message(chat_id, "Order not found.")
            return
        detail = json.dumps(
            {
                "id": order["id"],
                "status": order["status"],
                "total": order["total_minor"],
                "currency": order["currency"],
                "items": order["items_json"],
            },
            indent=2,
        )
        kb = {
            "inline_keyboard": [
                [
                    {"text": "Ship", "callback_data": _cb(f"ship:{order_id}")},
                    {"text": "Cancel", "callback_data": _cb(f"cancel:{order_id}")},
                ],
            ]
        }
        self.api.send_message(chat_id, detail, reply_markup=kb)

    def _on_callback(self, cb: dict) -> None:
        cb_id = cb.get("id", "")
        data = cb.get("data", "") or ""
        user = cb.get("from", {}) or {}
        msg = cb.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        try:
            if data.startswith("add:"):
                sku = data[4:]
                tg_id = self._ensure_customer(user)
                store_mod.cart_add(self.conn, tg_id, sku, 1)
                self.api.answer_callback_query(cb_id, text="Added \u2705")
            elif data == "cart:clear":
                with contextlib.suppress(Exception):
                    tg_id = int(user.get("id"))
                    store_mod.cart_clear(self.conn, tg_id)
                self.api.answer_callback_query(cb_id, text="Cleared")
            elif data == "checkout":
                self._do_checkout(cb_id, chat_id, user)
            elif data.startswith("ship:"):
                oid = data[5:]
                if not self._is_merchant(user.get("id")):
                    self.api.answer_callback_query(cb_id, text="not authorized")
                    return
                store_mod.transition(self.conn, oid, "shipped")
                self.api.answer_callback_query(cb_id, text="Shipped")
                if chat_id is not None:
                    self.api.send_message(chat_id, f"Order {oid} shipped.")
            elif data.startswith("cancel:"):
                oid = data[7:]
                if not self._is_merchant(user.get("id")):
                    self.api.answer_callback_query(cb_id, text="not authorized")
                    return
                try:
                    store_mod.get_order(self.conn, oid)
                except KeyError:
                    self.api.answer_callback_query(cb_id, text="not found")
                    return
                to = "cancelled"
                store_mod.transition(self.conn, oid, to)
                self.api.answer_callback_query(cb_id, text="Cancelled")
                if chat_id is not None:
                    self.api.send_message(chat_id, f"Order {oid} cancelled.")
            else:
                self.api.answer_callback_query(cb_id)
        except (ValueError, KeyError, store_mod.IllegalTransition) as e:
            with contextlib.suppress(Exception):
                self.api.answer_callback_query(cb_id, text=str(e)[:60])

    def _do_checkout(self, cb_id, chat_id, user) -> None:
        try:
            tg_id = int(user.get("id"))
        except Exception:
            self.api.answer_callback_query(cb_id, text="cart is empty")
            return
        with contextlib.suppress(Exception):
            self._ensure_customer(user)
        lines = store_mod.cart_view(self.conn, tg_id)
        if not lines:
            self.api.answer_callback_query(cb_id, text="cart is empty")
            return
        pairs = [(x["sku"], int(x["qty"])) for x in lines]
        try:
            oid = store_mod.create_order(self.conn, tg_id, pairs)
        except (ValueError, KeyError) as e:
            self.api.answer_callback_query(cb_id, text=str(e)[:60])
            return
        order = store_mod.get_order(self.conn, oid)
        total = int(order["total_minor"])
        currency = order.get("currency", "XTR") or "XTR"
        n = len(lines)
        self.api.answer_callback_query(cb_id)
        self.api.send_invoice(
            chat_id,
            title=f"Order {oid}",
            description=f"{n} items",
            payload=f"tb:{oid}",
            currency=currency,
            prices=[{"label": f"Order {oid}", "amount": total}],
            provider_token="",
        )
        self.api.send_message(
            chat_id, "Invoice sent \u2014 complete payment in Telegram"
        )

    def _on_pre_checkout(self, q: dict) -> None:
        qid = q.get("id", "")
        payload = q.get("invoice_payload", "") or ""
        total_amount = q.get("total_amount", 0)
        try:
            total_amount = int(total_amount)
        except Exception:
            self.api.answer_pre_checkout_query(qid, False, error_message="bad amount")
            return
        if not payload.startswith("tb:"):
            self.api.answer_pre_checkout_query(qid, False, error_message="bad payload")
            return
        oid = payload[3:]
        try:
            order = store_mod.get_order(self.conn, oid)
        except KeyError:
            self.api.answer_pre_checkout_query(
                qid, False, error_message="unknown order"
            )
            return
        if (
            order.get("status") != "pending_payment"
            or int(order.get("total_minor", -1)) != total_amount
        ):
            self.api.answer_pre_checkout_query(
                qid, False, error_message="amount mismatch"
            )
            return
        self.api.answer_pre_checkout_query(qid, True)

    def _on_successful_payment(self, msg: dict, chat_id) -> None:
        sp = msg.get("successful_payment", {}) or {}
        payload = sp.get("invoice_payload", "") or ""
        charge_id = sp.get("telegram_payment_charge_id", "") or ""
        try:
            total_amount = int(sp.get("total_amount", 0))
        except Exception:
            total_amount = 0
        currency = sp.get("currency", "XTR") or "XTR"
        try:
            order = store_mod.mark_paid_by_payload(
                self.conn, payload, charge_id, total_amount, currency
            )
        except (ValueError, KeyError) as e:
            self.api.send_message(chat_id, f"Payment error: {e}")
            return
        self.api.send_message(
            chat_id, f"Payment received for order {order['id']}. Thank you!"
        )
