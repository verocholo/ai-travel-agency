"""
NODO 4 — Google Distance Matrix. HTTP_MODULES_REALI.md §NODO 4 ("FINALIZZATO",
poi esteso 2026-07-11 — vedi nota multi-mode più sotto).
Decisione (Lorenzo): matrice piena N×N, hard-cap 10 punti (1 hotel + max 9 POI).
"""
from __future__ import annotations
import requests
from .schemas import Hotel, POI, TravelTime

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

MAX_POI_POINTS = 9  # cintura di sicurezza ridondante col cap lato Places (maxResultCount)

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


def build_points(hotels: list[Hotel], pois: list[POI]) -> list[dict]:
    """[4.0] Hard-cap enforced qui: 1 hotel-ancora + slice(poi, 0, 9)."""
    points = []
    for h in hotels[:1]:
        points.append({"id": h.id, "coord": h.coord})
    for p in pois[:MAX_POI_POINTS]:
        points.append({"id": p.id, "coord": p.coord})
    return points


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
            if element.get("status") != "OK":
                continue
            duration_in_traffic = element.get("duration_in_traffic", {}).get("value")
            duration = element.get("duration", {}).get("value")
            seconds = duration_in_traffic if duration_in_traffic is not None else duration
            if seconds is None:
                continue
            travel_times.append(
                TravelTime(
                    origin_id=points[i]["id"],
                    dest_id=points[j]["id"],
                    minutes=round(seconds / 60),
                    mode=mode,
                )
            )
    return travel_times


def fetch_distance_matrix_raw(points: list[dict], api_key: str, mode: str = "driving") -> dict:
    """[ESTRATTO 2026-07-10] Isola la sola chiamata HTTP, senza mapping —
    stesso principio già applicato a LiteAPI (debug_liteapi_raw.py): non
    presuppone len(points) >= 2, quello resta responsabilità del chiamante
    (get_distance_matrix la applica prima di invocare questa funzione).

    [AGGIORNATO 2026-07-11] `mode` parametrizzato (era hardcoded
    "driving"). `departure_time`/`duration_in_traffic` hanno senso solo in
    modalità "driving" (traffico reale) — per "walking" Google li ignora,
    ma evitiamo di inviarli comunque per chiarezza della richiesta."""
    coords = "|".join(p["coord"] for p in points)
    params = {
        "origins": coords,
        "destinations": coords,
        "mode": mode,
        "units": "metric",
        "language": "it",
        "key": api_key,
    }
    if mode == "driving":
        params["departure_time"] = "now"
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
