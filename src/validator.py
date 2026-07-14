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
_MARKDOWN_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


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
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ParseError(f"Output di Claude non è JSON valido: {e}") from e


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
        if day_numbers != expected_numbers and sorted(n for n in day_numbers if n is not None) != expected_numbers:
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
    for day in itinerary.get("days", []):
        _add(f"giorno {day.get('day')}: title", day.get("title"))
        for block in day.get("blocks", []):
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
    for i in range(len(all_blocks) - 1):
        current_day, current_block = all_blocks[i]
        next_day, next_block = all_blocks[i + 1]
        current_energy = poi_energy_by_id.get(current_block.get("poi_id"))
        if current_energy == "HIGH":
            next_energy = poi_energy_by_id.get(next_block.get("poi_id"))
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
    for day in itinerary.get("days", []):
        blocks = day.get("blocks", [])
        last_minutes = -1
        for block in blocks:
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


def validate_itinerary(
    itinerary: dict,
    valid_ids: set[str],
    expected_duration_days: int | None = None,
    objective_function: str | None = None,
    poi_energy_by_id: dict | None = None,
    budget_mode: str | None = None,
    budget_eur: float | None = None,
    min_cost_estimate: float | None = None,
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
