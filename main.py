#!/usr/bin/env python3
"""
CLI del prototipo AI Travel Agency. Vedi README.md per il setup.

Esempi:
  python main.py --fixture fixtures/trip_happy_path.json --scenario happy_path --mode mock
  python main.py --fixture fixtures/trip_simulazione_a_paradosso_finanziario.json \\
                  --scenario simulazione_a_paradosso_finanziario --mode mock
  python main.py --fixture fixtures/trip_happy_path.json --mode live
  python main.py --all-simulations   # esegue le 4 simulazioni di Chaos Engineering in mock mode
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import SETTINGS
from src.pipeline import run_mock, run_live
from src.mock_rag_data import get_mock_payload
from src.scenario_checks import (
    check_energy_alternation, check_budget_alert_when_needed,
    check_no_excluded_poi_used, check_rigid_window_free_of_real_activity,
    check_slot_libero_transparency,
)
from src import pdf_renderer
from src import guide_generator
from src import refinement
from src import freshness_check
from src import feedback_generator
from src import pdf_extras
from src.triage import normalize_raw_input
from src.modules import get_module_for_objective_function
from src.payload_builder import assemble_payload
from src.itinerary_utils import extract_used_poi_ids

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"

# [AGGIUNTO 2026-07-10] Mappa scenario -> quale controllo automatico
# applicare in più rispetto al Nodo 9 generico, e con quale contesto. Nato
# da un'autocritica: questi controlli erano fatti a occhio, una volta sola.
# Con --repeat N diventano ripetibili e misurano la CONSISTENZA su più
# chiamate (l'output di Claude non è deterministico — vedi CHANGELOG.md,
# temperature non è più impostata esplicitamente dopo il fix del 400).
_SCENARIO_ENERGY_CHECK = {
    "test_pacing_energetico",
    # [AGGIUNTO 2026-07-11 — Fase 2, terza fixture avversaria] stessa regola
    # di alternanza, qui in combinazione con altri 3 vincoli sullo stesso itinerario.
    "test_energy_pacing_injury_budget_paradox",
}
_SCENARIO_BUDGET_CHECK = {
    # scenario -> min_cost_estimate (calcolato a mano dai dati mock, vedi mock_rag_data.py)
    "simulazione_a_paradosso_finanziario": 310.0 * 7,  # H2 Marktgasse, 310€/notte * 7 notti
    # [AGGIUNTO 2026-07-11 — Fase 2] H1 Family Suites Rimini, 160€/notte * 4 notti
    "test_friction_safety_budget_paradox": 160.0 * 4,
    # [AGGIUNTO 2026-07-11 — Fase 2] H1 Hotel Marina Cagliari, 140€/notte * 3 notti
    "test_energy_pacing_injury_budget_paradox": 140.0 * 3,
}
# [AGGIUNTO 2026-07-11] Stessa logica per FRICTION_SAFETY (modulo famiglia):
# prima verificato solo a mano (lettura output + grep), ora automatico e
# ripetibile con --repeat N come già fatto per ENERGY_PACING/budget.
_SCENARIO_EXCLUDED_POI_CHECK = {
    # scenario -> set di poi_id che NON devono mai comparire nell'itinerario
    "test_friction_safety_famiglia": {"POI_TREKKING"},
    # [AGGIUNTI 2026-07-11 — Fase 2, fixture avversarie multi-vincolo]
    "test_friction_safety_budget_paradox": {"POI_TREKKING"},
    "test_work_connectivity_dietary_security": {"POI_CHURRASCO"},  # non vegetarian_verified
    "test_energy_pacing_injury_budget_paradox": {"POI_GYM_HIIT"},  # alto impatto, vietato dall'infortunio
}
_SCENARIO_RIGID_WINDOW_CHECK = {
    # scenario -> (window_start, window_end) HH:MM, nessuna intrusione reale può iniziare dentro
    "test_friction_safety_famiglia": ("13:00", "15:00"),
    "test_work_connectivity_nomade": ("09:00", "13:00"),
    # [AGGIUNTI 2026-07-11 — Fase 2] orari deliberatamente diversi dai
    # rispettivi test originali, per non ripetere lo stesso identico caso.
    "test_friction_safety_budget_paradox": ("14:00", "16:00"),
    "test_work_connectivity_dietary_security": ("10:00", "14:00"),
    "test_energy_pacing_injury_budget_paradox": ("15:00", "17:00"),  # blocco fisioterapico rigido
}
# [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità]
# `check_slot_libero_transparency()` (rinominata da un nome fuorviante che
# non descriveva cosa il controllo fa davvero — vedi scenario_checks.py)
# esisteva da tempo con una propria suite di test, ma non era MAI stata
# collegata a questo dispatch: dead code in produzione, esercitata solo
# dai suoi unit test. Lo scenario per cui esiste — poi=[] deliberato,
# Claude deve attivare [SLOT LIBERO] invece di inventare un ristorante —
# è esattamente "simulazione_c_isolamento_nutrizionale".
_SCENARIO_SLOT_LIBERO_TRANSPARENCY_CHECK = {
    "simulazione_c_isolamento_nutrizionale",
}
# [AGGIUNTO 2026-07-11] Per WORK_CONNECTIVITY la finestra protegge
# un'attività attesa (il lavoro stesso in coworking), non solo il riposo
# in hotel — questi id si sommano agli hotel come "safe_poi_ids".
_SCENARIO_RIGID_WINDOW_EXTRA_SAFE_IDS = {
    "test_work_connectivity_nomade": {"POI_COWORK"},
    "test_work_connectivity_dietary_security": {"POI_COWORK"},  # [AGGIUNTO 2026-07-11 — Fase 2]
    # test_energy_pacing_injury_budget_paradox NON ha bisogno di questa entry:
    # la fisioterapia è ambientata in hotel, già coperto dal default (safe_poi_ids
    # include sempre gli id degli hotel del payload — vedi _apply_scenario_checks sotto).
}

ALL_SIMULATIONS = [
    ("fixtures/trip_happy_path.json", "happy_path"),
    ("fixtures/trip_simulazione_a_paradosso_finanziario.json", "simulazione_a_paradosso_finanziario"),
    ("fixtures/trip_simulazione_b_apocalisse_logistica.json", "simulazione_b_apocalisse_logistica"),
    ("fixtures/trip_simulazione_c_isolamento_nutrizionale.json", "simulazione_c_isolamento_nutrizionale"),
    ("fixtures/trip_simulazione_d_prompt_injection.json", "simulazione_d_prompt_injection"),
]


def _apply_scenario_checks(scenario: str, mode: str, result) -> list[str]:
    """
    [AGGIUNTO 2026-07-10] Controlli specifici oltre al Nodo 9 generico —
    solo per mock mode (servono i dati RAG noti per calcolare energy_tag/
    min_cost_estimate; in live mode i dati sono reali e non pre-etichettati
    allo stesso modo). Ritorna la lista di violazioni testuali (vuota = ok).
    """
    if mode != "mock" or result.itinerary is None:
        return []
    violations: list[str] = []

    if scenario in _SCENARIO_ENERGY_CHECK:
        api_payload = get_mock_payload(scenario)
        energy_by_id = {p.id: p.energy_tag for p in api_payload.poi}
        ok, viol = check_energy_alternation(result.itinerary, energy_by_id)
        violations.extend(viol)

    if scenario in _SCENARIO_BUDGET_CHECK:
        min_cost = _SCENARIO_BUDGET_CHECK[scenario]
        ok, msg = check_budget_alert_when_needed(
            result.itinerary, result.trip.budget_mode, result.trip.budget_eur,
            min_cost_estimate=min_cost,
        )
        if not ok:
            violations.append(msg)

    if scenario in _SCENARIO_EXCLUDED_POI_CHECK:
        ok, viol = check_no_excluded_poi_used(
            result.itinerary, excluded_poi_ids=_SCENARIO_EXCLUDED_POI_CHECK[scenario]
        )
        violations.extend(viol)

    if scenario in _SCENARIO_RIGID_WINDOW_CHECK:
        window_start, window_end = _SCENARIO_RIGID_WINDOW_CHECK[scenario]
        api_payload = get_mock_payload(scenario)
        safe_poi_ids = {h.id for h in api_payload.hotels}
        safe_poi_ids |= _SCENARIO_RIGID_WINDOW_EXTRA_SAFE_IDS.get(scenario, set())
        ok, viol = check_rigid_window_free_of_real_activity(
            result.itinerary, window_start, window_end, safe_poi_ids=safe_poi_ids
        )
        violations.extend(viol)

    if scenario in _SCENARIO_SLOT_LIBERO_TRANSPARENCY_CHECK:
        api_payload = get_mock_payload(scenario)
        poi_ids_provided = {p.id for p in api_payload.poi}
        ok, viol = check_slot_libero_transparency(result.itinerary, poi_ids_provided=poi_ids_provided)
        violations.extend(viol)

    return violations


def _build_pdf_extras(
    itinerary: dict, trip, api_payload, api_key: str, google_maps_key: str | None = None,
) -> tuple[list[dict], dict | None, list[dict], bytes | None]:
    """
    [SPOSTATO 2026-07-14 — preparativi Make.com] La logica vera ora vive in
    `src/pdf_extras.py::build_pdf_extras()`, condivisa con il nuovo endpoint
    `POST /v1/pdf` di `service.py` (stesso principio anti-desync già seguito
    altrove: mai due implementazioni parallele della stessa cosa — vedi la
    docstring di `src/pdf_extras.py` per il dettaglio). Questo wrapper resta
    qui SOLO per (a) non rompere i test esistenti che chiamano
    `main._build_pdf_extras(...)` col nome storico, e (b) aggiungere i
    messaggi di progresso su console — `print()` ha senso per un CLI a
    esecuzione singola, non per un processo server HTTP a lunga vita (che
    userebbe `app.logger`), motivo per cui la funzione condivisa in
    `src/pdf_extras.py` resta silenziosa e questo wrapper aggiunge l'I/O.
    """
    used_poi_ids = extract_used_poi_ids(itinerary)
    poi_by_id = {p.id: p for p in api_payload.poi} if api_payload else {}

    guides, feedback, used_pois, map_png_bytes = pdf_extras.build_pdf_extras(
        itinerary, trip, api_payload, api_key, google_maps_key=google_maps_key,
    )

    guided_names = {g.get("poi_name") for g in guides}
    for poi_id in sorted(used_poi_ids):
        poi = poi_by_id.get(poi_id)
        if poi is None:
            continue
        if poi.name in guided_names:
            print(f"📄 Guida turistica generata per '{poi.name}' (per il PDF)")
        else:
            print(f"⚠️  Guida turistica saltata per '{poi.name}' (per il PDF)")

    if feedback:
        print("📄 Messaggio di feedback post-viaggio generato (per il PDF)")
    else:
        print("⚠️  Messaggio di feedback saltato (per il PDF)")

    if map_png_bytes:
        print("🗺️  Cartina generata (per il PDF)")

    return guides, feedback, used_pois, map_png_bytes


def _safe_fixture_call(fixture: str, loader):
    """
    [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità] La difesa
    esplicita già presente in `_run_one()` (fixture mancante/JSON non
    valido/campo mancante/Trip non valido -> messaggio "❌ ..." leggibile,
    non un traceback Python grezzo) copriva SOLO quel percorso. `_run_guide`,
    `_run_refine`, `_run_freshness_check` e `_run_feedback` condividono lo
    stesso identico punto di ingresso (apertura fixture + normalize_raw_input
    + trip.validate(), diretto o via `run_mock()`/`run_live()`), ma nessuno
    di questi quattro aveva lo stesso try/except — un fixture con un typo
    nel path, o un JSON malformato, dato a `--guide`/`--refine`/
    `--check-freshness`/`--feedback` produceva un traceback grezzo invece
    del messaggio chiaro previsto per il resto del CLI. Centralizzato qui
    invece di duplicare lo stesso blocco 4 volte in più (rischio concreto di
    disallineamento futuro, stesso principio anti-desync già seguito altrove
    in questo prototipo per le mappe scenario -> check).

    Esegue `loader()` (una funzione senza argomenti che incapsula la
    chiamata vera, così il chiamante decide cosa fare col risultato) e
    ritorna il suo valore se ha successo. Se solleva uno degli errori
    prevedibili, stampa un messaggio leggibile e ritorna `None` — il
    chiamante deve controllare `is None` e uscire con `return False`.
    """
    try:
        return loader()
    except FileNotFoundError:
        print(f"❌ Fixture non trovato: '{fixture}'")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Fixture '{fixture}' non è JSON valido: {e}")
        return None
    except KeyError as e:
        print(f"❌ Fixture '{fixture}' non ha il campo richiesto: {e}")
        return None
    except ValueError as e:
        # copre sia date malformate (date.fromisoformat) sia
        # "Trip non valido: [...]" sollevato da pipeline.py dopo trip.validate()
        print(f"❌ Trip non valido nel fixture '{fixture}': {e}")
        return None


def _run_one(fixture: str, scenario: str, mode: str, run_suffix: str = "", generate_pdf: bool = False) -> bool:
    print(f"\n{'=' * 70}\n▶ {scenario}  (mode={mode}{run_suffix})\n{'=' * 70}")

    if mode == "mock":
        missing = SETTINGS.missing_for_mock_mode()
        if missing:
            print(f"❌ Variabili mancanti per la mock mode: {missing} — vedi README.md")
            return False
    else:
        missing = SETTINGS.missing_for_live_mode()
        if missing:
            print(f"❌ Variabili mancanti per la live mode: {missing} — vedi README.md")
            return False

    # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio, CENTRALIZZATO 2026-07-12
    # in _safe_fixture_call() — vedi la sua docstring] Un fixture mancante/
    # malformato (file assente, JSON non valido, chiave richiesta mancante
    # come "email"/"arrivo", data non ISO, o un Trip che fallisce
    # trip.validate()) diventa un messaggio "❌ ..." leggibile, non un
    # traceback Python grezzo.
    if mode == "mock":
        result = _safe_fixture_call(fixture, lambda: run_mock(fixture, scenario, SETTINGS.anthropic_api_key))
    else:
        result = _safe_fixture_call(fixture, lambda: run_live(fixture, SETTINGS))
    if result is None:
        return False

    # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] data_layer_error:
    # vedi pipeline.py::run_live() — un fallimento nei Nodi 2b-4 (Geocoding/
    # LiteAPI/Places/Distance Matrix) ora produce un PipelineResult
    # leggibile invece di un crash, ma va comunque segnalato qui invece di
    # proseguire come se tutto fosse andato bene.
    if result.data_layer_error:
        print(f"❌ ERRORE STRATO DATI (Geocoding/LiteAPI/Places/Distance Matrix): {result.data_layer_error}")
        return False

    if result.parse_error:
        print(f"❌ PARSE ERROR: {result.parse_error}")
        print("--- Output grezzo di Claude ---")
        print(result.raw_claude_output[:2000])
        return False

    if result.geocoding_warning:
        print(f"⚠️  {result.geocoding_warning}")

    print(f"Trip: {result.trip.destination} | {result.trip.objective_function} | "
          f"{result.trip.duration_days}gg | budget_mode={result.trip.budget_mode}")

    # [AGGIUNTO 2026-07-11 — espansione tipi di alloggio] Prima non c'era
    # nessun modo di vedere, da un run --mode live, QUALE anchor point è
    # stato davvero selezionato e con quale property_type — bisognava
    # aprire il JSON completo a mano. Reso visibile qui, in console, per
    # ogni run live: verifica immediata che il nuovo DEFAULT_HOTEL_TYPE_IDS
    # (liteapi_client.py) stia davvero facendo scegliere anche appartamenti/
    # ville quando disponibili, non solo hotel classici.
    anchor_hotels = result.payload.get("DATI_API_FORNITI", {}).get("hotels", []) if result.payload else []
    if anchor_hotels:
        print("\n--- Anchor point selezionato (Nodo 3, hotel-ancora) ---")
        for h in anchor_hotels:
            ptype = h.get("property_type") or "[tipo non riportato dal fornitore]"
            print(f"  - {h.get('name')} — tipo: {ptype} — {h.get('price_night_eur')}€/notte")

    print(f"\n--- Validazione (Nodo 9) ---")
    print(result.validation_report.summary())

    scenario_violations = _apply_scenario_checks(scenario, mode, result)
    if scenario_violations:
        print(f"\n--- Controlli di scenario aggiuntivi: ❌ {len(scenario_violations)} violazione/i ---")
        for v in scenario_violations:
            print(f"  - {v}")
    elif mode == "mock" and (
        scenario in _SCENARIO_ENERGY_CHECK or scenario in _SCENARIO_BUDGET_CHECK
        or scenario in _SCENARIO_EXCLUDED_POI_CHECK or scenario in _SCENARIO_RIGID_WINDOW_CHECK
        or scenario in _SCENARIO_SLOT_LIBERO_TRANSPARENCY_CHECK
    ):
        print("\n--- Controlli di scenario aggiuntivi: ✅ nessuna violazione ---")

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_md = OUTPUT_DIR / f"{scenario}{run_suffix}.md"
    out_json = OUTPUT_DIR / f"{scenario}{run_suffix}_raw.json"
    out_md.write_text(result.rendered_markdown, encoding="utf-8")
    out_json.write_text(json.dumps(result.itinerary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📄 Itinerario salvato in: {out_md}")
    print(f"📄 JSON completo (con reasoning) salvato in: {out_json}")

    # [AGGIUNTO 2026-07-11 — richiesta di Lorenzo: "facciamo tutto ciò che
    # è necessario per avere un prodotto ottimo"] Il Markdown sopra resta
    # lo strumento di REVISIONE INTERNA (mostra poi_id per audit — vedi
    # renderer.py). Il PDF qui è il documento vero per il cliente finale
    # (src/pdf_renderer.py — HTML/CSS impaginato, no poi_id). Opt-in
    # (`--pdf`, default disattivato) perché richiede il binario esterno
    # wkhtmltopdf, non ancora verificato sul PC Windows di Lorenzo — non
    # deve rompere un run altrimenti riuscito se manca.
    if generate_pdf:
        sanitized_hotels = result.payload.get("DATI_API_FORNITI", {}).get("hotels", []) if result.payload else []
        # [AGGIUNTO 2026-07-12 — vedi _build_pdf_extras() sopra] guida
        # turistica per-POI + feedback post-viaggio incorporati nello
        # STESSO PDF cliente, non più solo file .md separati da --guide/
        # --feedback.
        guides, feedback, used_pois, map_png_bytes = _build_pdf_extras(
            result.itinerary, result.trip, result.api_payload, SETTINGS.anthropic_api_key,
            google_maps_key=SETTINGS.google_maps_key,
        )
        try:
            out_pdf = OUTPUT_DIR / f"{scenario}{run_suffix}.pdf"
            pdf_renderer.render_pdf(result.itinerary, result.trip.to_dict(), hotels=sanitized_hotels,
                                     guides=guides, feedback=feedback, poi=used_pois,
                                     map_png_bytes=map_png_bytes, output_path=str(out_pdf))
            print(f"📄 PDF cliente salvato in: {out_pdf}")
        except pdf_renderer.PdfRendererError as e:
            print(f"⚠️  Generazione PDF saltata: {e}")

    return result.validation_report.passed and not scenario_violations


def _run_repeated(fixture: str, scenario: str, mode: str, repeat: int, generate_pdf: bool = False) -> bool:
    """
    [AGGIUNTO 2026-07-10] L'output di Claude non è deterministico (vedi
    CHANGELOG.md: temperature non più impostata esplicitamente dopo il fix
    del 400 "temperature is deprecated"). Validare un comportamento con UNA
    sola chiamata è un campione fortunato, non una prova di affidabilità.
    Questo rilancia lo stesso scenario N volte e misura la CONSISTENZA.
    """
    print(f"\n{'#' * 70}\n# {scenario}: {repeat} run per misurare la consistenza\n{'#' * 70}")
    outcomes = []
    for i in range(1, repeat + 1):
        ok = _run_one(fixture, scenario, mode, run_suffix=f"_run{i}", generate_pdf=generate_pdf)
        outcomes.append(ok)
    passed = sum(outcomes)
    print(f"\n{'#' * 70}\n# RIEPILOGO CONSISTENZA — {scenario}: {passed}/{repeat} run senza violazioni")
    if passed < repeat:
        print(f"# ⚠️  Comportamento INCOSTANTE su {repeat} run — non considerare questo scenario")
        print(f"#     validato finché non si capisce la causa (system prompt ambiguo su questo")
        print(f"#     punto, o semplice varianza del modello che richiederebbe una temperature")
        print(f"#     più bassa se il modello tornasse ad accettarla).")
    else:
        print(f"# ✅ Comportamento COSTANTE su {repeat} run indipendenti.")
    print("#" * 70)
    return passed == repeat


def _run_guide(fixture: str, poi_name: str) -> bool:
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: guide turistiche per
    singolo POI] Percorso indipendente dalla pipeline completa (Nodi 1-9):
    serve solo `destination`/`objective_function` dal fixture, per dare a
    `guide_generator.py` lo stesso contesto di personalizzazione già usato
    per l'itinerario — non richiede LiteAPI/Places/Distance Matrix, quindi
    nessuna delle chiavi API di quei fornitori è necessaria qui, solo
    ANTHROPIC_API_KEY.
    """
    print(f"\n{'=' * 70}\n▶ Guida turistica: '{poi_name}'\n{'=' * 70}")

    missing = SETTINGS.missing_for_mock_mode()
    if "ANTHROPIC_API_KEY" in missing:
        print(f"❌ ANTHROPIC_API_KEY mancante — richiesta anche per --guide. Vedi README.md")
        return False

    # [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità, vedi
    # _safe_fixture_call()] Prima, un fixture mancante/malformato dato a
    # --guide produceva un traceback grezzo invece del messaggio "❌ ..."
    # leggibile già garantito per il resto del CLI.
    def _load():
        with open(fixture, encoding="utf-8") as f:
            raw = json.load(f)
        trip = normalize_raw_input(raw)
        trip_errors = trip.validate()
        if trip_errors:
            raise ValueError(f"Trip non valido: {trip_errors}")
        return trip

    trip = _safe_fixture_call(fixture, _load)
    if trip is None:
        return False

    module = get_module_for_objective_function(trip.objective_function)

    try:
        guide = guide_generator.generate_poi_guide(
            poi_name,
            trip.destination,
            api_key=SETTINGS.anthropic_api_key,
            objective_function=trip.objective_function,
            module_id=module.id,
        )
    except guide_generator.GuideGeneratorError as e:
        print(f"❌ Generazione guida fallita: {e}")
        return False

    OUTPUT_DIR.mkdir(exist_ok=True)
    slug = "".join(c if c.isalnum() else "_" for c in poi_name.lower()).strip("_")
    out_path = OUTPUT_DIR / f"guida_{slug}.md"
    out_path.write_text(guide_generator.render_guide_markdown(guide), encoding="utf-8")
    print(f"📄 Guida turistica salvata in: {out_path}")
    return True


def _run_refine(fixture: str, scenario: str, customer_request: str, generate_pdf: bool = False) -> bool:
    """
    [AGGIUNTO 2026-07-12 — agente di affinamento conversazionale]
    Genera prima l'itinerario base (mock mode, stessi dati di sempre),
    poi applica la richiesta del cliente con `src/refinement.py` sugli
    STESSI DATI_API_FORNITI — nessuna nuova chiamata a Places/LiteAPI.
    Percorso pensato per verifica manuale/demo, non ancora collegato a un
    canale cliente reale (decisione di fase Make.com).

    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "Voglio tutti e tre nello
    stesso PDF"] `--refine` non aveva MAI supportato `--pdf` prima d'ora —
    produceva solo il Markdown `{scenario}_affinato.md`. Ora, con
    `generate_pdf=True`, produce anche `{scenario}_affinato.pdf`: lo
    stesso PDF cliente arricchito (guide turistiche dei POI usati +
    feedback post-viaggio) prodotto da `_run_one()`, ma costruito
    sull'itinerario RIFINITO invece che su quello originale.
    """
    print(f"\n{'=' * 70}\n▶ Affinamento conversazionale — scenario base: {scenario}\n{'=' * 70}")

    missing = SETTINGS.missing_for_mock_mode()
    if missing:
        print(f"❌ Variabili mancanti: {missing} — vedi README.md")
        return False

    # [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità, vedi
    # _safe_fixture_call()] Stessa difesa esplicita già garantita per il
    # resto del CLI.
    base_result = _safe_fixture_call(fixture, lambda: run_mock(fixture, scenario, SETTINGS.anthropic_api_key))
    if base_result is None:
        return False
    if base_result.itinerary is None:
        print(f"❌ Impossibile generare l'itinerario base: {base_result.parse_error}")
        return False
    print(f"✅ Itinerario base generato — {base_result.validation_report.summary()}")

    api_payload = get_mock_payload(scenario)
    print(f"\n💬 Richiesta cliente: \"{customer_request}\"")

    try:
        result = refinement.refine_itinerary(
            base_result.itinerary,
            base_result.payload,
            api_payload,
            base_result.trip,
            customer_request,
            api_key=SETTINGS.anthropic_api_key,
        )
    except refinement.RefinementError as e:
        print(f"❌ Affinamento fallito: {e}")
        return False

    if result.itinerary is None:
        print(f"❌ Affinamento fallito (parse error): {result.parse_error}")
        return False

    print(f"\n--- Validazione post-affinamento (Nodo 9 rieseguito) ---")
    print(result.validation_report.summary())

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{scenario}_affinato.md"
    out_path.write_text(result.rendered_markdown, encoding="utf-8")
    print(f"\n📄 Itinerario affinato salvato in: {out_path}")

    if generate_pdf:
        sanitized_hotels = [h.to_dict() for h in api_payload.hotels]
        guides, feedback, used_pois, map_png_bytes = _build_pdf_extras(
            result.itinerary, base_result.trip, api_payload, SETTINGS.anthropic_api_key,
            google_maps_key=SETTINGS.google_maps_key,
        )
        try:
            out_pdf = OUTPUT_DIR / f"{scenario}_affinato.pdf"
            pdf_renderer.render_pdf(result.itinerary, base_result.trip.to_dict(), hotels=sanitized_hotels,
                                     guides=guides, feedback=feedback, poi=used_pois,
                                     map_png_bytes=map_png_bytes, output_path=str(out_pdf))
            print(f"📄 PDF cliente (itinerario affinato) salvato in: {out_pdf}")
        except pdf_renderer.PdfRendererError as e:
            print(f"⚠️  Generazione PDF saltata: {e}")

    return result.validation_report.passed


def _run_freshness_check(fixture: str, scenario: str, mode: str = "mock") -> bool:
    """
    [AGGIUNTO 2026-07-12 — controllo di freschezza pre-partenza] Genera
    l'itinerario (mock o live, vedi `mode`), poi riverifica hotel/POI
    EFFETTIVAMENTE USATI con chiamate LIVE reali a LiteAPI/Google Places —
    richiede quindi le stesse chiavi di --mode live anche quando
    l'itinerario stesso resta mock.

    [CORRETTO 2026-07-12 — bug reale trovato ED ESEGUITO da Lorenzo dal
    vivo] Prima, questa funzione ignorava silenziosamente `--mode live`:
    chiamava SEMPRE `run_mock()` + `get_mock_payload(scenario)`, qualunque
    fosse il flag passato da riga di comando (il dispatch in `main()` non
    passava nemmeno `args.mode` alla funzione). Lorenzo ha lanciato
    `--check-freshness` e poi `--mode live --check-freshness` aspettandosi
    un confronto mock/live, ottenendo invece byte-per-byte lo stesso
    identico report ("Relais Borgo Val d'Orcia (H1)", ecc. — nomi/ID
    fittizi della fixture mock, non dati reali) in entrambi i casi. Un
    itinerario davvero generato in `--mode live` avrebbe usato hotel/POI
    reali (con ID/nomi reali da LiteAPI/Places), rendendo possibile un
    vero esito POSITIVO nel controllo di freschezza — cosa impossibile
    finché il flag veniva ignorato. Corretto passando `mode` fino a qui e
    diramando su `run_live()`/`ApiPayload` reale quando `mode == "live"`.
    """
    print(f"\n{'=' * 70}\n▶ Controllo di freschezza pre-partenza — scenario: {scenario} (mode={mode})\n{'=' * 70}")

    missing = SETTINGS.missing_for_live_mode()
    if missing:
        print(f"❌ Variabili mancanti: {missing} — il controllo di freschezza richiede le "
              f"chiavi live (Google Maps/LiteAPI) anche se l'itinerario è mock. Vedi README.md")
        return False

    # [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità, vedi
    # _safe_fixture_call()] Stessa difesa esplicita già garantita per il
    # resto del CLI.
    if mode == "live":
        base_result = _safe_fixture_call(fixture, lambda: run_live(fixture, SETTINGS))
        if base_result is None:
            return False
        if base_result.data_layer_error:
            print(f"❌ Errore nello strato dati (Geocoding/LiteAPI/Places/Distance Matrix): "
                  f"{base_result.data_layer_error}")
            return False
    else:
        base_result = _safe_fixture_call(fixture, lambda: run_mock(fixture, scenario, SETTINGS.anthropic_api_key))
        if base_result is None:
            return False

    if base_result.itinerary is None:
        print(f"❌ Impossibile generare l'itinerario base: {base_result.parse_error}")
        return False
    print(f"✅ Itinerario base generato — {base_result.validation_report.summary()}")

    # [CORRETTO 2026-07-12] In mock mode l'ApiPayload di run_mock() non era
    # comunque esposto sul PipelineResult prima di questo fix (vedi nota
    # in src/pipeline.py) — get_mock_payload(scenario) resta un fallback
    # equivalente e sicuro per il caso mock, dove i dati sono comunque
    # deterministici. In live mode usiamo invece l'ApiPayload REALE appena
    # costruito da run_live(), mai stato disponibile qui prima d'ora.
    api_payload = base_result.api_payload if mode == "live" else get_mock_payload(scenario)
    report = freshness_check.run_freshness_check(
        base_result.itinerary, api_payload, base_result.trip,
        google_maps_key=SETTINGS.google_maps_key, liteapi_key=SETTINGS.liteapi_key,
    )
    print(f"\n--- Report di freschezza ---")
    print(report.summary())
    return report.all_confirmed


def _run_feedback(fixture: str, scenario: str) -> bool:
    """
    [AGGIUNTO 2026-07-12 — feedback post-viaggio] Genera l'itinerario base
    (mock mode), poi genera il messaggio di follow-up personalizzato con
    src/feedback_generator.py. Canale di invio reale (email dopo il
    rientro) resta una decisione della fase Make.com.
    """
    print(f"\n{'=' * 70}\n▶ Feedback post-viaggio — scenario base: {scenario}\n{'=' * 70}")

    missing = SETTINGS.missing_for_mock_mode()
    if missing:
        print(f"❌ Variabili mancanti: {missing} — vedi README.md")
        return False

    # [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità, vedi
    # _safe_fixture_call()] Stessa difesa esplicita già garantita per il
    # resto del CLI.
    base_result = _safe_fixture_call(fixture, lambda: run_mock(fixture, scenario, SETTINGS.anthropic_api_key))
    if base_result is None:
        return False
    if base_result.itinerary is None:
        print(f"❌ Impossibile generare l'itinerario base: {base_result.parse_error}")
        return False
    print(f"✅ Itinerario base generato — {base_result.validation_report.summary()}")

    try:
        feedback = feedback_generator.generate_post_trip_feedback(
            base_result.itinerary, api_key=SETTINGS.anthropic_api_key,
            objective_function=base_result.trip.objective_function,
        )
    except feedback_generator.FeedbackGeneratorError as e:
        print(f"❌ Generazione feedback fallita: {e}")
        return False

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{scenario}_feedback.md"
    out_path.write_text(feedback_generator.render_feedback_markdown(feedback), encoding="utf-8")
    print(f"📄 Messaggio di feedback salvato in: {out_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Prototipo AI Travel Agency")
    parser.add_argument("--fixture", help="Path al file trip_*.json")
    parser.add_argument("--scenario", default="happy_path",
                         help="Chiave dello scenario RAG mock (src/mock_rag_data.py). Ignorato in --mode live.")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--all-simulations", action="store_true",
                         help="Esegue happy path + le 4 simulazioni Chaos Engineering in mock mode")
    parser.add_argument("--repeat", type=int, default=1,
                         help="[AGGIUNTO 2026-07-10] Rilancia lo stesso scenario N volte per "
                              "misurare la consistenza (l'output di Claude non è deterministico). "
                              "Solo con --fixture/--scenario, non con --all-simulations.")
    parser.add_argument("--pdf", action="store_true",
                         help="[AGGIUNTO 2026-07-11, ESTESO 2026-07-12] Genera anche il PDF cliente "
                              "reale (src/pdf_renderer.py) oltre al Markdown di revisione interna. "
                              "Il PDF include ora anche, come sezioni della STESSA pagina/documento: "
                              "una guida turistica per ciascun POI EFFETTIVAMENTE USATO "
                              "nell'itinerario (src/guide_generator.py) e il messaggio di feedback "
                              "post-viaggio (src/feedback_generator.py) — nessun comando separato "
                              "necessario. Combinabile con --refine (produce lo stesso PDF "
                              "arricchito sull'itinerario RIFINITO). Richiede il binario esterno "
                              "wkhtmltopdf installato (vedi README.md) — se assente, stampa un "
                              "avviso e continua senza rompere il run; se la guida di un singolo "
                              "POI o il feedback falliscono, quella sezione viene semplicemente "
                              "omessa dal PDF, senza far fallire il resto.")
    parser.add_argument("--guide", metavar="NOME_POI",
                         help="[AGGIUNTO 2026-07-12] Genera una guida turistica per un singolo "
                              "POI (es. --guide \"Colosseo\") usando src/guide_generator.py, "
                              "invece di generare un itinerario completo. Richiede --fixture (per "
                              "destination/objective_function di contesto) ma NON esegue la "
                              "pipeline completa — solo ANTHROPIC_API_KEY è necessaria. Per "
                              "includere le guide DIRETTAMENTE nel PDF cliente (invece di un .md "
                              "a parte), usa --pdf su un run normale/--refine: le guide dei POI "
                              "usati nell'itinerario vengono generate automaticamente.")
    parser.add_argument("--refine", metavar="RICHIESTA_CLIENTE",
                         help="[AGGIUNTO 2026-07-12] Genera l'itinerario base (--fixture/--scenario, "
                              "mock mode) e poi applica una richiesta di modifica in linguaggio "
                              "naturale (es. --refine \"cambia il giorno 2\") con "
                              "src/refinement.py, riusando gli stessi DATI_API_FORNITI. "
                              "Combinabile con --pdf (vedi sopra).")
    parser.add_argument("--check-freshness", action="store_true",
                         help="[AGGIUNTO 2026-07-12] Genera l'itinerario base (mock) e riverifica "
                              "hotel/POI usati con chiamate LIVE reali a LiteAPI/Google Places "
                              "(src/freshness_check.py) — richiede le chiavi live anche in mock mode.")
    parser.add_argument("--feedback", action="store_true",
                         help="[AGGIUNTO 2026-07-12] Genera l'itinerario base (mock) e poi un "
                              "messaggio di follow-up post-viaggio personalizzato "
                              "(src/feedback_generator.py).")
    args = parser.parse_args()

    if args.guide:
        if not args.fixture:
            parser.error("--guide richiede anche --fixture (per destination/objective_function)")
        sys.exit(0 if _run_guide(args.fixture, args.guide) else 1)

    if args.refine:
        if not args.fixture:
            parser.error("--refine richiede anche --fixture/--scenario")
        sys.exit(0 if _run_refine(args.fixture, args.scenario, args.refine, generate_pdf=args.pdf) else 1)

    if args.check_freshness:
        if not args.fixture:
            parser.error("--check-freshness richiede anche --fixture/--scenario")
        sys.exit(0 if _run_freshness_check(args.fixture, args.scenario, args.mode) else 1)

    if args.feedback:
        if not args.fixture:
            parser.error("--feedback richiede anche --fixture/--scenario")
        sys.exit(0 if _run_feedback(args.fixture, args.scenario) else 1)

    if args.all_simulations:
        # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] --all-simulations
        # ha sempre ignorato silenziosamente --mode/--scenario/--repeat
        # (esegue SEMPRE le 5 simulazioni ufficiali in mock mode, una volta
        # ciascuna) — solo --repeat aveva questo scritto esplicitamente
        # nel proprio help text, --mode e --scenario no. Un utente che
        # lancia `--all-simulations --mode live` si aspetterebbe
        # ragionevolmente una verifica dal vivo e otterrebbe invece mock
        # mode senza alcun avviso. Ora segnalato esplicitamente invece di
        # lasciar scoprire la cosa leggendo l'output.
        ignored = []
        if args.mode != "mock":
            ignored.append(f"--mode {args.mode}")
        if args.scenario != "happy_path":
            ignored.append(f"--scenario {args.scenario}")
        if args.repeat != 1:
            ignored.append(f"--repeat {args.repeat}")
        if ignored:
            print(f"⚠️  --all-simulations ignora {', '.join(ignored)}: esegue sempre le 5 "
                  f"simulazioni ufficiali in mock mode, una run ciascuna.")
        results = [_run_one(f, s, "mock", generate_pdf=args.pdf) for f, s in ALL_SIMULATIONS]
        print(f"\n{'=' * 70}\nRIEPILOGO: {sum(results)}/{len(results)} scenari passati\n{'=' * 70}")
        sys.exit(0 if all(results) else 1)

    if not args.fixture:
        parser.error("--fixture è richiesto (oppure usa --all-simulations)")

    if args.repeat > 1:
        ok = _run_repeated(args.fixture, args.scenario, args.mode, args.repeat, generate_pdf=args.pdf)
    else:
        ok = _run_one(args.fixture, args.scenario, args.mode, generate_pdf=args.pdf)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
