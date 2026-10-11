#!/usr/bin/env bash
# Configure Telegram puis envoie un message de test.
# Le token est saisi de façon masquée et n'est enregistré nulle part.
set -e
cd "$(dirname "$0")"

while true; do
    read -r -s -p "Token du bot (saisie masquée) : " TELEGRAM_BOT_TOKEN
    echo
    TELEGRAM_BOT_TOKEN="$(echo -n "$TELEGRAM_BOT_TOKEN" | tr -d '[:space:]')"
    if [[ "$TELEGRAM_BOT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
        break
    fi
    echo "Ce n'est pas un token valide (format attendu : 123456789:AAF...). Recommence."
done

while true; do
    read -r -p "Chat ID (uniquement des chiffres, ex. 123456789) : " TELEGRAM_CHAT_ID
    TELEGRAM_CHAT_ID="$(echo -n "$TELEGRAM_CHAT_ID" | tr -d '[:space:]')"
    if [[ "$TELEGRAM_CHAT_ID" =~ ^-?[0-9]+$ ]]; then
        break
    fi
    echo "Le chat ID ne contient que des chiffres. Recommence."
done

export TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
python3 -m trading_bot telegram-test
