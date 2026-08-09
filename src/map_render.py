"""
NUOVO 2026-08-02 (bis) — la cartina disegnata IN CASA.

RICHIESTA DI LORENZO
--------------------
"le cartine: le hai completamente rimosse, attieniti a ciò che ti avevo detto
in precedenza per queste".

Nessuno le aveva rimosse dal codice: `maps_static.py` c'è ancora ed è intatto.
Erano sparite dal DOCUMENTO, che è l'unico posto dove esistono per il cliente.
Il motivo è che l'unica sorgente di cartina era la Static Maps API di Google, e
quella sorgente ha tre modi diversi di non esserci — nessuno dei quali è un bug:

  1. **chiave assente** (il campione in sandbox: nessuna `GOOGLE_MAPS_KEY`,
     quindi `build_day_maps_for_itinerary()` non chiama e ritorna i piani senza
     `png`);
  2. **rete o quota** (in produzione: 429, 403 "quota exceeded", timeout);
  3. **URL troppo lunga** (limite documentato ~8192 caratteri: una giornata con
     molte tappe la supera e la cartina viene scartata a monte).

In tutti e tre i casi il ripiego era "stampa solo la legenda". Che è una scelta
onesta — meglio l'informazione senza la figura che una figura finta — ma
produce esattamente il documento che Lorenzo ha in mano: un elenco numerato di
nomi, con scritto sopra "cartina", e nessuna cartina.

LA DECISIONE
------------
Una funzione di prodotto che dipende da una chiamata di rete esterna NON è una
funzione di prodotto: è una speranza. Qui la cartina diventa una proprietà
GARANTITA del documento, perché la disegniamo noi, in Python, dalle coordinate
reali che abbiamo già in mano e che non costano niente perché sono già state
pagate quando abbiamo cercato i POI.

Restano DUE sorgenti, in quest'ordine:

  - **Google Static Maps** quando c'è (strade vere, edifici, toponimi: per
    orientarsi camminando è insostituibile e costa ~0,002 € a cartina);
  - **questo modulo** sempre, come rete di sicurezza — e in sandbox, dove non
    c'è chiave, come sorgente unica.

ONESTÀ SU COSA MOSTRA (dichiarata anche nel documento cliente)
---------------------------------------------------------------
Questa non è una mappa stradale e non finge di esserlo: non ci sono strade,
non ci sono edifici, non ci sono nomi di vie. È uno SCHEMA IN SCALA, e in
scala lo è davvero: le posizioni relative dei punti e le distanze fra loro
sono calcolate dalle coordinate reali con la stessa proiezione di Mercator che
usa Google, e la barra della scala in fondo è misurata, non decorativa. Quello
che il cliente può leggerci — "il museo è a nord-ovest dell'hotel, a circa
600 metri, e il ristorante è sulla strada" — è vero. Quello che NON può
leggerci — "da che parte giro all'incrocio" — non è disegnato apposta, e sotto
la figura c'è scritto in chiaro.

Perché questo basta, e anzi in un caso è meglio di Google: la domanda a cui
serve rispondere prima di uscire dall'albergo non è "che strada faccio"
(a quella rispondono i link a Google Maps di ogni tappa, con la navigazione
vera in mano), è "come sono messe le mie giornate": cosa è vicino a cosa, se
sto attraversando la città due volte, se la sera torno indietro. Uno schema
pulito lo dice meglio di una mappa stradale piena di dettagli irrilevanti.

PERCHÉ PILLOW E NON UN SVG INLINE
----------------------------------
Il motore di wkhtmltopdf è Qt WebKit del 2014 (vedi la nota in cima al CSS di
pdf_renderer.py): il supporto SVG c'è ma è irregolare, e un SVG che non si
disegna è una pagina bianca in mano al cliente. Un PNG in `data:` URI segue
esattamente la stessa strada che già percorre la cartina di Google — stesso
campo `png`, stesso `<img>`, stesso ripiego — quindi non introduce un secondo
percorso di rendering da mantenere. Pillow è una dipendenza nuova ma
ordinaria, con ruota precompilata per l'immagine Docker in uso.

Se Pillow manca o il disegno fallisce per qualunque motivo, `render_day_map_png()`
ritorna `None` e il documento torna al comportamento di prima (solo legenda):
una cartina è un miglioramento, non un punto di rottura in più.
"""
from __future__ import annotations

import io
import math

# --- Palette ---------------------------------------------------------------
# Gli stessi colori del CSS del PDF e degli stessi nomi che `maps_static.py`
# assegna per tipo di POI: se il pallino "2" è arancione sulla cartina, il
# pallino "2" della legenda accanto DEVE essere arancione. La corrispondenza
# non è estetica, è l'unico modo in cui la legenda serve a qualcosa.
_MARKER_RGB = {
    "red": (178, 58, 58),
    "orange": (201, 118, 47),
    "green": (63, 143, 95),
    "blue": (47, 102, 144),
    "purple": (107, 74, 143),
    "yellow": (168, 135, 31),
}
_FALLBACK_MARKER_RGB = (47, 102, 144)
_HOTEL_RGB = (178, 58, 58)

_BG_RGB = (243, 247, 250)          # carta chiara, non bianca: la figura si stacca
_FRAME_RGB = (219, 227, 236)
_GRID_RGB = (228, 235, 242)
_PATH_RGB = (26, 59, 92)
_LABEL_RGB = (26, 59, 92)
_MUTED_RGB = (138, 151, 163)
_WHITE = (255, 255, 255)

# Disegniamo a 3x la dimensione di stampa e lasciamo che sia il PDF a ridurre:
# è l'anti-aliasing del povero, ma su cerchi e linee sottili funziona meglio di
# qualunque disegno diretto alla dimensione finale con questo toolkit.
_SCALE = 3
_W, _H = 380, 260                  # dimensione logica, in punti di stampa
_PAD = 30                          # margine interno perché i marker di bordo non vengano tagliati
_PIN_RADIUS = 9 * _SCALE           # raggio del pallino numerato
# Scostamento massimo consentito a un pallino per non coprirne un altro: un
# diametro e mezzo, cioè circa quattro millimetri sulla pagina stampata. È il
# prezzo che accettiamo di pagare alla precisione per far vedere tutte le
# tappe; oltre questo, la figura smetterebbe di poter dire "in scala".
_MAX_SHIFT = 3 * _PIN_RADIUS

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)
_FONT_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)

_EARTH_RADIUS_M = 6371008.8


def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont
    for path in (_FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    # Ultimo ripiego: il font bitmap incorporato in Pillow. Brutto e minuscolo,
    # ma una cartina con etichette brutte resta una cartina; senza font non si
    # disegnerebbe nulla.
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _mercator(lat: float, lng: float) -> tuple[float, float]:
    """Mercator sferica normalizzata in [0,1] — la stessa proiezione di Google,
    così uno schema disegnato qui e una cartina scaricata da loro mostrano le
    stesse proporzioni e il cliente non vede due geografie diverse nello stesso
    documento. La latitudine è tosata a ±85° (il limite oltre il quale la
    proiezione diverge): nessuna destinazione turistica ci arriva, ma un dato
    sporco non deve produrre un `math.log(0)`."""
    lat = max(min(float(lat), 85.0), -85.0)
    x = (float(lng) + 180.0) / 360.0
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def _nice_scale_metres(raw: float) -> float:
    """Il numero tondo immediatamente sotto `raw`, nella progressione
    1-2-5 × 10ⁿ. Una barra della scala che dice "437 m" è una barra che nessuno
    legge: deve dire 200, o 500, o 1 km."""
    if raw <= 0:
        return 0.0
    exponent = math.floor(math.log10(raw))
    base = 10 ** exponent
    for step in (5, 2, 1):
        if step * base <= raw:
            return float(step * base)
    return float(base)


def _format_metres(metres: float) -> str:
    if metres >= 1000:
        value = metres / 1000
        return f"{value:.0f} km" if value == int(value) else f"{value:.1f} km"
    return f"{metres:.0f} m"


def _project_points(points: list[tuple[float, float]], width: int, height: int) -> list[tuple[float, float]]:
    """Porta le coordinate reali dentro il riquadro, conservando le proporzioni.

    Il fattore di scala è UNO SOLO per i due assi (`min` dei due possibili), non
    uno per asse: allungare indipendentemente x e y riempirebbe meglio il
    riquadro ma stirerebbe la geografia, e su uno schema che dichiara di essere
    "in scala" sarebbe una bugia — la barra della scala smetterebbe di valere
    nella direzione stirata.

    Il caso di un solo punto (o di punti coincidenti) non ha un'estensione da
    scalare: si centra e basta, senza dividere per zero.
    """
    projected = [_mercator(lat, lng) for lat, lng in points]
    xs = [p[0] for p in projected]
    ys = [p[1] for p in projected]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max_x - min_x
    span_y = max_y - min_y
    inner_w = width - 2 * _PAD * _SCALE
    inner_h = height - 2 * _PAD * _SCALE
    if span_x <= 0 and span_y <= 0:
        return [(width / 2, height / 2) for _ in projected]
    scale = min(
        inner_w / span_x if span_x > 0 else float("inf"),
        inner_h / span_y if span_y > 0 else float("inf"),
    )
    off_x = (width - span_x * scale) / 2
    off_y = (height - span_y * scale) / 2
    return [
        ((x - min_x) * scale + off_x, (y - min_y) * scale + off_y)
        for x, y in projected
    ]


# Pixel del mondo intero al livello di zoom 0 nella tassellatura di Google:
# una tessera di 256 px copre l'intero pianeta. Tutta la georeferenziazione
# discende da questa costante e da `_mercator()`, che e' la stessa proiezione.
_WORLD_TILE_PX = 256.0
# Metri per pixel all'equatore a zoom 0 (= circonferenza terrestre / 256).
_EQUATOR_M_PER_PX = 156543.03392


def _google_pixels(
    points: list[tuple[float, float]], base_map: dict, width: int, height: int
) -> list[tuple[float, float]]:
    """
    In che pixel dell'immagine scaricata cade una certa coordinata.

    Questa e' la funzione che rende possibile disegnare i NOSTRI pallini sopra
    lo sfondo di GOOGLE senza che siano appoggiati a caso: si ricostruisce la
    stessa trasformazione che ha usato Google per generare quell'immagine —
    centro, zoom e fattore di scala arrivano da `maps_static.build_day_base_map_url`
    che li ha chiesti — e la si applica alle stesse coordinate reali dei POI.
    Il pallino "2" finisce sull'edificio del museo, non vicino.

    Da NON confondere con `_project_points()`, che invece riscala liberamente la
    nuvola di punti per riempire il riquadro: quello va bene su una tela vuota,
    qui allineerebbe i pallini a una geografia diversa da quella disegnata sotto.
    """
    zoom = float(base_map["zoom"])
    scala = float(base_map.get("scale") or 1)
    world = _WORLD_TILE_PX * (2.0 ** zoom) * scala
    cx, cy = _mercator(*base_map["center"])
    out = []
    for lat, lng in points:
        x, y = _mercator(lat, lng)
        out.append(((x - cx) * world + width / 2.0, (y - cy) * world + height / 2.0))
    return out


def _metres_per_pixel_at_zoom(base_map: dict) -> float | None:
    """La scala di una cartina di Google non si stima: discende da zoom,
    latitudine del centro e fattore di scala. Meglio del calcolo per differenza
    fra due punti, che con due sole tappe vicine ha un errore relativo alto."""
    try:
        lat = float(base_map["center"][0])
        zoom = float(base_map["zoom"])
        scala = float(base_map.get("scale") or 1)
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    valore = _EQUATOR_M_PER_PX * math.cos(math.radians(lat)) / (2.0 ** zoom) / scala
    return valore if valore > 0 else None


def _text_size(draw, text: str, font) -> tuple[int, int]:
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        return right - left, bottom - top
    except Exception:
        return (len(text) * 6, 10)


def _truncate(text: str, limit: int) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _coerce_point(value) -> tuple[float, float] | None:
    """Accetta sia `(lat, lng)` — la forma che usa `maps_static` — sia
    `{"lat": …, "lng": …}`, che è la forma con cui gli stessi dati arrivano da
    Google e da Make. Ritorna `None` su qualunque altra cosa: una singola tappa
    con coordinate malformate non deve far sparire la cartina dell'intero
    giorno."""
    if isinstance(value, dict):
        lat, lng = value.get("lat"), value.get("lng")
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        lat, lng = value[0], value[1]
    else:
        return None
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None
    return lat, lng


def render_day_map_png(plan: dict, day_label: str = "") -> bytes | None:
    """
    Disegna lo schema della giornata e ritorna i byte PNG, oppure `None` se non
    c'è abbastanza geografia per disegnare qualcosa di onesto (nessuna tappa
    con coordinate) o se Pillow non è disponibile.

    `plan` è un elemento di `maps_static.build_day_map_plans()`: si riusa quella
    struttura invece di inventarne una seconda, così cartina, legenda e sezione
    "come arrivare" leggono TUTTE lo stesso elenco ordinato di tappe — se un
    giorno la numerazione cambia, cambia in un posto solo.

    Non solleva mai: qualunque errore ritorna `None` e il documento ripiega
    sulla sola legenda, esattamente come faceva prima che questo modulo
    esistesse.
    """
    return render_day_map(plan, day_label)[0]


def render_day_map(plan: dict, day_label: str = "") -> tuple[bytes | None, dict]:
    """
    Come `render_day_map_png()`, ma ritorna anche le note su COME è stata
    disegnata la figura:

      - `declustered`, vero quando due tappe erano così vicine che i pallini si
        coprivano e sono stati allontanati di qualche pixel per renderli
        leggibili. Serve al renderer del PDF per dirlo nella didascalia: uno
        scostamento taciuto è un errore di misura, uno scostamento dichiarato è
        una scelta di leggibilità;
      - `pins`, la posizione in cui OGNI pallino è stato davvero disegnato (vedi
        `_geometria_dei_pin()`): è quello che permette al renderer di appoggiare
        un link cliccabile sopra il pallino, cosa che dentro un PNG non si può
        fare. Assente se l'export della geometria non riesce — la figura esce
        comunque, semplicemente senza lo strato dei link.
    """
    try:
        return _render_day_map_png(plan, day_label)
    except Exception:
        return None, {}


def _stops_and_hotel(plan: dict):
    """Le tappe con coordinate valide e il punto dell'albergo. Estratto in una
    funzione perche' ora lo leggono DUE disegnatori — lo schema e il disegno
    sopra la cartina di Google — e devono numerare le stesse tappe nello stesso
    ordine: una divergenza qui e la legenda accanto mentirebbe."""
    stops = [
        s for s in (plan or {}).get("stops") or []
        if isinstance(s, dict) and _coerce_point(s.get("point")) is not None
    ]
    return stops, _coerce_point((plan or {}).get("hotel_point"))


def _geo_points(stops: list, hotel_point) -> list:
    points = []
    if hotel_point:
        points.append(hotel_point)
    for stop in stops:
        points.append(_coerce_point(stop.get("point")))
    return points


def render_day_map_over_base(
    plan: dict, day_label: str, base_png: bytes, base_map: dict
) -> tuple[bytes | None, dict]:
    """Disegna le tappe della giornata SOPRA lo sfondo cartografico di Google.
    Come `render_day_map()`, non solleva mai: qualunque problema (immagine
    illeggibile, parametri di georeferenziazione mancanti, Pillow assente)
    ritorna `None` e il chiamante ridisegna lo schema, che non dipende da
    niente di esterno."""
    if not base_png or not isinstance(base_map, dict):
        return None, {}
    try:
        return _render_over_base_png(plan, day_label, base_png, base_map)
    except Exception:
        return None, {}


def _render_day_map_png(plan: dict, day_label: str) -> tuple[bytes | None, dict]:
    from PIL import Image

    stops, hotel_point = _stops_and_hotel(plan)
    if not stops:
        # Una cartina con il solo albergo sopra non dice niente che la scheda
        # dell'alloggio non dica gia' meglio: meglio nessuna figura.
        return None, {}

    width, height = _W * _SCALE, _H * _SCALE
    image = Image.new("RGB", (width, height), _BG_RGB)
    geo_points = _geo_points(stops, hotel_point)
    true_pixels = _project_points(geo_points, width, height)
    return _disegna_sopra(
        image, stops, hotel_point, geo_points, true_pixels, day_label,
        sopra_cartina=False, metres_per_px=None,
        hotel_name=(plan or {}).get("hotel_name"),
    )


def _render_over_base_png(
    plan: dict, day_label: str, base_png: bytes, base_map: dict
) -> tuple[bytes | None, dict]:
    """
    Gli stessi pallini, lo stesso percorso, la stessa barra della scala — ma
    disegnati SOPRA lo sfondo cartografico scaricato da Google invece che su una
    griglia vuota. E' la richiesta di Lorenzo: "manca la cartina, ci sono
    solamente i vettori".

    L'allineamento non e' approssimato: `base_map` porta con se' il centro, lo
    zoom e la scala con cui quell'immagine e' stata generata, e da quei tre
    numeri si ricava esattamente in che pixel cade una coordinata, con la stessa
    formula di Mercator che Google ha usato per disegnare le strade. Se
    l'immagine non si apre o i parametri mancano, si solleva e il chiamante
    ripiega sullo schema: mai un pallino appoggiato a caso su una strada
    sbagliata, che sarebbe peggio di nessuna cartina.
    """
    from PIL import Image

    stops, hotel_point = _stops_and_hotel(plan)
    if not stops:
        return None, {}
    image = Image.open(io.BytesIO(base_png)).convert("RGB")
    width, height = image.size
    geo_points = _geo_points(stops, hotel_point)
    true_pixels = _google_pixels(geo_points, base_map, width, height)
    return _disegna_sopra(
        image, stops, hotel_point, geo_points, true_pixels, day_label,
        sopra_cartina=True, metres_per_px=_metres_per_pixel_at_zoom(base_map),
        hotel_name=(plan or {}).get("hotel_name"),
    )


def _disegna_sopra(
    image,
    stops: list,
    hotel_point,
    geo_points: list,
    true_pixels: list,
    day_label: str,
    sopra_cartina: bool,
    metres_per_px: float | None,
    hotel_name=None,
) -> tuple[bytes | None, dict]:
    """Il disegno vero e proprio: percorso, etichette, pallini numerati, barra
    della scala, nord, cornice. Unico per le due sorgenti — se domani cambia il
    modo di disegnare un pallino, cambia in tutte e due le cartine insieme,
    che e' l'unico modo perche' la legenda continui a valere per entrambe."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    width, height = image.size

    # [CORRETTO 2026-08-02 — difetto VISTO sulla cartina di Siena, non dedotto]
    # Piazza del Campo, la Torre del Mangia e l'albergo distano fra loro poche
    # decine di metri: alla scala della giornata i tre pallini finiscono uno
    # sopra l'altro e sulla figura ne resta visibile UNO. Il cliente contava di
    # vedere cinque tappe e ne vedeva tre. Qui si allontanano quel tanto che
    # basta a distinguerli — vedi `_declutter()` per il limite dello
    # scostamento e il perche' non tradisca la barra della scala.
    pixels, declustered = _declutter(true_pixels, width, height)
    hotel_px = pixels[0] if hotel_point else None
    stop_px = pixels[1:] if hotel_point else pixels

    # La geometria dei pallini si legge QUI, subito dopo il declutter e prima
    # che il disegno la appiattisca in un PNG: e' l'unico punto in cui esiste
    # ancora la posizione VERA di ogni pallino. Ricalcolarla a valle
    # rifacendo proiezione + declutter darebbe numeri leggermente diversi al
    # primo cambio di uno dei due, e il link finirebbe accanto al pallino
    # invece che sopra. In `try` perche' il contratto della cartina viene prima:
    # se l'export fallisce si consegna la figura senza lo strato dei link, mai
    # il contrario.
    try:
        pins = _geometria_dei_pin(stops, hotel_px, stop_px, hotel_name, width, height)
    except Exception:
        pins = None

    # --- Griglia di fondo -------------------------------------------------
    # Solo sullo schema. Sopra una cartina vera sarebbe rumore che copre le
    # strade, cioe' esattamente l'informazione per cui la cartina e' li'.
    if not sopra_cartina:
        step = 34 * _SCALE
        for x in range(step, width, step):
            draw.line([(x, 0), (x, height)], fill=_GRID_RGB, width=_SCALE)
        for y in range(step, height, step):
            draw.line([(0, y), (width, y)], fill=_GRID_RGB, width=_SCALE)

    # --- Percorso ---------------------------------------------------------
    # L'ordine e' quello della giornata: hotel -> 1 -> 2 -> ... -> hotel. Il
    # ritorno in albergo e' tratteggiato e non pieno, perche' e' l'unico
    # segmento che il cliente potrebbe non fare (cena fuori, rientro in taxi):
    # disegnarlo uguale agli altri lo racconterebbe come un obbligo.
    route = ([hotel_px] if hotel_px else []) + list(stop_px)
    if sopra_cartina and len(route) > 1:
        # Filo bianco sotto la linea: sopra una strada grigia o un parco verde
        # una linea navy sottile sparisce. E' la stessa soluzione che usano le
        # mappe stampate da sempre.
        draw.line(route, fill=_WHITE, width=4 * _SCALE, joint="curve")
    if len(route) > 1:
        draw.line(route, fill=_PATH_RGB, width=2 * _SCALE, joint="curve")
    if hotel_px and len(stop_px) >= 1:
        if sopra_cartina:
            _dashed_line(draw, stop_px[-1], hotel_px, _WHITE, 4 * _SCALE)
        _dashed_line(draw, stop_px[-1], hotel_px, _PATH_RGB, 2 * _SCALE)

    font_pin = _load_font(9 * _SCALE, bold=True)
    font_label = _load_font(8 * _SCALE, bold=True)
    font_small = _load_font(7 * _SCALE)
    # L'alone dietro il testo: sullo schema il colore della carta, sopra una
    # cartina vera il bianco pieno, che e' l'unico fondo su cui un nome resta
    # leggibile qualunque cosa ci sia sotto.
    alone = _WHITE if sopra_cartina else _BG_RGB

    # --- Etichette dei nomi ------------------------------------------------
    # Si disegnano PRIMA dei marker, cosi' un'etichetta lunga che finisce sotto
    # un pallino vicino resta sotto e non lo copre: il pallino numerato e'
    # l'informazione che non si puo' perdere, il nome e' il di piu' (c'e'
    # comunque nella legenda accanto).
    # `taken` accumula i rettangoli gia' occupati (etichette scritte e pallini):
    # per ogni nome si provano otto posizioni intorno al marker e si tiene la
    # prima libera. Senza questo passaggio due tappe vicine — il caso NORMALE in
    # un centro storico, che e' dove si svolge il 90 % di questi itinerari — si
    # scrivono l'una sopra l'altra e il risultato sembra un errore di stampa.
    taken: list[tuple[float, float, float, float]] = []
    for px, py in list(stop_px) + ([hotel_px] if hotel_px else []):
        r = 11 * _SCALE
        taken.append((px - r, py - r, px + r, py + r))

    for index, stop in enumerate(stops):
        px, py = stop_px[index]
        name = _truncate(stop.get("name") or stop.get("activity") or "", 24)
        if not name:
            continue
        text_w, text_h = _text_size(draw, name, font_label)
        gap = 12 * _SCALE
        diag = gap * 0.72
        candidates = [
            (px + gap, py - text_h / 2),                     # destra
            (px - gap - text_w, py - text_h / 2),            # sinistra
            (px - text_w / 2, py + gap),                     # sotto
            (px - text_w / 2, py - gap - text_h),            # sopra
            (px + diag, py + diag),                          # in basso a destra
            (px - diag - text_w, py + diag),                 # in basso a sinistra
            (px + diag, py - diag - text_h),                 # in alto a destra
            (px - diag - text_w, py - diag - text_h),        # in alto a sinistra
        ]
        placed = None
        for tx, ty in candidates:
            box = (tx - 2 * _SCALE, ty - 1 * _SCALE,
                   tx + text_w + 2 * _SCALE, ty + text_h + 2 * _SCALE)
            if box[0] < 2 * _SCALE or box[2] > width - 2 * _SCALE:
                continue
            if box[1] < 2 * _SCALE or box[3] > height - 2 * _SCALE:
                continue
            if any(_overlaps(box, other) for other in taken):
                continue
            placed = (tx, ty, box)
            break
        if placed is None:
            # Nessuna delle otto posizioni e' libera: il nome resta nella sola
            # legenda accanto alla cartina, dove c'e' comunque. Scriverlo qui
            # sopra qualcos'altro renderebbe illeggibili due informazioni invece
            # di una.
            continue
        tx, ty, box = placed
        taken.append(box)
        # Alone chiaro sotto il testo: senza, un nome che cade sopra una linea
        # del percorso diventa illeggibile. Rettangolo pieno e non trasparenza,
        # che questo stack non ha (stesso vincolo del CSS).
        draw.rectangle(list(box), fill=alone)
        draw.text((tx, ty), name, fill=_LABEL_RGB, font=font_label)

    # --- Marker ------------------------------------------------------------
    for index, stop in enumerate(stops):
        px, py = stop_px[index]
        colour = _MARKER_RGB.get(stop.get("color"), _FALLBACK_MARKER_RGB)
        _pin(draw, px, py, colour, str(stop.get("label") or "\u2022"), font_pin)
    if hotel_px:
        _pin(draw, hotel_px[0], hotel_px[1], _HOTEL_RGB, "H", font_pin)

    # --- Barra della scala --------------------------------------------------
    # Sopra la cartina di Google la scala e' NOTA: discende da zoom, latitudine
    # e fattore di scala con cui l'immagine e' stata generata, non c'e' niente
    # da stimare. Sullo schema si misura sul disegno vero: distanza reale fra i
    # due punti piu' lontani diviso i pixel che li separano — e sui punti VERI,
    # non su quelli allontanati per leggibilita': la barra misura la proiezione,
    # non il ritocco. Se la scala non e' calcolabile (tutti i punti coincidono)
    # la barra non si disegna: meglio nessuna scala di una scala inventata.
    if metres_per_px is None:
        metres_per_px = _metres_per_pixel(geo_points, true_pixels)
    if metres_per_px:
        target_px = width * 0.22
        nice_m = _nice_scale_metres(target_px * metres_per_px)
        if nice_m > 0:
            bar_px = nice_m / metres_per_px
            by = height - 16 * _SCALE
            # [CORRETTO 2026-08-02] La barra stava sempre in basso a sinistra e
            # una tappa in quell'angolo ci finiva sopra — e' successo con
            # l'albergo di Siena, che copriva la scritta "100 m". Si sceglie
            # l'angolo in basso piu' libero: la scala e' l'elemento che rende
            # onesta la figura, non puo' essere il primo a diventare illeggibile.
            left_box = (8 * _SCALE, by - 16 * _SCALE, 16 * _SCALE + bar_px, by + 6 * _SCALE)
            right_box = (width - 16 * _SCALE - bar_px, by - 16 * _SCALE,
                         width - 8 * _SCALE, by + 6 * _SCALE)
            pin_boxes = [
                (px - _PIN_RADIUS, py - _PIN_RADIUS, px + _PIN_RADIUS, py + _PIN_RADIUS)
                for px, py in list(stop_px) + ([hotel_px] if hotel_px else [])
            ]
            occupied = pin_boxes + taken
            left_busy = sum(1 for b in occupied if _overlaps(left_box, b))
            right_busy = sum(1 for b in occupied if _overlaps(right_box, b))
            bx = 12 * _SCALE if left_busy <= right_busy else width - 12 * _SCALE - bar_px
            if sopra_cartina:
                # Sopra la cartina la barra ha bisogno del suo fondo, altrimenti
                # cade su una via e diventa illeggibile proprio l'elemento che
                # certifica le distanze.
                draw.rectangle(
                    [bx - 5 * _SCALE, by - 14 * _SCALE,
                     bx + bar_px + 5 * _SCALE, by + 5 * _SCALE],
                    fill=_WHITE,
                )
            draw.line([(bx, by), (bx + bar_px, by)], fill=_LABEL_RGB, width=2 * _SCALE)
            draw.line([(bx, by - 3 * _SCALE), (bx, by + 3 * _SCALE)], fill=_LABEL_RGB, width=2 * _SCALE)
            draw.line(
                [(bx + bar_px, by - 3 * _SCALE), (bx + bar_px, by + 3 * _SCALE)],
                fill=_LABEL_RGB, width=2 * _SCALE,
            )
            draw.text((bx, by - 12 * _SCALE), _format_metres(nice_m), fill=_LABEL_RGB, font=font_small)

    # --- Rosa dei venti ----------------------------------------------------
    # Solo il nord, che e' l'unica direzione che serve per orientare la figura
    # rispetto al mondo vero.
    nx, ny = width - 20 * _SCALE, 20 * _SCALE
    if sopra_cartina:
        draw.rectangle(
            [nx - 8 * _SCALE, ny - 12 * _SCALE, nx + 8 * _SCALE, ny + 17 * _SCALE],
            fill=_WHITE,
        )
    draw.line([(nx, ny + 7 * _SCALE), (nx, ny - 7 * _SCALE)], fill=_MUTED_RGB, width=2 * _SCALE)
    draw.polygon(
        [(nx, ny - 10 * _SCALE), (nx - 4 * _SCALE, ny - 3 * _SCALE), (nx + 4 * _SCALE, ny - 3 * _SCALE)],
        fill=_MUTED_RGB,
    )
    draw.text((nx - 3 * _SCALE, ny + 8 * _SCALE), "N", fill=_MUTED_RGB, font=font_small)

    # --- Intestazione e cornice --------------------------------------------
    if day_label:
        etichetta = _truncate(day_label, 46)
        tx, ty = 12 * _SCALE, 10 * _SCALE
        if sopra_cartina:
            tw, th = _text_size(draw, etichetta, font_small)
            draw.rectangle(
                [tx - 4 * _SCALE, ty - 3 * _SCALE, tx + tw + 4 * _SCALE, ty + th + 4 * _SCALE],
                fill=_WHITE,
            )
        draw.text((tx, ty), etichetta, fill=_MUTED_RGB, font=font_small)
    draw.rectangle([0, 0, width - 1, height - 1], outline=_FRAME_RGB, width=1 * _SCALE)

    buffer = io.BytesIO()
    # Palette adattiva: lo schema usa una decina di tinte piatte e 64 colori lo
    # rendono identico a un quarto del peso. Una cartina stradale vera ne ha
    # molte di piu' (verde dei parchi, azzurro dell'acqua, sfumature delle
    # strade) e a 64 si vedrebbe a fasce: li' se ne usano 200, che restano
    # comunque un terzo del PNG a colori pieni. Su un PDF che viaggia in
    # allegato via email, e che Make deve anche trasportare in base64 sotto il
    # tetto dei 256 KB per stringa, il peso non e' un dettaglio estetico.
    colori = 200 if sopra_cartina else 64
    image.convert("P", palette=1, colors=colori).save(buffer, format="PNG", optimize=True)
    meta = {"declustered": declustered}
    if pins:
        meta["pins"] = pins
    return buffer.getvalue(), meta


def _pin(draw, px: float, py: float, colour: tuple, label: str, font) -> None:
    """Pallino pieno con bordo bianco e numero al centro: lo stesso oggetto
    grafico della legenda nel CSS (`.map-pin`), perché siano riconoscibili come
    la stessa cosa a colpo d'occhio."""
    radius = _PIN_RADIUS
    draw.ellipse(
        [px - radius - 1.5 * _SCALE, py - radius - 1.5 * _SCALE,
         px + radius + 1.5 * _SCALE, py + radius + 1.5 * _SCALE],
        fill=_WHITE,
    )
    draw.ellipse([px - radius, py - radius, px + radius, py + radius], fill=colour)
    if font is None:
        return
    text_w, text_h = _text_size(draw, label, font)
    draw.text((px - text_w / 2, py - text_h / 2 - 1 * _SCALE), label, fill=_WHITE, font=font)


def _geometria_dei_pin(
    stops: list,
    hotel_px,
    stop_px: list,
    hotel_name,
    width: int,
    height: int,
) -> list[dict]:
    """
    Dove sta ogni pallino sull'immagine, perche' ci si possa appoggiare sopra un
    link cliccabile.

    PERCHE'. Dentro un PNG non si clicca niente. Il cliente pero' guarda la
    cartina sul telefono e il gesto naturale e' toccare il pallino della tappa:
    senza queste coordinate il renderer non ha modo di sapere dove mettere
    l'ancora HTML, e l'unica strada che resta e' la lista di link sotto la
    figura — che c'e', ma costa al cliente il lavoro di ritrovare "quale numero
    era il museo".

    IN PERCENTUALE E NON IN PIXEL. L'immagine nel documento e' scalata
    (`max-width: 100%` nel CSS del PDF) e disegnata a 3x la dimensione di
    stampa: i pixel di questo disegno non sono i pixel della pagina, e non lo
    sono nemmeno in modo costante. Una percentuale sopravvive a qualunque
    ridimensionamento, che e' esattamente cio' che serve a un overlay
    posizionato in `%` sopra l'immagine.

    `r_pct` e' in percentuale della LARGHEZZA anche per l'asse verticale: un
    pallino e' un cerchio, e un'area cliccabile calcolata con due percentuali
    diverse per i due assi sarebbe un'ellisse.

    ORDINE. Albergo per primo se e solo se e' stato disegnato, poi le tappe
    nell'ordine di `stops` — che e' gia' filtrato di quelle senza coordinate,
    cioe' di quelle che sulla figura non ci sono. Un pallino esportato ma non
    disegnato sarebbe un link su un punto vuoto della cartina.
    """
    pins: list[dict] = []
    if hotel_px is not None:
        # `poi_id` nullo e' il modo in cui il chiamante riconosce l'albergo: non
        # e' una tappa numerata, il suo identificativo sta in `hotel_id` del
        # piano. "Alloggio" e' lo stesso ripiego che usa `directions.py` quando
        # il nome dell'hotel manca, cosi' la stessa cosa si chiama allo stesso
        # modo nei due punti del documento in cui compare.
        pins.append(_pin_cliccabile(
            "H", None, str(hotel_name or "Alloggio"), hotel_px, width, height))
    for index, stop in enumerate(stops):
        if index >= len(stop_px):
            break
        poi_id = stop.get("poi_id")
        pins.append(_pin_cliccabile(
            # Esattamente l'etichetta DISEGNATA sul pallino, ripiego compreso:
            # se sulla figura c'e' un punto e nella legenda un "1", il cliente
            # non li collega.
            str(stop.get("label") or "•"),
            # Solo una stringa non vuota: il chiamante ci costruisce sopra un
            # link e un id di altro tipo non corrisponderebbe a nessun POI.
            poi_id if isinstance(poi_id, str) and poi_id else None,
            # Il nome INTERO, non quello troncato a 24 caratteri sulla figura:
            # li' il taglio serve a non coprire la cartina, qui il nome finisce
            # nel titolo del link, dove per il cliente e' l'unica conferma di
            # aver toccato la tappa giusta.
            str(stop.get("name") or stop.get("activity") or ""),
            stop_px[index], width, height,
        ))
    return pins


def _pin_cliccabile(label: str, poi_id, name: str, punto, width: int, height: int) -> dict:
    px, py = punto
    return {
        "label": label,
        "poi_id": poi_id,
        "name": name,
        # Il taglio a 0-100 e' difensivo: `_declutter()` gia' tiene i pallini
        # dentro la cornice, ma un link che finisse fuori dall'immagine
        # coprirebbe il testo della pagina e verrebbe toccato per sbaglio.
        # Due decimali bastano: sono ~0,1 px su un'immagine da 1280, cioe'
        # molto meno del bordo bianco del pallino.
        "x_pct": round(min(max(px / width * 100.0, 0.0), 100.0), 2),
        "y_pct": round(min(max(py / height * 100.0, 0.0), 100.0), 2),
        "r_pct": round(_PIN_RADIUS / width * 100.0, 2),
    }


def _declutter(
    points: list[tuple[float, float]], width: int, height: int
) -> tuple[list[tuple[float, float]], bool]:
    """
    Allontana i pallini che si coprono a vicenda, e dice se l'ha dovuto fare.

    PERCHÉ. In un centro storico — cioè nella quasi totalità di questi
    itinerari — due tappe distano spesso meno di cinquanta metri: alla scala
    della giornata i loro pallini si sovrappongono e il cliente ne vede uno solo.
    Una cartina che nasconde due tappe su cinque è peggio di nessuna cartina,
    perché sembra completa.

    COME. Rilassamento a coppie: finché due pallini distano meno del loro
    diametro, si spingono via l'uno dall'altro di metà della differenza. Poche
    iterazioni bastano; non serve un algoritmo elegante, serve che si vedano.

    QUANTO — ed è la parte che conta. Lo scostamento di ogni pallino è limitato
    a `_MAX_SHIFT`: qualche millimetro sulla pagina. Il vincolo esiste perché la
    figura dichiara di essere "in scala" e la barra della scala è una promessa
    misurabile; consentire spostamenti liberi trasformerebbe quella promessa in
    una bugia. Con questo tetto, due punti allontanati restano entro l'errore
    che il cliente già accetta leggendo un pallino largo come un isolato. E
    quando lo scostamento avviene, la didascalia lo dice.
    """
    pts = [list(p) for p in points]
    if len(pts) < 2:
        return [tuple(p) for p in pts], False
    min_sep = 2 * _PIN_RADIUS + 2 * _SCALE
    for _ in range(80):
        moved = False
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                dx, dy = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
                dist = math.hypot(dx, dy)
                if dist >= min_sep:
                    continue
                if dist < 1e-6:
                    # Coincidenti: nessuna direzione naturale in cui separarli.
                    # Si usa un angolo che dipende dall'indice, così due punti
                    # coincidenti vanno da parti diverse in modo deterministico
                    # (il PDF dev'essere riproducibile, non casuale).
                    angle = (i * 2.399963) % (2 * math.pi)
                    dx, dy, dist = math.cos(angle), math.sin(angle), 1.0
                push = (min_sep - dist) / 2.0
                ux, uy = dx / dist, dy / dist
                pts[i][0] -= ux * push; pts[i][1] -= uy * push
                pts[j][0] += ux * push; pts[j][1] += uy * push
                moved = True
        if not moved:
            break

    out: list[tuple[float, float]] = []
    declustered = False
    for (ox, oy), (nx, ny) in zip(points, pts):
        dx, dy = nx - ox, ny - oy
        shift = math.hypot(dx, dy)
        if shift > _MAX_SHIFT:
            scale = _MAX_SHIFT / shift
            dx, dy, shift = dx * scale, dy * scale, _MAX_SHIFT
        if shift > 1.5 * _SCALE:
            declustered = True
        margin = _PIN_RADIUS + 3 * _SCALE
        x = min(max(ox + dx, margin), width - margin)
        y = min(max(oy + dy, margin), height - margin)
        out.append((x, y))
    return out, declustered


def _overlaps(a: tuple, b: tuple) -> bool:
    """Due rettangoli (x0, y0, x1, y1) si sovrappongono?"""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _dashed_line(draw, start, end, colour, width: int, dash: int = 5) -> None:
    """Una linea tratteggiata, che questo toolkit non offre nativamente."""
    x1, y1 = start
    x2, y2 = end
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= 0:
        return
    dash_px = dash * _SCALE
    steps = max(int(length // dash_px), 1)
    for i in range(steps):
        if i % 2:
            continue
        t0, t1 = i / steps, min((i + 1) / steps, 1.0)
        draw.line(
            [(x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0),
             (x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1)],
            fill=colour, width=width,
        )


def _metres_per_pixel(geo: list[tuple[float, float]], pixels: list[tuple[float, float]]) -> float | None:
    """Metri reali per pixel disegnato, misurati sulla coppia di punti più
    distante in pixel — la coppia su cui l'errore relativo è minore."""
    best = None
    for i in range(len(geo)):
        for j in range(i + 1, len(geo)):
            dist_px = math.hypot(pixels[i][0] - pixels[j][0], pixels[i][1] - pixels[j][1])
            if dist_px <= 1:
                continue
            if best is None or dist_px > best[0]:
                best = (dist_px, _haversine_m(geo[i], geo[j]))
    if best is None or best[1] <= 0:
        return None
    return best[1] / best[0]


def attach_local_maps(day_maps: list[dict] | None) -> list[dict]:
    """
    Riempie il campo `png` di ogni giornata che non ce l'ha, disegnandolo con
    questo modulo. Idempotente: una giornata che ha già la cartina di Google
    (`png` valorizzato) non viene toccata, perché una mappa stradale vera è
    meglio del nostro schema ogni volta che c'è.

    Marca la provenienza in `map_source` (`"google"` | `"schema"`), che il
    renderer usa per scrivere sotto la figura la didascalia giusta — al cliente
    va detto che cosa sta guardando, sempre.

    [AGGIUNTO 2026-08-03] Aggiunge anche `pins`: per ogni pallino DISEGNATO,
    `{"label", "poi_id", "name", "x_pct", "y_pct", "r_pct"}` — la posizione in
    percentuale dell'immagine, nell'ordine albergo (se c'e') + tappe. Serve al
    renderer per appoggiare un'ancora HTML sopra il pallino: dentro un PNG non
    si clicca niente, e toccare il pallino e' il gesto che un cliente con il
    telefono in mano fa comunque. `pins` e' ASSENTE quando non c'e' figura,
    stessa convenzione di `map_source`. Vedi `_geometria_dei_pin()`.
    """
    out = []
    for plan in day_maps or []:
        if not isinstance(plan, dict):
            continue
        plan = dict(plan)
        day = plan.get("day")
        title = plan.get("title") or ""
        label = " · ".join(x for x in (f"Giorno {day}" if day else "", title) if x)
        base_map = plan.get("base_map")

        # Caso nuovo (2026-08-02) e ormai normale in produzione: `png` e' lo
        # SFONDO stradale nudo e `base_map` dice con che centro/zoom/scala e'
        # stato generato. Ci disegniamo sopra le stesse tappe numerate dello
        # schema — strade vere SOTTO, pallini nostri SOPRA.
        if plan.get("png") and isinstance(base_map, dict):
            png, meta = render_day_map_over_base(plan, label, plan["png"], base_map)
            if png:
                plan["png"] = png
                plan["map_source"] = "google"
                if meta.get("declustered"):
                    plan["map_declustered"] = True
                _applica_pin(plan, meta)
                out.append(plan)
                continue
            # Il disegno sopra lo sfondo non e' riuscito. Lo sfondo da solo NON
            # va consegnato: e' la cartina della citta', non della giornata, e
            # il cliente ci cercherebbe i pallini della legenda senza trovarli.
            # Si butta e si ridisegna lo schema, che non dipende da niente.
            plan["png"] = None

        # Caso storico: `png` e' gia' una cartina finita (i marker li ha
        # disegnati Google via URL). Non si tocca.
        elif plan.get("png"):
            plan.setdefault("map_source", "google")
            out.append(plan)
            continue

        png, meta = render_day_map(plan, label)
        if png:
            plan["png"] = png
            plan["map_source"] = "schema"
            if meta.get("declustered"):
                plan["map_declustered"] = True
        _applica_pin(plan, meta if png else {})
        out.append(plan)
    return out


def _applica_pin(plan: dict, meta: dict) -> None:
    """Porta la geometria dei pallini sul piano, dove il renderer la trova.

    Le due regole, entrambe volute:
      - `pins` c'e' SOLO se c'e' anche la figura, esattamente come `map_source`.
        Un elenco di link senza l'immagine sotto non e' un'informazione in meno,
        e' un overlay appoggiato sul nulla;
      - se questa passata non ha prodotto pallini, un eventuale `pins` rimasto
        dalla passata precedente si butta: sarebbe la geometria di UN'ALTRA
        immagine, cioe' link nel posto sbagliato — il difetto peggiore di tutti,
        perche' silenzioso.
    """
    pins = (meta or {}).get("pins")
    if pins:
        plan["pins"] = pins
    else:
        plan.pop("pins", None)
