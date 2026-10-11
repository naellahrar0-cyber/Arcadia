"""Envoi et lecture des messages Telegram. Les erreurs ne montrent jamais le token."""
from __future__ import annotations

from pathlib import Path

import requests

from .config import Config

TELEGRAM_MAX_CHARS = 4000  # limite Telegram : 4096


class TelegramError(RuntimeError):
    pass


def telegram_call(token: str, method: str, **params) -> dict:
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=30)
    except requests.RequestException as exc:
        # `from None` : l'exception d'origine contient l'URL, donc le token
        raise TelegramError(f"Telegram injoignable ({type(exc).__name__})") from None
    if resp.status_code != 200:
        raise TelegramError(f"Telegram a refusé la requête (HTTP {resp.status_code})")
    return resp.json()


def get_updates(token: str, offset: int | None = None, timeout: int = 20) -> list[dict]:
    params = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    return telegram_call(token, "getUpdates", **params)["result"]


class Notifier:
    def __init__(self, cfg: Config):
        self.token = cfg.telegram_token
        self.chat_id = cfg.telegram_chat_id
        self.log_file = Path(cfg.log_file)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> None:
        print(text, flush=True)
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(text + "\n" + "-" * 40 + "\n")
        if self.telegram_enabled:
            for chunk in _chunks(text, TELEGRAM_MAX_CHARS):
                telegram_call(self.token, "sendMessage", chat_id=self.chat_id, text=chunk,
                              disable_web_page_preview=True)


def _chunks(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]
