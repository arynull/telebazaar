import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


def data_dir() -> Path:
    raw = os.environ.get("TELEBAZAAR_DATA_DIR", "")
    if raw.strip():
        return Path(raw).expanduser()
    return Path.home() / ".telebazaar"


def ensure_dirs() -> Path:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_merchant_ids(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for v in value:
            try:
                out.append(int(v))
            except (ValueError, TypeError):
                continue
        return out
    s = str(value).strip()
    if not s:
        return []
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def load_config() -> dict:
    d = data_dir()
    cfg = {"bot_token": "", "merchant_ids": [], "data_dir": str(d)}
    path = d / "config.toml"
    file_data = {}
    if path.is_file() and tomllib is not None:
        try:
            with open(path, "rb") as f:
                file_data = tomllib.load(f) or {}
        except Exception:
            file_data = {}
    if isinstance(file_data, dict):
        nested = (
            file_data.get("telebazaar")
            if isinstance(file_data.get("telebazaar"), dict)
            else {}
        )
        token = file_data.get("bot_token", nested.get("bot_token", ""))
        mids = file_data.get("merchant_ids", nested.get("merchant_ids", []))
        if isinstance(token, str):
            cfg["bot_token"] = token.strip()
        cfg["merchant_ids"] = _parse_merchant_ids(mids)
    env_token = os.environ.get("TELEBAZAAR_BOT_TOKEN", "").strip()
    if env_token:
        cfg["bot_token"] = env_token
    if "TELEBAZAAR_MERCHANT_IDS" in os.environ:
        cfg["merchant_ids"] = _parse_merchant_ids(
            os.environ.get("TELEBAZAAR_MERCHANT_IDS", "")
        )
    return cfg


def get_token(config=None) -> str:
    env_token = os.environ.get("TELEBAZAAR_BOT_TOKEN", "").strip()
    if env_token:
        return env_token
    if config is not None and isinstance(config, dict):
        t = str(config.get("bot_token", "")).strip()
        if t:
            return t
    return load_config().get("bot_token", "")
