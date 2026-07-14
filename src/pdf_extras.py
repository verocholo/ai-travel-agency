"""
src/pdf_extras.py — logica di costruzione dei contenuti "post-consegna" per
il PDF cliente (guide turistiche per-POI, feedback post-viaggio, POI
effettivamente usati, cartina).

[AGGIUNTO 2026-07-14 — preparativi Make.com] Prima questa funzione viveva
SOLO in `main.py` (CLI), come `_build_pdf_extras()`. Il nuovo endpoint HTTP
`POST /v1/pdf` in `service.py` (Nodo 10A per Make.com) ha bisogno della
STESSA identica logica — mai due implementazioni parallele che rischiano di
disallinearsi (stesso principio anti-desync già applicato più volte in
questo progetto, es. `_SHOPPING_TYPES` importato da `places_client.py` in
`modules.py` invece di essere riscritto). `service.py` non può importare
`main.py` direttamente: `main.py` è l'entrypoint CLI (argparse, `sys.exit`),
non un modulo pensato per essere importato da un servizio HTTP a lunga vita.
Questa funzione è quindi stata spostata qui, in `src/`, e sia `main.py` sia
`service.py` la importano da qui. `main.py` mantiene `_build_pdf_extras`
come alias locale (stesso nome di prima) per non rompere i test esistenti
che lo richiamano come `main._build_pdf_extras(...)`.
"""
from __future__ import annotations

from src import guide_generator
from src import feedback_generator
from src import maps_static
from src.modules import get_module_for_objective_function


def build_pdf_extras(
    itinerary: dict, trip, api_payload, api_key: str, google_maps_key: str | None = None,
    include_guides: bool = True, include_feedback: bool = True, include_map: bool = True,
) -> tuple[list[dict], dict | None, list[dict], bytes | None]:
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "ok ora prima di fare il
    resto fai in modo di aggiungerli al pdf che si genera", chiarita con
    "Voglio tutti e tre nello stesso PDF"] Genera i contenuti
    "post-consegna" — guide turistiche per i POI EFFETTIVAMENTE USATI
    nell'itinerario (stesso pattern di estrazione di
    freshness_check.run_freshness_check(): `poi_id` nei blocks, non
    l'intero DATI_API_FORNITI, che può contenere candidati mai scelti da
    Claude) più il messaggio di feedback post-viaggio — da incorporare
    nello stesso PDF cliente invece che come file .md separati generati
    da comandi CLI distinti (--guide/--feedback), come accadeva prima di
    questa modifica.

    Stesso principio "degrada senza rompere il resto" già applicato altrove
    in questo prototipo (es. wkhtmltopdf assente non fa fallire l'intero
    run): se la guida per UN singolo POI fallisce (rete, parsing, campo
    mancante), quel POI viene semplicemente saltato con un avviso — non fa
    fallire gli altri POI, né il feedback, né la generazione del PDF nel
    suo complesso. Stesso principio per il feedback: se fallisce, il PDF
    viene comunque generato senza quella sezione.

    [AGGIUNTI 2026-07-12 — richiesta di Lorenzo: "ristoranti"/"hotel"/
    "intrattenimento" curati, "cartina + percorsi"] Ritorna anche
    `used_pois` (i dict dei POI EFFETTIVAMENTE usati, per le sezioni
    curate "Dove mangiare"/"Cosa fare" — stessa estrazione di
    `extract_used_poi_ids()`, un solo posto dove questa logica vive, non
    duplicata come prima di questa modifica) e `map_png_bytes` (la
    cartina, `None` se `google_maps_key` non è configurata o se la
    generazione fallisce — mai un'eccezione, vedi
    `maps_static.build_map_for_itinerary()`).

    [AGGIUNTI 2026-07-14 — preparativi Make.com] `include_guides`/
    `include_feedback`/`include_map` (tutti `True` di default, quindi
    nessuna rottura per `main.py`, che non li passa mai esplicitamente):
    permettono al chiamante di saltare interamente una sezione — usato da
    `POST /v1/pdf` in `service.py`, dove il cliente Make.com può scegliere
    un PDF più leggero/veloce (es. senza guide, che richiedono una
    chiamata Claude per POI) senza dover post-processare l'output.
    """
    # Import locale (non in cima al modulo) per evitare un ciclo di import:
    # `itinerary_utils` non dipende da questo modulo, ma tenerlo qui rende
    # esplicito che è usato solo da questa funzione, stesso stile del resto
    # del file.
    from src.itinerary_utils import extract_used_poi_ids

    used_poi_ids = extract_used_poi_ids(itinerary)
    poi_by_id = {p.id: p for p in api_payload.poi} if api_payload else {}
    module = get_module_for_objective_function(trip.objective_function)

    guides = []
    if include_guides:
        for poi_id in sorted(used_poi_ids):
            poi = poi_by_id.get(poi_id)
            if poi is None:
                # Difensivo: non dovrebbe succedere se il Nodo 9 (Fedeltà RAG)
                # ha già validato l'itinerario — stesso caso difensivo già
                # presente in freshness_check.run_freshness_check().
                continue
            try:
                guide = guide_generator.generate_poi_guide(
                    poi.name, trip.destination, api_key=api_key,
                    objective_function=trip.objective_function, module_id=module.id,
                )
                guides.append(guide)
            except guide_generator.GuideGeneratorError:
                # Il chiamante (CLI o servizio HTTP) decide come loggare
                # l'avviso — questa funzione resta silenziosa sull'I/O, non
                # presuppone una console disponibile (il servizio HTTP usa
                # app.logger, non print()).
                pass

    feedback = None
    if include_feedback:
        try:
            feedback = feedback_generator.generate_post_trip_feedback(
                itinerary, api_key=api_key, objective_function=trip.objective_function,
            )
        except feedback_generator.FeedbackGeneratorError:
            pass

    used_pois = [poi_by_id[pid].to_dict() for pid in sorted(used_poi_ids) if pid in poi_by_id]

    map_png_bytes = None
    if include_map:
        map_png_bytes = maps_static.build_map_for_itinerary(
            api_payload.hotels if api_payload else [],
            api_payload.poi if api_payload else [],
            itinerary,
            google_maps_key,
        )

    return guides, feedback, used_pois, map_png_bytes
