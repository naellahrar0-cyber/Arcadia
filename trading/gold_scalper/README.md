# XAUUSD scalping engine (research)

Python script that generates scalping signals (BUY / SELL) on gold, backtests them
honestly, filters them with a small AI model, and draws the chart.

## Install

    pip install pandas numpy

## Run

    python gold_scalper.py --synthetic --live          # demo on simulated data
    python gold_scalper.py --csv xauusd_m5.csv --live  # your own 5-minute OHLC data

CSV columns: `time,open,high,low,close` (UTC). Or fetch directly: `python gold_scalper.py --tradingview --live` (needs `pip install tvdatafeed`; optional `TV_USER` and `TV_PASS` env vars). Other sources: MT5 or Dukascopy exports.

Outputs in `gold_out/`: `chart.html` (candles, EMAs, buy/sell markers, SL/TP, equity),
`trades.csv`, `report.json`.

## How it works

1. **Signal**: EMA 9 crosses EMA 21 in the direction of the EMA 200 trend, RSI in a
   momentum band, London + New York session only, minimum ATR.
2. **Risk**: stop = 1 ATR, target = 1.5 ATR, 2-hour time stop, 0.30 USD round-trip cost,
   1% equity risked per trade.
3. **AI filter**: logistic regression trained only on trades that closed before the split
   date, then used to skip low-probability signals.
4. **Validation**: all reported numbers are out-of-sample (after the split).

## Limits

- No strategy wins 90% of trades. Expect results close to the costs on real data.
- Parameters are not optimised here. Optimising them on the same data overfits.
- Live mode prints a signal only. It does not send orders. Test on a demo account first.
