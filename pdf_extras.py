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

import os

from src import guide_generator
from src import feedback_generator
from src import maps_static
from src import map_render
from src import directions as directions_mod
from src import cost_estimator
from src import place_links
from src import tips_generator
from src import feedback_link as feedback_link_mod
from src import predeparture as predeparture_mod
from src import vademecum as vademecum_mod
from src import checklist_xlsx as checklist_xlsx_mod
from src import fascicolo
from src import hosting
from src import poi_pdf
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
        # [RISCRITTO 2026-08-01 — perché nel PDF venduto davvero la sezione
        # "Guide turistiche tascabili" NON ESISTEVA]
        #
        # Tutta l'impalcatura c'era: le ancore, i link interni per blocco, il
        # capitolo in fondo, la voce nell'indice. Mancava il contenuto, e il
        # motivo è aritmetico, non logico. Questo ciclo faceva UNA chiamata a
        # Claude PER LUOGO, in sequenza. Con tredici luoghi in programma e
        # 12-25 secondi a guida sono 2,5-5 minuti di solo tempo di attesa,
        # dentro uno scenario Make.com che sul piano Free viene ucciso a 300
        # secondi — e a valle c'erano ancora la stima dei costi, i consigli e
        # il rendering. Le guide erano la coda della coda: o non partivano, o
        # venivano troncate insieme a tutto il resto.
        #
        # Le chiamate sono INDIPENDENTI fra loro: nessuna guida ha bisogno di
        # un'altra guida. Eseguirle in sequenza non era una scelta, era
        # un'omissione. In parallelo il tempo totale diventa quello della più
        # lenta (~20 s) invece della somma (~5 min).
        #
        # Perché parallelo e NON una singola chiamata che le genera tutte,
        # che pure sarebbe più economica in token: (a) un unico JSON con
        # tredici guide dentro è esattamente la forma che si fa troncare, e
        # un troncamento le perderebbe TUTTE invece di una; (b) si perde
        # l'isolamento dei fallimenti, che è la proprietà per cui questa
        # sezione è best-effort; (c) la qualità per guida cala, perché il
        # modello divide l'attenzione fra tredici luoghi nello stesso turno —
        # ed è precisamente l'errore che `tips_generator` esiste per non
        # ripetere. Il costo in token resta identico: si paga il testo
        # generato, non il modo in cui lo si chiede.
        #
        # `max_workers` è tenuto basso di proposito: il collo di bottiglia è
        # il rate limit di Anthropic, non la CPU, e sei chiamate insieme
        # bastano a portare tredici guide sotto il minuto.
        import contextvars
        from concurrent.futures import ThreadPoolExecutor

        # [RISCRITTO 2026-08-02 — richiesta di Lorenzo: «deve esserci una guida
        # per ogni cosa che lo richieda»]
        #
        # Qui c'era `sorted(used_poi_ids)`: una guida per ogni POI con un id di
        # Google, in ordine alfabetico di id. Due difetti in una riga.
        #
        # Il primo è di copertura: un programma vero è pieno di tappe che NON
        # hanno un id di Google — "mattinata nel quartiere di Alfama", "salita
        # al belvedere", "giro al mercato" — ed erano esattamente quelle su cui
        # il cliente avrebbe voluto leggere qualcosa. Restavano mute.
        #
        # Il secondo è di ordine: `sorted()` su un id di Google ordina per una
        # stringa opaca. Il capitolo delle guide usciva in un ordine che non
        # corrispondeva a niente di percepibile — né al programma, né
        # all'alfabeto dei nomi.
        #
        # La regola di selezione vive ora in `guide_generator.select_guide_
        # targets()`, che è pura e ha i suoi test: qui resta solo l'esecuzione.
        targets = guide_generator.select_guide_targets(itinerary, poi_by_id)

        def _one_guide(item):
            try:
                guide = guide_generator.generate_poi_guide(
                    item["name"], trip.destination, api_key=api_key,
                    objective_function=trip.objective_function, module_id=module.id,
                    kind=item["kind"],
                )
                # [AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "reindirizzi il
                # cliente alla fine del pdf ... portandolo DIRETTAMENTE
                # sull'attrazione richiesta"] È l'unico anello che lega la
                # guida al blocco del giorno-per-giorno da cui parte il link:
                # `render_html()` costruisce l'ancora HTML da questo campo. Il
                # nome del POI non basta come chiave (due "Duomo" nello stesso
                # viaggio esistono davvero), l'id sì.
                guide["poi_id"] = item["poi_id"] or item["key"]
                return guide
            except guide_generator.GuideSkipped as e:
                # [AGGIUNTO 2026-08-02] Non è un guasto: il modello ha
                # dichiarato di non riconoscere un luogo reale dietro una riga
                # del programma, ed è la ragione per cui possiamo permetterci
                # di essere generosi con i candidati. Si stampa in modo
                # DIVERSO da un errore, altrimenti fra un mese nessuno saprà
                # più distinguere "tre righe non erano luoghi" da "tre guide
                # perse per un timeout".
                print(f"·  nessuna guida per '{item['name'][:80]}' — {e}")
                return None
            except Exception as e:
                # [AGGIORNATO 2026-07-31 — audit di perfezionamento, bug reale
                # eseguito] Prima si catturava SOLO GuideGeneratorError, ma
                # `generate_poi_guide` NON avvolge la chiamata API in try/except:
                # un errore di RETE/API (APIConnectionError, RateLimitError,
                # Timeout) si propagava come eccezione diversa e faceva fallire
                # l'INTERO PDF — contraddicendo il docstring, che promette di
                # saltare il singolo POI proprio su "rete, parsing, campo
                # mancante". `except Exception` rende la sezione davvero
                # best-effort: una guida che fallisce viene saltata, il PDF esce.
                #
                # [AGGIORNATO 2026-08-01] `pass` nudo, però, era troppo muto:
                # tredici guide fallite e zero guide riuscite producevano
                # esattamente lo stesso PDF di `include_guides=False`, e non
                # c'era modo di distinguere le due cose né dal documento né
                # dai log. Ora la riga c'è. Resta best-effort: si stampa, non
                # si solleva.
                print(
                    f"⚠️  guida non generata per '{item['name'][:80]}' — "
                    f"{type(e).__name__}: {str(e)[:300]}"
                )
                return None

        # [AGGIUNTO 2026-08-01 — regressione introdotta dalla
        # parallelizzazione qui sopra, trovata da un test prima che uscisse.]
        #
        # `cost_telemetry` tiene il `Ledger` in una `ContextVar`, e i thread
        # creati da `ThreadPoolExecutor` NON ereditano il contesto di chi li
        # avvia: dentro il worker `_CURRENT.get()` torna `None` e
        # `record_llm()` diventa un no-op muto. Nessun errore, nessun
        # fallimento — semplicemente il costo delle guide (una chiamata a
        # Claude PER LUOGO, cioè la voce che moltiplica il costo di un
        # itinerario) sparisce dal conto e il margine dichiarato diventa più
        # roseo del vero. È esattamente la perdita silenziosa che
        # `cost_telemetry` esiste per impedire, riprodotta dal modulo che lo
        # usa: la si scoprirebbe confrontando il preventivo con la fattura di
        # Anthropic a fine mese.
        #
        # Le copie si fanno QUI, nel thread chiamante, e UNA PER TASK:
        #   - qui, perché `copy_context()` copia il contesto di CHI LA CHIAMA,
        #     e invocarla dentro il worker copierebbe il contesto (vuoto) del
        #     worker, cioè non risolverebbe niente (primo tentativo, fallito);
        #   - una per task, perché un singolo `Context` non può essere entrato
        #     da due thread contemporaneamente (`RuntimeError: cannot enter
        #     context ... already entered`).
        # Le copie condividono i VALORI: tutte vedono lo STESSO oggetto
        # `Ledger`, quindi i costi si sommano lì dentro. `list.append` è
        # atomica sotto il GIL — nessun lock necessario.
        jobs = [(contextvars.copy_context(), item) for item in targets]

        def _one_guide_in_context(job):
            ctx, item = job
            return ctx.run(_one_guide, item)

        if jobs:
            # [ALZATO 2026-08-02 da 6 a 8] I candidati sono aumentati (anche le
            # tappe senza scheda Google) e ogni guida è più lunga di circa il
            # settanta per cento: a parità di parallelismo il capitolo delle
            # guide sarebbe cresciuto di quasi un minuto, dentro un tetto di
            # 300 secondi che è già il rischio numero uno di questo prodotto.
            # Il collo di bottiglia resta il rate limit di Anthropic, non la
            # CPU: otto chiamate insieme lo reggono.
            with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
                # `map` conserva l'ordine di `jobs`, che segue `targets`,
                # cioè l'ORDINE DI VISITA: le guide escono deterministiche e
                # il capitolo in fondo scorre come il programma.
                guides = [
                    g for g in pool.map(_one_guide_in_context, jobs)
                    if g is not None
                ]

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
    include_predeparture: bool = True,
    include_vademecum: bool = True,
    include_checklist_sheet: bool = True,
    include_overview_map: bool = True,
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

    [AGGIUNTO 2026-08-01 — la parte sbagliata del best-effort]
    Degradare invece di fallire resta giusto. Degradare in SILENZIO no, e il
    prezzo l'ha pagato il primo cliente vero: `generate_architect_tips()`
    veniva troncata da un `max_tokens` troppo basso, sollevava correttamente
    l'eccezione, e qui sotto un `except Exception` nudo la trasformava in
    `tips = None` senza lasciare traccia da nessuna parte. Nel PDF sono
    comparsi tre consigli generici (il ripiego legacy) e nessuno — né io né
    Lorenzo né i log di Render — ha saputo che era successo qualcosa. Da oggi
    ogni sezione che cade lascia due tracce: una riga stampata (quindi nei log
    di Render, ricercabile) e una voce in `section_errors`, che i chiamanti
    passano ai contatori e all'allarme. Il documento continua a uscire: cambia
    solo che ora lo sappiamo.

    `section_errors` NON fa parte degli argomenti di `render_pdf()`: usare
    `split_render_kwargs()` per separarlo prima di fare `**`.
    """
    from src.itinerary_utils import extract_used_poi_ids

    hotels = list(api_payload.hotels) if api_payload else []
    pois = list(api_payload.poi) if api_payload else []
    travel_times = getattr(api_payload, "travel_times", None) if api_payload else None
    module = get_module_for_objective_function(trip.objective_function)

    sections: dict = {
        # [AGGIUNTO 2026-08-03] La cartina d'insieme. Prima nasceva in
        # `build_pdf_extras()` come semplici byte PNG: bastava a stamparla e non
        # bastava a nient'altro: non si sapeva dove fosse finito ogni pallino
        # (quindi niente link sopra) e senza chiave Google spariva del tutto.
        # Ora e' un piano come quelli per giornata, con la stessa rete di
        # sicurezza e la stessa geometria dei pallini.
        "overview_map": None,
        "day_maps": [], "directions": [], "cost_summary": None,
        "tips": None, "place_cards": {}, "feedback_link": None,
        "predeparture": None, "vademecum": None,
        "checklist_sheet": None,
        # Il file vero. NON e' un argomento del renderer: viaggia insieme alle
        # sezioni perche' chi genera il PDF e' anche chi lo spedisce, e farlo
        # ricostruire a valle significherebbe ricalcolarlo da capo.
        "checklist_xlsx": None,
    }
    section_errors: dict[str, str] = {}

    def _record(section: str, exc: Exception) -> None:
        """Una sezione è caduta. Non alza: annota e stampa.

        Il messaggio contiene il TIPO dell'eccezione oltre al testo, perché
        `TipsGeneratorError: troncato a max_tokens=6000` e
        `AuthenticationError: invalid x-api-key` richiedono due interventi
        completamente diversi e senza il tipo si confondono in un log.
        """
        detail = f"{type(exc).__name__}: {exc}"
        section_errors[section] = detail[:500]
        print(f"⚠️  pdf_extras: sezione '{section}' non generata — {detail[:500]}")

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
        except Exception as e:  # noqa: BLE001 — best-effort come ogni altra sezione
            _record("feedback_link", e)
            sections["feedback_link"] = None

    # I piani servono sia alle cartine sia alle tratte: calcolati una volta.
    try:
        day_plans = maps_static.build_day_map_plans(hotels, pois, itinerary)
    except Exception as e:
        _record("day_plans", e)
        day_plans = []

    if include_day_maps:
        try:
            day_maps = maps_static.build_day_maps_for_itinerary(
                hotels, pois, itinerary, google_maps_key,
            )
        except Exception as e:
            _record("day_maps", e)
            day_maps = []
        # Rete di sicurezza: se la costruzione delle cartine è caduta ma i piani
        # ci sono, si riparte da quelli — la legenda testuale non deve sparire
        # per un errore che riguarda solo l'immagine.
        if not day_maps and day_plans:
            day_maps = [
                {"day": p.get("day"), "title": p.get("title"), "png": None,
                 "stops": p.get("stops") or [], "hotel_point": p.get("hotel_point"),
                 "hotel_name": p.get("hotel_name"), "hotel_id": p.get("hotel_id")}
                for p in day_plans
            ]
        # Una cartina che dipende da UNA chiamata di rete non è una funzione del
        # prodotto, è una speranza: bastano chiave assente, quota esaurita o URL
        # troppo lungo perché il cliente riceva il documento senza. Qui si
        # disegna in locale ciò che manca, con le coordinate già in mano.
        try:
            sections["day_maps"] = map_render.attach_local_maps(day_maps)
        except Exception as e:
            _record("day_maps_local", e)
            sections["day_maps"] = day_maps

    if include_overview_map:
        try:
            piano = maps_static.build_overview_map(
                hotels, pois, itinerary, google_maps_key, day_plans=day_plans,
            )
        except Exception as e:
            _record("overview_map", e)
            piano = None
        if piano is not None:
            # Stessa strada delle cartine per giornata, di proposito: sfondo
            # stradale di Google se c'e', schema disegnato in casa se non c'e',
            # e in tutti e due i casi la geometria dei pallini. Passa dalla
            # stessa funzione perche' un secondo disegnatore vorrebbe dire due
            # legende che possono divergere.
            try:
                # `or []` e il controllo sulla lunghezza non sono paranoia:
                # `attach_local_maps()` scarta cio' che non riconosce, quindi
                # puo' restituire una lista vuota. Prendere `[0]` alla cieca
                # farebbe fallire la cartina d'insieme per un motivo — indice
                # fuori intervallo — che non dice niente a nessuno.
                risultato = map_render.attach_local_maps([piano]) or []
                sections["overview_map"] = risultato[0] if risultato else piano
            except Exception as e:
                _record("overview_map_local", e)
                sections["overview_map"] = piano

    if include_directions:
        try:
            sections["directions"] = directions_mod.build_directions_by_day(
                day_plans, travel_times,
            )
        except Exception as e:
            _record("directions", e)
            sections["directions"] = []

    if include_costs:
        try:
            sections["cost_summary"] = cost_estimator.estimate_costs(
                itinerary, trip, hotels, pois, travellers=travellers,
            )
        except Exception as e:
            _record("cost_summary", e)
            sections["cost_summary"] = None

    # [AGGIUNTO 2026-08-01] Nessuna chiave API, nessuna rete, nessun modello:
    # è una lettura di dati che abbiamo già in mano. Sta comunque dentro un
    # `try` come tutte le altre — non perché ci si aspetti che fallisca, ma
    # perché la regola "una sezione che cade non porta giù il documento" non
    # ammette eccezioni scelte a occhio.
    if include_predeparture:
        try:
            sections["predeparture"] = predeparture_mod.build_predeparture(
                trip, itinerary, hotels=hotels, pois=pois,
            )
        except Exception as e:
            _record("predeparture", e)
            sections["predeparture"] = None

    # [AGGIUNTO 2026-08-02 — task #167] Vademecum, valigia e bagagli.
    # Come `predeparture`: zero rete, zero token, zero latenza. È una scelta,
    # non una comodità — questa sezione deve poter esistere anche dentro il
    # tetto dei 300 secondi di Make, e una sezione che costa zero non può mai
    # essere la ragione per cui un documento non esce in tempo.
    if include_vademecum:
        try:
            sections["vademecum"] = vademecum_mod.build_vademecum(
                trip, itinerary, hotels=hotels, pois=pois, travellers=travellers,
            )
        except Exception as e:
            _record("vademecum", e)
            sections["vademecum"] = None

    # [AGGIUNTO 2026-08-02 — task #172/#173, richiesta di Lorenzo: "dopo
    # l'elenco vorrei che creassi un collegamento per un foglio di calcolo
    # google ... costruito in base a cio' che richiede la valigia"]
    #
    # Il foglio NON ha una sorgente propria: rilegge `vademecum` e
    # `predeparture` appena costruiti. E' il motivo per cui sta QUI e non in
    # un punto piu' comodo — deve venire dopo di loro, e se uno dei due e'
    # caduto il foglio esce piu' corto invece che sbagliato.
    if include_checklist_sheet:
        try:
            blob = checklist_xlsx_mod.build_checklist_xlsx(
                trip, sections.get("vademecum"), sections.get("predeparture"),
                itinerary, travellers=travellers,
            )
            if blob:
                filename = checklist_xlsx_mod.build_checklist_filename(trip)
                sections["checklist_xlsx"] = {"filename": filename, "content": blob}
                righe = len(checklist_xlsx_mod.build_checklist_rows(
                    trip, sections.get("vademecum"), sections.get("predeparture"),
                ))
                # Il "doppio binario" deciso con Lorenzo il 2026-08-02: finche'
                # `CHECKLIST_SHEET_TEMPLATE_URL` non e' configurato il riquadro
                # del PDF rimanda all'ALLEGATO; il giorno in cui lo sara',
                # rimandera' al foglio Google, senza toccare una riga di
                # codice. Un indirizzo vuoto o non http non entra: meglio
                # l'allegato di un collegamento che non apre niente.
                url = (os.getenv("CHECKLIST_SHEET_TEMPLATE_URL") or "").strip()
                if not url.startswith("https://"):
                    url = ""
                sections["checklist_sheet"] = {
                    "filename": filename, "rows": righe, "url": url,
                    "label": "Foglio della valigia (Fogli Google)" if url else "",
                }
        except Exception as e:
            _record("checklist_sheet", e)
            sections["checklist_sheet"] = None
            sections["checklist_xlsx"] = None

    if include_place_links:
        try:
            sections["place_cards"] = place_links.build_place_cards_by_id(
                pois, only_ids=extract_used_poi_ids(itinerary),
            )
        except Exception as e:
            _record("place_cards", e)
            sections["place_cards"] = {}

    if include_tips and api_key:
        try:
            sections["tips"] = tips_generator.generate_architect_tips(
                trip, itinerary, api_key=api_key, hotels=hotels, pois=pois,
                cost_summary=sections["cost_summary"],
                objective_function=trip.objective_function, module_id=module.id,
            )
        except Exception as e:
            # Il ripiego non è "nessun consiglio": `render_html()` ristampa la
            # vecchia lista piatta `itinerary["architect_tips"]` quando questa
            # è None. Meglio sei consigli generici che una sezione vuota — ma
            # ora il ripiego è RUMOROSO: è esattamente questo `except` che il
            # 2026-08-01 ha nascosto un troncamento da max_tokens e ha fatto
            # arrivare al primo cliente pagante tre righe di consigli generici
            # al posto di quattordici sezioni.
            _record("tips", e)
            sections["tips"] = None

    sections["section_errors"] = section_errors
    return sections


# Chiavi che `pdf_renderer.render_pdf()` accetta davvero. Tutto il resto che
# `build_pdf_sections()` restituisce è diagnostica per il chiamante e va tolto
# prima del `**`, altrimenti aggiungere una diagnostica romperebbe il
# rendering — che è il modo più stupido possibile di rompere il prodotto.
_RENDER_SECTION_KEYS = (
    "overview_map",
    "day_maps", "directions", "cost_summary", "tips", "place_cards",
    "feedback_link", "predeparture", "vademecum", "checklist_sheet",
    # [AGGIUNTO 2026-08-03 — task #178] Le URL delle guide pubblicate: e'
    # quello che trasforma un pallino della cartina in un collegamento a un
    # documento vero invece che a un capitolo interno.
    "guide_urls",
    # [AGGIUNTO 2026-08-03 — task #181] Le fotografie vere delle attrazioni.
    # Senza questa riga la chiave verrebbe costruita e poi buttata via dal
    # filtro a lista bianca due righe piu' sotto — in silenzio, che e' il
    # motivo per cui la lista bianca e' scritta a mano e non dedotta.
    "photos",
    # [AGGIUNTO 2026-08-05 — task #190/#192] I capitoli staccati da cucire
    # dentro lo stesso file e gli allegati da infilarci (il foglio della
    # valigia). Sono in lista bianca di proposito: cosi' il fascicolo diventa
    # il modo NORMALE di stampare e non una cosa che ogni chiamante deve
    # ricordarsi di chiedere — che era la richiesta esplicita di Lorenzo,
    # «standardizza tutto il progetto».
    "capitoli_pdf",
    "allegati",
)


def split_render_kwargs(sections: dict) -> tuple[dict, dict]:
    """Separa `(argomenti per render_pdf, errori per sezione)`.

    Filtra per lista bianca e non per esclusione: così una diagnostica
    aggiunta in futuro non arriva mai al renderer per dimenticanza.
    """
    render_kwargs = {k: sections[k] for k in _RENDER_SECTION_KEYS if k in sections}
    errors = sections.get("section_errors") or {}
    return render_kwargs, dict(errors)


# ---------------------------------------------------------------------------
# Le guide per attrazione come documenti a sé (task #178)
# ---------------------------------------------------------------------------
def build_directions_by_poi(directions) -> dict:
    """Da `sections["directions"]` a `{poi_id: "come ci arrivo"}`.

    Ogni tratta sa gia' da dove si parte, dove si arriva e quanto dura: qui
    la si gira dal punto di vista dell'ATTRAZIONE, che e' il punto di vista
    di chi ha in mano la guida di quel posto e non tutto l'itinerario.

    Quando la stessa attrazione compare in piu' giornate vince la PRIMA:
    e' quella in cui il cliente ci arriva per la prima volta, l'unica volta
    in cui la domanda "come ci arrivo?" e' davvero aperta.
    """
    fuori: dict = {}
    for giornata in directions or []:
        if not isinstance(giornata, dict):
            continue
        for tratta in giornata.get("legs") or []:
            if not isinstance(tratta, dict):
                continue
            arrivo = tratta.get("to_poi_id")
            if not isinstance(arrivo, str) or not arrivo or arrivo in fuori:
                continue
            partenza = str(tratta.get("from_name") or "").strip()
            durata = str(tratta.get("duration_text") or "").strip()
            if not partenza:
                continue
            fuori[arrivo] = f"Da {partenza}, {durata}." if durata else f"Da {partenza}."
    return fuori


def prepara_fascicolo(
    guides,
    sections: dict,
    *,
    itinerary=None,
    trip=None,
    destination: str = "",
    photos: dict | None = None,
    poi=None,
) -> dict:
    """Prepara i capitoli staccati e gli allegati: il fascicolo in un file solo.

    [AGGIUNTO 2026-08-05 — task #190/#192. Richiesta di Lorenzo: «questi
    documenti seppur diversi stiano in un unico file, non so come farai ma
    trova il modo»]

    È la sorella di `publish_hosted_guides()` e risolve lo stesso problema —
    togliere dal documento principale le pagine di dettaglio che lo rendono
    noioso — per una strada migliore su tutti e tre i punti che contano:

      - **un file solo**, che era la richiesta;
      - **funziona senza rete**, quindi in aereo e all'estero senza dati,
        che è esattamente quando questi documenti si leggono;
      - **il ritorno arriva al punto esatto** da cui si era partiti, cosa
        che con un documento ospitato è impossibile: una URL non sa da dove
        ci sei arrivato.

    Va chiamata PRIMA di `publish_hosted_guides()`. Le guide che diventano
    capitoli non vengono anche pubblicate: sarebbero stampate due volte, e
    ogni stampa è mezzo secondo su un'esecuzione che ha già sfiorato il tetto
    duro dei 300 secondi di Make.

    Scrive dentro `sections` la chiave `capitoli_pdf`, che
    `split_render_kwargs()` gira poi a `render_pdf()` da sola: così il
    fascicolo diventa il modo normale di stampare invece di un argomento in
    più che ogni chiamante deve ricordarsi. L'altra metà — il foglio della
    valigia come allegato — la mette `allega_foglio_valigia()`, che va
    chiamata più tardi per la ragione spiegata lì.

    Best-effort come ogni altra sezione: se qualcosa va storto il cliente
    riceve il documento di ieri, con le guide stampate dentro.
    """
    esito = {"capitoli": 0, "errore": ""}
    if not isinstance(sections, dict):
        return esito

    elenco = [g for g in (guides or []) if isinstance(g, dict) and g.get("poi_id")]
    if not elenco:
        return esito

    try:
        ritorni = fascicolo.elenca_ritorni(
            itinerary, elenco,
            giorni_con_cartina=[
                dm.get("day") for dm in (sections.get("day_maps") or [])
                if isinstance(dm, dict)
            ],
        )
        capitoli = poi_pdf.costruisci_capitoli(
            elenco, ritorni,
            destination=destination or _destinazione_di(trip),
            place_cards=sections.get("place_cards"),
            photos=photos,
            directions_by_poi=build_directions_by_poi(sections.get("directions")),
            open_hours_by_poi=_orari_per_poi(poi),
        )
    except Exception as e:  # noqa: BLE001 — best-effort come ogni sezione
        print(f"⚠️  pdf_extras: fascicolo non preparato — {type(e).__name__}: {e}")
        esito["errore"] = type(e).__name__
        return esito

    if capitoli:
        sections["capitoli_pdf"] = capitoli
        esito["capitoli"] = len(capitoli)
    return esito


def allega_foglio_valigia(sections: dict) -> bool:
    """Infila il foglio della valigia DENTRO il PDF, come allegato vero.

    [AGGIUNTO 2026-08-05 — task #192. Decisione presa con Lorenzo: «doppio
    binario»]

    Il foglio viaggia per tre strade diverse, e non è ridondanza: nessuna
    delle tre basta da sola.

      1. **allegato dentro il PDF** (questa funzione): un file solo, come
         chiesto. Anteprima, Acrobat e Foxit lo mostrano nel pannello degli
         allegati — ma i lettori dei telefoni quasi mai;
      2. **capitolo stampabile dentro il PDF**, con le stesse caselle: è
         quello che legge chi apre il documento dal telefono, ed è anche
         l'unico che si può stampare e portarsi dietro;
      3. **collegamento al foglio ospitato**, per chi vuole spuntare le
         caselle col dito invece che con una matita.

    Va chiamata DOPO `aggiungi_ritorno_al_foglio_valigia()`: quella rifà il
    foglio da capo per metterci dentro il bottone di ritorno, e allegare
    prima significherebbe infilare nel PDF la versione senza bottone — lo
    stesso file, e proprio senza la cosa che era stata chiesta. È lo stesso
    inciampo già preso una volta con l'allegato della mail, il 2026-08-03.
    """
    if not isinstance(sections, dict):
        return False
    foglio = sections.get("checklist_xlsx")
    if not isinstance(foglio, dict) or not foglio.get("content"):
        return False
    nome = str(foglio.get("filename") or "").strip() or "valigia.xlsx"
    sections["allegati"] = {nome: foglio["content"]}
    return True


def publish_hosted_guides(
    guides,
    sections: dict,
    *,
    trip=None,
    destination: str = "",
    photos: dict | None = None,
    poi=None,
) -> dict:
    """Pubblica una guida per attrazione e scrive le URL dentro `sections`.

    [AGGIUNTO 2026-08-03 — richiesta di Lorenzo: "migliorare la guida
    turistica linkando un pdf per attrazione da te generato ad hoc ... con
    bottone di torna all'itinerario alla parte giusta", e sua scelta
    esplicita: "PDF separati, ospitati su Render"]

    L'ordine qui e' obbligato e non e' evidente, quindi vale la pena
    scriverlo: la guida deve contenere il bottone "torna all'itinerario",
    ma l'itinerario non e' ancora stato stampato quando la guida viene
    costruita. E' esattamente il problema che `hosting.reserve()` risolve:
    il token della consegna si sceglie PRIMA, la URL del documento
    principale si calcola da quel token, e il file vero ci si scrive sopra
    dopo. Chi chiama deve solo ricordarsi l'ultimo passo — ed e' per questo
    che questa funzione restituisce anche `consegna` e `token`.

    L'identificativo della consegna e' il `ref` del collegamento recensione,
    non un codice nuovo: e' lo stesso che Make archivia in Airtable accanto
    al viaggio, e averne due diversi per la stessa vendita significherebbe
    non riuscire piu' a collegare un documento pubblicato a chi l'ha
    comprato.

    Ritorna sempre un dizionario, mai un'eccezione. Quando l'ospitalita' non
    e' configurata su Render — cioe' finche' `PUBLIC_BASE_URL` non e'
    impostata — ritorna tutto vuoto e il prodotto resta quello di ieri: un
    unico PDF con le guide stampate dentro.
    """
    vuoto = {"guide_urls": {}, "itinerary_url": None, "consegna": None, "token": None}
    if not guides or not hosting.is_configured():
        return vuoto

    # [AGGIUNTO 2026-08-05 — task #190] Le guide che sono gia' diventate
    # capitoli cuciti non si pubblicano anche: sarebbero stampate due volte,
    # e mezzo secondo per guida su un'esecuzione che ha gia' sfiorato il tetto
    # dei 300 secondi di Make non e' un dettaglio. Fra le due strade vince il
    # fascicolo — e' un file solo, funziona senza rete e riporta al punto
    # esatto — quindi qui ci si fa da parte.
    gia_capitoli = {
        c.get("poi_id") for c in (sections.get("capitoli_pdf") or [])
        if isinstance(c, dict)
    }
    if gia_capitoli:
        guides = [g for g in guides
                  if isinstance(g, dict) and g.get("poi_id") not in gia_capitoli]
        if not guides:
            return vuoto

    try:
        collegamento = sections.get("feedback_link") or {}
        consegna = str(collegamento.get("ref") or "").strip() or hosting.new_delivery_id()
        token = hosting.reserve(consegna)
        if not token:
            return vuoto
        itinerary_url = hosting.public_url(consegna, token, "itinerario")

        urls = poi_pdf.publish_guides(
            guides,
            consegna=consegna,
            destination=destination or _destinazione_di(trip),
            place_cards=sections.get("place_cards"),
            photos=photos,
            itinerary_url=itinerary_url,
            directions_by_poi=build_directions_by_poi(sections.get("directions")),
            # [AGGIUNTO 2026-08-03 — task #180] Gli orari di apertura veri,
            # dal fornitore. Vanno nella guida della singola attrazione e non
            # nel documento principale: e' esattamente lo "zoom out dal macro
            # al micro" chiesto da Lorenzo — il dettaglio che serve davanti al
            # portone sta dietro al portone, non in copertina.
            open_hours_by_poi=_orari_per_poi(poi),
        )
    except Exception as e:  # noqa: BLE001 — best-effort come ogni altra sezione
        print(f"⚠️  pdf_extras: guide ospitate non pubblicate — {type(e).__name__}: {e}")
        return vuoto

    sections["guide_urls"] = urls
    return {
        "guide_urls": urls, "itinerary_url": itinerary_url,
        "consegna": consegna, "token": token,
    }


def aggiungi_ritorno_al_foglio_valigia(
    sections: dict,
    itinerary_url,
    *,
    trip=None,
    itinerary=None,
    travellers: int = 1,
) -> bool:
    """Rimette in cima al foglio della valigia il bottone «torna all'itinerario».

    [AGGIUNTO 2026-08-03 — task #184, richiesta di Lorenzo: «ovviamente un
    pulsante sul foglio di calcolo che ti fa ritornare al pdf originario»]

    Perche' il foglio va rifatto invece che corretto: perche' quando viene
    costruito, dentro `build_pdf_extras()`, l'indirizzo del PDF non esiste
    ancora — il documento non e' stato nemmeno stampato. L'indirizzo nasce
    piu' tardi, da `publish_hosted_guides()`, che prenota il posto del
    documento principale prima di scriverci sopra il file. Sono due momenti
    diversi e nessuno dei due si puo' spostare: il foglio ha bisogno del
    vademecum (che viene prima), il bottone ha bisogno della prenotazione
    (che viene dopo).

    Rifarlo costa quanto farlo la prima volta e non costa NIENTE di quello
    che conta: nessuna chiamata di rete, nessun token del modello, qualche
    decina di millisecondi di `openpyxl` dentro un'esecuzione che ne dura
    duecentomila. Non vale la pena di inventare un modo per correggere un
    file gia' scritto.

    Best-effort come ogni altra sezione: se qualcosa va storto resta il
    foglio di prima, che e' completo e utile — gli manca solo la strada di
    ritorno. Ritorna `True` solo se il bottone c'e' davvero, cosi' chi chiama
    puo' dirlo nei log invece di darlo per scontato.
    """
    if not isinstance(sections, dict):
        return False
    precedente = sections.get("checklist_xlsx")
    if not isinstance(precedente, dict) or not precedente.get("content"):
        return False
    # La stessa regola del riquadro nel PDF e del bottone dentro le guide:
    # un indirizzo che non e' un `https://` vero non diventa un pulsante.
    # Meglio nessun bottone di un bottone che non apre niente — su un foglio
    # di calcolo, per giunta, dove il cliente non ha modo di capire perche'.
    if not isinstance(itinerary_url, str) or not itinerary_url.strip().startswith("https://"):
        return False

    try:
        blob = checklist_xlsx_mod.build_checklist_xlsx(
            trip, sections.get("vademecum"), sections.get("predeparture"),
            itinerary, travellers=travellers,
            itinerary_url=itinerary_url.strip(),
        )
    except Exception as e:  # noqa: BLE001 — best-effort, vedi docstring
        print("⚠️  pdf_extras: foglio valigia senza bottone di ritorno — "
              f"{type(e).__name__}: {e}")
        return False
    if not blob:
        return False

    sections["checklist_xlsx"] = dict(precedente, content=blob)
    return True


def _orari_per_poi(poi) -> dict:
    """`{poi_id: open_hours}` da una lista di POI, dizionari oppure oggetti.

    [AGGIUNTO 2026-08-03 — task #180]

    Accetta entrambe le forme di proposito: `service.py` ha in mano i POI
    gia' convertiti in dizionari, `main.py` ha l'`ApiPayload` con le
    dataclass. Chiedere a uno dei due di convertire prima di chiamare
    significa avere due strade diverse per lo stesso documento, ed e' il modo
    con cui in questo progetto si sono gia' create differenze fra il PDF
    provato in locale e quello ricevuto dal cliente.
    """
    risultato: dict = {}
    for elemento in (poi or []):
        if isinstance(elemento, dict):
            identificativo, orari = elemento.get("id"), elemento.get("open_hours")
        else:
            identificativo = getattr(elemento, "id", None)
            orari = getattr(elemento, "open_hours", None)
        if isinstance(identificativo, str) and identificativo and isinstance(orari, dict):
            risultato[identificativo] = orari
    return risultato


def _destinazione_di(trip) -> str:
    """Il nome della citta', se il viaggio ce l'ha. Serve solo alla riga sotto
    il titolo della guida: se manca, la guida esce senza e non se ne accorge
    nessuno."""
    for campo in ("destination", "city", "destination_city"):
        valore = getattr(trip, campo, None)
        if isinstance(valore, str) and valore.strip():
            return valore.strip()
    return ""
