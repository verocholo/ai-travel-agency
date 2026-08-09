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

from . import cost_telemetry
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
    scale: int | None = None,
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
    # [AGGIUNTO 2026-07-31 — feedback di Lorenzo: "migliorare la parte grafica,
    # la parte da migliorare maggiormente è quella delle cartine"] `scale=2`
    # raddoppia i pixel reali dell'immagine mantenendo la stessa area
    # geografica (parametro documentato della Static API): sullo schermo il PDF
    # non cambia, ma STAMPATO e sullo zoom la cartina smette di essere sfocata.
    # Il costo è zero in termini di quota (stessa richiesta), solo byte in più.
    if scale is not None:
        query_parts.append(f"scale={_quote(scale)}")
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
    cost_telemetry.record_api_call("google_static_maps")
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
    scale: int | None = 2,
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

    [CORRETTA UN'ASIMMETRIA IL 2026-08-01 — feedback di Lorenzo: "migliorare
    la parte grafica ... la parte da migliorare maggiormente è quella delle
    cartine"] Le cartine per giorno nascevano già con `scale=2` (vedi
    `build_day_map_url`), questa no: la cartina d'apertura — la PRIMA che il
    cliente vede, e l'unica che guarda il viaggio intero — era l'unica sfocata
    del documento. `scale=2` raddoppia i pixel a parità di area geografica e
    di quota consumata (è la stessa richiesta): cambia solo il peso in byte.
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

    url = build_static_map_url(
        markers_by_style, paths, api_key, size=size, center=center, zoom=zoom, scale=scale
    )
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
        url = build_static_map_url(
            markers_by_style, [], api_key, size=size, center=center, zoom=zoom, scale=scale
        )
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


# ---------------------------------------------------------------------------
# CARTINE PER GIORNO, NUMERATE — [AGGIUNTO 2026-07-31]
#
# Feedback diretto di Lorenzo dopo aver usato di persona un itinerario reale:
#   "è brutta esteticamente e onestamente non ci capisce nulla, sono
#    semplicemente puntini con coordinate che non aiutano minimamente il
#    cliente ad orientarsi durante la giornata"
#   "sarebbe opportuno indicare vicino ad ogni indicatore cosa sono e il numero
#    (1=prima attività del giorno, 2=seconda attività del giorno e così via),
#    le mappe devono essere ad hoc quindi se la città è piccola e le attrazioni
#    sono vicine la cartina dovrà essere molto zoomata"
#
# Tre cause reali del problema, tutte chiuse qui:
#   1) UNA cartina per l'INTERO viaggio -> su un multi-città il bbox include
#      tutte le città e lo zoom collassa a livello regionale: i punti di una
#      singola giornata diventano indistinguibili. Fix: una cartina PER GIORNO,
#      il cui bbox contiene solo le tappe di quel giorno -> lo zoom "ad hoc"
#      che Lorenzo chiede esce da solo dalla matematica di compute_center_zoom
#      (città piccola con tappe vicine = bbox stretto = zoom alto).
#   2) marker etichettati per TIPO (R/M/A/S) -> il cliente vede lettere che non
#      dicono in che ORDINE muoversi. Fix: etichetta = numero della tappa
#      nell'ordine di visita, esattamente come chiesto.
#   3) nessuna legenda -> anche un marker numerato è muto senza la riga che dice
#      "2 · 11:30 · Galleria dell'Accademia". La legenda vive nell'HTML del PDF
#      (testo vero, selezionabile e leggibile), non bruciata nel PNG: qui
#      restituiamo i dati strutturati e pdf_renderer li impagina.
# ---------------------------------------------------------------------------

# Le etichette dei marker della Static API sono UN SOLO carattere alfanumerico
# maiuscolo (0-9, A-Z) — documentato. Quindi: cifre 1..9 per le prime nove
# tappe (il caso reale di quasi ogni giornata), poi lettere. Sono escluse:
# "H" (riservata all'hotel, sarebbe ambigua), "I" e "O" (indistinguibili da 1 e
# 0 a questa dimensione).
_ORDER_LABELS = "123456789ABCDEFGJKLMNPQRSTUVWXYZ"

# Colore del marker per tipo, così la cartina resta leggibile a colpo d'occhio
# ("il verde è dove mangio") MENTRE il numero dice l'ordine. Le due
# informazioni non competono più per lo stesso spazio.
_DAY_MARKER_COLOR_BY_TYPE = {
    "restaurant": "green",
    "museum": "orange",
    "activity": "blue",
    "shopping": "purple",
}
_DAY_FALLBACK_MARKER_COLOR = "blue"
_DAY_PATH_COLOR = "0x1a3b5c"

# Etichette italiane della categoria, per la legenda nel PDF (mai mostrare al
# cliente il valore tecnico "restaurant").
_TYPE_LABEL_IT = {
    "restaurant": "Dove mangiare",
    "museum": "Museo / cultura",
    "activity": "Attività",
    "shopping": "Shopping",
    "hotel": "Alloggio",
}


def _type_label_it(poi_type) -> str:
    return _TYPE_LABEL_IT.get(poi_type, "Tappa")


def build_day_map_plans(hotels: list, pois: list, itinerary: dict) -> list[dict]:
    """
    Funzione PURA (nessuna rete): dall'itinerario già generato + i dati reali
    costruisce, per ciascun giorno, l'elenco ordinato delle tappe geolocalizzate
    con la loro etichetta di ordine.

    Ritorna una lista di `{"day", "title", "hotel_point", "stops": [...]}` dove
    ogni stop è `{"label", "time", "activity", "location", "poi_id", "point",
    "type", "type_label", "color"}`.

    Regole (tutte pensate per non mentire al cliente):
      - si itera sui BLOCCHI nell'ordine in cui compaiono, non su un insieme:
        l'ordine è l'informazione di prodotto qui;
      - un blocco senza `poi_id`, o con un id sconosciuto, o con coordinate non
        numeriche, NON entra in cartina (non abbiamo un punto reale da mettere:
        preferiamo una tappa in meno che un puntino inventato) ma non rompe la
        numerazione delle altre;
      - un poi_id ripetuto nello stesso giorno (es. si torna in piazza la sera)
        occupa UN solo marker, quello della prima visita — due marker
        sovrapposti sono illeggibili; l'orario successivo resta comunque nel
        programma testuale del PDF;
      - i blocchi in hotel non diventano tappe numerate: l'hotel ha il suo
        marker rosso "H", ed è il punto di partenza/ritorno del percorso.
    """
    hotel_by_id = {getattr(h, "id", None): h for h in (hotels or [])}
    poi_by_id = {getattr(p, "id", None): p for p in (pois or [])}
    days = (itinerary or {}).get("days") or []
    if not isinstance(days, list):
        return []

    plans = []
    for day in days:
        if not isinstance(day, dict):
            continue
        blocks = day.get("blocks") or []
        if not isinstance(blocks, list):
            blocks = []
        stops = []
        seen_ids: set[str] = set()
        hotel_point = None
        for block in blocks:
            if not isinstance(block, dict):
                continue
            poi_id = block.get("poi_id")
            if not isinstance(poi_id, str) or not poi_id:
                continue
            if poi_id in hotel_by_id:
                point = _point_of(hotel_by_id[poi_id])
                if point is not None and hotel_point is None:
                    hotel_point = point
                continue
            if poi_id in seen_ids:
                continue
            poi = poi_by_id.get(poi_id)
            if poi is None:
                continue
            point = _point_of(poi)
            if point is None:
                continue
            seen_ids.add(poi_id)
            index = len(stops)
            poi_type = getattr(poi, "type", None)
            stops.append({
                "label": _ORDER_LABELS[index] if index < len(_ORDER_LABELS) else "",
                "time": block.get("time") or "",
                # [AGGIUNTO 2026-08-02] Il NOME del posto, come lo chiama
                # Google e come lo trova il cliente sull'insegna. Non esisteva,
                # e chi doveva stampare un nome (la legenda della cartina, le
                # tratte di "come arrivare") era costretto a scegliere fra
                # `activity` — una frase, "Pranzo alla Taverna di San Giuseppe"
                # — e `location`, che nei blocchi veri è un indirizzo o
                # addirittura il nome nudo della città. Ne uscivano legende con
                # «3 Via Giovanni Duprè 132» e tratte con «2 → 3 Piazza del
                # Duomo 1 → Siena». Un puntino su una cartina e la freccia di
                # uno spostamento chiedono un nome proprio: ora ce l'hanno.
                "name": getattr(poi, "name", "") or block.get("activity") or "",
                "activity": block.get("activity") or getattr(poi, "name", "") or "",
                "location": block.get("location") or getattr(poi, "name", "") or "",
                "poi_id": poi_id,
                "point": point,
                "type": poi_type,
                "type_label": _type_label_it(poi_type),
                "color": _DAY_MARKER_COLOR_BY_TYPE.get(poi_type, _DAY_FALLBACK_MARKER_COLOR),
            })
        if hotel_point is None:
            # Nessun blocco in hotel quel giorno (il caso normale a metà
            # viaggio): usa comunque l'hotel-ancora più pertinente, così la
            # cartina mostra "da dove parto e dove torno a dormire".
            hotel_point = _pick_day_anchor(
                [s["poi_id"] for s in stops],
                [pt for pt in (_point_of(h) for h in (hotels or [])) if pt is not None],
                set(hotel_by_id),
                {pid: pt for pid, pt in (
                    (getattr(o, "id", None), _point_of(o)) for o in list(hotels or []) + list(pois or [])
                ) if pid is not None and pt is not None},
            )
        # Nome/id dell'hotel effettivamente usato come ancora, per la sezione
        # "Come arrivare" (src/directions.py): al cliente va detto "dall'Hotel
        # Duomo", mai "da H1" (vedi check_no_raw_id_leakage — stesso principio).
        hotel_id, hotel_name = None, None
        for h in (hotels or []):
            if _point_of(h) == hotel_point and hotel_point is not None:
                hotel_id, hotel_name = getattr(h, "id", None), getattr(h, "name", None)
                break
        plans.append({
            "day": day.get("day"),
            "title": day.get("title") or "",
            "hotel_point": hotel_point,
            "hotel_id": hotel_id,
            "hotel_name": hotel_name,
            "stops": stops,
        })
    return plans


def _point_of(obj) -> tuple[float, float] | None:
    """Coordinate reali di un hotel/POI, o None se assenti/non numeriche —
    difesa contro una forma inattesa che altrimenti farebbe saltare l'intera
    cartina invece della singola tappa."""
    lat = getattr(obj, "lat", None)
    lng = getattr(obj, "lng", None)
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def build_day_map_url(
    plan: dict, api_key: str, size: str = "640x420", scale: int | None = 2
) -> str | None:
    """Funzione pura: URL della cartina di UN giorno, marker numerati
    nell'ordine di visita + percorso hotel -> tappe -> hotel.

    Lo zoom NON è fisso: `compute_center_zoom` lo calcola sul bbox delle sole
    tappe di QUESTA giornata — che è precisamente la richiesta "le mappe devono
    essere ad hoc": tre attrazioni a 300 m l'una dall'altra in un borgo
    producono uno zoom da quartiere, le stesse tre sparse per Londra uno zoom
    da città. Nessuna soglia arbitraria da tarare a mano.
    """
    stops = plan.get("stops") or []
    hotel_point = plan.get("hotel_point")
    markers_by_style = []
    if hotel_point is not None:
        markers_by_style.append({**_HOTEL_MARKER_STYLE, "points": [hotel_point]})
    # Un gruppo `markers=` per tappa: colore E etichetta cambiano a ogni punto,
    # quindi non sono raggruppabili come nella cartina d'insieme.
    for stop in stops:
        markers_by_style.append({
            "color": stop.get("color") or _DAY_FALLBACK_MARKER_COLOR,
            "label": stop.get("label") or "",
            "points": [stop["point"]],
        })

    path_points = []
    if hotel_point is not None:
        path_points.append(hotel_point)
    path_points += [s["point"] for s in stops]
    if hotel_point is not None and len(path_points) > 1:
        path_points.append(hotel_point)
    paths = [{"color": _DAY_PATH_COLOR, "points": path_points}] if len(path_points) >= 2 else []

    marker_points = [p for style in markers_by_style for p in style["points"]]
    width_px, height_px = _parse_size(size)
    center_zoom = compute_center_zoom(marker_points, width_px, height_px)
    center = (center_zoom[0], center_zoom[1]) if center_zoom else None
    zoom = center_zoom[2] if center_zoom else None

    url = build_static_map_url(
        markers_by_style, paths, api_key, size=size, center=center, zoom=zoom, scale=scale
    )
    if url is not None and len(url) > _MAX_URL_LENGTH and paths:
        url = build_static_map_url(
            markers_by_style, [], api_key, size=size, center=center, zoom=zoom, scale=scale
        )
    if url is not None and len(url) > _MAX_URL_LENGTH:
        return None
    return url


# [NUOVO 2026-08-02 — richiesta di Lorenzo, con foto alla mano: "ora quella
# parte e' fatta bene ma manca la cartina, ci sono solamente i vettori ma la
# cartina in se' manca"] Aveva ragione, e la causa non era un errore: Google
# Static Maps e lo schema disegnato in casa erano due sorgenti ALTERNATIVE.
# O l'una o l'altro. Senza chiave (la sandbox, ma anche qualunque cliente
# servito mentre la quota e' esaurita) restava lo schema: pallini e vettori
# su una griglia, senza una strada sotto.
#
# La correzione e' smettere di scegliere e METTERE INSIEME le due cose:
# a Google si chiede soltanto lo SFONDO — strade, piazze, toponimi, niente
# marker — e i pallini numerati, il percorso, la barra della scala e il nord
# li disegniamo noi sopra, con la stessa proiezione di Mercator che ha usato
# Google per lo sfondo, quindi allineati al pixel.
#
# Tre motivi per cui e' meglio anche a prescindere dalla richiesta:
#   1. i colori dei pallini restano gli STESSI della legenda accanto e del CSS
#      del PDF (quelli di Google li sceglie Google, e non coincidevano mai);
#   2. l'URL non puo' piu' essere troppo lunga — e' un URL fisso di ~250
#      caratteri contro il tetto di 8000, quindi il terzo modo di non avere la
#      cartina (vedi il preambolo di map_render.py) sparisce del tutto;
#   3. e' la STESSA chiamata di prima, una per giornata: costo invariato.
_BASE_MAP_SIZE = "640x438"   # rapporto 1,461 = quello della tela dello schema
_BASE_MAP_TYPE = "roadmap"
# Lo sfondo deve fare lo sfondo. I pallini di Google per bar e negozi sono
# rumore che compete con i NOSTRI pallini numerati (il cliente ne conterebbe
# venti invece di cinque), e una tinta piena sotto un pallino navy lo nasconde:
# si spengono le icone commerciali e si smorza il colore, lasciando intatto
# tutto cio' che serve a orientarsi — strade, nomi delle vie, parchi, acqua.
_BASE_MAP_STYLES = (
    "feature:poi.business|visibility:off",
    "feature:poi|element:labels.icon|visibility:off",
    "feature:transit|element:labels.icon|visibility:off",
    "saturation:-35",
    "lightness:12",
)


def build_day_base_map_url(
    plan: dict,
    api_key: str,
    size: str = _BASE_MAP_SIZE,
    scale: int | None = 2,
) -> dict | None:
    """
    URL dello SFONDO cartografico di una giornata: solo `center`, `zoom`,
    `size`, `scale`, `maptype` e stile. Nessun `markers=`, nessun `path=` —
    quelli li disegna `map_render` sopra l'immagine.

    Ritorna un dizionario con l'URL E i parametri di georeferenziazione
    (`center`, `zoom`, `size`, `scale`), perche' senza quelli l'immagine e'
    solo una figura: sono loro a permettere di calcolare in che pixel cade una
    certa coordinata. Ritorna `None` se non c'e' nessun punto da inquadrare.

    Il centro e lo zoom si calcolano sugli stessi punti reali di prima
    (`compute_center_zoom`), quindi l'inquadratura "ad hoc" per giornata —
    borgo stretto, metropoli larga — resta identica: cambia cosa si chiede a
    Google dentro quella inquadratura, non l'inquadratura.
    """
    if not api_key:
        return None
    points: list[tuple[float, float]] = []
    hotel_point = plan.get("hotel_point")
    if hotel_point is not None:
        points.append(hotel_point)
    for stop in plan.get("stops") or []:
        point = stop.get("point")
        if point is not None:
            points.append(point)
    if not points:
        return None

    width_px, height_px = _parse_size(size)
    # [MISURATO 2026-08-02, non dedotto] Con il tetto storico di zoom 17 una
    # giornata raccolta in un centro storico — duecento metri fra la prima e
    # l'ultima tappa, cioe' il caso NORMALE di questi itinerari — finiva in un
    # grappolo di pallini al centro di una cartina larga un quartiere: tutto
    # corretto e tutto illeggibile. Sullo schema il problema non esisteva
    # perche' `_project_points()` riscala la nuvola per riempire il riquadro;
    # su una cartina vera lo zoom E' la scala e non si puo' barare. Il tetto
    # sale a 19 (Google arriva a 21 per la roadmap): quel grappolo diventa un
    # isolato leggibile, con i nomi delle vie sotto.
    center_zoom = compute_center_zoom(points, width_px, height_px, max_zoom=19)
    if center_zoom is None:
        return None
    center_lat, center_lng, zoom = center_zoom

    query_parts = [
        f"size={_quote(size)}",
        f"center={_quote(f'{center_lat},{center_lng}')}",
        f"zoom={_quote(zoom)}",
        f"maptype={_quote(_BASE_MAP_TYPE)}",
    ]
    if scale is not None:
        query_parts.append(f"scale={_quote(scale)}")
    for style in _BASE_MAP_STYLES:
        query_parts.append(f"style={_quote(style)}")
    query_parts.append(f"key={_quote(api_key)}")
    url = STATIC_MAP_BASE_URL + "?" + "&".join(query_parts)
    if len(url) > _MAX_URL_LENGTH:  # difesa in profondita': non puo' accadere
        return None
    return {
        "url": url,
        "center": (center_lat, center_lng),
        "zoom": zoom,
        "size": (width_px, height_px),
        "scale": int(scale or 1),
    }


def build_day_maps_for_itinerary(
    hotels: list,
    pois: list,
    itinerary: dict,
    api_key: str | None,
    size: str = "640x420",
    scale: int | None = 2,
) -> list[dict]:
    """
    Orchestrazione: una cartina numerata PER GIORNO + la sua legenda.

    Ritorna una lista di `{"day", "title", "png": bytes|None, "stops": [...],
    "hotel_point", "hotel_name", "hotel_id"}`. `png=None` per una giornata senza
    tappe geolocalizzabili o il cui download fallisce: il PDF impagina comunque
    la legenda testuale, e una cartina mancante non fa MAI fallire il documento
    (stesso principio già applicato a guida/feedback/cartina d'insieme). Non
    solleva mai verso il chiamante.

    [2026-08-02] Senza `api_key` NON si ritorna più la lista vuota. I piani —
    tappe numerate, colori, coordinate — sono già calcolati e non costano né una
    chiamata né un centesimo; buttarli via cancellava anche la legenda testuale
    e lasciava il documento senza NIENTE al posto della cartina. È esattamente
    il difetto che il cliente ha visto nel PDF di esempio. Ora si ritornano con
    `png=None` e a valle `map_render.attach_local_maps()` disegna lo schema.
    """
    plans = build_day_map_plans(hotels, pois, itinerary)
    results = []
    for plan in plans:
        png = None
        base_map = None
        if api_key and plan.get("stops"):
            try:
                # [CAMBIATO 2026-08-02] Si chiede a Google lo SFONDO, non la
                # cartina finita: i marker e il percorso li disegna
                # `map_render` sopra, allineati alla stessa proiezione. Vedi la
                # nota lunga sopra `build_day_base_map_url`.
                base = build_day_base_map_url(plan, api_key, scale=scale)
                if base is not None:
                    png = fetch_static_map_png(base["url"])
                    base_map = {k: v for k, v in base.items() if k != "url"}
            except (MapsStaticError, requests.exceptions.RequestException) as e:
                print(f"⚠️  Cartina del giorno {plan.get('day')} saltata: {e}")
                png, base_map = None, None
            except Exception as e:  # difesa in profondità: mai far cadere il PDF
                print(f"⚠️  Cartina del giorno {plan.get('day')} saltata (errore inatteso): {e}")
                png, base_map = None, None
        results.append({
            "day": plan.get("day"),
            "title": plan.get("title"),
            "png": png,
            # Presente SOLO quando `png` e' uno sfondo nudo da completare.
            # Un `png` senza `base_map` e' una cartina gia' finita (il
            # comportamento storico) e a valle non viene toccata.
            "base_map": base_map,
            "stops": plan.get("stops") or [],
            # Servono al disegno locale (l'albergo è il punto di partenza e di
            # ritorno del percorso). Prima venivano scartati qui e il disegno
            # avrebbe avuto le tappe ma non il perno della giornata.
            "hotel_point": plan.get("hotel_point"),
            "hotel_name": plan.get("hotel_name"),
            "hotel_id": plan.get("hotel_id"),
        })
    return results


def build_overview_plan(day_plans: list[dict] | None) -> dict | None:
    """
    Un solo "piano" con TUTTE le tappe del viaggio, nella stessa forma di quelli
    per giornata: `{"day", "title", "stops", "hotel_point", "hotel_name",
    "hotel_id"}`. Funzione pura, nessuna rete.

    [AGGIUNTO 2026-08-03 — segnalazione del cliente: «risolvi il problema delle
    cartine che non si vedono»]
    La cartina d'insieme — la PRIMA che il cliente vede, quella del capitolo "a
    colpo d'occhio" — era l'unica del documento senza rete di sicurezza: la
    disegnava Google e basta, e senza chiave, senza quota o senza rete
    spariva. Non ripiegava su niente: il capitolo usciva senza figura, e chi lo
    guardava concludeva che il prodotto la cartina non ce l'ha. Le cartine per
    giornata questa rete ce l'avevano gia' da un giorno. Qui si costruisce il
    piano che permette di disegnarla in casa con lo stesso codice, e — cosa che
    prima era impossibile — di sapere DOVE e' finito ogni pallino, che e' quello
    che serve per renderla cliccabile.

    Due scelte, entrambe volute:
      - l'etichetta del pallino e' il NUMERO DEL GIORNO, non l'ordine della
        tappa. A questa scala "3" deve voler dire "ci vai il terzo giorno":
        e' l'unica domanda che si fa a una cartina d'insieme. Il colore resta
        quello del tipo di posto, cosi' la legenda del documento continua a
        valere identica per tutte le cartine;
      - un posto visitato in due giorni diversi occupa UN solo pallino, quello
        della prima volta. Due pallini nello stesso punto con due numeri
        diversi non sono piu' informazione, sono un errore di stampa — e il
        programma testuale racconta comunque entrambe le visite.
    """
    stops: list[dict] = []
    visti: set = set()
    hotel_point = None
    hotel_name = None
    hotel_id = None
    for plan in day_plans or []:
        if not isinstance(plan, dict):
            continue
        if hotel_point is None and plan.get("hotel_point") is not None:
            hotel_point = plan.get("hotel_point")
            hotel_name = plan.get("hotel_name")
            hotel_id = plan.get("hotel_id")
        giorno = plan.get("day")
        for stop in plan.get("stops") or []:
            if not isinstance(stop, dict):
                continue
            poi_id = stop.get("poi_id")
            chiave = poi_id if poi_id else (stop.get("name"), stop.get("point"))
            if chiave in visti:
                continue
            visti.add(chiave)
            tappa = dict(stop)
            tappa["label"] = str(giorno) if giorno is not None else ""
            tappa["day"] = giorno
            stops.append(tappa)
    if not stops:
        return None
    return {
        "day": None,
        "title": "Il viaggio a colpo d'occhio",
        "stops": stops,
        "hotel_point": hotel_point,
        "hotel_name": hotel_name,
        "hotel_id": hotel_id,
    }


def build_overview_map(
    hotels: list,
    pois: list,
    itinerary: dict,
    api_key: str | None,
    size: str = _BASE_MAP_SIZE,
    scale: int | None = 2,
    day_plans: list[dict] | None = None,
) -> dict | None:
    """
    La cartina d'insieme, costruita come quelle per giornata: si chiede a Google
    lo SFONDO stradale nudo e i pallini li disegna `map_render` sopra.

    Ritorna un piano con `png` (lo sfondo, o `None`) e `base_map` (centro, zoom,
    scala: i tre numeri che permettono di sapere in che pixel cade una
    coordinata), oppure `None` se non c'e' niente da inquadrare. Non solleva
    mai: un problema di rete costa la figura, non il documento.

    `day_plans` si puo' passare gia' calcolato — il chiamante di solito ce l'ha
    gia' in mano per le cartine per giornata e per "come arrivare", e ricalcolarlo
    qui sarebbe lavoro doppio su dati identici.
    """
    if day_plans is None:
        day_plans = build_day_map_plans(hotels, pois, itinerary)
    plan = build_overview_plan(day_plans)
    if plan is None:
        return None
    png = None
    base_map = None
    if api_key:
        try:
            base = build_day_base_map_url(plan, api_key, size=size, scale=scale)
            if base is not None:
                png = fetch_static_map_png(base["url"])
                base_map = {k: v for k, v in base.items() if k != "url"}
        except (MapsStaticError, requests.exceptions.RequestException) as e:
            print(f"\u26a0\ufe0f  Cartina d'insieme saltata: {e}")
            png, base_map = None, None
        except Exception as e:  # difesa in profondita': mai far cadere il PDF
            print(f"\u26a0\ufe0f  Cartina d'insieme saltata (errore inatteso): {e}")
            png, base_map = None, None
    plan["png"] = png
    plan["base_map"] = base_map
    return plan


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
    # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    # confronto di distanza in gradi al quadrato SENZA la correzione cos(lat)
    # sul delta di longitudine: alle latitudini europee (~44°) un grado di
    # longitudine vale ~0,72 di un grado di latitudine, quindi con più hotel si
    # poteva scegliere come ancora del percorso del giorno l'hotel più LONTANO
    # sul terreno. Stesso identico bug già chiuso in liteapi_client._distance_sq
    # ([CORRETTO 2026-07-12]); qui era rimasto. Applico la stessa correzione.
    lng_correction = math.cos(math.radians(mean_lat))
    return min(
        hotel_points,
        key=lambda hp: (hp[0] - mean_lat) ** 2 + ((hp[1] - mean_lng) * lng_correction) ** 2,
    )
