#!/usr/bin/env bash
# Affiche ton chat ID Telegram. Le token est saisi de façon masquée.
set -e
cd "$(dirname "$0")"
read -r -s -p "Token du bot (saisie masquée) : " TELEGRAM_BOT_TOKEN
echo
export TELEGRAM_BOT_TOKEN="$(echo -n "$TELEGRAM_BOT_TOKEN" | tr -d '[:space:]')"
python3 -m trading_bot telegram-chatid
