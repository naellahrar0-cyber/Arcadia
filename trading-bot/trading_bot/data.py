"""Fournisseurs de données de marché : bougies OHLCV indexées en UTC.

Règle commune : seules les bougies CLÔTURÉES sont renvoyées. La bougie en cours
est retirée, sinon un signal pourrait disparaître avant la fin de la bougie.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
HEADERS = {"User-Agent": "Mozilla/5.0 (trading-bot)"}


def bars_per_day(interval: str) -> int:
    return 1440 // INTERVAL_MINUTES[interval]


def _closed_only(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    return df.iloc[:-1].tail(limit)  # la dernière ligne est la bougie en cours


class BinanceProvider:
    """Klines publiques Binance (sans clé API). Idéal pour les cryptos, 24/7."""

    url = "https://api.binance.com/api/v3/klines"

    def fetch(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        resp = requests.get(
            self.url,
            params={"symbol": symbol, "interval": interval, "limit": min(limit + 1, 1000)},
            timeout=15,
        )
        resp.raise_for_status()
        cols = ["open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]
        df = pd.DataFrame(resp.json(), columns=cols)
        df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return _closed_only(df, limit)


class YahooProvider:
    """Chart API Yahoo Finance (actions, ETF, forex, indices). Usage personnel uniquement."""

    url = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    ranges = {"15m": "60d", "1h": "730d", "1d": "5y"}

    def fetch(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        if interval not in self.ranges:
            raise ValueError(f"Intervalle {interval} non supporté par Yahoo : {list(self.ranges)}")
        resp = requests.get(
            self.url.format(symbol=symbol),
            params={"interval": interval, "range": self.ranges[interval]},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        df = pd.DataFrame(
            {k: quote[k] for k in ("open", "high", "low", "close", "volume")},
            index=pd.to_datetime(result["timestamp"], unit="s", utc=True),
        ).dropna(subset=["open", "high", "low", "close"])
        return _closed_only(df, limit)


class CSVProvider:
    """Fichiers locaux <SYMBOL>_<INTERVAL>.csv (colonnes : timestamp,open,high,low,close,volume)."""

    def __init__(self, directory: str):
        self.directory = Path(directory)

    def fetch(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        path = self.directory / f"{symbol}_{interval}.csv"
        df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
        df.index = pd.to_datetime(df.index, utc=True)
        return df[["open", "high", "low", "close", "volume"]].astype(float).tail(limit)


def get_provider(cfg) -> BinanceProvider | YahooProvider | CSVProvider:
    if cfg.provider == "binance":
        return BinanceProvider()
    if cfg.provider == "yahoo":
        return YahooProvider()
    if cfg.provider == "csv":
        return CSVProvider(cfg.csv_dir)
    raise ValueError(f"Fournisseur inconnu : {cfg.provider}")
