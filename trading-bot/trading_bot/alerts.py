"""Alertes de changement de marché, calendrier économique et biais indicatif des actualités.

Le biais des actualités repose sur des mots-clés : c'est un indice, pas une analyse.
"""
from __future__ import annotations

import logging
import re

import pandas as pd
import requests

from .config import Config
from .strategy import add_indicators

log = logging.getLogger(__name__)
CURRENCIES = {"EUR", "USD", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"}
BULLISH = ("rise", "rally", "surge", "jump", "gain", "strong", "beat", "higher", "record", "boost")
BEARISH = ("fall", "drop", "slump", "plunge", "weak", "miss", "lower", "fear", "crisis", "tumble", "decline")


def regime_alerts(symbol: str, df: pd.DataFrame, cfg: Config) -> list[str]:
    """Volatilité anormale ou cassure de la moyenne 200 sur la dernière bougie clôturée."""
    if len(df) < cfg.ema_trend + 60:
        return []
    d = add_indicators(df, cfg)
    alerts = []
    atr_pct = d["atr"] / d["close"] * 100
    ratio = atr_pct.iloc[-1] / atr_pct.iloc[-51:-1].median()
    if ratio >= 2:
        alerts.append(f"Volatilité x{ratio:.1f} par rapport à la normale")
    above_now = d["close"].iloc[-1] > d["ema_trend"].iloc[-1]
    above_prev = d["close"].iloc[-2] > d["ema_trend"].iloc[-2]
    if above_now != above_prev:
        alerts.append("Cassure de la moyenne 200 : " + ("passage au-dessus (haussier)" if above_now
                                                       else "passage en dessous (baissier)"))
    return alerts


def headline_bias(titles: list[str]) -> str:
    score = 0
    for title in titles:
        low = title.lower()
        score += sum(bool(re.search(rf"\b{w}", low)) for w in BULLISH)
        score -= sum(bool(re.search(rf"\b{w}", low)) for w in BEARISH)
    if score >= 2:
        return "haussier"
    if score <= -2:
        return "baissier"
    return "neutre"


def currencies_for(symbol: str) -> set[str]:
    base = symbol.replace("=X", "")
    found = {base[:3], base[3:6]} & CURRENCIES
    return found or {"USD"}


def fetch_events(url: str) -> list[dict]:
    """Calendrier économique JSON : une liste d'objets avec title, country, impact, date."""
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    events = []
    for item in resp.json():
        if str(item.get("impact", "")).lower() != "high":
            continue
        ts = pd.Timestamp(item["date"])
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        events.append({"title": item.get("title", ""), "country": item.get("country", ""), "time": ts})
    return events


def upcoming_alerts(events: list[dict], symbols: list[str], now: pd.Timestamp, minutes: int) -> list[dict]:
    wanted = set().union(*(currencies_for(s) for s in symbols)) if symbols else set()
    return [ev for ev in events
            if ev["country"] in wanted and pd.Timedelta(0) <= ev["time"] - now <= pd.Timedelta(minutes=minutes)]
