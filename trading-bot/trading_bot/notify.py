"""Envoi des messages : console + fichier journal, et Telegram si configuré."""
from __future__ import annotations

from pathlib import Path

import requests

from .config import Config

TELEGRAM_MAX_CHARS = 4000  # limite Telegram : 4096


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
                resp = requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": chunk, "disable_web_page_preview": True},
                    timeout=15,
                )
                resp.raise_for_status()


def _chunks(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]
