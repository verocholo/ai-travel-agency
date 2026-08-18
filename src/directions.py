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

# [NUOVO 2026-08-01 — collaudo del primo PDF venduto davvero, difetto 4]
# Nel PDF reale comparivano righe come "circa 0 min in auto" tra due tappe
# dello stesso centro storico. Sono tecnicamente vere (la Distance Matrix
# arrotonda per difetto) e praticamente assurde: nessuno prende l'auto per
# zero minuti, e un cliente che legge "in auto" in un centro pedonale smette
# di fidarsi di TUTTO il resto del documento. Sotto questa soglia lo
# spostamento non è un tragitto, è una prossimità: va detto con una parola,
# non con un numero e un mezzo di trasporto.
NEGLIGIBLE_LEG_MINUTES = 2
NEGLIGIBLE_LEG_TEXT = "a pochi passi"

# [NUOVO 2026-08-18 — dal fascicolo di Bologna vero, pagina 6: «circa 12 min
# in auto · circa 960 m» per andare a cena, su un itinerario che il documento
# stesso dichiara tutto a piedi.]
#
# Novecentosessanta metri in auto sono dodici minuti di traffico e zero
# senso: e' lo stesso difetto gia' riparato il 1 agosto per gli spostamenti
# da zero minuti («nessuno prende l'auto per zero minuti»), visto dall'altro
# lato — li' era il TEMPO a essere assurdo, qui e' la DISTANZA.
#
# Sotto questa soglia il tragitto si dichiara a piedi e il tempo si ricalcola
# sull'andatura, perche' il numero misurato in auto non descrive piu' niente
# di utile. E' un dato derivato, non misurato, ed e' comunque molto piu'
# onesto del precedente: la distanza resta quella vera di Google.
#
# Millecinquecento metri sono circa venti minuti di cammino: la soglia oltre
# la quale una persona in citta' comincia davvero a valutare un mezzo. Sopra,
# il documento continua a mostrare il tempo in auto e offre accanto
# l'alternativa coi mezzi, che e' la scelta giusta per un tragitto vero.
METRI_MASSIMI_A_PIEDI = 1500

# [NUOVO 2026-08-01 — "semplificargli la vita e togliergli più lavoro
# possibile"] Sopra questa soglia uno spostamento non si improvvisa: vale la
# pena offrire ANCHE il percorso coi mezzi accanto a quello a piedi, così il
# cliente confronta in un tap invece di scoprire in strada che quaranta minuti
# a piedi erano due fermate di metro. Sotto la soglia l'alternativa è rumore.
ALTERNATIVE_MODE_MIN_MINUTES = 12

# Margine di sicurezza sull'ora di partenza calcolata: la Distance Matrix
# misura porta-a-porta, non "il tempo di finire il caffè, trovare l'uscita e
# capire da che parte girare". Cinque minuti è il minimo onesto; senza, l'ora
# stampata sarebbe sistematicamente ottimistica e il cliente sistematicamente
# in ritardo — cioè un dato peggiore di nessun dato.
DEPARTURE_BUFFER_MINUTES = 5


def _parse_clock(value) -> int | None:
    """`"11:00"` -> minuti dalla mezzanotte. `None` se non è un orario.

    Accetta anche le forme che Claude produce davvero nei blocchi
    (`"09:30-11:00"`, `"9:30"`): si prende il PRIMO orario, che è quello di
    inizio dell'attività, cioè l'istante in cui bisogna esserci.
    """
    if not isinstance(value, str):
        return None
    head = value.strip().split("-")[0].split("–")[0].strip()
    parts = head.split(":")
    if len(parts) != 2:
        return None
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def compute_departure_time(arrival_time, minutes, buffer_minutes: int = DEPARTURE_BUFFER_MINUTES):
    """"A che ora devo uscire?" — la domanda che il cliente si fa davvero.

    [NUOVO 2026-08-01] Il PDF sapeva già due cose separate: che l'attività
    comincia alle 11:00 e che il tragitto dura 18 minuti. La sottrazione la
    faceva il cliente, in strada, col telefono in mano. Farla noi costa zero
    (nessuna chiamata, nessun dato nuovo) ed è esattamente il "togliergli più
    lavoro possibile" chiesto da Lorenzo.

    Ritorna `"HH:MM"` oppure `None` quando manca uno dei due ingredienti —
    mai un orario stimato. Se la sottrazione scavalca la mezzanotte
    (spostamento notturno di rientro) ritorna `None`: un "parti entro le
    23:50" del giorno prima confonderebbe più di quanto aiuti.
    """
    arrival_min = _parse_clock(arrival_time)
    if arrival_min is None:
        return None
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        return None
    depart_min = arrival_min - minutes - max(0, int(buffer_minutes))
    if depart_min < 0:
        return None
    return f"{depart_min // 60:02d}:{depart_min % 60:02d}"


def describe_leg_duration(minutes, mode_label: str | None = "") -> str | None:
    """Testo onesto per la durata di un tragitto.

    - `None` se non abbiamo una misura reale: il chiamante scriverà
      esplicitamente che il tempo va verificato (mai una stima inventata).
    - `"a pochi passi"` quando la misura è sotto la soglia di significatività:
      il mezzo NON viene nominato, perché è proprio il mezzo il dato assurdo
      ("in auto" per 0 minuti).
    - altrimenti "circa N min <mezzo>".
    """
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        return None
    if minutes <= NEGLIGIBLE_LEG_MINUTES:
        return NEGLIGIBLE_LEG_TEXT
    return f"circa {minutes} min {(mode_label or '').strip()}".strip()


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
            lookup[key] = {
                "minutes": minutes,
                "mode": getattr(tt, "mode", None),
                # [AGGIUNTO 2026-08-03 — task #179] I metri viaggiano come
                # attributo appeso (vedi `distance_matrix.TRAVEL_TIME_METRES_ATTR`)
                # e possono non esserci affatto: dopo un giro sul filo HTTP la
                # dataclass viene ricostruita senza. `None` qui non e' un
                # errore, e' il caso normale meta' delle volte.
                "metres": _metri_di(tt),
            }
    return lookup


def _metri_di(tt) -> int | None:
    """I metri appesi a una misura, se ci sono e se sono un numero vero."""
    valore = getattr(tt, "metres", None)
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        return None
    if valore < 0 or valore != valore or valore in (float("inf"), float("-inf")):
        return None
    return int(round(valore))


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
            # [CORRETTO 2026-08-02 — stesso difetto già corretto in legenda,
            # visto rigenerando il campione con un payload completo] Prima
            # veniva prima `location`, che nei blocchi veri è un indirizzo
            # oppure — peggio — il nome nudo della città: uscivano tratte
            # illeggibili come «1 → 2  Siena → Piazza del Campo 1» e
            # «2 → 3  Piazza del Duomo 1 → Siena», dove lo stesso posto compare
            # una volta col nome e una volta con la via, e la città finisce a
            # fare da tappa. La riga "come arrivare" risponde a una domanda
            # sola — "da DOVE a DOVE mi sto spostando?" — e per rispondere
            # servono due NOMI. L'indirizzo di destinazione resta stampato nel
            # programma della giornata, e il link Google Maps porta comunque
            # al posto esatto: qui serve il nome.
            "name": stop.get("name") or stop.get("activity") or stop.get("location") or "",
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
        # Difetto 4, seconda metà: se la misura dice che sono adiacenti, il
        # link deve aprire le indicazioni A PIEDI. Aprire la navigazione
        # stradale per duecento metri è, dal lato del cliente, un errore.
        negligible = isinstance(minutes, int) and not isinstance(minutes, bool) and 0 <= minutes <= NEGLIGIBLE_LEG_MINUTES
        if negligible:
            mode = "walking"
        mode_label = travel_mode_label(mode)
        # [AGGIUNTO 2026-08-03 — task #179] Prima i metri veri di Google.
        # Se non ci sono (payload arrivato via HTTP, dove l'attributo appeso
        # non sopravvive alla serializzazione) si ripiega sulla linea d'aria
        # corretta di un fattore stradale, e lo si DICHIARA: un totale
        # stimato spacciato per misurato e' peggio di nessun totale.
        metri = (measured or {}).get("metres")
        metri = metri if isinstance(metri, int) and not isinstance(metri, bool) else None
        metri_stimati = False
        if metri is None:
            metri = stima_metri_in_linea_daria(origin.get("point"), dest.get("point"))
            metri_stimati = metri is not None

        # [RICLASSIFICATO SULLA DISTANZA — 2026-08-18] Vedi
        # `METRI_MASSIMI_A_PIEDI`. Si fa QUI e non piu' su, dov'e' la
        # riclassificazione gemella basata sui minuti, per una ragione
        # banale: i metri si conoscono solo adesso.
        if (mode == "driving" and isinstance(metri, int)
                and 0 < metri <= METRI_MASSIMI_A_PIEDI):
            mode = "walking"
            mode_label = travel_mode_label(mode)
            minuti_a_piedi = int(round(metri / METRI_AL_MINUTO_A_PIEDI))
            # Mai zero: «circa 0 min a piedi» sarebbe l'assurdita' di prima
            # con un mezzo diverso. Sotto la soglia dei due minuti il testo
            # diventa comunque «a pochi passi», che e' la forma giusta.
            minutes = max(1, minuti_a_piedi)

        arrival_time = dest.get("time", "")
        # [NUOVO 2026-08-01] Alternativa coi mezzi solo sui tragitti lunghi, e
        # solo quando il modo principale non è già quello: due link identici
        # sarebbero rumore.
        alt_mode = None
        if (
            isinstance(minutes, int) and not isinstance(minutes, bool)
            and minutes >= ALTERNATIVE_MODE_MIN_MINUTES
            and mode != "transit"
        ):
            alt_mode = "transit"
        legs.append({
            "from_label": origin.get("label", ""),
            "from_name": origin.get("name", ""),
            "to_label": dest.get("label", ""),
            "to_name": dest.get("name", ""),
            # [AGGIUNTI 2026-08-02 — task #166] Gli id erano già qui dentro
            # (servono per cercare la misura in `travel_lookup`) ma non
            # uscivano dal leg: chi legge i leg a valle poteva sapere QUANTI
            # minuti dura uno spostamento, non FRA QUALI blocchi. Serve a
            # `pacing.analyze_day()`, che deve sottrarre il tempo di
            # spostamento dalla finestra fra due blocchi per capire quanto
            # tempo resta davvero libero.
            "from_poi_id": origin.get("poi_id"),
            "to_poi_id": dest.get("poi_id"),
            "arrival_time": arrival_time,
            "minutes": minutes,
            # [AGGIUNTI 2026-08-03 — task #179, richiesta di Lorenzo:
            # "inserire nel programma del giorno il totale di
            # chilometri/percorrenze a piedi"] Tre campi e non uno solo,
            # perche' un totale di chilometri messo accanto a un programma di
            # giornata e' una promessa: chi lo legge decide che scarpe
            # mettersi. `metres` e' il numero, `metres_estimated` dice se
            # viene da Google o dalla linea d'aria, `distance_text` e' la
            # forma gia' pronta da stampare. Tenerli separati permette di
            # sommare i numeri e di dichiarare la stima UNA volta sola sul
            # totale invece che su ogni riga.
            "metres": metri,
            "metres_estimated": metri_stimati,
            "distance_text": format_distance(metri),
            "mode": mode,
            "mode_label": mode_label,
            "duration_text": describe_leg_duration(minutes, mode_label),
            "depart_by": compute_departure_time(arrival_time, minutes),
            "url": build_directions_url(origin["point"], dest["point"], mode),
            "alt_mode": alt_mode,
            "alt_mode_label": travel_mode_label(alt_mode) if alt_mode else None,
            "alt_url": (
                build_directions_url(origin["point"], dest["point"], alt_mode)
                if alt_mode else None
            ),
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


# --------------------------------------------------------------------------
# [NUOVO 2026-08-03 — task #179] Chilometri e percorrenze a piedi
#
# Richiesta letterale di Lorenzo:
#   "inserire nel programma del giorno il totale di chilometri/percorrenze a
#    piedi"
#
# Perche' e' una funzionalita' e non un abbellimento: il numero che manca a
# chi legge un programma di giornata non e' "quante tappe", e' "quanto
# cammino". E' il dato che decide le scarpe, che dice a chi ha un ginocchio
# malandato se quella giornata e' fattibile, e che smaschera un itinerario
# scritto bene ma impossibile da percorrere.
#
# TRE REGOLE, tutte sull'onesta' del numero:
# 1. I metri veri vengono da Google e sono gia' pagati (stanno nella stessa
#    risposta da cui leggiamo i minuti). Non costano una chiamata in piu'.
# 2. Quando i metri veri non ci sono si usa la linea d'aria moltiplicata per
#    un fattore stradale, e il totale viene marcato come STIMATO. Il PDF
#    scrivera' "circa" e lo dira'.
# 3. "A piedi" vuol dire il modo del tragitto, non un'ipotesi. Un tragitto in
#    autobus non entra nel totale a piedi nemmeno se e' corto.
# --------------------------------------------------------------------------

# Rapporto fra percorso reale e distanza in linea d'aria in un centro urbano.
# 1.3 e' il valore comunemente usato per gli spostamenti a piedi in citta'
# (isolati rettangolari, sensi unici pedonali, ponti). Non e' un dato di
# Google: proprio per questo ogni numero che ne deriva esce marcato "stimato".
FATTORE_STRADALE = 1.3

# Sotto questa soglia il totale di giornata non si stampa: "0,2 km a piedi"
# non e' un'informazione, e' rumore su ogni giornata passata dentro un museo.
METRI_MINIMI_PER_STAMPARE = 400

# Andatura di camminata usata SOLO per i tragitti a piedi di cui conosciamo i
# metri ma non i minuti. 4,5 km/h e' l'andatura media di un turista con zaino,
# non quella di un pendolare.
METRI_AL_MINUTO_A_PIEDI = 75.0


def stima_metri_in_linea_daria(origine, destinazione) -> int | None:
    """Metri stimati fra due coordinate, oppure `None`.

    Formula dell'emisenoverso (haversine) sul raggio medio terrestre, poi
    moltiplicata per `FATTORE_STRADALE`. Ritorna `None` — mai 0 — se una
    delle due coordinate non e' utilizzabile: "non lo so" e "sono nello
    stesso punto" sono due affermazioni diverse, e un totale di giornata non
    deve poterle confondere.
    """
    import math

    try:
        lat1, lng1 = float(origine[0]), float(origine[1])
        lat2, lng2 = float(destinazione[0]), float(destinazione[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(v) for v in (lat1, lng1, lat2, lng2)):
        return None
    raggio = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    metri = 2 * raggio * math.asin(min(1.0, math.sqrt(a)))
    return int(round(metri * FATTORE_STRADALE))


def format_distance(metri) -> str | None:
    """`1840` -> `"1,8 km"`, `320` -> `"320 m"`, tutto il resto -> `None`.

    La virgola e' quella italiana: il documento e' in italiano e "1.8 km"
    letto da un italiano e' un refuso, non un numero.
    """
    if isinstance(metri, bool) or not isinstance(metri, (int, float)):
        return None
    if metri < 0:
        return None
    if metri < 1000:
        return f"{int(round(metri / 10.0)) * 10} m"
    return f"{metri / 1000:.1f}".replace(".", ",") + " km"


def summarize_day_travel(legs) -> dict | None:
    """Il totale di una giornata, oppure `None` se non c'e' niente da dire.

    Ritorna:
      {"metres", "metres_text", "estimated",
       "walking_metres", "walking_text", "walking_minutes", "legs"}

    `None` (e non un dizionario di zeri) quando i metri non si conoscono per
    nessun tragitto o quando il totale sta sotto `METRI_MINIMI_PER_STAMPARE`:
    una riga "in movimento: 0 m" su una giornata in cui si e' camminato
    davvero e' peggio dell'assenza della riga, perche' e' falsa.
    """
    totale = 0
    a_piedi = 0
    minuti_a_piedi = 0
    stimato = False
    contati = 0
    for leg in legs or []:
        if not isinstance(leg, dict):
            continue
        metri = leg.get("metres")
        if isinstance(metri, bool) or not isinstance(metri, (int, float)) or metri < 0:
            continue
        metri = int(round(metri))
        totale += metri
        contati += 1
        if leg.get("metres_estimated"):
            stimato = True
        if leg.get("mode") == "walking":
            a_piedi += metri
            minuti = leg.get("minutes")
            if isinstance(minuti, int) and not isinstance(minuti, bool) and minuti > 0:
                minuti_a_piedi += minuti
            else:
                # Metri senza minuti: capita sui tragitti che Google ha
                # misurato in auto e che noi abbiamo riclassificato a piedi
                # perche' erano di due passi. Meglio un'andatura dichiarata
                # che una casella vuota nel totale della giornata.
                minuti_a_piedi += int(round(metri / METRI_AL_MINUTO_A_PIEDI))
    if not contati or totale < METRI_MINIMI_PER_STAMPARE:
        return None
    return {
        "metres": totale,
        "metres_text": format_distance(totale),
        "estimated": stimato,
        "walking_metres": a_piedi,
        "walking_text": format_distance(a_piedi) if a_piedi else None,
        "walking_minutes": minuti_a_piedi or None,
        "legs": contati,
    }
