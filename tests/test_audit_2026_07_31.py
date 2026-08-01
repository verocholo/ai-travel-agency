"""
[NUOVO 2026-07-31 — audit di perfezionamento] Test di regressione per i bug
reali trovati (ed ESEGUITI) nell'audit adversariale multi-prospettiva del
2026-07-31. Tema dominante: molte funzioni che processano output LLM o dati
API esterni CRASHAVANO (→ HTTP 500) su input malformati-ma-parsabili, invece
di degradare in un errore pulito (FAIL del Nodo 9 / 400 del servizio) — perché
solo check_format_compliance e check_rag_fidelity erano state irrobustite, non
le altre funzioni parallele. Ogni test qui sotto FALLIREBBE (crash o falso
PASS) senza il fix corrispondente; i nomi dei test descrivono l'invariante.

Vedi CHANGELOG-2026-07-31-* per il razionale completo di ciascun fix.
"""
import unittest
import unittest.mock
from unittest.mock import MagicMock

from src import validator, scenario_checks, itinerary_utils, triage, price_display
from src import geocoding, distance_matrix, places_client, liteapi_client, claude_engine
from src import renderer, pdf_renderer, pipeline
from src.schemas import Trip


class _FakeAnthropicAPIError(Exception):
    """Sta in per anthropic.APIError (classe base degli errori dell'SDK)."""
    pass


# ---------------------------------------------------------------- validator.py

class TestValidatorRobustness(unittest.TestCase):
    IDS = {"H1", "P1"}

    def _validate(self, it):
        return validator.validate_itinerary(
            it, self.IDS, expected_duration_days=1,
            objective_function="ENERGY_PACING", poi_energy_by_id={"H1": "HIGH"},
        )

    def test_non_dict_itinerary_fails_clean_never_crashes(self):
        for bad in (None, [1, 2], "ciao", 42):
            with self.subTest(bad=bad):
                r = self._validate(bad)
                self.assertFalse(r.passed)

    def test_days_null_or_non_list_fails_clean(self):
        for bad in ({"days": None, "destination": "R"}, {"days": "x", "destination": "R"}):
            with self.subTest(bad=bad):
                r = self._validate(bad)
                self.assertFalse(r.passed)

    def test_non_dict_day_or_block_fails_clean(self):
        r = self._validate({"destination": "R", "days": ["strday"]})
        self.assertFalse(r.passed)
        r = self._validate({"destination": "R", "days": [{"day": 1, "blocks": ["strblock"]}]})
        self.assertFalse(r.passed)

    def test_unhashable_poi_id_does_not_crash_energy_pacing(self):
        r = self._validate({"destination": "R", "days": [
            {"day": 1, "blocks": [{"time": "09:00", "activity": "a", "poi_id": ["H1"]}]}]})
        self.assertFalse(r.passed)  # non deve sollevare TypeError

    def test_mixed_type_day_numbers_do_not_crash_sorted(self):
        r = validator.validate_itinerary(
            {"destination": "R", "days": [
                {"day": 1, "blocks": [{"time": "09:00", "activity": "a"}]},
                {"day": "2", "blocks": [{"time": "10:00", "activity": "b"}]}]},
            set(), expected_duration_days=2)
        self.assertFalse(r.passed)  # non deve sollevare '<' str vs int

    def test_parse_output_rejects_non_dict_toplevel(self):
        for s in ("[]", "42", '"x"', "null"):
            with self.subTest(s=s):
                with self.assertRaises(validator.ParseError):
                    validator.parse_claude_output(s)

    def test_parse_output_accepts_uppercase_json_fence(self):
        d = validator.parse_claude_output('```JSON\n{"destination":"R","days":[]}\n```')
        self.assertEqual(d["destination"], "R")

    def test_geospatial_coherence_tolerates_malformed_shapes(self):
        ok, _ = validator.check_geospatial_coherence({"days": None})
        # non deve crashare; None-days = nessun blocco = nessun errore
        self.assertTrue(ok)
        ok, _ = validator.check_geospatial_coherence({"days": [None, {"day": 1, "blocks": ["x"]}]})
        self.assertTrue(ok)

    def test_no_id_leakage_tolerates_malformed_shapes(self):
        ok, _ = validator.check_no_raw_id_leakage({"days": [None, {"day": 1, "blocks": [None]}]}, {"H1"})
        self.assertTrue(ok)


# ----------------------------------------------------------- scenario_checks.py

class TestScenarioChecksRobustness(unittest.TestCase):
    def test_budget_alert_non_string_does_not_crash_len(self):
        for alert in (True, 123, 4.5):
            with self.subTest(alert=alert):
                ok, msg = scenario_checks.check_budget_alert_when_needed(
                    {"budget_alert": alert}, "LIMITED", 100.0, min_cost_estimate=500.0)
                self.assertTrue(ok)  # non deve sollevare "has no len()"


# ------------------------------------------------------------ itinerary_utils.py

class TestItineraryUtilsRobustness(unittest.TestCase):
    def test_unhashable_poi_id_is_ignored_not_crash(self):
        s = itinerary_utils.extract_used_poi_ids(
            {"days": [{"day": 1, "blocks": [{"poi_id": ["X"]}, {"poi_id": "P1"}]}]})
        self.assertEqual(s, {"P1"})

    def test_duplicate_day_numbers_accumulate_not_overwrite(self):
        d = itinerary_utils.extract_used_poi_ids_by_day(
            {"days": [{"day": 1, "blocks": [{"poi_id": "P1"}]},
                      {"day": 1, "blocks": [{"poi_id": "P2"}]}]})
        self.assertEqual(d, {1: ["P1", "P2"]})

    def test_null_days_or_blocks_do_not_crash(self):
        self.assertEqual(itinerary_utils.extract_used_poi_ids({"days": None}), set())
        self.assertEqual(itinerary_utils.extract_used_poi_ids({"days": [None, {"blocks": None}]}), set())


# --------------------------------------------------------------------- triage.py

class TestTriageRobustness(unittest.TestCase):
    def test_sportello_does_not_falsely_match_sport(self):
        self.assertEqual(
            triage.deduce_objective_function("Relax totale, info allo sportello del comune"),
            "BALANCED")

    def test_real_sport_terms_still_match(self):
        for scopo in ("Vacanza sportiva", "voglio fare sport", "weekend sportivo", "torneo di tennis"):
            with self.subTest(scopo=scopo):
                self.assertEqual(triage.deduce_objective_function(scopo), "ENERGY_PACING")

    def test_null_date_raises_valueerror_not_typeerror(self):
        with self.assertRaises(ValueError):
            triage.normalize_raw_input(
                {"arrivo": None, "partenza": None, "email": "a@b.c", "destinazione": "R"})

    def test_non_numeric_budget_raises_valueerror(self):
        with self.assertRaises(ValueError):
            triage.normalize_raw_input(
                {"arrivo": "2026-09-10", "partenza": "2026-09-12", "email": "a@b.c",
                 "destinazione": "R", "budget": [1, 2]})

    def test_non_string_scopo_raises_valueerror(self):
        with self.assertRaises(ValueError):
            triage.normalize_raw_input(
                {"arrivo": "2026-09-10", "partenza": "2026-09-12", "email": "a@b.c",
                 "destinazione": "R", "scopo": 123})


# --------------------------------------------------------------------- schemas.py

class TestTripValidateTypeSafety(unittest.TestCase):
    def _trip(self, **over):
        base = dict(email="a@b.c", destination="R", date_start="2026-09-10",
                    date_end="2026-09-12", duration_days=2, budget_mode="UNLIMITED",
                    budget_eur=0.0, objective_function="BALANCED")
        base.update(over)
        return Trip(**base)

    def test_non_string_dates_reported_not_crash(self):
        errs = self._trip(date_start=5, date_end=6).validate()
        self.assertTrue(any("date" in e.lower() for e in errs))

    def test_non_string_destination_reported_not_crash(self):
        errs = self._trip(destination=42).validate()
        self.assertTrue(any("destination" in e.lower() for e in errs))

    def test_non_string_email_reported_not_crash(self):
        errs = self._trip(email=123).validate()
        self.assertTrue(any("email" in e.lower() for e in errs))

    def test_bool_budget_rejected_as_non_numeric(self):
        errs = self._trip(budget_eur=True).validate()
        self.assertTrue(any("numerico" in e for e in errs))


# ------------------------------------------------------------------ price_display

class TestPriceDisplayRobustness(unittest.TestCase):
    def test_unhashable_price_level_returns_empty_not_crash(self):
        self.assertEqual(price_display.price_level_symbol(["MODERATE"]), "")
        self.assertEqual(price_display.price_level_symbol({"a": 1}), "")

    def test_valid_price_level_still_works(self):
        self.assertEqual(price_display.price_level_symbol("MODERATE"), "€€")


# ------------------------------------------------------------ data layer clients

class TestPlacesClientRobustness(unittest.TestCase):
    def test_null_display_name_does_not_lose_whole_batch(self):
        pois = places_client.map_places_response({"places": [
            {"id": "a", "location": {"latitude": 1, "longitude": 2}, "displayName": {"text": "Valido"}},
            {"id": "b", "location": {"latitude": 3, "longitude": 4}, "displayName": None},
        ]})
        # entrambi mappati: displayName null → nome di default, non perdita del batch
        self.assertEqual(len(pois), 2)

    def test_null_opening_hours_periods_do_not_crash(self):
        self.assertEqual(places_client._open_days({"periods": None}), [])
        self.assertEqual(places_client._open_days({"periods": [{"open": None}]}), [])

    def test_empty_included_types_omits_filter(self):
        # [] esplicito = nessun filtro (freshness check); None = default 4 tipi
        import unittest.mock as m
        captured = {}
        def fake_post(url, json=None, **kw):
            captured["body"] = json
            resp = MagicMock(); resp.raise_for_status = lambda: None; resp.json = lambda: {"places": []}
            return resp
        with m.patch("src.places_client.requests.post", side_effect=fake_post):
            places_client.fetch_nearby_raw(1.0, 2.0, "k", included_types=[])
        self.assertNotIn("includedTypes", captured["body"])
        with m.patch("src.places_client.requests.post", side_effect=fake_post):
            places_client.fetch_nearby_raw(1.0, 2.0, "k", included_types=None)
        self.assertEqual(captured["body"]["includedTypes"], places_client._DEFAULT_INCLUDED_TYPES)


class TestLiteApiRobustness(unittest.TestCase):
    def test_non_numeric_price_raises_liteapierror_not_typeerror(self):
        for total in ([{"amount": None, "currency": "EUR"}], [{"amount": "N/A"}], None):
            with self.subTest(total=total):
                with self.assertRaises(liteapi_client.LiteApiError):
                    liteapi_client._extract_total_price(
                        {"hotelId": "h", "roomTypes": [{"rates": [{"retailRate": {"total": total}}]}]})

    def test_null_room_type_entry_raises_liteapierror(self):
        with self.assertRaises(liteapi_client.LiteApiError):
            liteapi_client._extract_total_price({"hotelId": "h", "roomTypes": [None]})


class TestDistanceMatrixRobustness(unittest.TestCase):
    def test_null_duration_field_does_not_crash(self):
        points = [{"id": "a", "coord": "0,0"}, {"id": "b", "coord": "1,1"}]
        out = distance_matrix.map_distance_matrix_response(
            {"rows": [{"elements": [{"status": "OK"}, {"status": "OK", "duration": None}]}]}, points)
        self.assertEqual(out, [])  # nessuna entry valida, ma nessun crash


class TestGeocodingRobustness(unittest.TestCase):
    def test_null_latlng_raises_geocodingerror(self):
        with self.assertRaises(geocoding.GeocodingError):
            geocoding.parse_geocoding_response(
                {"status": "OK", "results": [{"geometry": {"location": {"lat": None, "lng": None}}}]})

    def test_non_json_200_body_raises_geocodingerror(self):
        import unittest.mock as m
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = MagicMock(side_effect=ValueError("Expecting value"))
        with m.patch("src.geocoding.requests.get", return_value=resp):
            with self.assertRaises(geocoding.GeocodingError):
                geocoding.geocode("Roma", "k")


# --------------------------------------------------------------- claude_engine.py

class TestAnthropicApiErrorHandling(unittest.TestCase):
    """[AGGIUNTO 2026-07-31 — trovato da un test end-to-end dal vivo su Make]
    Un errore dell'API Anthropic (credito esaurito, rate limit, sovraccarico)
    deve diventare un errore TIPIZZATO (ClaudeEngineError/RefinementError), non
    propagarsi come eccezione grezza → HTTP 500 verso Make."""

    def _fake_anthropic_raising(self, exc):
        fake_client = MagicMock()
        fake_client.messages.stream.side_effect = exc
        fake_module = MagicMock()
        fake_module.Anthropic.return_value = fake_client
        # APIError deve essere una VERA classe eccezione perché `except
        # anthropic.APIError` funzioni col modulo mockato.
        fake_module.APIError = _FakeAnthropicAPIError
        return fake_module

    def test_call_claude_translates_api_error_to_claude_engine_error(self):
        import sys
        fake = self._fake_anthropic_raising(_FakeAnthropicAPIError("credit balance too low"))
        with unittest.mock.patch.dict(sys.modules, {"anthropic": fake}):
            with self.assertRaises(claude_engine.ClaudeEngineError) as ctx:
                claude_engine.call_claude({"a": 1}, "BALANCED", 3, api_key="k")
        self.assertIn("Anthropic", str(ctx.exception))

    def test_refine_translates_api_error_to_refinement_error(self):
        from src import refinement
        from src.schemas import Trip, ApiPayload
        trip = Trip(email="a@b.c", destination="R", date_start="2026-09-10",
                    date_end="2026-09-12", duration_days=2, budget_mode="UNLIMITED",
                    budget_eur=0.0, objective_function="BALANCED")
        fake = self._fake_anthropic_raising(_FakeAnthropicAPIError("rate limit"))
        with unittest.mock.patch("anthropic.Anthropic", fake.Anthropic), \
             unittest.mock.patch("anthropic.APIError", _FakeAnthropicAPIError, create=True):
            with self.assertRaises(refinement.RefinementError):
                refinement.refine_itinerary(
                    {"destination": "R", "days": []}, {}, ApiPayload(hotels=[], travel_times=[], poi=[]),
                    trip, "cambia x", api_key="k")


class TestSelectModelRobustness(unittest.TestCase):
    def test_none_objective_function_does_not_crash(self):
        self.assertEqual(claude_engine.select_model(None, 3), "claude-sonnet-5")

    def test_substring_exclusivity_does_not_trigger_opus(self):
        # solo l'enum ESATTO usa Opus, non una sottostringa
        self.assertEqual(claude_engine.select_model("MY_EXCLUSIVITY_THING", 3), "claude-sonnet-5")
        self.assertEqual(claude_engine.select_model("EXCLUSIVITY_ZERO_FRICTION", 3), "claude-opus-4-8")


# --------------------------------------------------------------- renderers/PDF

class TestRendererRobustness(unittest.TestCase):
    TRIP = {"destination": "R", "date_start": "2026-09-10", "date_end": "2026-09-12",
            "duration_days": 2, "objective_function": "BALANCED", "budget_mode": "UNLIMITED",
            "budget_eur": 0, "email": "a@b.c", "raw_notes": ""}
    MAL = {"destination": "R", "days": [
        {"day": 1, "blocks": None}, None,
        {"day": 2, "blocks": [None, {"time": "09:00", "activity": "x", "poi_id": ["Z"]}]}]}

    def test_markdown_renderer_tolerates_null_blocks_and_days(self):
        self.assertTrue(renderer.render_markdown(self.MAL, self.TRIP))

    def test_html_renderer_tolerates_null_blocks_and_days(self):
        self.assertTrue(pdf_renderer.render_html(self.MAL, self.TRIP))

    def test_html_renderer_escapes_injection(self):
        inj = {"destination": "<script>alert(1)</script>",
               "executive_summary": "<img src=x onerror=alert(1)>",
               "days": [{"day": 1, "title": "t", "blocks": [
                   {"time": "09:00", "activity": "<script>bad</script>", "location": "L", "poi_id": None}]}]}
        html = pdf_renderer.render_html(inj, self.TRIP)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;", html)


# ------------------------------------------------------------------- pipeline.py

class TestPipelineRobustness(unittest.TestCase):
    def test_redacts_google_key_from_data_layer_error(self):
        msg = "ConnectionError: https://maps.googleapis.com/maps/api/geocode/json?address=Roma&key=AIzaSyREALSECRET123&language=it"
        red = pipeline._redact_secrets(msg)
        self.assertNotIn("AIzaSyREALSECRET123", red)
        self.assertIn("key=REDACTED", red)

    def test_redacts_api_key_headers(self):
        red = pipeline._redact_secrets("error x-api-key: SECRETVALUE123 boom")
        self.assertNotIn("SECRETVALUE123", red)


# ------------------------------------------------------------------ pdf_extras

class TestPdfExtrasDegradation(unittest.TestCase):
    """[AGGIUNTO 2026-07-31 — audit di perfezionamento, bug reale eseguito]
    build_pdf_extras deve DEGRADARE (saltare la sezione) su un errore di
    RETE/API della guida/feedback, non far fallire l'intero PDF — prima
    catturava solo GuideGeneratorError/FeedbackGeneratorError, non le
    eccezioni di rete che generate_poi_guide NON avvolge."""

    def _trip(self):
        return Trip(email="a@b.c", destination="Roma", date_start="2026-09-10",
                    date_end="2026-09-12", duration_days=2, budget_mode="UNLIMITED",
                    budget_eur=0.0, objective_function="BALANCED")

    def test_network_error_in_guide_does_not_break_whole_pdf(self):
        from src import pdf_extras
        from src.schemas import POI, ApiPayload
        poi = POI(id="P1", type="museum", name="Museo", lat=1.0, lng=2.0, energy_tag="LOW")
        api_payload = ApiPayload(hotels=[], travel_times=[], poi=[poi])
        itinerary = {"destination": "Roma", "days": [
            {"day": 1, "blocks": [{"time": "09:00", "activity": "Museo", "poi_id": "P1"}]}]}
        with unittest.mock.patch(
            "src.pdf_extras.guide_generator.generate_poi_guide",
            side_effect=ConnectionError("network down"),
        ):
            guides, feedback, used, mp = pdf_extras.build_pdf_extras(
                itinerary, self._trip(), api_payload, api_key="k",
                include_guides=True, include_feedback=False, include_map=False,
            )
        self.assertEqual(guides, [])  # saltata, non crash


if __name__ == "__main__":
    unittest.main()
