"""
NUOVO 2026-07-31 — "Stima dei costi e dettaglio budget".

Richiesta letterale di Lorenzo: "manca la parte della stima dei costi e
dettaglio budget".

PERCHÉ QUESTO MODULO NON CHIEDE NIENTE A CLAUDE
------------------------------------------------
Un LLM che stima costi produce numeri plausibili e sbagliati. Qui il numero è
la cosa su cui il cliente prende decisioni vere (quanto contante porto, posso
permettermi la cena di venerdì), quindi la stima è ARITMETICA su dati reali,
calcolata in Python e verificabile riga per riga:

  - ALLOGGIO: `Hotel.price_night_eur` — un prezzo REALE per notte da LiteAPI,
    moltiplicato per il numero di notti calcolato dalle date del viaggio. È
    l'unica voce di cui conosciamo l'importo esatto.
  - RISTORANTI E ATTIVITÀ: NON conosciamo l'importo. Google dà una FASCIA
    (`price_level`: INEXPENSIVE/MODERATE/...). Quindi produciamo un
    INTERVALLO min–max per fascia, dichiarato come intervallo. Le fasce sotto
    sono cifre di riferimento europee per persona, esplicitate qui nel codice
    perché siano criticabili e correggibili, non nascoste dentro un prompt.
  - DATO ASSENTE: la voce entra nell'elenco marcata `[Da Verificare]` e NON
    entra nei totali. Gonfiare il totale con una stima inventata per un locale
    senza fascia di prezzo renderebbe l'intero conto inaffidabile.
  - TRASPORTI LOCALI, VOLI/TRENI PER ARRIVARE, SOUVENIR, IMPREVISTI: fuori
    stima e DICHIARATI fuori stima. Il documento lo dice al cliente in chiaro:
    è la differenza tra un preventivo onesto e un preventivo che tradisce.

Il risultato è una struttura dati; l'impaginazione è di pdf_renderer.py.
"""
from __future__ import annotations

from datetime import date

# Fasce di spesa PER PERSONA, in euro, per un pasto in un ristorante europeo.
# Sono intervalli deliberatamente larghi: preferiamo un intervallo onesto e
# ampio a un numero preciso e falso. Valori rivedibili in un punto solo.
_MEAL_BANDS_EUR = {
    "FREE": (0, 0),
    "INEXPENSIVE": (10, 20),
    "MODERATE": (20, 40),
    "EXPENSIVE": (40, 75),
    "VERY_EXPENSIVE": (75, 130),
}

# Fasce per un ingresso/attività (museo, sito, esperienza).
_ACTIVITY_BANDS_EUR = {
    "FREE": (0, 0),
    "INEXPENSIVE": (5, 12),
    "MODERATE": (12, 25),
    "EXPENSIVE": (25, 50),
    "VERY_EXPENSIVE": (50, 100),
}

# Attività senza alcun `price_level` dall'API: NON stimiamo. Molte delle cose
# migliori di una giornata (una piazza, un belvedere, un quartiere) sono
# gratuite, e attribuire loro un costo inventato gonfierebbe il totale.
_UNKNOWN_LABEL = "[Da Verificare]"

_CATEGORY_LABELS = {
    "lodging": "Alloggio",
    "meals": "Pasti e ristoranti",
    "activities": "Visite, musei e attività",
}


def count_nights(date_start, date_end) -> int | None:
    """Notti tra due date ISO (`YYYY-MM-DD`). None se non calcolabile —
    nessun fallback a un numero arbitrario: senza notti certe non c'è un
    costo alloggio certo, e lo diciamo."""
    try:
        start = date.fromisoformat(str(date_start)[:10])
        end = date.fromisoformat(str(date_end)[:10])
    except (TypeError, ValueError):
        return None
    nights = (end - start).days
    return nights if nights > 0 else None


def _band(bands: dict, price_level) -> tuple[int, int] | None:
    if not isinstance(price_level, str):
        return None
    return bands.get(price_level)


def estimate_costs(itinerary: dict, trip, hotels: list, pois: list, travellers: int = 1) -> dict:
    """
    Ritorna:
      {
        "travellers": int,
        "nights": int|None,
        "lines": [{"category", "category_label", "label", "detail",
                   "min_eur": float|None, "max_eur": float|None, "known": bool}],
        "totals_by_category": {categoria: {"min_eur", "max_eur"}},
        "total_min_eur": float, "total_max_eur": float,
        "unknown_count": int,
        "budget_eur": float|None,
        "budget_verdict": "within"|"tight"|"over"|None,
        "excluded_note": str,
      }

    Conta ogni comparsa di un ristorante nell'itinerario come un pasto (se il
    cliente cena due volte nello stesso posto, sono due cene), ma ogni visita a
    un museo UNA volta sola: il biglietto non si ricompra tornando la sera.
    """
    hotels = hotels or []
    pois = pois or []
    poi_by_id = {getattr(p, "id", None): p for p in pois}
    hotel_ids = {getattr(h, "id", None) for h in hotels}
    travellers = travellers if isinstance(travellers, int) and travellers > 0 else 1

    lines: list[dict] = []

    # --- ALLOGGIO: dato reale, unica voce con importo esatto ---------------
    # [CORRETTO 2026-08-02 — difetto visto rigenerando il campione, non dedotto
    # a tavolino] Prima ogni struttura in `hotels` diventava una voce di costo e
    # tutte finivano nel totale. Con due strutture in elenco il documento
    # addebitava al cliente DUE alberghi per le stesse notti: nel campione,
    # 420 € + 354 € = 774 € per tre notti dormite in un letto solo, e il verdetto
    # sul budget passava a "sopra il budget" per una spesa che non esiste.
    # Le strutture in elenco sono ALTERNATIVE fra cui il cliente sceglie (è la
    # decisione di prodotto già presa a monte: un solo hotel-àncora per viaggio,
    # vedi il feedback al business plan) e la copertina infatti ne stampa una
    # sola, sotto "BASE". Qui vale la stessa regola: si conta la prima, cioè
    # quella che il documento presenta come base, e si DICE che le altre sono
    # alternative — mai sommarle in silenzio, mai ometterle in silenzio.
    nights = count_nights(getattr(trip, "date_start", None), getattr(trip, "date_end", None))
    alternatives = max(len(hotels) - 1, 0)
    if alternatives == 1:
        alt_note = " · l'altra struttura in elenco è un'alternativa a questa, non si somma"
    elif alternatives > 1:
        alt_note = (
            f" · le altre {alternatives} strutture in elenco sono alternative a questa,"
            " non si sommano"
        )
    else:
        alt_note = ""
    for hotel in hotels[:1]:
        price = getattr(hotel, "price_night_eur", None)
        name = getattr(hotel, "name", None) or "Alloggio"
        if isinstance(price, (int, float)) and not isinstance(price, bool) and nights:
            total = float(price) * nights
            lines.append({
                "category": "lodging",
                "category_label": _CATEGORY_LABELS["lodging"],
                "label": name,
                "detail": (
                    f"{nights} notti × {price:.0f} € a notte (prezzo reale del fornitore)"
                    + alt_note
                ),
                "min_eur": total,
                "max_eur": total,
                "known": True,
            })
        else:
            lines.append({
                "category": "lodging",
                "category_label": _CATEGORY_LABELS["lodging"],
                "label": name,
                "detail": f"prezzo per notte non fornito — {_UNKNOWN_LABEL}" + alt_note,
                "min_eur": None, "max_eur": None, "known": False,
            })

    # --- PASTI E ATTIVITÀ: fasce, mai importi puntuali --------------------
    meal_counts: dict[str, int] = {}
    activity_ids: list[str] = []
    seen_activities: set[str] = set()
    for day in (itinerary or {}).get("days") or []:
        if not isinstance(day, dict):
            continue
        blocks = day.get("blocks") or []
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            poi_id = block.get("poi_id")
            if not isinstance(poi_id, str) or poi_id in hotel_ids:
                continue
            poi = poi_by_id.get(poi_id)
            if poi is None:
                continue
            if getattr(poi, "type", None) == "restaurant":
                meal_counts[poi_id] = meal_counts.get(poi_id, 0) + 1
            elif poi_id not in seen_activities:
                seen_activities.add(poi_id)
                activity_ids.append(poi_id)

    for poi_id, times in meal_counts.items():
        poi = poi_by_id[poi_id]
        band = _band(_MEAL_BANDS_EUR, getattr(poi, "price_level", None))
        name = getattr(poi, "name", None) or "Ristorante"
        suffix = f" × {times}" if times > 1 else ""
        if band is None:
            lines.append({
                "category": "meals", "category_label": _CATEGORY_LABELS["meals"],
                "label": f"{name}{suffix}",
                "detail": f"fascia di prezzo non fornita — {_UNKNOWN_LABEL}",
                "min_eur": None, "max_eur": None, "known": False,
            })
            continue
        lo, hi = band[0] * times * travellers, band[1] * times * travellers
        lines.append({
            "category": "meals", "category_label": _CATEGORY_LABELS["meals"],
            "label": f"{name}{suffix}",
            "detail": (
                f"fascia {getattr(poi, 'price_level', '')} · "
                f"{band[0]}–{band[1]} € a persona a pasto"
                + (f" × {travellers} persone" if travellers > 1 else "")
            ),
            "min_eur": float(lo), "max_eur": float(hi), "known": True,
        })

    for poi_id in activity_ids:
        poi = poi_by_id[poi_id]
        band = _band(_ACTIVITY_BANDS_EUR, getattr(poi, "price_level", None))
        name = getattr(poi, "name", None) or "Attività"
        if band is None:
            lines.append({
                "category": "activities", "category_label": _CATEGORY_LABELS["activities"],
                "label": name,
                "detail": (
                    "ingresso non quantificato dal fornitore — "
                    f"{_UNKNOWN_LABEL} (molte visite di questo tipo sono gratuite)"
                ),
                "min_eur": None, "max_eur": None, "known": False,
            })
            continue
        lo, hi = band[0] * travellers, band[1] * travellers
        lines.append({
            "category": "activities", "category_label": _CATEGORY_LABELS["activities"],
            "label": name,
            "detail": (
                f"fascia {getattr(poi, 'price_level', '')} · {band[0]}–{band[1]} € a persona"
                + (f" × {travellers} persone" if travellers > 1 else "")
            ),
            "min_eur": float(lo), "max_eur": float(hi), "known": True,
        })

    totals_by_category: dict[str, dict] = {}
    for line in lines:
        if not line["known"]:
            continue
        bucket = totals_by_category.setdefault(line["category"], {"min_eur": 0.0, "max_eur": 0.0})
        bucket["min_eur"] += line["min_eur"]
        bucket["max_eur"] += line["max_eur"]

    total_min = sum(b["min_eur"] for b in totals_by_category.values())
    total_max = sum(b["max_eur"] for b in totals_by_category.values())
    unknown_count = sum(1 for line in lines if not line["known"])

    budget_eur = getattr(trip, "budget_eur", None)
    budget_eur = float(budget_eur) if isinstance(budget_eur, (int, float)) and not isinstance(budget_eur, bool) else None
    verdict = None
    if budget_eur is not None and lines:
        if total_max <= budget_eur:
            verdict = "within"
        elif total_min <= budget_eur:
            verdict = "tight"
        else:
            verdict = "over"

    return {
        "travellers": travellers,
        "nights": nights,
        "lines": lines,
        "totals_by_category": totals_by_category,
        "category_labels": _CATEGORY_LABELS,
        "total_min_eur": total_min,
        "total_max_eur": total_max,
        "unknown_count": unknown_count,
        "budget_eur": budget_eur,
        "budget_verdict": verdict,
        "excluded_note": (
            "Non inclusi in questa stima: viaggio di andata e ritorno verso la "
            "destinazione, trasporti locali (bus, metro, taxi), acquisti personali "
            "e souvenir, assicurazione di viaggio, imprevisti. I costi di pasti e "
            "attività sono intervalli basati sulla fascia di prezzo dichiarata dal "
            "fornitore, non prezzi confermati: verifica sempre sul posto o sul sito "
            "ufficiale prima di impegnarti."
        ),
    }
