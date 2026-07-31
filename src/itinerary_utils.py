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


# [AGGIORNATO 2026-07-31 — audit di perfezionamento] guardie di robustezza:
# queste funzioni girano ANCHE quando la validazione del Nodo 9 è FAIL (in
# main.py::_build_pdf_extras la generazione PDF può partire su un itinerario
# non ancora validato PASS), quindi devono tollerare le stesse forme inattese
# gestite nel validator: `days`/`blocks` = None o non-lista, elementi non-dict,
# e soprattutto un `poi_id` NON HASHABLE (es. una lista) che faceva crashare la
# set-comprehension con `TypeError: unhashable type`. Un poi_id non-str non è
# comunque un id valido: viene ignorato, mai crash.
def _iter_poi_ids(day: dict):
    """Yield dei poi_id validi (stringa non vuota) dei blocchi di un giorno,
    in ordine, saltando blocchi non-dict e id di tipo/valore inatteso."""
    if not isinstance(day, dict):
        return
    for block in day.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        pid = block.get("poi_id")
        if isinstance(pid, str) and pid:
            yield pid


def extract_used_poi_ids(itinerary: dict) -> set[str]:
    """Insieme (non ordinato) di tutti i `poi_id` non-null usati in
    QUALUNQUE blocco dell'itinerario — stessa estrazione già usata da
    `main.py::_build_pdf_extras()` per le guide turistiche per-POI."""
    if not isinstance(itinerary, dict):
        return set()
    return {
        pid
        for day in itinerary.get("days") or []
        for pid in _iter_poi_ids(day)
    }


def extract_used_poi_ids_by_day(itinerary: dict) -> dict[int, list[str]]:
    """`poi_id` usati per ciascun giorno, IN ORDINE di visita (preserva
    l'ordine dei blocchi) — serve a disegnare il percorso di ciascuna
    giornata sulla cartina (`maps_static.py`), non solo a sapere quali id
    compaiono. Giorni senza alcun `poi_id` (es. tutto `[SLOT LIBERO]`) sono
    omessi dal risultato, non presenti come lista vuota."""
    result: dict[int, list[str]] = {}
    if not isinstance(itinerary, dict):
        return result
    for day in itinerary.get("days") or []:
        if not isinstance(day, dict):
            continue
        ids = list(_iter_poi_ids(day))
        if ids:
            # [AGGIORNATO 2026-07-31 — audit di perfezionamento] `setdefault
            # + extend` invece di assegnazione diretta: numeri di giorno
            # duplicati (Claude che emette due "day": 1) collidevano sulla
            # chiave e il percorso del primo giorno spariva SILENZIOSAMENTE dal
            # tracciato della cartina. Ora i poi_id vengono accumulati.
            result.setdefault(day.get("day"), []).extend(ids)
    return result
