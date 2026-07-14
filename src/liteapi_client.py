"""
NODO 3 — Ricettività (Anchor Point). HTTP_MODULES_REALI.md §NODO 3.
LiteAPI (Nuitée Connect): X-API-Key -> data/hotels (geocode) -> hotels/rates -> mapping.

[SOSTITUISCE amadeus_client.py — 2026-07-10] Amadeus ha chiuso il portale
self-service developer il 17 luglio 2026 (fonti in CHANGELOG.md). LiteAPI è
il rimpiazzo verificato: stessa interfaccia pubblica di prima
(search_hotels_by_geocode / search_hotel_offers / select_anchor_hotel), così
il resto della pipeline (payload_builder.py, pipeline.py) non ha dovuto
cambiare.

Autenticazione più semplice del predecessore: un solo header `X-API-Key`,
niente OAuth2 client_credentials, niente cache del token.

✅ VERIFICATO DAL VIVO [2026-07-10]: chiamata reale eseguita da Lorenzo con
sandbox key su Firenze (43.7699685, 11.2576706) — 20 hotel candidati da
`data/hotels`, 19/19 prezzi estratti correttamente da `hotels/rates` con lo
schema sotto (0 scartati dal mapping difensivo). Non è più una ricostruzione
"alla cieca" da prosa documentale: i nomi-campo qui sotto sono confermati
da una risposta JSON reale, non ipotizzati.

Due correzioni rispetto alla prima stesura (scritta senza accesso di rete):
1. Il campo stelle si chiama `stars`, non `starRating` come avevo scritto
   inizialmente — corretto in `select_anchor_hotel()` sotto.
2. `retailRate.total` è SEMPRE una lista di dict con `amount`/`currency`
   (es. `[{"amount": 289.05, "currency": "EUR"}]`), mai un numero semplice
   né un dict "nudo" — su 19 hotel reali, la forma "list of dicts" ha
   coperto il 100% dei casi. `_extract_total_price()` gestisce comunque
   anche le altre due forme (numero semplice, dict senza lista) come
   fallback difensivo puro: non sono mai state osservate dal vivo, ma
   costano poco da tenere nel caso l'API cambi forma in futuro. Se dovesse
   ripresentarsi un caso non riconosciuto, `LiteApiError` lo segnala in modo
   esplicito — MAI un numero sbagliato in silenzio.

Copertura geografica (il vero punto debole dichiarato di LiteAPI) non ancora
verificata: Firenze è una città importante dove qualunque provider avrebbe
buona copertura. Il test che conta per il mercato beachhead (circoli
tennis/padel, spesso in centri piccoli) è su una destinazione rurale tipo
Val d'Orcia — vedi debug_liteapi_raw.py e prototipo-status.md.
"""
from __future__ import annotations
import math
import requests
from .schemas import Hotel

BASE_URL = "https://api.liteapi.travel/v3.0"
HOTELS_BY_GEOCODE_URL = f"{BASE_URL}/data/hotels"
HOTEL_RATES_URL = f"{BASE_URL}/hotels/rates"


class LiteApiError(Exception):
    pass


# [AGGIUNTO 2026-07-11 — richiesta di prodotto di Lorenzo: "vorrei che il
# software fosse collegato non solo a Booking ma anche ad altre piattaforme
# di alloggio (es. Airbnb...)"] Ricerca (via web search, fonti in
# CHANGELOG.md item 82): Airbnb non ha un'API self-service per terze parti
# ed è contrattualmente vietato costruirci un prodotto come il nostro; Vrbo/
# Expedia Rapid API ha lo stesso identico gate di Booking Affiliate (niente
# self-service). Ma LiteAPI — che usiamo già — classifica ogni struttura
# con un `hotelTypeId`: confermato dal vivo con `debug_liteapi_property_types.py`
# su Lisbona che filtrando esplicitamente su Apartments/Villas/Aparthotels/
# Holiday homes/Private vacation home si ottengono 20/20 candidati REALI
# (es. "Lisbon Art Stay Hotel & Apartments", "LSA Restauradores by Numa" —
# un serviced apartment vero) — non solo una tassonomia teorica. Senza
# nessun filtro esplicito, la ricerca di default restituiva invece 20/20
# "Hotels" — quindi stavamo lasciando fuori quest'offerta per nessuna
# ragione tecnica, solo perché non la chiedevamo mai esplicitamente.
#
# Lista completa dei 52 tipi noti a LiteAPI, ottenuta dal vivo via
# `GET /data/hotelTypes` (mai chiamato prima in questo progetto) — tenuta
# qui per intero (non solo il sottoinsieme di default sotto) così che
# QUALSIASI hotelTypeId incontrato in una risposta reale si traduca in un
# nome leggibile invece di restare un numero opaco, anche se quel tipo non
# fa parte della ricerca di default.
_HOTEL_TYPE_NAMES: dict[int, str] = {
    0: "Not Available", 201: "Apartments", 203: "Hostels", 204: "Hotels",
    205: "Motels", 206: "Resorts", 207: "Residences", 208: "Bed and breakfasts",
    209: "Ryokans", 210: "Farm stays", 212: "Holiday parks", 213: "Villas",
    214: "Campsites", 215: "Boats", 216: "Guest houses", 218: "Inns",
    219: "Aparthotels", 220: "Holiday homes", 221: "Lodges", 222: "Homestays",
    223: "Country houses", 224: "Luxury tents", 225: "Capsule hotels",
    226: "Love hotels", 227: "Riads", 228: "Chalets", 229: "Condos",
    230: "Cottages", 231: "Economy hotels", 232: "Gites", 233: "Health resorts",
    234: "Cruises", 235: "Student accommodation", 243: "Tree house property",
    247: "Pension", 250: "Private vacation home", 251: "Pousada",
    252: "Country house", 254: "Campsite", 257: "Cabin", 258: "Holiday park",
    262: "Affittacamere", 264: "Hostel/Backpacker accommodation",
    265: "Houseboat", 268: "Ranch", 271: "Agritourism property",
    272: "Mobile home", 273: "Safari/Tentalow", 274: "All-inclusive property",
    276: "Castle", 277: "property", 278: "Palace",
}

# Sottoinsieme usato di DEFAULT nella ricerca reale (search_hotels_by_geocode).
# Scelta deliberata, non esaustiva — criterio: tipi di alloggio "curati" e
# compatibili col nostro modello ad "anchor point" con lat/lng fisso
# (Distance Matrix/Nodo 4), esclusi quindi tipi senza indirizzo stabile
# (Cruises, Boats, Houseboat) o non allineati al posizionamento del
# prodotto (Motels, Capsule hotels, Love hotels, Economy hotels, Hostels —
# economy/backpacker; Health resorts, Student accommodation, Ranch, Mobile
# home, Safari/Tentalow, All-inclusive property, Castle, Palace — troppo
# di nicchia per un default, valutabili singolarmente in futuro se un
# cliente li richiede esplicitamente). Include sempre 204 (Hotels,
# comportamento preesistente, invariato) più le categorie "vacation
# rental"-style confermate dal vivo (Apartments/Villas/Aparthotels/Holiday
# homes/Private vacation home) e altre categorie curate mainstream
# (Guest houses, B&B, Residences, Condos, Cottages, Chalets, Country
# houses, Affittacamere — rilevante per il beachhead italiano, Farm stays —
# coerente con le destinazioni rurali già servite, Lodges, Homestays, Inns).
DEFAULT_HOTEL_TYPE_IDS: tuple[int, ...] = (
    204, 201, 213, 219, 220, 250, 216, 208, 207, 229, 230, 228, 223, 252, 262, 210, 221, 222, 218,
)


class LiteApiClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _headers(self, json_body: bool = False) -> dict:
        headers = {"X-API-Key": self.api_key, "accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def search_hotels_by_geocode(
        self, lat: float, lng: float, radius_km: int = 5,
        hotel_type_ids: tuple[int, ...] | None = DEFAULT_HOTEL_TYPE_IDS,
    ) -> list[dict]:
        """
        [AGGIORNATO 2026-07-11] `hotel_type_ids` di default ora usa
        `DEFAULT_HOTEL_TYPE_IDS` invece di nessun filtro — vedi la nota
        estesa sopra quella costante per il razionale completo (bug reale
        di prodotto: la ricerca senza filtro restituiva solo "Hotels",
        lasciando fuori appartamenti/ville/altro senza motivo tecnico).
        Passa `hotel_type_ids=None` esplicitamente per tornare al
        comportamento pre-2026-07-11 (nessun filtro, LiteAPI decide da
        sola quali tipi mostrare — utile per debug/confronto, vedi
        debug_liteapi_property_types.py).
        """
        params = {
            "latitude": lat,
            "longitude": lng,
            "radius": max(radius_km * 1000, 1000),  # LiteAPI vuole metri, min 1000
            "limit": 20,
        }
        if hotel_type_ids:
            params["hotelTypeIds"] = ",".join(str(t) for t in hotel_type_ids)
        resp = requests.get(
            HOTELS_BY_GEOCODE_URL,
            headers=self._headers(),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def search_hotel_offers(
        self, hotel_ids: list[str], date_start: str, date_end: str,
        budget_eur: float | None = None,
    ) -> list[dict]:
        if not hotel_ids:
            return []
        body = {
            "hotelIds": hotel_ids[:50],  # stesso margine di sicurezza del client precedente
            "checkin": date_start,
            "checkout": date_end,
            "occupancies": [{"adults": 2}],
            "currency": "EUR",
            "guestNationality": "IT",
            "roomMapping": True,
            "includeHotelData": True,
        }
        # budget_eur non è un filtro diretto documentato per hotels/rates (a
        # differenza di Amadeus priceRange): il filtro budget resta applicato
        # a valle in select_anchor_hotel/Claude, non qui. [Da Verificare]
        resp = requests.post(
            HOTEL_RATES_URL,
            headers=self._headers(json_body=True),
            json=body,
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])


def _distance_sq(lat1, lng1, lat2, lng2) -> float:
    """
    Stima di distanza in "pseudo-gradi al quadrato", usata SOLO per
    ordinare candidati per baricentricità (mai per un tempo/distanza reale
    — quelli vengono sempre da Distance Matrix, vedi HARD_CONSTRAINTS
    punto 2 del system prompt). [CORRETTO 2026-07-12 — bug reale trovato
    in audit di qualità] Trattare 1° di latitudine e 1° di longitudine
    come equivalenti è sbagliato a qualunque latitudine diversa
    dall'equatore: un grado di longitudine misura ~111km * cos(lat) sul
    terreno, non ~111km come un grado di latitudine — alle latitudini
    italiane (~44°N) è compresso di circa il 28% (cos(44°) ≈ 0.72).
    Scenario concreto: due hotel candidati, uno 0.007° a nord (~777m reali)
    e uno 0.009° a est (~719m reali, PIÙ VICINO sul terreno grazie alla
    compressione della longitudine) — senza correzione, il calcolo grezzo
    classificava il primo come più vicino, l'opposto della realtà,
    rischiando di scegliere l'hotel-ancora sbagliato quando i candidati
    sono distribuiti soprattutto in longitudine rispetto alla destinazione.
    Fix: applica la correzione standard cos(lat) al delta di longitudine
    prima di elevarlo al quadrato (usa la latitudine media dei due punti,
    approssimazione più che sufficiente per gli hotel-ancora, tutti entro
    pochi km dalla destinazione).
    """
    lat_rad_mean = math.radians((lat1 + lat2) / 2)
    lng_correction = math.cos(lat_rad_mean)
    return (lat1 - lat2) ** 2 + ((lng1 - lng2) * lng_correction) ** 2


def _extract_total_price(rate_entry: dict) -> float:
    """
    Isola la parte meno certa dello schema LiteAPI (vedi nota di onestà in
    testa al file). Prova le forme plausibili in ordine e solleva
    LiteApiError se nessuna corrisponde — non inventa un prezzo.
    """
    room_types = rate_entry.get("roomTypes") or []
    if not room_types:
        raise LiteApiError(f"hotelId={rate_entry.get('hotelId')}: 'roomTypes' assente o vuoto")
    rates = room_types[0].get("rates") or []
    if not rates:
        raise LiteApiError(f"hotelId={rate_entry.get('hotelId')}: 'rates' assente o vuoto")
    retail_rate = rates[0].get("retailRate")
    if retail_rate is None:
        raise LiteApiError(f"hotelId={rate_entry.get('hotelId')}: 'retailRate' assente")

    total = retail_rate.get("total") if isinstance(retail_rate, dict) else None
    if isinstance(total, (int, float)):
        return float(total)
    if isinstance(total, dict) and "amount" in total:
        return float(total["amount"])
    if isinstance(total, list) and total and isinstance(total[0], dict) and "amount" in total[0]:
        return float(total[0]["amount"])

    raise LiteApiError(
        f"hotelId={rate_entry.get('hotelId')}: forma di 'retailRate.total' non riconosciuta "
        f"({total!r}) — verifica lo schema reale con una chiamata sandbox e aggiorna "
        f"_extract_total_price() prima di fidartene in produzione."
    )


def select_anchor_hotel(
    hotels_by_geocode: list[dict],
    hotel_offers: list[dict],
    dest_lat: float,
    dest_lng: float,
    duration_days: int,
    max_hotels: int = 1,
) -> list[Hotel]:
    """
    Funzione pura (nessuna chiamata di rete) — mapping [3.3] di
    HTTP_MODULES_REALI.md. Ordina per baricentricità e prende `max_hotels`
    (default 1, coerente col cap del Nodo 4 — invariato dalla migrazione).

    NON inventa nulla: se hotel_offers è vuoto propaga hotels=[] (Claude
    attiva il fallback [SLOT LIBERO]) — vedi HTTP_MODULES_REALI.md §Nodo 3
    error handler. Le entry con schema-prezzo non riconosciuto vengono
    scartate (non incluse a caso), non fanno fallire l'intera selezione.
    """
    if not hotel_offers:
        return []

    # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] `h["id"]` con
    # indicizzazione diretta faceva crashare l'INTERA selezione con un
    # KeyError grezzo se anche una sola entry di hotels_by_geocode fosse
    # priva del campo "id" — inconsistente col resto di questa stessa
    # funzione, che è deliberatamente difensiva ovunque altro (vedi
    # docstring: "le entry con schema-prezzo non riconosciuto vengono
    # scartate, non fanno fallire l'intera selezione"). Un'entry malformata
    # viene ora scartata da questa mappa invece di far esplodere tutto.
    geocode_by_id = {h["id"]: h for h in hotels_by_geocode if "id" in h}

    candidates: list[tuple[float, Hotel]] = []
    for rate_entry in hotel_offers:
        hotel_id = rate_entry.get("hotelId")
        geo = geocode_by_id.get(hotel_id, {})
        lat = geo.get("latitude")
        lng = geo.get("longitude")
        if lat is None or lng is None:
            continue
        try:
            price_total = _extract_total_price(rate_entry)
        except LiteApiError:
            continue
        dist = _distance_sq(lat, lng, dest_lat, dest_lng)
        # [AGGIUNTO 2026-07-11] `hotelTypeId` -> nome leggibile via
        # _HOTEL_TYPE_NAMES; None se assente dalla risposta o se l'id non è
        # tra quelli noti (mai inventato — stesso principio di
        # affiliate_url="[Da Verificare]" già usato in questa stessa
        # funzione). `.get(..., {})`/`.get()` ovunque: un fornitore che non
        # riporta questo campo (es. dati mock/fixture esistenti, mai
        # aggiornati con questo campo) non deve far fallire la selezione.
        hotel_type_id = geo.get("hotelTypeId")
        property_type = _HOTEL_TYPE_NAMES.get(hotel_type_id) if hotel_type_id is not None else None
        hotel = Hotel(
            id=hotel_id,
            name=geo.get("name", "[Da Verificare]"),
            lat=lat,
            lng=lng,
            price_night_eur=round(price_total / max(duration_days, 1), 2),
            stars=geo.get("stars"),  # [FIX 2026-07-10] confermato dal vivo: non "starRating"
            tags=[],
            affiliate_url="[Da Verificare]",
            property_type=property_type,
        )
        candidates.append((dist, hotel))

    candidates.sort(key=lambda c: c[0])
    return [h for _, h in candidates[:max_hotels]]
