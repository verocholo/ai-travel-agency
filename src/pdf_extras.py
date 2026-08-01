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
from src import directions as directions_mod
from src import cost_estimator
from src import place_links
from src import tips_generator
from src import feedback_link as feedback_link_mod
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
                # [AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "reindirizzi il
                # cliente alla fine del pdf ... portandolo DIRETTAMENTE
                # sull'attrazione richiesta"] È l'unico anello che lega la
                # guida al blocco del giorno-per-giorno da cui parte il link:
                # `render_html()` costruisce l'ancora HTML da questo campo. Il
                # nome del POI non basta come chiave (due "Duomo" nello stesso
                # viaggio esistono davvero), l'id sì.
                guide["poi_id"] = poi_id
                guides.append(guide)
            except Exception:
                # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale
                # eseguito] Prima si catturava SOLO GuideGeneratorError, ma
                # `generate_poi_guide` NON avvolge la chiamata API in try/except:
                # un errore di RETE/API (APIConnectionError, RateLimitError,
                # Timeout) si propagava come eccezione diversa e faceva fallire
                # l'INTERO PDF — contraddicendo il docstring, che promette di
                # saltare il singolo POI proprio su "rete, parsing, campo
                # mancante". `except Exception` rende la sezione davvero
                # best-effort: una guida che fallisce viene saltata, il PDF esce.
                # Il chiamante decide come loggare (questa funzione resta muta
                # sull'I/O: il servizio HTTP usa app.logger, non print()).
                pass

    feedback = None
    if include_feedback:
        try:
            feedback = feedback_generator.generate_post_trip_feedback(
                itinerary, api_key=api_key, objective_function=trip.objective_function,
            )
        except Exception:
            # Stesso motivo della guida sopra: un errore di rete/API non deve
            # far fallire l'intero PDF, la sezione feedback è best-effort.
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


def build_pdf_sections(
    itinerary: dict,
    trip,
    api_payload,
    api_key: str | None = None,
    google_maps_key: str | None = None,
    travellers: int = 1,
    include_day_maps: bool = True,
    include_directions: bool = True,
    include_costs: bool = True,
    include_tips: bool = True,
    include_place_links: bool = True,
    include_feedback_link: bool = True,
) -> dict:
    """
    [AGGIUNTO 2026-07-31 — richieste di Lorenzo del 2026-07-31: cartine per
    giornata numerate, "cartina e come arrivare", "stima dei costi e dettaglio
    budget", Architect's Tips per direttrici, "piani b se piove", menù e info
    dei ristoranti]

    Costruisce in UN SOLO POSTO le cinque nuove sezioni del PDF e le ritorna
    come dizionario pronto da passare a `pdf_renderer.render_pdf(**sections)`.

    Perché una funzione nuova e non altri valori di ritorno di
    `build_pdf_extras()`: quella ritorna una 4-tupla posizionale usata da
    `main.py`, da `service.py` e da una dozzina di test. Allargarla a nove
    elementi posizionali significa rompere ogni chiamante per un guadagno
    nullo — e ogni elemento aggiunto in futuro lo romperebbe di nuovo. Qui
    ritorniamo un dict, che cresce senza rompere niente.

    Ordine delle dipendenze (non è arbitrario):
      1. i piani-giornata delle cartine numerate,
      2. da quelli le tratte "come arrivare" — così i numeri stampati accanto
         a ogni spostamento sono ESATTAMENTE i numeri disegnati sulla cartina,
      3. la stima dei costi,
      4. i consigli, che ricevono la stima come fatto verificato (un consiglio
         di risparmio deve conoscere il totale, altrimenti è aria fritta).

    Ogni sezione è best-effort e indipendente dalle altre, come guide e
    feedback in `build_pdf_extras()`: una chiave API scaduta costa al cliente
    quella sezione, mai il documento.
    """
    from src.itinerary_utils import extract_used_poi_ids

    hotels = list(api_payload.hotels) if api_payload else []
    pois = list(api_payload.poi) if api_payload else []
    travel_times = getattr(api_payload, "travel_times", None) if api_payload else None
    module = get_module_for_objective_function(trip.objective_function)

    sections: dict = {
        "day_maps": [], "directions": [], "cost_summary": None,
        "tips": None, "place_cards": {}, "feedback_link": None,
    }

    # [AGGIUNTO 2026-08-01 — punto 6 del feedback "da investitore": la sezione
    # recensione fa domande bellissime e non offre nessun posto dove
    # rispondere] Non costa una chiamata di rete ne' una chiamata al modello:
    # e' solo un codice opaco piu' una URL letta dall'ambiente. Se
    # FEEDBACK_FORM_URL non e' impostata resta il solo `ref` (utile comunque a
    # Make per archiviare la consegna) e il PDF non mostra nessun link morto.
    if include_feedback_link:
        try:
            ref, url = feedback_link_mod.build_feedback_link(trip)
            sections["feedback_link"] = {
                "ref": ref,
                "url": url,
                "core_questions": feedback_link_mod.CORE_QUESTIONS if url else [],
            }
        except Exception:  # noqa: BLE001 — best-effort come ogni altra sezione
            sections["feedback_link"] = None

    # I piani servono sia alle cartine sia alle tratte: calcolati una volta.
    try:
        day_plans = maps_static.build_day_map_plans(hotels, pois, itinerary)
    except Exception:
        day_plans = []

    if include_day_maps:
        try:
            sections["day_maps"] = maps_static.build_day_maps_for_itinerary(
                hotels, pois, itinerary, google_maps_key,
            )
        except Exception:
            sections["day_maps"] = []

    if include_directions:
        try:
            sections["directions"] = directions_mod.build_directions_by_day(
                day_plans, travel_times,
            )
        except Exception:
            sections["directions"] = []

    if include_costs:
        try:
            sections["cost_summary"] = cost_estimator.estimate_costs(
                itinerary, trip, hotels, pois, travellers=travellers,
            )
        except Exception:
            sections["cost_summary"] = None

    if include_place_links:
        try:
            sections["place_cards"] = place_links.build_place_cards_by_id(
                pois, only_ids=extract_used_poi_ids(itinerary),
            )
        except Exception:
            sections["place_cards"] = {}

    if include_tips and api_key:
        try:
            sections["tips"] = tips_generator.generate_architect_tips(
                trip, itinerary, api_key=api_key, hotels=hotels, pois=pois,
                cost_summary=sections["cost_summary"],
                objective_function=trip.objective_function, module_id=module.id,
            )
        except Exception:
            # Il ripiego non è "nessun consiglio": `render_html()` ristampa la
            # vecchia lista piatta `itinerary["architect_tips"]` quando questa
            # è None. Meglio sei consigli generici che una sezione vuota.
            sections["tips"] = None

    return sections
