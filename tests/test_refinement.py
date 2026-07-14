"""
[NUOVO 2026-07-12 — richiesta di Lorenzo, idea proposta da Claude:
"agente di affinamento conversazionale"] Copre src/refinement.py: stesso
pattern di mocking di test_pipeline.py/test_guide_generator.py — nessuna
vera chiamata API nella suite automatica.
"""
import dataclasses
import json
import unittest
from unittest.mock import patch, MagicMock

from src import refinement
from src.claude_engine import BASE_MAX_TOKENS
from src.schemas import Trip, ApiPayload, Hotel, POI

TRIP = Trip(
    email="cliente@mail.com",
    destination="Roma",
    date_start="2026-09-01",
    date_end="2026-09-04",
    duration_days=3,
    budget_eur=0,
    budget_mode="UNLIMITED",
    objective_function="ENERGY_PACING",
)

HOTEL = Hotel(id="H1", name="Hotel Test", lat=41.9, lng=12.5, price_night_eur=100.0)
POI_1 = POI(id="P1", type="museum", name="Colosseo", lat=41.89, lng=12.49)
API_PAYLOAD = ApiPayload(hotels=[HOTEL], travel_times=[], poi=[POI_1])
PAYLOAD = {"trip": TRIP.to_dict(), "DATI_API_FORNITI": API_PAYLOAD.to_dict()}

CURRENT_ITINERARY = {
    "destination": "Roma",
    "executive_summary": "Un bel viaggio.",
    "days": [
        {"day": 1, "title": "Arrivo", "blocks": [
            {"time": "09:00", "activity": "Colosseo", "location": "Roma", "poi_id": "P1"},
        ]},
        {"day": 2, "title": "Giorno 2", "blocks": [
            {"time": "09:00", "activity": "Tempo libero", "location": "", "poi_id": None},
        ]},
        {"day": 3, "title": "Giorno 3", "blocks": [
            {"time": "09:00", "activity": "Tempo libero", "location": "", "poi_id": None},
        ]},
    ],
}


def _mock_response(text: str, stop_reason: str = "end_turn"):
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    return response


class TestBuildRefinementUserMessage(unittest.TestCase):
    def test_includes_customer_request_and_current_itinerary(self):
        msg = refinement.build_refinement_user_message(
            CURRENT_ITINERARY, API_PAYLOAD.to_dict(), "cambia il giorno 1"
        )
        self.assertIn("cambia il giorno 1", msg)
        self.assertIn("Colosseo", msg)
        self.assertIn("P1", msg)


class TestRefineItinerary(unittest.TestCase):
    def test_successful_refinement_revalidates_and_renders(self):
        # [AGGIORNATO 2026-07-12 — audit di revisione completa] `days`
        # ora ha esattamente 3 elementi (1..3), pari a TRIP.duration_days
        # — da quando `expected_duration_days` è stato wired in
        # refine_itinerary(), un itinerario abbreviato a 1 solo giorno per
        # un trip di 3 notti farebbe fallire format_compliance (per
        # design: è esattamente il gap che quel fix chiude).
        updated_itinerary = {
            "destination": "Roma",
            "executive_summary": "Versione aggiornata.",
            "days": [
                {"day": 1, "title": "Arrivo (aggiornato)", "blocks": [
                    {"time": "10:00", "activity": "Foro Romano", "location": "Roma", "poi_id": None},
                ]},
                {"day": 2, "title": "Giorno 2", "blocks": [
                    {"time": "09:00", "activity": "Tempo libero", "location": "", "poi_id": None},
                ]},
                {"day": 3, "title": "Giorno 3", "blocks": [
                    {"time": "09:00", "activity": "Tempo libero", "location": "", "poi_id": None},
                ]},
            ],
        }
        fake_response = _mock_response(json.dumps(updated_itinerary))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            result = refinement.refine_itinerary(
                CURRENT_ITINERARY, PAYLOAD, API_PAYLOAD, TRIP, "cambia il giorno 1", api_key="fake-key"
            )
        self.assertIsNone(result.parse_error)
        self.assertEqual(result.itinerary["executive_summary"], "Versione aggiornata.")
        self.assertTrue(result.validation_report.passed, result.validation_report.summary())
        self.assertIn("Foro Romano", result.rendered_markdown)

    def test_wrong_day_count_fails_revalidation(self):
        # [AGGIUNTO 2026-07-12 — audit di revisione completa] Regressione
        # diretta sul gap appena chiuso: un affinamento che restituisse
        # meno giorni di quelli dichiarati da trip.duration_days deve ora
        # fallire la revalidazione, non più un PASS silenzioso.
        short_itinerary = {
            "destination": "Roma",
            "executive_summary": "Versione abbreviata per errore.",
            "days": [
                {"day": 1, "title": "Arrivo", "blocks": [
                    {"time": "10:00", "activity": "Foro Romano", "location": "Roma", "poi_id": None},
                ]},
            ],
        }
        fake_response = _mock_response(json.dumps(short_itinerary))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            result = refinement.refine_itinerary(
                CURRENT_ITINERARY, PAYLOAD, API_PAYLOAD, TRIP, "cambia il giorno 1", api_key="fake-key"
            )
        self.assertFalse(result.validation_report.passed)
        self.assertTrue(any("attesi esattamente 3" in e for e in result.validation_report.format_errors))

    def test_hallucinated_poi_id_caught_by_revalidation(self):
        # [Nodo 9 rieseguito] Un affinamento che inventasse un poi_id mai
        # fornito deve essere rilevato esattamente come nella generazione
        # originale — nessuna scorciatoia di qualità sul secondo turno.
        bad_itinerary = {
            "destination": "Roma",
            "executive_summary": "x",
            "days": [
                {"day": 1, "title": "Arrivo", "blocks": [
                    {"time": "10:00", "activity": "Posto inventato", "location": "Roma", "poi_id": "P999"},
                ]},
            ],
        }
        fake_response = _mock_response(json.dumps(bad_itinerary))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            result = refinement.refine_itinerary(
                CURRENT_ITINERARY, PAYLOAD, API_PAYLOAD, TRIP, "aggiungi un'attività", api_key="fake-key"
            )
        self.assertFalse(result.validation_report.passed)
        self.assertIn("P999", result.validation_report.hallucinated_poi_ids)

    def test_markdown_fence_wrapped_json_still_parses(self):
        wrapped = "```json\n" + json.dumps(CURRENT_ITINERARY) + "\n```"
        fake_response = _mock_response(wrapped)
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            result = refinement.refine_itinerary(
                CURRENT_ITINERARY, PAYLOAD, API_PAYLOAD, TRIP, "nessuna modifica", api_key="fake-key"
            )
        self.assertIsNone(result.parse_error)
        self.assertIsNotNone(result.itinerary)

    def test_invalid_json_sets_parse_error_not_exception(self):
        fake_response = _mock_response("non e' JSON valido")
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            result = refinement.refine_itinerary(
                CURRENT_ITINERARY, PAYLOAD, API_PAYLOAD, TRIP, "cambia qualcosa", api_key="fake-key"
            )
        self.assertIsNotNone(result.parse_error)
        self.assertIsNone(result.itinerary)

    def test_truncated_response_raises_clear_error(self):
        fake_response = _mock_response("{incompleto", stop_reason="max_tokens")
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            with self.assertRaises(refinement.RefinementError) as ctx:
                refinement.refine_itinerary(
                    CURRENT_ITINERARY, PAYLOAD, API_PAYLOAD, TRIP, "cambia qualcosa", api_key="fake-key"
                )
        self.assertIn("troncata", str(ctx.exception))

    def test_max_tokens_scales_with_trip_duration_when_not_overridden(self):
        # [AGGIUNTO 2026-07-12 — audit di potenziamento massimo] Stesso gap
        # e stesso fix di claude_engine.call_claude(): max_tokens era fisso
        # a 16000 anche qui, indipendentemente da quanto fosse lungo il
        # viaggio da rigenerare.
        long_trip = dataclasses.replace(TRIP, duration_days=14, date_end="2026-09-15")
        fake_response = _mock_response(json.dumps(CURRENT_ITINERARY))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            refinement.refine_itinerary(
                CURRENT_ITINERARY, PAYLOAD, API_PAYLOAD, long_trip, "cambia qualcosa", api_key="fake-key"
            )
        kwargs = MockClient.return_value.messages.create.call_args.kwargs
        self.assertGreater(kwargs["max_tokens"], BASE_MAX_TOKENS)

    def test_max_tokens_explicit_override_still_respected(self):
        fake_response = _mock_response(json.dumps(CURRENT_ITINERARY))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            refinement.refine_itinerary(
                CURRENT_ITINERARY, PAYLOAD, API_PAYLOAD, TRIP, "cambia qualcosa",
                api_key="fake-key", max_tokens=1234,
            )
        kwargs = MockClient.return_value.messages.create.call_args.kwargs
        self.assertEqual(kwargs["max_tokens"], 1234)


if __name__ == "__main__":
    unittest.main()
