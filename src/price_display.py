"""
[NUOVO 2026-07-12 — richiesta di Lorenzo: "segnare ogni costo (hotel,
ristoranti)"] Modulo minuscolo e deliberatamente isolato: converte il
`price_level` di un POI (enum Google, vedi places_client.py) nel simbolo
€/€€/€€€ mostrato al cliente. Condiviso tra `renderer.py` (Markdown,
revisione interna) e `pdf_renderer.py` (documento cliente) — stesso
principio "anti-desync" già seguito altrove nel progetto: una sola
implementazione della conversione, non due copie che rischiano di
divergere silenziosamente.

Funzione pura, nessuna chiamata di rete/IO — facile da testare in
isolamento.
"""
from __future__ import annotations

_SYMBOLS = {
    "FREE": "Gratuito",
    "INEXPENSIVE": "€",
    "MODERATE": "€€",
    "EXPENSIVE": "€€€",
    "VERY_EXPENSIVE": "€€€€",
}


def price_level_symbol(price_level: str | None) -> str:
    """Ritorna il simbolo da mostrare al cliente, oppure stringa vuota se
    il dato non è disponibile — mai un simbolo inventato per un valore
    mancante o non riconosciuto (stesso principio di Fedeltà RAG di tutto
    il resto del progetto: un dato assente resta assente, non si finge)."""
    if not price_level:
        return ""
    return _SYMBOLS.get(price_level, "")
