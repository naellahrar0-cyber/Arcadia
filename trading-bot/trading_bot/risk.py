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
