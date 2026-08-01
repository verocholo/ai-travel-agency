"""
NUOVO 2026-07-31 — sezione "Cartina e come arrivare".

Richiesta letterale di Lorenzo:
  "manca anche la parte 'cartina e come arrivare' in cui spieghi spostamento
   per spostamento come arrivare (una specifica della parte affiliata a
   google maps)"

Questo modulo è la controparte TESTUALE e NAVIGABILE della cartina numerata di
`maps_static.build_day_map_plans()`: per ogni giornata produce la catena degli
spostamenti (hotel -> tappa 1 -> tappa 2 -> ... -> hotel), ciascuno con il
tempo reale quando lo conosciamo e un link che apre l'indicazione stradale vera
sul telefono del cliente.

DUE SCELTE DI PROGETTO, ENTRAMBE SULL'ONESTÀ DEL DATO
-----------------------------------------------------
1. I minuti NON vengono mai inventati. Provengono da `ApiPayload.travel_times`,
   cioè da una chiamata reale alla Distance Matrix di Google fatta a monte
   (Nodo 4). Se per una coppia origine/destinazione non abbiamo la misura, il
   campo `minutes` resta `None` e il PDF scrive "tempo non disponibile" invece
   di una stima plausibile ma falsa. Una stima inventata su una distanza in
   linea d'aria è esattamente il tipo di dato che fa perdere un treno a un
   cliente.
2. Il link NON è una nostra ricostruzione del percorso: è un deep link alla
   Google Maps URLs API
   (https://developers.google.com/maps/documentation/urls/get-started#directions-action),
   documentata, stabile e SENZA chiave API — il calcolo del percorso lo fa
   Google, live, col traffico del momento in cui il cliente lo apre. Noi
   passiamo solo due coordinate REALI e la modalità. Questo chiude anche il
   limite dichiarato in maps_static.py (le linee della cartina statica sono
   segmenti retti, non percorsi di guida): la cartina dà il colpo d'occhio, il
   link dà il percorso vero.
"""
from __future__ import annotations

# Modalità accettate dalla URLs API. `mode` in TravelTime arriva da
# distance_matrix.py e usa lo stesso vocabolario di Google ("driving",
# "walking", "transit", "bicycling"), ma normalizziamo comunque: un valore
# inatteso non deve produrre un URL che Google rifiuta.
_VALID_TRAVEL_MODES = {"driving", "walking", "bicycling", "transit"}
_DEFAULT_TRAVEL_MODE = "walking"

_MODE_LABEL_IT = {
    "driving": "in auto",
    "walking": "a piedi",
    "bicycling": "in bici",
    "transit": "con i mezzi",
}

DIRECTIONS_BASE_URL = "https://www.google.com/maps/dir/"


def travel_mode_label(mode: str | None) -> str:
    return _MODE_LABEL_IT.get(_normalize_mode(mode), _MODE_LABEL_IT[_DEFAULT_TRAVEL_MODE])


def _normalize_mode(mode: str | None) -> str:
    if isinstance(mode, str) and mode.lower() in _VALID_TRAVEL_MODES:
        return mode.lower()
    return _DEFAULT_TRAVEL_MODE


def build_directions_url(
    origin: tuple[float, float],
    destination: tuple[float, float],
    mode: str | None = None,
) -> str | None:
    """Deep link Google Maps "indicazioni stradali" tra due coordinate reali.

    Ritorna `None` se una delle due coordinate non è utilizzabile — meglio
    nessun link che un link che apre Google Maps sul punto sbagliato.
    Nessuna chiave API: la URLs API è pubblica e documentata.
    """
    try:
        o_lat, o_lng = float(origin[0]), float(origin[1])
        d_lat, d_lng = float(destination[0]), float(destination[1])
    except (TypeError, ValueError, IndexError):
        return None
    return (
        f"{DIRECTIONS_BASE_URL}?api=1"
        f"&origin={o_lat},{o_lng}"
        f"&destination={d_lat},{d_lng}"
        f"&travelmode={_normalize_mode(mode)}"
    )


def build_travel_time_lookup(travel_times) -> dict[tuple[str, str], dict]:
    """`[TravelTime]` -> `{(origin_id, dest_id): {"minutes", "mode"}}`.

    Se esistono più misure per la stessa coppia (il Nodo 4 interroga la
    Distance Matrix sia in "driving" sia in "walking"), tiene quella PIÙ BREVE:
    su una tappa urbana è quasi sempre quella a piedi, ed è quella che il
    cliente sceglierebbe davvero. Ignora silenziosamente le entry malformate.
    """
    lookup: dict[tuple[str, str], dict] = {}
    for tt in travel_times or []:
        origin = getattr(tt, "origin_id", None)
        dest = getattr(tt, "dest_id", None)
        minutes = getattr(tt, "minutes", None)
        if not isinstance(origin, str) or not isinstance(dest, str):
            continue
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            continue
        key = (origin, dest)
        current = lookup.get(key)
        if current is None or minutes < current["minutes"]:
            lookup[key] = {"minutes": minutes, "mode": getattr(tt, "mode", None)}
    return lookup


def build_day_legs(plan: dict, travel_lookup: dict[tuple[str, str], dict] | None = None) -> list[dict]:
    """
    Dalla "plan" di una giornata (`maps_static.build_day_map_plans()`) alla
    catena degli spostamenti di quella giornata.

    Ogni leg è:
      {"from_label", "from_name", "to_label", "to_name",
       "minutes": int|None, "mode": str, "mode_label": str, "url": str|None}

    Le etichette (`from_label`/`to_label`) sono le STESSE della cartina — "H",
    "1", "2", ... — così il cliente legge "da 2 a 3" guardando i due numeri
    che ha davanti sulla mappa. È l'anello che mancava tra cartina e testo.

    L'ultimo leg (ultima tappa -> hotel) c'è solo se conosciamo l'hotel: il
    rientro serale è uno spostamento reale come gli altri, ed è quello in cui
    il cliente è più stanco e più ha bisogno del link.
    """
    travel_lookup = travel_lookup or {}
    stops = plan.get("stops") or []
    hotel_point = plan.get("hotel_point")
    hotel_id = plan.get("hotel_id")
    hotel_name = plan.get("hotel_name") or "Alloggio"

    nodes = []
    if hotel_point is not None:
        nodes.append({"label": "H", "name": hotel_name, "point": hotel_point, "poi_id": hotel_id})
    for stop in stops:
        nodes.append({
            "label": stop.get("label") or "",
            "name": stop.get("location") or stop.get("activity") or "",
            "point": stop.get("point"),
            "poi_id": stop.get("poi_id"),
            "time": stop.get("time") or "",
        })
    if hotel_point is not None and stops:
        nodes.append({"label": "H", "name": hotel_name, "point": hotel_point, "poi_id": hotel_id})

    legs = []
    for i in range(len(nodes) - 1):
        origin, dest = nodes[i], nodes[i + 1]
        if origin.get("point") is None or dest.get("point") is None:
            continue
        measured = travel_lookup.get((origin.get("poi_id"), dest.get("poi_id")))
        if measured is None:
            # la Distance Matrix è simmetrica nei fatti per gli spostamenti
            # urbani brevi: se abbiamo solo la direzione opposta, la usiamo e
            # NON fingiamo che sia una misura diversa.
            measured = travel_lookup.get((dest.get("poi_id"), origin.get("poi_id")))
        minutes = measured["minutes"] if measured else None
        mode = _normalize_mode(measured.get("mode") if measured else None)
        legs.append({
            "from_label": origin.get("label", ""),
            "from_name": origin.get("name", ""),
            "to_label": dest.get("label", ""),
            "to_name": dest.get("name", ""),
            "arrival_time": dest.get("time", ""),
            "minutes": minutes,
            "mode": mode,
            "mode_label": travel_mode_label(mode),
            "url": build_directions_url(origin["point"], dest["point"], mode),
        })
    return legs


def build_directions_by_day(day_plans: list[dict], travel_times=None) -> list[dict]:
    """Comodità per il renderer: `[{"day", "title", "legs": [...]}]`.
    Non solleva mai: una giornata malformata produce semplicemente 0 leg."""
    lookup = build_travel_time_lookup(travel_times)
    out = []
    for plan in day_plans or []:
        if not isinstance(plan, dict):
            continue
        out.append({
            "day": plan.get("day"),
            "title": plan.get("title") or "",
            "legs": build_day_legs(plan, lookup),
        })
    return out
