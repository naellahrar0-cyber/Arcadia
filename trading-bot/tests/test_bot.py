import numpy as np
import pandas as pd
import pytest

from trading_bot.backtest import backtest, close_trade
from trading_bot.brief import snapshot
from trading_bot.config import Config
import trading_bot.data as data
from trading_bot.data import BinanceProvider, CSVProvider
from trading_bot.indicators import atr, rsi
from trading_bot.messages import format_brief, format_signal
from trading_bot.risk import position_size
from trading_bot.runner import scan
from trading_bot.state import State
from trading_bot.strategy import LONG, SHORT, Signal, compute_signals, latest_signal


def make_ohlc(n=800, seed=0, drift=0.0, vol=0.01, start=100.0):
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    open_ = np.concatenate([[start], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def send(self, text):
        self.messages.append(text)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_indicator_ranges():
    df = make_ohlc()
    r = rsi(df["close"], 14).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    assert (atr(df, 14).dropna() > 0).all()


def test_signal_levels_are_coherent():
    cfg = Config()
    sigs = compute_signals(make_ohlc(n=1500, seed=3, drift=0.001), cfg)
    longs, shorts = sigs[sigs["side"] == LONG], sigs[sigs["side"] == SHORT]
    assert len(longs) + len(shorts) > 0
    assert (longs["stop"] < longs["entry"]).all() and (longs["take_profit"] > longs["entry"]).all()
    assert (shorts["stop"] > shorts["entry"]).all() and (shorts["take_profit"] < shorts["entry"]).all()
    if len(longs):
        ratio = (longs["take_profit"] - longs["entry"]) / (longs["entry"] - longs["stop"])
        assert np.allclose(ratio, cfg.reward_risk)


def test_position_size_risks_fixed_amount():
    qty, notional, risk = position_size(1000, 0.01, entry=100, stop=95)
    assert risk == pytest.approx(10)
    assert qty == pytest.approx(2)
    assert notional == pytest.approx(200)


def test_close_trade_is_fee_aware():
    ts = pd.Timestamp("2026-01-01", tz="UTC")
    pos = {"i": 0, "time": ts, "side": LONG, "entry": 100.0, "stop": 95.0, "tp": 110.0}
    t = close_trade(pos, 5, ts, 110.0, "TP", fee=0.001)
    assert t["return_pct"] == pytest.approx((0.10 - 0.002) * 100)
    assert t["r"] == pytest.approx((0.10 - 0.002) / 0.05)


def test_backtest_summary_is_consistent():
    res = backtest(make_ohlc(n=1500, seed=3, drift=0.001), Config())
    s = res.summary
    assert s["trades"] == len(res.trades) > 0
    assert 0 <= s["win_rate_pct"] <= 100
    assert s["max_drawdown_pct"] <= 0
    assert set(s["exits"]) <= {"TP", "SL", "TIME"}


def test_binance_drops_forming_candle(monkeypatch):
    rows = [[i * 3_600_000, "1", "2", "0.5", str(i + 1), "10", i * 3_600_000 + 3_599_999,
             "0", "0", "0", "0", "0"] for i in range(5)]
    monkeypatch.setattr(data.requests, "get", lambda *a, **k: FakeResponse(rows))
    df = BinanceProvider().fetch("BTCUSDT", "1h", 3)
    assert len(df) == 3
    assert df["close"].iloc[-1] == 4.0  # la bougie 5 (en cours) est écartée


def test_csv_provider(tmp_path):
    make_ohlc(n=50).reset_index().rename(columns={"index": "timestamp"}).to_csv(tmp_path / "TEST_1h.csv", index=False)
    df = CSVProvider(tmp_path).fetch("TEST", "1h", 10)
    assert len(df) == 10 and list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_format_signal_shows_levels_and_percentages():
    sig = Signal("BTCUSDT", "1h", pd.Timestamp("2026-01-01 12:00", tz="UTC"), "LONG", 100.0, 98.0, 104.0)
    text = format_signal(sig, Config())
    assert "SIGNAL LONG — BTCUSDT" in text
    assert "(-2.00 %)" in text and "(+4.00 %)" in text
    assert "1 : 2.0" in text


def test_brief_lists_every_symbol():
    cfg = Config()
    snaps = [snapshot(s, make_ohlc(seed=i), cfg) for i, s in enumerate(["BTCUSDT", "ETHUSDT"])]
    text = format_brief(snaps, [], cfg, pd.Timestamp("2026-01-01 08:00").to_pydatetime())
    assert "BTCUSDT" in text and "ETHUSDT" in text
    assert "Aucun signal" in text
    assert "Données indisponibles" not in text


def test_brief_reports_failed_symbols():
    text = format_brief([], [], Config(), pd.Timestamp("2026-01-01 08:00").to_pydatetime(), ["BTCUSDT"])
    assert "Données indisponibles : BTCUSDT" in text


def test_scan_never_notifies_same_signal_twice(tmp_path, monkeypatch):
    cfg = Config(symbols=["TEST"], state_file=str(tmp_path / "s.json"), log_file=str(tmp_path / "l.log"))
    sig = Signal("TEST", "1h", pd.Timestamp("2026-01-01", tz="UTC"), "LONG", 100.0, 98.0, 104.0)
    monkeypatch.setattr("trading_bot.runner.latest_signal", lambda s, df, c: sig)

    class Provider:
        def fetch(self, symbol, interval, limit):
            return make_ohlc(n=50)

    notifier, state = FakeNotifier(), State(cfg.state_file)
    scan(cfg, Provider(), notifier, state)
    scan(cfg, Provider(), notifier, State(cfg.state_file))  # relecture de l'état sur disque
    assert len(notifier.messages) == 1


def test_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    State(path).mark("k1")
    assert State(path).seen("k1") and not State(path).seen("k2")
