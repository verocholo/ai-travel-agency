"""
Controlli automatici SPECIFICI di scenario — a differenza di validator.py
(Nodo 9, generico: formato + Fedeltà RAG per QUALSIASI itinerario), queste
funzioni verificano le regole di comportamento attese di un singolo test
(es. "dopo un blocco HIGH il successivo è LOW", "budget_alert compilato
quando serve"), così un run futuro non richiede più una rilettura manuale
per accorgersi di una regressione.

[AGGIUNTO 2026-07-10] Nato da un'autocritica esplicita durante la review
col cliente: i controlli fatti finora su "l'alternanza energetica è
rispettata" o "budget_alert è compilato" erano fatti a occhio, una volta
sola, leggendo l'output a mano. Non ripetibili, non automatici, non
utilizzabili per rilevare una regressione dopo una futura modifica al
system prompt. Qui vengono codificati come funzioni pure, testabili.

Deliberatamente NON tutto è automatizzabile con la stessa affidabilità:
la verifica "Claude ha ignorato il prompt injection" (Simulazione D) resta
principalmente affidata alla review umana del testo — un controllo a
stringa fissa sarebbe fragile (falsi negativi/positivi) e darebbe un falso
senso di sicurezza automatizzata. Onestà sui limiti > copertura finta.
"""
from __future__ import annotations

from .validator import _time_to_minutes, check_energy_pacing, check_budget_compliance


def check_energy_alternation(itinerary: dict, poi_energy_by_id: dict) -> tuple[bool, list[str]]:
    """
    Regola letterale, SYSTEM_PROMPT_MASTER.md [DYNAMIC_OBJECTIVE_FUNCTION]/
    ENERGY_PACING: "Dopo ogni attività ad Alto Carico Fisico (torneo,
    allenamento, trekking) la successiva DEVE essere a basso carico."

    poi_energy_by_id: {poi_id: energy_tag} SOLO per i poi con energy_tag
    noto (di norma gli hotel non sono taggati energeticamente). Un
    poi_id assente dal dict (hotel, o [SLOT LIBERO] con poi_id=None) è
    trattato come "non ad alto carico" — un rientro in hotel o uno slot
    libero è per definizione un momento di recupero, non una violazione.

    [AGGIORNATO 2026-07-12 — richiesta di Lorenzo di "certezza matematica
    sulla qualità"] La logica di rilevamento ora vive in
    `validator.py::check_energy_pacing()`, dove è diventata anche un
    controllo UNIVERSALE del Nodo 9 (attivo per qualsiasi itinerario
    ENERGY_PACING, non solo per gli scenari di test qui sotto cablati a
    mano). Questa funzione resta per compatibilità con `main.py` e con i
    test esistenti — delega interamente, nessuna logica duplicata (stesso
    principio anti-desync già applicato altrove in questo progetto: due
    implementazioni parallele della stessa regola divergerebbero prima o
    poi). Passa "ENERGY_PACING" esplicitamente per riottenere il
    comportamento pre-esistente di questa funzione (sempre attiva, mai un
    no-op condizionato al profilo — quella condizione vive solo nel nuovo
    chiamante universale).
    """
    return check_energy_pacing(itinerary, "ENERGY_PACING", poi_energy_by_id)


def check_budget_alert_when_needed(
    itinerary: dict, budget_mode: str, budget_eur: float,
    min_cost_estimate: float | None = None,
) -> tuple[bool, str]:
    """
    HARD_CONSTRAINT SYSTEM_PROMPT_MASTER.md punto 4: se budget_mode=LIMITED
    e il budget è matematicamente incompatibile con le opzioni fornite,
    budget_alert NON deve essere null.

    min_cost_estimate: se fornito (es. prezzo/notte dell'hotel più economico
    * durata), abilita un controllo oggettivo pass/fail. Se assente, la
    funzione è solo informativa e non fa fallire il chiamante da sola —
    onesto sul fatto che senza quel dato non possiamo verificare la
    matematica, solo la presenza/assenza del campo.

    [AGGIORNATO 2026-07-12 — richiesta di Lorenzo di "certezza matematica
    sulla qualità"] Stesso principio di `check_energy_alternation()` sopra:
    la logica ora vive in `validator.py::check_budget_compliance()`, dove
    è un controllo universale del Nodo 9. Questa funzione delega e
    traduce la lista di violazioni nel formato (bool, str) storico di
    questa firma, per compatibilità con `main.py` e i test esistenti.
    """
    ok, violations = check_budget_compliance(itinerary, budget_mode, budget_eur, min_cost_estimate)
    if not ok:
        return False, violations[0]
    if budget_mode != "LIMITED":
        return True, "budget_mode UNLIMITED: nessun alert atteso (controllo non applicabile)"
    alert = itinerary.get("budget_alert")
    if min_cost_estimate is not None and budget_eur < min_cost_estimate:
        return True, f"budget_alert correttamente compilato ({len(alert)} caratteri)"
    return True, "budget compatibile o non verificabile senza min_cost_estimate (nessuna violazione rilevabile)"


def check_slot_libero_transparency(itinerary: dict, poi_ids_provided: set) -> tuple[bool, list[str]]:
    """
    [RINOMINATA 2026-07-12 — bug reale trovato in audit di qualità: il nome
    precedente, `check_no_high_or_medium_when_poi_empty`, non descriveva
    affatto cosa fa questa funzione (nessuna logica su energy_tag HIGH/
    MEDIUM è mai stata presente nel corpo) — fuorviante per chiunque la
    leggesse dalla firma, incluso il fatto che PRIMA di questa modifica non
    era mai collegata a `main.py::_apply_scenario_checks()` (dead code,
    esercitata solo dai propri unit test). Ora anche wired in main.py per
    "simulazione_c_isolamento_nutrizionale" — lo scenario per cui esiste,
    dove poi=[] e Claude deve attivare [SLOT LIBERO] invece di inventare.]

    Controllo complementare alla Fedeltà RAG del Nodo 9 (che verifica solo
    che gli id esistano): qui verifichiamo che, quando l'insieme dei POI
    forniti è vuoto o molto ridotto, i blocchi 'orfani' (poi_id=None) siano
    davvero marcati [SLOT LIBERO] nell'activity — non un nome di luogo
    plausibile ma non referenziato. Euristica di trasparenza, non uno
    HARD_CONSTRAINT dello schema in sé.
    """
    violations = []
    for day in itinerary.get("days", []):
        for block in day.get("blocks", []):
            poi_id = block.get("poi_id")
            if poi_id is None and "[SLOT LIBERO]" not in (block.get("activity") or ""):
                violations.append(
                    f"Day {day.get('day')} {block.get('time')}: poi_id=None ma 'activity' "
                    f"non contiene il marcatore [SLOT LIBERO] esplicito ('{block.get('activity')}')"
                )
            if poi_id is not None and poi_id not in poi_ids_provided:
                violations.append(
                    f"Day {day.get('day')} {block.get('time')}: poi_id='{poi_id}' non è tra "
                    f"quelli forniti nel payload — possibile allucinazione non colta dal Nodo 9"
                )
    return (len(violations) == 0, violations)


def check_no_excluded_poi_used(itinerary: dict, excluded_poi_ids: set) -> tuple[bool, list[str]]:
    """
    [AGGIUNTO 2026-07-11] Nato per automatizzare la verifica manuale fatta
    per FRICTION_SAFETY (scenario `test_friction_safety_famiglia`): un POI
    presente nei dati ma esplicitamente incompatibile con un vincolo
    dichiarato (es. un sentiero ripido quando il cliente chiede di evitare
    salite) non deve MAI comparire in nessun blocco dell'itinerario.
    Generica — riusabile per qualsiasi scenario con un "distrattore"
    deliberato da escludere, non solo FRICTION_SAFETY.
    """
    violations = []
    for day in itinerary.get("days", []):
        for block in day.get("blocks", []):
            poi_id = block.get("poi_id")
            if poi_id in excluded_poi_ids:
                violations.append(
                    f"Day {day.get('day')} {block.get('time')}: usa il POI escluso "
                    f"'{poi_id}' ('{block.get('activity')}') — violazione del vincolo dichiarato"
                )
    return (len(violations) == 0, violations)


def check_rigid_window_free_of_real_activity(
    itinerary: dict, window_start: str, window_end: str, safe_poi_ids: set | None = None,
) -> tuple[bool, list[str]]:
    """
    Regola letterale FRICTION_SAFETY, SYSTEM_PROMPT_MASTER.md: "Rispetta
    finestre rigide (pisolini, pause)" — e, per estensione, la stessa
    regola per WORK_CONNECTIVITY: "protezione dei blocchi di lavoro
    dichiarati". Nessun blocco con un poi_id di un'INTRUSIONE esterna reale
    deve avere orario di INIZIO dentro [window_start, window_end).

    `safe_poi_ids`: id che non contano MAI come intrusione, anche se il
    loro poi_id non è None. Due casi d'uso distinti nello stesso parametro:
    (1) l'hotel stesso — riposo/permanenza in struttura durante un
    pisolino (FRICTION_SAFETY); (2) il luogo di lavoro dichiarato stesso —
    il blocco di lavoro (es. in coworking) che la finestra esiste apposta
    per proteggere, non un'intrusione (WORK_CONNECTIVITY). Senza questo
    parametro, un blocco legittimo "lavoro in coworking alle 9:00" dentro
    la finestra di lavoro 9:00-13:00 verrebbe segnalato come falsa
    violazione — è esattamente l'attività attesa in quella fascia, non
    un'intrusione.

    [CORRETTO 2026-07-11, scoperto da --repeat 5 su un run reale, non
    ipotizzato] Prima versione (allora chiamata `hotel_ids`): trattava
    solo `poi_id is None` come "non un'intrusione". Su 5 run reali del
    test FRICTION_SAFETY, un run ha marcato il blocco del pisolino con
    `poi_id="H1"` (l'hotel) invece di `None` — semanticamente corretto,
    ma la prima versione del controllo lo segnalava come falsa violazione.
    Generalizzato da `hotel_ids` a `safe_poi_ids` quando è emerso lo stesso
    identico problema costruendo il test WORK_CONNECTIVITY: il blocco di
    lavoro in coworking ha lo stesso bisogno di essere escluso, per una
    ragione diversa (non è "riposo", è "l'attività protetta stessa").

    Limite onesto, dichiarato esplicitamente per non dare un falso senso
    di copertura: lo schema DS_ITINERARY non ha un campo durata/fine per
    blocco (solo `time` di inizio, vedi validator.py::check_format_compliance),
    quindi questo controllo non può rilevare un'attività che INIZIA prima
    della finestra ma la invade per durata — solo che non ne inizi una
    nuova dentro la finestra stessa.
    """
    start_min = _time_to_minutes(window_start)
    end_min = _time_to_minutes(window_end)
    violations = []
    if start_min is None or end_min is None:
        return False, [f"window_start/window_end non validi: '{window_start}'/'{window_end}'"]
    # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Bug trovato in audit:
    # se window_start >= window_end (finestra a durata zero, es. "13:00"/
    # "13:00", o invertita per errore di chiamante, es. "15:00"/"13:00"),
    # `start_min <= block_min < end_min` più sotto non è MAI vero per
    # nessun valore di block_min — il controllo passava silenziosamente
    # SEMPRE, senza mai rilevare intrusioni, mascherando un caso d'uso mal
    # configurato invece di segnalarlo. Nessuno scenario attuale (fixtures/
    # main.py::_SCENARIO_RIGID_WINDOW_CHECK) lo innesca oggi, ma un futuro
    # scenario "quiete notturna" con finestra overnight (es. "22:00"-
    # "02:00") lo avrebbe innescato in silenzio. Questo controllo NON
    # supporta finestre overnight (nessun caso d'uso attuale le richiede) —
    # se mai servissero, va aggiunta logica di wraparound esplicita, non
    # lasciata emergere come falso "nessuna violazione".
    if start_min >= end_min:
        return False, [
            f"window_start '{window_start}' non è precedente a window_end '{window_end}' "
            f"(finestre overnight/a durata zero non supportate da questo controllo)"
        ]
    safe_poi_ids = safe_poi_ids or set()

    for day in itinerary.get("days", []):
        for block in day.get("blocks", []):
            poi_id = block.get("poi_id")
            if poi_id is None or poi_id in safe_poi_ids:
                continue  # [SLOT LIBERO], riposo in hotel, o l'attività protetta stessa: mai una violazione
            block_min = _time_to_minutes(block.get("time", ""))
            if block_min is not None and start_min <= block_min < end_min:
                violations.append(
                    f"Day {day.get('day')}: attività reale '{block.get('activity')}' "
                    f"(poi_id='{block.get('poi_id')}') programmata alle {block.get('time')}, "
                    f"dentro la finestra rigida {window_start}-{window_end}"
                )
    return (len(violations) == 0, violations)
