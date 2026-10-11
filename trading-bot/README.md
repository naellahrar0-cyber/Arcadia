# Trading Bot — signaux, stop-loss / take-profit et brief matinal

Bot d'**alertes** : il surveille des marchés, détecte des points d'entrée et t'envoie
chaque signal avec **entrée, stop-loss, take-profit, % de gain/perte potentiel et
taille de position** calculée sur ton risque. Tu places l'ordre toi-même.

Chaque matin (08:00 Paris), il envoie aussi un **brief** : variation 24 h, tendance,
RSI, volatilité, supports/résistances et signaux actifs.

> ⚠️ Aucun bot ne garantit un profit. Le trading à effet de levier peut faire perdre
> plus que la mise. Commence par `backtest` puis en **compte démo / papier** avant
> tout argent réel. Ce code n'exécute aucun ordre.

## Stratégie

« Pullback dans la tendance » :

- **Long** : prix > EMA 200, EMA 20 > EMA 50, la bougie descend sur l'EMA 20 puis la
  reprend, RSI entre 40 et 65.
- **Short** : symétrique.
- **Stop-loss** = entrée ∓ 1,5 × ATR. **Take-profit** = 2 × la distance du stop (R/R 1:2).
- Calculée sur bougies **clôturées** uniquement (pas de signal qui disparaît).

Tous les paramètres sont dans `trading_bot/config.py`.

## Installation

```bash
cd trading-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # puis renseigne Telegram (optionnel)
```

## Utilisation

```bash
python -m trading_bot backtest                # teste la stratégie sur l'historique
python -m trading_bot backtest --symbol ETHUSDT
python -m trading_bot scan                    # cherche les signaux maintenant
python -m trading_bot brief                   # envoie le brief maintenant
python -m trading_bot run                     # mode continu : brief 08:00 + scans toutes les 15 min
python -m trading_bot --provider yahoo scan   # actions / forex (ex. symbol AAPL, EURUSD=X dans la config)
```

Sans Telegram configuré, les messages s'affichent dans le terminal et sont ajoutés à
`signals.log`.

## Notifications Telegram

1. Crée un bot avec **@BotFather** → récupère le token.
2. Envoie un message à ton bot, puis ouvre
   `https://api.telegram.org/bot<TOKEN>/getUpdates` pour lire ton `chat.id`.
3. Renseigne `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` dans `.env`
   (chargés depuis l'environnement, ex. `export $(cat .env | xargs)`).

## Faire tourner le bot 24/7

Le bot doit tourner en continu (VPS, Raspberry Pi, ou ton PC allumé). Exemple systemd :

```ini
[Service]
WorkingDirectory=/opt/trading-bot
EnvironmentFile=/opt/trading-bot/.env
ExecStart=/opt/trading-bot/.venv/bin/python -m trading_bot run
Restart=always
```

## Tests

```bash
pip install pytest && pytest
```

## Limites connues

- Les données viennent d'API publiques : elles peuvent avoir des trous ou des retards.
- Le backtest ignore le glissement de prix, les frais réels de ton broker et la
  liquidité. Les résultats passés ne préjugent pas des résultats futurs.
- Pas d'intégration TradingView (ses alertes passent par webhook, non implémenté ici).
- Une seule position à la fois par paire ; pas de gestion de corrélation entre paires.
