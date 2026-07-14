"""
[AGGIUNTO 2026-07-11] Prima suite di test per pipeline.py — non esisteva
alcuna copertura prima d'ora. Nata direttamente dal bug critico scoperto
seguendo l'istruzione di Lorenzo "massima qualità per un prodotto da
lanciare sul mercato": run_live() chiamava sempre
modules.get_module(modules.DEFAULT_MODULE_ID), cioè SEMPRE il modulo
sport, ignorando trip.objective_function. Family e Work erano
funzionalmente irraggiungibili in modalità live nonostante fossero
completamente costruiti e unit-testati — perché run_mock() bypassa del
tutto modules.py/places_client.py (usa payload finti pre-costruiti) e
nessun test toccava mai run_live().

Questi test mockano TUTTE le chiamate HTTP reali (geocoding, LiteAPI,
Places, Distance Matrix, Claude) — nessuna rete richiesta, coerente col
fatto che questo sandbox può raggiungere solo api.anthropic.com. Lo scopo
non è validare le risposte HTTP (già coperto altrove: test_geocoding.py,
test_liteapi_mapping.py, test_places_mapping.py, test_distance_matrix.py)
ma la CABLATURA di run_live(): che il modulo giusto (quindi le
`included_types` giuste) venga passato a places_client.search_nearby() in
base a trip.objective_function, per ciascuno dei tre moduli oggi
esistenti.
"""
import re
import unittest
from dataclasses import dataclass
from unittest.mock import patch, MagicMock

import requests

from src import pipeline
from src.schemas import Hotel, POI
from src.geocoding import GeocodingError


@dataclass
class _FakeSettings:
    anthropic_api_key: str = "fake-anthropic-key"
    google_maps_key: str = "fake-google-key"
    liteapi_key: str = "fake-liteapi-key"


_FAKE_HOTEL = Hotel(id="H1", name="Hotel Test", lat=38.11, lng=15.66, price_night_eur=100.0, stars=4.0)

# location_type="ROOFTOP" -> is_imprecise_match() è False -> nessun
# geocoding_warning nei test che non lo testano esplicitamente.
_PRECISE_GEOCODE_FULL = {
    "lat": 38.11, "lng": 15.66, "location_type": "ROOFTOP", "formatted_address": "Via Test 1",
}


class TestRunLiveModuleSelection(unittest.TestCase):
    """[2026-07-11] Regressione diretta per il bug: verifica che
    run_live() chieda a Places le categorie del modulo corretto per ogni
    objective_function, non sempre quelle del modulo sport."""

    def _run_live_with_mocks(self, fixture_path: str, geocode_full_return=None):
        with patch("src.geocoding.geocode_full", return_value=geocode_full_return or _PRECISE_GEOCODE_FULL) as mock_geocode, \
             patch("src.liteapi_client.LiteApiClient") as MockLiteApiClient, \
             patch("src.liteapi_client.select_anchor_hotel", return_value=[_FAKE_HOTEL]), \
             patch("src.places_client.search_nearby", return_value=[]) as mock_search_nearby, \
             patch("src.distance_matrix.get_distance_matrix", return_value=[]), \
             patch("src.pipeline.call_claude", return_value="NON E' JSON VALIDO — irrilevante per questo test"):

            mock_instance = MockLiteApiClient.return_value
            mock_instance.search_hotels_by_geocode.return_value = []
            mock_instance.search_hotel_offers.return_value = []

            result = pipeline.run_live(fixture_path, _FakeSettings())

            self.assertTrue(mock_geocode.called)
            self.assertTrue(mock_search_nearby.called)
            return result, mock_search_nearby

    def test_sport_fixture_requests_sport_categories(self):
        # trip_happy_path.json -> scopo "Torneo di tennis amatoriale" -> ENERGY_PACING
        _, mock_search_nearby = self._run_live_with_mocks("fixtures/trip_happy_path.json")
        _, kwargs = mock_search_nearby.call_args
        included = kwargs["included_types"]
        self.assertIn("tennis_court", included)
        self.assertIn("sports_complex", included)
        self.assertNotIn("coworking_space", included)
        self.assertNotIn("zoo", included)

    def test_family_fixture_requests_family_categories(self):
        # trip_test_friction_safety_famiglia.json -> FRICTION_SAFETY
        _, mock_search_nearby = self._run_live_with_mocks("fixtures/trip_test_friction_safety_famiglia.json")
        _, kwargs = mock_search_nearby.call_args
        included = kwargs["included_types"]
        self.assertIn("zoo", included)
        self.assertIn("water_park", included)
        self.assertNotIn("tennis_court", included)
        self.assertNotIn("coworking_space", included)

    def test_work_fixture_requests_work_categories(self):
        # trip_test_work_connectivity_nomade.json -> WORK_CONNECTIVITY
        _, mock_search_nearby = self._run_live_with_mocks("fixtures/trip_test_work_connectivity_nomade.json")
        _, kwargs = mock_search_nearby.call_args
        included = kwargs["included_types"]
        self.assertIn("coworking_space", included)
        self.assertIn("business_center", included)
        self.assertNotIn("tennis_court", included)
        self.assertNotIn("zoo", included)

    def test_all_three_fixtures_still_include_base_categories(self):
        # Le 4 categorie universali (restaurant/tourist_attraction/museum/park)
        # devono restare presenti indipendentemente dal modulo selezionato.
        for fixture in (
            "fixtures/trip_happy_path.json",
            "fixtures/trip_test_friction_safety_famiglia.json",
            "fixtures/trip_test_work_connectivity_nomade.json",
        ):
            _, mock_search_nearby = self._run_live_with_mocks(fixture)
            _, kwargs = mock_search_nearby.call_args
            included = kwargs["included_types"]
            for base in ("restaurant", "tourist_attraction", "museum", "park"):
                self.assertIn(base, included, f"'{base}' mancante per {fixture}")

    def test_result_is_a_pipeline_result_even_with_parse_error(self):
        # Non un test sul contenuto dell'itinerario (Claude è mockato con
        # output non-JSON deliberatamente): verifica solo che run_live()
        # non esploda e propaghi correttamente il parse_error invece di
        # un crash, coerente col resto della pipeline (_call_claude_and_validate).
        result, _ = self._run_live_with_mocks("fixtures/trip_happy_path.json")
        self.assertIsNone(result.itinerary)
        self.assertIsNotNone(result.parse_error)

    def test_api_payload_is_exposed_with_real_live_hotels(self):
        # [AGGIUNTO 2026-07-12 — bug reale trovato ED ESEGUITO da Lorenzo
        # dal vivo] Prima di questo fix, PipelineResult non esponeva MAI
        # l'ApiPayload costruito da run_live() (hotel/POI con ID/coordinate
        # REALI) — vedi la nota estesa in main.py:_run_freshness_check() e
        # in questo file. `--check-freshness --mode live` non aveva quindi
        # altra scelta che riusare sempre get_mock_payload(), rendendo
        # impossibile un vero esito positivo del controllo di freschezza.
        # Questo test verifica che result.api_payload esista e contenga
        # davvero l'hotel restituito da select_anchor_hotel() in questa
        # run live (non None, non i dati mock).
        result, _ = self._run_live_with_mocks("fixtures/trip_happy_path.json")
        self.assertIsNotNone(result.api_payload)
        self.assertEqual([h.id for h in result.api_payload.hotels], ["H1"])
        self.assertEqual(result.api_payload.hotels[0].name, "Hotel Test")


class TestRunLiveErrorHandling(unittest.TestCase):
    """[AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Prima, un fallimento
    reale in Geocoding/LiteAPI/Places/Distance Matrix (tutti scenari
    documentati come possibili — status ZERO_RESULTS, un 4xx/5xx HTTP,
    ecc.) propagava come traceback Python grezzo. Questi test verificano
    che run_live() lo trasformi invece in un PipelineResult leggibile
    (data_layer_error), senza crashare."""

    def test_geocoding_error_becomes_data_layer_error_not_a_crash(self):
        with patch("src.geocoding.geocode_full", side_effect=GeocodingError("ZERO_RESULTS")):
            result = pipeline.run_live("fixtures/trip_happy_path.json", _FakeSettings())
        self.assertIsNotNone(result.data_layer_error)
        self.assertIn("ZERO_RESULTS", result.data_layer_error)
        self.assertIsNone(result.itinerary)

    def test_places_http_error_becomes_data_layer_error_not_a_crash(self):
        with patch("src.geocoding.geocode_full", return_value=_PRECISE_GEOCODE_FULL), \
             patch("src.liteapi_client.LiteApiClient") as MockLiteApiClient, \
             patch("src.liteapi_client.select_anchor_hotel", return_value=[_FAKE_HOTEL]), \
             patch("src.places_client.search_nearby", side_effect=requests.exceptions.HTTPError("500 Server Error")):
            mock_instance = MockLiteApiClient.return_value
            mock_instance.search_hotels_by_geocode.return_value = []
            mock_instance.search_hotel_offers.return_value = []
            result = pipeline.run_live("fixtures/trip_happy_path.json", _FakeSettings())
        self.assertIsNotNone(result.data_layer_error)
        self.assertIsNone(result.itinerary)


class TestEnumSafetyBeforeAnyClaudeCall(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — richiesta di Lorenzo di "certezza matematica
    sulla qualità"] `system_prompt_master.txt` §[HARD_CONSTRAINTS] punto 7
    istruisce Claude su un fallback se riceve un `objective_function`/
    `budget_mode` non riconosciuto — ma un'istruzione al modello non è mai
    una garanzia assoluta. La garanzia REALE, più forte, è strutturale:
    su OGNI percorso di questo codebase, un `Trip` con un enum invalido
    non può fisicamente raggiungere Claude, per due motivi indipendenti:

    (1) `triage.deduce_objective_function()` ha esattamente 5 "return"
        letterali nel suo codice sorgente (nessun pass-through di input
        utente) — il suo insieme di valori possibili è quello, per
        costruzione, non per un controllo a runtime. Stesso discorso per
        `budget_mode` in `normalize_raw_input()` (`"UNLIMITED" if
        budget==0 else "LIMITED"`, sempre uno dei due).
    (2) ANCHE se un Trip venisse costruito direttamente (bypassando la
        classificazione, es. un futuro chiamante/API diretta), sia
        `run_mock()` sia `run_live()` chiamano `trip.validate()` come
        primissimo passo e sollevano `ValueError` PRIMA di costruire il
        payload o chiamare `call_claude()` — vedi pipeline.py righe 68-70
        e 82-84.

    Questo test dimostra (2) concretamente: monkeypatcha
    `deduce_objective_function` per restituire un valore APPOSITAMENTE
    non whitelisted (simula un futuro bug/regressione nel classificatore,
    o un Trip costruito da un ipotetico chiamante diverso da
    normalize_raw_input) e verifica che `anthropic.Anthropic` non venga
    MAI costruito — non solo che il risultato sia "onesto", ma che la
    rete non venga proprio toccata.
    """

    def test_invalid_objective_function_never_reaches_anthropic_client(self):
        with patch("src.triage.deduce_objective_function", return_value="VALORE_INVENTATO"), \
             patch("anthropic.Anthropic") as MockAnthropic:
            with self.assertRaises(ValueError) as ctx:
                pipeline.run_mock("fixtures/trip_happy_path.json", "happy_path", "fake-key")
        self.assertIn("objective_function", str(ctx.exception))
        MockAnthropic.assert_not_called()

    def test_invalid_objective_function_never_reaches_anthropic_client_live_mode(self):
        with patch("src.triage.deduce_objective_function", return_value="VALORE_INVENTATO"), \
             patch("anthropic.Anthropic") as MockAnthropic:
            with self.assertRaises(ValueError) as ctx:
                pipeline.run_live("fixtures/trip_happy_path.json", _FakeSettings())
        self.assertIn("objective_function", str(ctx.exception))
        MockAnthropic.assert_not_called()

    def test_deduce_objective_function_source_has_no_pass_through_return(self):
        # Prova statica, non statistica: la funzione ha SOLO return
        # letterali (nessuna f-string/variabile derivata dall'input
        # utente) — il suo codominio è quell'insieme finito per
        # costruzione del codice sorgente, non "di solito" o "nei test
        # provati finora".
        import inspect
        from src.triage import deduce_objective_function
        from src.schemas import VALID_OBJECTIVE_FUNCTIONS
        source = inspect.getsource(deduce_objective_function)
        returned_literals = re.findall(r'return\s+"([A-Z_]+)"', source)
        self.assertTrue(returned_literals, "nessun return letterale trovato — verifica manuale necessaria")
        for literal in returned_literals:
            self.assertIn(literal, VALID_OBJECTIVE_FUNCTIONS)


class TestRunLiveGeocodingWarning(unittest.TestCase):
    """[AGGIUNTO 2026-07-11 — audit qualità pre-lancio] geocode_full()/
    is_imprecise_match() esistevano da Fase 3 (nati dal bug reale "Val
    d'Orcia, Toscana", un mis-geocode di 60-70km con status="OK") ma non
    erano mai stati collegati a run_live() — solo agli script debug_*.py.
    Verifica che un match impreciso (location_type=APPROXIMATE/
    GEOMETRIC_CENTER) produca ora un warning esplicito nel PipelineResult
    invece di passare silenzioso."""

    def test_imprecise_geocode_sets_warning(self):
        imprecise = {
            "lat": 43.567, "lng": 10.981, "location_type": "APPROXIMATE",
            "formatted_address": "Val d'Orcia, Toscana, Italia",
        }
        result, _ = self._run_live_with_mocks_helper("fixtures/trip_happy_path.json", imprecise)
        self.assertIsNotNone(result.geocoding_warning)
        self.assertIn("APPROXIMATE", result.geocoding_warning)

    def test_precise_geocode_leaves_warning_none(self):
        result, _ = self._run_live_with_mocks_helper("fixtures/trip_happy_path.json", _PRECISE_GEOCODE_FULL)
        self.assertIsNone(result.geocoding_warning)

    def _run_live_with_mocks_helper(self, fixture_path, geocode_full_return):
        # stesso helper di TestRunLiveModuleSelection, duplicato qui in
        # forma di funzione libera per non dipendere da ereditarietà tra
        # classi di test diverse.
        with patch("src.geocoding.geocode_full", return_value=geocode_full_return), \
             patch("src.liteapi_client.LiteApiClient") as MockLiteApiClient, \
             patch("src.liteapi_client.select_anchor_hotel", return_value=[_FAKE_HOTEL]), \
             patch("src.places_client.search_nearby", return_value=[]) as mock_search_nearby, \
             patch("src.distance_matrix.get_distance_matrix", return_value=[]), \
             patch("src.pipeline.call_claude", return_value="NON E' JSON VALIDO — irrilevante per questo test"):
            mock_instance = MockLiteApiClient.return_value
            mock_instance.search_hotels_by_geocode.return_value = []
            mock_instance.search_hotel_offers.return_value = []
            result = pipeline.run_live(fixture_path, _FakeSettings())
            return result, mock_search_nearby


class TestRunLiveDistanceMatrixWiring(unittest.TestCase):
    """[AGGIUNTO 2026-07-11 — audit di qualità, secondo giro] Gap reale
    trovato: TUTTI gli helper sopra (`_run_live_with_mocks` e
    `_run_live_with_mocks_helper`) mockano `src.places_client.search_nearby`
    per restituire SEMPRE `[]`, quindi `build_points()` produce sempre e
    solo 1 punto (il solo hotel-ancora). `get_distance_matrix_multi_mode()`
    ha un cortocircuito esplicito `if len(points) < 2: return []` — quindi
    in nessuno di quei test la Distance Matrix viene MAI davvero
    interrogata, e il mock su `src.distance_matrix.get_distance_matrix`
    non viene mai invocato. Risultato: se qualcuno per errore avesse
    ripristinato pipeline.py a chiamare la vecchia `get_distance_matrix()`
    single-mode invece di `get_distance_matrix_multi_mode()`, TUTTI i test
    esistenti sarebbero comunque passati — falsa sicurezza sul cablaggio
    multi-modalità. Questo test usa >=1 POI reale (oltre all'hotel-ancora)
    per garantire >=2 punti, cablando quindi `search_nearby` per restituire
    un mock ma facendo passare la Distance Matrix per il vero
    `get_distance_matrix_multi_mode()` con solo la HTTP di fondo
    (`get_distance_matrix`) mockata — così verifichiamo che compaiano
    entrambe le modalità "driving" e "walking" nel risultato finale."""

    _FAKE_POI = POI(id="P1", type="restaurant", name="Ristorante Test", lat=38.12, lng=15.67)

    def test_run_live_uses_multi_mode_distance_matrix_with_two_or_more_points(self):
        calls = []

        def fake_get_distance_matrix(pts, api_key, mode="driving"):
            calls.append(mode)
            seconds = 20 if mode == "driving" else 200
            from src.distance_matrix import map_distance_matrix_response
            return map_distance_matrix_response(
                {
                    "status": "OK",
                    "rows": [
                        {"elements": [{"status": "OK", "duration": {"value": 0}},
                                       {"status": "OK", "duration": {"value": seconds}}]},
                        {"elements": [{"status": "OK", "duration": {"value": seconds}},
                                       {"status": "OK", "duration": {"value": 0}}]},
                    ],
                },
                pts,
                mode=mode,
            )

        with patch("src.geocoding.geocode_full", return_value=_PRECISE_GEOCODE_FULL), \
             patch("src.liteapi_client.LiteApiClient") as MockLiteApiClient, \
             patch("src.liteapi_client.select_anchor_hotel", return_value=[_FAKE_HOTEL]), \
             patch("src.places_client.search_nearby", return_value=[self._FAKE_POI]), \
             patch("src.distance_matrix.get_distance_matrix", side_effect=fake_get_distance_matrix), \
             patch("src.pipeline.call_claude", return_value="NON E' JSON VALIDO — irrilevante per questo test"):
            mock_instance = MockLiteApiClient.return_value
            mock_instance.search_hotels_by_geocode.return_value = []
            mock_instance.search_hotel_offers.return_value = []
            pipeline.run_live("fixtures/trip_happy_path.json", _FakeSettings())

        # Se pipeline.py chiamasse ancora get_distance_matrix() single-mode
        # direttamente (bypassando get_distance_matrix_multi_mode), `calls`
        # conterrebbe una sola entry invece di due ("driving" e "walking").
        self.assertEqual(sorted(calls), ["driving", "walking"])


if __name__ == "__main__":
    unittest.main()
