"""Mise en forme des messages envoyés (alertes de signal et brief matinal)."""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .brief import Snapshot
from .config import Config
from .data import INTERVAL_MINUTES
from .risk import position_size, target_position_size
from .strategy import Signal


DISCLAIMER = "Généré automatiquement à partir d'indicateurs techniques. Ce n'est pas un conseil financier."


def fmt_price(x: float) -> str:
    if math.isnan(x):
        return "n/a"
    if abs(x) >= 1000:
        text = f"{x:,.2f}"
    elif abs(x) >= 100:
        text = f"{x:.3f}"
    elif abs(x) >= 1:
        text = f"{x:.5f}"  # ex. EURUSD 1.12345
    else:
        text = f"{x:.6f}"
    return text.replace(",", " ")


def format_signal(sig: Signal, cfg: Config) -> str:
    if cfg.target_profit is not None:
        qty, notional, loss = target_position_size(cfg.target_profit, sig.entry, sig.take_profit, sig.stop)
        size_lines = [
            f"Taille       : {qty:.4f} unités ≈ {fmt_price(notional)} de valeur",
            f"Gain visé    : +{cfg.target_profit:.2f} au take-profit",
            f"Perte max    : -{loss:.2f} au stop-loss",
        ]
    else:
        qty, notional, loss = position_size(cfg.capital, cfg.risk_per_trade, sig.entry, sig.stop)
        size_lines = [
            f"Taille       : {qty:.4f} unités ≈ {fmt_price(notional)} de valeur",
            f"Risque       : {loss:.2f} ({cfg.risk_per_trade * 100:.1f} % de {fmt_price(cfg.capital)})",
        ]

    if sig.side == "LONG":
        icon, label = "🟢", "ACHAT (BUY)"
    else:
        icon, label = "🔴", "VENTE (SELL)"
    # Le signal part à la clôture de la bougie : heure de fin de bougie, affichée à l'heure locale choisie
    close_time = sig.time + pd.Timedelta(minutes=INTERVAL_MINUTES[sig.interval])
    local = close_time.tz_convert(cfg.display_timezone)
    return "\n".join([
        f"{icon} ENTRÉE EN POSITION — {label} — {sig.symbol} ({sig.interval})",
        f"Heure ({cfg.display_timezone.split('/')[-1]}) : {local:%d/%m/%Y %H:%M}",
        "",
        f"Entrée       : {fmt_price(sig.entry)}",
        f"Stop-loss    : {fmt_price(sig.stop)}  (-{sig.risk_pct:.2f} %)",
        f"Take-profit  : {fmt_price(sig.take_profit)}  (+{sig.reward_pct:.2f} %)",
        f"Ratio R/R    : 1 : {sig.rr:.1f}",
        "",
        *size_lines,
        "",
        "Ordre à placer manuellement (aucune exécution automatique).",
        DISCLAIMER,
    ])


def format_brief(snapshots: list[Snapshot], signals: list[Signal], cfg: Config, now: datetime,
                 failed: list[str] | None = None, news: list[dict] | None = None) -> str:
    lines = [f"☀️ Brief marché — {now:%d/%m/%Y %H:%M} ({cfg.timezone})", "", "Vue d'ensemble"]
    if failed:
        lines.append(f"⚠️ Données indisponibles : {', '.join(failed)}")
    for s in snapshots:
        lines.append(
            f"• {s.symbol} : {fmt_price(s.price)} ({s.change_pct:+.2f} % sur 24 h) — "
            f"tendance {s.trend}, RSI {s.rsi:.0f}, volatilité {s.atr_pct:.2f} %"
        )
        lines.append(f"   Support {fmt_price(s.support)} · Résistance {fmt_price(s.resistance)}")

    lines.append("")
    if signals:
        lines.append(f"Signaux actifs ({len(signals)}) :")
        for sig in signals:
            lines.append(
                f"  - {sig.side} {sig.symbol} : entrée {fmt_price(sig.entry)}, "
                f"TP +{sig.reward_pct:.2f} %, SL -{sig.risk_pct:.2f} %"
            )
    else:
        lines.append("Aucun signal sur la dernière bougie clôturée.")
    if news:
        from .alerts import headline_bias

        tickers = sorted({item["ticker"] for item in news})
        biases = ", ".join(f"{t} {headline_bias([i['title'] for i in news if i['ticker'] == t])}" for t in tickers)
        lines += ["", f"Actualités (biais par mots-clés, indicatif) : {biases}", "Titres :"]
        for item in news:
            lines.append(f"  - [{item['ticker']}] {item['title']}")
            if item["link"]:
                lines.append(f"    {item['link']}")
    lines += ["", f"ℹ️ {DISCLAIMER}"]
    return "\n".join(lines)


def format_prices(snapshots: list[Snapshot], cfg: Config, now: datetime) -> str:
    lines = [f"💹 Prix — {now.astimezone(ZoneInfo(cfg.display_timezone)):%d/%m %H:%M} (heure du Maroc)", ""]
    for s in snapshots:
        lines.append(f"• {s.symbol} : {fmt_price(s.price)} ({s.change_pct:+.2f} % sur 24 h), "
                     f"tendance {s.trend}, RSI {s.rsi:.0f}")
    return "\n".join(lines)


def format_event_alert(ev: dict, cfg: Config) -> str:
    local = ev["time"].tz_convert(cfg.display_timezone)
    return "\n".join([
        f"📅 ÉVÉNEMENT À FORT IMPACT dans moins de {cfg.alert_minutes_before} min",
        f"{ev['country']} — {ev['title']}",
        f"Heure (Maroc) : {local:%d/%m %H:%M}",
        "Des mouvements rapides sont possibles autour de cette annonce.",
        DISCLAIMER,
    ])


HELP_TEXT = "\n".join([
    "🤖 Commandes :",
    "/brief : brief complet maintenant (prix, signaux, actualités)",
    "/prix : prix et tendance des paires suivies",
    "/status : état du bot et dernier scan",
    "/aide : cette liste",
    "",
    "Le brief arrive aussi automatiquement chaque heure, et les signaux « ENTRÉE EN POSITION » dès qu'ils apparaissent.",
])
