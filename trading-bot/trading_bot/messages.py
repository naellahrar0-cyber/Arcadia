"""Mise en forme des messages envoyés (alertes de signal et brief matinal)."""
from __future__ import annotations

import math
from datetime import datetime

from .brief import Snapshot
from .config import Config
from .risk import position_size, target_position_size
from .strategy import Signal

DISCLAIMER = "Généré automatiquement à partir d'indicateurs techniques. Ce n'est pas un conseil financier."


def fmt_price(x: float) -> str:
    if math.isnan(x):
        return "n/a"
    text = f"{x:,.2f}" if abs(x) >= 1 else f"{x:.6f}"
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
    icon = "🟢" if sig.side == "LONG" else "🔴"
    return "\n".join([
        f"{icon} SIGNAL {sig.side} — {sig.symbol} ({sig.interval})",
        f"Bougie clôturée : {sig.time:%Y-%m-%d %H:%M} UTC",
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
                 failed: list[str] | None = None) -> str:
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
    lines += ["", f"ℹ️ {DISCLAIMER}"]
    return "\n".join(lines)
