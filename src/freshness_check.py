"""
Controllo di freschezza pre-partenza (prototipo) — src/freshness_check.py.

[NUOVO 2026-07-12 — richiesta di Lorenzo, idea proposta da Claude e
accettata: "un controllo automatico qualche giorno prima della partenza
che riverifica orari/disponibilità e segnala eventuali cambiamenti"]

Un itinerario viene generato con dati verificati in un certo momento, ma
il viaggio può avvenire settimane o mesi dopo. Questo modulo NON introduce
una nuova API — riusa esattamente gli stessi due client HTTP già
integrati e testati (`liteapi_client.py`, `places_client.py`), interrogati
di nuovo più vicino alla data del viaggio, per rilevare cambiamenti
rispetto allo snapshot originale:

- Hotel: `search_hotel_offers([hotel.id], ...)` — se lo stesso id non
  restituisce più tariffe per le date del viaggio, è un segnale reale che
  qualcosa è cambiato (esaurito, ritirato dall'inventario, ecc.).
- POI: `search_nearby()` con raggio stretto attorno alle coordinate del
  POI originale — se lo stesso id non compare più, è un segnale (chiuso,
  spostato, o semplicemente fuori dai primi risultati — l'onestà del
  messaggio riflette questa incertezza, non dichiara "chiuso" come fatto
  certo).

Verifica SOLO gli elementi EFFETTIVAMENTE USATI nell'itinerario (i
`poi_id` referenziati nei blocks, più l'hotel-ancora) — non l'intero
DATI_API_FORNITI originale, che può contenere candidati mai scelti da
Claude e quindi irrilevanti per il cliente.

**Nota di onestà, stesso principio già seguito altrove nel progetto**:
questo modulo richiede le stesse chiavi API live di `--mode live`
(GOOGLE_MAPS_KEY, LITEAPI_KEY) — non testabile con chiamate reali da
questo ambiente sandbox (rete ad allowlist, stesso limite già documentato
per il tentativo di click-test in browser). I test automatici mockano
entrambi i client, stesso pattern di `test_pipeline.py::TestRunLiveModuleSelection`.
Una verifica dal vivo resta da fare da Lorenzo, come già per `--mode live`.
Il canale di invio reale (es. email automatica N giorni prima della
partenza) resta una decisione della fase Make.com — qui costruiamo e
verifichiamo solo la logica del controllo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .liteapi_client import LiteApiClient
from .places_client import search_nearby
from .schemas import Trip, Hotel, POI, ApiPayload


@dataclass
class FreshnessItemResult:
    id: str
    name: str
    kind: str  # "hotel" | "poi"
    still_confirmed: bool
    detail: str


@dataclass
class FreshnessReport:
    items: list[FreshnessItemResult] = field(default_factory=list)

    @property
    def all_confirmed(self) -> bool:
        return all(item.still_confirmed for item in self.items)

    def summary(self) -> str:
        if not self.items:
            return "Nessun elemento da verificare (itinerario senza hotel/POI referenziati)."
        lines = []
        for item in self.items:
            mark = "✅" if item.still_confirmed else "⚠️"
            lines.append(f"{mark} [{item.kind}] {item.name} ({item.id}): {item.detail}")
        return "\n".join(lines)


def check_hotel_freshness(hotel: Hotel, trip: Trip, client: LiteApiClient) -> FreshnessItemResult:
    try:
        offers = client.search_hotel_offers([hotel.id], trip.date_start, trip.date_end)
    except Exception as e:
        # [FIX 2026-07-12 — trovato con una vera chiamata dal vivo contro
        # api.liteapi.travel, non in teoria] `search_hotel_offers()` NON
        # avvolge i fallimenti di rete/HTTP in `LiteApiError` (lo fa solo
        # per risposte 200 con dati mancanti — vedi liteapi_client.py) —
        # un errore di connessione/proxy/timeout si propaga come
        # `requests.exceptions.*` grezzo. Il primo giro di questo modulo
        # catturava solo `LiteApiError`, quindi un vero `ProxyError` (403
        # dal proxy di rete di questo ambiente sandbox, verificato dal
        # vivo) faceva crashare l'intero controllo con un traceback invece
        # di essere segnalato come un singolo item non verificato — stessa
        # ampiezza di `except Exception` già usata in `check_poi_freshness`
        # qui sotto, ora allineata per coerenza.
        return FreshnessItemResult(
            hotel.id, hotel.name, "hotel", False, f"Verifica fallita (errore di rete/API): {e}"
        )
    found = any(o.get("hotelId") == hotel.id or o.get("id") == hotel.id for o in offers)
    if found:
        return FreshnessItemResult(
            hotel.id, hotel.name, "hotel", True, "Tariffe ancora disponibili per queste date"
        )
    return FreshnessItemResult(
        hotel.id, hotel.name, "hotel", False,
        "Nessuna tariffa trovata per queste date in una nuova ricerca — potrebbe essere "
        "esaurito o non più disponibile: verificare manualmente prima di confermare al cliente",
    )


def check_poi_freshness(poi: POI, google_maps_key: str, radius_m: int = 200) -> FreshnessItemResult:
    try:
        fresh_pois = search_nearby(
            poi.lat, poi.lng, google_maps_key, radius_m=radius_m, max_results=20, included_types=None
        )
    except Exception as e:  # stesso principio di places_client.py: non inghiottire, ma non serve un tipo specifico qui
        return FreshnessItemResult(
            poi.id, poi.name, "poi", False, f"Verifica fallita (errore di rete/API): {e}"
        )
    found = any(p.id == poi.id for p in fresh_pois)
    if found:
        return FreshnessItemResult(
            poi.id, poi.name, "poi", True, "Ancora presente in una nuova ricerca nella stessa zona"
        )
    return FreshnessItemResult(
        poi.id, poi.name, "poi", False,
        "Non trovato in una nuova ricerca nella stessa zona — potrebbe essere chiuso, "
        "spostato, o semplicemente fuori dai primi risultati: verificare manualmente",
    )


def run_freshness_check(
    itinerary: dict,
    api_payload: ApiPayload,
    trip: Trip,
    google_maps_key: str,
    liteapi_key: str,
) -> FreshnessReport:
    used_poi_ids = {
        block.get("poi_id")
        for day in itinerary.get("days", [])
        for block in day.get("blocks", [])
        if block.get("poi_id")
    }
    poi_by_id = {p.id: p for p in api_payload.poi}

    client = LiteApiClient(liteapi_key)
    report = FreshnessReport()

    # L'hotel-ancora non passa da poi_id nei blocks — verificato sempre,
    # indipendentemente da quali POI sono stati effettivamente scelti.
    for hotel in api_payload.hotels:
        report.items.append(check_hotel_freshness(hotel, trip, client))

    for poi_id in used_poi_ids:
        poi = poi_by_id.get(poi_id)
        if poi is None:
            # Difensivo: non dovrebbe succedere se il Nodo 9 (Fedeltà RAG)
            # ha già validato l'itinerario — un poi_id riferito che non
            # esiste tra i dati forniti sarebbe stato bloccato prima.
            continue
        report.items.append(check_poi_freshness(poi, google_maps_key))

    return report
