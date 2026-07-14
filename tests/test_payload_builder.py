import unittest
from src.schemas import Trip, Hotel, POI, TravelTime
from src.payload_builder import assemble_payload


class TestAssemblePayload(unittest.TestCase):
    def setUp(self):
        self.trip = Trip(
            email="a@b.com", destination="Roma", date_start="2026-10-05",
            date_end="2026-10-06", duration_days=1, budget_eur=0,
            budget_mode="UNLIMITED", objective_function="ENERGY_PACING",
            raw_notes="test",
        )
        self.hotels = [Hotel(id="H1", name="Hotel X", lat=1.0, lng=2.0)]
        self.pois = [POI(id="P1", type="restaurant", name="Y", lat=1.1, lng=2.1)]
        self.travel_times = [TravelTime(origin_id="H1", dest_id="P1", minutes=10)]

    def test_shape_matches_ds_payload_api(self):
        payload = assemble_payload(self.trip, self.hotels, self.travel_times, self.pois)
        self.assertIn("trip", payload)
        self.assertIn("DATI_API_FORNITI", payload)
        self.assertIn("hotels", payload["DATI_API_FORNITI"])
        self.assertIn("travel_times", payload["DATI_API_FORNITI"])
        self.assertIn("poi", payload["DATI_API_FORNITI"])

    def test_trip_fields_present(self):
        payload = assemble_payload(self.trip, self.hotels, self.travel_times, self.pois)
        for field in ("email", "destination", "date_start", "date_end", "duration_days",
                      "budget_eur", "budget_mode", "objective_function", "raw_notes"):
            self.assertIn(field, payload["trip"])

    def test_json_serializable(self):
        import json
        payload = assemble_payload(self.trip, self.hotels, self.travel_times, self.pois)
        json.dumps(payload)  # non deve sollevare


if __name__ == "__main__":
    unittest.main()
