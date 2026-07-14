"""
[AGGIUNTO 2026-07-12 — gap di copertura reale trovato nell'audit di
potenziamento massimo] `src/claude_engine.py` non aveva NESSUN test
diretto prima di questo file: `select_model()` (la logica che decide
Sonnet vs Opus, con impatto diretto sui COGS del Cap. 2.7 del business
plan) e il rilevamento del troncamento `max_tokens` in `call_claude()`
(che distingue un errore leggibile da un `ParseError` criptico a valle nel
Nodo 9) erano entrambi verificati solo a mano durante le run dal vivo, mai
da un test automatico che li eserciti in isolamento.
"""
import unittest
from unittest.mock import patch, MagicMock
from src.claude_engine import (
    select_model, build_user_message, call_claude, ClaudeEngineError,
    select_max_tokens, BASE_MAX_TOKENS, BASELINE_DAYS, MAX_TOKENS_CEILING,
)


class TestSelectModel(unittest.TestCase):
    def test_exclusivity_objective_function_uses_opus(self):
        self.assertEqual(select_model("EXCLUSIVITY_ZERO_FRICTION", 3), "claude-opus-4-8")

    def test_long_trip_over_10_days_uses_opus_even_if_balanced(self):
        self.assertEqual(select_model("BALANCED", 11), "claude-opus-4-8")

    def test_exactly_10_days_still_uses_sonnet(self):
        # confine esatto: la regola è "> 10", non ">= 10"
        self.assertEqual(select_model("BALANCED", 10), "claude-sonnet-5")

    def test_short_trip_balanced_uses_sonnet(self):
        self.assertEqual(select_model("BALANCED", 3), "claude-sonnet-5")

    def test_energy_pacing_short_trip_uses_sonnet(self):
        self.assertEqual(select_model("ENERGY_PACING", 3), "claude-sonnet-5")

    def test_exclusivity_and_long_trip_together_still_opus(self):
        self.assertEqual(select_model("EXCLUSIVITY_ZERO_FRICTION", 14), "claude-opus-4-8")


class TestSelectMaxTokens(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — gap reale trovato nell'audit di potenziamento
    massimo] `max_tokens` era fisso a 16000 indipendentemente da
    `duration_days` — un viaggio lungo produce fisiologicamente più output
    (più "days[]", scratchpad più lungo) e rischiava lo stesso troncamento
    già visto e corretto una volta (FIX 2026-07-10 #3).
    """

    def test_short_trip_uses_base_budget(self):
        self.assertEqual(select_max_tokens(3), BASE_MAX_TOKENS)

    def test_exactly_baseline_days_uses_base_budget(self):
        self.assertEqual(select_max_tokens(BASELINE_DAYS), BASE_MAX_TOKENS)

    def test_beyond_baseline_scales_up(self):
        result_short = select_max_tokens(BASELINE_DAYS + 1)
        result_longer = select_max_tokens(BASELINE_DAYS + 5)
        self.assertGreater(result_short, BASE_MAX_TOKENS)
        self.assertGreater(result_longer, result_short)

    def test_never_exceeds_ceiling_even_for_very_long_trips(self):
        self.assertLessEqual(select_max_tokens(365), MAX_TOKENS_CEILING)


class TestBuildUserMessage(unittest.TestCase):
    def test_placeholder_replaced_with_serialized_payload(self):
        payload = {"destinazione": "Firenze", "n": 1}
        message = build_user_message(payload)
        self.assertNotIn("{{7.json}}", message)
        self.assertIn("Firenze", message)

    def test_non_ascii_chars_preserved_not_escaped(self):
        # ensure_ascii=False nel json.dumps — un nome di città con accenti
        # deve restare leggibile nel messaggio, non uscire come à.
        payload = {"destinazione": "Val d'Orcia, Toscana"}
        message = build_user_message(payload)
        self.assertIn("Val d'Orcia", message)
        self.assertNotIn("\\u00e0", message)


class _FakeTextBlock:
    def __init__(self, text):
        self.text = text


class _FakeUsage:
    def __init__(self, output_tokens):
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(self, text, stop_reason="end_turn", output_tokens=42):
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = stop_reason
        self.usage = _FakeUsage(output_tokens)


class TestCallClaude(unittest.TestCase):
    """
    Mocka `anthropic.Anthropic` direttamente (il modulo è importato
    localmente dentro call_claude() apposta per restare testabile senza il
    pacchetto — vedi il commento in claude_engine.py) cosi' nessuna di
    queste chiamate tocca davvero la rete.
    """

    def _make_fake_anthropic(self, response):
        fake_client = MagicMock()
        fake_client.messages.create.return_value = response
        fake_anthropic_module = MagicMock()
        fake_anthropic_module.Anthropic.return_value = fake_client
        return fake_anthropic_module, fake_client

    def test_returns_response_text_on_success(self):
        response = _FakeResponse("{\"ok\": true}")
        fake_module, fake_client = self._make_fake_anthropic(response)
        with patch.dict("sys.modules", {"anthropic": fake_module}):
            text = call_claude({"a": 1}, "BALANCED", 3, api_key="fake-key")
        self.assertEqual(text, "{\"ok\": true}")

    def test_raises_claude_engine_error_on_max_tokens_truncation(self):
        # [Bug reale FIX 2026-07-10 #3] Un JSON troncato a metà per
        # max_tokens raggiunto deve dare un errore diagnostico esplicito
        # qui, non un ParseError criptico a valle nel Nodo 9.
        response = _FakeResponse("{\"scratchpad\": \"tagliato a met", stop_reason="max_tokens", output_tokens=16000)
        fake_module, _ = self._make_fake_anthropic(response)
        with patch.dict("sys.modules", {"anthropic": fake_module}):
            with self.assertRaises(ClaudeEngineError) as ctx:
                call_claude({"a": 1}, "BALANCED", 3, api_key="fake-key", max_tokens=16000)
        self.assertIn("max_tokens", str(ctx.exception))
        self.assertIn("16000", str(ctx.exception))

    def test_temperature_omitted_by_default(self):
        response = _FakeResponse("{}")
        fake_module, fake_client = self._make_fake_anthropic(response)
        with patch.dict("sys.modules", {"anthropic": fake_module}):
            call_claude({"a": 1}, "BALANCED", 3, api_key="fake-key")
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertNotIn("temperature", kwargs)

    def test_temperature_included_when_explicitly_passed(self):
        response = _FakeResponse("{}")
        fake_module, fake_client = self._make_fake_anthropic(response)
        with patch.dict("sys.modules", {"anthropic": fake_module}):
            call_claude({"a": 1}, "BALANCED", 3, api_key="fake-key", temperature=0.5)
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0.5)

    def test_prefill_disabled_by_default_conversation_ends_on_user_message(self):
        # [FIX 2026-07-10 #2] use_prefill di default False: l'API rifiuta
        # esplicitamente un messaggio assistant in coda alla conversazione.
        response = _FakeResponse("{}")
        fake_module, fake_client = self._make_fake_anthropic(response)
        with patch.dict("sys.modules", {"anthropic": fake_module}):
            call_claude({"a": 1}, "BALANCED", 3, api_key="fake-key")
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["messages"][-1]["role"], "user")

    def test_prefill_when_explicitly_enabled_prepends_brace_to_result(self):
        response = _FakeResponse("\"ok\": true}")  # senza la graffa iniziale, come farebbe il modello con prefill
        fake_module, fake_client = self._make_fake_anthropic(response)
        with patch.dict("sys.modules", {"anthropic": fake_module}):
            text = call_claude({"a": 1}, "BALANCED", 3, api_key="fake-key", use_prefill=True)
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["messages"][-1]["role"], "assistant")
        self.assertEqual(kwargs["messages"][-1]["content"], "{")
        self.assertTrue(text.startswith("{"))

    def test_model_selected_correctly_passed_to_create(self):
        response = _FakeResponse("{}")
        fake_module, fake_client = self._make_fake_anthropic(response)
        with patch.dict("sys.modules", {"anthropic": fake_module}):
            call_claude({"a": 1}, "EXCLUSIVITY_ZERO_FRICTION", 3, api_key="fake-key")
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-4-8")

    def test_max_tokens_defaults_to_select_max_tokens_when_not_passed(self):
        # [AGGIUNTO 2026-07-12] nessun max_tokens esplicito -> deve scalare
        # con duration_days invece di usare sempre 16000.
        response = _FakeResponse("{}")
        fake_module, fake_client = self._make_fake_anthropic(response)
        with patch.dict("sys.modules", {"anthropic": fake_module}):
            call_claude({"a": 1}, "BALANCED", 14, api_key="fake-key")
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertGreater(kwargs["max_tokens"], BASE_MAX_TOKENS)

    def test_max_tokens_explicit_override_still_respected(self):
        response = _FakeResponse("{}")
        fake_module, fake_client = self._make_fake_anthropic(response)
        with patch.dict("sys.modules", {"anthropic": fake_module}):
            call_claude({"a": 1}, "BALANCED", 14, api_key="fake-key", max_tokens=9999)
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["max_tokens"], 9999)


if __name__ == "__main__":
    unittest.main()
