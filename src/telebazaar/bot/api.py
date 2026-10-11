import json
import time
import urllib.error
import urllib.request


class TelegramAPIError(Exception):
    pass


class BotAPI:
    def __init__(self, token):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"

    def _post(self, method, params, _retried=False):
        url = f"{self.base}/{method}"
        body = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            # URL is built from a fixed https://api.telegram.org base (see
            # __init__), never from user input, so urllib is safe here.
            with urllib.request.urlopen(  # nosec B310
                req, timeout=15
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read()
            except Exception:
                raw = b""
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                data = {}
            if e.code == 429 and not _retried:
                wait = 1
                try:
                    wait = int(data.get("parameters", {}).get("retry_after", 1))
                except Exception:
                    wait = 1
                time.sleep(max(wait, 1))
                return self._post(method, params, _retried=True)
            desc = (
                data.get("description", f"HTTP {e.code}")
                if isinstance(data, dict)
                else f"HTTP {e.code}"
            )
            raise TelegramAPIError(str(desc)) from e
        if not isinstance(data, dict) or not data.get("ok"):
            desc = (
                data.get("description", "unknown error")
                if isinstance(data, dict)
                else "unknown error"
            )
            code = data.get("error_code") if isinstance(data, dict) else None
            if code == 429 and not _retried:
                wait = 1
                try:
                    wait = int(data.get("parameters", {}).get("retry_after", 1))
                except Exception:
                    wait = 1
                time.sleep(max(wait, 1))
                return self._post(method, params, _retried=True)
            raise TelegramAPIError(str(desc))
        return data.get("result")

    def get_updates(self, offset=None, timeout=30):
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        return self._post("getUpdates", params)

    def send_message(self, chat_id, text, reply_markup=None):
        params = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        return self._post("sendMessage", params)

    def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        params = {"chat_id": chat_id, "photo": photo}
        if caption is not None:
            params["caption"] = caption
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        return self._post("sendPhoto", params)

    def answer_callback_query(self, callback_query_id, text=None):
        params = {"callback_query_id": callback_query_id}
        if text is not None:
            params["text"] = text
        return self._post("answerCallbackQuery", params)

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        return self._post("editMessageText", params)

    def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        return self._post(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            },
        )

    def send_invoice(
        self,
        chat_id,
        title,
        description,
        payload,
        currency,
        prices,
        # Empty default forces explicit config; this is not a credential.
        provider_token="",  # nosec
    ):
        return self._post(
            "sendInvoice",
            {
                "chat_id": chat_id,
                "title": title,
                "description": description,
                "payload": payload,
                "currency": currency,
                "prices": prices,
                "provider_token": provider_token,
            },
        )

    def answer_pre_checkout_query(self, pre_checkout_query_id, ok, error_message=None):
        params = {"pre_checkout_query_id": pre_checkout_query_id, "ok": bool(ok)}
        if error_message is not None:
            params["error_message"] = error_message
        return self._post("answerPreCheckoutQuery", params)
