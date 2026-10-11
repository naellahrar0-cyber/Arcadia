"""Photographie du marché pour le brief matinal."""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .config import Config
from .data import bars_per_day
from .strategy import add_indicators


@dataclass(frozen=True)
class Snapshot:
    symbol: str
    price: float
    change_pct: float  # variation sur ~24 h
    trend: str  # "haussière", "baissière" ou "neutre"
    rsi: float
    atr_pct: float  # volatilité moyenne par bougie, en % du prix
    support: float  # plus bas des 20 dernières bougies (hors bougie courante)
    resistance: float  # plus haut des 20 dernières bougies (hors bougie courante)


def snapshot(symbol: str, df: pd.DataFrame, cfg: Config) -> Snapshot:
    d = add_indicators(df, cfg)
    last = d.iloc[-1]
    back = bars_per_day(cfg.interval)
    change = (last["close"] / d["close"].iloc[-1 - back] - 1) * 100 if len(d) > back else math.nan

    if last["close"] > last["ema_trend"] and last["ema_fast"] > last["ema_slow"]:
        trend = "haussière"
    elif last["close"] < last["ema_trend"] and last["ema_fast"] < last["ema_slow"]:
        trend = "baissière"
    else:
        trend = "neutre"

    window = d.iloc[-21:-1]
    return Snapshot(
        symbol=symbol,
        price=float(last["close"]),
        change_pct=float(change),
        trend=trend,
        rsi=float(last["rsi"]),
        atr_pct=float(last["atr"] / last["close"] * 100),
        support=float(window["low"].min()),
        resistance=float(window["high"].max()),
    )
