"""
[AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni costo (hotel,
ristoranti)"] Copre src/price_display.py — funzione pura, nessun mock
necessario.
"""
import unittest
from src.price_display import price_level_symbol


class TestPriceLevelSymbol(unittest.TestCase):
    def test_free(self):
        self.assertEqual(price_level_symbol("FREE"), "Gratuito")

    def test_inexpensive(self):
        self.assertEqual(price_level_symbol("INEXPENSIVE"), "€")

    def test_moderate(self):
        self.assertEqual(price_level_symbol("MODERATE"), "€€")

    def test_expensive(self):
        self.assertEqual(price_level_symbol("EXPENSIVE"), "€€€")

    def test_very_expensive(self):
        self.assertEqual(price_level_symbol("VERY_EXPENSIVE"), "€€€€")

    def test_none_gives_empty_string_not_a_fake_symbol(self):
        # Mai inventare un simbolo per un dato assente — stesso principio
        # di Fedeltà RAG del resto del progetto.
        self.assertEqual(price_level_symbol(None), "")

    def test_empty_string_gives_empty_string(self):
        self.assertEqual(price_level_symbol(""), "")

    def test_unrecognized_value_gives_empty_string_not_a_crash(self):
        self.assertEqual(price_level_symbol("SOMETHING_UNEXPECTED"), "")


if __name__ == "__main__":
    unittest.main()
