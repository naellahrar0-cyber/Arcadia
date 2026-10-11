#!/usr/bin/env bash
# Configure Telegram puis envoie un message de test.
# Le token est saisi de façon masquée et n'est enregistré nulle part.
set -e
cd "$(dirname "$0")"

read -r -s -p "Token du bot (saisie masquée) : " TELEGRAM_BOT_TOKEN
echo
read -r -p "Chat ID : " TELEGRAM_CHAT_ID
export TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID

python3 -m trading_bot telegram-test
