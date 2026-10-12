"""Actualités via les flux RSS publics de Yahoo Finance (un flux par ticker).

Une source en panne n'empêche pas les autres d'être lues.
"""
from __future__ import annotations

import logging
from xml.etree import ElementTree as ET

import requests

log = logging.getLogger(__name__)
FEED_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
HEADERS = {"User-Agent": "Mozilla/5.0 (trading-bot)"}


def fetch_news(tickers: list[str], per_ticker: int = 2) -> list[dict]:
    items, seen_titles = [], set()
    for ticker in tickers:
        try:
            resp = requests.get(FEED_URL.format(ticker=ticker), headers=HEADERS, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except (requests.RequestException, ET.ParseError):
            log.warning("Actualités indisponibles pour %s", ticker)
            continue
        taken = 0
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            if not title or title in seen_titles or taken >= per_ticker:
                continue
            seen_titles.add(title)
            taken += 1
            items.append({
                "ticker": ticker,
                "title": title,
                "link": (item.findtext("link") or "").strip().split("?")[0],  # sans paramètres de suivi
                "published": (item.findtext("pubDate") or "").strip(),
            })
    return items
