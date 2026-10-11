"""Orchestration : scan des signaux, brief matinal et boucle continue."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .brief import snapshot
from .data import INTERVAL_MINUTES
from .messages import format_brief, format_signal
from .strategy import Signal, latest_signal

log = logging.getLogger(__name__)


def scan(cfg, provider, notifier, state) -> list[Signal]:
    """Notifie chaque nouveau signal sur la dernière bougie clôturée."""
    sent = []
    for symbol in cfg.symbols:
        try:
            df = provider.fetch(symbol, cfg.interval, cfg.lookback)
        except Exception:  # une paire en erreur ne doit pas bloquer les autres
            log.exception("Données indisponibles pour %s", symbol)
            continue
        sig = latest_signal(symbol, df, cfg)
        if sig is None or state.seen(sig.key):
            continue
        max_age = timedelta(minutes=INTERVAL_MINUTES[cfg.interval] * cfg.max_signal_age_bars)
        if datetime.now(timezone.utc) - sig.time.to_pydatetime() > max_age:
            log.info("Signal %s %s ignoré : bougie trop ancienne (%s)", sig.side, sig.symbol, sig.time)
            continue
        notifier.send(format_signal(sig, cfg))
        state.mark(sig.key)
        sent.append(sig)
    return sent


def morning_brief(cfg, provider, notifier, now: datetime) -> str:
    snapshots, signals, failed = [], [], []
    for symbol in cfg.symbols:
        try:
            df = provider.fetch(symbol, cfg.interval, cfg.lookback)
        except Exception:
            log.exception("Données indisponibles pour %s", symbol)
            failed.append(symbol)
            continue
        snapshots.append(snapshot(symbol, df, cfg))
        sig = latest_signal(symbol, df, cfg)
        if sig is not None:
            signals.append(sig)
    text = format_brief(snapshots, signals, cfg, now, failed)
    notifier.send(text)
    return text


def run_forever(cfg, provider, notifier, state, tick_seconds: int = 30) -> None:
    tz = ZoneInfo(cfg.timezone)
    last_scan = None
    log.info("Bot démarré : %s, %s, brief à %s", ", ".join(cfg.symbols), cfg.interval, cfg.brief_time)
    while True:
        now = datetime.now(tz)
        today = now.date().isoformat()
        try:
            if now.strftime("%H:%M") >= cfg.brief_time and state.data.get("last_brief") != today:
                morning_brief(cfg, provider, notifier, now)
                state.data["last_brief"] = today
                state.save()
            if last_scan is None or time.monotonic() - last_scan >= cfg.scan_every_minutes * 60:
                scan(cfg, provider, notifier, state)
                last_scan = time.monotonic()
        except Exception:
            log.exception("Erreur dans la boucle, nouvelle tentative au prochain tick")
        time.sleep(tick_seconds)
