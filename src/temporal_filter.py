"""
NODO 6 — Filtro Temporale. HTTP_MODULES_REALI.md §NODO 6. Nessuna chiamata
HTTP: logica pura. Scarta i POI chiusi in TUTTI i giorni del soggiorno.
"""
from __future__ import annotations
from datetime import date, timedelta
from .schemas import POI

_DOW_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def compute_travel_days(date_start: str, duration_days: int) -> list[str]:
    """[6.0] travel_days — insieme distinct dei giorni-settimana del soggiorno.

    [AGGIUNTO 2026-07-12 — gap reale trovato in audit di qualità]
    `duration_days` è normalmente garantito positivo perché deriva sempre
    da `date_end - date_start` in `triage.py::normalize_raw_input()`, e
    `Trip.validate()` rifiuta esplicitamente `date_start >= date_end`
    prima che questa funzione venga mai chiamata nel flusso reale
    (`pipeline.py`). Ma questa funzione non lo garantiva DA SÉ: con
    `duration_days <= 0`, `range(min(duration_days, 7))` è vuoto e la
    funzione tornava silenziosamente `[]` invece di segnalare un input
    invalido — un futuro chiamante che bypassasse `Trip.validate()` (un
    test, uno script di debug, un futuro punto di ingresso) avrebbe
    ottenuto un `travel_days=[]` che poi fa scartare in `filter_open_pois()`
    OGNI POI con orari noti (solo quelli con orari ignoti sopravvivono),
    un comportamento sbagliato ma plausibile — mai un errore esplicito.
    Stesso principio "fallisci in modo esplicito e presto" già applicato a
    `Trip.validate()`: qui aggiunge una seconda barriera diretta sulla
    funzione stessa, invece di fare affidamento solo su un invariante
    upstream non imposto da questo modulo.
    """
    if duration_days <= 0:
        raise ValueError(
            f"duration_days deve essere positivo, ricevuto {duration_days} — "
            f"un soggiorno di durata nulla o negativa non ha giorni di viaggio da calcolare."
        )
    if duration_days >= 7:
        return list(_DOW_ORDER)
    start = date.fromisoformat(date_start)
    days = set()
    for offset in range(min(duration_days, 7)):
        d = start + timedelta(days=offset)
        # date.weekday(): Mon=0..Sun=6 -> stesso vocabolario canonico
        days.add(_DOW_ORDER[d.weekday()])
    # ordine stabile
    return [d for d in _DOW_ORDER if d in days]


def filter_open_pois(pois: list[POI], travel_days: list[str]) -> list[POI]:
    """
    [6.3] Filtro: passa se (A) aperto in almeno 1 giorno del soggiorno,
    OPPURE (B) orari ignoti (open_days vuoto — trasparenza, non potatura
    conservativa, come da nota di design in HTTP_MODULES_REALI.md).
    """
    travel_set = set(travel_days)
    kept = []
    for poi in pois:
        if not poi.open_days:
            kept.append(poi)  # gruppo B: orari ignoti, passa con trasparenza
            continue
        if travel_set.intersection(poi.open_days):  # gruppo A
            kept.append(poi)
    return kept
