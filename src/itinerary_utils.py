"""
[NUOVO 2026-07-12 — richiesta di Lorenzo: sezioni curate ristoranti/hotel/
intrattenimento + cartina con percorsi] Piccole funzioni pure, condivise,
per estrarre dall'itinerario GIÀ GENERATO da Claude quali `poi_id` sono
stati DAVVERO usati (e in che ordine, giorno per giorno).

Prima di questo modulo, `main.py::_build_pdf_extras()` calcolava
`used_poi_ids` inline con una list/set comprehension propria — estratta
qui perché ora serve in almeno due punti (le sezioni curate "Dove
mangiare"/"Cosa fare" del documento, e il tracciato dei percorsi sulla
cartina di `maps_static.py`): stesso principio "anti-desync" già seguito
altrove nel progetto, una sola implementazione invece di due copie che
rischiano di divergere.

Perché "solo i poi_id effettivamente usati" e non l'intero DATI_API_FORNITI:
stessa Fedeltà RAG di tutto il resto del sistema — mostrare al cliente
un elenco di "consigli" che include POI MAI scelti da Claude per
quell'itinerario (magari scartati per un vincolo, o semplicemente non
selezionati) sarebbe fuorviante, non un'invenzione di dati ma comunque
un'informazione presentata come "la tua raccomandazione" che non lo è
davvero.
"""
from __future__ import annotations


def extract_used_poi_ids(itinerary: dict) -> set[str]:
    """Insieme (non ordinato) di tutti i `poi_id` non-null usati in
    QUALUNQUE blocco dell'itinerario — stessa estrazione già usata da
    `main.py::_build_pdf_extras()` per le guide turistiche per-POI."""
    return {
        block.get("poi_id")
        for day in itinerary.get("days", [])
        for block in day.get("blocks", [])
        if block.get("poi_id")
    }


def extract_used_poi_ids_by_day(itinerary: dict) -> dict[int, list[str]]:
    """`poi_id` usati per ciascun giorno, IN ORDINE di visita (preserva
    l'ordine dei blocchi) — serve a disegnare il percorso di ciascuna
    giornata sulla cartina (`maps_static.py`), non solo a sapere quali id
    compaiono. Giorni senza alcun `poi_id` (es. tutto `[SLOT LIBERO]`) sono
    omessi dal risultato, non presenti come lista vuota."""
    result: dict[int, list[str]] = {}
    for day in itinerary.get("days", []):
        ids = [b.get("poi_id") for b in day.get("blocks", []) if b.get("poi_id")]
        if ids:
            result[day.get("day")] = ids
    return result
