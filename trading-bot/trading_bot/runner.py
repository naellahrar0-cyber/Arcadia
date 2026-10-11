"""Orchestration : scans, brief horaire, réponses aux messages Telegram et boucle continue."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .ai import analyze_news
from .alerts import fetch_events, regime_alerts, upcoming_alerts
from .brief import snapshot
from .data import INTERVAL_MINUTES
from .messages import DISCLAIMER, HELP_TEXT, fmt_price, format_brief, format_event_alert, format_prices, format_signal
from .news import fetch_news
from .notify import TelegramError, get_updates
from .strategy import Signal, latest_signal

log = logging.getLogger(__name__)


def scan(cfg, provider, notifier, state) -> list[Signal]:
    """Notifie chaque nouveau signal sur la dernière bougie clôturée."""
    sent = []
    for symbol in cfg.symbols:
        try:
            df = provider.fetch(symbol, cfg.interval, cfg.lookback)
        except Exception as exc:  # une paire en erreur ne doit pas bloquer les autres
            log.error("Données indisponibles pour %s (%s)", symbol, type(exc).__name__)
            continue
        for text in regime_alerts(symbol, df, cfg):
            key = f"regime|{symbol}|{df.index[-1].isoformat()}|{text}"
            if not state.seen(key):
                notifier.send(f"⚠️ CHANGEMENT DE MARCHÉ — {symbol} ({cfg.interval})\n{text}\n{DISCLAIMER}")
                state.mark(key)
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


def _snapshots(cfg, provider):
    snapshots, signals, failed = [], [], []
    for symbol in cfg.symbols:
        try:
            df = provider.fetch(symbol, cfg.interval, cfg.lookback)
        except Exception as exc:
            log.error("Données indisponibles pour %s (%s)", symbol, type(exc).__name__)
            failed.append(symbol)
            continue
        snapshots.append(snapshot(symbol, df, cfg))
        sig = latest_signal(symbol, df, cfg)
        if sig is not None:
            signals.append(sig)
    return snapshots, signals, failed


def morning_brief(cfg, provider, notifier, now: datetime) -> str:
    """Brief complet : prix, tendances, signaux actifs et actualités."""
    snapshots, signals, failed = _snapshots(cfg, provider)
    news = fetch_news(cfg.news_tickers, cfg.news_per_ticker)
    text = format_brief(snapshots, signals, cfg, now, failed, news)
    analysis = analyze_news(news, cfg)
    if analysis:
        text += f"\n\n🧠 Analyse IA des actualités (à vérifier) :\n{analysis}"
    notifier.send(text)
    return text


def status_text(cfg, state, now: datetime) -> str:
    local = now.astimezone(ZoneInfo(cfg.display_timezone))
    return "\n".join([
        "🤖 Bot actif",
        f"Heure (Maroc) : {local:%d/%m/%Y %H:%M}",
        f"Paires : {', '.join(cfg.symbols)} ({cfg.interval})",
        f"Dernier scan : {state.data.get('last_scan') or 'pas encore'}",
        f"Brief : chaque heure à :{cfg.brief_minute:02d} (heure du Maroc)",
        "",
        "Tape /aide pour la liste des commandes.",
    ])


def run_now_text(cfg, provider, now: datetime) -> str:
    """Réponse immédiate à /run : achat, vente ou pas d'entrée, avec les niveaux."""
    _, signals, failed = _snapshots(cfg, provider)
    max_age = timedelta(minutes=INTERVAL_MINUTES[cfg.interval] * cfg.max_signal_age_bars)
    fresh = [s for s in signals if now - s.time.to_pydatetime() <= max_age]
    local = now.astimezone(ZoneInfo(cfg.display_timezone))
    lines = [f"🔎 Analyse maintenant — {local:%d/%m %H:%M} (heure du Maroc)", ""]
    if fresh:
        for sig in fresh:
            label = "ACHAT (BUY)" if sig.side == "LONG" else "VENTE (SELL)"
            lines.append(f"➡️ {label} — {sig.symbol}")
            lines.append(f"   Entrée {fmt_price(sig.entry)} · SL {fmt_price(sig.stop)} (-{sig.risk_pct:.2f} %) · "
                         f"TP {fmt_price(sig.take_profit)} (+{sig.reward_pct:.2f} %) · R/R 1:{sig.rr:.1f}")
    else:
        lines.append("⏸ Pas d'entrée maintenant : aucun signal sur la dernière bougie clôturée.")
    if failed:
        lines.append(f"⚠️ Données indisponibles : {', '.join(failed)}")
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


def answer_messages(cfg, state, provider, notifier, now: datetime) -> int:
    """Répond aux messages envoyés au bot. Seul le chat configuré reçoit une réponse."""
    if not cfg.telegram_token or not cfg.telegram_chat_id:
        return 0
    answered = 0
    for update in get_updates(cfg.telegram_token, offset=state.data.get("update_offset")):
        state.data["update_offset"] = update["update_id"] + 1
        msg = update.get("message") or {}
        if str((msg.get("chat") or {}).get("id", "")) != str(cfg.telegram_chat_id):
            continue  # message d'un inconnu : ignoré
        command = (msg.get("text") or "").strip().lower().split("@")[0]
        if command in ("/brief", "brief"):
            morning_brief(cfg, provider, notifier, now)
        elif command in ("/run", "run"):
            notifier.send(run_now_text(cfg, provider, now))
        elif command in ("/prix", "prix", "/prices"):
            snapshots, _, _ = _snapshots(cfg, provider)
            notifier.send(format_prices(snapshots, cfg, now))
        elif command in ("/aide", "aide", "/help", "help", "/start"):
            notifier.send(HELP_TEXT)
        else:
            notifier.send(status_text(cfg, state, now))
        answered += 1
    state.save()
    return answered


def run_forever(cfg, provider, notifier, state, tick_seconds: int = 5) -> None:
    tz = ZoneInfo(cfg.timezone)
    last_scan = None
    events, events_at = [], None
    log.info("Bot démarré : %s, %s, brief chaque heure à :%02d", ", ".join(cfg.symbols), cfg.interval, cfg.brief_minute)
    while True:
        now = datetime.now(tz)
        hour_key = now.strftime("%Y-%m-%d %H")
        try:
            if now.minute >= cfg.brief_minute and state.data.get("last_brief") != hour_key:
                morning_brief(cfg, provider, notifier, now)
                state.data["last_brief"] = hour_key
                state.save()
            if last_scan is None or time.monotonic() - last_scan >= cfg.scan_every_minutes * 60:
                scan(cfg, provider, notifier, state)
                last_scan = time.monotonic()
                state.data["last_scan"] = now.strftime("%d/%m %H:%M")
                state.save()
        except TelegramError as exc:  # message sans token, pas de trace complète
            log.error("%s", exc)
        except Exception:
            log.exception("Erreur dans la boucle, nouvelle tentative au prochain tick")
        if cfg.calendar_url and (events_at is None or time.monotonic() - events_at > 1800):
            try:
                events = fetch_events(cfg.calendar_url)
            except (requests.RequestException, ValueError, KeyError):
                log.warning("Calendrier économique indisponible")
            events_at = time.monotonic()  # nouvelle tentative dans 30 min
        try:
            for ev in upcoming_alerts(events, cfg.symbols, pd.Timestamp.now(tz="UTC"), cfg.alert_minutes_before):
                key = f"event|{ev['title']}|{ev['time'].isoformat()}"
                if not state.seen(key):
                    notifier.send(format_event_alert(ev, cfg))
                    state.mark(key)
        except TelegramError as exc:
            log.error("%s", exc)
        try:
            answer_messages(cfg, state, provider, notifier, datetime.now(tz))
        except TelegramError as exc:
            log.error("%s", exc)
        time.sleep(tick_seconds)
