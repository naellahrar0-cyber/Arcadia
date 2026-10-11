"""État persistant : évite de renvoyer deux fois le même signal ou le même brief."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)
MAX_KEYS = 500


class State:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data: dict = {"sent": [], "last_brief": None}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                log.warning("État illisible (%s), on repart à zéro", self.path)

    def seen(self, key: str) -> bool:
        return key in self.data["sent"]

    def mark(self, key: str) -> None:
        self.data["sent"] = (self.data["sent"] + [key])[-MAX_KEYS:]
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
