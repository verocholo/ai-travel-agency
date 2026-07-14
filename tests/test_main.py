"""
[AGGIUNTO 2026-07-11 — audit qualità + Fase 2] Prima suite di test mai
scritta per main.py — copre solo il pezzo a più alto rischio silenzioso:
le mappe scenario -> controllo automatico (_SCENARIO_ENERGY_CHECK,
_SCENARIO_BUDGET_CHECK, _SCENARIO_EXCLUDED_POI_CHECK,
_SCENARIO_RIGID_WINDOW_CHECK, _SCENARIO_RIGID_WINDOW_EXTRA_SAFE_IDS) sono
scritte a mano e referenziano chiavi di src.mock_rag_data.SCENARIOS per
stringa — un typo in una di queste chiavi non verrebbe mai rilevato da
nessun test esistente, solo al primo lancio reale di quello scenario
specifico (get_mock_payload() solleverebbe un KeyError criptico). Stesso
principio anti-desync già applicato altrove in questa sessione
(VALID_OBJECTIVE_FUNCTIONS <-> deduce_objective_function,
OBJECTIVE_FUNCTION_TO_MODULE <-> VALID_OBJECTIVE_FUNCTIONS).
"""
import unittest
from unittest.mock import MagicMock, patch

import main
from src.mock_rag_data import SCENARIOS
from src.schemas import ApiPayload, POI, Trip
from src.guide_generator import GuideGeneratorError
from src.feedback_generator import FeedbackGeneratorError


class TestScenarioCheckWiringConsistency(unittest.TestCase):
    def test_scenario_check_dicts_are_not_empty(self):
        # [AGGIUNTO 2026-07-11 — audit di qualità, secondo giro] Gap reale:
        # tutti i test sotto usano `for scenario in main._SCENARIO_X:
        # assertIn(...)` — un `for` su un dict VUOTO non itera nulla e il
        # test passa comunque, "verde" senza aver verificato niente. Se un
        # futuro refactor svuotasse per errore uno di questi dict (es. un
        # merge sbagliato), questi test continuerebbero a passare in
        # silenzio. Questo test rende esplicito che ci si aspetta
        # contenuto reale in ciascuno.
        for name in (
            "_SCENARIO_ENERGY_CHECK", "_SCENARIO_BUDGET_CHECK", "_SCENARIO_EXCLUDED_POI_CHECK",
            "_SCENARIO_RIGID_WINDOW_CHECK", "_SCENARIO_SLOT_LIBERO_TRANSPARENCY_CHECK",
        ):
            self.assertTrue(getattr(main, name), f"main.{name} è vuoto — i test 'for scenario in ...' sotto sarebbero no-op")

    def test_energy_check_scenarios_exist_in_mock_rag_data(self):
        for scenario in main._SCENARIO_ENERGY_CHECK:
            self.assertIn(scenario, SCENARIOS, f"'{scenario}' non esiste in mock_rag_data.SCENARIOS")

    def test_budget_check_scenarios_exist_in_mock_rag_data(self):
        for scenario in main._SCENARIO_BUDGET_CHECK:
            self.assertIn(scenario, SCENARIOS, f"'{scenario}' non esiste in mock_rag_data.SCENARIOS")

    def test_excluded_poi_check_scenarios_exist_in_mock_rag_data(self):
        for scenario in main._SCENARIO_EXCLUDED_POI_CHECK:
            self.assertIn(scenario, SCENARIOS, f"'{scenario}' non esiste in mock_rag_data.SCENARIOS")

    def test_rigid_window_check_scenarios_exist_in_mock_rag_data(self):
        for scenario in main._SCENARIO_RIGID_WINDOW_CHECK:
            self.assertIn(scenario, SCENARIOS, f"'{scenario}' non esiste in mock_rag_data.SCENARIOS")

    def test_slot_libero_transparency_check_scenarios_exist_in_mock_rag_data(self):
        # [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità]
        # check_slot_libero_transparency() esisteva da tempo con una
        # propria suite di test, ma non era mai stata collegata a questo
        # dispatch (dead code in produzione) finché non è stato trovato in
        # questo audit — stesso principio anti-desync già applicato agli
        # altri _SCENARIO_* dict qui sopra.
        for scenario in main._SCENARIO_SLOT_LIBERO_TRANSPARENCY_CHECK:
            self.assertIn(scenario, SCENARIOS, f"'{scenario}' non esiste in mock_rag_data.SCENARIOS")

    def test_rigid_window_extra_safe_ids_scenarios_exist_in_mock_rag_data(self):
        for scenario in main._SCENARIO_RIGID_WINDOW_EXTRA_SAFE_IDS:
            self.assertIn(scenario, SCENARIOS, f"'{scenario}' non esiste in mock_rag_data.SCENARIOS")

    def test_rigid_window_extra_safe_ids_only_used_where_a_window_check_exists(self):
        # Un'entry in _SCENARIO_RIGID_WINDOW_EXTRA_SAFE_IDS senza una
        # corrispondente entry in _SCENARIO_RIGID_WINDOW_CHECK non
        # verrebbe mai letta da _apply_scenario_checks() — dead config.
        for scenario in main._SCENARIO_RIGID_WINDOW_EXTRA_SAFE_IDS:
            self.assertIn(scenario, main._SCENARIO_RIGID_WINDOW_CHECK,
                          f"'{scenario}' ha extra_safe_ids ma nessun _SCENARIO_RIGID_WINDOW_CHECK corrispondente")

    def test_rigid_window_bounds_are_valid_hhmm_and_start_before_end(self):
        # Regressione diretta per il bug trovato in audit in
        # scenario_checks.py (window_start >= window_end passava sempre
        # "nessuna violazione"): verifica che nessuna entry di
        # configurazione reale in main.py sia essa stessa mal configurata.
        for scenario, (start, end) in main._SCENARIO_RIGID_WINDOW_CHECK.items():
            h1, m1 = start.split(":")
            h2, m2 = end.split(":")
            start_min = int(h1) * 60 + int(m1)
            end_min = int(h2) * 60 + int(m2)
            self.assertLess(start_min, end_min, f"'{scenario}': window_start {start} non precede window_end {end}")


class TestRunFreshnessCheckRespectsMode(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — bug reale trovato ED ESEGUITO da Lorenzo dal
    vivo sul suo PC] `_run_freshness_check()` ignorava silenziosamente
    `--mode live`: chiamava SEMPRE `run_mock()` + `get_mock_payload()`,
    producendo lo stesso identico report (nomi/ID fittizi della fixture
    mock) sia con `--mode mock` sia con `--mode live --check-freshness`.
    Lorenzo ha lanciato entrambi i comandi aspettandosi risultati diversi
    e ha ricevuto output identico byte-per-byte — segnale del bug. Questi
    test bloccano la regressione mockando run_mock/run_live/
    get_mock_payload/freshness_check.run_freshness_check e verificando
    quale viene davvero chiamato in base a `mode`.
    """

    def _fake_result(self, api_payload):
        result = MagicMock()
        result.itinerary = {"days": []}
        result.validation_report.summary.return_value = "PASS"
        result.trip = MagicMock()
        result.api_payload = api_payload
        result.data_layer_error = None
        return result

    @patch("main.freshness_check")
    @patch("main.get_mock_payload")
    @patch("main.run_live")
    @patch("main.run_mock")
    @patch("main.SETTINGS")
    def test_mode_live_calls_run_live_not_run_mock(self, mock_settings, mock_run_mock, mock_run_live,
                                                     mock_get_mock_payload, mock_freshness_check):
        mock_settings.missing_for_live_mode.return_value = []
        live_api_payload = object()  # sentinel: "l'ApiPayload REALE di run_live()"
        mock_run_live.return_value = self._fake_result(live_api_payload)
        mock_freshness_check.run_freshness_check.return_value = MagicMock(summary=lambda: "ok")

        main._run_freshness_check("fixtures/trip_happy_path.json", "happy_path", mode="live")

        mock_run_live.assert_called_once()
        mock_run_mock.assert_not_called()
        mock_get_mock_payload.assert_not_called()
        # L'ApiPayload passato al controllo di freschezza deve essere
        # quello REALE di run_live(), non quello mock.
        _, kwargs = mock_freshness_check.run_freshness_check.call_args
        called_api_payload = mock_freshness_check.run_freshness_check.call_args[0][1]
        self.assertIs(called_api_payload, live_api_payload)

    @patch("main.freshness_check")
    @patch("main.get_mock_payload")
    @patch("main.run_live")
    @patch("main.run_mock")
    @patch("main.SETTINGS")
    def test_mode_mock_calls_run_mock_not_run_live(self, mock_settings, mock_run_mock, mock_run_live,
                                                     mock_get_mock_payload, mock_freshness_check):
        mock_settings.missing_for_live_mode.return_value = []
        mock_get_mock_payload.return_value = object()
        mock_run_mock.return_value = self._fake_result(api_payload=None)
        mock_freshness_check.run_freshness_check.return_value = MagicMock(summary=lambda: "ok")

        main._run_freshness_check("fixtures/trip_happy_path.json", "happy_path", mode="mock")

        mock_run_mock.assert_called_once()
        mock_run_live.assert_not_called()
        mock_get_mock_payload.assert_called_once_with("happy_path")


class TestBuildPdfExtras(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "ok ora prima di fare il
    resto fai in modo di aggiungerli al pdf che si genera", chiarita con
    "Voglio tutti e tre nello stesso PDF"] Copre `main._build_pdf_extras()`
    — la nuova orchestrazione che genera guide turistiche per-POI e il
    messaggio di feedback post-viaggio da incorporare nel PDF cliente,
    invece che solo come file .md separati (--guide/--feedback). Mocka
    `guide_generator`/`feedback_generator` (stesso principio già seguito
    per gli altri test di main.py: nessuna chiamata di rete reale a
    Claude).

    [AGGIORNATO 2026-07-12 — "ristoranti"/"hotel"/"intrattenimento" curati,
    "cartina + percorsi"] `_build_pdf_extras()` ora ritorna una 4-tupla
    `(guides, feedback, used_pois, map_png_bytes)`, non più solo
    `(guides, feedback)` — tutti i test sotto aggiornati per spacchettare
    4 valori. Le chiamate che non passano `google_maps_key` esplicitamente
    usano il default `None`, per cui `maps_static.build_map_for_itinerary()`
    ritorna `None` immediatamente (nessuna chiamata di rete — vedi il primo
    `if not api_key: return None` in maps_static.py), coerente con lo stesso
    principio "nessuna chiamata di rete reale" già seguito per guide/feedback.
    """

    def _trip(self):
        return Trip(
            email="a@b.com", destination="Val d'Orcia", date_start="2026-09-01",
            date_end="2026-09-04", duration_days=3, budget_eur=0, budget_mode="UNLIMITED",
            objective_function="ENERGY_PACING",
        )

    def _api_payload(self):
        poi1 = POI(id="P1", type="activity", name="Terme di San Filippo", lat=42.9, lng=11.6)
        poi2 = POI(id="P2", type="museum", name="Museo Etrusco", lat=43.0, lng=11.7)
        return ApiPayload(hotels=[], travel_times=[], poi=[poi1, poi2])

    def _itinerary(self, poi_ids):
        return {
            "days": [
                {"day": 1, "blocks": [{"time": "09:00", "activity": "Visita", "poi_id": pid} for pid in poi_ids]}
            ]
        }

    @patch("src.pdf_extras.feedback_generator")
    @patch("src.pdf_extras.guide_generator")
    def test_generates_one_guide_per_used_poi_and_one_feedback(self, mock_guide_gen, mock_feedback_gen):
        mock_guide_gen.generate_poi_guide.return_value = {"title": "Guida", "poi_name": "x"}
        mock_guide_gen.GuideGeneratorError = GuideGeneratorError
        mock_feedback_gen.generate_post_trip_feedback.return_value = {"intro_message": "ciao"}
        mock_feedback_gen.FeedbackGeneratorError = FeedbackGeneratorError

        itinerary = self._itinerary(["P1", "P2"])
        guides, feedback, used_pois, map_png_bytes = main._build_pdf_extras(
            itinerary, self._trip(), self._api_payload(), "fake-key"
        )

        self.assertEqual(mock_guide_gen.generate_poi_guide.call_count, 2)
        self.assertEqual(len(guides), 2)
        self.assertEqual(feedback, {"intro_message": "ciao"})
        self.assertEqual({p["id"] for p in used_pois}, {"P1", "P2"})
        self.assertIsNone(map_png_bytes)

    @patch("src.pdf_extras.feedback_generator")
    @patch("src.pdf_extras.guide_generator")
    def test_poi_not_referenced_in_itinerary_gets_no_guide(self, mock_guide_gen, mock_feedback_gen):
        # Solo P1 è effettivamente usato nell'itinerario — P2 esiste in
        # api_payload.poi ma non deve generare una guida (stesso principio
        # di freshness_check.run_freshness_check(): verificare solo ciò che
        # è EFFETTIVAMENTE USATO, non l'intero DATI_API_FORNITI).
        mock_guide_gen.generate_poi_guide.return_value = {"title": "Guida"}
        mock_guide_gen.GuideGeneratorError = GuideGeneratorError
        mock_feedback_gen.generate_post_trip_feedback.return_value = {"intro_message": "ciao"}
        mock_feedback_gen.FeedbackGeneratorError = FeedbackGeneratorError

        itinerary = self._itinerary(["P1"])
        guides, _, used_pois, _ = main._build_pdf_extras(itinerary, self._trip(), self._api_payload(), "fake-key")

        self.assertEqual(mock_guide_gen.generate_poi_guide.call_count, 1)
        self.assertEqual({p["id"] for p in used_pois}, {"P1"})
        mock_guide_gen.generate_poi_guide.assert_called_once_with(
            "Terme di San Filippo", "Val d'Orcia", api_key="fake-key",
            objective_function="ENERGY_PACING", module_id=mock_guide_gen.generate_poi_guide.call_args.kwargs["module_id"],
        )

    @patch("src.pdf_extras.feedback_generator")
    @patch("src.pdf_extras.guide_generator")
    def test_one_failing_guide_does_not_block_the_others_or_feedback(self, mock_guide_gen, mock_feedback_gen):
        # [Stesso principio "degrada senza rompere il resto" già applicato
        # altrove nel prototipo] Una singola guida che fallisce (rete,
        # parsing, campo mancante) non deve far saltare le altre guide né
        # il feedback né l'intera generazione del PDF.
        mock_guide_gen.GuideGeneratorError = GuideGeneratorError
        mock_guide_gen.generate_poi_guide.side_effect = [
            GuideGeneratorError("boom"), {"title": "Guida OK"},
        ]
        mock_feedback_gen.generate_post_trip_feedback.return_value = {"intro_message": "ciao"}
        mock_feedback_gen.FeedbackGeneratorError = FeedbackGeneratorError

        itinerary = self._itinerary(["P1", "P2"])
        guides, feedback, used_pois, _ = main._build_pdf_extras(
            itinerary, self._trip(), self._api_payload(), "fake-key"
        )

        self.assertEqual(len(guides), 1)
        self.assertEqual(guides[0], {"title": "Guida OK"})
        self.assertEqual(feedback, {"intro_message": "ciao"})
        # [Fedeltà RAG] used_pois riflette gli id EFFETTIVAMENTE usati
        # nell'itinerario, non dipende dal successo/fallimento della guida
        # — la guida è un contenuto extra, non la fonte di verità sui POI
        # usati (quella è extract_used_poi_ids()).
        self.assertEqual({p["id"] for p in used_pois}, {"P1", "P2"})

    @patch("src.pdf_extras.feedback_generator")
    @patch("src.pdf_extras.guide_generator")
    def test_failing_feedback_returns_none_but_does_not_raise(self, mock_guide_gen, mock_feedback_gen):
        mock_guide_gen.GuideGeneratorError = GuideGeneratorError
        mock_guide_gen.generate_poi_guide.return_value = {"title": "Guida"}
        mock_feedback_gen.FeedbackGeneratorError = FeedbackGeneratorError
        mock_feedback_gen.generate_post_trip_feedback.side_effect = FeedbackGeneratorError("boom")

        itinerary = self._itinerary(["P1"])
        guides, feedback, used_pois, _ = main._build_pdf_extras(
            itinerary, self._trip(), self._api_payload(), "fake-key"
        )

        self.assertEqual(len(guides), 1)
        self.assertIsNone(feedback)
        self.assertEqual({p["id"] for p in used_pois}, {"P1"})

    @patch("src.pdf_extras.feedback_generator")
    @patch("src.pdf_extras.guide_generator")
    def test_no_poi_ids_in_itinerary_produces_no_guides(self, mock_guide_gen, mock_feedback_gen):
        mock_guide_gen.GuideGeneratorError = GuideGeneratorError
        mock_feedback_gen.FeedbackGeneratorError = FeedbackGeneratorError
        mock_feedback_gen.generate_post_trip_feedback.return_value = {"intro_message": "ciao"}

        itinerary = {"days": [{"day": 1, "blocks": [{"time": "09:00", "activity": "Libero"}]}]}
        guides, feedback, used_pois, map_png_bytes = main._build_pdf_extras(
            itinerary, self._trip(), self._api_payload(), "fake-key"
        )

        mock_guide_gen.generate_poi_guide.assert_not_called()
        self.assertEqual(guides, [])
        self.assertIsNotNone(feedback)
        self.assertEqual(used_pois, [])
        self.assertIsNone(map_png_bytes)

    @patch("src.pdf_extras.feedback_generator")
    @patch("src.pdf_extras.guide_generator")
    def test_no_google_maps_key_gives_none_map_without_network_call(self, mock_guide_gen, mock_feedback_gen):
        # [AGGIUNTO 2026-07-12 — "cartina + percorsi"] Nessuna chiave ->
        # `maps_static.build_map_for_itinerary()` ritorna `None` subito
        # (vedi `if not api_key: return None` in maps_static.py) — stesso
        # principio "degrada senza rompere il resto" già verificato per
        # guida/feedback, ora esteso alla cartina.
        mock_guide_gen.GuideGeneratorError = GuideGeneratorError
        mock_guide_gen.generate_poi_guide.return_value = {"title": "Guida"}
        mock_feedback_gen.FeedbackGeneratorError = FeedbackGeneratorError
        mock_feedback_gen.generate_post_trip_feedback.return_value = {"intro_message": "ciao"}

        itinerary = self._itinerary(["P1"])
        _, _, _, map_png_bytes = main._build_pdf_extras(
            itinerary, self._trip(), self._api_payload(), "fake-key", google_maps_key=None,
        )

        self.assertIsNone(map_png_bytes)

    @patch("src.pdf_extras.maps_static")
    @patch("src.pdf_extras.feedback_generator")
    @patch("src.pdf_extras.guide_generator")
    def test_google_maps_key_provided_calls_build_map_for_itinerary(
        self, mock_guide_gen, mock_feedback_gen, mock_maps_static
    ):
        # [AGGIUNTO 2026-07-12 — "cartina + percorsi"] Quando la chiave è
        # configurata, `_build_pdf_extras()` deve effettivamente invocare
        # `maps_static.build_map_for_itinerary()` con i dati reali
        # (hotels/poi di api_payload, l'itinerario, la chiave) e propagare
        # il PNG risultante — mockato qui (nessuna chiamata di rete reale
        # a Google, coerente con test_maps_static.py che copre la funzione
        # in isolamento).
        mock_guide_gen.GuideGeneratorError = GuideGeneratorError
        mock_guide_gen.generate_poi_guide.return_value = {"title": "Guida"}
        mock_feedback_gen.FeedbackGeneratorError = FeedbackGeneratorError
        mock_feedback_gen.generate_post_trip_feedback.return_value = {"intro_message": "ciao"}
        mock_maps_static.build_map_for_itinerary.return_value = b"fake-png-bytes"

        api_payload = self._api_payload()
        itinerary = self._itinerary(["P1"])
        _, _, _, map_png_bytes = main._build_pdf_extras(
            itinerary, self._trip(), api_payload, "fake-key", google_maps_key="fake-maps-key",
        )

        mock_maps_static.build_map_for_itinerary.assert_called_once_with(
            api_payload.hotels, api_payload.poi, itinerary, "fake-maps-key",
        )
        self.assertEqual(map_png_bytes, b"fake-png-bytes")

    @patch("src.pdf_extras.maps_static")
    @patch("src.pdf_extras.feedback_generator")
    @patch("src.pdf_extras.guide_generator")
    def test_map_generation_failure_does_not_block_guides_or_feedback(
        self, mock_guide_gen, mock_feedback_gen, mock_maps_static
    ):
        # [Stesso principio "degrada senza rompere il resto"] Anche se
        # `maps_static` ritornasse `None` (fallimento interno già gestito
        # lì, mai un'eccezione verso questo chiamante), guide e feedback
        # non devono risentirne.
        mock_guide_gen.GuideGeneratorError = GuideGeneratorError
        mock_guide_gen.generate_poi_guide.return_value = {"title": "Guida"}
        mock_feedback_gen.FeedbackGeneratorError = FeedbackGeneratorError
        mock_feedback_gen.generate_post_trip_feedback.return_value = {"intro_message": "ciao"}
        mock_maps_static.build_map_for_itinerary.return_value = None

        itinerary = self._itinerary(["P1"])
        guides, feedback, used_pois, map_png_bytes = main._build_pdf_extras(
            itinerary, self._trip(), self._api_payload(), "fake-key", google_maps_key="fake-maps-key",
        )

        self.assertEqual(len(guides), 1)
        self.assertEqual(feedback, {"intro_message": "ciao"})
        self.assertEqual({p["id"] for p in used_pois}, {"P1"})
        self.assertIsNone(map_png_bytes)


class TestFixtureErrorHandlingConsistency(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità] Prima,
    solo `_run_one()` trasformava un fixture mancante/malformato in un
    messaggio "❌ ..." leggibile (vedi `_safe_fixture_call()`) — `--guide`/
    `--refine`/`--check-freshness`/`--feedback` propagavano invece un
    `FileNotFoundError`/`json.JSONDecodeError` grezzo. Questi test
    verificano che le quattro funzioni ritornino `False` in modo pulito
    (non un'eccezione) per un fixture inesistente, invece di limitarsi a
    testare _safe_fixture_call() in isolamento — la garanzia che conta è
    che OGNI punto di ingresso del CLI la usi davvero.
    """

    def _settings_with_no_missing_vars(self, mock_settings):
        mock_settings.missing_for_mock_mode.return_value = []
        mock_settings.missing_for_live_mode.return_value = []
        mock_settings.anthropic_api_key = "fake-key"

    @patch("main.SETTINGS")
    def test_run_guide_missing_fixture_returns_false_not_raise(self, mock_settings):
        self._settings_with_no_missing_vars(mock_settings)
        self.assertFalse(main._run_guide("fixtures/non_esiste.json", "Colosseo"))

    @patch("main.SETTINGS")
    def test_run_refine_missing_fixture_returns_false_not_raise(self, mock_settings):
        self._settings_with_no_missing_vars(mock_settings)
        self.assertFalse(main._run_refine("fixtures/non_esiste.json", "happy_path", "cambia il giorno 2"))

    @patch("main.SETTINGS")
    def test_run_freshness_check_mock_missing_fixture_returns_false_not_raise(self, mock_settings):
        self._settings_with_no_missing_vars(mock_settings)
        self.assertFalse(main._run_freshness_check("fixtures/non_esiste.json", "happy_path", mode="mock"))

    @patch("main.SETTINGS")
    def test_run_freshness_check_live_missing_fixture_returns_false_not_raise(self, mock_settings):
        self._settings_with_no_missing_vars(mock_settings)
        self.assertFalse(main._run_freshness_check("fixtures/non_esiste.json", "happy_path", mode="live"))

    @patch("main.SETTINGS")
    def test_run_feedback_missing_fixture_returns_false_not_raise(self, mock_settings):
        self._settings_with_no_missing_vars(mock_settings)
        self.assertFalse(main._run_feedback("fixtures/non_esiste.json", "happy_path"))

    @patch("main.SETTINGS")
    def test_run_guide_malformed_json_returns_false_not_raise(self, mock_settings):
        # File presente ma JSON non valido -> stesso trattamento pulito.
        self._settings_with_no_missing_vars(mock_settings)
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("questo non e' JSON valido {{{")
            bad_path = f.name
        try:
            self.assertFalse(main._run_guide(bad_path, "Colosseo"))
        finally:
            import os
            os.unlink(bad_path)


if __name__ == "__main__":
    unittest.main()
