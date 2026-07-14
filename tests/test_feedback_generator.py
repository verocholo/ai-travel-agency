"""
[NUOVO 2026-07-12 — richiesta di Lorenzo, idea proposta da Claude:
"feedback post-viaggio"] Copre src/feedback_generator.py, stesso pattern
di mocking di test_guide_generator.py — mai una vera chiamata API nella
suite automatica.
"""
import json
import unittest
from unittest.mock import patch, MagicMock

from src.feedback_generator import (
    build_feedback_user_message,
    generate_post_trip_feedback,
    render_feedback_markdown,
    FeedbackGeneratorError,
)

ITINERARY = {
    "destination": "Roma",
    "days": [{"day": 1, "title": "Arrivo", "blocks": [
        {"time": "09:00", "activity": "Colosseo", "location": "Roma"},
    ]}],
}

VALID_FEEDBACK = {
    "intro_message": "Speriamo che il viaggio a Roma sia andato benissimo!",
    "questions": [
        "Il pacing tra il torneo e il recupero il primo giorno ti è sembrato adeguato?",
        "Il Colosseo ha rispettato le aspettative in termini di tempo di visita stimato?",
    ],
    "testimonial_request": "Ci daresti il permesso di usare la tua risposta come testimonianza pubblica?",
    "closing_message": "Grazie ancora per aver scelto il nostro servizio!",
}


def _mock_response(text: str, stop_reason: str = "end_turn"):
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    return response


class TestBuildFeedbackUserMessage(unittest.TestCase):
    def test_includes_itinerary_content(self):
        msg = build_feedback_user_message(ITINERARY)
        self.assertIn("Colosseo", msg)
        self.assertIn("Roma", msg)

    def test_includes_objective_function_when_given(self):
        msg = build_feedback_user_message(ITINERARY, objective_function="ENERGY_PACING")
        self.assertIn("ENERGY_PACING", msg)


class TestGeneratePostTripFeedback(unittest.TestCase):
    def test_successful_generation_returns_dict(self):
        fake_response = _mock_response(json.dumps(VALID_FEEDBACK))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            feedback = generate_post_trip_feedback(ITINERARY, api_key="fake-key")
        self.assertEqual(len(feedback["questions"]), 2)

    def test_markdown_fence_wrapped_json_still_parses(self):
        wrapped = "```json\n" + json.dumps(VALID_FEEDBACK) + "\n```"
        fake_response = _mock_response(wrapped)
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            feedback = generate_post_trip_feedback(ITINERARY, api_key="fake-key")
        self.assertIn("testimonial_request", feedback)

    def test_missing_field_raises_clear_error(self):
        incomplete = dict(VALID_FEEDBACK)
        del incomplete["testimonial_request"]
        fake_response = _mock_response(json.dumps(incomplete))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            with self.assertRaises(FeedbackGeneratorError) as ctx:
                generate_post_trip_feedback(ITINERARY, api_key="fake-key")
        self.assertIn("testimonial_request", str(ctx.exception))

    def test_too_many_questions_raises_clear_error(self):
        bad = dict(VALID_FEEDBACK)
        bad["questions"] = ["a", "b", "c", "d", "e"]
        fake_response = _mock_response(json.dumps(bad))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            with self.assertRaises(FeedbackGeneratorError):
                generate_post_trip_feedback(ITINERARY, api_key="fake-key")

    def test_truncated_response_raises_clear_error(self):
        fake_response = _mock_response("{incompleto", stop_reason="max_tokens")
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            with self.assertRaises(FeedbackGeneratorError) as ctx:
                generate_post_trip_feedback(ITINERARY, api_key="fake-key")
        self.assertIn("troncata", str(ctx.exception))


class TestRenderFeedbackMarkdown(unittest.TestCase):
    def test_renders_all_sections(self):
        out = render_feedback_markdown(VALID_FEEDBACK)
        self.assertIn(VALID_FEEDBACK["intro_message"], out)
        self.assertIn(VALID_FEEDBACK["questions"][0], out)
        self.assertIn(VALID_FEEDBACK["testimonial_request"], out)
        self.assertIn(VALID_FEEDBACK["closing_message"], out)


if __name__ == "__main__":
    unittest.main()
