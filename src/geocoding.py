"""
NODO 2b — Geocoding. HTTP_MODULES_REALI.md §NODO 2 (upgrade).
Trasforma trip.destination (o l'indirizzo del polo sportivo) in dest_lat/dest_lng.
"""
from __future__ import annotations
import math

import requests

from . import cost_telemetry

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
    # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    # `float(...)` esplicito attorno a lat/lng: un `location["lat"]` presente ma
    # null passava indenne e la funzione restituiva `(None, None)` violando in
    # silenzio il contratto `tuple[float, float]`, col crash che emergeva molto
    # più a valle (aritmetica su dest_lat). Ora un lat/lng null/non-numerico
    # diventa subito un GeocodingError esplicito (TypeError catturato sotto).
    try:
        location = results[0]["geometry"]["location"]
        return float(location["lat"]), float(location["lng"])
    except (KeyError, TypeError, ValueError) as e:
        raise GeocodingError(f"Geocoding OK ma shape della risposta inatteso: campo mancante/invalido {e}") from e


def _safe_json(resp, context: str) -> dict:
    """[AGGIUNTO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    Una risposta 200 con body NON-JSON (pagina HTML da proxy/WAF/captive
    portal — caso già incontrato realmente col proxy del sandbox) faceva
    propagare un `requests.exceptions.JSONDecodeError` grezzo invece del
    `GeocodingError` che il resto del modulo promette: chi cattura
    `GeocodingError` per attivare il percorso email-scuse/refund non lo
    intercettava. Normalizzo qui."""
    try:
        return resp.json()
    except ValueError as e:
        raise GeocodingError(f"{context}: risposta 200 ma body non-JSON ({e})") from e


def geocode(address: str, api_key: str) -> tuple[float, float]:
    cost_telemetry.record_api_call("google_geocoding")
    resp = requests.get(GEOCODE_URL, params=_geocode_params(address, api_key), timeout=15)
    resp.raise_for_status()
    return parse_geocoding_response(_safe_json(resp, "geocode"))


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
        # [AGGIUNTI 2026-08-01 — collaudo PDF reale, difetto 1 "bolla
        # geografica"] Due campi che Google restituisce GIÀ in ogni risposta
        # di geocoding e che finora buttavamo via, pagando la chiamata e non
        # leggendone metà del contenuto.
        "country_code": _extract_country_code(result),
        "viewport_radius_m": _viewport_radius_m(result),
    }


def _extract_country_code(result: dict) -> str | None:
    """Codice paese ISO-3166-1 alpha-2 (`IT`, `PT`, `FR`...) dal risultato di
    geocoding. Serve a `places_client.fetch_nearby_raw(region_code=...)`: senza
    di esso Google applica le convenzioni di denominazione del chiamante e non
    quelle del paese di destinazione — una delle due cause del difetto "nomi in
    lingua sbagliata" trovato nel collaudo del 2026-08-01 (un POI di Lisbona
    tornato con nome portoghese-brasiliano). None se assente: il chiamante
    semplicemente non passa `regionCode` e il comportamento resta quello di
    prima, mai peggiore."""
    for component in result.get("address_components") or []:
        if not isinstance(component, dict):
            continue
        if "country" in (component.get("types") or []):
            short = component.get("short_name")
            if isinstance(short, str) and len(short.strip()) == 2:
                return short.strip().upper()
    return None


# Limiti di sicurezza sul raggio derivato dal viewport. Il minimo evita che un
# borgo minuscolo produca un raggio di 300 m in cui non esiste abbastanza da
# fare; il massimo evita che una richiesta su una regione o su una città
# enorme produca un raggio da decine di km, che è esattamente il modo in cui
# si finisce con nove POI sparsi e inarrivabili a piedi.
_MIN_VIEWPORT_RADIUS_M = 1200
_MAX_VIEWPORT_RADIUS_M = 12000
_EARTH_RADIUS_M = 6371000.0


def _viewport_radius_m(result: dict) -> int | None:
    """[AGGIUNTO 2026-08-01] Raggio di ricerca proporzionato alla DIMENSIONE
    REALE della destinazione, letto dal `viewport` che Google allega a ogni
    risultato di geocoding.

    Perché serve. Fino a oggi il raggio era 3000 m fissi per qualunque
    destinazione: lo stesso numero per Roma e per un paese di duemila
    abitanti. Su una città grande 3 km dal centroide sono una bolla che taglia
    fuori interi quartieri (il difetto 1 del collaudo reale); su un borgo sono
    un raggio che pesca mezza provincia. Il viewport è il rettangolo che Google
    stesso considera "questo luogo": è la misura giusta perché è la misura del
    fornitore del dato, non una nostra stima.

    Restituisce metà della diagonale del viewport, arrotondata, dentro i
    limiti sopra. None se il viewport manca o è malformato — il chiamante
    ricade sul default storico.
    """
    viewport = (result.get("geometry") or {}).get("viewport")
    if not isinstance(viewport, dict):
        return None
    try:
        ne = viewport["northeast"]
        sw = viewport["southwest"]
        ne_lat, ne_lng = float(ne["lat"]), float(ne["lng"])
        sw_lat, sw_lng = float(sw["lat"]), float(sw["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    mid_lat_rad = math.radians((ne_lat + sw_lat) / 2.0)
    dlat_m = math.radians(ne_lat - sw_lat) * _EARTH_RADIUS_M
    dlng_m = math.radians(ne_lng - sw_lng) * _EARTH_RADIUS_M * math.cos(mid_lat_rad)
    half_diagonal = math.hypot(dlat_m, dlng_m) / 2.0
    if half_diagonal <= 0:
        return None
    return int(max(_MIN_VIEWPORT_RADIUS_M, min(_MAX_VIEWPORT_RADIUS_M, round(half_diagonal))))


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
    cost_telemetry.record_api_call("google_geocoding")
    resp = requests.get(GEOCODE_URL, params=_geocode_params(address, api_key), timeout=15)
    resp.raise_for_status()
    return parse_geocoding_response_full(_safe_json(resp, "geocode_full"))
