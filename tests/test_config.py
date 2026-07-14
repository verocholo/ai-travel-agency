"""
[AGGIUNTO 2026-07-12 — gap di copertura reale trovato nell'audit di
potenziamento massimo] `src/config.py` non aveva nessun test dedicato.
In particolare, la nota di fix del 2026-07-11 nel codice sorgente ("i
default di una dataclass sono valutati una volta a import time, non a
ogni istanziazione — fix: default_factory") non aveva un test di
REGRESSIONE che la eserciti davvero: nulla impediva a un futuro refactor
di reintrodurre lo stesso bug (es. tornando a `field(default=os.getenv(...))`)
senza che nessun test se ne accorgesse.
"""
import os
import unittest
from unittest.mock import patch
from src.config import Settings


class TestSettingsEnvReadPerInstance(unittest.TestCase):
    """
    Regressione diretta sul bug [CORRETTO 2026-07-11] descritto nel
    docstring di Settings: con `os.getenv(...)` come default DIRETTO
    (non default_factory), i valori vengono letti UNA sola volta a
    import-time della classe, non ad ogni Settings(). Se qualcuno
    reintroducesse quel bug, questo test lo romperebbe subito.
    """

    def test_reads_current_env_value_not_a_stale_import_time_snapshot(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "prima-chiave"}):
            s1 = Settings()
            self.assertEqual(s1.anthropic_api_key, "prima-chiave")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "seconda-chiave"}):
            s2 = Settings()
            self.assertEqual(s2.anthropic_api_key, "seconda-chiave")

    def test_missing_key_is_none_not_empty_string(self):
        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
            self.assertIsNone(s.anthropic_api_key)
            self.assertIsNone(s.google_maps_key)
            self.assertIsNone(s.liteapi_key)


class TestMissingForLiveMode(unittest.TestCase):
    def test_all_keys_present_nothing_missing(self):
        env = {"ANTHROPIC_API_KEY": "a", "GOOGLE_MAPS_KEY": "b", "LITEAPI_KEY": "c"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(Settings().missing_for_live_mode(), [])

    def test_reports_each_missing_key_by_name(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "a"}, clear=True):
            missing = Settings().missing_for_live_mode()
        self.assertIn("GOOGLE_MAPS_KEY", missing)
        self.assertIn("LITEAPI_KEY", missing)
        self.assertNotIn("ANTHROPIC_API_KEY", missing)

    def test_all_missing_reports_all_three(self):
        with patch.dict(os.environ, {}, clear=True):
            missing = Settings().missing_for_live_mode()
        self.assertEqual(set(missing), {"ANTHROPIC_API_KEY", "GOOGLE_MAPS_KEY", "LITEAPI_KEY"})


class TestMissingForMockMode(unittest.TestCase):
    def test_only_anthropic_key_required(self):
        # in mock mode Google Maps/LiteAPI non servono: i dati RAG sono finti
        env = {"ANTHROPIC_API_KEY": "a"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(Settings().missing_for_mock_mode(), [])

    def test_missing_anthropic_key_reported(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings().missing_for_mock_mode(), ["ANTHROPIC_API_KEY"])

    def test_google_maps_and_liteapi_absence_does_not_affect_mock_mode(self):
        # ANTHROPIC_API_KEY presente, le altre due assenti -> comunque [] per mock mode
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "a"}, clear=True):
            self.assertEqual(Settings().missing_for_mock_mode(), [])


if __name__ == "__main__":
    unittest.main()
