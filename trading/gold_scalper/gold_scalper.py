#!/usr/bin/env python3
"""
Gold (XAUUSD) scalping engine: rule-based signals + AI filter + backtest + chart.

Usage:
  python gold_scalper.py --synthetic                 # demo on simulated data
  python gold_scalper.py --csv xauusd_m5.csv         # your own OHLC data
  python gold_scalper.py --csv xauusd_m5.csv --live  # signal on the last closed bar
  python gold_scalper.py --tradingview --live        # download XAUUSD M5 from TradingView

CSV format: columns time,open,high,low,close (time in UTC, e.g. 5-minute bars).
Outputs go to ./gold_out/ : trades.csv, report.json, chart.html

Research tool only. It does not place orders and cannot guarantee any win rate.
"""
import argparse
import html
import json
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Config:
    ema_fast: int = 9
    ema_slow: int = 21
    ema_trend: int = 200
    rsi_len: int = 14
    atr_len: int = 14
    sl_atr: float = 1.0           # stop-loss distance in ATR
    tp_atr: float = 1.5           # take-profit distance in ATR (RR = 1.5)
    max_hold_bars: int = 24       # time stop (24 x M5 = 2 hours)
    cost: float = 0.30            # spread + slippage per round trip, in USD
    risk_per_trade: float = 0.01  # 1% of equity risked per trade
    start_equity: float = 10_000.0
    session_utc: tuple = (7, 20)  # London open to New York close
    min_atr: float = 0.5          # skip dead markets (ATR in USD)
    cooldown_bars: int = 3
    ai_threshold: float = 0.55    # minimum AI probability of a winning trade


# ----------------------------------------------------------------- data

def load_csv(path):
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert(None)
    df = df.set_index("time").sort_index()[["open", "high", "low", "close"]]
    return df.astype(float).dropna()


def fetch_tradingview(symbol="XAUUSD", exchange="OANDA", interval="5m", n_bars=5000):
    """Download OHLC bars from TradingView with the community `tvdatafeed` package.
    Install with: pip install tvdatafeed. Login is optional; set TV_USER and TV_PASS to use one."""
    try:
        from tvDatafeed import Interval, TvDatafeed
    except ImportError as e:
        raise SystemExit("Missing package: run 'pip install tvdatafeed' to use --tradingview") from e
    tv_interval = {"1m": Interval.in_1_minute, "5m": Interval.in_5_minute,
                   "15m": Interval.in_15_minute, "1h": Interval.in_1_hour}[interval]
    user, pwd = os.environ.get("TV_USER"), os.environ.get("TV_PASS")
    tv = TvDatafeed(user, pwd) if user and pwd else TvDatafeed()
    raw = tv.get_hist(symbol=symbol, exchange=exchange, interval=tv_interval, n_bars=n_bars)
    if raw is None or raw.empty:
        raise SystemExit(f"TradingView returned no data for {exchange}:{symbol}")
    df = raw[["open", "high", "low", "close"]].astype(float).dropna()
    df.index = pd.to_datetime(df.index)  # TradingView timestamps are treated as UTC
    return df.sort_index()


def synthetic_gold(n=20_000, seed=7):
    """Simulated XAUUSD M5 data: GARCH volatility, intraday seasonality, drift regimes."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-06", periods=n * 2, freq="5min")
    idx = idx[idx.dayofweek < 5][:n]
    hours = idx.hour + idx.minute / 60
    season = 1 + 0.8 * np.exp(-((hours - 14.0) ** 2) / 6)  # London/NY overlap is busier
    drift = 0.000015 * np.sign(np.sin(np.arange(n) / 3000))
    z = rng.standard_normal(n)
    var = np.empty(n)
    ret = np.empty(n)
    var[0] = 2.5e-7
    ret[0] = 0.0
    raw = np.empty(n)  # GARCH shock before seasonality, keeps the variance process stable
    raw[0] = 0.0
    for t in range(1, n):
        var[t] = 5e-9 + 0.08 * raw[t - 1] ** 2 + 0.9 * var[t - 1]
        raw[t] = np.sqrt(var[t]) * z[t]
        ret[t] = drift[t] + raw[t] * season[t]
    close = 2300 * np.exp(np.cumsum(ret))
    opn = np.r_[close[0], close[:-1]]
    sd = np.sqrt(var) * season * close
    high = np.maximum(opn, close) + np.abs(rng.normal(0, 0.4, n)) * sd
    low = np.minimum(opn, close) - np.abs(rng.normal(0, 0.4, n)) * sd
    return pd.DataFrame({"open": opn, "high": high, "low": low, "close": close}, index=idx).round(2)


# ----------------------------------------------------------- indicators

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n):
    pc = df["close"].shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def add_indicators(df, cfg):
    df = df.copy()
    df["ema_f"] = ema(df.close, cfg.ema_fast)
    df["ema_s"] = ema(df.close, cfg.ema_slow)
    df["ema_t"] = ema(df.close, cfg.ema_trend)
    df["rsi"] = rsi(df.close, cfg.rsi_len)
    df["atr"] = atr(df, cfg.atr_len)
    return df


def raw_signals(df, cfg):
    """Trend-following EMA cross, filtered by session, volatility, 200 EMA bias and RSI."""
    hour = df.index.hour
    in_session = (hour >= cfg.session_utc[0]) & (hour < cfg.session_utc[1])
    ok = in_session & (df.atr >= cfg.min_atr)
    prev_f, prev_s = df.ema_f.shift(1), df.ema_s.shift(1)
    long_ = ok & (prev_f <= prev_s) & (df.ema_f > df.ema_s) & (df.close > df.ema_t) & df.rsi.between(50, 70)
    short_ = ok & (prev_f >= prev_s) & (df.ema_f < df.ema_s) & (df.close < df.ema_t) & df.rsi.between(30, 50)
    sig = {int(i): 1 for i in np.flatnonzero(long_.values)}
    sig.update({int(i): -1 for i in np.flatnonzero(short_.values)})
    return sig


# ------------------------------------------------------------- backtest

def simulate(df, signals, cfg):
    """Bar-by-bar simulation. One position at a time, entry at next bar open.
    If SL and TP are both touched inside one bar, SL is assumed first (conservative)."""
    o, h, l, c, a = (df[k].values for k in ("open", "high", "low", "close", "atr"))
    idx = df.index
    trades, busy_until, last_entry = [], -1, -10**9
    for i, side in sorted(signals.items()):
        if i <= busy_until or i - last_entry < cfg.cooldown_bars or i + 1 >= len(df):
            continue
        entry = o[i + 1] + side * cfg.cost / 2
        risk = cfg.sl_atr * a[i]
        sl, tp = entry - side * risk, entry + side * cfg.tp_atr * a[i]
        exit_px, exit_i, reason = None, None, "TIME"
        for j in range(i + 1, min(i + 1 + cfg.max_hold_bars, len(df))):
            hit_sl = l[j] <= sl if side == 1 else h[j] >= sl
            hit_tp = h[j] >= tp if side == 1 else l[j] <= tp
            if hit_sl:
                exit_px, exit_i, reason = sl, j, "SL"
                break
            if hit_tp:
                exit_px, exit_i, reason = tp, j, "TP"
                break
        if exit_px is None:
            exit_i = min(i + cfg.max_hold_bars, len(df) - 1)
            exit_px = c[exit_i]
        exit_px -= side * cfg.cost / 2
        pnl = side * (exit_px - entry)
        trades.append({
            "entry_time": idx[i + 1], "exit_time": idx[exit_i],
            "side": "BUY" if side == 1 else "SELL", "entry": round(entry, 2),
            "sl": round(sl, 2), "tp": round(tp, 2), "exit": round(exit_px, 2),
            "reason": reason, "R": round(pnl / risk, 3), "bar": i,
        })
        busy_until, last_entry = exit_i, i + 1
    return trades


def metrics(trades, cfg):
    if not trades:
        return {"trades": 0}
    R = np.array([t["R"] for t in trades])
    gains, losses = R[R > 0].sum(), -R[R <= 0].sum()
    eq = np.r_[cfg.start_equity, cfg.start_equity * np.cumprod(1 + cfg.risk_per_trade * R)]
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    return {
        "trades": len(R),
        "win_rate_pct": round(100 * (R > 0).mean(), 2),
        "avg_R": round(R.mean(), 3),
        "profit_factor": round(gains / losses, 3) if losses > 0 else None,
        "max_drawdown_pct": round(100 * dd, 2),
        "final_equity": round(eq[-1], 2),
        "return_pct": round(100 * (eq[-1] / cfg.start_equity - 1), 2),
    }


# ------------------------------------------------------------- AI filter

DIRECTIONAL = [0, 1, 2, 3]  # features that flip sign for shorts


def feature_matrix(df):
    atr_ = df.atr
    X = pd.DataFrame({
        "rsi": df.rsi / 100 - 0.5,
        "trend_dist": (df.close - df.ema_t) / atr_,
        "cross_gap": (df.ema_f - df.ema_s) / atr_,
        "slope": (df.ema_s - df.ema_s.shift(5)) / atr_,
        "vol_regime": atr_ / atr_.rolling(100).mean() - 1,
        "hour_sin": np.sin(2 * np.pi * df.index.hour / 24),
        "hour_cos": np.cos(2 * np.pi * df.index.hour / 24),
    }, index=df.index).fillna(0)
    return X.clip(-5, 5).values


def sig_features(X, bar, side):
    f = X[bar].copy()
    f[DIRECTIONAL] *= side
    return f


def fit_logreg(X, y, lr=0.1, epochs=3000, l2=1e-3):
    """Logistic regression in numpy (no extra dependency). Returns predict(X) -> probability."""
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.c_[(X - mu) / sd, np.ones(len(X))]
    w = np.zeros(Z.shape[1])
    for _ in range(epochs):
        p = 1 / (1 + np.exp(-Z @ w))
        w -= lr * (Z.T @ (p - y) / len(y) + l2 * w)
    return lambda Xn: 1 / (1 + np.exp(-(np.c_[(Xn - mu) / sd, np.ones(len(Xn))] @ w)))


# ------------------------------------------------------------ reporting

def write_chart(df, trades, cfg, path, n):
    d = df.iloc[-n:]
    W, PH, EH, L, T = 1200, 460, 150, 60, 20
    lo, hi = d.low.min(), d.high.max()
    span = (hi - lo) or 1
    cw = (W - L - 20) / len(d)
    y = lambda p: T + (hi - p) / span * PH
    x = lambda k: L + (k + 0.5) * cw
    svg = [f'<svg viewBox="0 0 {W} {PH + EH + 80}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="11">']
    for k, (_, r) in enumerate(d.iterrows()):
        col = "#26a69a" if r.close >= r.open else "#ef5350"
        svg.append(f'<line x1="{x(k):.1f}" x2="{x(k):.1f}" y1="{y(r.high):.1f}" y2="{y(r.low):.1f}" stroke="{col}"/>')
        top, bot = y(max(r.open, r.close)), y(min(r.open, r.close))
        svg.append(f'<rect x="{x(k) - cw * 0.35:.1f}" y="{top:.1f}" width="{cw * 0.7:.1f}" height="{max(bot - top, 1):.1f}" fill="{col}"/>')
    for col, colour in (("ema_f", "#42a5f5"), ("ema_s", "#ffa726"), ("ema_t", "#ab47bc")):
        pts = " ".join(f"{x(k):.1f},{y(v):.1f}" for k, v in enumerate(d[col]))
        svg.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="1.2"/>')
    pos = {ts: k for k, ts in enumerate(d.index)}
    for t in trades:
        if t["entry_time"] not in pos:
            continue
        k0 = pos[t["entry_time"]]
        k1 = pos.get(t["exit_time"], len(d) - 1)
        for level, colour in ((t["tp"], "#2e7d32"), (t["sl"], "#c62828")):
            svg.append(f'<line x1="{x(k0):.1f}" x2="{x(k1):.1f}" y1="{y(level):.1f}" y2="{y(level):.1f}" stroke="{colour}" stroke-dasharray="4 3" stroke-width="1"/>')
        if t["side"] == "BUY":
            ty = y(d.low.iloc[k0]) + 14
            pts = f"{x(k0):.1f},{ty:.1f} {x(k0) - 6:.1f},{ty + 10:.1f} {x(k0) + 6:.1f},{ty + 10:.1f}"
            svg.append(f'<polygon points="{pts}" fill="#2e7d32"><title>BUY {t["entry"]} | TP {t["tp"]} | SL {t["sl"]} | {t["reason"]} {t["R"]}R</title></polygon>')
        else:
            ty = y(d.high.iloc[k0]) - 14
            pts = f"{x(k0):.1f},{ty:.1f} {x(k0) - 6:.1f},{ty - 10:.1f} {x(k0) + 6:.1f},{ty - 10:.1f}"
            svg.append(f'<polygon points="{pts}" fill="#c62828"><title>SELL {t["entry"]} | TP {t["tp"]} | SL {t["sl"]} | {t["reason"]} {t["R"]}R</title></polygon>')
    for k in range(0, len(d), max(1, len(d) // 8)):
        svg.append(f'<text x="{x(k):.1f}" y="{PH + T + 14}" text-anchor="middle">{d.index[k]:%d %b %H:%M}</text>')
    # equity panel
    eq = [cfg.start_equity]
    for t in trades:
        eq.append(eq[-1] * (1 + cfg.risk_per_trade * t["R"]))
    base = PH + T + 40
    if len(eq) > 1:
        emin, emax = min(eq), max(eq)
        es = (emax - emin) or 1
        pts = " ".join(f"{L + k * (W - L - 20) / max(len(eq) - 1, 1):.1f},{base + EH - (v - emin) / es * EH:.1f}" for k, v in enumerate(eq))
        svg.append(f'<text x="{L}" y="{base - 6}">Equity (out-of-sample)</text>')
        svg.append(f'<polyline points="{pts}" fill="none" stroke="#1565c0" stroke-width="1.5"/>')
    svg.append("</svg>")
    legend = ("<p><span style='color:#42a5f5'>EMA 9</span> · <span style='color:#ffa726'>EMA 21</span> · "
              "<span style='color:#ab47bc'>EMA 200</span> · ▲ buy · ▼ sell · dashed green = TP · dashed red = SL</p>")
    body = f"""<!doctype html><html><head><meta charset="utf-8"><title>Gold scalper</title>
<style>body{{font-family:sans-serif;margin:20px;background:#fff;color:#222}}</style></head>
<body><h2>XAUUSD scalping backtest</h2>{legend}{''.join(svg)}
<p>Last {n} bars shown. Each marker is a trade taken by the AI-filtered strategy.</p></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def print_metrics(name, m):
    print(f"\n[{name}]")
    if m.get("trades", 0) == 0:
        print("  no trades")
        return
    for k, v in m.items():
        print(f"  {k:<18} {v}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="OHLC CSV file (time,open,high,low,close)")
    ap.add_argument("--synthetic", action="store_true", help="use simulated data")
    ap.add_argument("--tradingview", action="store_true", help="download data from TradingView")
    ap.add_argument("--tv-symbol", default="XAUUSD")
    ap.add_argument("--tv-exchange", default="OANDA")
    ap.add_argument("--tv-interval", default="5m", choices=["1m", "5m", "15m", "1h"])
    ap.add_argument("--tv-bars", type=int, default=5000)
    ap.add_argument("--out", default="gold_out")
    ap.add_argument("--split", type=float, default=0.6, help="fraction of data used to train the AI filter")
    ap.add_argument("--bars", type=int, default=1000, help="candles shown in chart")
    ap.add_argument("--live", action="store_true", help="print the signal on the last bar")
    args = ap.parse_args()
    if not (args.csv or args.synthetic or args.tradingview):
        ap.error("give --csv FILE, --synthetic or --tradingview")

    cfg = Config()
    if args.tradingview:
        raw = fetch_tradingview(args.tv_symbol, args.tv_exchange, args.tv_interval, args.tv_bars)
        os.makedirs(args.out, exist_ok=True)
        raw.to_csv(os.path.join(args.out, "tradingview_bars.csv"))  # reuse later with --csv
        print(f"Downloaded {len(raw)} bars from TradingView ({args.tv_exchange}:{args.tv_symbol}, {args.tv_interval})")
    elif args.csv:
        raw = load_csv(args.csv)
    else:
        raw = synthetic_gold()
    df = add_indicators(raw, cfg).dropna(subset=["ema_t", "rsi", "atr"])
    X = feature_matrix(df)
    split_time = df.index[int(len(df) * args.split)]
    sig = raw_signals(df, cfg)

    # 1) AI filter: learn from trades that CLOSED before the split only
    train = [t for t in simulate(df, sig, cfg) if t["exit_time"] < split_time]
    model = None
    if len(train) >= 30:
        Xtr = np.array([sig_features(X, t["bar"], 1 if t["side"] == "BUY" else -1) for t in train])
        ytr = np.array([1.0 if t["R"] > 0 else 0.0 for t in train])
        model = fit_logreg(Xtr, ytr)
        print(f"AI filter trained on {len(train)} past trades (win rate {100 * ytr.mean():.1f}%)")
    else:
        print(f"Not enough past trades to train AI filter ({len(train)} < 30): rules only.")

    # 2) Out-of-sample comparison (the only numbers you should trust)
    oos_sig = {i: s for i, s in sig.items() if df.index[i] >= split_time}
    oos_rule = simulate(df, oos_sig, cfg)
    if model is not None:
        keep = {i: s for i, s in oos_sig.items()
                if model(sig_features(X, i, s)[None, :])[0] >= cfg.ai_threshold}
        oos_final = simulate(df, keep, cfg)
    else:
        oos_final = oos_rule
    report = {
        "data": {"from": str(df.index[0]), "to": str(df.index[-1]), "bars": len(df), "split": str(split_time)},
        "out_of_sample_rules_only": metrics(oos_rule, cfg),
        "out_of_sample_rules_plus_ai": metrics(oos_final, cfg),
        "config": cfg.__dict__,
    }
    print_metrics("OOS rules only", report["out_of_sample_rules_only"])
    print_metrics("OOS rules + AI filter", report["out_of_sample_rules_plus_ai"])

    os.makedirs(args.out, exist_ok=True)
    pd.DataFrame(oos_final).to_csv(os.path.join(args.out, "trades.csv"), index=False)
    with open(os.path.join(args.out, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    write_chart(df, oos_final, cfg, os.path.join(args.out, "chart.html"), min(args.bars, len(df)))
    print(f"\nFiles written to {args.out}/ (trades.csv, report.json, chart.html)")

    # 3) Live signal on the last bar of the file
    if args.live:
        last = len(df) - 1
        if last in sig:
            side = sig[last]
            a = df.atr.iloc[last]
            entry = df.close.iloc[last]
            p = model(sig_features(X, last, side)[None, :])[0] if model else float("nan")
            sl = entry - side * cfg.sl_atr * a
            tp = entry + side * cfg.tp_atr * a
            print(f"\nLIVE SIGNAL {'BUY' if side == 1 else 'SELL'} at {entry:.2f}  SL {sl:.2f}  TP {tp:.2f}  AI prob {p:.2f}")
            if model is not None and p < cfg.ai_threshold:
                print("AI filter rejects this signal (prob below threshold) -> do not trade")
        else:
            print("\nNo signal on the last bar.")


if __name__ == "__main__":
    main()
