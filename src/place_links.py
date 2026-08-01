"""
NUOVO 2026-07-31 — "menù" e "info utili" per ogni locale.

Richiesta letterale di Lorenzo:
  "per i ristoranti è utile che crei un collegamento con il menù del ristorante
   che spesso trovi su internet ed un altro collegamento con le info utili sul
   ristorante (indirizzo, numero, ecc...)"

IL PUNTO DELICATO: IL MENÙ NON È UN CAMPO DELL'API
--------------------------------------------------
Google Places non restituisce "l'URL del menù". Restituisce il sito ufficiale
del locale. Un menù è quasi sempre lì dentro, ma indovinare l'URL esatto
(`/menu`, `/carta`, `/it/menu`...) significherebbe generare link che nel 90% dei
casi portano a un 404 — e un cliente che paga e trova link rotti smette di
fidarsi dell'intero documento, non solo di quel link.

Quindi la gerarchia è dichiarata e onesta, mai una finzione:
  1. sito ufficiale del locale (dato REALE dell'API) -> etichetta "Menù e sito
     ufficiale", perché è lì che il menù sta davvero;
  2. se il sito manca -> ricerca Google preimpostata "<nome> <indirizzo> menu",
     etichettata come RICERCA, non come menù. Il cliente vede che è una ricerca
     e sa cosa aspettarsi.

Per le "info utili" invece il dato è pieno e verificato: indirizzo e telefono
reali dall'API, più la scheda Google Maps ufficiale del locale (`googleMapsUri`)
che contiene orari aggiornati, foto e recensioni — molto più utile del link a
coordinate grezze che usavamo prima.

Nessuna chiave API: tutti gli URL prodotti qui sono link pubblici e documentati
(Google Maps URLs API / ricerca Google).
"""
from __future__ import annotations

from urllib.parse import quote_plus

GOOGLE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_MAPS_SEARCH_URL = "https://www.google.com/maps/search/?api=1"

# Tipi per cui ha senso mostrare la scheda "menù": un museo non ha un menù.
_MENU_RELEVANT_TYPES = {"restaurant"}


def _search_url(query: str) -> str:
    return f"{GOOGLE_SEARCH_URL}?q={quote_plus(query)}"


def build_menu_link(poi) -> dict | None:
    """`{"url", "label", "is_search"}` oppure None se non pertinente.

    `is_search=True` dice al renderer di etichettare il link come RICERCA:
    l'onestà sul tipo di link è parte del prodotto, non un dettaglio.
    """
    if getattr(poi, "type", None) not in _MENU_RELEVANT_TYPES:
        return None
    website = getattr(poi, "website", None)
    if isinstance(website, str) and website.strip():
        return {"url": website.strip(), "label": "Menù e sito ufficiale", "is_search": False}
    name = (getattr(poi, "name", "") or "").strip()
    if not name:
        return None
    address = (getattr(poi, "address", None) or "").strip()
    query = f"{name} {address} menu".strip()
    return {"url": _search_url(query), "label": "Cerca il menù online", "is_search": True}


def build_info_link(poi) -> dict | None:
    """Scheda "info utili": preferisce il link ufficiale Google Maps del locale
    (orari, foto, recensioni, numero) e ricade sulle coordinate reali — che
    abbiamo SEMPRE, perché senza di esse il POI non sarebbe nemmeno esistito."""
    maps_uri = getattr(poi, "google_maps_uri", None)
    if isinstance(maps_uri, str) and maps_uri.strip():
        return {"url": maps_uri.strip(), "label": "Info, orari e recensioni", "is_search": False}
    try:
        lat, lng = float(getattr(poi, "lat")), float(getattr(poi, "lng"))
    except (TypeError, ValueError):
        return None
    return {
        "url": f"{GOOGLE_MAPS_SEARCH_URL}&query={lat},{lng}",
        "label": "Apri in Google Maps",
        "is_search": False,
    }


def build_place_card(poi) -> dict:
    """Tutto quello che il PDF può mostrare di un locale, in una struttura sola.

    `{"name", "address", "phone", "menu_link", "info_link"}` — ogni campo è
    `None` quando il fornitore non l'ha dato, mai un segnaposto inventato. Il
    renderer omette semplicemente la riga corrispondente: una scheda con due
    righe vere è meglio di quattro righe di cui due false.
    """
    return {
        "poi_id": getattr(poi, "id", None),
        "name": getattr(poi, "name", None),
        "address": getattr(poi, "address", None),
        "phone": getattr(poi, "phone", None),
        "menu_link": build_menu_link(poi),
        "info_link": build_info_link(poi),
    }


def build_place_cards_by_id(pois, only_ids=None) -> dict[str, dict]:
    """`{poi_id: scheda}` per i POI richiesti (default: tutti).

    `only_ids` serve a rispettare la Fedeltà RAG anche qui: il PDF mostra le
    schede solo dei locali EFFETTIVAMENTE usati nell'itinerario
    (`itinerary_utils.extract_used_poi_ids`), non dell'intero bacino di ricerca.
    """
    cards = {}
    for poi in pois or []:
        poi_id = getattr(poi, "id", None)
        if not isinstance(poi_id, str):
            continue
        if only_ids is not None and poi_id not in only_ids:
            continue
        cards[poi_id] = build_place_card(poi)
    return cards
