"""
[NUOVO 2026-07-12 — richiesta di Lorenzo, "guida turistica sulla base
dell'itinerario generato (es. guida turistica sul colosseo a tutto
tondo)"] Copre src/guide_generator.py: `build_guide_user_message()`
(funzione pura) e `generate_poi_guide()` (chiamata Claude mockata, stesso
pattern di `tests/test_pipeline.py` — mai una vera chiamata API nella
suite automatica, coerente con come il resto del progetto testa Nodo 8).
"""
import unittest
from unittest.mock import patch, MagicMock

from src.guide_generator import (
    build_guide_user_message,
    generate_poi_guide,
    render_guide_markdown,
    GuideGeneratorError,
)

VALID_GUIDE = {
    "poi_name": "Colosseo",
    "title": "Il Colosseo: cuore dell'antica Roma",
    "history_summary": "Paragrafo uno.\n\nParagrafo due.",
    "practical_tips": ["Arriva presto per evitare la folla", "Indossa scarpe comode"],
    "best_time_to_visit": "Primo mattino, prima dell'apertura di massa",
    "estimated_visit_duration": "2-3 ore",
    "consiglio_personalizzato": "Dato il tuo ritmo energetico, pianifica una pausa dopo.",
    "disclaimer": "Verifica sempre orari e prezzi aggiornati sul sito ufficiale prima della visita.",
}


def _mock_response(text: str, stop_reason: str = "end_turn"):
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    return response


class TestBuildGuideUserMessage(unittest.TestCase):
    def test_includes_poi_and_destination(self):
        msg = build_guide_user_message("Colosseo", "Roma")
        self.assertIn("Colosseo", msg)
        self.assertIn("Roma", msg)

    def test_objective_function_included_when_present(self):
        msg = build_guide_user_message("Colosseo", "Roma", objective_function="ENERGY_PACING")
        self.assertIn("ENERGY_PACING", msg)

    def test_objective_function_absent_when_not_given(self):
        msg = build_guide_user_message("Colosseo", "Roma")
        self.assertNotIn("objective_function", msg)

    def test_module_id_included_when_present(self):
        msg = build_guide_user_message("Colosseo", "Roma", module_id="sport_active_travel")
        self.assertIn("sport_active_travel", msg)


class TestGeneratePoiGuide(unittest.TestCase):
    def test_successful_generation_returns_dict(self):
        import json
        fake_response = _mock_response(json.dumps(VALID_GUIDE))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            guide = generate_poi_guide("Colosseo", "Roma", api_key="fake-key")
        self.assertEqual(guide["poi_name"], "Colosseo")
        self.assertEqual(guide["estimated_visit_duration"], "2-3 ore")

    def test_markdown_fence_wrapped_json_still_parses(self):
        # [REGRESSIONE — stesso bug reale già trovato nel Nodo 9 sul
        # capstone lavoro/Lisbona] Claude a volte avvolge l'intero JSON in
        # una fence markdown nonostante le istruzioni. Riusiamo
        # `parse_claude_output()`, quindi questo deve funzionare qui
        # esattamente come già funziona per l'itinerario.
        import json
        wrapped = "```json\n" + json.dumps(VALID_GUIDE) + "\n```"
        fake_response = _mock_response(wrapped)
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            guide = generate_poi_guide("Colosseo", "Roma", api_key="fake-key")
        self.assertEqual(guide["poi_name"], "Colosseo")

    def test_invalid_json_raises_clear_error(self):
        fake_response = _mock_response("questo non e' JSON valido")
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            with self.assertRaises(GuideGeneratorError) as ctx:
                generate_poi_guide("Colosseo", "Roma", api_key="fake-key")
        self.assertIn("Colosseo", str(ctx.exception))

    def test_missing_required_field_raises_clear_error(self):
        import json
        incomplete = dict(VALID_GUIDE)
        del incomplete["disclaimer"]
        fake_response = _mock_response(json.dumps(incomplete))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            with self.assertRaises(GuideGeneratorError) as ctx:
                generate_poi_guide("Colosseo", "Roma", api_key="fake-key")
        self.assertIn("disclaimer", str(ctx.exception))

    def test_empty_practical_tips_raises_clear_error(self):
        import json
        bad = dict(VALID_GUIDE)
        bad["practical_tips"] = []
        fake_response = _mock_response(json.dumps(bad))
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            with self.assertRaises(GuideGeneratorError):
                generate_poi_guide("Colosseo", "Roma", api_key="fake-key")

    def test_truncated_response_raises_clear_error(self):
        fake_response = _mock_response("{incompleto...", stop_reason="max_tokens")
        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = fake_response
            with self.assertRaises(GuideGeneratorError) as ctx:
                generate_poi_guide("Colosseo", "Roma", api_key="fake-key")
        self.assertIn("troncata", str(ctx.exception))


class TestRenderGuideMarkdown(unittest.TestCase):
    def test_renders_all_sections(self):
        out = render_guide_markdown(VALID_GUIDE)
        self.assertIn(VALID_GUIDE["title"], out)
        self.assertIn("Paragrafo uno.", out)
        self.assertIn("Arriva presto per evitare la folla", out)
        self.assertIn(VALID_GUIDE["best_time_to_visit"], out)
        self.assertIn(VALID_GUIDE["estimated_visit_duration"], out)
        self.assertIn(VALID_GUIDE["consiglio_personalizzato"], out)
        self.assertIn(VALID_GUIDE["disclaimer"], out)


if __name__ == "__main__":
    unittest.main()
