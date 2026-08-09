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
# Deep-link ufficiale della "Google Maps URLs API": porta DIRETTAMENTE sulla
# scheda di QUEL locale (menù, orari, foto, recensioni, numero), non su una
# pagina di risultati da spulciare. È documentato e stabile, e non consuma
# nessuna quota: è un URL, non una chiamata API.
GOOGLE_MAPS_PLACE_URL = "https://www.google.com/maps/place/?q=place_id:{place_id}"

# Tipi per cui ha senso mostrare la scheda "menù": un museo non ha un menù.
# Nota: la normalizzazione di `places_client` fa collassare bar, caffè,
# pasticcerie, gelaterie ed enoteche tutte su "restaurant", quindi questo
# insieme di un elemento copre già tutto il mangiare-e-bere.
_MENU_RELEVANT_TYPES = {"restaurant"}

# Tipi per cui ha senso un link "biglietti e orari": tutto ciò che si visita.
_TICKET_RELEVANT_TYPES = {"museum", "activity"}


def _search_url(query: str) -> str:
    return f"{GOOGLE_SEARCH_URL}?q={quote_plus(query)}"


def _clean(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def build_place_page_url(poi) -> str | None:
    """URL della scheda Google del locale, in UN tap.

    [AGGIUNTO 2026-08-01 — richiesta di Lorenzo: "devi collegarti direttamente
    al loro menù senza dover far cercare nulla al cliente ... togliergli più
    lavoro possibile"]

    Preferisce `googleMapsUri`, che è il link canonico restituito dall'API.
    Quando manca, lo ricostruisce dal `place_id` — che è esattamente ciò che
    `poi.id` contiene per ogni POI venuto da Google Places. Il risultato è
    identico: la scheda del locale, non una ricerca.
    """
    uri = _clean(getattr(poi, "google_maps_uri", None))
    if uri:
        return uri
    place_id = _clean(getattr(poi, "id", None))
    if not place_id:
        return None
    return GOOGLE_MAPS_PLACE_URL.format(place_id=quote_plus(place_id))


def build_menu_link(poi) -> dict | None:
    """`{"url", "label", "is_search"}` oppure None se non pertinente.

    `is_search=True` dice al renderer di etichettare il link come RICERCA:
    l'onestà sul tipo di link è parte del prodotto, non un dettaglio.

    [RISCRITTA LA SCALA DI RIPIEGO IL 2026-08-01] Prima era: sito ufficiale,
    altrimenti una RICERCA su Google. Il secondo gradino era proprio il lavoro
    che Lorenzo ha chiesto di togliere al cliente — una pagina di risultati da
    spulciare, in una città sconosciuta, con il telefono in una mano.
    Adesso in mezzo c'è la scheda Google del locale: un tap, e ci sono il menù
    (quando Google ce l'ha), gli orari di oggi, le foto dei piatti e il
    numero. La ricerca resta solo per il caso residuo in cui non abbiamo né
    sito né identificativo — che, con i POI che vengono da Places, non
    dovrebbe accadere mai.
    """
    if getattr(poi, "type", None) not in _MENU_RELEVANT_TYPES:
        return None
    website = _clean(getattr(poi, "website", None))
    if website:
        return {"url": website, "label": "Menù e sito ufficiale", "is_search": False}
    place_page = build_place_page_url(poi)
    if place_page:
        # Etichetta deliberatamente NON "Menù": la scheda Google mostra il menù
        # solo quando il locale l'ha caricato. Promettere un menù e mostrare
        # una scheda sarebbe la stessa disonestà del `sito.it/menu` indovinato
        # che questo modulo rifiuta da sempre.
        return {
            "url": place_page,
            "label": "Menù, foto e orari sulla scheda del locale",
            "is_search": False,
        }
    name = _clean(getattr(poi, "name", None))
    if not name:
        return None
    address = _clean(getattr(poi, "address", None)) or ""
    query = f"{name} {address} menu".strip()
    return {"url": _search_url(query), "label": "Cerca il menù online", "is_search": True}


def build_phone_link(poi) -> dict | None:
    """Link `tel:` — prenotare un tavolo diventa un tap, non una trascrizione.

    [AGGIUNTO 2026-08-01] Il numero c'era già, stampato come testo. Su un PDF
    letto dal telefono — che è come questo documento viene letto davvero, in
    viaggio — un numero non cliccabile significa: memorizzalo, esci dal PDF,
    apri il telefono, ridigitalo. Tre passaggi e un errore di trascrizione
    possibile, per una cosa che il formato PDF sa fare da sé.

    `url` è normalizzato (solo cifre e un eventuale `+` iniziale, come vuole
    lo schema `tel:`), `label` resta il numero LEGGIBILE come lo ha scritto
    Google, spazi e prefissi compresi.
    """
    raw = _clean(getattr(poi, "phone", None))
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    prefix = "+" if raw.lstrip().startswith("+") else ""
    return {"url": f"tel:{prefix}{digits}", "label": raw, "is_search": False}


def build_tickets_link(poi) -> dict | None:
    """Link "biglietti e orari" per ciò che si visita.

    [AGGIUNTO 2026-08-01 — direttrice "biglietti e prenotazioni" chiesta da
    Lorenzo per i consigli, applicata anche qui dove serve davvero: sul
    luogo, nel giorno in cui lo si visita.]

    Solo il sito UFFICIALE, mai una rivendita: il biglietto di un museo
    comprato su un portale terzo costa regolarmente il 20-30 % in più per lo
    stesso ingresso, e mandarcelo noi sarebbe farlo perdere al cliente. Se il
    sito ufficiale non c'è, questa funzione non inventa un ripiego: gli orari
    stanno già nella scheda Google del link "info".
    """
    if getattr(poi, "type", None) not in _TICKET_RELEVANT_TYPES:
        return None
    website = _clean(getattr(poi, "website", None))
    if not website:
        return None
    return {"url": website, "label": "Biglietti e orari (sito ufficiale)", "is_search": False}


def build_info_link(poi) -> dict | None:
    """Scheda "info utili": preferisce il link ufficiale Google Maps del locale
    (orari, foto, recensioni, numero) e ricade sulle coordinate reali — che
    abbiamo SEMPRE, perché senza di esse il POI non sarebbe nemmeno esistito."""
    place_page = build_place_page_url(poi)
    if place_page:
        return {"url": place_page, "label": "Info, orari e recensioni", "is_search": False}
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

    Ogni campo è `None` quando il fornitore non l'ha dato, mai un segnaposto
    inventato. Il renderer omette semplicemente la riga corrispondente: una
    scheda con due righe vere è meglio di quattro righe di cui due false.

    [AGGIUNTI 2026-08-01] `phone_link` (schema `tel:`, per chiamare o
    prenotare con un tap) e `tickets_link` (sito ufficiale di ciò che si
    visita). `phone` resta accanto a `phone_link` come TESTO: il PDF va
    anche stampato, e su carta un `tel:` non si clicca.
    """
    return {
        "poi_id": getattr(poi, "id", None),
        "name": getattr(poi, "name", None),
        "address": getattr(poi, "address", None),
        "phone": getattr(poi, "phone", None),
        "menu_link": build_menu_link(poi),
        "info_link": build_info_link(poi),
        "phone_link": build_phone_link(poi),
        "tickets_link": build_tickets_link(poi),
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
