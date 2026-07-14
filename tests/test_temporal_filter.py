import unittest
from src.schemas import POI
from src.temporal_filter import compute_travel_days, filter_open_pois


class TestComputeTravelDays(unittest.TestCase):
    def test_short_trip(self):
        # 2026-09-14 è un lunedì; 3 giorni -> Mon, Tue, Wed
        days = compute_travel_days("2026-09-14", 3)
        self.assertEqual(days, ["Mon", "Tue", "Wed"])

    def test_full_week_shortcut(self):
        days = compute_travel_days("2026-09-14", 7)
        self.assertEqual(days, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    def test_longer_than_week_still_full_week(self):
        days = compute_travel_days("2026-09-14", 14)
        self.assertEqual(set(days), {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"})

    def test_zero_duration_raises_explicit_error_not_silent_empty_list(self):
        # [AGGIUNTO 2026-07-12 — gap reale trovato in audit di qualità]
        # Prima, duration_days=0 tornava silenziosamente [] (nessun
        # travel_days), che a valle in filter_open_pois() scarta ogni POI
        # con orari noti invece di segnalare un input invalido.
        with self.assertRaises(ValueError):
            compute_travel_days("2026-09-14", 0)

    def test_negative_duration_raises_explicit_error(self):
        with self.assertRaises(ValueError):
            compute_travel_days("2026-09-14", -3)


class TestFilterOpenPois(unittest.TestCase):
    def test_keeps_poi_open_on_travel_day(self):
        poi = POI(id="P1", type="restaurant", name="X", lat=0, lng=0, open_days=["Mon"])
        result = filter_open_pois([poi], ["Mon", "Tue"])
        self.assertEqual(len(result), 1)

    def test_drops_poi_closed_all_travel_days(self):
        poi = POI(id="P1", type="restaurant", name="X", lat=0, lng=0, open_days=["Sun"])
        result = filter_open_pois([poi], ["Mon", "Tue"])
        self.assertEqual(len(result), 0)

    def test_keeps_poi_with_unknown_hours_transparency(self):
        # gruppo B: open_days vuoto -> passa (trasparenza, non potatura conservativa)
        poi = POI(id="P1", type="restaurant", name="X", lat=0, lng=0, open_days=[])
        result = filter_open_pois([poi], ["Mon"])
        self.assertEqual(len(result), 1)

    def test_empty_poi_list_stays_empty(self):
        # array vuoto propagato as-is -> Claude attiva [SLOT LIBERO]
        self.assertEqual(filter_open_pois([], ["Mon"]), [])


if __name__ == "__main__":
    unittest.main()
