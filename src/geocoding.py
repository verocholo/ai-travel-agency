"""
NODO 2b — Geocoding. HTTP_MODULES_REALI.md §NODO 2 (upgrade).
Trasforma trip.destination (o l'indirizzo del polo sportivo) in dest_lat/dest_lng.
"""
from __future__ import annotations
import requests

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# [AGGIUNTO 2026-07-11 — audit di qualità, secondo giro] Bug reale scoperto
# nel capstone test famiglia: la fixture chiedeva "San Marino,
# Emilia-Romagna" (errore mio di autoring, San Marino non è affatto in
# Emilia-Romagna — è uno stato sovrano indipendente) e il bias
# region="it", hardcoded qui sotto per OGNI chiamata di geocoding, ha
# spinto Google a risolvere la query verso un'omonima località italiana
# vicino Carpi (provincia di Modena) invece della vera Repubblica di San
# Marino. Il fix più diretto per la fixture è stato correggere la stringa
# ("Repubblica di San Marino"), ma resta un rischio strutturale: QUALSIASI
# destinazione futura il cui nome coincide con un'enclave/microstato
# straniero all'interno o ai confini d'Italia sarebbe soggetta allo stesso
# tipo di mis-geocode, indipendentemente da quanto la fixture sia scritta
# bene. Fix strutturale: per questi nomi noti, omettiamo del tutto il
# parametro `region` (non lo ri-bias-iamo semplicemente su un altro
# valore) — nessuna chiamata API aggiuntiva, nessun rischio di falsi
# positivi introdotto (a differenza dell'alternativa "doppio geocode e
# confronta", scartata proprio per questo). Il confronto è case-insensitive
# e su una lista chiusa e piccola: gli unici casi noti di enclave/
# microstato il cui nome può comparire come destinazione di viaggio in
# Italia o ai suoi confini.
_REGION_BIAS_BYPASS_NAMES = frozenset({
    "san marino",
    "repubblica di san marino",
    "città del vaticano",
    "citta del vaticano",
    "vaticano",
    "stato della città del vaticano",
})


def _should_bypass_region_bias(address: str) -> bool:
    """Vero se `address` corrisponde (case-insensitive, dopo strip) a uno
    dei nomi noti di enclave/microstato per cui il bias region="it" va
    omesso. Confronto volutamente semplice ed esatto (non substring): un
    match troppo permissivo (es. "via San Marino 4, Roma") userebbe questa
    stessa lista per bypassare il bias su un indirizzo italiano reale,
    reintroducendo un rischio invece di eliminarlo."""
    return address.strip().casefold() in _REGION_BIAS_BYPASS_NAMES


def _geocode_params(address: str, api_key: str) -> dict:
    params = {"address": address, "language": "it", "key": api_key}
    if not _should_bypass_region_bias(address):
        params["region"] = "it"
    return params


class GeocodingError(Exception):
    pass


def parse_geocoding_response(data: dict) -> tuple[float, float]:
    """Funzione pura, testabile senza rete — separa parsing da I/O."""
    if data.get("status") != "OK":
        raise GeocodingError(
            f"Geocoding fallito: status={data.get('status')} "
            f"(vedi [Filter] validazione, Cap. 7 Chaos Engineering: "
            f"ZERO_RESULTS/INVALID_REQUEST -> Nodo E1 email scuse + Stripe refund)"
        )
    results = data.get("results") or []
    if not results:
        raise GeocodingError("Geocoding OK ma results[] vuoto")
    # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] status="OK" con uno
    # shape interno inatteso (campo "geometry"/"location" mancante o
    # rinominato da un futuro cambio API) faceva crashare con un KeyError
    # grezzo invece del GeocodingError esplicito già usato per gli altri
    # casi di fallimento in questa stessa funzione — inconsistente con la
    # filosofia "fallisci in modo esplicito" del resto del prototipo.
    try:
        location = results[0]["geometry"]["location"]
        return location["lat"], location["lng"]
    except (KeyError, TypeError) as e:
        raise GeocodingError(f"Geocoding OK ma shape della risposta inatteso: campo mancante {e}") from e


def geocode(address: str, api_key: str) -> tuple[float, float]:
    resp = requests.get(GEOCODE_URL, params=_geocode_params(address, api_key), timeout=15)
    resp.raise_for_status()
    return parse_geocoding_response(resp.json())


def parse_geocoding_response_full(data: dict) -> dict:
    """[AGGIUNTO 2026-07-10] Come parse_geocoding_response(), ma espone anche
    `location_type`/`formatted_address` — nati da un bug reale scoperto in
    Fase 3: "Val d'Orcia, Toscana" (nome di valle, non di comune con un
    centro univoco) è stato geocodificato a 60-70km dal luogo reale, senza
    nessun errore esplicito (status era comunque "OK"). Google segnala
    proprio questi casi con `location_type`: vedi is_imprecise_match().
    Funzione pura, testabile senza rete — stesso principio di
    parse_geocoding_response()."""
    lat, lng = parse_geocoding_response(data)
    result = data["results"][0]
    return {
        "lat": lat,
        "lng": lng,
        "location_type": result.get("geometry", {}).get("location_type", "UNKNOWN"),
        "formatted_address": result.get("formatted_address", ""),
    }


def is_imprecise_match(location_type: str) -> bool:
    """`ROOFTOP`/`RANGE_INTERPOLATED` = Google ha trovato un indirizzo
    puntuale (edificio/civico). `APPROXIMATE`/`GEOMETRIC_CENTER` = nessun
    punto preciso — tipicamente un nome di area/regione/valle senza un
    centro univoco, esattamente il caso che ha causato il bug di Fase 3.
    Non un errore hard (`status` resta "OK"), ma un segnale da non ignorare
    silenziosamente prima di usare le coordinate per la ricerca radiale."""
    return location_type in ("APPROXIMATE", "GEOMETRIC_CENTER")


def geocode_full(address: str, api_key: str) -> dict:
    """Come geocode(), ma ritorna anche location_type/formatted_address per
    poter segnalare match imprecisi invece di propagarli in silenzio."""
    resp = requests.get(GEOCODE_URL, params=_geocode_params(address, api_key), timeout=15)
    resp.raise_for_status()
    return parse_geocoding_response_full(resp.json())
