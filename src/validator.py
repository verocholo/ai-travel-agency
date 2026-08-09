"""
NODO 9 — Parse & Sanitize. HTTP_MODULES_REALI.md §NODO 9 / BLUEPRINT_MAKE.md
§NODO 9. Tre controlli, nell'ordine documentato:
  [9.1] Parse JSON
  [9.2] [Filter] format-compliance
  [9.3] Verifica Fedeltà RAG (KPI 100%, Cap. 7.4 del business plan)
  [9.4] Scarto scratchpad (reasoning va solo in log/Airtable, non nel PDF)
"""
from __future__ import annotations
import copy
import json
import re
from dataclasses import dataclass, field

# [AGGIUNTO 2026-08-02 — task #166] Tabella delle durate tipiche e soglie di
# ritmo: sono le stesse che il renderer usa per scrivere il margine al
# cliente. Una sola copia, così il warning all'operatore e la frase nel PDF
# non possono raccontare due storie diverse.
from . import pacing


class ParseError(Exception):
    pass


# [AGGIUNTO 2026-07-11 — capstone live test #3 (lavoro/Lisbona), bug reale
# scoperto dal vivo] `[OUTPUT_CONTRACT]` in system_prompt_master.txt dice
# esplicitamente "NIENTE fence markdown", ma è solo un'istruzione testuale
# senza alcuna difesa strutturale a monte: l'assistant-prefill (che
# avrebbe forzato il primo carattere a "{") è stato disabilitato il
# 2026-07-10 perché questo modello lo rifiuta con un 400 (vedi
# claude_engine.py::call_claude()). Sul primo test dal vivo mai eseguito
# sul modulo lavoro, Claude ha comunque avvolto l'intero JSON in una fence
# ```json ... ``` nonostante l'istruzione — variabilità del modello che
# nessuna delle due sessioni di audit di qualità precedenti (mattina e
# secondo giro) aveva rilevato, perché non era mai stata esercitata da un
# vero test dal vivo su questo modulo. `json.loads()` falliva con
# "Expecting value: line 1 column 1" perché il primo carattere reale era
# un backtick, non "{". Fix: rimozione difensiva della fence PRIMA del
# parsing, solo se l'intero testo (dopo strip degli spazi) è delimitato da
# ```/```json all'inizio e ``` alla fine — un match volutamente stretto
# (non una sostituzione permissiva di ``` ovunque nel testo) per non
# rischiare di alterare contenuto legittimo dentro stringhe JSON che
# contenessero triple-backtick. Stesso principio di resilienza già
# applicato altrove nel prototipo (places_client.py/liteapi_client.py:
# scarta un elemento malformato invece di far fallire tutto;
# distance_matrix.py: tollera il fallimento della modalità secondaria):
# la difesa robusta è nel codice, non solo nell'istruzione al modello.
# [AGGIORNATO 2026-07-31 — audit di perfezionamento] `re.IGNORECASE` aggiunto:
# il pattern gestiva solo il tag lowercase ```` ```json ````, ma un modello LLM
# emette con la stessa plausibilità ```` ```JSON ```` (variabilità reale già
# osservata per la fence stessa). Senza IGNORECASE, un JSON perfettamente valido
# avvolto in ```` ```JSON ```` veniva RIFIUTATO con ParseError — stessa classe di
# bug del capstone Lisbona, solo sulla capitalizzazione del tag.
_MARKDOWN_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)


def _strip_markdown_json_fence(raw_text: str) -> str:
    """Se `raw_text` (dopo strip degli spazi) è interamente racchiuso in
    una fence markdown (```json ... ``` oppure ``` ... ```), ne restituisce
    solo il contenuto interno. Altrimenti restituisce `raw_text` invariato
    — nessun effetto per l'output già conforme a [OUTPUT_CONTRACT]."""
    stripped = raw_text.strip()
    match = _MARKDOWN_JSON_FENCE_RE.match(stripped)
    return match.group(1) if match else raw_text


@dataclass
class ValidationReport:
    format_compliance_ok: bool = True
    format_errors: list[str] = field(default_factory=list)
    rag_fidelity_ok: bool = True
    hallucinated_poi_ids: list[str] = field(default_factory=list)
    geospatial_overlap_ok: bool = True
    geospatial_errors: list[str] = field(default_factory=list)
    # [AGGIUNTO 2026-07-12 — bug reale trovato dal vivo da Lorenzo, leggendo
    # un vero PDF cliente generato: "15 min in auto da POI2" invece di "15
    # min in auto da Terme di San Filippo"] Vedi check_no_raw_id_leakage()
    # sotto per il razionale completo.
    no_id_leakage_ok: bool = True
    leaked_raw_ids: list[str] = field(default_factory=list)
    # [AGGIUNTI 2026-07-12 — richiesta di Lorenzo di "certezza matematica
    # sulla qualità"] Vedi check_energy_pacing()/check_budget_compliance()
    # sopra: prima questi due HARD_CONSTRAINTS (pacing energetico, alert di
    # budget) erano verificati SOLO per scenari di test specifici, mai come
    # parte del Nodo 9 universale. Default True/[] (no-op) quando i
    # parametri opzionali di validate_itinerary non vengono passati —
    # nessuna rottura per i chiamanti esistenti.
    energy_pacing_ok: bool = True
    energy_pacing_violations: list[str] = field(default_factory=list)
    budget_compliance_ok: bool = True
    budget_compliance_violations: list[str] = field(default_factory=list)
    # [AGGIUNTO 2026-07-31 — feedback diretto di Lorenzo dopo un viaggio
    # reale: giornate troppo vuote / attività brevi gonfiate a 3 ore]
    # Warning NON bloccanti (non toccano `passed`): densità/durata è in
    # parte un giudizio (vedi certainty-matrix.md), quindi qui SEGNALIAMO
    # all'operatore/Make senza bocciare il documento — la difesa primaria è
    # la regola [HARD_CONSTRAINTS] punto 9 nel system prompt, questo è il
    # termometro strutturale che rende visibile quando non viene rispettata.
    day_density_warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.format_compliance_ok
            and self.rag_fidelity_ok
            and self.geospatial_overlap_ok
            and self.no_id_leakage_ok
            and self.energy_pacing_ok
            and self.budget_compliance_ok
        )

    def summary(self) -> str:
        lines = [f"PASS" if self.passed else "FAIL — vedi dettagli sotto"]
        if not self.format_compliance_ok:
            lines += [f"  [format] {e}" for e in self.format_errors]
        if not self.rag_fidelity_ok:
            lines.append(
                f"  [Fedeltà RAG] poi_id allucinati (non presenti nei dati forniti): "
                f"{self.hallucinated_poi_ids}"
            )
        if not self.geospatial_overlap_ok:
            lines += [f"  [geospaziale] {e}" for e in self.geospatial_errors]
        if not self.no_id_leakage_ok:
            lines += [f"  [leak id] {e}" for e in self.leaked_raw_ids]
        if not self.energy_pacing_ok:
            lines += [f"  [pacing energetico] {e}" for e in self.energy_pacing_violations]
        if not self.budget_compliance_ok:
            lines += [f"  [budget] {e}" for e in self.budget_compliance_violations]
        if self.day_density_warnings:
            lines += [f"  [warning densità — non bloccante] {w}" for w in self.day_density_warnings]
        return "\n".join(lines)


def parse_claude_output(raw_text: str) -> dict:
    """[9.1] Parse JSON. Solleva ParseError se non è JSON valido —
    nel Make.com reale questo attiva il repair/retry (Cap. 7.2).

    [AGGIORNATO 2026-07-11 — bug reale dal capstone live test lavoro/Lisbona]
    Prima del parsing vero e proprio, rimuove una eventuale fence markdown
    che avvolge l'intero output (```json ... ```) — vedi
    _strip_markdown_json_fence() sopra per il razionale completo. Se il
    testo non è affatto racchiuso in una fence, il comportamento è
    identico a prima (nessuna regressione per l'output già conforme)."""
    text = _strip_markdown_json_fence(raw_text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ParseError(f"Output di Claude non è JSON valido: {e}") from e
    # [AGGIUNTO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    # `json.loads` accetta QUALSIASI valore JSON top-level: un array `[...]`,
    # uno scalare (`42`, `"ciao"`, `null`) sono JSON validi ma NON un itinerario.
    # Prima venivano restituiti tali e quali e facevano crashare a valle
    # (`'list'/'int' object has no attribute 'get'`) in pipeline/validator, fuori
    # da qualsiasi try/except — un traceback grezzo (→ HTTP 500) invece del
    # ParseError pulito che è lo scopo del Nodo 9. La docstring promette `-> dict`:
    # ora il contratto è fatto rispettare qui, all'unico punto di ingresso.
    if not isinstance(parsed, dict):
        raise ParseError(
            f"Output di Claude è JSON valido ma non è un oggetto (trovato "
            f"{type(parsed).__name__}): un itinerario deve essere un oggetto JSON."
        )
    return parsed


def check_format_compliance(
    itinerary: dict, expected_duration_days: int | None = None
) -> tuple[bool, list[str]]:
    """[9.2] — stesso set di condizioni AND documentato in HTTP_MODULES_REALI.md.

    [AGGIUNTO 2026-07-12 — audit di potenziamento massimo, gap reale] Prima
    esisteva solo un controllo generico "days[] è vuoto" — un singolo
    giorno con `blocks: []` (nessun blocco, ma l'oggetto giorno presente)
    passava indenne: nessuna attività, nessun pasto, nessun [SLOT LIBERO],
    semplicemente un giorno "vuoto" nel documento cliente senza che nulla
    lo segnalasse. Anche `len(days)` non era mai confrontato con
    `trip.duration_days`: un itinerario di 3 giorni che ne restituisse solo
    2 (o 4, con un duplicato) passava format_compliance ugualmente, perché
    nessun controllo lo confrontava con la durata dichiarata dal cliente.
    Entrambi corretti qui, in modo retrocompatibile:
    `expected_duration_days` è opzionale (default None = comportamento
    pre-esistente, nessuna rottura per chi non lo passa).

    [AGGIUNTO 2026-07-12 — audit di revisione completa, richiesta di
    Lorenzo di "certezza matematica"] Prima, una risposta di Claude
    tecnicamente JSON-valida ma con una forma inattesa — `days` non una
    lista (es. un dict), un elemento di `days` non un dict (es. una
    stringa), `blocks` non una lista, o un elemento di `blocks` non un
    dict — faceva crashare questa funzione con un `AttributeError`/
    `TypeError` grezzo invece di produrre il FAIL pulito che è l'intero
    scopo del Nodo 9 (dimostrato riproducendo ciascun caso direttamente).
    Nessun `try/except` in `pipeline.py` avvolge questa chiamata (a
    differenza di altri fallimenti già gestiti altrove nello stesso file),
    quindi un output sufficientemente malformato di Claude avrebbe fatto
    fallire l'intera richiesta con un traceback invece di un report di
    validazione leggibile. Ora ogni forma inattesa produce un errore
    esplicito in `errors` ed è saltata in sicurezza, mai un crash."""
    errors = []
    # [AGGIUNTO 2026-07-31 — audit di perfezionamento] guardia sul tipo
    # dell'itinerario stesso: se Claude emette un array/scalare top-level (che
    # `parse_claude_output` ora già respinge, ma la funzione è anche chiamata
    # direttamente altrove/nei test), `itinerary.get(...)` crasherebbe. FAIL
    # pulito invece del crash — coerente con "mai un crash" del docstring.
    if not isinstance(itinerary, dict):
        return (False, [f"itinerario non è un oggetto JSON (trovato {type(itinerary).__name__})"])
    days = itinerary.get("days")
    if not isinstance(days, list):
        errors.append(f"days deve essere una lista, trovato {type(days).__name__}")
        days = []
    if len(days) == 0:
        errors.append("days[] è vuoto")
    day_numbers = []
    for day in days:
        if not isinstance(day, dict):
            errors.append(f"un elemento di days[] non è un oggetto valido (trovato {type(day).__name__}): {day!r}")
            continue
        day_numbers.append(day.get("day"))
        blocks = day.get("blocks", [])
        if not isinstance(blocks, list):
            errors.append(f"giorno {day.get('day')}: blocks deve essere una lista, trovato {type(blocks).__name__}")
            blocks = []
        if len(blocks) == 0:
            errors.append(f"giorno {day.get('day')}: blocks[] è vuoto (nessuna attività, nemmeno [SLOT LIBERO])")
        for block in blocks:
            if not isinstance(block, dict):
                errors.append(f"giorno {day.get('day')}: un elemento di blocks[] non è un oggetto valido (trovato {type(block).__name__}): {block!r}")
                continue
            if not block.get("time"):
                errors.append(f"giorno {day.get('day')}: blocco senza 'time'")
            if not block.get("activity"):
                errors.append(f"giorno {day.get('day')}: blocco senza 'activity'")
    if expected_duration_days is not None:
        if len(days) != expected_duration_days:
            errors.append(
                f"days[] ha {len(days)} elementi, attesi esattamente {expected_duration_days} "
                f"(trip.duration_days)"
            )
        expected_numbers = list(range(1, expected_duration_days + 1))
        # [AGGIUNTO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
        # `sorted(...)` su numeri di giorno di TIPO MISTO (es. `[1, "2"]`, se
        # Claude emette un "day" come stringa) sollevava
        # `TypeError: '<' not supported between 'str' and 'int'` — crash proprio
        # nella funzione che promette "mai un crash". Filtro ai soli interi:
        # un "day" non-intero non può comunque combaciare con la numerazione
        # attesa, quindi il mismatch viene già segnalato dal ramo sotto.
        sortable = sorted(n for n in day_numbers if isinstance(n, int))
        if day_numbers != expected_numbers and sortable != expected_numbers:
            errors.append(
                f"giorni numerati {day_numbers}, attesi 1..{expected_duration_days} senza buchi né duplicati"
            )
    if not itinerary.get("destination"):
        errors.append("destination è vuoto")
    return (len(errors) == 0, errors)


def check_rag_fidelity(itinerary: dict, valid_ids: set[str]) -> tuple[bool, list[str]]:
    """
    [9.3] KPI 100% — Cap. 7.4 del business plan (Fedeltà RAG / Grounding).
    Ogni blocks[].poi_id non-null deve esistere tra gli id forniti al Nodo 7.
    """
    hallucinated = []
    for day in itinerary.get("days", []) or []:
        if not isinstance(day, dict):
            continue
        for block in day.get("blocks", []) or []:
            if not isinstance(block, dict):
                continue
            poi_id = block.get("poi_id")
            if poi_id is None:
                continue
            # [AGGIUNTO 2026-07-12 — audit di revisione completa] un
            # `poi_id` di tipo non hashable (es. una lista, se Claude
            # producesse una forma inattesa) faceva sollevare un
            # `TypeError: unhashable type` da `poi_id not in valid_ids`
            # (un set) — riprodotto direttamente. Un id di tipo scorretto
            # non è comunque un id valido: trattato qui come allucinato
            # invece di far crashare l'intero Nodo 9.
            try:
                is_valid = poi_id in valid_ids
            except TypeError:
                hallucinated.append(poi_id)
                continue
            if not is_valid:
                hallucinated.append(poi_id)
    return (len(hallucinated) == 0, hallucinated)


def check_no_raw_id_leakage(itinerary: dict, valid_ids: set[str]) -> tuple[bool, list[str]]:
    """
    [AGGIUNTO 2026-07-12 — bug reale trovato dal vivo da Lorenzo, leggendo
    un vero PDF cliente generato] `check_rag_fidelity()` verifica che il
    campo STRUTTURATO "poi_id" referenzi solo id reali — ma non impedisce
    che Claude scriva lo STESSO id grezzo (es. "H1", "POI2") anche dentro un
    campo di testo libero rivolto al cliente (executive_summary, activity,
    location, logistics, title del giorno, architect_tips, budget_alert).
    Osservato due volte in PDF reali generati sul PC di Lorenzo: "15 min in
    auto daH1" e, più spesso, nell'itinerario prodotto da `--refine`
    (probabile causa: il turno di affinamento riceve l'itinerario corrente
    già in JSON, con gli id "poi_id" ben visibili nel contesto, e Claude a
    volte li ricopia invece di tradurli nel nome reale).

    `system_prompt_master.txt` ora lo vieta esplicitamente
    (HARD_CONSTRAINTS punto 1, OUTPUT_CONTRACT punto 6), ma un'istruzione
    testuale non è mai una garanzia assoluta col comportamento di un LLM —
    stesso principio già applicato altrove in questo prototipo (la fence
    markdown è vietata da [OUTPUT_CONTRACT] eppure è stata comunque emessa
    una volta durante un test dal vivo, da cui la difesa STRUTTURALE
    aggiunta in `parse_claude_output()`). Qui la difesa strutturale è
    questo controllo: rileva se un id valido compare come TOKEN autonomo
    (bordi di parola espliciti, non una sottostringa di un'altra parola —
    così "H1" non farebbe scattare un falso positivo dentro, es., "aH15")
    in uno qualunque dei campi di testo libero del documento cliente.
    """
    leaked = []
    texts: list[tuple[str, str]] = []

    def _add(label: str, value) -> None:
        if isinstance(value, str) and value:
            texts.append((label, value))

    _add("destination", itinerary.get("destination"))
    _add("executive_summary", itinerary.get("executive_summary"))
    _add("budget_alert", itinerary.get("budget_alert"))
    for tip in itinerary.get("architect_tips") or []:
        _add("architect_tips", tip)
    # [AGGIORNATO 2026-07-31 — audit di perfezionamento] stesse guardie
    # isinstance già presenti in check_rag_fidelity: senza, una forma
    # `days`/`day`/`blocks`/`block` inattesa (None, non-dict) faceva crashare
    # questa funzione con AttributeError/TypeError invece del FAIL pulito.
    for day in itinerary.get("days") or []:
        if not isinstance(day, dict):
            continue
        _add(f"giorno {day.get('day')}: title", day.get("title"))
        for block in day.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            _add(f"giorno {day.get('day')}: activity", block.get("activity"))
            _add(f"giorno {day.get('day')}: location", block.get("location"))
            _add(f"giorno {day.get('day')}: logistics", block.get("logistics"))

    for vid in valid_ids:
        if not vid:
            continue
        # [AGGIUNTO 2026-07-12 — audit di revisione completa, bug reale
        # trovato ed eseguito] Senza `re.IGNORECASE`, un id leakato con una
        # capitalizzazione diversa (es. "h1" invece di "H1") passava
        # indenne — riprodotto direttamente:
        # check_no_raw_id_leakage({"executive_summary": "...da h1..."}, {"H1"})
        # ritornava (True, []), un falso PASS. La variabilità di
        # maiuscole/minuscole in un output LLM è un caso plausibile, non
        # teorico — esattamente il tipo di variabilità che questo
        # controllo esiste per intercettare.
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(vid)}(?![A-Za-z0-9_])", re.IGNORECASE)
        for label, text in texts:
            if pattern.search(text):
                leaked.append(f"id '{vid}' citato letteralmente in un campo di testo libero ({label}): {text!r}")

    return (len(leaked) == 0, leaked)


def check_energy_pacing(
    itinerary: dict, objective_function: str | None, poi_energy_by_id: dict | None
) -> tuple[bool, list[str]]:
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo di "certezza matematica
    sulla qualità"] HARD_CONSTRAINT punto 3 (`system_prompt_master.txt`,
    "GESTIONE ENERGIE: rispetta la regola di pacing della FUNZIONE
    OBIETTIVO attiva") era verificato SOLO da `scenario_checks.py::check_energy_alternation()`,
    e SOLO per gli scenari di test espliciti cablati a mano in
    `main.py::_apply_scenario_checks()` — MAI come parte del Nodo 9
    universale (`validate_itinerary()`), quindi mai su un vero cliente
    ENERGY_PACING che non corrispondesse esattamente a uno degli scenari
    hardcoded. Un itinerario reale che violasse l'alternanza energetica
    avrebbe potuto risultare "PASS" nel report di validazione — nessuno se
    ne sarebbe accorto senza rileggerlo a mano, esattamente il tipo di
    falso senso di sicurezza che questo intero file esiste per evitare.

    Qui diventa un controllo universale: si applica automaticamente a
    QUALSIASI itinerario con `objective_function == "ENERGY_PACING"` (per
    ogni altro profilo è un no-op, coerente con la formulazione letterale
    della regola in `[DYNAMIC_OBJECTIVE_FUNCTION]`, che la scopre solo per
    ENERGY_PACING), usando `poi_energy_by_id` costruito da
    `ApiPayload.poi[].energy_tag` — un campo già presente su OGNI POI,
    non solo su quelli degli scenari di test storici. Logica di
    rilevamento identica, verbatim, a `scenario_checks.check_energy_alternation()`
    (che ora delega qui — vedi la sua docstring per non duplicare la
    spiegazione, e per il principio anti-desync già applicato altrove in
    questo progetto per due liste/implementazioni parallele).
    """
    if objective_function != "ENERGY_PACING":
        return True, []
    poi_energy_by_id = poi_energy_by_id or {}
    violations = []
    days = itinerary.get("days", []) or []
    # [AGGIUNTO 2026-07-12 — audit di revisione completa, gap reale
    # trovato] La versione precedente controllava solo coppie ADIACENTI
    # ALL'INTERNO dello stesso giorno (`range(len(blocks) - 1)` per
    # ciascun giorno separatamente) — un blocco HIGH come ULTIMO blocco
    # del giorno N non veniva mai confrontato col PRIMO blocco del giorno
    # N+1, anche se quel primo blocco fosse a sua volta HIGH/MEDIUM (es.
    # partita serale seguita da un allenamento la mattina dopo). Corretto
    # concatenando tutti i blocchi di tutti i giorni in un'unica sequenza
    # cronologica prima di applicare la stessa regola di adiacenza —
    # stessa logica di rilevamento, ora senza il confine artificiale tra
    # un giorno e il successivo.
    all_blocks = []
    for day in days:
        if not isinstance(day, dict):
            continue
        for block in day.get("blocks", []) or []:
            if isinstance(block, dict):
                all_blocks.append((day.get("day"), block))
    # [AGGIUNTO 2026-07-31 — audit di perfezionamento, bug reale eseguito] un
    # `poi_id` non hashable (es. una lista, forma inattesa da Claude) faceva
    # sollevare `TypeError: unhashable type` da `poi_energy_by_id.get(poi_id)` —
    # stessa classe già chiusa in check_rag_fidelity ma non qui, e questo ramo
    # è SEMPRE attivo per i clienti ENERGY_PACING (il beachhead). Un id non-str
    # non è comunque in mappa: lo tratto come energia sconosciuta (None), non
    # crash.
    def _energy_of(block: dict):
        pid = block.get("poi_id")
        if not isinstance(pid, str):
            return None
        return poi_energy_by_id.get(pid)

    for i in range(len(all_blocks) - 1):
        current_day, current_block = all_blocks[i]
        next_day, next_block = all_blocks[i + 1]
        current_energy = _energy_of(current_block)
        if current_energy == "HIGH":
            next_energy = _energy_of(next_block)
            if next_energy not in (None, "LOW"):
                boundary = "" if current_day == next_day else f" (a cavallo tra giorno {current_day} e giorno {next_day})"
                violations.append(
                    f"Day {current_day}: dopo il blocco HIGH delle "
                    f"{current_block.get('time')} ('{current_block.get('poi_id')}') segue "
                    f"'{next_block.get('poi_id')}' con energy={next_energy} invece di "
                    f"LOW/riposo (blocco delle {next_block.get('time')} il giorno {next_day}){boundary}"
                )
    return (len(violations) == 0, violations)


def check_budget_compliance(
    itinerary: dict,
    budget_mode: str | None,
    budget_eur: float | None,
    min_cost_estimate: float | None = None,
) -> tuple[bool, list[str]]:
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo di "certezza matematica
    sulla qualità"] Stesso gap di check_energy_pacing() sopra, ma per
    HARD_CONSTRAINT punto 4 (BUDGET): `scenario_checks.py::check_budget_alert_when_needed()`
    esisteva già ma non era mai parte del Nodo 9 universale — solo di
    scenari di test specifici. Qui diventa un controllo universale,
    attivo per QUALSIASI itinerario con `budget_mode == "LIMITED"` (per
    "UNLIMITED" è un no-op, coerente con HARD_CONSTRAINT punto 4 stesso).
    `min_cost_estimate` è tipicamente il prezzo/notte dell'hotel più
    economico tra quelli forniti moltiplicato per `trip.duration_days` —
    calcolabile da `ApiPayload.hotels` per QUALSIASI itinerario, non solo
    per gli scenari di test storici che lo passavano a mano. Se assente
    (nessun hotel con prezzo noto), il controllo resta solo informativo,
    onestamente: non possiamo verificare la matematica senza un prezzo di
    riferimento, meglio dichiararlo esplicitamente che fingere una
    verifica che non stiamo facendo.
    """
    alert = itinerary.get("budget_alert")
    if budget_mode != "LIMITED":
        return True, []
    if min_cost_estimate is not None and budget_eur is not None and budget_eur < min_cost_estimate:
        if not alert:
            return False, [
                f"budget_mode=LIMITED, budget_eur={budget_eur} < costo minimo stimato "
                f"{min_cost_estimate}, ma budget_alert è null/vuoto — violazione"
            ]
    return True, []


def _time_to_minutes(hhmm: str) -> int | None:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def check_geospatial_coherence(itinerary: dict) -> tuple[bool, list[str]]:
    """
    Metrica "Coerenza Geospaziale" (Cap. 7.4, soglia 100%): controllo
    leggero di sovrapposizione oraria all'interno dello stesso giorno
    (i blocchi devono essere in ordine cronologico non decrescente).
    Non sostituisce una verifica spaziale piena, ma cattura la classe di
    errore più grave (blocchi fuori sequenza / sovrapposti).
    """
    errors = []
    # [AGGIORNATO 2026-07-31 — audit di perfezionamento] guardie isinstance
    # su days/day/blocks/block, come nelle altre funzioni del Nodo 9: una forma
    # inattesa (None, non-dict) faceva crashare questo controllo invece di
    # produrre il FAIL pulito. `or []` copre anche il caso `"days": null`.
    for day in itinerary.get("days") or []:
        if not isinstance(day, dict):
            continue
        blocks = day.get("blocks") or []
        if not isinstance(blocks, list):
            continue
        last_minutes = -1
        for block in blocks:
            if not isinstance(block, dict):
                continue
            minutes = _time_to_minutes(block.get("time", ""))
            if minutes is None:
                errors.append(
                    f"giorno {day.get('day')}: time '{block.get('time')}' non è HH:MM valido"
                )
                continue
            if minutes < last_minutes:
                errors.append(
                    f"giorno {day.get('day')}: blocco '{block.get('activity')}' alle "
                    f"{block.get('time')} è fuori sequenza cronologica"
                )
            last_minutes = minutes
    return (len(errors) == 0, errors)


# [AGGIUNTI 2026-07-31 — feedback diretto di Lorenzo dopo aver testato di
# persona un itinerario reale (interrail): "attività che richiedono poco
# tempo le fai di lunghezze enormi (3 ore), lasciando così il cliente ad
# annoiarsi in una città che non conosce"]
# Soglie volutamente GENEROSE rispetto alla tabella di [HARD_CONSTRAINTS]
# punto 9 nel system prompt: qui non stiamo giudicando se una singola visita
# è tarata bene (è un giudizio, vedi certainty-matrix.md), stiamo cercando la
# patologia strutturale — il buco di mezza giornata travestito da attività.
# 180 min è oltre il massimo di QUALSIASI riga della tabella tranne il grande
# museo nazionale (2h–3h), quindi un blocco che lo supera è quasi sempre
# diluizione, non densità.
_DENSITY_MAX_BLOCK_MINUTES = 180
# Una giornata piena (né di arrivo né di partenza) deve coprire mattina,
# pranzo, pomeriggio e sera: sotto i 5 blocchi è la "giornata con 3 sole
# attività diluite" che il punto 9 chiama esplicitamente fallimento del
# prodotto.
_DENSITY_MIN_BLOCKS_FULL_DAY = 5


def check_day_density(
    itinerary: dict,
    objective_function: str | None = None,
    poi_by_id: dict | None = None,
) -> list[str]:
    """
    Termometro strutturale della regola [HARD_CONSTRAINTS] punto 9
    ("DURATE REALISTICHE E GIORNATE PIENE", regola anti-noia).

    Restituisce SOLO una lista di warning, NON una coppia (ok, errori) come
    gli altri controlli del Nodo 9, ed è deliberatamente NON bloccante
    (`ValidationReport.passed` la ignora). Il razionale è quello scritto in
    `certainty-matrix.md`: "questa giornata è troppo vuota" è in parte un
    giudizio editoriale, non una proprietà matematicamente decidibile —
    bocciare un PDF su un giudizio significherebbe generare falsi FAIL su
    itinerari legittimi (una giornata di trekking di 6 ore È un blocco solo,
    ed è giusta). La difesa PRIMARIA resta la regola nel system prompt, che
    agisce a monte in generazione; questo controllo è il termometro che rende
    VISIBILE all'operatore (e a Make, via `_serialize_validation_report`)
    quando quella regola non è stata rispettata, invece di lasciare che il
    problema arrivi in silenzio fino al cliente — che è esattamente com'è
    arrivato a Lorenzo la prima volta.

    Due patologie rilevate:
      1) blocco gonfiato — durata implicita (orario del blocco successivo −
         orario del blocco) oltre `_DENSITY_MAX_BLOCK_MINUTES`;
      2) giornata scarna — giornata intera (né la prima né l'ultima, che sono
         legittimamente parziali per arrivo/partenza) con meno di
         `_DENSITY_MIN_BLOCKS_FULL_DAY` blocchi.

    L'ULTIMO blocco di ogni giornata non è mai valutato per la durata: non
    esiste un orario successivo da cui dedurla, e inventare una fine della
    giornata produrrebbe warning fantasma su ogni cena.

    `objective_function == "EXCLUSIVITY_ZERO_FRICTION"` disattiva entrambi i
    controlli: per quel profilo il vuoto è progettato (max 1 ancora forte al
    giorno, vedi `[DYNAMIC_OBJECTIVE_FUNCTION]`), quindi ogni warning sarebbe
    un falso positivo sistematico. Per gli altri profili i warning restano —
    sono informativi, e ENERGY_PACING/WORK_CONNECTIVITY hanno comunque il
    diritto di produrre blocchi lunghi purché siano blocchi ESPLICITI
    (recupero, lavoro), cosa che l'operatore vede leggendo il warning.

    [AGGIORNATO 2026-08-02 — task #166, "valuta tu caso per caso ma stacci
    molto attento"] La soglia sui blocchi gonfiati non è più un 180 uguale
    per tutti QUANDO si sa che luogo sia il blocco. Il difetto che Lorenzo
    ha riletto in un PDF generato DOPO l'introduzione di questo controllo
    era proprio un caso che il 180 non poteva vedere: una visita da 40
    minuti a cui erano state assegnate due ore e mezza. 150 < 180, nessun
    warning, difetto in chiaro nel documento del cliente.

    Con `poi_by_id` (mappa `place_id -> POI`, passata dalla pipeline che ce
    l'ha già in mano) la soglia diventa la durata tipica di QUEL tipo di
    luogo, dalla tabella eseguibile di `src/pacing.py`: si segnala quando
    il tempo assegnato eccede il massimo tipico di oltre
    `pacing.IDLE_WARNING_MINUTES`. Due ore in un grande museo passano; due
    ore davanti a una fontana no.

    Senza `poi_by_id` (chiamanti storici, e blocchi senza scheda Google:
    "passeggiata in centro" non ha un place_id) resta il vecchio taglio
    piatto a `_DENSITY_MAX_BLOCK_MINUTES`. Non è un ripiego pigro: senza
    sapere che luogo sia, una soglia stretta produrrebbe warning su
    itinerari legittimi, ed è esattamente il falso positivo sistematico che
    insegna a ignorare i warning.
    """
    if objective_function == "EXCLUSIVITY_ZERO_FRICTION":
        return []
    warnings: list[str] = []
    # Stesse guardie difensive di check_geospatial_coherence: una forma
    # inattesa non deve mai far crashare il Nodo 9.
    days = itinerary.get("days") or []
    if not isinstance(days, list):
        return []
    valid_days = [d for d in days if isinstance(d, dict)]
    last_index = len(valid_days) - 1
    for index, day in enumerate(valid_days):
        day_label = day.get("day")
        blocks_raw = day.get("blocks") or []
        if not isinstance(blocks_raw, list):
            continue
        blocks = [b for b in blocks_raw if isinstance(b, dict)]
        is_edge_day = index == 0 or index == last_index
        if not is_edge_day and len(blocks) < _DENSITY_MIN_BLOCKS_FULL_DAY:
            warnings.append(
                f"giorno {day_label}: solo {len(blocks)} blocchi per una giornata intera "
                f"(minimo di riferimento {_DENSITY_MIN_BLOCKS_FULL_DAY}: mattina, pranzo, "
                f"pomeriggio, sera) — rischio giornata vuota/cliente annoiato"
            )
        for position, block in enumerate(blocks[:-1]):
            start = _time_to_minutes(block.get("time", ""))
            end = _time_to_minutes(blocks[position + 1].get("time", ""))
            if start is None or end is None:
                continue
            duration = end - start
            # Un delta negativo è un blocco fuori sequenza: già segnalato
            # (come errore bloccante) da check_geospatial_coherence, qui
            # sarebbe solo rumore duplicato.
            if duration <= 0:
                continue
            poi = None
            if poi_by_id:
                poi = poi_by_id.get(pacing._poi_id_of(block))
            if poi is not None:
                # Soglia su misura del luogo.
                typical = pacing.typical_minutes_for(poi, start)
                excess = duration - typical[1]
                if excess > pacing.IDLE_WARNING_MINUTES:
                    warnings.append(
                        f"giorno {day_label}: blocco '{block.get('activity')}' delle "
                        f"{block.get('time')} occupa {duration / 60:.1f}h implicite ma la "
                        f"sosta dura di norma {pacing.describe_typical(typical)} — "
                        f"{pacing.describe_duration(excess)} di vuoto non programmato"
                    )
            elif duration > _DENSITY_MAX_BLOCK_MINUTES:
                hours = duration / 60
                warnings.append(
                    f"giorno {day_label}: blocco '{block.get('activity')}' delle "
                    f"{block.get('time')} occupa {hours:.1f}h implicite "
                    f"(soglia {_DENSITY_MAX_BLOCK_MINUTES // 60}h) — verificare che non sia "
                    f"un'attività breve diluita per riempire un buco"
                )
    return warnings


def validate_itinerary(
    itinerary: dict,
    valid_ids: set[str],
    expected_duration_days: int | None = None,
    objective_function: str | None = None,
    poi_energy_by_id: dict | None = None,
    budget_mode: str | None = None,
    budget_eur: float | None = None,
    min_cost_estimate: float | None = None,
    poi_by_id: dict | None = None,
) -> ValidationReport:
    """
    [AGGIORNATO 2026-07-12 — audit di potenziamento massimo] nuovo parametro
    opzionale `expected_duration_days` (default None, nessuna rottura per i
    chiamanti esistenti): se passato, `check_format_compliance` verifica
    anche che `days[]` abbia esattamente quel numero di elementi, numerati
    1..N senza buchi né duplicati — vedi il docstring di
    `check_format_compliance` per il razionale completo.

    [AGGIORNATO 2026-07-12 (bis) — richiesta di Lorenzo di "certezza
    matematica sulla qualità"] Altri quattro parametri opzionali
    (`objective_function`, `poi_energy_by_id`, `budget_mode`, `budget_eur`,
    `min_cost_estimate` — tutti default None, stesso principio di non
    rottura): se passati, attivano `check_energy_pacing()` e
    `check_budget_compliance()` a livello di Nodo 9 universale, non più
    solo per scenari di test specifici — vedi i docstring di quelle due
    funzioni sopra per il razionale completo.
    """
    report = ValidationReport()
    # [AGGIUNTO 2026-07-31 — audit di perfezionamento] guard top-level: se
    # l'itinerario non è un oggetto (parse_claude_output lo respinge già, ma
    # validate_itinerary è anche un punto di ingresso pubblico chiamabile
    # direttamente), fallisci pulito su format_compliance senza far girare gli
    # altri controlli su un tipo che li farebbe crashare.
    if not isinstance(itinerary, dict):
        report.format_compliance_ok = False
        report.format_errors = [f"itinerario non è un oggetto JSON (trovato {type(itinerary).__name__})"]
        return report
    report.format_compliance_ok, report.format_errors = check_format_compliance(
        itinerary, expected_duration_days=expected_duration_days
    )
    report.rag_fidelity_ok, report.hallucinated_poi_ids = check_rag_fidelity(itinerary, valid_ids)
    report.geospatial_overlap_ok, report.geospatial_errors = check_geospatial_coherence(itinerary)
    report.no_id_leakage_ok, report.leaked_raw_ids = check_no_raw_id_leakage(itinerary, valid_ids)
    report.energy_pacing_ok, report.energy_pacing_violations = check_energy_pacing(
        itinerary, objective_function, poi_energy_by_id
    )
    report.budget_compliance_ok, report.budget_compliance_violations = check_budget_compliance(
        itinerary, budget_mode, budget_eur, min_cost_estimate
    )
    # [AGGIUNTO 2026-07-31 — regola anti-noia, punto 9 di [HARD_CONSTRAINTS]]
    # Non tocca `report.passed` (vedi docstring di check_day_density): è un
    # termometro, non un filtro.
    # [AGGIORNATO 2026-08-02 — task #166] `poi_by_id` è opzionale: quando c'è,
    # la soglia dei blocchi gonfiati diventa specifica del tipo di luogo.
    report.day_density_warnings = check_day_density(
        itinerary, objective_function, poi_by_id
    )
    return report


def strip_reasoning(itinerary: dict) -> dict:
    """[9.4] — reasoning va solo in log/Airtable (audit), mai nel documento cliente.

    [CORRETTO 2026-07-11 — audit qualità pre-lancio] `dict(itinerary)` è
    una copia SHALLOW: rimuove "reasoning" in sicurezza (chiave di primo
    livello), ma `sanitized["days"]` restava lo STESSO oggetto di
    `itinerary["days"]` — nessun bug attivo oggi (pipeline.py oggi solo
    legge `sanitized`, non lo modifica), ma un trap latente: pipeline.py
    scrive sia `itinerary` (JSON grezzo, con reasoning, per l'audit log in
    output/*_raw.json) sia il documento cliente derivato da `sanitized` —
    un futuro passo di post-processing che modificasse `sanitized["days"]`
    in place corromperebbe silenziosamente anche il log di audit. Fix:
    deepcopy, così le due copie sono davvero indipendenti fin da subito.
    """
    sanitized = copy.deepcopy(itinerary)
    sanitized.pop("reasoning", None)
    return sanitized
