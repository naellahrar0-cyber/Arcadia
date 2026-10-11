"""Configuration du bot. Les secrets viennent des variables d'environnement."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # Marché
    provider: str = "binance"  # binance | yahoo | csv
    symbols: list[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    interval: str = "1h"
    lookback: int = 500  # bougies clôturées utilisées pour les signaux
    backtest_bars: int = 1000  # bougies utilisées pour le backtest
    csv_dir: str = "data"  # dossier des CSV (provider=csv) : <SYMBOL>_<INTERVAL>.csv

    # Stratégie
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    rsi_period: int = 14
    atr_period: int = 14
    pullback_tolerance: float = 0.003  # 0,3 % autour de l'EMA rapide
    atr_stop_mult: float = 1.5  # stop-loss = 1,5 x ATR
    reward_risk: float = 2.0  # take-profit = 2 x distance du stop

    # Gestion du risque
    capital: float = 1000.0
    risk_per_trade: float = 0.01  # 1 % du capital risqué par trade
    target_profit: float | None = None  # si défini : taille calculée pour gagner ce montant au take-profit
    fee_per_side: float = 0.001  # frais par côté (0,1 %), utilisés par le backtest
    max_hold_bars: int = 48  # sortie au bout de N bougies si ni SL ni TP

    # Planning
    timezone: str = "Europe/Paris"  # planning du brief et des scans
    display_timezone: str = "Africa/Casablanca"  # heure affichée dans les messages
    brief_time: str = "08:00"
    scan_every_minutes: int = 15
    max_signal_age_bars: int = 2  # ignore un signal plus vieux que N bougies (évite les alertes périmées)

    # Notifications
    telegram_token: str | None = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str | None = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID"))
    state_file: str = "state.json"
    log_file: str = "signals.log"

    # Webhook TradingView (alertes envoyées par le script Pine)
    tv_secret: str | None = field(default_factory=lambda: os.getenv("TV_WEBHOOK_SECRET"))
    webhook_host: str = "127.0.0.1"  # 0.0.0.0 si derrière un reverse proxy HTTPS
    webhook_port: int = 8080
