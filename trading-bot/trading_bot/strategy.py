"""Stratégie « pullback dans la tendance ».

Long : tendance haussière confirmée (prix au-dessus de l'EMA 200, EMA 20 au-dessus
de l'EMA 50), la bougie plonge sur l'EMA 20 puis la reprend, RSI non extrême.
Short : symétrique.

Stop-loss = entrée ∓ ATR x mult. Take-profit = entrée ± distance du stop x R/R.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config
from .indicators import atr, ema, rsi

LONG, SHORT = 1, -1


@dataclass(frozen=True)
class Signal:
    symbol: str
    interval: str
    time: pd.Timestamp  # ouverture de la bougie clôturée qui a déclenché le signal
    side: str  # "LONG" ou "SHORT"
    entry: float
    stop: float
    take_profit: float

    @property
    def risk_pct(self) -> float:
        return abs(self.entry - self.stop) / self.entry * 100

    @property
    def reward_pct(self) -> float:
        return abs(self.take_profit - self.entry) / self.entry * 100

    @property
    def rr(self) -> float:
        return self.reward_pct / self.risk_pct

    @property
    def key(self) -> str:
        return f"{self.symbol}|{self.interval}|{self.time.isoformat()}|{self.side}"


def add_indicators(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ema(out["close"], cfg.ema_fast)
    out["ema_slow"] = ema(out["close"], cfg.ema_slow)
    out["ema_trend"] = ema(out["close"], cfg.ema_trend)
    out["rsi"] = rsi(out["close"], cfg.rsi_period)
    out["atr"] = atr(out, cfg.atr_period)
    return out


def compute_signals(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Une ligne par bougie : side (1, -1 ou 0), entry, stop, take_profit, atr."""
    d = add_indicators(df, cfg)
    tol = cfg.pullback_tolerance

    uptrend = (d["close"] > d["ema_trend"]) & (d["ema_fast"] > d["ema_slow"])
    downtrend = (d["close"] < d["ema_trend"]) & (d["ema_fast"] < d["ema_slow"])
    long_ok = uptrend & (d["low"] <= d["ema_fast"] * (1 + tol)) & (d["close"] > d["ema_fast"]) & d["rsi"].between(40, 65)
    short_ok = downtrend & (d["high"] >= d["ema_fast"] * (1 - tol)) & (d["close"] < d["ema_fast"]) & d["rsi"].between(35, 60)

    side = np.where(long_ok, LONG, np.where(short_ok, SHORT, 0))
    entry = d["close"]
    risk = d["atr"] * cfg.atr_stop_mult
    return pd.DataFrame(
        {
            "side": side,
            "entry": entry,
            "stop": entry - side * risk,
            "take_profit": entry + side * risk * cfg.reward_risk,
            "atr": d["atr"],
        },
        index=d.index,
    )


def latest_signal(symbol: str, df: pd.DataFrame, cfg: Config) -> Signal | None:
    """Signal sur la dernière bougie clôturée, ou None."""
    row = compute_signals(df, cfg).iloc[-1]
    if row["side"] == 0:
        return None
    return Signal(
        symbol=symbol,
        interval=cfg.interval,
        time=df.index[-1],
        side="LONG" if row["side"] == LONG else "SHORT",
        entry=float(row["entry"]),
        stop=float(row["stop"]),
        take_profit=float(row["take_profit"]),
    )
