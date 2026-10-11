# Trading Bot — signaux, stop-loss / take-profit et brief matinal

Bot d'**alertes** : il surveille des marchés, détecte des points d'entrée et t'envoie
chaque signal avec **entrée, stop-loss, take-profit, % de gain/perte potentiel et
taille de position** calculée sur ton risque. Tu places l'ordre toi-même.

Chaque heure, il envoie un **brief** : prix, variation 24 h, tendance, RSI, volatilité,
supports/résistances, signaux actifs et **actualités**.

Tu peux lui écrire sur Telegram : `/brief` (brief maintenant), `/prix`, `/status`, `/aide`.

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

## Utiliser avec XM (signaux seulement)

Le bot ne passe aucun ordre. Il t'envoie l'alerte, tu places l'ordre dans XM.

- **Données forex** : Yahoo fournit les paires en `SYMBOLE=X` (ex. `EURUSD=X`, `GBPUSD=X`,
  `USDJPY=X`). Ce sont des cours moyens, pas les cours XM : l'écart (spread) de XM et le
  décalage de prix peuvent déplacer ton entrée. Vérifie le prix dans MT4/MT5 avant d'ordonner.
- **Lancer sur des paires forex** :
  ```bash
  python -m trading_bot --provider yahoo --symbols EURUSD=X,GBPUSD=X,USDJPY=X scan
  python -m trading_bot --provider yahoo --symbols EURUSD=X,GBPUSD=X,USDJPY=X run
  ```
- **Taille** : l'alerte donne un nombre d'« unités » de la devise de base. Dans XM, un lot
  standard = 100 000 unités ; convertis avant d'ordonner. Le risque fixé reste celui de
  `capital` × `risk_per_trade` (1 % par défaut).
- **Levier** : XM propose un fort effet de levier. Une perte de stop peut être amplifiée
  si tu prends une taille trop grande. Commence sur un compte démo XM.
- Le backtest peut aussi tourner sur Yahoo : `python -m trading_bot --provider yahoo --symbols EURUSD=X backtest`.

## Intégration TradingView

Le dossier `tradingview/` contient `bot_signals.pine` : le même indicateur que le bot,
affiché sur ton graphique, qui envoie une alerte JSON à chaque signal clôturé.

1. Dans TradingView : **Pine Editor** → colle le contenu de `bot_signals.pine` → **Ajouter au graphique**.
   Remplace `VOTRE_SECRET` dans le script par la valeur de `TV_WEBHOOK_SECRET`.
2. Crée une alerte : condition **Bot Signals → Any alert() function call**,
   fréquence **Once Per Bar Close**, **Notifications → Webhook URL** =
   `https://<ton-domaine>/tradingview`.
3. Sur ton serveur :
   ```bash
   export TV_WEBHOOK_SECRET='un-secret-long-et-aleatoire'
   python -m trading_bot webhook --host 0.0.0.0 --port 8080
   ```
   TradingView doit atteindre le bot depuis Internet (ports 80 ou 443 uniquement) :
   mets un reverse proxy HTTPS (Caddy, nginx) devant le port 8080.

Le bot recalcule stop-loss et take-profit à partir de l'ATR envoyé par l'alerte, avec les
mêmes règles que `config.py`, puis notifie. Un même signal n'est notifié qu'une fois.
Sans secret valide, le webhook répond 401 ; sans `TV_WEBHOOK_SECRET`, il refuse de démarrer.

> Le script Pine n'a pas pu être compilé ni exécuté dans TradingView pendant le développement.
> Vérifie sur un graphique qu'il affiche les mêmes signaux que `python -m trading_bot scan`
> sur la même période. Les moyennes peuvent différer légèrement à l'amorçage (historique court).

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
- L'intégration TradingView dépend d'une URL publique HTTPS et n'a pas été testée contre un vrai compte TradingView.
- Une seule position à la fois par paire ; pas de gestion de corrélation entre paires.
