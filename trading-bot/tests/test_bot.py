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


def test_target_sizing_gains_target_at_take_profit():
    from trading_bot.risk import target_position_size

    qty, notional, loss = target_position_size(1.0, entry=100.0, take_profit=104.0, stop=98.0)
    assert qty * 4.0 == pytest.approx(1.0)  # gain au take-profit = cible
    assert loss == pytest.approx(0.5)  # perte au stop = cible / R:R (2)
    assert notional == pytest.approx(qty * 100.0)


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


def test_yahoo_forex_parse_drops_forming_candle(monkeypatch):
    payload = {"chart": {"result": [{
        "timestamp": [1_760_000_000 + i * 3600 for i in range(4)],
        "indicators": {"quote": [{"open": [1.10, 1.11, 1.12, None], "high": [1.11, 1.12, 1.13, None],
                                  "low": [1.09, 1.10, 1.11, None], "close": [1.105, 1.115, 1.125, None],
                                  "volume": [0, 0, 0, None]}]},
    }]}}
    monkeypatch.setattr(data.requests, "get", lambda *a, **k: FakeResponse(payload))
    df = data.YahooProvider().fetch("EURUSD=X", "1h", 10)
    assert len(df) == 2  # la 4e bougie (vide, en cours) est écartée
    assert df["close"].iloc[-1] == pytest.approx(1.115)


def test_csv_provider(tmp_path):
    make_ohlc(n=50).reset_index().rename(columns={"index": "timestamp"}).to_csv(tmp_path / "TEST_1h.csv", index=False)
    df = CSVProvider(tmp_path).fetch("TEST", "1h", 10)
    assert len(df) == 10 and list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_fmt_price_keeps_forex_precision():
    from trading_bot.messages import fmt_price

    assert fmt_price(1.12345) == "1.12345"
    assert fmt_price(158.28) == "158.280"
    assert fmt_price(67432.0) == "67 432.00"


def test_format_signal_shows_levels_and_percentages():
    sig = Signal("BTCUSDT", "1h", pd.Timestamp("2026-01-01 12:00", tz="UTC"), "LONG", 100.0, 98.0, 104.0)
    text = format_signal(sig, Config())
    assert "ENTRÉE EN POSITION — ACHAT (BUY) — BTCUSDT" in text
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
    fresh = pd.Timestamp.now(tz="UTC").floor("h") - pd.Timedelta(hours=1)
    sig = Signal("TEST", "1h", fresh, "LONG", 100.0, 98.0, 104.0)
    monkeypatch.setattr("trading_bot.runner.latest_signal", lambda s, df, c: sig)

    class Provider:
        def fetch(self, symbol, interval, limit):
            return make_ohlc(n=50)

    notifier, state = FakeNotifier(), State(cfg.state_file)
    scan(cfg, Provider(), notifier, state)
    scan(cfg, Provider(), notifier, State(cfg.state_file))  # relecture de l'état sur disque
    assert len(notifier.messages) == 1


def test_tradingview_long_payload_levels():
    from trading_bot.webhook import signal_from_payload

    cfg = Config(atr_stop_mult=1.5, reward_risk=2.0)
    sig = signal_from_payload({"secret": "x", "symbol": "btcusdt", "side": "long", "price": 100.0,
                               "atr": 2.0, "interval": "60", "time": "2026-10-11T14:00:00Z"}, cfg)
    assert sig.side == "LONG" and sig.symbol == "BTCUSDT" and sig.interval == "1h"
    assert sig.stop == pytest.approx(97.0) and sig.take_profit == pytest.approx(106.0)
    assert sig.time == pd.Timestamp("2026-10-11 14:00", tz="UTC")


def test_tradingview_short_payload_levels():
    from trading_bot.webhook import signal_from_payload

    sig = signal_from_payload({"symbol": "ETHUSDT", "side": "SHORT", "price": 100.0, "atr": 2.0,
                               "interval": "D", "time": 1_760_191_200_000}, Config())
    assert sig.stop == pytest.approx(103.0) and sig.take_profit == pytest.approx(94.0)
    assert sig.interval == "1d"


def test_tradingview_rejects_bad_payloads():
    from trading_bot.webhook import PayloadError, signal_from_payload

    for bad in ({"side": "LONG", "price": 1, "atr": 1},  # symbol manquant
                {"symbol": "A", "side": "BUY", "price": 1, "atr": 1},
                {"symbol": "A", "side": "LONG", "price": 0, "atr": 1},
                {"symbol": "A", "side": "LONG", "price": 1, "atr": 1, "interval": "7m"}):
        with pytest.raises(PayloadError):
            signal_from_payload(bad, Config())


def test_tradingview_secret_and_dedupe(tmp_path):
    from trading_bot.webhook import handle_payload

    notifier = FakeNotifier()
    state = State(tmp_path / "s.json")
    payload = {"secret": "good", "symbol": "BTCUSDT", "side": "LONG", "price": 100.0,
               "atr": 2.0, "interval": "1h", "time": "2026-10-11T14:00:00Z"}
    assert handle_payload(payload, Config(tv_secret=None), notifier, state)[0] == 503
    assert handle_payload(dict(payload, secret="bad"), Config(tv_secret="good"), notifier, state)[0] == 401
    assert handle_payload(payload, Config(tv_secret="good"), notifier, state) == (200, "signal notifié")
    assert handle_payload(payload, Config(tv_secret="good"), notifier, state) == (200, "doublon ignoré")
    assert len(notifier.messages) == 1


def test_webhook_http_end_to_end(tmp_path):
    import json as _json
    import threading
    import urllib.error
    import urllib.request

    from trading_bot.webhook import make_server

    cfg = Config(tv_secret="good", state_file=str(tmp_path / "s.json"))
    notifier = FakeNotifier()
    server = make_server(cfg, notifier, State(cfg.state_file), host="127.0.0.1", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/tradingview"
    body = _json.dumps({"secret": "good", "symbol": "BTCUSDT", "side": "SHORT", "price": 100.0,
                        "atr": 2.0, "interval": "60", "time": "2026-10-11T14:00:00Z"}).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200 and b"notifi" in resp.read()
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(urllib.request.Request(url, data=body.replace(b"good", b"nope")), timeout=5)
        assert err.value.code == 401
        assert len(notifier.messages) == 1 and "VENTE (SELL) — BTCUSDT (1h)" in notifier.messages[0]
    finally:
        server.shutdown()
        server.server_close()


def test_scan_ignores_stale_signal(tmp_path, monkeypatch):
    from trading_bot.runner import scan

    cfg = Config(symbols=["TEST"], state_file=str(tmp_path / "s.json"), log_file=str(tmp_path / "l.log"))
    old = Signal("TEST", "1h", pd.Timestamp("2026-01-01", tz="UTC"), "LONG", 100.0, 98.0, 104.0)
    monkeypatch.setattr("trading_bot.runner.latest_signal", lambda s, df, c: old)

    class Provider:
        def fetch(self, symbol, interval, limit):
            return make_ohlc(n=50)

    notifier = FakeNotifier()
    assert scan(cfg, Provider(), notifier, State(cfg.state_file)) == []
    assert notifier.messages == []


def test_entry_message_has_side_and_morocco_time():
    sig_long = Signal("EURUSD=X", "1h", pd.Timestamp("2026-10-11 14:00", tz="UTC"), "LONG", 1.1, 1.097, 1.106)
    sig_short = Signal("EURUSD=X", "1h", pd.Timestamp("2026-10-11 14:00", tz="UTC"), "SHORT", 1.1, 1.103, 1.094)
    text_long, text_short = format_signal(sig_long, Config()), format_signal(sig_short, Config())
    assert "ACHAT (BUY)" in text_long and "VENTE (SELL)" in text_short
    # L'heure affichée = fin de bougie (15:00 UTC) convertie dans le fuseau Africa/Casablanca
    expected = pd.Timestamp("2026-10-11 15:00", tz="UTC").tz_convert("Africa/Casablanca")
    assert f"Heure (Casablanca) : {expected:%d/%m/%Y %H:%M}" in text_long


def test_bot_answers_only_configured_chat(tmp_path, monkeypatch):
    from trading_bot import runner

    cfg = Config(telegram_token="t", telegram_chat_id="42", state_file=str(tmp_path / "s.json"))
    updates = [
        {"update_id": 10, "message": {"chat": {"id": 999}, "text": "hello"}},  # inconnu
        {"update_id": 11, "message": {"chat": {"id": 42}, "text": "/status"}},  # toi
    ]
    monkeypatch.setattr(runner, "get_updates", lambda token, offset=None, timeout=20: updates)
    notifier, state = FakeNotifier(), State(cfg.state_file)
    assert runner.answer_messages(cfg, state, notifier, pd.Timestamp.now(tz="UTC").to_pydatetime()) == 1
    assert len(notifier.messages) == 1 and "Bot actif" in notifier.messages[0]
    assert State(cfg.state_file).data["update_offset"] == 12


def test_telegram_error_never_shows_token(monkeypatch):
    import requests
    from trading_bot import notify

    def boom(url, **kwargs):
        raise requests.ConnectionError(f"failed for {url}")

    monkeypatch.setattr(notify.requests, "post", boom)
    with pytest.raises(notify.TelegramError) as err:
        notify.telegram_call("123:SECRETTOKEN", "sendMessage", chat_id=1, text="x")
    assert "SECRETTOKEN" not in str(err.value)


def test_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    State(path).mark("k1")
    assert State(path).seen("k1") and not State(path).seen("k2")
