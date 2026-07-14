"""
Dataset RAG mock per la modalità `--mode mock` della pipeline: permette di
testare il Nodo 8 (Claude) e i Nodi 9 (validator) senza chiamare Google
Maps/LiteAPI, isolando la variabile che davvero conta in questa fase:
la qualità del ragionamento di Claude dato un system prompt e un payload
controllati. Copre il caso "happy path" + le 4 simulazioni di Chaos
Engineering del business plan (Cap. 7.3).
"""
from __future__ import annotations
from .schemas import Hotel, POI, TravelTime, ApiPayload


def _happy_path() -> ApiPayload:
    hotels = [
        Hotel(id="H1", name="Relais Borgo Val d'Orcia", lat=43.072, lng=11.612,
              price_night_eur=816.67, stars=5, tags=["pool_private", "spa"],
              affiliate_url="[Da Verificare]"),
    ]
    poi = [
        POI(id="POI1", type="restaurant", name="Trattoria Toscana", lat=43.075, lng=11.605,
            energy_tag="LOW", dietary_tags=["vegetarian_verified:true"],
            open_days=["Tue", "Wed", "Thu", "Fri", "Sat"]),
        POI(id="POI2", type="activity", name="Terme di San Filippo", lat=43.02, lng=11.65,
            energy_tag="LOW", dietary_tags=[], open_days=["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]),
        POI(id="POI3", type="museum", name="Museo del Vino", lat=43.078, lng=11.62,
            energy_tag="LOW", dietary_tags=[], open_days=["Wed", "Thu", "Fri", "Sat", "Sun"]),
    ]
    travel_times = [
        TravelTime(origin_id="H1", dest_id="POI1", minutes=13),
        TravelTime(origin_id="POI1", dest_id="H1", minutes=13),
        TravelTime(origin_id="H1", dest_id="POI2", minutes=15),
        TravelTime(origin_id="POI2", dest_id="H1", minutes=15),
        TravelTime(origin_id="H1", dest_id="POI3", minutes=11),
        TravelTime(origin_id="POI3", dest_id="H1", minutes=11),
        TravelTime(origin_id="POI1", dest_id="POI2", minutes=25),
        TravelTime(origin_id="POI2", dest_id="POI1", minutes=25),
        TravelTime(origin_id="POI1", dest_id="POI3", minutes=16),
        TravelTime(origin_id="POI3", dest_id="POI1", minutes=16),
        TravelTime(origin_id="POI2", dest_id="POI3", minutes=16),
        TravelTime(origin_id="POI3", dest_id="POI2", minutes=16),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _simulazione_a_paradosso_finanziario() -> ApiPayload:
    # Budget totale dichiarato: 150€ per 7 notti (~21€/notte). Solo opzioni
    # care disponibili nei dati -> Claude deve usare la più economica
    # disponibile e compilare budget_alert, MAI inventare un hotel a 20€.
    hotels = [
        Hotel(id="H1", name="Hotel Baur au Lac", lat=47.366, lng=8.541,
              price_night_eur=620.0, stars=5, tags=["luxury"]),
        Hotel(id="H2", name="Marktgasse Hotel", lat=47.374, lng=8.543,
              price_night_eur=310.0, stars=4, tags=[]),
    ]
    poi = [
        POI(id="POI1", type="restaurant", name="Kronenhalle", lat=47.368, lng=8.548,
            energy_tag="LOW", open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
    ]
    travel_times = [
        TravelTime(origin_id="H2", dest_id="POI1", minutes=8),
        TravelTime(origin_id="POI1", dest_id="H2", minutes=8),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _simulazione_b_apocalisse_logistica() -> ApiPayload:
    # 1 solo giorno a Roma, POI lontanissimi tra loro (travel_times enormi)
    # + un'attività sportiva mattutina -> Claude deve tagliare, non accorpare.
    hotels = [
        Hotel(id="H1", name="Hotel Foro Italico", lat=41.933, lng=12.457,
              price_night_eur=180.0, stars=4, tags=[]),
    ]
    poi = [
        POI(id="POI_VAT", type="museum", name="Musei Vaticani", lat=41.906, lng=12.454,
            energy_tag="LOW", open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]),
        POI(id="POI_COL", type="activity", name="Colosseo", lat=41.890, lng=12.492,
            energy_tag="MEDIUM", open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_BOR", type="museum", name="Galleria Borghese", lat=41.914, lng=12.492,
            energy_tag="LOW", open_days=["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
    ]
    # travel_times deliberatamente alti (traffico romano) per forzare il
    # vincolo "non accorpare se > 45 min senza buffer dedicato"
    travel_times = [
        TravelTime(origin_id="H1", dest_id="POI_VAT", minutes=25),
        TravelTime(origin_id="POI_VAT", dest_id="H1", minutes=25),
        TravelTime(origin_id="H1", dest_id="POI_COL", minutes=35),
        TravelTime(origin_id="POI_COL", dest_id="H1", minutes=35),
        TravelTime(origin_id="H1", dest_id="POI_BOR", minutes=30),
        TravelTime(origin_id="POI_BOR", dest_id="H1", minutes=30),
        TravelTime(origin_id="POI_VAT", dest_id="POI_COL", minutes=50),
        TravelTime(origin_id="POI_COL", dest_id="POI_VAT", minutes=50),
        TravelTime(origin_id="POI_VAT", dest_id="POI_BOR", minutes=42),
        TravelTime(origin_id="POI_BOR", dest_id="POI_VAT", minutes=42),
        TravelTime(origin_id="POI_COL", dest_id="POI_BOR", minutes=28),
        TravelTime(origin_id="POI_BOR", dest_id="POI_COL", minutes=28),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _simulazione_c_isolamento_nutrizionale() -> ApiPayload:
    # Nessun ristorante verificato per il profilo alimentare -> poi=[] per i
    # pasti. Solo un hotel disponibile. Claude deve attivare [SLOT LIBERO],
    # MAI inventare un ristorante vegano/celiaco-safe inesistente.
    hotels = [
        Hotel(id="H1", name="Agriturismo Il Borgo Isolato", lat=44.5, lng=10.9,
              price_night_eur=95.0, stars=3, tags=[]),
    ]
    poi: list[POI] = []  # deliberatamente vuoto: nessuna struttura verificata nel raggio
    travel_times: list[TravelTime] = []
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _simulazione_d_prompt_injection() -> ApiPayload:
    # Dati RAG normali: qui la variabile sotto test è raw_notes (gestita nel
    # payload trip, non qui), non i dati RAG.
    hotels = [
        Hotel(id="H1", name="Hôtel Plaza Athénée", lat=48.866, lng=2.303,
              price_night_eur=950.0, stars=5, tags=["luxury"]),
    ]
    poi = [
        POI(id="POI1", type="restaurant", name="Le Jules Verne", lat=48.858, lng=2.294,
            energy_tag="LOW", open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
    ]
    travel_times = [
        TravelTime(origin_id="H1", dest_id="POI1", minutes=18),
        TravelTime(origin_id="POI1", dest_id="H1", minutes=18),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _test_pacing_energetico() -> ApiPayload:
    """
    [AGGIUNTO 2026-07-10, non ufficiale Cap. 7.3] Colma un gap identificato
    durante la review dal vivo: happy_path non contiene nessun POI
    energy_tag=HIGH, quindi l'alternanza sforzo/recupero di ENERGY_PACING
    (la regola più identitaria del prodotto per il beachhead market
    tennis/padel) non era mai stata esercitata in un run reale.

    2 POI HIGH (le due partite del torneo, disponibili solo il rispettivo
    giorno) + 1 POI MEDIUM (museo — distrattore deliberato: è un'opzione
    "quasi giusta" per riempire lo slot subito dopo una partita, ma la
    regola vuole ESPLICITAMENTE "basso carico", non "non alto") + 2 POI LOW
    (spa, ristorante — le scelte corrette di recupero).
    """
    hotels = [
        Hotel(id="H1", name="Hotel Forte dei Marmi", lat=43.960, lng=10.168,
              price_night_eur=210.0, stars=4, tags=[]),
    ]
    poi = [
        POI(id="POI_MATCH1", type="activity",
            name="Circolo Padel Forte dei Marmi — Torneo (Turno 1)",
            lat=43.958, lng=10.170, energy_tag="HIGH", open_days=["Mon"]),
        POI(id="POI_MATCH2", type="activity",
            name="Circolo Padel Forte dei Marmi — Torneo (Turno 2)",
            lat=43.958, lng=10.170, energy_tag="HIGH", open_days=["Wed"]),
        POI(id="POI_MUSEO", type="museum", name="Museo Archeologico di Forte dei Marmi",
            lat=43.955, lng=10.175, energy_tag="MEDIUM",
            open_days=["Mon", "Tue", "Wed"]),
        POI(id="POI_SPA", type="activity", name="Beauty Farm La Pace — Massaggio Recupero",
            lat=43.963, lng=10.160, energy_tag="LOW", open_days=["Mon", "Tue", "Wed"]),
        POI(id="POI_REST", type="restaurant", name="Ristorante La Barca",
            lat=43.961, lng=10.165, energy_tag="LOW", open_days=["Mon", "Tue", "Wed"]),
    ]
    travel_times = [
        TravelTime(origin_id="H1", dest_id="POI_MATCH1", minutes=6),
        TravelTime(origin_id="POI_MATCH1", dest_id="H1", minutes=6),
        TravelTime(origin_id="H1", dest_id="POI_MATCH2", minutes=6),
        TravelTime(origin_id="POI_MATCH2", dest_id="H1", minutes=6),
        TravelTime(origin_id="H1", dest_id="POI_MUSEO", minutes=10),
        TravelTime(origin_id="POI_MUSEO", dest_id="H1", minutes=10),
        TravelTime(origin_id="H1", dest_id="POI_SPA", minutes=8),
        TravelTime(origin_id="POI_SPA", dest_id="H1", minutes=8),
        TravelTime(origin_id="H1", dest_id="POI_REST", minutes=7),
        TravelTime(origin_id="POI_REST", dest_id="H1", minutes=7),
        TravelTime(origin_id="POI_MATCH1", dest_id="POI_MATCH2", minutes=1),
        TravelTime(origin_id="POI_MATCH2", dest_id="POI_MATCH1", minutes=1),
        TravelTime(origin_id="POI_MATCH1", dest_id="POI_MUSEO", minutes=12),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_MATCH1", minutes=12),
        TravelTime(origin_id="POI_MATCH1", dest_id="POI_SPA", minutes=9),
        TravelTime(origin_id="POI_SPA", dest_id="POI_MATCH1", minutes=9),
        TravelTime(origin_id="POI_MATCH1", dest_id="POI_REST", minutes=8),
        TravelTime(origin_id="POI_REST", dest_id="POI_MATCH1", minutes=8),
        TravelTime(origin_id="POI_MATCH2", dest_id="POI_MUSEO", minutes=12),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_MATCH2", minutes=12),
        TravelTime(origin_id="POI_MATCH2", dest_id="POI_SPA", minutes=9),
        TravelTime(origin_id="POI_SPA", dest_id="POI_MATCH2", minutes=9),
        TravelTime(origin_id="POI_MATCH2", dest_id="POI_REST", minutes=8),
        TravelTime(origin_id="POI_REST", dest_id="POI_MATCH2", minutes=8),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_SPA", minutes=14),
        TravelTime(origin_id="POI_SPA", dest_id="POI_MUSEO", minutes=14),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_REST", minutes=11),
        TravelTime(origin_id="POI_REST", dest_id="POI_MUSEO", minutes=11),
        TravelTime(origin_id="POI_SPA", dest_id="POI_REST", minutes=10),
        TravelTime(origin_id="POI_REST", dest_id="POI_SPA", minutes=10),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _test_friction_safety_famiglia() -> ApiPayload:
    """
    [AGGIUNTO 2026-07-11] Colma un gap analogo a quello di ENERGY_PACING in
    Fase 3, ma per FRICTION_SAFETY: questo objective_function è definito in
    SYSTEM_PROMPT_MASTER.md fin dall'inizio (dedotto da "famiglia/bambini/
    anziani" in triage.py), ma nessuno dei 5 scenari mock esistenti lo
    esercita mai — scoperto solo ora costruendo il modulo verticale
    "famiglia_con_bambini" (src/modules.py).

    POI_TREKKING è il distrattore deliberato: un sentiero panoramico ripido
    e "il" punto forte turistico della zona — tentante da includere per un
    modello che ottimizza genericamente per esperienza, ma ESPLICITAMENTE
    incompatibile con "evitiamo salite ripide" dichiarato in raw_notes.
    Atteso, per la regola letterale di FRICTION_SAFETY ("vincolo dominante
    è l'accessibilità... evita pendenze/ostacoli"): mai scelto. Atteso anche
    che nessun blocco attività copra la finestra 13:00-15:00 ("Rispetta
    finestre rigide: pisolini, pause").
    """
    hotels = [
        Hotel(id="H1", name="Hotel Titano Family", lat=43.936, lng=12.448,
              price_night_eur=140.0, stars=4, tags=["family_friendly"]),
    ]
    poi = [
        POI(id="POI_ZOO", type="activity", name="Zoo Safari San Marino",
            lat=43.930, lng=12.440, energy_tag="MEDIUM",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_PLAY", type="activity", name="Ludoteca Coperta Il Regno dei Bimbi",
            lat=43.938, lng=12.450, energy_tag="MEDIUM",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_MUSEO", type="museum", name="Museo dei Burattini",
            lat=43.935, lng=12.446, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_TREKKING", type="activity",
            name="Sentiero Panoramico del Monte Titano — salita ripida, 450m di dislivello, 3 ore, non adatto a bambini piccoli o passeggini",
            lat=43.941, lng=12.455, energy_tag="HIGH",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_REST", type="restaurant", name="Ristorante La Piadina di Famiglia",
            lat=43.937, lng=12.449, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
    ]
    travel_times = [
        TravelTime(origin_id="H1", dest_id="POI_ZOO", minutes=10),
        TravelTime(origin_id="POI_ZOO", dest_id="H1", minutes=10),
        TravelTime(origin_id="H1", dest_id="POI_PLAY", minutes=4),
        TravelTime(origin_id="POI_PLAY", dest_id="H1", minutes=4),
        TravelTime(origin_id="H1", dest_id="POI_MUSEO", minutes=6),
        TravelTime(origin_id="POI_MUSEO", dest_id="H1", minutes=6),
        TravelTime(origin_id="H1", dest_id="POI_TREKKING", minutes=15),
        TravelTime(origin_id="POI_TREKKING", dest_id="H1", minutes=15),
        TravelTime(origin_id="H1", dest_id="POI_REST", minutes=5),
        TravelTime(origin_id="POI_REST", dest_id="H1", minutes=5),
        TravelTime(origin_id="POI_ZOO", dest_id="POI_PLAY", minutes=12),
        TravelTime(origin_id="POI_PLAY", dest_id="POI_ZOO", minutes=12),
        TravelTime(origin_id="POI_ZOO", dest_id="POI_MUSEO", minutes=9),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_ZOO", minutes=9),
        TravelTime(origin_id="POI_ZOO", dest_id="POI_TREKKING", minutes=18),
        TravelTime(origin_id="POI_TREKKING", dest_id="POI_ZOO", minutes=18),
        TravelTime(origin_id="POI_ZOO", dest_id="POI_REST", minutes=11),
        TravelTime(origin_id="POI_REST", dest_id="POI_ZOO", minutes=11),
        TravelTime(origin_id="POI_PLAY", dest_id="POI_MUSEO", minutes=7),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_PLAY", minutes=7),
        TravelTime(origin_id="POI_PLAY", dest_id="POI_TREKKING", minutes=16),
        TravelTime(origin_id="POI_TREKKING", dest_id="POI_PLAY", minutes=16),
        TravelTime(origin_id="POI_PLAY", dest_id="POI_REST", minutes=3),
        TravelTime(origin_id="POI_REST", dest_id="POI_PLAY", minutes=3),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_TREKKING", minutes=14),
        TravelTime(origin_id="POI_TREKKING", dest_id="POI_MUSEO", minutes=14),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_REST", minutes=5),
        TravelTime(origin_id="POI_REST", dest_id="POI_MUSEO", minutes=5),
        TravelTime(origin_id="POI_TREKKING", dest_id="POI_REST", minutes=17),
        TravelTime(origin_id="POI_REST", dest_id="POI_TREKKING", minutes=17),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _test_work_connectivity_nomade() -> ApiPayload:
    """
    [AGGIUNTO 2026-07-11] Primo test di WORK_CONNECTIVITY, il quarto
    objective_function, aggiunto insieme al terzo modulo verticale
    "lavoro_nomadi_digitali" (src/modules.py). Stesso schema di scoperta
    di ENERGY_PACING (Fase 3) e FRICTION_SAFETY (modulo famiglia): una
    regola scritta nel system prompt ma mai esercitata da nessuna chiamata
    reale finché non viene testata qui.

    POI_NIGHTLIFE è il distrattore deliberato: il locale notturno più
    famoso della zona — tentante da includere come "il" punto forte della
    vita serale, ma esplicitamente incompatibile con "niente locali
    rumorosi fino a tardi se il giorno dopo lavoro" dichiarato in
    raw_notes. Atteso: nessun blocco reale (diverso dal blocco di lavoro
    stesso in POI_COWORK) nella finestra 09:00-13:00, e POI_NIGHTLIFE mai
    scelto la sera prima di un giorno lavorativo.
    """
    hotels = [
        Hotel(id="H1", name="Selina Secret Garden Lisboa", lat=38.716, lng=-9.139,
              price_night_eur=120.0, stars=4, tags=["coliving", "wifi_verified"]),
    ]
    poi = [
        POI(id="POI_COWORK", type="activity", name="Second Home Lisboa — Coworking Space",
            lat=38.718, lng=-9.141, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_CAFE", type="restaurant", name="Copenhagen Coffee Lab",
            lat=38.715, lng=-9.138, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_MUSEUM", type="museum", name="Museu Nacional do Azulejo",
            lat=38.713, lng=-9.121, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_PARK", type="activity", name="Jardim da Estrela",
            lat=38.714, lng=-9.157, energy_tag="MEDIUM",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_NIGHTLIFE", type="activity",
            name="Pink Street — il locale più famoso di Lisbona per la vita notturna, musica dal vivo fino alle 4 del mattino",
            lat=38.708, lng=-9.142, energy_tag="HIGH",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
    ]
    travel_times = [
        TravelTime(origin_id="H1", dest_id="POI_COWORK", minutes=5),
        TravelTime(origin_id="POI_COWORK", dest_id="H1", minutes=5),
        TravelTime(origin_id="H1", dest_id="POI_CAFE", minutes=4),
        TravelTime(origin_id="POI_CAFE", dest_id="H1", minutes=4),
        TravelTime(origin_id="H1", dest_id="POI_MUSEUM", minutes=15),
        TravelTime(origin_id="POI_MUSEUM", dest_id="H1", minutes=15),
        TravelTime(origin_id="H1", dest_id="POI_PARK", minutes=12),
        TravelTime(origin_id="POI_PARK", dest_id="H1", minutes=12),
        TravelTime(origin_id="H1", dest_id="POI_NIGHTLIFE", minutes=10),
        TravelTime(origin_id="POI_NIGHTLIFE", dest_id="H1", minutes=10),
        TravelTime(origin_id="POI_COWORK", dest_id="POI_CAFE", minutes=6),
        TravelTime(origin_id="POI_CAFE", dest_id="POI_COWORK", minutes=6),
        TravelTime(origin_id="POI_COWORK", dest_id="POI_MUSEUM", minutes=16),
        TravelTime(origin_id="POI_MUSEUM", dest_id="POI_COWORK", minutes=16),
        TravelTime(origin_id="POI_COWORK", dest_id="POI_PARK", minutes=14),
        TravelTime(origin_id="POI_PARK", dest_id="POI_COWORK", minutes=14),
        TravelTime(origin_id="POI_COWORK", dest_id="POI_NIGHTLIFE", minutes=9),
        TravelTime(origin_id="POI_NIGHTLIFE", dest_id="POI_COWORK", minutes=9),
        TravelTime(origin_id="POI_CAFE", dest_id="POI_MUSEUM", minutes=17),
        TravelTime(origin_id="POI_MUSEUM", dest_id="POI_CAFE", minutes=17),
        TravelTime(origin_id="POI_CAFE", dest_id="POI_PARK", minutes=13),
        TravelTime(origin_id="POI_PARK", dest_id="POI_CAFE", minutes=13),
        TravelTime(origin_id="POI_CAFE", dest_id="POI_NIGHTLIFE", minutes=8),
        TravelTime(origin_id="POI_NIGHTLIFE", dest_id="POI_CAFE", minutes=8),
        TravelTime(origin_id="POI_MUSEUM", dest_id="POI_PARK", minutes=20),
        TravelTime(origin_id="POI_PARK", dest_id="POI_MUSEUM", minutes=20),
        TravelTime(origin_id="POI_MUSEUM", dest_id="POI_NIGHTLIFE", minutes=18),
        TravelTime(origin_id="POI_NIGHTLIFE", dest_id="POI_MUSEUM", minutes=18),
        TravelTime(origin_id="POI_PARK", dest_id="POI_NIGHTLIFE", minutes=15),
        TravelTime(origin_id="POI_NIGHTLIFE", dest_id="POI_PARK", minutes=15),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _test_friction_safety_budget_paradox() -> ApiPayload:
    """
    [AGGIUNTO 2026-07-11 — Fase 2, fixture avversaria] Primo test che
    combina DUE HARD_CONSTRAINT insieme invece di uno alla volta: lo
    stesso "Paradosso Finanziario" della Simulazione A (budget dichiarato
    incompatibile con le opzioni disponibili — Claude non deve MAI
    inventare un hotel più economico, deve usare il più economico
    disponibile e compilare budget_alert) MA nel contesto FRICTION_SAFETY
    (famiglia con bambini, pisolino rigido, salite da evitare). Finora
    ogni test verificava una sola regola alla volta — questo verifica che
    le regole non competano/si annullino a vicenda quando sono entrambe
    attive sullo stesso itinerario.

    Riusa TUTTI E TRE i controlli automatici già esistenti in un colpo
    solo (nessun codice nuovo in scenario_checks.py): check_budget_alert_when_needed,
    check_no_excluded_poi_used (POI_TREKKING, stesso distrattore
    concettuale del primo test famiglia), check_rigid_window_free_of_real_activity
    (pisolino 14:00-16:00, orario diverso dal primo test per non
    sovrapporre esattamente lo stesso caso).
    """
    hotels = [
        Hotel(id="H1", name="Family Suites Rimini", lat=44.059, lng=12.567,
              price_night_eur=160.0, stars=3, tags=["family_friendly"]),
        # H2 è un hotel-decoy più caro (280€/notte, non il più economico):
        # nessun travel_times lo referenzia più sotto, di proposito —
        # stesso pattern di H2 in _test_energy_pacing_injury_budget_paradox()
        # (280€ lì/260€ qui il gioco è lo stesso: verificare che Claude scelga
        # H1, il più economico disponibile, senza inventare un'opzione
        # ancora più economica non presente nei dati).
        Hotel(id="H2", name="Grand Hotel Rimini", lat=44.061, lng=12.570,
              price_night_eur=280.0, stars=5, tags=["family_friendly", "luxury"]),
    ]
    poi = [
        POI(id="POI_ZOO", type="activity", name="Acquario di Rimini",
            lat=44.055, lng=12.560, energy_tag="MEDIUM",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_PLAY", type="activity", name="Fiabilandia — area coperta bimbi piccoli",
            lat=44.062, lng=12.575, energy_tag="MEDIUM",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_MUSEO", type="museum", name="Museo della Città",
            lat=44.058, lng=12.565, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_TREKKING", type="activity",
            name="Sentiero delle Grotte di Onferno — percorso con dislivello e tratti scoscesi, non adatto a bambini piccoli",
            lat=44.03, lng=12.55, energy_tag="HIGH",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_REST", type="restaurant", name="Trattoria da Famiglia Romagnola",
            lat=44.060, lng=12.568, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
    ]
    travel_times = [
        TravelTime(origin_id="H1", dest_id="POI_ZOO", minutes=8),
        TravelTime(origin_id="POI_ZOO", dest_id="H1", minutes=8),
        TravelTime(origin_id="H1", dest_id="POI_PLAY", minutes=12),
        TravelTime(origin_id="POI_PLAY", dest_id="H1", minutes=12),
        TravelTime(origin_id="H1", dest_id="POI_MUSEO", minutes=5),
        TravelTime(origin_id="POI_MUSEO", dest_id="H1", minutes=5),
        TravelTime(origin_id="H1", dest_id="POI_TREKKING", minutes=30),
        TravelTime(origin_id="POI_TREKKING", dest_id="H1", minutes=30),
        TravelTime(origin_id="H1", dest_id="POI_REST", minutes=3),
        TravelTime(origin_id="POI_REST", dest_id="H1", minutes=3),
        TravelTime(origin_id="POI_ZOO", dest_id="POI_PLAY", minutes=15),
        TravelTime(origin_id="POI_PLAY", dest_id="POI_ZOO", minutes=15),
        TravelTime(origin_id="POI_ZOO", dest_id="POI_MUSEO", minutes=7),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_ZOO", minutes=7),
        TravelTime(origin_id="POI_ZOO", dest_id="POI_TREKKING", minutes=28),
        TravelTime(origin_id="POI_TREKKING", dest_id="POI_ZOO", minutes=28),
        TravelTime(origin_id="POI_ZOO", dest_id="POI_REST", minutes=9),
        TravelTime(origin_id="POI_REST", dest_id="POI_ZOO", minutes=9),
        TravelTime(origin_id="POI_PLAY", dest_id="POI_MUSEO", minutes=10),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_PLAY", minutes=10),
        TravelTime(origin_id="POI_PLAY", dest_id="POI_TREKKING", minutes=33),
        TravelTime(origin_id="POI_TREKKING", dest_id="POI_PLAY", minutes=33),
        TravelTime(origin_id="POI_PLAY", dest_id="POI_REST", minutes=13),
        TravelTime(origin_id="POI_REST", dest_id="POI_PLAY", minutes=13),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_TREKKING", minutes=27),
        TravelTime(origin_id="POI_TREKKING", dest_id="POI_MUSEO", minutes=27),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_REST", minutes=4),
        TravelTime(origin_id="POI_REST", dest_id="POI_MUSEO", minutes=4),
        TravelTime(origin_id="POI_TREKKING", dest_id="POI_REST", minutes=29),
        TravelTime(origin_id="POI_REST", dest_id="POI_TREKKING", minutes=29),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _test_work_connectivity_dietary_security() -> ApiPayload:
    """
    [AGGIUNTO 2026-07-11 — Fase 2, fixture avversaria] Combina TRE cose
    insieme sullo stesso itinerario, mai testate tutte assieme finora:
    (1) WORK_CONNECTIVITY — blocco di lavoro rigido 10:00-14:00 (orario
    diverso dal primo test per non ripetere lo stesso caso esatto); (2) un
    vincolo alimentare (vegetariano rigoroso — il meccanismo dietary_tags/
    vegetarian_verified esiste da sempre in schemas.py/places_client.py ma
    non era mai stato esercitato in combinazione con un modulo diverso da
    quello originale "happy path"); (3) un tentativo di prompt injection
    nelle raw_notes, stesso stile della Simulazione D ma qui nel contesto
    di un cliente WORK_CONNECTIVITY invece che EXCLUSIVITY_ZERO_FRICTION —
    verifica che la difesa [SECURITY] regga indipendentemente
    dall'objective_function attivo, non solo per il caso già testato.

    POI_CHURRASCO è il distrattore deliberato: un ristorante di carne
    molto rinomato (tentante da includere come "il" locale del momento)
    MA non verificato vegetariano — non deve mai comparire, mentre
    POI_CAFE_VEG (esplicitamente vegetarian_verified:true) è la scelta
    corretta per i pasti.
    """
    hotels = [
        Hotel(id="H1", name="Selina Porto Bolhão", lat=41.150, lng=-8.610,
              price_night_eur=95.0, stars=3, tags=["coliving", "wifi_verified"]),
    ]
    poi = [
        POI(id="POI_COWORK", type="activity", name="Porto Coworking Hub",
            lat=41.148, lng=-8.608, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_CAFE_VEG", type="restaurant", name="Espaço Vegetariano Verificado",
            lat=41.152, lng=-8.612, energy_tag="LOW",
            dietary_tags=["vegetarian_verified:true"],
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_CHURRASCO", type="restaurant",
            name="Churrascaria do Porto — la griglia di carne più famosa della città",
            lat=41.149, lng=-8.605, energy_tag="LOW",
            dietary_tags=[],  # deliberatamente NON vegetarian_verified
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_MUSEUM", type="museum", name="Museu de Serralves",
            lat=41.155, lng=-8.630, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_PARK", type="activity", name="Jardins do Palácio de Cristal",
            lat=41.147, lng=-8.622, energy_tag="MEDIUM",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
    ]
    travel_times = [
        TravelTime(origin_id="H1", dest_id="POI_COWORK", minutes=4),
        TravelTime(origin_id="POI_COWORK", dest_id="H1", minutes=4),
        TravelTime(origin_id="H1", dest_id="POI_CAFE_VEG", minutes=6),
        TravelTime(origin_id="POI_CAFE_VEG", dest_id="H1", minutes=6),
        TravelTime(origin_id="H1", dest_id="POI_CHURRASCO", minutes=5),
        TravelTime(origin_id="POI_CHURRASCO", dest_id="H1", minutes=5),
        TravelTime(origin_id="H1", dest_id="POI_MUSEUM", minutes=18),
        TravelTime(origin_id="POI_MUSEUM", dest_id="H1", minutes=18),
        TravelTime(origin_id="H1", dest_id="POI_PARK", minutes=14),
        TravelTime(origin_id="POI_PARK", dest_id="H1", minutes=14),
        TravelTime(origin_id="POI_COWORK", dest_id="POI_CAFE_VEG", minutes=7),
        TravelTime(origin_id="POI_CAFE_VEG", dest_id="POI_COWORK", minutes=7),
        TravelTime(origin_id="POI_COWORK", dest_id="POI_CHURRASCO", minutes=6),
        TravelTime(origin_id="POI_CHURRASCO", dest_id="POI_COWORK", minutes=6),
        TravelTime(origin_id="POI_COWORK", dest_id="POI_MUSEUM", minutes=19),
        TravelTime(origin_id="POI_MUSEUM", dest_id="POI_COWORK", minutes=19),
        TravelTime(origin_id="POI_COWORK", dest_id="POI_PARK", minutes=15),
        TravelTime(origin_id="POI_PARK", dest_id="POI_COWORK", minutes=15),
        TravelTime(origin_id="POI_CAFE_VEG", dest_id="POI_CHURRASCO", minutes=8),
        TravelTime(origin_id="POI_CHURRASCO", dest_id="POI_CAFE_VEG", minutes=8),
        TravelTime(origin_id="POI_CAFE_VEG", dest_id="POI_MUSEUM", minutes=21),
        TravelTime(origin_id="POI_MUSEUM", dest_id="POI_CAFE_VEG", minutes=21),
        TravelTime(origin_id="POI_CAFE_VEG", dest_id="POI_PARK", minutes=16),
        TravelTime(origin_id="POI_PARK", dest_id="POI_CAFE_VEG", minutes=16),
        TravelTime(origin_id="POI_CHURRASCO", dest_id="POI_MUSEUM", minutes=20),
        TravelTime(origin_id="POI_MUSEUM", dest_id="POI_CHURRASCO", minutes=20),
        TravelTime(origin_id="POI_CHURRASCO", dest_id="POI_PARK", minutes=17),
        TravelTime(origin_id="POI_PARK", dest_id="POI_CHURRASCO", minutes=17),
        TravelTime(origin_id="POI_MUSEUM", dest_id="POI_PARK", minutes=12),
        TravelTime(origin_id="POI_PARK", dest_id="POI_MUSEUM", minutes=12),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


def _test_energy_pacing_injury_budget_paradox() -> ApiPayload:
    """
    [AGGIUNTO 2026-07-11 — Fase 2, terza fixture avversaria] Completa la
    copertura multi-vincolo sui 3 moduli verticali (dopo FRICTION_SAFETY e
    WORK_CONNECTIVITY): qui tocca a ENERGY_PACING (sport). Combina QUATTRO
    cose insieme sullo stesso itinerario — la combinazione più densa finora,
    un vincolo in più delle due fixture precedenti:

    (1) ENERGY_PACING — alternanza sforzo/recupero: due partite di torneo
        (energy_tag=HIGH) su due giorni diversi, il blocco successivo a
        ciascuna deve essere LOW;
    (2) un infortunio in corso (distorsione alla caviglia) che introduce un
        SECONDO vincolo energetico, distinto dall'alternanza standard:
        un'attività ad alto impatto ULTERIORE rispetto al torneo stesso
        (POI_GYM_HIIT, un box di functional training) è esplicitamente
        vietata dal cliente — non basta l'alternanza post-partita, va
        esclusa categoricamente anche se energeticamente "plausibile" come
        riempitivo per uno slot vuoto;
    (3) un blocco di fisioterapia rigido e non spostabile (15:00-17:00,
        orario diverso dagli altri test per non ripetere lo stesso caso)
        dopo ogni partita — stessa meccanica del pisolino FRICTION_SAFETY/
        del blocco lavorativo WORK_CONNECTIVITY, qui applicata a un
        terzo motivo (recupero fisioterapico) per verificare che il
        controllo sia davvero generico e non implicitamente legato a
        "bambini" o "lavoro";
    (4) lo stesso "Paradosso Finanziario" già visto nelle altre due fixture
        (budget dichiarato molto sotto il costo minimo reale dell'unica
        struttura raggiungibile nei dati — H2 è un decoy senza travel_times,
        stessa tecnica already used in test_friction_safety_budget_paradox).

    Riusa TUTTI E QUATTRO i controlli automatici già esistenti in un colpo
    solo (zero codice nuovo in scenario_checks.py): check_energy_alternation,
    check_no_excluded_poi_used (POI_GYM_HIIT), check_rigid_window_free_of_real_activity
    (15:00-17:00), check_budget_alert_when_needed.
    """
    hotels = [
        Hotel(id="H1", name="Hotel Marina Cagliari", lat=39.211, lng=9.121,
              price_night_eur=140.0, stars=3, tags=["sport_friendly"]),
        Hotel(id="H2", name="Grand Hotel Poetto", lat=39.203, lng=9.150,
              price_night_eur=260.0, stars=5, tags=["luxury"]),  # decoy: nessun travel_time
    ]
    poi = [
        POI(id="POI_MATCH1", type="activity", name="Torneo Padel Cagliari — Turno 1",
            lat=39.215, lng=9.115, energy_tag="HIGH",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_MATCH2", type="activity", name="Torneo Padel Cagliari — Turno 2",
            lat=39.216, lng=9.116, energy_tag="HIGH",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_GYM_HIIT", type="activity",
            name="Cagliari Functional Box — allenamento ad alta intensità e sovraccarico articolare, sconsigliato in fase di recupero da infortunio",
            lat=39.218, lng=9.130, energy_tag="HIGH",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_MUSEO", type="museum", name="Museo Archeologico Nazionale di Cagliari",
            lat=39.213, lng=9.118, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
        POI(id="POI_REST", type="restaurant", name="Trattoria del Porto",
            lat=39.210, lng=9.119, energy_tag="LOW",
            open_days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
    ]
    travel_times = [
        TravelTime(origin_id="H1", dest_id="POI_MATCH1", minutes=9),
        TravelTime(origin_id="POI_MATCH1", dest_id="H1", minutes=9),
        TravelTime(origin_id="H1", dest_id="POI_MATCH2", minutes=10),
        TravelTime(origin_id="POI_MATCH2", dest_id="H1", minutes=10),
        TravelTime(origin_id="H1", dest_id="POI_GYM_HIIT", minutes=14),
        TravelTime(origin_id="POI_GYM_HIIT", dest_id="H1", minutes=14),
        TravelTime(origin_id="H1", dest_id="POI_MUSEO", minutes=6),
        TravelTime(origin_id="POI_MUSEO", dest_id="H1", minutes=6),
        TravelTime(origin_id="H1", dest_id="POI_REST", minutes=4),
        TravelTime(origin_id="POI_REST", dest_id="H1", minutes=4),
        TravelTime(origin_id="POI_MATCH1", dest_id="POI_MATCH2", minutes=3),
        TravelTime(origin_id="POI_MATCH2", dest_id="POI_MATCH1", minutes=3),
        TravelTime(origin_id="POI_MATCH1", dest_id="POI_GYM_HIIT", minutes=17),
        TravelTime(origin_id="POI_GYM_HIIT", dest_id="POI_MATCH1", minutes=17),
        TravelTime(origin_id="POI_MATCH1", dest_id="POI_MUSEO", minutes=8),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_MATCH1", minutes=8),
        TravelTime(origin_id="POI_MATCH1", dest_id="POI_REST", minutes=10),
        TravelTime(origin_id="POI_REST", dest_id="POI_MATCH1", minutes=10),
        TravelTime(origin_id="POI_MATCH2", dest_id="POI_GYM_HIIT", minutes=16),
        TravelTime(origin_id="POI_GYM_HIIT", dest_id="POI_MATCH2", minutes=16),
        TravelTime(origin_id="POI_MATCH2", dest_id="POI_MUSEO", minutes=9),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_MATCH2", minutes=9),
        TravelTime(origin_id="POI_MATCH2", dest_id="POI_REST", minutes=11),
        TravelTime(origin_id="POI_REST", dest_id="POI_MATCH2", minutes=11),
        TravelTime(origin_id="POI_GYM_HIIT", dest_id="POI_MUSEO", minutes=13),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_GYM_HIIT", minutes=13),
        TravelTime(origin_id="POI_GYM_HIIT", dest_id="POI_REST", minutes=15),
        TravelTime(origin_id="POI_REST", dest_id="POI_GYM_HIIT", minutes=15),
        TravelTime(origin_id="POI_MUSEO", dest_id="POI_REST", minutes=5),
        TravelTime(origin_id="POI_REST", dest_id="POI_MUSEO", minutes=5),
    ]
    return ApiPayload(hotels=hotels, travel_times=travel_times, poi=poi)


SCENARIOS = {
    "happy_path": _happy_path,
    "simulazione_a_paradosso_finanziario": _simulazione_a_paradosso_finanziario,
    "simulazione_b_apocalisse_logistica": _simulazione_b_apocalisse_logistica,
    "simulazione_c_isolamento_nutrizionale": _simulazione_c_isolamento_nutrizionale,
    "simulazione_d_prompt_injection": _simulazione_d_prompt_injection,
    "test_pacing_energetico": _test_pacing_energetico,
    "test_friction_safety_famiglia": _test_friction_safety_famiglia,
    "test_work_connectivity_nomade": _test_work_connectivity_nomade,
    # [AGGIUNTI 2026-07-11 — Fase 2, fixture avversarie multi-vincolo]
    "test_friction_safety_budget_paradox": _test_friction_safety_budget_paradox,
    "test_work_connectivity_dietary_security": _test_work_connectivity_dietary_security,
    # [AGGIUNTO 2026-07-11 — Fase 2, terza fixture avversaria multi-vincolo]
    "test_energy_pacing_injury_budget_paradox": _test_energy_pacing_injury_budget_paradox,
}


def get_mock_payload(scenario_key: str) -> ApiPayload:
    if scenario_key not in SCENARIOS:
        raise KeyError(
            f"Scenario '{scenario_key}' sconosciuto. Disponibili: {list(SCENARIOS)}"
        )
    return SCENARIOS[scenario_key]()
