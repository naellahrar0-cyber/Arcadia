"""Analyse des actualités par une IA (API Anthropic). Désactivée sans ANTHROPIC_API_KEY.

L'IA résume et met en lien les titres avec les paires suivies. Elle ne donne ni
prix cible ni ordre : c'est une aide à la lecture, à vérifier.
"""
from __future__ import annotations

import logging

import requests

from .config import Config

log = logging.getLogger(__name__)
API_URL = "https://api.anthropic.com/v1/messages"


def analyze_news(news: list[dict], cfg: Config) -> str | None:
    if not cfg.anthropic_api_key or not news:
        return None
    headlines = "\n".join(f"- [{item['ticker']}] {item['title']}" for item in news)
    prompt = (
        "Voici des titres d'actualité financière récents, classés par ticker :\n"
        f"{headlines}\n\n"
        "En français, en 6 lignes maximum : 1) pour chaque ticker, l'effet probable "
        "(haussier, baissier, neutre ou incertain) et pourquoi ; 2) les risques à surveiller dans les prochaines heures. "
        "Ne donne aucun prix cible, aucun conseil d'achat ou de vente, et indique quand l'information est insuffisante."
    )
    try:
        resp = requests.post(
            API_URL,
            headers={"x-api-key": cfg.anthropic_api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": cfg.ai_model, "max_tokens": 500,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        resp.raise_for_status()
        parts = resp.json().get("content", [])
        return "\n".join(p["text"] for p in parts if p.get("type") == "text").strip() or None
    except (requests.RequestException, ValueError, KeyError) as exc:
        # sans l'exception complète : pas de clé ni d'en-tête dans les traces
        log.warning("Analyse IA indisponible (%s)", type(exc).__name__)
        return None
