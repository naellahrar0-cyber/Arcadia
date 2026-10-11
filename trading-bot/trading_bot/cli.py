"""Ligne de commande : python -m trading_bot <scan|brief|run|backtest>."""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .backtest import backtest
from .config import Config
from .data import get_provider
from .notify import Notifier
from .runner import morning_brief, run_forever, scan
from .state import State


def _backtest(cfg: Config, provider, only: str | None) -> int:
    symbols = [only] if only else cfg.symbols
    header = f"{'Paire':<12}{'Trades':>7}{'Gain %':>9}{'Win %':>8}{'R moy.':>8}{'PF':>7}{'Max DD %':>10}{'SL/TP/Temps':>14}"
    print(header)
    print("-" * len(header))
    for symbol in symbols:
        df = provider.fetch(symbol, cfg.interval, cfg.backtest_bars)
        s = backtest(df, cfg).summary
        exits = s["exits"]
        exit_txt = f"{exits.get('SL', 0)}/{exits.get('TP', 0)}/{exits.get('TIME', 0)}"
        print(f"{symbol:<12}{s['trades']:>7}{s['total_return_pct']:>9.2f}{s['win_rate_pct']:>8.1f}"
              f"{s['avg_r']:>8.3f}{s['profit_factor']:>7.2f}{s['max_drawdown_pct']:>10.2f}{exit_txt:>14}")
    print("\nBacktest historique uniquement : aucune garantie pour le futur. Frais et glissement simplifiés.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading_bot", description="Alertes de signaux + brief matinal")
    parser.add_argument("--provider", choices=["binance", "yahoo", "csv"], help="Source de données (défaut : config)")
    parser.add_argument("--symbols", nargs="+", help="Remplace la liste de paires (ex. EURUSD=X GBPUSD=X pour XM via Yahoo)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="Cherche les signaux sur la dernière bougie clôturée et notifie")
    sub.add_parser("brief", help="Envoie le brief du marché maintenant")
    sub.add_parser("telegram-test", help="Envoie un message de test pour valider Telegram")
    sub.add_parser("run", help="Boucle continue : brief quotidien + scans réguliers")
    bt = sub.add_parser("backtest", help="Teste la stratégie sur l'historique")
    bt.add_argument("--symbol", help="Une seule paire (défaut : toutes celles de la config)")
    wh = sub.add_parser("webhook", help="Reçoit les alertes TradingView et notifie les signaux")
    wh.add_argument("--host", help="Adresse d'écoute (défaut : 127.0.0.1)")
    wh.add_argument("--port", type=int, help="Port d'écoute (défaut : 8080)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config()
    if args.provider:
        cfg.provider = args.provider
    if args.symbols:
        cfg.symbols = args.symbols
    provider = get_provider(cfg)

    if args.command == "backtest":
        return _backtest(cfg, provider, args.symbol)

    notifier, state = Notifier(cfg), State(cfg.state_file)
    if args.command == "webhook":
        from .webhook import make_server

        if args.host:
            cfg.webhook_host = args.host
        if args.port:
            cfg.webhook_port = args.port
        if not cfg.tv_secret:
            parser.error("définissez TV_WEBHOOK_SECRET avant de lancer le webhook")
        server = make_server(cfg, notifier, state)
        logging.info("Webhook à l'écoute sur http://%s:%s/tradingview", *server.server_address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    elif args.command == "scan":
        sent = scan(cfg, provider, notifier, state)
        print(f"{len(sent)} nouveau(x) signal(aux).")
    elif args.command == "telegram-test":
        if not notifier.telegram_enabled:
            parser.error("définissez TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID (voir README)")
        try:
            notifier.send("✅ Test Telegram du bot : si tu lis ce message, la configuration fonctionne.")
        except requests.RequestException as exc:
            # Ne pas afficher l'exception complète : son URL contient le token
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 404:
                parser.error("Telegram ne reconnaît pas le token. Vérifie-le (ou révoque-le et refais-en un).")
            if status == 400:
                parser.error("Telegram refuse le chat ID. Vérifie-le : il doit venir de getUpdates.")
            parser.error(f"Envoi impossible vers Telegram ({type(exc).__name__}). Vérifie la connexion internet.")
        print("Message de test envoyé.")
    elif args.command == "brief":
        morning_brief(cfg, provider, notifier, datetime.now(ZoneInfo(cfg.timezone)))
    elif args.command == "run":
        run_forever(cfg, provider, notifier, state)
    return 0
