import unittest
from src.validator import (
    parse_claude_output, ParseError, check_format_compliance,
    check_rag_fidelity, check_geospatial_coherence, check_no_raw_id_leakage,
    check_energy_pacing, check_budget_compliance,
    validate_itinerary, strip_reasoning,
)

GOOD_ITINERARY = {
    "reasoning": "<scratchpad>...</scratchpad>",
    "destination": "Val d'Orcia",
    "executive_summary": "Riposo pre-torneo.",
    "budget_alert": None,
    "days": [
        {
            "day": 1,
            "title": "Arrivo",
            "blocks": [
                {"time": "16:00", "activity": "Check-in", "location": "Hotel", "logistics": "", "poi_id": "H1"},
                {"time": "19:00", "activity": "Cena", "location": "Trattoria", "logistics": "13 min", "poi_id": "POI1"},
            ],
        }
    ],
    "architect_tips": ["Porta racchette di scorta."],
}


class TestParseClaudeOutput(unittest.TestCase):
    def test_valid_json(self):
        result = parse_claude_output('{"a": 1}')
        self.assertEqual(result, {"a": 1})

    def test_invalid_json_raises(self):
        with self.assertRaises(ParseError):
            parse_claude_output("questo non è JSON")

    def test_prose_before_json_raises(self):
        # violazione OUTPUT_CONTRACT: "NIENTE testo prima o dopo"
        with self.assertRaises(ParseError):
            parse_claude_output('Certo! Ecco il tuo itinerario: {"a": 1}')

    def test_markdown_json_fence_is_stripped(self):
        # [AGGIUNTO 2026-07-11 — bug reale dal capstone live test lavoro/
        # Lisbona] Claude ha avvolto l'intero output in una fence
        # ```json ... ``` nonostante [OUTPUT_CONTRACT] lo vieti
        # esplicitamente — json.loads() falliva su "Expecting value: line
        # 1 column 1" perché il primo carattere reale era un backtick.
        result = parse_claude_output('```json\n{"a": 1}\n```')
        self.assertEqual(result, {"a": 1})

    def test_markdown_fence_without_json_language_tag_is_stripped(self):
        result = parse_claude_output('```\n{"a": 1}\n```')
        self.assertEqual(result, {"a": 1})

    def test_markdown_fence_with_surrounding_whitespace_is_stripped(self):
        result = parse_claude_output('   ```json\n{"a": 1}\n```   \n')
        self.assertEqual(result, {"a": 1})

    def test_partial_fence_not_stripped_still_raises(self):
        # Un testo che INIZIA con una fence ma non FINISCE con una fence
        # (es. prosa residua dopo la chiusura, o fence non chiusa) non deve
        # essere silenziosamente "aggiustato" — il match è volutamente
        # stretto (intero testo racchiuso, non solo l'inizio).
        with self.assertRaises(ParseError):
            parse_claude_output('```json\n{"a": 1}\nCerto, fammi sapere se serve altro!')


class TestFormatCompliance(unittest.TestCase):
    def test_good_itinerary_passes(self):
        ok, errors = check_format_compliance(GOOD_ITINERARY)
        self.assertTrue(ok, errors)

    def test_empty_days_fails(self):
        ok, errors = check_format_compliance({**GOOD_ITINERARY, "days": []})
        self.assertFalse(ok)
        self.assertTrue(any("days[]" in e for e in errors))

    def test_missing_activity_fails(self):
        bad = {**GOOD_ITINERARY, "days": [{"day": 1, "title": "x", "blocks": [
            {"time": "10:00", "activity": "", "location": "x", "poi_id": None}
        ]}]}
        ok, errors = check_format_compliance(bad)
        self.assertFalse(ok)

    def test_missing_destination_fails(self):
        ok, errors = check_format_compliance({**GOOD_ITINERARY, "destination": ""})
        self.assertFalse(ok)

    def test_empty_blocks_in_a_day_fails(self):
        # [AGGIUNTO 2026-07-12 — audit di potenziamento massimo, gap reale]
        # Un giorno con "blocks": [] (l'oggetto giorno presente, ma
        # nessuna attività dentro, nemmeno un [SLOT LIBERO]) passava indenne
        # prima di questo fix: nessun pasto, nessuna attività, semplicemente
        # un giorno vuoto nel documento cliente senza alcuna segnalazione.
        bad = {**GOOD_ITINERARY, "days": [{"day": 1, "title": "Giorno vuoto", "blocks": []}]}
        ok, errors = check_format_compliance(bad)
        self.assertFalse(ok)
        self.assertTrue(any("blocks[] è vuoto" in e for e in errors))

    def test_days_not_a_list_fails_cleanly_not_crashed(self):
        # [AGGIUNTO 2026-07-12 — audit di revisione completa, bug reale
        # trovato ed eseguito] `days` come dict invece di lista faceva
        # crashare con `AttributeError`/`TypeError` (iterando sulle chiavi
        # del dict, poi chiamando `.get()` su una stringa) — riprodotto
        # direttamente prima del fix.
        ok, errors = check_format_compliance({**GOOD_ITINERARY, "days": {"1": "x"}})
        self.assertFalse(ok)
        self.assertTrue(any("days deve essere una lista" in e for e in errors))

    def test_day_element_not_a_dict_fails_cleanly_not_crashed(self):
        ok, errors = check_format_compliance({**GOOD_ITINERARY, "days": ["not-a-dict"]})
        self.assertFalse(ok)
        self.assertTrue(any("non è un oggetto valido" in e for e in errors))

    def test_blocks_not_a_list_fails_cleanly_not_crashed(self):
        ok, errors = check_format_compliance(
            {**GOOD_ITINERARY, "days": [{"day": 1, "blocks": {"time": "10:00"}}]}
        )
        self.assertFalse(ok)
        self.assertTrue(any("blocks deve essere una lista" in e for e in errors))

    def test_block_element_not_a_dict_fails_cleanly_not_crashed(self):
        ok, errors = check_format_compliance(
            {**GOOD_ITINERARY, "days": [{"day": 1, "blocks": ["not-a-dict"]}]}
        )
        self.assertFalse(ok)
        self.assertTrue(any("un elemento di blocks[] non è un oggetto valido" in e for e in errors))

    def test_expected_duration_days_not_checked_when_omitted(self):
        # comportamento pre-esistente invariato: senza il nuovo parametro,
        # nessun controllo sul conteggio/numerazione dei giorni.
        ok, errors = check_format_compliance(GOOD_ITINERARY)  # 1 solo giorno, nessun expected_duration_days
        self.assertTrue(ok, errors)

    def test_expected_duration_days_matching_count_passes(self):
        itinerary = {**GOOD_ITINERARY, "days": [
            {**GOOD_ITINERARY["days"][0], "day": 1},
            {**GOOD_ITINERARY["days"][0], "day": 2},
            {**GOOD_ITINERARY["days"][0], "day": 3},
        ]}
        ok, errors = check_format_compliance(itinerary, expected_duration_days=3)
        self.assertTrue(ok, errors)

    def test_expected_duration_days_wrong_count_fails(self):
        # [AGGIUNTO 2026-07-12 — audit di potenziamento massimo, gap reale]
        # Un itinerario di 3 giorni dichiarati che ne restituisse solo 2
        # passava format_compliance indenne prima di questo fix: nessun
        # controllo confrontava len(days) con trip.duration_days.
        itinerary = {**GOOD_ITINERARY, "days": [
            {**GOOD_ITINERARY["days"][0], "day": 1},
            {**GOOD_ITINERARY["days"][0], "day": 2},
        ]}
        ok, errors = check_format_compliance(itinerary, expected_duration_days=3)
        self.assertFalse(ok)
        self.assertTrue(any("attesi esattamente 3" in e for e in errors))

    def test_expected_duration_days_gap_in_numbering_fails(self):
        itinerary = {**GOOD_ITINERARY, "days": [
            {**GOOD_ITINERARY["days"][0], "day": 1},
            {**GOOD_ITINERARY["days"][0], "day": 3},  # manca il 2, duplicato nessuno
        ]}
        ok, errors = check_format_compliance(itinerary, expected_duration_days=2)
        self.assertFalse(ok)

    def test_expected_duration_days_duplicate_numbering_fails(self):
        itinerary = {**GOOD_ITINERARY, "days": [
            {**GOOD_ITINERARY["days"][0], "day": 1},
            {**GOOD_ITINERARY["days"][0], "day": 1},  # duplicato, mai il 2
        ]}
        ok, errors = check_format_compliance(itinerary, expected_duration_days=2)
        self.assertFalse(ok)

    def test_expected_duration_days_out_of_order_but_complete_still_passes(self):
        # l'ordine grezzo nell'array non conta, solo l'insieme dei numeri
        itinerary = {**GOOD_ITINERARY, "days": [
            {**GOOD_ITINERARY["days"][0], "day": 2},
            {**GOOD_ITINERARY["days"][0], "day": 1},
            {**GOOD_ITINERARY["days"][0], "day": 3},
        ]}
        ok, errors = check_format_compliance(itinerary, expected_duration_days=3)
        self.assertTrue(ok, errors)


class TestRagFidelity(unittest.TestCase):
    def test_all_ids_valid_passes(self):
        ok, hallucinated = check_rag_fidelity(GOOD_ITINERARY, valid_ids={"H1", "POI1"})
        self.assertTrue(ok)
        self.assertEqual(hallucinated, [])

    def test_unknown_poi_id_flagged(self):
        # KPI 100% Fedeltà RAG (Cap. 7.4): un solo id inventato deve essere rilevato
        ok, hallucinated = check_rag_fidelity(GOOD_ITINERARY, valid_ids={"H1"})  # POI1 mancante
        self.assertFalse(ok)
        self.assertIn("POI1", hallucinated)

    def test_null_poi_id_always_ok(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "10:00", "activity": "[SLOT LIBERO]", "poi_id": None}
        ]}]}
        ok, hallucinated = check_rag_fidelity(itin, valid_ids=set())
        self.assertTrue(ok)

    def test_unhashable_poi_id_flagged_not_crashed(self):
        # [AGGIUNTO 2026-07-12 — audit di revisione completa, bug reale
        # trovato ed eseguito] Un poi_id di tipo non hashable (es. una
        # lista, se Claude producesse una forma JSON inattesa) sollevava
        # `TypeError: unhashable type: 'list'` da `poi_id not in valid_ids`
        # (un set) — crash dell'intero Nodo 9 invece di un FAIL pulito.
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "10:00", "activity": "x", "poi_id": ["H1"]}
        ]}]}
        ok, hallucinated = check_rag_fidelity(itin, valid_ids={"H1"})
        self.assertFalse(ok)
        self.assertEqual(hallucinated, [["H1"]])

    def test_non_dict_day_or_block_flagged_not_crashed(self):
        itin = {"days": ["not-a-dict", {"day": 1, "blocks": ["not-a-dict-either"]}]}
        ok, hallucinated = check_rag_fidelity(itin, valid_ids=set())
        self.assertTrue(ok)  # nessun blocco valido da cui estrarre un poi_id, nessun crash


class TestGeospatialCoherence(unittest.TestCase):
    def test_chronological_order_passes(self):
        ok, errors = check_geospatial_coherence(GOOD_ITINERARY)
        self.assertTrue(ok, errors)

    def test_out_of_order_blocks_flagged(self):
        bad = {"days": [{"day": 1, "blocks": [
            {"time": "19:00", "activity": "Cena", "poi_id": None},
            {"time": "10:00", "activity": "Colazione", "poi_id": None},  # fuori sequenza
        ]}]}
        ok, errors = check_geospatial_coherence(bad)
        self.assertFalse(ok)

    def test_malformed_time_flagged(self):
        bad = {"days": [{"day": 1, "blocks": [
            {"time": "non-un-orario", "activity": "x", "poi_id": None},
        ]}]}
        ok, errors = check_geospatial_coherence(bad)
        self.assertFalse(ok)


class TestNoRawIdLeakage(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — bug reale trovato dal vivo da Lorenzo, leggendo
    un vero PDF cliente generato: "15 min in auto da POI2" invece di "15
    min in auto da Terme di San Filippo"] Difesa strutturale (non solo
    l'istruzione in system_prompt_master.txt) contro l'id grezzo di un
    hotel/POI che finisce in un campo di testo libero rivolto al cliente.
    """

    def test_good_itinerary_with_no_ids_in_free_text_passes(self):
        ok, leaked = check_no_raw_id_leakage(GOOD_ITINERARY, valid_ids={"H1", "POI1"})
        self.assertTrue(ok, leaked)
        self.assertEqual(leaked, [])

    def test_id_leaked_in_logistics_is_flagged(self):
        bad = {**GOOD_ITINERARY, "days": [{"day": 1, "title": "Arrivo", "blocks": [
            {"time": "17:15", "activity": "Terme", "location": "Terme di San Filippo",
             "logistics": "15 min in auto da POI2", "poi_id": None},
        ]}]}
        ok, leaked = check_no_raw_id_leakage(bad, valid_ids={"H1", "POI2"})
        self.assertFalse(ok)
        self.assertTrue(any("POI2" in e for e in leaked))

    def test_id_leaked_in_executive_summary_is_flagged(self):
        bad = {**GOOD_ITINERARY, "executive_summary": "Le terme (POI2) sono l'unico POI aperto."}
        ok, leaked = check_no_raw_id_leakage(bad, valid_ids={"H1", "POI2"})
        self.assertFalse(ok)
        self.assertTrue(any("POI2" in e for e in leaked))

    def test_id_leaked_in_day_title_is_flagged(self):
        bad = {**GOOD_ITINERARY, "days": [{"day": 1, "title": "Trasferimento verso H1", "blocks": [
            {"time": "10:00", "activity": "x", "poi_id": None},
        ]}]}
        ok, leaked = check_no_raw_id_leakage(bad, valid_ids={"H1"})
        self.assertFalse(ok)

    def test_id_leaked_in_architect_tips_is_flagged(self):
        bad = {**GOOD_ITINERARY, "architect_tips": ["Ricorda di tornare a H1 prima di sera."]}
        ok, leaked = check_no_raw_id_leakage(bad, valid_ids={"H1"})
        self.assertFalse(ok)

    def test_id_leaked_in_budget_alert_is_flagged(self):
        bad = {**GOOD_ITINERARY, "budget_alert": "H1 è la struttura più economica disponibile."}
        ok, leaked = check_no_raw_id_leakage(bad, valid_ids={"H1"})
        self.assertFalse(ok)

    def test_id_as_substring_of_longer_word_does_not_false_positive(self):
        # "H1" dentro "H10" (o "H1a") non è lo stesso token — bordi di
        # parola espliciti, altrimenti un nome/numero legittimo che
        # contiene la stessa sequenza di caratteri farebbe scattare un
        # falso positivo.
        bad = {**GOOD_ITINERARY, "executive_summary": "La camera H10 è già stata assegnata."}
        ok, leaked = check_no_raw_id_leakage(bad, valid_ids={"H1"})
        self.assertTrue(ok, leaked)

    def test_poi_id_field_itself_not_scanned_as_free_text(self):
        # Il campo strutturato "poi_id" è l'UNICO posto dove l'id grezzo è
        # legittimo (serve alla Fedeltà RAG) — non deve mai essere
        # scambiato per un "leak" nel testo libero.
        ok, leaked = check_no_raw_id_leakage(GOOD_ITINERARY, valid_ids={"H1", "POI1"})
        self.assertTrue(ok, leaked)

    def test_no_valid_ids_means_nothing_can_leak(self):
        ok, leaked = check_no_raw_id_leakage(GOOD_ITINERARY, valid_ids=set())
        self.assertTrue(ok)
        self.assertEqual(leaked, [])

    def test_id_leaked_with_different_casing_is_flagged(self):
        # [AGGIUNTO 2026-07-12 — audit di revisione completa, bug reale
        # trovato ed eseguito] Senza `re.IGNORECASE`, "h1" (minuscolo)
        # passava indenne come se non fosse lo stesso id di "H1" —
        # riprodotto direttamente prima del fix: ritornava (True, []).
        # La variabilità di maiuscole/minuscole in un output LLM è
        # plausibile, non un caso di laboratorio.
        bad = {**GOOD_ITINERARY, "executive_summary": "Raggiungibile in 10 min da h1 (hotel)."}
        ok, leaked = check_no_raw_id_leakage(bad, valid_ids={"H1"})
        self.assertFalse(ok)
        self.assertTrue(any("H1" in e for e in leaked))


class TestEnergyPacing(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo di "certezza matematica
    sulla qualità"] check_energy_pacing() generalizza
    scenario_checks.check_energy_alternation() a un controllo UNIVERSALE
    del Nodo 9 — vedi il docstring di check_energy_pacing() in
    validator.py per il razionale completo (prima era verificato solo
    per scenari di test specifici, mai su un vero cliente ENERGY_PACING
    qualsiasi).
    """

    ENERGY = {"MATCH1": "HIGH", "MATCH2": "HIGH", "MUSEO": "MEDIUM", "SPA": "LOW"}

    def test_no_op_for_non_energy_pacing_profiles(self):
        # una violazione identica passerebbe indenne per qualunque altro
        # profilo — la regola letterale è scoperta solo per ENERGY_PACING
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "MATCH1"}, {"time": "12:00", "poi_id": "MUSEO"},
        ]}]}
        ok, violations = check_energy_pacing(itin, "FRICTION_SAFETY", self.ENERGY)
        self.assertTrue(ok)
        self.assertEqual(violations, [])

    def test_no_op_when_objective_function_is_none(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "MATCH1"}, {"time": "12:00", "poi_id": "MUSEO"},
        ]}]}
        ok, violations = check_energy_pacing(itin, None, self.ENERGY)
        self.assertTrue(ok)

    def test_energy_pacing_violation_detected_when_active(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "MATCH1"}, {"time": "12:00", "poi_id": "MUSEO"},
        ]}]}
        ok, violations = check_energy_pacing(itin, "ENERGY_PACING", self.ENERGY)
        self.assertFalse(ok)
        self.assertEqual(len(violations), 1)

    def test_energy_pacing_good_case_passes_when_active(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "MATCH1"}, {"time": "12:00", "poi_id": "SPA"},
        ]}]}
        ok, violations = check_energy_pacing(itin, "ENERGY_PACING", self.ENERGY)
        self.assertTrue(ok, violations)

    def test_missing_poi_energy_by_id_treated_as_empty(self):
        itin = {"days": [{"day": 1, "blocks": [{"time": "09:00", "poi_id": "MATCH1"}]}]}
        ok, violations = check_energy_pacing(itin, "ENERGY_PACING", None)
        self.assertTrue(ok)

    def test_violation_across_day_boundary_detected(self):
        # [AGGIUNTO 2026-07-12 — audit di revisione completa, gap reale
        # trovato] Prima, la regola di adiacenza si applicava SOLO
        # all'interno dello stesso giorno — un blocco HIGH come ULTIMO
        # blocco del giorno 1 non veniva mai confrontato col PRIMO blocco
        # del giorno 2, anche se anch'esso fosse HIGH (es. partita serale
        # seguita da un allenamento la mattina dopo, nessun vero riposo
        # nel mezzo). Riprodotto: prima del fix, questo caso ritornava
        # (True, []) — un falso PASS.
        itin = {"days": [
            {"day": 1, "blocks": [{"time": "20:00", "poi_id": "MATCH1"}]},
            {"day": 2, "blocks": [{"time": "08:00", "poi_id": "MATCH2"}]},
        ]}
        ok, violations = check_energy_pacing(itin, "ENERGY_PACING", self.ENERGY)
        self.assertFalse(ok)
        self.assertEqual(len(violations), 1)
        self.assertIn("cavallo", violations[0])

    def test_recovery_across_day_boundary_passes(self):
        itin = {"days": [
            {"day": 1, "blocks": [{"time": "20:00", "poi_id": "MATCH1"}]},
            {"day": 2, "blocks": [{"time": "08:00", "poi_id": "SPA"}]},
        ]}
        ok, violations = check_energy_pacing(itin, "ENERGY_PACING", self.ENERGY)
        self.assertTrue(ok, violations)


class TestBudgetCompliance(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo di "certezza matematica
    sulla qualità"] check_budget_compliance() generalizza
    scenario_checks.check_budget_alert_when_needed() a un controllo
    UNIVERSALE del Nodo 9.
    """

    def test_no_op_for_unlimited_budget_mode(self):
        ok, violations = check_budget_compliance({"budget_alert": None}, "UNLIMITED", 0, min_cost_estimate=5000)
        self.assertTrue(ok)
        self.assertEqual(violations, [])

    def test_limited_incompatible_without_alert_fails(self):
        ok, violations = check_budget_compliance(
            {"budget_alert": None}, "LIMITED", 150.0, min_cost_estimate=2170.0
        )
        self.assertFalse(ok)
        self.assertEqual(len(violations), 1)

    def test_limited_incompatible_with_alert_passes(self):
        ok, violations = check_budget_compliance(
            {"budget_alert": "Budget insufficiente, servono 2170€"}, "LIMITED", 150.0,
            min_cost_estimate=2170.0,
        )
        self.assertTrue(ok, violations)

    def test_limited_without_min_cost_estimate_is_informative_only(self):
        # onestà sui limiti: senza un prezzo di riferimento non possiamo
        # verificare la matematica, quindi non facciamo fallire nulla
        ok, violations = check_budget_compliance({"budget_alert": None}, "LIMITED", 150.0)
        self.assertTrue(ok)

    def test_limited_budget_sufficient_passes_even_without_alert(self):
        ok, violations = check_budget_compliance(
            {"budget_alert": None}, "LIMITED", 5000.0, min_cost_estimate=2170.0
        )
        self.assertTrue(ok)


class TestValidateItineraryIntegration(unittest.TestCase):
    def test_good_itinerary_passes_overall(self):
        report = validate_itinerary(GOOD_ITINERARY, valid_ids={"H1", "POI1"})
        self.assertTrue(report.passed)

    def test_hallucination_fails_overall(self):
        report = validate_itinerary(GOOD_ITINERARY, valid_ids={"H1"})
        self.assertFalse(report.passed)
        self.assertFalse(report.rag_fidelity_ok)

    def test_leaked_id_fails_overall(self):
        # [AGGIUNTO 2026-07-12] check_no_raw_id_leakage() deve contribuire
        # a `passed` esattamente come gli altri controlli del Nodo 9 — un
        # itinerario che perde questo controllo non deve mai risultare
        # PASS nel suo complesso.
        bad = {**GOOD_ITINERARY, "executive_summary": "Le terme (POI1) sono l'unico POI aperto."}
        report = validate_itinerary(bad, valid_ids={"H1", "POI1"})
        self.assertFalse(report.passed)
        self.assertFalse(report.no_id_leakage_ok)
        self.assertTrue(report.leaked_raw_ids)

    def test_expected_duration_days_not_passed_by_default_no_regression(self):
        # GOOD_ITINERARY ha un solo giorno: senza passare expected_duration_days
        # esplicitamente, validate_itinerary si comporta come prima di questo
        # fix (nessuna rottura per i chiamanti esistenti che non lo passano).
        report = validate_itinerary(GOOD_ITINERARY, valid_ids={"H1", "POI1"})
        self.assertTrue(report.passed)

    def test_expected_duration_days_forwarded_to_format_compliance(self):
        # [AGGIUNTO 2026-07-12 — audit di potenziamento massimo] Se passato,
        # il parametro deve arrivare fino a check_format_compliance() e
        # contribuire a report.passed esattamente come gli altri controlli.
        report = validate_itinerary(GOOD_ITINERARY, valid_ids={"H1", "POI1"}, expected_duration_days=3)
        self.assertFalse(report.passed)
        self.assertFalse(report.format_compliance_ok)
        self.assertTrue(any("attesi esattamente 3" in e for e in report.format_errors))

    def test_energy_pacing_and_budget_no_op_by_default_no_regression(self):
        # [AGGIUNTO 2026-07-12 — certezza matematica] Nessuno dei nuovi
        # parametri passato esplicitamente: comportamento invariato per
        # ogni chiamante esistente che non li conosce ancora.
        report = validate_itinerary(GOOD_ITINERARY, valid_ids={"H1", "POI1"})
        self.assertTrue(report.passed)
        self.assertTrue(report.energy_pacing_ok)
        self.assertTrue(report.budget_compliance_ok)

    def test_energy_pacing_violation_fails_overall_when_wired(self):
        bad = {**GOOD_ITINERARY, "days": [{"day": 1, "blocks": [
            {"time": "16:00", "activity": "Torneo", "location": "Campo", "logistics": "", "poi_id": "H1"},
            {"time": "19:00", "activity": "Museo", "location": "Museo", "logistics": "", "poi_id": "POI1"},
        ]}]}
        report = validate_itinerary(
            bad, valid_ids={"H1", "POI1"},
            objective_function="ENERGY_PACING",
            poi_energy_by_id={"H1": "HIGH", "POI1": "MEDIUM"},
        )
        self.assertFalse(report.passed)
        self.assertFalse(report.energy_pacing_ok)
        self.assertTrue(report.energy_pacing_violations)

    def test_budget_violation_fails_overall_when_wired(self):
        bad = {**GOOD_ITINERARY, "budget_alert": None}
        report = validate_itinerary(
            bad, valid_ids={"H1", "POI1"},
            budget_mode="LIMITED", budget_eur=100.0, min_cost_estimate=2000.0,
        )
        self.assertFalse(report.passed)
        self.assertFalse(report.budget_compliance_ok)
        self.assertTrue(report.budget_compliance_violations)


class TestStripReasoning(unittest.TestCase):
    def test_removes_reasoning_key(self):
        sanitized = strip_reasoning(GOOD_ITINERARY)
        self.assertNotIn("reasoning", sanitized)
        self.assertIn("destination", sanitized)  # resto intatto

    def test_original_dict_not_mutated(self):
        strip_reasoning(GOOD_ITINERARY)
        self.assertIn("reasoning", GOOD_ITINERARY)  # l'originale non deve cambiare


if __name__ == "__main__":
    unittest.main()
