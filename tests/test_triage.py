import unittest
from src.triage import deduce_objective_function, normalize_raw_input, _date_difference_days
from src.schemas import VALID_OBJECTIVE_FUNCTIONS


class TestDeduceObjectiveFunction(unittest.TestCase):
    def test_sport(self):
        self.assertEqual(deduce_objective_function("Torneo di tennis amatoriale"), "ENERGY_PACING")
        self.assertEqual(deduce_objective_function("Allenamento intensivo"), "ENERGY_PACING")

    def test_famiglia(self):
        self.assertEqual(deduce_objective_function("Vacanza in famiglia con bambini"), "FRICTION_SAFETY")

    def test_lavoro_remoto(self):
        # [AGGIUNTO 2026-07-11] Terzo modulo verticale: WORK_CONNECTIVITY.
        self.assertEqual(deduce_objective_function("Lavoro da remoto per due settimane"), "WORK_CONNECTIVITY")
        self.assertEqual(deduce_objective_function("Sono un nomade digitale, cerco coworking"), "WORK_CONNECTIVITY")
        self.assertEqual(deduce_objective_function("Workation smart working"), "WORK_CONNECTIVITY")

    def test_luxury(self):
        self.assertEqual(deduce_objective_function("Anniversario di matrimonio"), "EXCLUSIVITY_ZERO_FRICTION")

    def test_luna_di_miele(self):
        # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] "luna di miele"
        # (frase italiana standard per "honeymoon", prima presente solo in
        # inglese) mancava: un cliente italiano che scrive "Viaggio di luna
        # di miele" cadeva silenziosamente su BALANCED.
        self.assertEqual(deduce_objective_function("Viaggio di luna di miele a Parigi"), "EXCLUSIVITY_ZERO_FRICTION")

    def test_sport_generic_keyword(self):
        # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] "sport"/"sportiv-"
        # mancava dalle keyword ENERGY_PACING: una "Vacanza sportiva"
        # generica cadeva su BALANCED nonostante ENERGY_PACING sia
        # esattamente la lente di ottimizzazione giusta.
        self.assertEqual(deduce_objective_function("Vacanza sportiva in montagna"), "ENERGY_PACING")
        self.assertEqual(deduce_objective_function("Settimana di sport intenso"), "ENERGY_PACING")

    def test_gara_does_not_false_positive_match_garage(self):
        # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Bug reale trovato
        # in audit: il matching precedente era `"gara" in s` (substring
        # puro), che scattava anche su "garage" ("gara" + "ge") — un
        # cliente che scrive "Cerco hotel con garage" veniva erroneamente
        # dedotto come ENERGY_PACING. Ora richiede confine di parola.
        self.assertEqual(deduce_objective_function("Cerco hotel con garage"), "BALANCED")
        # "gara" come parola intera deve continuare a funzionare (nessuna
        # regressione sull'intento originale).
        self.assertEqual(deduce_objective_function("Gara di tennis amatoriale"), "ENERGY_PACING")

    def test_family_safety_keywords_win_over_sport_keywords_when_mixed(self):
        # [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità]
        # Prima, ENERGY_PACING veniva controllato per primo: uno "scopo"
        # che menziona sia sport sia famiglia/anziani/bambini finiva
        # dedotto ENERGY_PACING, perdendo le protezioni FRICTION_SAFETY
        # (finestre rigide, accessibilità, sicurezza) per un viaggio con
        # anziani/bambini a bordo. La sicurezza deve sempre prevalere
        # (stesso principio dichiarato in system_prompt_master.txt per il
        # profilo FRICTION_SAFETY).
        self.assertEqual(
            deduce_objective_function("Vacanza sportiva in famiglia con nonni anziani e bambini"),
            "FRICTION_SAFETY",
        )
        self.assertEqual(
            deduce_objective_function("Torneo di tennis con tutta la famiglia, bambini al seguito"),
            "FRICTION_SAFETY",
        )

    def test_default(self):
        self.assertEqual(deduce_objective_function("Weekend qualsiasi"), "BALANCED")
        self.assertEqual(deduce_objective_function(""), "BALANCED")

    def test_every_possible_output_is_a_valid_objective_function(self):
        # [AGGIUNTO 2026-07-11] Regressione diretta: aggiungere
        # WORK_CONNECTIVITY qui in triage.py senza aggiungerlo anche a
        # schemas.py::VALID_OBJECTIVE_FUNCTIONS ha fatto fallire
        # Trip.validate() con un errore criptico solo alla prima chiamata
        # reale (run_mock -> ValueError), non ai unit test — perché nessun
        # test collegava esplicitamente le due liste. Questo test lo
        # impedisce per qualunque nicchia futura: ogni stringa che
        # deduce_objective_function può restituire deve esistere anche nel
        # whitelist di Trip.validate().
        possible_scopi = [
            "Torneo di tennis amatoriale", "Vacanza in famiglia con bambini",
            "Lavoro da remoto", "Anniversario di matrimonio", "Weekend qualsiasi", "",
        ]
        for scopo in possible_scopi:
            of = deduce_objective_function(scopo)
            self.assertIn(of, VALID_OBJECTIVE_FUNCTIONS, f"'{of}' (da scopo='{scopo}') non in VALID_OBJECTIVE_FUNCTIONS")


class TestNormalizeRawInput(unittest.TestCase):
    def test_happy_path(self):
        raw = {
            "email": "a@b.com",
            "scopo": "Torneo di tennis amatoriale",
            "destinazione": "Val d'Orcia, Toscana",
            "arrivo": "2026-09-14",
            "partenza": "2026-09-17",
            "budget": 0,
            "note": "niente folla",
        }
        trip = normalize_raw_input(raw)
        self.assertEqual(trip.objective_function, "ENERGY_PACING")
        self.assertEqual(trip.duration_days, 3)
        self.assertEqual(trip.budget_mode, "UNLIMITED")
        self.assertEqual(trip.validate(), [])

    def test_budget_limited(self):
        raw = {
            "email": "a@b.com", "scopo": "Vacanza di lusso",
            "destinazione": "Zurigo", "arrivo": "2026-08-01",
            "partenza": "2026-08-08", "budget": 150, "note": "",
        }
        trip = normalize_raw_input(raw)
        self.assertEqual(trip.budget_mode, "LIMITED")
        self.assertEqual(trip.duration_days, 7)

    def test_date_difference(self):
        self.assertEqual(_date_difference_days("2026-01-01", "2026-01-05"), 4)

    def test_invalid_dates_caught_by_validate(self):
        raw = {
            "email": "a@b.com", "scopo": "x", "destinazione": "Roma",
            "arrivo": "2026-10-06", "partenza": "2026-10-05",  # invertite!
            "budget": 0, "note": "",
        }
        trip = normalize_raw_input(raw)
        errors = trip.validate()
        self.assertTrue(any("date_start" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
