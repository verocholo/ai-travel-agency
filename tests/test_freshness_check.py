"""
[NUOVO 2026-07-12 — richiesta di Lorenzo, idea proposta da Claude:
"controllo di freschezza pre-partenza"] Copre src/freshness_check.py.
Mocka `LiteApiClient.search_hotel_offers` e `places_client.search_nearby`
— nessuna vera chiamata di rete, stesso pattern di
`test_pipeline.py::TestRunLiveModuleSelection` (questo ambiente sandbox
non ha comunque accesso di rete a quei fornitori, vedi nota nel modulo).
"""
import unittest
from unittest.mock import patch

from src.freshness_check import (
    check_hotel_freshness,
    check_poi_freshness,
    run_freshness_check,
    FreshnessReport,
)
import requests

from src.schemas import Trip, Hotel, POI, ApiPayload
from src.liteapi_client import LiteApiClient, LiteApiError

TRIP = Trip(
    email="cliente@mail.com", destination="Roma", date_start="2026-09-01", date_end="2026-09-04",
    duration_days=3, budget_eur=0, budget_mode="UNLIMITED", objective_function="BALANCED",
)
HOTEL = Hotel(id="H1", name="Hotel Test", lat=41.9, lng=12.5)
POI_OK = POI(id="P1", type="museum", name="Colosseo", lat=41.89, lng=12.49)
POI_MISSING = POI(id="P2", type="restaurant", name="Trattoria Sparita", lat=41.90, lng=12.48)


class TestCheckHotelFreshness(unittest.TestCase):
    def test_hotel_still_has_offers_confirmed(self):
        client = LiteApiClient(api_key="fake")
        with patch.object(client, "search_hotel_offers", return_value=[{"hotelId": "H1"}]):
            result = check_hotel_freshness(HOTEL, TRIP, client)
        self.assertTrue(result.still_confirmed)

    def test_hotel_no_offers_flagged(self):
        client = LiteApiClient(api_key="fake")
        with patch.object(client, "search_hotel_offers", return_value=[]):
            result = check_hotel_freshness(HOTEL, TRIP, client)
        self.assertFalse(result.still_confirmed)
        self.assertIn("Nessuna tariffa", result.detail)

    def test_api_error_flagged_not_raised(self):
        client = LiteApiClient(api_key="fake")
        with patch.object(client, "search_hotel_offers", side_effect=LiteApiError("500 boom")):
            result = check_hotel_freshness(HOTEL, TRIP, client)
        self.assertFalse(result.still_confirmed)
        self.assertIn("500 boom", result.detail)

    def test_network_level_error_flagged_not_raised(self):
        # [REGRESSIONE — trovato con una vera chiamata dal vivo contro
        # api.liteapi.travel in questo ambiente sandbox: un ProxyError reale
        # (403 dal proxy di rete) faceva crashare l'intero controllo con un
        # traceback, perché `search_hotel_offers()` non avvolge i fallimenti
        # di rete in `LiteApiError` — il primo giro di questo modulo
        # catturava solo quel tipo, non un `requests.exceptions.ProxyError`
        # grezzo.
        client = LiteApiClient(api_key="fake")
        with patch.object(
            client, "search_hotel_offers",
            side_effect=requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden"),
        ):
            result = check_hotel_freshness(HOTEL, TRIP, client)
        self.assertFalse(result.still_confirmed)
        self.assertIn("403", result.detail)


class TestCheckPoiFreshness(unittest.TestCase):
    def test_poi_still_present_confirmed(self):
        with patch("src.freshness_check.search_nearby", return_value=[POI_OK]):
            result = check_poi_freshness(POI_OK, google_maps_key="fake")
        self.assertTrue(result.still_confirmed)

    def test_poi_missing_flagged_not_as_certainly_closed(self):
        with patch("src.freshness_check.search_nearby", return_value=[]):
            result = check_poi_freshness(POI_MISSING, google_maps_key="fake")
        self.assertFalse(result.still_confirmed)
        # Onestà: non deve affermare "chiuso" come fatto certo.
        self.assertIn("potrebbe essere chiuso", result.detail)


class TestRunFreshnessCheck(unittest.TestCase):
    def test_checks_only_used_poi_and_all_hotels(self):
        itinerary = {
            "days": [{"day": 1, "blocks": [
                {"poi_id": "P1"},
                {"poi_id": None},  # [SLOT LIBERO] — non verificabile, ignorato correttamente
            ]}],
        }
        api_payload = ApiPayload(hotels=[HOTEL], travel_times=[], poi=[POI_OK, POI_MISSING])
        with patch("src.freshness_check.search_nearby", return_value=[POI_OK]), \
             patch.object(LiteApiClient, "search_hotel_offers", return_value=[{"hotelId": "H1"}]):
            report = run_freshness_check(itinerary, api_payload, TRIP, google_maps_key="fake", liteapi_key="fake")
        # Solo P1 (usato) + l'hotel, MAI P2 (mai scelto da Claude nell'itinerario).
        checked_ids = {item.id for item in report.items}
        self.assertIn("H1", checked_ids)
        self.assertIn("P1", checked_ids)
        self.assertNotIn("P2", checked_ids)
        self.assertTrue(report.all_confirmed)

    def test_report_summary_flags_unconfirmed_items(self):
        report = FreshnessReport(items=[])
        from src.freshness_check import FreshnessItemResult
        report.items.append(FreshnessItemResult("H1", "Hotel Test", "hotel", False, "sparito"))
        self.assertFalse(report.all_confirmed)
        self.assertIn("⚠️", report.summary())


if __name__ == "__main__":
    unittest.main()
