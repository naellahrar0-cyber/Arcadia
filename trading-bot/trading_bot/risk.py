"""Dimensionnement de position : on fixe le montant risqué, la taille en découle."""
from __future__ import annotations


def position_size(capital: float, risk_per_trade: float, entry: float, stop: float) -> tuple[float, float, float]:
    """Retourne (quantité, valeur notionnelle, montant risqué) pour un stop donné."""
    distance = abs(entry - stop)
    if distance == 0:
        raise ValueError("Le stop-loss doit être différent de l'entrée")
    risk_amount = capital * risk_per_trade
    qty = risk_amount / distance
    return qty, qty * entry, risk_amount


def target_position_size(target_profit: float, entry: float, take_profit: float, stop: float) -> tuple[float, float, float]:
    """Taille pour gagner `target_profit` si le take-profit est atteint. Retourne (quantité, notionnel, perte au stop)."""
    reward_distance = abs(take_profit - entry)
    if reward_distance == 0:
        raise ValueError("Le take-profit doit être différent de l'entrée")
    qty = target_profit / reward_distance
    return qty, qty * entry, qty * abs(entry - stop)
