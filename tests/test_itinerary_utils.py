"""
[AGGIUNTO 2026-07-12] Copre src/itinerary_utils.py — funzioni pure,
nessun mock necessario.
"""
import unittest
from src.itinerary_utils import extract_used_poi_ids, extract_used_poi_ids_by_day

ITINERARY = {
    "destination": "Roma",
    "days": [
        {"day": 1, "title": "Arrivo", "blocks": [
            {"time": "09:00", "activity": "Check-in", "location": "Hotel", "poi_id": "H1"},
            {"time": "13:00", "activity": "Pranzo", "location": "Trattoria", "poi_id": "POI1"},
            {"time": "16:00", "activity": "Riposo libero", "location": "Hotel", "poi_id": None},
        ]},
        {"day": 2, "title": "Museo", "blocks": [
            {"time": "10:00", "activity": "Museo", "location": "Museo del Vino", "poi_id": "POI3"},
            {"time": "13:00", "activity": "Pranzo", "location": "Trattoria", "poi_id": "POI1"},
        ]},
        {"day": 3, "title": "Libero", "blocks": [
            {"time": "10:00", "activity": "[SLOT LIBERO]", "location": "Centro", "poi_id": None},
        ]},
    ],
}


class TestExtractUsedPoiIds(unittest.TestCase):
    def test_collects_all_non_null_poi_ids_across_days(self):
        self.assertEqual(extract_used_poi_ids(ITINERARY), {"H1", "POI1", "POI3"})

    def test_empty_itinerary_gives_empty_set(self):
        self.assertEqual(extract_used_poi_ids({"days": []}), set())

    def test_missing_days_key_does_not_crash(self):
        self.assertEqual(extract_used_poi_ids({}), set())


class TestExtractUsedPoiIdsByDay(unittest.TestCase):
    def test_preserves_order_within_day(self):
        result = extract_used_poi_ids_by_day(ITINERARY)
        self.assertEqual(result[1], ["H1", "POI1"])
        self.assertEqual(result[2], ["POI3", "POI1"])

    def test_day_with_only_slot_libero_is_omitted(self):
        result = extract_used_poi_ids_by_day(ITINERARY)
        self.assertNotIn(3, result)

    def test_empty_itinerary_gives_empty_dict(self):
        self.assertEqual(extract_used_poi_ids_by_day({"days": []}), {})


if __name__ == "__main__":
    unittest.main()
