"""
NUOVO 2026-07-12 — "cartina + percorsi", richiesta di prodotto di Lorenzo.

Costruisce e scarica un'immagine statica (Google Maps Static API) con un
marker per l'hotel-ancora e per ciascun POI EFFETTIVAMENTE USATO
nell'itinerario (non l'intero DATI_API_FORNITI — stessa Fedeltà RAG del
resto del progetto, vedi src/itinerary_utils.py), più una linea per
ciascun giorno che collega le tappe nell'ordine visitato.

**Onestà sui limiti, dichiarata anche nel documento cliente**: le linee
sono segmenti retti tra coordinate reali, NON un percorso di guida vero
(che richiederebbe la Directions API di Google, non integrata in questo
prototipo) — una semplificazione visiva dichiarata, non un dato inventato:
le coordinate di partenza/arrivo di ogni segmento sono reali e verificate,
solo la forma della linea tra i due punti è approssimata.

Stessa architettura "pura vs HTTP" già seguita in places_client.py:
`build_static_map_url()` è una funzione pura (testabile senza rete),
`fetch_static_map_png()` isola la sola chiamata HTTP,
`build_map_for_itinerary()` orchestra i dati reali e non solleva MAI
un'eccezione verso il chiamante — una cartina mancante (chiave assente,
rete irraggiungibile, quota esaurita) non deve mai far fallire l'intero
PDF, stesso principio già applicato a guida/feedback in
main.py::_build_pdf_extras().
"""
from __future__ import annotations

import math
from urllib.parse import quote

import requests

from .itinerary_utils import extract_used_poi_ids_by_day

STATIC_MAP_BASE_URL = "https://maps.googleapis.com/maps/api/staticmap"

# [AGGIUNTO 2026-07-12 — audit di revisione completa] Limite documentato
# di Google Static Maps (~8192 caratteri per URL) — vedi
# developers.google.com/maps/documentation/maps-static/start#url-size-restriction.
# Usiamo un margine conservativo (8000, non 8192) per lasciare spazio a
# eventuali differenze di conteggio tra client/server.
_MAX_URL_LENGTH = 8000

# Stile marker per tipo di POI — colori validi predefiniti dell'API
# (developers.google.com/maps/documentation/maps-static/start#Markers).
# L'hotel ha sempre un marker proprio, distinto dai POI.
_HOTEL_MARKER_STYLE = {"color": "red", "label": "H"}
_MARKER_STYLE_BY_TYPE = {
    "restaurant": {"color": "green", "label": "R"},
    "museum": {"color": "orange", "label": "M"},
    "activity": {"color": "blue", "label": "A"},
    # [AGGIUNTO 2026-07-13 (ter) — categoria shopping] "purple" è un colore
    # valido predefinito dell'API (stessa fonte del commento sopra),
    # distinto dagli altri tre già in uso.
    "shopping": {"color": "purple", "label": "S"},
}
_FALLBACK_MARKER_STYLE = {"color": "gray", "label": "P"}

# Un colore per giorno (ciclico se i giorni superano la palette) — stessi
# colori del brand già usati nel CSS del PDF (pdf_renderer.py `_CSS`), per
# coerenza visiva tra cartina e documento.
_PATH_COLORS = ["0x1a3b5c", "0x2f6690", "0xc9762f", "0x3f8f5f", "0x8a97a3", "0x6b7a89"]


class MapsStaticError(Exception):
    """Sollevata se Google Static Maps risponde con un errore HTTP o con
    un contenuto che non è un'immagine — stesso pattern di
    GeocodingError/LiteApiError altrove nel progetto: mai un fallimento
    silenzioso o un file corrotto scambiato per un PNG valido."""


def _quote(value) -> str:
    # `,` e `:` e `|` sono separatori significativi nella sintassi di
    # Static Maps (coordinate, stile, elenco punti) — li lasciamo
    # letterali; tutto il resto (qui solo cifre/lettere/punto decimale,
    # mai testo esterno non fidato: nessun nome hotel/POI finisce in
    # questa URL, solo coordinate e colori) viene comunque percent-encoded
    # per correttezza.
    return quote(str(value), safe=",:|")


def build_static_map_url(
    markers_by_style: list[dict],
    paths: list[dict],
    api_key: str,
    size: str = "640x400",
    center: tuple[float, float] | None = None,
    zoom: int | None = None,
) -> str | None:
    """
    Funzione pura — costruisce l'URL della Google Static Maps API.

    `markers_by_style`: lista di `{"color": ..., "label": ..., "points": [(lat,lng), ...]}`.
    `paths`: lista di `{"color": ..., "points": [(lat,lng), ...]}` — un
    path con meno di 2 punti non produce alcuna linea (non ha senso
    disegnare un segmento con un solo punto), viene scartato.

    [AGGIUNTO 2026-07-13 (ter) — richiesta di Lorenzo: "la mappa dovrebbe
    essere più zoomata sulla città", confermata come miglioramento
    generale di prodotto via AskUserQuestion] `center`/`zoom`, se
    forniti, vengono passati esplicitamente all'API invece di lasciare
    che Google calcoli da sé un riquadro che include tutti i marker/path
    — stessa tecnica già validata a mano per le mappe TomTom del viaggio
    di Lorenzo: l'auto-fit implicito di un provider di mappe tende ad
    aggiungere più margine del necessario attorno ai punti reali, "meno
    zoomato" di quanto un cliente vorrebbe vedere. Vedi
    `compute_center_zoom()` sotto per come vengono calcolati a partire
    dalle coordinate REALI di hotel/POI — mai un centro/zoom arbitrario.
    Se omessi (default None), il comportamento resta quello originale
    (auto-fit implicito di Google) — nessuna rottura per chiamanti
    esistenti che non li passano.

    Ritorna `None` se non c'è assolutamente nulla da disegnare (nessun
    marker, nessun path con almeno 2 punti) — non ha senso costruire una
    cartina vuota.
    """
    query_parts = [f"size={_quote(size)}"]
    if center is not None:
        query_parts.append(f"center={_quote(f'{center[0]},{center[1]}')}")
    if zoom is not None:
        query_parts.append(f"zoom={_quote(zoom)}")
    has_content = False

    for style in markers_by_style:
        points = style.get("points") or []
        if not points:
            continue
        has_content = True
        locations = "|".join(f"{lat},{lng}" for lat, lng in points)
        style_str = f"color:{style['color']}"
        if style.get("label"):
            style_str += f"|label:{style['label']}"
        query_parts.append(f"markers={_quote(style_str)}|{_quote(locations)}")

    for path in paths:
        points = path.get("points") or []
        if len(points) < 2:
            continue
        has_content = True
        locations = "|".join(f"{lat},{lng}" for lat, lng in points)
        style_str = f"color:{path['color']}|weight:4"
        query_parts.append(f"path={_quote(style_str)}|{_quote(locations)}")

    if not has_content:
        return None

    query_parts.append(f"key={_quote(api_key)}")
    return STATIC_MAP_BASE_URL + "?" + "&".join(query_parts)


def fetch_static_map_png(url: str, timeout: int = 15) -> bytes:
    """Isola la sola chiamata HTTP (stesso principio di
    places_client.py::fetch_nearby_raw() — ispeziona la risposta reale
    prima di fidarti del chiamante che la usa)."""
    resp = requests.get(url, timeout=timeout)
    if resp.status_code != 200:
        raise MapsStaticError(
            f"Google Static Maps ha risposto {resp.status_code}: "
            f"{(resp.text or '')[:300] or '[nessun dettaglio]'}"
        )
    content_type = resp.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        raise MapsStaticError(
            f"Google Static Maps non ha restituito un'immagine "
            f"(Content-Type: {content_type!r})"
        )
    return resp.content


# [AGGIUNTO 2026-07-13 (ter) — richiesta di Lorenzo: "la mappa dovrebbe
# essere più zoomata sulla città", confermata come miglioramento generale
# di prodotto (non specifico al suo viaggio) via AskUserQuestion] Stessa
# tecnica di calcolo già validata a mano, punto per punto, per le mappe
# TomTom del viaggio personale di Lorenzo (Web Mercator, centro+zoom
# espliciti invece di un bbox/auto-fit che il provider tende ad
# espandere più del necessario) — qui generalizzata in una funzione pura
# e testata, non più un calcolo manuale una tantum.
_WORLD_PX = 256  # dimensione della mappa mondiale intera a zoom 0 (convenzione Web Mercator standard)


def _lat_to_mercator_y(lat_deg: float) -> float:
    lat_rad = math.radians(max(min(lat_deg, 85.05), -85.05))  # clamp: la proiezione di Mercatore diverge ai poli
    return math.log(math.tan(math.pi / 4 + lat_rad / 2))


def compute_center_zoom(
    points: list[tuple[float, float]],
    width_px: int,
    height_px: int,
    padding_ratio: float = 0.18,
    min_zoom: int = 2,
    max_zoom: int = 17,
) -> tuple[float, float, int] | None:
    """
    Funzione pura (nessuna chiamata di rete) — calcola il centro e lo
    zoom Web Mercator che inquadrano TUTTI i `points` forniti (coordinate
    REALI di hotel/POI, mai un punto inventato) con un margine di
    sicurezza (`padding_ratio`, di default il 18% dell'immagine, per non
    tagliare etichette/marker ai bordi — stesso ordine di grandezza già
    usato a mano per le mappe TomTom, 22%-38% a seconda del giorno).

    Ritorna `None` se `points` è vuoto (nessuna cartina da centrare — il
    chiamante deve già gestire questo caso, qui solo per difesa in
    profondità). Con un solo punto (o più punti coincidenti), non c'è un
    bbox da inquadrare: ritorna uno zoom fisso "a livello di quartiere"
    (`max_zoom - 2`) centrato su quell'unico punto.
    """
    if not points:
        return None

    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)
    center_lat = (min_lat + max_lat) / 2
    center_lng = (min_lng + max_lng) / 2

    if min_lat == max_lat and min_lng == max_lng:
        return center_lat, center_lng, max_zoom - 2

    lng_span = max_lng - min_lng
    x_frac = lng_span / 360.0

    y_top = _lat_to_mercator_y(max_lat)
    y_bottom = _lat_to_mercator_y(min_lat)
    y_frac = (y_top - y_bottom) / (2 * math.pi)

    usable_width = width_px * (1 - padding_ratio)
    usable_height = height_px * (1 - padding_ratio)

    # zoom tale che (world_px * frazione_di_mondo_coperta * 2^zoom) stia
    # nello spazio utile dell'immagine — stessa formula (invertita) usata
    # per calcolare quanti pixel copre una data estensione geografica a un
    # dato zoom.
    zoom_x = math.log2(usable_width / (_WORLD_PX * x_frac)) if x_frac > 0 else max_zoom
    zoom_y = math.log2(usable_height / (_WORLD_PX * y_frac)) if y_frac > 0 else max_zoom

    zoom = math.floor(min(zoom_x, zoom_y))
    zoom = max(min_zoom, min(max_zoom, zoom))
    return center_lat, center_lng, zoom


def _parse_size(size: str) -> tuple[int, int]:
    """`"640x400"` -> `(640, 400)`. Difensivo: un formato inatteso (mai
    dovrebbe capitare, `size` è sempre un letterale interno, non input
    esterno) ricade sul default del prodotto invece di sollevare
    un'eccezione che farebbe fallire l'intera cartina."""
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 640, 400


def build_map_for_itinerary(
    hotels: list,
    pois: list,
    itinerary: dict,
    api_key: str | None,
    size: str = "640x400",
) -> bytes | None:
    """
    Orchestrazione ad alto livello: dati reali (`hotels`/`pois` — oggetti
    con `.id`/`.lat`/`.lng`/`.type`, es. `ApiPayload.hotels`/`ApiPayload.poi`)
    + l'itinerario GIÀ GENERATO da Claude → URL della cartina → PNG.

    Degrada in modo pulito, MAI un'eccezione verso il chiamante: ritorna
    `None` se manca la chiave API, se non c'è nulla da disegnare (nessun
    poi_id usato e nessun hotel), o se il download fallisce per
    qualunque motivo di rete — una cartina mancante non deve mai far
    fallire l'intero PDF (stesso principio di guida/feedback in
    main.py::_build_pdf_extras()).
    """
    if not api_key:
        return None

    used_ids_by_day = extract_used_poi_ids_by_day(itinerary)
    hotel_points = [(h.lat, h.lng) for h in hotels]
    hotel_ids = {h.id for h in hotels}
    poi_by_id = {p.id: p for p in pois}

    markers_by_style = []
    if hotel_points:
        markers_by_style.append({**_HOTEL_MARKER_STYLE, "points": hotel_points})

    used_poi_ids = {pid for ids in used_ids_by_day.values() for pid in ids} - hotel_ids
    points_by_type: dict[str, list[tuple[float, float]]] = {}
    for poi_id in used_poi_ids:
        poi = poi_by_id.get(poi_id)
        if poi is None:
            continue
        points_by_type.setdefault(poi.type, []).append((poi.lat, poi.lng))

    for poi_type, points in points_by_type.items():
        style = _MARKER_STYLE_BY_TYPE.get(poi_type, _FALLBACK_MARKER_STYLE)
        markers_by_style.append({**style, "points": points})

    all_points_by_id = {h.id: (h.lat, h.lng) for h in hotels}
    all_points_by_id.update({p.id: (p.lat, p.lng) for p in pois})

    # [AGGIUNTO 2026-07-12 — audit di revisione completa, bug reale trovato
    # ed eseguito] Prima, il percorso di OGNI giorno usava sempre e solo
    # `hotel_points[0]` come punto di partenza/arrivo, indipendentemente da
    # QUALE hotel quel giorno usasse davvero — con più di un hotel
    # nell'itinerario (lo schema `ApiPayload.hotels` lo permette, anche se
    # l'architettura attuale a "1 hotel-ancora" del Nodo 4 lo rende raro in
    # pratica oggi), la linea disegnata poteva collegare un giorno intero
    # trascorso vicino all'hotel B con un segmento fantasma verso l'hotel A
    # — dimostrato con un caso reale a due hotel in città diverse. Corretto
    # scegliendo, per ciascun giorno, l'hotel ancora più pertinente: quello
    # esplicitamente referenziato quel giorno (es. check-in/check-out) se
    # presente, altrimenti il più vicino ai punti reali di quel giorno.
    paths = []
    for i, day_num in enumerate(sorted(used_ids_by_day)):
        day_ids = used_ids_by_day[day_num]
        anchor = _pick_day_anchor(day_ids, hotel_points, hotel_ids, all_points_by_id)
        path_points = []
        if anchor is not None:
            path_points.append(anchor)
        for pid in day_ids:
            if pid in hotel_ids:
                continue  # già rappresentato dall'anchor, non un secondo punto
            point = all_points_by_id.get(pid)
            if point is not None:
                path_points.append(point)
        if anchor is not None:
            path_points.append(anchor)
        if len(path_points) >= 2:
            paths.append({"color": _PATH_COLORS[i % len(_PATH_COLORS)], "points": path_points})

    # [AGGIUNTO 2026-07-13 (ter) — vedi compute_center_zoom()] Centro/zoom
    # calcolati sul bbox di TUTTI i punti realmente disegnati come marker
    # (hotel-ancora + POI effettivamente usati) — mai sui punti dei path
    # da soli, che potrebbero non includere un hotel/POI isolato mostrato
    # solo come marker in un giorno senza percorso disegnabile.
    all_marker_points = [p for style in markers_by_style for p in style.get("points", [])]
    width_px, height_px = _parse_size(size)
    center_zoom = compute_center_zoom(all_marker_points, width_px, height_px)
    center = (center_zoom[0], center_zoom[1]) if center_zoom else None
    zoom = center_zoom[2] if center_zoom else None

    url = build_static_map_url(markers_by_style, paths, api_key, size=size, center=center, zoom=zoom)
    if url is None:
        return None

    # [AGGIUNTO 2026-07-12 — audit di revisione completa, bug reale
    # trovato ed eseguito] Google Static Maps ha un limite documentato di
    # ~8192 caratteri per URL — un itinerario con molti giorni/POI (questo
    # stesso PDF anticipa itinerari fino a ~30 giorni, vedi pdf_renderer.py)
    # può superarlo facilmente (dimostrato con 14 giorni x 8 POI/giorno ->
    # oltre 9200 caratteri). Senza questo controllo, la cartina sparisce
    # silenziosamente (stesso avviso generico di un fallimento di rete)
    # proprio per gli itinerari più ricchi, dove sarebbe più utile. Prima
    # di arrendersi, ritenta senza i percorsi (solo i marker, che crescono
    # molto più lentamente con la dimensione dell'itinerario) — una
    # cartina con soli marker è comunque più utile di nessuna cartina.
    if len(url) > _MAX_URL_LENGTH and paths:
        print("⚠️  Cartina: URL troppo lungo per l'itinerario completo, ritento senza i percorsi (solo marker)")
        url = build_static_map_url(markers_by_style, [], api_key, size=size, center=center, zoom=zoom)
        if url is None:
            return None
    if len(url) > _MAX_URL_LENGTH:
        print("⚠️  Cartina saltata: itinerario troppo grande per Google Static Maps anche coi soli marker")
        return None

    try:
        return fetch_static_map_png(url)
    except (MapsStaticError, requests.exceptions.RequestException) as e:
        print(f"⚠️  Cartina saltata (impossibile scaricarla da Google Static Maps): {e}")
        return None


def _pick_day_anchor(
    day_ids: list[str],
    hotel_points: list[tuple[float, float]],
    hotel_ids: set[str],
    all_points_by_id: dict[str, tuple[float, float]],
) -> tuple[float, float] | None:
    """Sceglie l'hotel-ancora più pertinente per il percorso di un giorno:
    (1) un hotel esplicitamente referenziato quel giorno (es. check-in),
    (2) altrimenti l'hotel più vicino ai punti reali usati quel giorno,
    (3) altrimenti il primo hotel disponibile (unico caso oggi, dato il
    limite architetturale a 1 hotel-ancora del Nodo 4). Nessun hotel ->
    `None` (nessun punto di ancoraggio per il percorso)."""
    if not hotel_points:
        return None
    referenced_hotel_ids = [hid for hid in day_ids if hid in hotel_ids]
    if referenced_hotel_ids:
        point = all_points_by_id.get(referenced_hotel_ids[0])
        if point is not None:
            return point
    if len(hotel_points) == 1:
        return hotel_points[0]
    real_points_today = [
        all_points_by_id[pid] for pid in day_ids
        if pid in all_points_by_id and pid not in hotel_ids
    ]
    if not real_points_today:
        return hotel_points[0]
    mean_lat = sum(p[0] for p in real_points_today) / len(real_points_today)
    mean_lng = sum(p[1] for p in real_points_today) / len(real_points_today)
    return min(hotel_points, key=lambda hp: (hp[0] - mean_lat) ** 2 + (hp[1] - mean_lng) ** 2)
