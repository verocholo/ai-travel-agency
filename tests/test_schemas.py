"""
[AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Prima suite di test mai
scritta per src/schemas.py::Trip.validate() — un gap di per sé notato
durante la revisione. Copre sia i controlli originali sia i tre aggiunti
in questo stesso audit (budget_eur negativo, destination vuota, email
palesemente malformata), che prima passavano indenni attraverso
trip.validate() senza che nessun test lo segnalasse.
"""
import unittest
from src.schemas import Trip, VALID_OBJECTIVE_FUNCTIONS, POI


def _valid_trip(**overrides) -> Trip:
    base = dict(
        email="cliente@mail.com",
        destination="Roma",
        date_start="2026-09-01",
        date_end="2026-09-04",
        duration_days=3,
        budget_eur=0.0,
        budget_mode="UNLIMITED",
        objective_function="BALANCED",
    )
    base.update(overrides)
    return Trip(**base)


class TestTripValidate(unittest.TestCase):
    def test_valid_trip_has_no_errors(self):
        self.assertEqual(_valid_trip().validate(), [])

    def test_date_start_not_before_date_end_fails(self):
        errors = _valid_trip(date_start="2026-09-05", date_end="2026-09-04").validate()
        self.assertTrue(any("date_start" in e for e in errors))

    def test_dates_equal_fails(self):
        errors = _valid_trip(date_start="2026-09-01", date_end="2026-09-01").validate()
        self.assertTrue(any("date_start" in e for e in errors))

    def test_non_numeric_budget_fails(self):
        errors = _valid_trip(budget_eur="non un numero").validate()
        self.assertTrue(any("budget_eur" in e for e in errors))

    def test_negative_budget_fails(self):
        # [AGGIUNTO 2026-07-11] Gap trovato in audit: un budget_eur
        # negativo (tipico errore di digitazione in un form reale) passava
        # indenne — non è un caso ipotetico, LIMITED con budget negativo è
        # uno stato non valido che nessuna parte a valle sapeva gestire.
        errors = _valid_trip(budget_eur=-50.0, budget_mode="LIMITED").validate()
        self.assertTrue(any("negativo" in e for e in errors))

    def test_zero_budget_does_not_trigger_negative_check(self):
        # budget_eur=0 (UNLIMITED, il default del form) non è negativo:
        # nessuna regressione sul caso più comune.
        self.assertEqual(_valid_trip(budget_eur=0.0).validate(), [])

    def test_invalid_objective_function_fails(self):
        errors = _valid_trip(objective_function="NON_ESISTE").validate()
        self.assertTrue(any("objective_function" in e for e in errors))

    def test_invalid_budget_mode_fails(self):
        errors = _valid_trip(budget_mode="BOH").validate()
        self.assertTrue(any("budget_mode" in e for e in errors))

    def test_empty_destination_fails(self):
        # [AGGIUNTO 2026-07-11] Gap trovato in audit.
        errors = _valid_trip(destination="").validate()
        self.assertTrue(any("destination" in e for e in errors))

    def test_whitespace_only_destination_fails(self):
        errors = _valid_trip(destination="   ").validate()
        self.assertTrue(any("destination" in e for e in errors))

    def test_empty_email_fails(self):
        # [AGGIUNTO 2026-07-11] Gap trovato in audit.
        errors = _valid_trip(email="").validate()
        self.assertTrue(any("email" in e for e in errors))

    def test_email_without_at_sign_fails(self):
        errors = _valid_trip(email="non-una-email").validate()
        self.assertTrue(any("email" in e for e in errors))

    def test_valid_email_passes(self):
        errors = _valid_trip(email="lorenzo@example.com").validate()
        self.assertEqual([e for e in errors if "email" in e], [])

    def test_all_valid_objective_functions_pass(self):
        # Regressione anti-desync (stesso principio già usato in
        # test_triage.py): ogni valore in VALID_OBJECTIVE_FUNCTIONS deve
        # essere accettato da Trip.validate(), non solo alcuni.
        for of in VALID_OBJECTIVE_FUNCTIONS:
            errors = _valid_trip(objective_function=of).validate()
            self.assertEqual(errors, [], f"objective_function={of} non dovrebbe fallire la validazione")


class TestPOIPriceLevel(unittest.TestCase):
    """[AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni costo
    (hotel, ristoranti)"] `POI.price_level` è un campo nuovo, opzionale —
    verifica che il default resti None (nessuna rottura per i chiamanti
    esistenti che costruiscono un POI senza specificarlo, es. i fixture di
    mock_rag_data.py) e che venga incluso in to_dict() per finire nel
    payload passato a Claude."""

    def _poi(self, **overrides):
        base = dict(id="P1", type="restaurant", name="Trattoria Test", lat=41.9, lng=12.5)
        base.update(overrides)
        return POI(**base)

    def test_default_price_level_is_none(self):
        self.assertIsNone(self._poi().price_level)

    def test_explicit_price_level_preserved(self):
        self.assertEqual(self._poi(price_level="MODERATE").price_level, "MODERATE")

    def test_to_dict_includes_price_level(self):
        self.assertIn("price_level", self._poi(price_level="EXPENSIVE").to_dict())
        self.assertEqual(self._poi(price_level="EXPENSIVE").to_dict()["price_level"], "EXPENSIVE")

    def test_to_dict_includes_price_level_none(self):
        self.assertIsNone(self._poi().to_dict()["price_level"])


if __name__ == "__main__":
    unittest.main()
