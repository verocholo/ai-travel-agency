"""
[AGGIUNTO 2026-07-12 — microservizio HTTP per Make.com, vedi service.py]
Copre service.py usando il test client di Flask — nessun server reale in
ascolto, nessuna vera chiamata di rete. Stesso pattern di mocking già
usato in test_pipeline.py/test_refinement.py: `src.pipeline.call_claude`
o `anthropic.Anthropic` sono sempre patchati, mai una vera chiamata API
nella suite automatica (questo sandbox non ha comunque nessuna chiave reale
impostata — vedi src/config.py — quindi una vera chiamata fallirebbe).
"""
import json
import os
import unittest
from unittest.mock import patch, MagicMock

import service
from src.schemas import Trip, Hotel, POI, ApiPayload

_RAW_TRIP = {
    "email": "cliente@mail.com",
    "scopo": "Torneo di tennis amatoriale",
    "destinazione": "Val d'Orcia, Toscana",
    "arrivo": "2026-09-14",
    "partenza": "2026-09-17",
    "budget": 0,
    "note": "Preferisco cene leggere la sera prima delle partite.",
}

_VALID_ITINERARY_JSON = json.dumps({
    "destination": "Val d'Orcia, Toscana",
    "executive_summary": "Un bel viaggio.",
    "days": [
        {"day": 1, "title": "Giorno 1", "blocks": [
            {"time": "09:00", "activity": "Visita", "location": "Val d'Orcia", "poi_id": None},
        ]},
    ],
})


def _mock_anthropic_response(text: str, stop_reason: str = "end_turn"):
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    return response


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        service.app.testing = True
        self.client = service.app.test_client()
        # Env pulito a ogni test — non deve dipendere da variabili lasciate
        # da altri test o dall'ambiente della macchina che esegue la suite.
        self._env_patch = patch.dict(os.environ, {"SERVICE_API_KEY": "segreto-di-test"})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()


class TestHealth(ServiceTestCase):
    def test_health_no_auth_required(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")

    def test_test_suite_label_is_computed_not_a_stale_hardcoded_string(self):
        # [AGGIUNTO 2026-07-13 — audit di revisione completa] Regressione
        # diretta sul bug trovato: l'etichetta era una costante scritta a
        # mano ("404/404") già disallineata dalla suite reale (486 test).
        # Verifica che sia ora calcolata dinamicamente — deve contenere
        # un conteggio consistente con se stesso (N/N), non la vecchia
        # stringa fissa.
        label = service.TEST_SUITE_STATUS
        self.assertNotEqual(label, "404/404")
        self.assertRegex(label, r"^\d+/\d+")
        count_str = label.split("/")[0]
        self.assertGreater(int(count_str), 400)  # la suite reale è ben oltre 400 test


class TestGlobalErrorHandler(ServiceTestCase):
    def test_deeply_nested_json_returns_json_500_not_html(self):
        # [AGGIUNTO 2026-07-13 — audit di revisione completa] Regressione
        # diretta sul bug riprodotto: un body JSON annidato a dismisura fa
        # sollevare RecursionError da `request.get_json(silent=True)`,
        # che PRIMA del fix propagava come pagina HTML generica di
        # Werkzeug invece di un JSON — rompendo il contratto documentato
        # in DEPLOY.md verso Make.com.
        nested = "[" * 5000 + "]" * 5000
        resp = self.client.post(
            "/v1/itinerary",
            data=nested,
            content_type="application/json",
            headers={"X-Service-Key": "segreto-di-test"},
        )
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.content_type, "application/json")
        data = resp.get_json()
        self.assertIsNotNone(data)
        self.assertIn("error", data)

    def test_unknown_route_still_returns_json_not_html(self):
        # Verifica anche il caso "gratis" (404 di Flask/Werkzeug per una
        # rotta inesistente) — il global handler intercetta anche le
        # HTTPException, non solo le eccezioni non gestite.
        resp = self.client.get("/v1/rotta-inesistente")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.content_type, "application/json")
        self.assertIn("error", resp.get_json())


class TestAuth(ServiceTestCase):
    def test_missing_header_rejected(self):
        resp = self.client.post("/v1/itinerary", json={"mode": "mock", "trip": _RAW_TRIP})
        self.assertEqual(resp.status_code, 401)

    def test_wrong_key_rejected(self):
        resp = self.client.post(
            "/v1/itinerary", json={"mode": "mock", "trip": _RAW_TRIP},
            headers={"X-Service-Key": "chiave-sbagliata"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_correct_key_still_accepted_after_hmac_switch(self):
        # [AGGIUNTO 2026-07-13 — audit di revisione completa] Regressione
        # diretta sul fix `!=` -> `hmac.compare_digest()`: la chiave
        # corretta deve continuare a essere accettata esattamente come
        # prima (nessuna richiesta legittima Make.com deve rompersi).
        resp = self.client.get("/health", headers={"X-Service-Key": "segreto-di-test"})
        self.assertEqual(resp.status_code, 200)  # /health non richiede auth, solo sanity
        resp = self.client.post(
            "/v1/itinerary", json={"mode": "mock", "trip": _RAW_TRIP, "scenario_key": "happy_path"},
            headers={"X-Service-Key": "segreto-di-test"},
        )
        self.assertNotEqual(resp.status_code, 401)

    def test_empty_string_key_rejected_not_treated_as_falsy_bypass(self):
        # [AGGIUNTO 2026-07-13 — audit di revisione completa] Con
        # `hmac.compare_digest()`, una stringa vuota lato client va
        # comunque rifiutata esplicitamente (guardia `not provided`
        # prima della chiamata, che altrimenti solleverebbe un
        # `TypeError` non gestito con SERVICE_API_KEY non vuota).
        resp = self.client.post(
            "/v1/itinerary", json={"mode": "mock", "trip": _RAW_TRIP},
            headers={"X-Service-Key": ""},
        )
        self.assertEqual(resp.status_code, 401)

    def test_fail_closed_when_service_key_not_configured_on_server(self):
        # Anche con l'header giusto lato client, se il SERVER non ha
        # SERVICE_API_KEY impostata la richiesta va rifiutata — non deve
        # mai "aprirsi" per assenza di configurazione.
        self._env_patch.stop()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SERVICE_API_KEY", None)
            resp = self.client.post(
                "/v1/itinerary", json={"mode": "mock", "trip": _RAW_TRIP},
                headers={"X-Service-Key": "qualunque-cosa"},
            )
        self.assertEqual(resp.status_code, 401)
        self._env_patch.start()  # rimesso per il tearDown esistente


class TestCreateItineraryValidation(ServiceTestCase):
    def _post(self, body):
        return self.client.post(
            "/v1/itinerary", json=body, headers={"X-Service-Key": "segreto-di-test"}
        )

    def test_missing_mode_rejected(self):
        resp = self._post({"trip": _RAW_TRIP})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_mode_rejected(self):
        resp = self._post({"mode": "invented", "trip": _RAW_TRIP})
        self.assertEqual(resp.status_code, 400)

    def test_missing_trip_rejected(self):
        resp = self._post({"mode": "mock"})
        self.assertEqual(resp.status_code, 400)

    def test_mock_mode_without_scenario_key_rejected(self):
        resp = self._post({"mode": "mock", "trip": _RAW_TRIP})
        self.assertEqual(resp.status_code, 400)

    def test_trip_missing_required_field_rejected(self):
        broken_trip = dict(_RAW_TRIP)
        del broken_trip["email"]
        resp = self._post({"mode": "mock", "trip": broken_trip, "scenario_key": "happy_path"})
        self.assertEqual(resp.status_code, 400)

    def test_missing_env_keys_reported_as_server_error_not_crash(self):
        # In questo sandbox ANTHROPIC_API_KEY non è mai impostata (vedi
        # config.py) — verifica che il servizio lo segnali con un 500
        # leggibile invece di un traceback grezzo o un 200 silenziosamente
        # sbagliato.
        resp = self._post({"mode": "mock", "trip": _RAW_TRIP, "scenario_key": "happy_path"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("ANTHROPIC_API_KEY", resp.get_json()["error"])


class TestCreateItinerarySuccess(ServiceTestCase):
    def test_mock_mode_end_to_end_with_mocked_claude_call(self):
        with patch("src.config.SETTINGS.anthropic_api_key", "fake-key"), \
             patch("src.pipeline.call_claude", return_value=_VALID_ITINERARY_JSON):
            resp = self.client.post(
                "/v1/itinerary",
                json={"mode": "mock", "trip": _RAW_TRIP, "scenario_key": "happy_path"},
                headers={"X-Service-Key": "segreto-di-test"},
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["trip"]["destination"], "Val d'Orcia, Toscana")
        self.assertIsNotNone(data["itinerary"])
        self.assertIsNotNone(data["api_payload"])
        self.assertIn("hotels", data["api_payload"])
        self.assertIsNotNone(data["validation"])
        self.assertIn("passed", data["validation"])
        self.assertIsNotNone(data["rendered_markdown"])

    def test_live_mode_data_layer_error_returns_502_not_crash(self):
        from src.geocoding import GeocodingError
        with patch("src.config.SETTINGS.anthropic_api_key", "fake-key"), \
             patch("src.config.SETTINGS.google_maps_key", "fake-key"), \
             patch("src.config.SETTINGS.liteapi_key", "fake-key"), \
             patch("src.geocoding.geocode_full", side_effect=GeocodingError("ZERO_RESULTS")):
            resp = self.client.post(
                "/v1/itinerary",
                json={"mode": "live", "trip": _RAW_TRIP},
                headers={"X-Service-Key": "segreto-di-test"},
            )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("error", resp.get_json())


class TestRefine(ServiceTestCase):
    TRIP_DICT = Trip(
        email="cliente@mail.com", destination="Roma", date_start="2026-09-01",
        date_end="2026-09-04", duration_days=3, budget_eur=0, budget_mode="UNLIMITED",
        objective_function="ENERGY_PACING",
    ).to_dict()
    API_PAYLOAD_DICT = ApiPayload(
        hotels=[Hotel(id="H1", name="Hotel Test", lat=41.9, lng=12.5, price_night_eur=100.0)],
        travel_times=[],
        poi=[POI(id="P1", type="museum", name="Colosseo", lat=41.89, lng=12.49)],
    ).to_dict()
    CURRENT_ITINERARY = {
        "destination": "Roma",
        "executive_summary": "Un bel viaggio.",
        "days": [{"day": 1, "title": "Arrivo", "blocks": [
            {"time": "09:00", "activity": "Colosseo", "location": "Roma", "poi_id": "P1"},
        ]}],
    }

    def _post(self, body):
        return self.client.post(
            "/v1/refine", json=body, headers={"X-Service-Key": "segreto-di-test"}
        )

    def test_missing_fields_rejected(self):
        resp = self._post({"trip": self.TRIP_DICT})
        self.assertEqual(resp.status_code, 400)

    def test_malformed_trip_or_payload_rejected(self):
        resp = self._post({
            "trip": {"campo_invalido": True},
            "api_payload": self.API_PAYLOAD_DICT,
            "current_itinerary": self.CURRENT_ITINERARY,
            "customer_request": "cambia il giorno 1",
        })
        self.assertEqual(resp.status_code, 400)

    def test_trip_with_invalid_field_values_rejected_not_just_missing_fields(self):
        # [AGGIUNTO 2026-07-13 — audit di revisione completa] Regressione
        # diretta sul bug reale trovato: `Trip(**body["trip"])` costruisce
        # l'oggetto con successo anche con VALORI non validi (qui:
        # date_start >= date_end) — solo `TypeError` per campi
        # mancanti/extra era intercettato, `Trip.validate()` non veniva
        # mai chiamato. Prima del fix questo request avrebbe superato la
        # validazione e tentato l'affinamento con un trip semanticamente
        # rotto.
        broken_trip = dict(self.TRIP_DICT)
        broken_trip["date_start"] = "2026-09-10"
        broken_trip["date_end"] = "2026-09-01"  # precedente a date_start
        resp = self._post({
            "trip": broken_trip,
            "api_payload": self.API_PAYLOAD_DICT,
            "current_itinerary": self.CURRENT_ITINERARY,
            "customer_request": "cambia il giorno 1",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("non è precedente", str(resp.get_json()["error"]))

    def test_successful_refine_with_mocked_claude_call(self):
        with patch("src.config.SETTINGS.anthropic_api_key", "fake-key"), \
             patch("anthropic.Anthropic") as MockClient:
            instance = MockClient.return_value
            instance.messages.create.return_value = _mock_anthropic_response(_VALID_ITINERARY_JSON)
            resp = self._post({
                "trip": self.TRIP_DICT,
                "api_payload": self.API_PAYLOAD_DICT,
                "current_itinerary": self.CURRENT_ITINERARY,
                "customer_request": "cambia il giorno 1",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsNotNone(data["itinerary"])
        self.assertIsNotNone(data["validation"])
        self.assertIsNotNone(data["rendered_markdown"])


class TestGeneratePdf(ServiceTestCase):
    """
    [AGGIUNTO 2026-07-14 — preparativi Make.com, Nodo 10A] Copre il nuovo
    endpoint `POST /v1/pdf`. Stesso principio di mocking del resto della
    suite: `src.pdf_extras.guide_generator`/`feedback_generator` (mai una
    vera chiamata Claude) e `service.pdf_renderer.render_pdf` (mai un vero
    `wkhtmltopdf` in esecuzione nella suite automatica — anche se in
    questo sandbox è installato, la suite non deve dipendere da un
    binario esterno per restare verde ovunque venga eseguita, stesso
    principio già seguito per le chiamate di rete reali).
    """
    TRIP_DICT = Trip(
        email="cliente@mail.com", destination="Roma", date_start="2026-09-01",
        date_end="2026-09-04", duration_days=3, budget_eur=0, budget_mode="UNLIMITED",
        objective_function="ENERGY_PACING",
    ).to_dict()
    API_PAYLOAD_DICT = ApiPayload(
        hotels=[Hotel(id="H1", name="Hotel Test", lat=41.9, lng=12.5, price_night_eur=100.0)],
        travel_times=[],
        poi=[POI(id="P1", type="museum", name="Colosseo", lat=41.89, lng=12.49)],
    ).to_dict()
    ITINERARY_WITH_POI = {
        "destination": "Roma",
        "executive_summary": "Un bel viaggio.",
        "days": [{"day": 1, "title": "Arrivo", "blocks": [
            {"time": "09:00", "activity": "Colosseo", "location": "Roma", "poi_id": "P1"},
        ]}],
    }

    def _post(self, body):
        return self.client.post(
            "/v1/pdf", json=body, headers={"X-Service-Key": "segreto-di-test"}
        )

    @staticmethod
    def _fake_render_pdf(itinerary, trip, hotels=None, guides=None, feedback=None,
                          poi=None, map_png_bytes=None, output_path=None):
        # Scrive un PDF finto ma non vuoto nel path richiesto — stesso
        # contratto reale di pdf_renderer.render_pdf() (scrive su
        # `output_path`, ritorna quel path), senza invocare wkhtmltopdf.
        from pathlib import Path
        Path(output_path).write_bytes(b"%PDF-1.4 contenuto finto\n")
        return output_path

    def test_missing_auth_rejected(self):
        resp = self.client.post("/v1/pdf", json={
            "trip": self.TRIP_DICT, "api_payload": self.API_PAYLOAD_DICT,
            "itinerary": self.ITINERARY_WITH_POI,
        })
        self.assertEqual(resp.status_code, 401)

    def test_missing_fields_rejected(self):
        resp = self._post({"trip": self.TRIP_DICT, "api_payload": self.API_PAYLOAD_DICT})
        self.assertEqual(resp.status_code, 400)

    def test_malformed_trip_or_payload_rejected(self):
        resp = self._post({
            "trip": {"campo_invalido": True},
            "api_payload": self.API_PAYLOAD_DICT,
            "itinerary": self.ITINERARY_WITH_POI,
        })
        self.assertEqual(resp.status_code, 400)

    def test_itinerary_missing_days_key_rejected(self):
        resp = self._post({
            "trip": self.TRIP_DICT,
            "api_payload": self.API_PAYLOAD_DICT,
            "itinerary": {"destination": "Roma"},  # niente 'days'
        })
        self.assertEqual(resp.status_code, 400)

    def test_itinerary_not_a_dict_rejected(self):
        resp = self._post({
            "trip": self.TRIP_DICT,
            "api_payload": self.API_PAYLOAD_DICT,
            "itinerary": "non un dict",
        })
        self.assertEqual(resp.status_code, 400)

    def test_non_boolean_include_flag_rejected(self):
        resp = self._post({
            "trip": self.TRIP_DICT,
            "api_payload": self.API_PAYLOAD_DICT,
            "itinerary": self.ITINERARY_WITH_POI,
            "include_guides": "yes",  # deve essere un booleano vero, non una stringa
        })
        self.assertEqual(resp.status_code, 400)

    def test_missing_anthropic_key_rejected_when_guides_requested(self):
        # Default: include_guides/include_feedback sono entrambi True — in
        # questo sandbox ANTHROPIC_API_KEY non è mai impostata (vedi
        # config.py), quindi deve dare un 500 leggibile, non un crash.
        resp = self._post({
            "trip": self.TRIP_DICT,
            "api_payload": self.API_PAYLOAD_DICT,
            "itinerary": self.ITINERARY_WITH_POI,
        })
        self.assertEqual(resp.status_code, 500)
        self.assertIn("ANTHROPIC_API_KEY", resp.get_json()["error"])

    def test_pure_pdf_without_guides_feedback_or_map_needs_no_anthropic_key(self):
        # [Punto centrale del nuovo endpoint] Con tutte e tre le sezioni
        # extra disattivate, il PDF si genera comunque, SENZA bisogno di
        # ANTHROPIC_API_KEY — nessuna chiamata Claude viene tentata.
        with patch("service.pdf_renderer.render_pdf", side_effect=self._fake_render_pdf):
            resp = self._post({
                "trip": self.TRIP_DICT,
                "api_payload": self.API_PAYLOAD_DICT,
                "itinerary": self.ITINERARY_WITH_POI,
                "include_guides": False,
                "include_feedback": False,
                "include_map": False,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["guides_requested"], 0)
        self.assertEqual(data["guides_generated"], 0)
        self.assertFalse(data["feedback_included"])
        self.assertFalse(data["map_included"])
        import base64
        self.assertEqual(base64.b64decode(data["pdf_base64"]), b"%PDF-1.4 contenuto finto\n")

    def test_successful_pdf_with_guides_and_feedback_mocked(self):
        with patch("src.config.SETTINGS.anthropic_api_key", "fake-key"), \
             patch("src.pdf_extras.guide_generator") as mock_guide_gen, \
             patch("src.pdf_extras.feedback_generator") as mock_feedback_gen, \
             patch("src.pdf_extras.maps_static") as mock_maps_static, \
             patch("service.pdf_renderer.render_pdf", side_effect=self._fake_render_pdf):
            mock_guide_gen.generate_poi_guide.return_value = {"title": "Guida", "poi_name": "Colosseo"}
            mock_feedback_gen.generate_post_trip_feedback.return_value = {"intro_message": "ciao"}
            mock_maps_static.build_map_for_itinerary.return_value = b"fake-png-bytes"

            resp = self._post({
                "trip": self.TRIP_DICT,
                "api_payload": self.API_PAYLOAD_DICT,
                "itinerary": self.ITINERARY_WITH_POI,
            })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["guides_requested"], 1)
        self.assertEqual(data["guides_generated"], 1)
        self.assertTrue(data["feedback_included"])
        self.assertTrue(data["map_included"])
        import base64
        self.assertEqual(base64.b64decode(data["pdf_base64"]), b"%PDF-1.4 contenuto finto\n")

    def test_pdf_renderer_failure_returns_500_not_crash(self):
        from src.pdf_renderer import PdfRendererError
        with patch("service.pdf_renderer.render_pdf", side_effect=PdfRendererError("wkhtmltopdf assente")):
            resp = self._post({
                "trip": self.TRIP_DICT,
                "api_payload": self.API_PAYLOAD_DICT,
                "itinerary": self.ITINERARY_WITH_POI,
                "include_guides": False,
                "include_feedback": False,
                "include_map": False,
            })
        self.assertEqual(resp.status_code, 500)
        self.assertIn("wkhtmltopdf assente", resp.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
