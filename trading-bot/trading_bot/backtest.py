"""Backtest de la stratégie sur l'historique.

Hypothèses (volontairement prudentes) :
- entrée au cours de clôture de la bougie du signal ;
- sortie évaluée à partir de la bougie suivante ;
- si stop ET take-profit sont touchés dans la même bougie, on compte le stop ;
- frais appliqués à l'entrée et à la sortie ; pas de glissement modélisé.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config
from .strategy import LONG, compute_signals


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    summary: dict


def close_trade(pos: dict, i: int, time, exit_price: float, reason: str, fee: float) -> dict:
    direction = pos["side"]
    gross = direction * (exit_price - pos["entry"]) / pos["entry"]
    net = gross - 2 * fee
    risk_pct = abs(pos["entry"] - pos["stop"]) / pos["entry"]
    return {
        "entry_time": pos["time"],
        "exit_time": time,
        "side": "LONG" if direction == LONG else "SHORT",
        "entry": pos["entry"],
        "exit": exit_price,
        "reason": reason,
        "return_pct": net * 100,
        "r": net / risk_pct,  # résultat en multiple du risque initial, frais inclus
        "bars": i - pos["i"],
    }


def backtest(df: pd.DataFrame, cfg: Config) -> BacktestResult:
    sigs = compute_signals(df, cfg)
    highs, lows, closes = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    side, entry, stop, tp = (sigs[c].to_numpy() for c in ("side", "entry", "stop", "take_profit"))

    trades, pos = [], None
    for i in range(len(df)):
        if pos is not None:
            if pos["side"] == LONG:
                hit_sl, hit_tp = lows[i] <= pos["stop"], highs[i] >= pos["tp"]
            else:
                hit_sl, hit_tp = highs[i] >= pos["stop"], lows[i] <= pos["tp"]
            exit_price = reason = None
            if hit_sl:
                exit_price, reason = pos["stop"], "SL"
            elif hit_tp:
                exit_price, reason = pos["tp"], "TP"
            elif i - pos["i"] >= cfg.max_hold_bars:
                exit_price, reason = closes[i], "TIME"
            if exit_price is not None:
                trades.append(close_trade(pos, i, df.index[i], exit_price, reason, cfg.fee_per_side))
                pos = None

        # Ouverture : une seule position à la fois, et pas sur la toute dernière bougie
        if pos is None and i < len(df) - 1 and side[i] != 0 and not np.isnan(stop[i]):
            pos = {"i": i, "time": df.index[i], "side": int(side[i]),
                   "entry": entry[i], "stop": stop[i], "tp": tp[i]}

    trades_df = pd.DataFrame(trades)
    return BacktestResult(trades=trades_df, summary=summarize(trades_df, cfg))


def summarize(trades: pd.DataFrame, cfg: Config) -> dict:
    if trades.empty:
        return {"trades": 0, "win_rate_pct": 0.0, "avg_r": 0.0, "profit_factor": 0.0,
                "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "avg_bars": 0.0, "exits": {}}

    wins, losses = trades[trades["r"] > 0], trades[trades["r"] <= 0]
    gross_loss = -losses["r"].sum()
    # Courbe d'équité : chaque trade risque `risk_per_trade` de l'équité courante
    equity = np.concatenate([[1.0], (1 + cfg.risk_per_trade * trades["r"]).cumprod().to_numpy()])
    drawdown = equity / np.maximum.accumulate(equity) - 1

    return {
        "trades": int(len(trades)),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "avg_r": round(float(trades["r"].mean()), 3),
        "profit_factor": round(float(wins["r"].sum() / gross_loss), 2) if gross_loss > 0 else float("inf"),
        "total_return_pct": round((equity[-1] - 1) * 100, 2),
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 2),
        "avg_bars": round(float(trades["bars"].mean()), 1),
        "exits": trades["reason"].value_counts().to_dict(),
    }
