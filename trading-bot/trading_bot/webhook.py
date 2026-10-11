"""Récepteur de webhooks TradingView.

Le script Pine (tradingview/bot_signals.pine) envoie une alerte JSON quand un signal
apparaît. Ce module valide le secret, recalcule stop-loss et take-profit avec les
mêmes règles que le bot, puis notifie. Aucun ordre n'est passé.
"""
from __future__ import annotations

import hmac
import json
import logging
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd

from .config import Config
from .data import INTERVAL_MINUTES
from .messages import format_signal
from .strategy import Signal

log = logging.getLogger(__name__)
MAX_BODY = 4096
REQUIRED_FIELDS = ("symbol", "side", "price", "atr")
_lock = threading.Lock()  # sérialise l'accès à l'état entre threads HTTP


class PayloadError(ValueError):
    pass


def normalize_interval(value: str) -> str:
    """TradingView envoie '60' pour 1h, '240' pour 4h, 'D' pour 1 jour."""
    value = str(value).strip()
    if value.isdigit():
        minutes = int(value)
        for label, m in INTERVAL_MINUTES.items():
            if m == minutes:
                return label
        raise PayloadError(f"intervalle non supporté : {value}")
    if value.upper() == "D":
        return "1d"
    if value in INTERVAL_MINUTES:
        return value
    raise PayloadError(f"intervalle non supporté : {value}")


def _parse_time(value) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp(datetime.now(UTC))
    if isinstance(value, (int, float)):
        return pd.Timestamp(value, unit="ms", tz="UTC")
    ts = pd.Timestamp(str(value))
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def signal_from_payload(payload: dict, cfg: Config) -> Signal:
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        raise PayloadError(f"champs manquants : {', '.join(missing)}")
    side = str(payload["side"]).upper()
    if side not in ("LONG", "SHORT"):
        raise PayloadError("side doit valoir LONG ou SHORT")
    try:
        price, atr = float(payload["price"]), float(payload["atr"])
    except (TypeError, ValueError) as exc:
        raise PayloadError("price et atr doivent être numériques") from exc
    if price <= 0 or atr <= 0:
        raise PayloadError("price et atr doivent être > 0")

    sign = 1 if side == "LONG" else -1
    risk = atr * cfg.atr_stop_mult
    return Signal(
        symbol=str(payload["symbol"]).upper(),
        interval=normalize_interval(payload.get("interval", cfg.interval)),
        time=_parse_time(payload.get("time")),
        side=side,
        entry=price,
        stop=price - sign * risk,
        take_profit=price + sign * risk * cfg.reward_risk,
    )


def handle_payload(payload: dict, cfg: Config, notifier, state) -> tuple[int, str]:
    """Logique pure du webhook : retourne (code HTTP, message). Testable sans serveur."""
    if not cfg.tv_secret:
        return 503, "webhook désactivé : TV_WEBHOOK_SECRET non défini"
    if not hmac.compare_digest(str(payload.get("secret", "")), cfg.tv_secret):
        return 401, "secret invalide"
    try:
        sig = signal_from_payload(payload, cfg)
    except (PayloadError, ValueError) as exc:
        return 400, str(exc)

    with _lock:
        if state.seen(sig.key):
            return 200, "doublon ignoré"
        notifier.send(format_signal(sig, cfg))
        state.mark(sig.key)
    return 200, "signal notifié"


def make_handler(cfg: Config, notifier, state):
    class TradingViewHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path.rstrip("/") != "/tradingview":
                return self._reply(404, "introuvable")
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0:
                return self._reply(400, "corps vide")
            if length > MAX_BODY:
                return self._reply(413, "corps trop volumineux")
            try:
                payload = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                return self._reply(400, "JSON invalide")
            if not isinstance(payload, dict):
                return self._reply(400, "un objet JSON est attendu")
            status, message = handle_payload(payload, cfg, notifier, state)
            self._reply(status, message)

        def _reply(self, status: int, message: str) -> None:
            body = message.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # ne journalise ni le corps ni le secret
            log.info("%s %s", self.address_string(), fmt % args)

    return TradingViewHandler


def make_server(cfg: Config, notifier, state, host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host or cfg.webhook_host, cfg.webhook_port if port is None else port),
        make_handler(cfg, notifier, state),
    )


def serve(cfg: Config, notifier, state) -> None:
    server = make_server(cfg, notifier, state)
    log.info("Webhook TradingView à l'écoute sur %s:%s/tradingview", *server.server_address)
    try:
        server.serve_forever()
    finally:
        server.server_close()
