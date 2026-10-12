"""Journal des signaux : pour chaque signal envoyé, on vérifie ensuite si le stop ou le take-profit a été touché.

C'est la mesure réelle des résultats, sur tes marchés et avec les frais configurés.
"""
from __future__ import annotations

import pandas as pd

from .backtest import close_trade
from .strategy import LONG, SHORT

MAX_ENTRIES = 500
MIN_SAMPLE = 30  # en dessous, les pourcentages ne veulent rien dire


def add_signal(state, sig) -> None:
    journal = state.data.setdefault("journal", [])
    if any(e["key"] == sig.key for e in journal):
        return
    journal.append({
        "key": sig.key, "symbol": sig.symbol, "interval": sig.interval, "side": sig.side,
        "time": sig.time.isoformat(), "entry": sig.entry, "stop": sig.stop, "tp": sig.take_profit,
        "status": "open",
    })
    state.data["journal"] = journal[-MAX_ENTRIES:]


def evaluate(state, cfg, provider) -> int:
    """Clôture les signaux dont le stop, le take-profit ou la durée maximale a été atteint. Retourne le nombre clôturé."""
    closed_now = 0
    for entry in state.data.get("journal", []):
        if entry["status"] != "open":
            continue
        try:
            df = provider.fetch(entry["symbol"], entry["interval"], cfg.lookback)
        except Exception:
            continue  # donnée indisponible : on réessaiera au prochain passage
        signal_time = pd.Timestamp(entry["time"])
        pos = {"i": 0, "time": signal_time, "side": LONG if entry["side"] == "LONG" else SHORT,
               "entry": entry["entry"], "stop": entry["stop"], "tp": entry["tp"]}
        for n, (ts, bar) in enumerate(df[df.index > signal_time].iterrows(), start=1):
            if pos["side"] == LONG:
                hit_sl, hit_tp = bar["low"] <= pos["stop"], bar["high"] >= pos["tp"]
            else:
                hit_sl, hit_tp = bar["high"] >= pos["stop"], bar["low"] <= pos["tp"]
            if hit_sl:
                exit_price, reason = pos["stop"], "SL"  # même hypothèse prudente que le backtest
            elif hit_tp:
                exit_price, reason = pos["tp"], "TP"
            elif n >= cfg.max_hold_bars:
                exit_price, reason = bar["close"], "TIME"
            else:
                continue
            trade = close_trade(pos, n, ts, exit_price, reason, cfg.fee_per_side)
            entry.update(status="closed", result=reason, r=round(trade["r"], 3),
                         return_pct=round(trade["return_pct"], 3), closed_at=ts.isoformat())
            closed_now += 1
            break
    return closed_now


def stats_text(state, now_local: str) -> str:
    journal = state.data.get("journal", [])
    closed = [e for e in journal if e["status"] == "closed"]
    open_ = [e for e in journal if e["status"] == "open"]
    lines = [f"📒 Journal des signaux — {now_local} (heure du Maroc)", ""]
    if not closed:
        lines.append("Aucun signal clôturé pour l'instant.")
    else:
        wins = [e for e in closed if e["r"] > 0]
        total_r = sum(e["r"] for e in closed)
        lines += [
            f"Signaux clôturés : {len(closed)}",
            f"Gagnants (TP) : {len(wins) / len(closed) * 100:.0f} %",
            f"Résultat moyen : {total_r / len(closed):+.2f} R (R = risque initial, frais inclus)",
            f"Total : {total_r:+.2f} R",
        ]
        if len(closed) < MIN_SAMPLE:
            lines.append(f"⚠️ Échantillon trop petit (moins de {MIN_SAMPLE} signaux) : pas de conclusion pour l'instant.")
    lines.append(f"Signaux encore ouverts : {len(open_)}")
    for e in open_[-5:]:
        lines.append(f"  - {e['side']} {e['symbol']} entrée {e['entry']:.5g}, SL {e['stop']:.5g}, TP {e['tp']:.5g}")
    return "\n".join(lines)
