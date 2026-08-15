"""
NODO 4 — Google Distance Matrix. HTTP_MODULES_REALI.md §NODO 4 ("FINALIZZATO",
poi esteso 2026-07-11 — vedi nota multi-mode più sotto).
Decisione (Lorenzo): matrice piena N×N, hard-cap 10 punti (1 hotel + max 9 POI).
"""
from __future__ import annotations
import math
import os

import requests

from . import cost_telemetry
from .schemas import Hotel, POI, TravelTime

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

# [AGGIUNTO 2026-08-01 — prima misura di costo in produzione]
# Fino a oggi la modalità "driving" inviava sempre `departure_time=now`.
# Due problemi, scoperti insieme guardando il costo reale della prima
# esecuzione vera:
#
# 1. COSTO. Google fattura la Distance Matrix su due SKU distinti. Senza
#    informazioni di traffico è "Essentials", 5 $ ogni 1000 elementi; appena
#    la richiesta contiene `departure_time` diventa "Advanced", 10 $ ogni
#    1000 — il doppio. Con la matrice piena 10x10 questo significa 1,00 $
#    invece di 0,50 $ per il solo giro "driving", cioè circa 0,46 € in più
#    per ogni itinerario venduto a 4,90 €.
#
# 2. SENSO. `departure_time=now` chiede il traffico di ADESSO. Ma il viaggio
#    del cliente è nel futuro, spesso di settimane: il traffico di questo
#    preciso momento su quella strada non descrive il suo viaggio, descrive
#    il nostro pomeriggio. Stavamo pagando il doppio per un dato che, nel
#    caso d'uso reale, è rumore travestito da precisione.
#
# Quindi il traffico ora è SPENTO per default. Resta accendibile con
# DISTANCE_MATRIX_TRAFFIC=true senza toccare il codice, perché per un
# prodotto diverso (un itinerario per oggi, una navetta, un transfer) la
# scelta opposta sarebbe quella giusta — e perché una decisione di costo
# reversibile da una variabile d'ambiente è una decisione che si può
# rimisurare invece di ridiscutere.
_TRAFFIC_ENV_VAR = "DISTANCE_MATRIX_TRAFFIC"


def traffic_enabled() -> bool:
    """True se le richieste "driving" devono includere il traffico in tempo reale.

    Default: False — vedi la nota estesa qui sopra. Attivandolo, il costo del
    giro "driving" RADDOPPIA e la telemetria lo registra sotto la voce
    `google_distance_matrix_advanced`, così il resoconto dei costi resta
    onesto invece di continuare a mostrare la tariffa base.
    """
    raw = os.getenv(_TRAFFIC_ENV_VAR)
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "si", "sì")

MAX_POI_POINTS = 9  # cintura di sicurezza ridondante col cap lato Places (maxResultCount)

# [AGGIUNTO 2026-08-01] Tetto usato dalla pipeline quando `plan_matrix()` può
# scegliere la sola modalità pedonale: 14 punti totali (1 hotel + 13 POI) danno
# 196 elementi, sotto il budget di 200 che spendiamo comunque oggi. Vedi la
# nota estesa sopra `plan_matrix()`.
MAX_POI_POINTS_COMPACT = 13

# [AGGIUNTO 2026-07-11 — capstone live test, bug reale scoperto dal vivo]
# Prima questo modulo chiedeva SOLO mode="driving", sempre e comunque. Sul
# primo vero test dal vivo su un centro storico compatto e pedonale
# (Repubblica di San Marino, modulo famiglia), la matrice "in auto" è
# tornata a 0 minuti per OGNI coppia di punti — tecnicamente corretto (le
# distanze reali sono di poche centinaia di metri), ma fuorviante: un
# centro storico collinare a piedi ha attrito reale (scalini, acciottolato,
# dislivelli) che "0 min in auto" nasconde del tutto. Claude stesso se n'è
# accorto e l'ha segnalato onestamente nei suoi "Tips" invece di
# presentare il dato come affidabile — comportamento corretto, ma il gap
# è nei DATI forniti, non nel ragionamento. FRICTION_SAFETY in particolare
# esiste apposta per proteggere da "salite/camminate lunghe": un dato "in
# auto" non misura affatto questo rischio.
# Fix: interroghiamo la Distance Matrix in DUE modalità (driving + walking)
# invece di una sola, e lasciamo che sia Claude — non una soglia hardcoded
# qui — a scegliere quale dei due tempi è il più realistico da comunicare
# al cliente per ciascuna coppia, con l'istruzione dedicata aggiunta in
# SYSTEM_PROMPT_MASTER.md §LOGICA SPAZIALE. Stesso principio di design già
# seguito in tutto il resto del prototipo: non hardcodiamo regole di
# business per ogni caso specifico, diamo a Claude i dati reali e le
# istruzioni per ragionarci sopra.
DISTANCE_MATRIX_MODES = ("driving", "walking")


def build_points(hotels: list[Hotel], pois: list[POI], max_poi: int = MAX_POI_POINTS) -> list[dict]:
    """[4.0] Hard-cap enforced qui: 1 hotel-ancora + slice(poi, 0, max_poi).

    [AGGIORNATO 2026-08-01] `max_poi` è ora un parametro, con default identico
    al valore storico (nessun cambiamento per chi non lo passa). Serve a
    `plan_matrix()` qui sotto, che decide quanti punti valga la pena misurare
    A PARITÀ DI ELEMENTI FATTURATI."""
    points = []
    for h in hotels[:1]:
        points.append({"id": h.id, "coord": h.coord})
    for p in pois[:max_poi]:
        points.append({"id": p.id, "coord": p.coord})
    return points


# ---------------------------------------------- budget di elementi e modalità
# [AGGIUNTO 2026-08-01 — collaudo del PDF reale]
#
# Google fattura questa API a ELEMENTI (origini × destinazioni), non a
# chiamata. Oggi spendiamo esattamente 200 elementi a itinerario: 10 punti ×
# 10 punti × 2 modalità. Quei 200 elementi sono un budget, e finora lo
# spendevamo in un solo modo possibile senza mai chiederci se fosse il
# migliore.
#
# La domanda giusta è: in un centro storico dove tutto dista otto minuti a
# piedi, che cosa ci dice la matrice "in auto"? Niente. Anzi, peggio di
# niente: nel collaudo reale ha riempito il PDF di righe "circa 0 min in auto",
# che il cliente legge come un errore del prodotto — ed è il difetto 4.
#
# Quindi: se i punti stanno tutti dentro un raggio pedonale, chiediamo SOLO
# "walking" e reinvestiamo gli stessi 200 elementi in PIÙ PUNTI (14 invece di
# 10, perché 14² = 196 ≤ 200). Quattro tappe misurate in più al giorno sono
# esattamente ciò che mancava all'itinerario per non lasciare il cliente con
# quattro slot vuoti. Se invece i punti sono sparsi, "in auto" è
# un'informazione vera e la teniamo, restando a 10 punti.
#
# Costo invariato in entrambi i rami. Questa non è una spesa in più, è la
# stessa spesa messa dove serve.
DISTANCE_MATRIX_ELEMENT_BUDGET = 200

# Soglia oltre la quale un insieme di punti smette di essere "un posto dove si
# va a piedi". 2,5 km è la distanza massima fra due tappe qualsiasi, non la
# somma del percorso: entro quella soglia qualunque coppia di punti è
# raggiungibile a piedi in circa mezz'ora.
COMPACT_SPREAD_M = 2500

_EARTH_RADIUS_M = 6371000.0


def _parse_coord(coord: str) -> tuple[float, float] | None:
    try:
        lat_s, lng_s = str(coord).split(",")
        return float(lat_s), float(lng_s)
    except (ValueError, AttributeError):
        return None


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def haversine_metres(a, b) -> int | None:
    """Distanza in linea d'aria fra due coordinate, in metri interi, oppure
    `None` se una delle due non è leggibile.

    [AGGIUNTO 2026-08-03 — "totale di chilometri/percorrenze a piedi"]
    Wrapper PUBBLICO e tollerante su `_haversine_m` (che pretende due tuple di
    float già validate e solleva sui dati sporchi). Esiste perché il ripiego
    della sezione "come arrivare" — quando Google non ci ha dato la distanza di
    una tratta — deve poter chiedere una stima senza dover ripetere qui la
    formula né il raggio terrestre: una sola implementazione, un solo posto in
    cui può essere sbagliata.

    ATTENZIONE a chi la usa: il risultato è una DISTANZA IN LINEA D'ARIA, non
    un percorso. Va sempre dichiarata come tale al cliente (vedi
    `directions.format_metres_it(..., is_estimate=True)`), mai stampata come
    se fosse una misura di Google.
    """
    ca, cb = _coord_pair(a), _coord_pair(b)
    if ca is None or cb is None:
        return None
    try:
        metres = _haversine_m(ca, cb)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(metres) or metres < 0:
        return None
    return int(round(metres))


def _coord_pair(value) -> tuple[float, float] | None:
    """`(lat, lng)` da una tupla/lista o da una stringa `"lat,lng"`; `None` se
    il valore non è una coppia di numeri finiti."""
    if isinstance(value, str):
        parsed = _parse_coord(value)
        if parsed is None:
            return None
        lat, lng = parsed
    else:
        try:
            lat, lng = float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    return lat, lng


def max_pairwise_spread_m(points: list[dict]) -> float:
    """Distanza in linea d'aria fra i due punti più lontani. Funzione pura.

    0.0 se i punti sono meno di due o se nessuna coppia ha coordinate
    leggibili — caso in cui `plan_matrix` sceglie prudentemente il ramo
    conservativo (entrambe le modalità), perché "non lo so" non deve mai
    diventare "allora è compatto"."""
    coords = [c for c in (_parse_coord(p.get("coord", "")) for p in points) if c]
    if len(coords) < 2:
        return 0.0
    return max(
        _haversine_m(coords[i], coords[j])
        for i in range(len(coords))
        for j in range(i + 1, len(coords))
    )


def plan_matrix(
    points: list[dict],
    element_budget: int = DISTANCE_MATRIX_ELEMENT_BUDGET,
    compact_spread_m: float = COMPACT_SPREAD_M,
) -> tuple[list[dict], tuple[str, ...]]:
    """Decide quanti punti misurare e in quali modalità, dentro il budget di
    elementi. Restituisce `(punti_troncati, modalità)`. Funzione pura.

    Vedi la nota estesa qui sopra per il ragionamento. In sintesi: destinazione
    compatta → solo "walking", più punti; destinazione sparsa → entrambe le
    modalità, meno punti. In entrambi i casi il numero di elementi fatturati
    resta sotto `element_budget`.
    """
    if len(points) < 2:
        return list(points), DISTANCE_MATRIX_MODES
    spread = max_pairwise_spread_m(points)
    compact = 0.0 < spread <= compact_spread_m
    modes = ("walking",) if compact else DISTANCE_MATRIX_MODES
    max_points = int(math.isqrt(max(1, element_budget // len(modes))))
    return list(points[:max_points]), modes


# ------------------------------------------------------- distanza per tratta
# [AGGIUNTO 2026-08-03 — richiesta di Lorenzo: "inserire nel programma del
# giorno il totale di chilometri/percorrenze a piedi"]
#
# I chilometri NON costano una chiamata in più. Ogni elemento con
# `status: "OK"` della Distance Matrix contiene GIÀ, nella stessa risposta da
# cui leggiamo `duration`, anche `distance: {"value": <metri>, "text": "1,8 km"}`
# — è il formato documentato dell'API, non un extra da richiedere, e `units`
# è già impostato a "metric" in `fetch_distance_matrix_raw`. Finora quel campo
# arrivava e veniva buttato via, esattamente come `rating` di Places prima del
# collaudo del 2026-08-01.
#
# Questo è importante quanto la funzionalità: la Distance Matrix è la voce più
# cara del prodotto (~61% del costo reale per itinerario). Aggiungere una
# seconda chiamata — o peggio la Directions API — per un dato che è già nella
# risposta pagata avrebbe fatto salire il costo variabile senza portare un solo
# byte di informazione nuova.
#
# Usiamo `distance.value` (metri, numerico) e NON `distance.text`, che è una
# stringa già formattata da Google secondo `language`/`units` e quindi non
# sommabile: i totali di giornata hanno bisogno di numeri.
#
# NOTA SULLA SERIALIZZAZIONE — leggere prima di "sistemare" questo punto.
# `metres` viene appeso alle istanze `TravelTime` come ATTRIBUTO, non come
# campo della dataclass. È deliberato: `TravelTime.to_dict()` usa `asdict()`,
# che serializza solo i campi dichiarati, e quel dizionario viaggia dentro
# DS_PAYLOAD_API fino a `service.py`, che lo ricostruisce con `TravelTime(**t)`.
# Una chiave in più sul filo diventerebbe un `TypeError` su un argomento
# inatteso, cioè un HTTP 400 su /v1/pdf per ogni itinerario. Finché `metres`
# non è un campo vero di `schemas.TravelTime`, la distanza reale di Google
# sopravvive solo nel percorso in-process (run_live, generazione PDF diretta);
# dopo un giro sul filo la sezione "come arrivare" ripiega sulla stima in linea
# d'aria, DICHIARANDOLA. Vedi src/directions.py.
TRAVEL_TIME_METRES_ATTR = "metres"


def element_distance_metres(element) -> int | None:
    """Metri percorsi secondo Google per un singolo elemento della matrice.

    `None` — mai 0 — quando il dato non c'è, non è numerico o è assurdo
    (negativo, NaN, infinito, `True`): "non lo so" e "zero metri" sono due
    affermazioni diverse e il PDF non deve poterle confondere.

    Difende dagli stessi casi già visti dal vivo su `duration`: campo presente
    ma `null` (per cui `.get("distance", {})` non basta e serve `or {}`), e
    valori di tipo inatteso da una risposta parziale.
    """
    if not isinstance(element, dict):
        return None
    value = (element.get("distance") or {}).get("value")
    return coerce_metres(value)


def coerce_metres(value) -> int | None:
    """Un numero di metri utilizzabile, oppure `None`.

    `bool` è escluso esplicitamente: in Python `True` è un `int` di valore 1, e
    senza questo controllo un `True` finito nei dati diventerebbe "1 metro" —
    un numero inventato che si somma agli altri e sporca il totale di giornata.
    Stesso controllo già presente in `directions.compute_departure_time`.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(round(value))


def map_distance_matrix_response(data: dict, points: list[dict], mode: str = "driving") -> list[TravelTime]:
    """Funzione pura — mapping [4.4]. Scarta diagonale e status != OK.

    [AGGIORNATO 2026-07-11] `mode` ora è un parametro (prima hardcoded
    "driving" qui dentro) — necessario per poter taggare correttamente le
    entry ottenute da una chiamata mode="walking" (vedi
    get_distance_matrix_multi_mode sotto). Default "driving" per
    compatibilità con chi chiama questa funzione pura direttamente (es. i
    test esistenti) senza passare `mode`.
    """
    travel_times = []
    rows = data.get("rows", [])
    for i, row in enumerate(rows):
        elements = row.get("elements", [])
        for j, element in enumerate(elements):
            if i == j:
                continue  # scarta diagonale punto->sé stesso
            if not isinstance(element, dict) or element.get("status") != "OK":
                continue
            # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale
            # eseguito] `element.get("duration", {}).get("value")` crashava se
            # il campo era presente ma null (`"duration": null`): il default
            # `{}` non copre il null. In modalità primaria "driving" un crash
            # qui fa fallire l'intero Nodo 4. `or {}` copre entrambi i casi.
            duration_in_traffic = (element.get("duration_in_traffic") or {}).get("value")
            duration = (element.get("duration") or {}).get("value")
            seconds = duration_in_traffic if duration_in_traffic is not None else duration
            if seconds is None:
                continue
            tt = TravelTime(
                origin_id=points[i]["id"],
                dest_id=points[j]["id"],
                minutes=round(seconds / 60),
                mode=mode,
            )
            # [AGGIUNTO 2026-08-03 — richiesta di Lorenzo: "inserire nel
            # programma del giorno il totale di chilometri"] I metri erano
            # gia' dentro questa risposta e finivano nel cestino. Vengono
            # appesi come ATTRIBUTO e non come campo: il perche' e' spiegato
            # per esteso nel commento sopra `TRAVEL_TIME_METRES_ATTR`, e
            # cambiarlo senza leggerlo rompe /v1/pdf per ogni itinerario.
            setattr(tt, TRAVEL_TIME_METRES_ATTR, element_distance_metres(element))
            travel_times.append(tt)
    return travel_times


def fetch_distance_matrix_raw(points: list[dict], api_key: str, mode: str = "driving") -> dict:
    """[ESTRATTO 2026-07-10] Isola la sola chiamata HTTP, senza mapping —
    stesso principio già applicato a LiteAPI (debug_liteapi_raw.py): non
    presuppone len(points) >= 2, quello resta responsabilità del chiamante
    (get_distance_matrix la applica prima di invocare questa funzione).

    [AGGIORNATO 2026-07-11] `mode` parametrizzato (era hardcoded
    "driving"). `departure_time`/`duration_in_traffic` hanno senso solo in
    modalità "driving" (traffico reale) — per "walking" Google li ignora,
    ma evitiamo di inviarli comunque per chiarezza della richiesta.

    [AGGIORNATO 2026-08-01] `departure_time` non viene più inviato per
    default nemmeno in "driving": vedi la nota su `traffic_enabled()` in
    testa al modulo (raddoppiava il costo per un dato riferito a oggi
    mentre il viaggio è fra settimane)."""
    coords = "|".join(p["coord"] for p in points)
    params = {
        "origins": coords,
        "destinations": coords,
        "mode": mode,
        "units": "metric",
        "language": "it",
        "key": api_key,
    }
    with_traffic = mode == "driving" and traffic_enabled()
    if with_traffic:
        params["departure_time"] = "now"
    # Google fattura la Distance Matrix a ELEMENTI (origini x destinazioni),
    # non a chiamata: qui la matrice e' quadrata sugli stessi punti. La voce
    # cambia se la richiesta porta il traffico, perche' cambia lo SKU e con
    # esso il prezzo per elemento (5 $/1000 contro 10 $/1000).
    cost_telemetry.record_api_call(
        "google_distance_matrix_advanced" if with_traffic else "google_distance_matrix",
        units=len(points) ** 2,
    )
    resp = requests.get(DISTANCE_MATRIX_URL, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_distance_matrix(points: list[dict], api_key: str, mode: str = "driving") -> list[TravelTime]:
    if len(points) < 2:
        return []  # matrice non ha senso con < 2 punti
    data = fetch_distance_matrix_raw(points, api_key, mode=mode)
    if data.get("status") != "OK":
        raise RuntimeError(
            f"Distance Matrix fallita (mode={mode}): status={data.get('status')} "
            f"(error handler: 3 retry backoff, poi email scuse + Stripe refund)"
        )
    return map_distance_matrix_response(data, points, mode=mode)


def get_distance_matrix_multi_mode(
    points: list[dict], api_key: str, modes: tuple[str, ...] = DISTANCE_MATRIX_MODES,
) -> list[TravelTime]:
    """[AGGIUNTO 2026-07-11 — capstone live test] Interroga la Distance
    Matrix in più modalità (default: driving + walking) e restituisce
    l'unione delle entry, ciascuna taggata col proprio `mode` — Claude
    riceve entrambi i tempi per la stessa coppia di punti e sceglie quale
    comunicare (vedi SYSTEM_PROMPT_MASTER.md §LOGICA SPAZIALE).

    La PRIMA modalità in `modes` (default "driving") è quella
    primaria/storica: un suo fallimento propaga normalmente, coerente con
    run_live() che lo intercetta già come data_layer_error. Un fallimento
    di una modalità successiva (es. "walking" non disponibile per quella
    coppia di coordinate, o un errore transitorio) NON deve far fallire
    l'intero Nodo 4 — stesso principio di resilienza già applicato a un
    singolo place/hotel malformato altrove nel prototipo (places_client.py,
    liteapi_client.py): meglio un arricchimento parziale che nessun
    risultato. NOTA: la primarietà è determinata dalla POSIZIONE in
    `modes`, non dal nome "driving" — chi passa un `modes` custom con un
    ordine diverso da quello di default sposta anche quale modalità è
    "primaria". Non cambiare l'ordine di DISTANCE_MATRIX_MODES senza
    aggiornare anche questa nota.

    [CORRETTO 2026-07-11 — audit di qualità, trovato da un secondo giro di
    revisione dopo il capstone test] Prima, il `try/except` sulle modalità
    non primarie catturava SOLO `RuntimeError` (il solo caso "status !=
    OK" di Google) — ma un fallimento HTTP reale e plausibile (timeout,
    errore 5xx, blip di rete) su `fetch_distance_matrix_raw()` solleva
    `requests.exceptions.RequestException`, non `RuntimeError`. Un
    fallimento transitorio della sola modalità "walking" propagava quindi
    fuori da questa funzione fino a `run_live()`, che lo intercetta sì, ma
    come un `data_layer_error` che butta via ANCHE i risultati "driving"
    già ottenuti con successo — esattamente il comportamento che questa
    funzione dichiara (nel suo stesso docstring) di NON dover avere per le
    modalità non primarie. Corretto catturando entrambi i tipi di eccezione."""
    if len(points) < 2:
        return []
    combined: list[TravelTime] = []
    for i, mode in enumerate(modes):
        if i == 0:
            combined.extend(get_distance_matrix(points, api_key, mode=mode))
        else:
            try:
                combined.extend(get_distance_matrix(points, api_key, mode=mode))
            except (RuntimeError, requests.exceptions.RequestException) as e:
                print(f"⚠️  Distance Matrix modalità '{mode}' non disponibile, proseguo solo con le altre: {e}")
    return combined
