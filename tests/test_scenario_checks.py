import unittest
from src.scenario_checks import (
    check_energy_alternation, check_budget_alert_when_needed,
    check_slot_libero_transparency,
    check_no_excluded_poi_used, check_rigid_window_free_of_real_activity,
)


class TestEnergyAlternation(unittest.TestCase):
    def setUp(self):
        self.energy = {"MATCH1": "HIGH", "MATCH2": "HIGH", "MUSEO": "MEDIUM",
                        "SPA": "LOW", "REST": "LOW"}

    def test_high_followed_by_low_passes(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "MATCH1"},
            {"time": "12:00", "poi_id": "REST"},
        ]}]}
        ok, violations = check_energy_alternation(itin, self.energy)
        self.assertTrue(ok, violations)

    def test_high_followed_by_medium_fails(self):
        # esattamente il tranello del fixture test_pacing_energetico
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "MATCH1"},
            {"time": "12:00", "poi_id": "MUSEO"},
        ]}]}
        ok, violations = check_energy_alternation(itin, self.energy)
        self.assertFalse(ok)
        self.assertEqual(len(violations), 1)

    def test_high_followed_by_high_fails(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "MATCH1"},
            {"time": "12:00", "poi_id": "MATCH2"},
        ]}]}
        ok, violations = check_energy_alternation(itin, self.energy)
        self.assertFalse(ok)

    def test_high_followed_by_slot_libero_passes(self):
        # poi_id=None (SLOT LIBERO) conta come riposo, non è una violazione
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "MATCH1"},
            {"time": "12:00", "poi_id": None},
        ]}]}
        ok, violations = check_energy_alternation(itin, self.energy)
        self.assertTrue(ok, violations)

    def test_high_followed_by_hotel_passes(self):
        # id non presente nel dict energy (es. hotel, non taggato) -> non è HIGH/MEDIUM
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "MATCH1"},
            {"time": "12:00", "poi_id": "H1"},
        ]}]}
        ok, violations = check_energy_alternation(itin, self.energy)
        self.assertTrue(ok, violations)

    def test_no_high_blocks_trivially_passes(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "SPA"},
            {"time": "12:00", "poi_id": "REST"},
        ]}]}
        ok, violations = check_energy_alternation(itin, self.energy)
        self.assertTrue(ok, violations)


class TestBudgetAlertWhenNeeded(unittest.TestCase):
    def test_unlimited_always_passes(self):
        ok, msg = check_budget_alert_when_needed({"budget_alert": None}, "UNLIMITED", 0)
        self.assertTrue(ok)

    def test_limited_incompatible_no_alert_fails(self):
        ok, msg = check_budget_alert_when_needed(
            {"budget_alert": None}, "LIMITED", 150.0, min_cost_estimate=2170.0)
        self.assertFalse(ok)

    def test_limited_incompatible_with_alert_passes(self):
        ok, msg = check_budget_alert_when_needed(
            {"budget_alert": "Budget incompatibile, servono 2170€"}, "LIMITED", 150.0,
            min_cost_estimate=2170.0)
        self.assertTrue(ok)

    def test_limited_without_min_cost_estimate_is_informative_only(self):
        ok, msg = check_budget_alert_when_needed({"budget_alert": None}, "LIMITED", 150.0)
        self.assertTrue(ok)  # non possiamo verificare la matematica senza min_cost_estimate


class TestSlotLiberoTransparency(unittest.TestCase):
    # [RINOMINATA 2026-07-12, vedi scenario_checks.py per il razionale]
    def test_slot_libero_marked_correctly_passes(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "20:00", "poi_id": None, "activity": "[SLOT LIBERO] Cena libera"},
        ]}]}
        ok, violations = check_slot_libero_transparency(itin, poi_ids_provided=set())
        self.assertTrue(ok, violations)

    def test_null_poi_id_without_marker_fails(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "20:00", "poi_id": None, "activity": "Cena in un ristorante tipico"},
        ]}]}
        ok, violations = check_slot_libero_transparency(itin, poi_ids_provided=set())
        self.assertFalse(ok)

    def test_poi_id_not_in_provided_set_fails(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "20:00", "poi_id": "GHOST", "activity": "Cena"},
        ]}]}
        ok, violations = check_slot_libero_transparency(itin, poi_ids_provided={"POI1"})
        self.assertFalse(ok)

    def test_poi_id_in_provided_set_passes(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "20:00", "poi_id": "POI1", "activity": "Cena"},
        ]}]}
        ok, violations = check_slot_libero_transparency(itin, poi_ids_provided={"POI1"})
        self.assertTrue(ok, violations)


class TestNoExcludedPoiUsed(unittest.TestCase):
    # [AGGIUNTO 2026-07-11] Automatizza la verifica fatta a mano su
    # test_friction_safety_famiglia (POI_TREKKING mai scelto).
    def test_excluded_poi_not_used_passes(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "POI_ZOO", "activity": "Zoo"},
        ]}]}
        ok, violations = check_no_excluded_poi_used(itin, excluded_poi_ids={"POI_TREKKING"})
        self.assertTrue(ok, violations)

    def test_excluded_poi_used_fails(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "POI_TREKKING", "activity": "Sentiero panoramico"},
        ]}]}
        ok, violations = check_no_excluded_poi_used(itin, excluded_poi_ids={"POI_TREKKING"})
        self.assertFalse(ok)
        self.assertEqual(len(violations), 1)

    def test_excluded_poi_used_on_multiple_days_reports_all(self):
        itin = {"days": [
            {"day": 1, "blocks": [{"time": "09:00", "poi_id": "POI_TREKKING", "activity": "x"}]},
            {"day": 2, "blocks": [{"time": "09:00", "poi_id": "POI_TREKKING", "activity": "x"}]},
        ]}
        ok, violations = check_no_excluded_poi_used(itin, excluded_poi_ids={"POI_TREKKING"})
        self.assertFalse(ok)
        self.assertEqual(len(violations), 2)


class TestRigidWindowFreeOfRealActivity(unittest.TestCase):
    # [AGGIUNTO 2026-07-11] Automatizza la verifica fatta a mano sul
    # rispetto del pisolino (13:00-15:00) in test_friction_safety_famiglia.
    def test_real_activity_outside_window_passes(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:15", "poi_id": "POI_ZOO", "activity": "Zoo"},
            {"time": "13:00", "poi_id": None, "activity": "[SLOT LIBERO] Pisolino"},
            {"time": "15:15", "poi_id": "POI_MUSEO", "activity": "Museo"},
        ]}]}
        ok, violations = check_rigid_window_free_of_real_activity(itin, "13:00", "15:00")
        self.assertTrue(ok, violations)

    def test_real_activity_starting_inside_window_fails(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "13:30", "poi_id": "POI_ZOO", "activity": "Zoo"},
        ]}]}
        ok, violations = check_rigid_window_free_of_real_activity(itin, "13:00", "15:00")
        self.assertFalse(ok)
        self.assertEqual(len(violations), 1)

    def test_slot_libero_inside_window_passes(self):
        # Il pisolino stesso (poi_id=None) non è mai una violazione, anche
        # se il suo orario di inizio coincide esattamente con la finestra.
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "13:00", "poi_id": None, "activity": "[SLOT LIBERO] Pisolino"},
        ]}]}
        ok, violations = check_rigid_window_free_of_real_activity(itin, "13:00", "15:00")
        self.assertTrue(ok, violations)

    def test_activity_exactly_at_window_end_passes(self):
        # [window_start, window_end) — l'estremo finale è escluso: un'uscita
        # che inizia esattamente alle 15:00 non è una violazione.
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "15:00", "poi_id": "POI_MUSEO", "activity": "Museo"},
        ]}]}
        ok, violations = check_rigid_window_free_of_real_activity(itin, "13:00", "15:00")
        self.assertTrue(ok, violations)

    def test_invalid_window_bounds_fails_explicitly(self):
        itin = {"days": []}
        ok, violations = check_rigid_window_free_of_real_activity(itin, "boh", "15:00")
        self.assertFalse(ok)

    def test_start_equal_to_end_fails_explicitly(self):
        # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Bug trovato in
        # audit: prima di questo fix, window_start==window_end (finestra a
        # durata zero) faceva sì che `start_min <= block_min < end_min` non
        # fosse MAI vero — il controllo passava sempre "senza violazioni",
        # mascherando un caso configurato male invece di segnalarlo.
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "13:00", "activity": "Qualcosa", "poi_id": "POI1"},
        ]}]}
        ok, violations = check_rigid_window_free_of_real_activity(itin, "13:00", "13:00")
        self.assertFalse(ok)

    def test_start_after_end_fails_explicitly(self):
        # Finestra overnight (es. window_start="22:00", window_end="02:00")
        # non è supportata da questo controllo (nessun caso d'uso attuale la
        # richiede) — deve fallire esplicitamente, non passare in silenzio
        # con "nessuna violazione mai rilevabile".
        itin = {"days": []}
        ok, violations = check_rigid_window_free_of_real_activity(itin, "22:00", "02:00")
        self.assertFalse(ok)

    def test_hotel_poi_id_inside_window_passes_when_safe_ids_given(self):
        # [AGGIUNTO 2026-07-11] Scoperto da --repeat 5 su un run reale: il
        # modello a volte marca il pisolino con poi_id="H1" (l'hotel) invece
        # di None. Semanticamente non è un'intrusione reale, quindi non deve
        # essere una violazione quando safe_poi_ids è passato esplicitamente.
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "13:00", "poi_id": "H1", "activity": "Pisolino obbligatorio in camera"},
        ]}]}
        ok, violations = check_rigid_window_free_of_real_activity(
            itin, "13:00", "15:00", safe_poi_ids={"H1"})
        self.assertTrue(ok, violations)

    def test_hotel_poi_id_inside_window_fails_without_safe_ids(self):
        # Comportamento di default (safe_poi_ids omesso) resta conservativo:
        # senza sapere quali id sono "sicuri", un poi_id non-None dentro la
        # finestra è trattato come potenziale violazione.
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "13:00", "poi_id": "H1", "activity": "Pisolino obbligatorio in camera"},
        ]}]}
        ok, violations = check_rigid_window_free_of_real_activity(itin, "13:00", "15:00")
        self.assertFalse(ok)

    def test_protected_work_block_poi_id_passes_when_safe_ids_given(self):
        # [AGGIUNTO 2026-07-11] Caso WORK_CONNECTIVITY: il blocco di lavoro
        # stesso (es. in coworking) dentro la finestra protetta non è
        # un'intrusione — è l'attività che la finestra esiste per proteggere.
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "09:00", "poi_id": "POI_COWORK", "activity": "Lavoro da remoto"},
        ]}]}
        ok, violations = check_rigid_window_free_of_real_activity(
            itin, "09:00", "13:00", safe_poi_ids={"POI_COWORK"})
        self.assertTrue(ok, violations)

    def test_intrusion_during_work_block_fails(self):
        itin = {"days": [{"day": 1, "blocks": [
            {"time": "10:30", "poi_id": "POI_NIGHTLIFE", "activity": "Giro turistico"},
        ]}]}
        ok, violations = check_rigid_window_free_of_real_activity(
            itin, "09:00", "13:00", safe_poi_ids={"POI_COWORK"})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
