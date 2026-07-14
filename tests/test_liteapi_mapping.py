import json
import unittest
from pathlib import Path
from unittest.mock import patch
from src.liteapi_client import (
    select_anchor_hotel, _extract_total_price, LiteApiError,
    LiteApiClient, DEFAULT_HOTEL_TYPE_IDS, _HOTEL_TYPE_NAMES,
    HOTEL_RATES_URL,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "mock_api_responses"


class TestSelectAnchorHotel(unittest.TestCase):
    def setUp(self):
        self.hotels_geo = json.loads((FIXTURES / "liteapi_hotels_by_geocode.json").read_text())["data"]
        self.offers = json.loads((FIXTURES / "liteapi_hotel_rates.json").read_text())["data"]

    def test_selects_only_one_hotel_by_default(self):
        # Nodo 4 hard-cap: 1 SOLO hotel-ancora (decisione Lorenzo, invariata dalla migrazione)
        result = select_anchor_hotel(self.hotels_geo, self.offers, dest_lat=43.07, dest_lng=11.61,
                                      duration_days=3)
        self.assertEqual(len(result), 1)

    def test_picks_most_baricentric_hotel(self):
        # H1 è più vicino a (43.07, 11.61) di H2 nei dati mock -> deve vincere H1
        result = select_anchor_hotel(self.hotels_geo, self.offers, dest_lat=43.07, dest_lng=11.61,
                                      duration_days=3)
        self.assertEqual(result[0].id, "H1")

    def test_price_per_night_computed_correctly(self):
        result = select_anchor_hotel(self.hotels_geo, self.offers, dest_lat=43.07, dest_lng=11.61,
                                      duration_days=3)
        # H1 offer totale 2450.00 / 3 notti = 816.67
        self.assertAlmostEqual(result[0].price_night_eur, 816.67, places=2)

    def test_empty_offers_propagates_empty_list_no_invention(self):
        # HARD_CONSTRAINT: mai inventare hotel — array vuoto propagato as-is
        result = select_anchor_hotel(self.hotels_geo, [], dest_lat=43.07, dest_lng=11.61, duration_days=3)
        self.assertEqual(result, [])

    def test_max_hotels_param_expandable(self):
        # verifica che il cap sia parametrico (per l'opzione futura "2 hotel-ancora")
        result = select_anchor_hotel(self.hotels_geo, self.offers, dest_lat=43.07, dest_lng=11.61,
                                      duration_days=3, max_hotels=2)
        self.assertEqual(len(result), 2)

    def test_missing_geocode_entry_skipped_not_invented(self):
        # hotelId nella risposta rates ma assente da hotels_by_geocode -> scartato, non inventato
        offers = [{"hotelId": "H999", "roomTypes": [{"rates": [{"retailRate": {"total": {"amount": 100}}}]}]}]
        result = select_anchor_hotel(self.hotels_geo, offers, dest_lat=43.07, dest_lng=11.61, duration_days=3)
        self.assertEqual(result, [])

    def test_geocode_entry_missing_id_field_is_skipped_not_a_crash(self):
        # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Un'entry di
        # hotels_by_geocode senza il campo "id" faceva crashare con un
        # KeyError grezzo l'INTERA selezione (indicizzazione diretta
        # h["id"]) — inconsistente con la filosofia difensiva del resto
        # di questa stessa funzione. Ora quell'unica entry malformata viene
        # scartata, il resto della selezione funziona normalmente.
        hotels_geo_with_bad_entry = self.hotels_geo + [{"name": "Hotel senza id", "latitude": 1.0, "longitude": 2.0}]
        result = select_anchor_hotel(hotels_geo_with_bad_entry, self.offers, dest_lat=43.07, dest_lng=11.61,
                                      duration_days=3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "H1")

    def test_longitude_compression_correction_picks_the_real_closest_hotel(self):
        # [AGGIUNTO 2026-07-12 — bug reale trovato in audit di qualità]
        # 1° di longitudine misura ~111km * cos(lat) sul terreno, non
        # ~111km come un grado di latitudine — un calcolo grezzo che
        # tratta i due assi come equivalenti sceglie l'hotel-ancora
        # SBAGLIATO quando i candidati sono offset soprattutto in
        # longitudine rispetto alla destinazione. Qui: dest=(44.0, 11.0).
        # H1 è 0.007° a nord (nessun offset in longitudine) -> ~777m reali.
        # H2 è 0.009° a est (nessun offset in latitudine) -> a 44°N, un
        # grado di longitudine è compresso di cos(44°)≈0.719, quindi H2 è
        # in realtà a ~719m, PIÙ VICINO di H1. Senza la correzione
        # cos(lat), il confronto grezzo dei gradi (0.007² < 0.009²)
        # sceglierebbe erroneamente H1.
        hotels_geo = [
            {"id": "H1", "name": "Hotel Nord", "latitude": 44.007, "longitude": 11.0},
            {"id": "H2", "name": "Hotel Est", "latitude": 44.0, "longitude": 11.009},
        ]
        result = select_anchor_hotel(hotels_geo, self.offers, dest_lat=44.0, dest_lng=11.0, duration_days=3)
        self.assertEqual(result[0].id, "H2")


class TestPropertyTypeMapping(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-11 — richiesta di prodotto di Lorenzo: espandere
    oltre Booking/hotel classici] Copre il nuovo campo `Hotel.property_type`
    popolato da `hotelTypeId` — vedi la nota estesa in liteapi_client.py per
    il razionale completo (confermato dal vivo su Lisbona: 20/20 candidati
    reali per Apartments quando richiesti esplicitamente).
    """

    def setUp(self):
        self.offers = json.loads((FIXTURES / "liteapi_hotel_rates.json").read_text())["data"]

    def test_known_hotel_type_id_mapped_to_readable_name(self):
        hotels_geo = [
            {"id": "H1", "name": "Lisbon Art Stay Apartments", "latitude": 43.072, "longitude": 11.612,
             "stars": 0, "hotelTypeId": 201},
        ]
        result = select_anchor_hotel(hotels_geo, self.offers, dest_lat=43.07, dest_lng=11.61, duration_days=3)
        self.assertEqual(result[0].property_type, "Apartments")

    def test_hotels_type_id_mapped_correctly_too(self):
        hotels_geo = [
            {"id": "H1", "name": "Some Hotel", "latitude": 43.072, "longitude": 11.612,
             "stars": 4, "hotelTypeId": 204},
        ]
        result = select_anchor_hotel(hotels_geo, self.offers, dest_lat=43.07, dest_lng=11.61, duration_days=3)
        self.assertEqual(result[0].property_type, "Hotels")

    def test_missing_hotel_type_id_field_defaults_to_none_not_invented(self):
        # Copre anche le fixture/dati mock esistenti (mai aggiornati con
        # questo campo) — non deve far crashare né inventare un tipo.
        hotels_geo = json.loads((FIXTURES / "liteapi_hotels_by_geocode.json").read_text())["data"]
        result = select_anchor_hotel(hotels_geo, self.offers, dest_lat=43.07, dest_lng=11.61, duration_days=3)
        self.assertIsNone(result[0].property_type)

    def test_unknown_hotel_type_id_defaults_to_none_not_invented(self):
        hotels_geo = [
            {"id": "H1", "name": "Struttura Misteriosa", "latitude": 43.072, "longitude": 11.612,
             "stars": 3, "hotelTypeId": 999999},
        ]
        result = select_anchor_hotel(hotels_geo, self.offers, dest_lat=43.07, dest_lng=11.61, duration_days=3)
        self.assertIsNone(result[0].property_type)


class TestSearchHotelsByGeocodeTypeFilter(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-11] Copre il nuovo default `hotelTypeIds` passato da
    `search_hotels_by_geocode()` — prima la ricerca non filtrava mai per
    tipo, e su una ricerca reale a Lisbona questo restituiva 20/20 "Hotels"
    (LiteAPI privilegia gli hotel classici quando non gli si chiede
    esplicitamente altro), lasciando fuori appartamenti/ville/altro senza
    nessuna ragione tecnica.
    """

    def _fake_get(self, captured):
        def fake_get(url, headers, params, timeout):
            captured.update(params)
            class FakeResp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {"data": []}
            return FakeResp()
        return fake_get

    def test_default_call_includes_hotel_type_ids_filter(self):
        captured = {}
        client = LiteApiClient("fake-key")
        with patch("src.liteapi_client.requests.get", side_effect=self._fake_get(captured)):
            client.search_hotels_by_geocode(43.07, 11.61)
        self.assertIn("hotelTypeIds", captured)
        expected = ",".join(str(t) for t in DEFAULT_HOTEL_TYPE_IDS)
        self.assertEqual(captured["hotelTypeIds"], expected)

    def test_explicit_none_omits_filter_for_backward_compat(self):
        # Uso esplicito da debug_liteapi_property_types.py per confrontare
        # col comportamento pre-2026-07-11 (nessun filtro).
        captured = {}
        client = LiteApiClient("fake-key")
        with patch("src.liteapi_client.requests.get", side_effect=self._fake_get(captured)):
            client.search_hotels_by_geocode(43.07, 11.61, hotel_type_ids=None)
        self.assertNotIn("hotelTypeIds", captured)

    def test_default_hotel_type_ids_includes_hotels_for_backward_compat(self):
        # 204 = "Hotels" deve restare sempre incluso: comportamento
        # preesistente (prima di questo fix, la pipeline trovava SOLO
        # hotel) non deve sparire, solo espandersi.
        self.assertIn(204, DEFAULT_HOTEL_TYPE_IDS)
        self.assertEqual(_HOTEL_TYPE_NAMES[204], "Hotels")

    def test_all_default_type_ids_resolve_to_known_names(self):
        # Nessun id nella lista di default deve essere sconosciuto alla
        # tabella di lookup — altrimenti property_type sarebbe sempre None
        # per quel tipo, silenziosamente.
        for type_id in DEFAULT_HOTEL_TYPE_IDS:
            self.assertIn(type_id, _HOTEL_TYPE_NAMES, f"hotelTypeId {type_id} non ha un nome noto")


class TestSearchHotelOffers(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — gap di copertura reale trovato nell'audit di
    potenziamento massimo] `LiteApiClient.search_hotel_offers()` era sempre
    mockato al confine (mai testato direttamente): nessun test verificava
    che il body POST fosse costruito correttamente (endpoint, header,
    hotelIds troncati a 50, checkin/checkout passati as-is), né il
    comportamento con una lista di hotel_ids vuota.
    """

    def _fake_post(self, captured, response_data=None):
        def fake_post(url, headers, json, timeout):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            class FakeResp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return response_data if response_data is not None else {"data": []}
            return FakeResp()
        return fake_post

    def test_empty_hotel_ids_returns_empty_list_without_http_call(self):
        client = LiteApiClient("fake-key")
        with patch("src.liteapi_client.requests.post") as mock_post:
            result = client.search_hotel_offers([], "2026-09-14", "2026-09-17")
        self.assertEqual(result, [])
        mock_post.assert_not_called()

    def test_posts_to_hotel_rates_url_with_api_key_header(self):
        captured = {}
        client = LiteApiClient("secret-key")
        with patch("src.liteapi_client.requests.post", side_effect=self._fake_post(captured)):
            client.search_hotel_offers(["H1", "H2"], "2026-09-14", "2026-09-17")
        self.assertEqual(captured["url"], HOTEL_RATES_URL)
        self.assertEqual(captured["headers"]["X-API-Key"], "secret-key")

    def test_body_includes_checkin_checkout_and_hotel_ids(self):
        captured = {}
        client = LiteApiClient("fake-key")
        with patch("src.liteapi_client.requests.post", side_effect=self._fake_post(captured)):
            client.search_hotel_offers(["H1", "H2"], "2026-09-14", "2026-09-17")
        self.assertEqual(captured["json"]["hotelIds"], ["H1", "H2"])
        self.assertEqual(captured["json"]["checkin"], "2026-09-14")
        self.assertEqual(captured["json"]["checkout"], "2026-09-17")

    def test_hotel_ids_truncated_to_50_same_safety_margin_as_before(self):
        captured = {}
        client = LiteApiClient("fake-key")
        many_ids = [f"H{i}" for i in range(75)]
        with patch("src.liteapi_client.requests.post", side_effect=self._fake_post(captured)):
            client.search_hotel_offers(many_ids, "2026-09-14", "2026-09-17")
        self.assertEqual(len(captured["json"]["hotelIds"]), 50)

    def test_returns_data_field_from_response(self):
        captured = {}
        client = LiteApiClient("fake-key")
        fake_data = {"data": [{"hotelId": "H1"}]}
        with patch("src.liteapi_client.requests.post", side_effect=self._fake_post(captured, fake_data)):
            result = client.search_hotel_offers(["H1"], "2026-09-14", "2026-09-17")
        self.assertEqual(result, [{"hotelId": "H1"}])


class TestExtractTotalPrice(unittest.TestCase):
    """
    test_list_of_dicts copre la forma CONFERMATA dal vivo [2026-07-10, 19/19
    hotel reali su Firenze, vedi nota in liteapi_client.py]: è quella che la
    pipeline incontrerà davvero. test_dict_with_amount e test_plain_number
    coprono forme MAI osservate dal vivo, tenute solo come fallback
    difensivo puro nel caso l'API cambi schema in futuro — il client deve
    comunque gestirle tutte, e fallire in modo esplicito se non le riconosce.
    """

    def test_dict_with_amount(self):
        entry = {"roomTypes": [{"rates": [{"retailRate": {"total": {"amount": 250.0, "currency": "EUR"}}}]}]}
        self.assertEqual(_extract_total_price(entry), 250.0)

    def test_plain_number(self):
        entry = {"roomTypes": [{"rates": [{"retailRate": {"total": 250.0}}]}]}
        self.assertEqual(_extract_total_price(entry), 250.0)

    def test_list_of_dicts(self):
        # Forma reale confermata dal vivo — vedi docstring della classe.
        entry = {"roomTypes": [{"rates": [{"retailRate": {"total": [{"amount": 250.0, "currency": "EUR"}]}}]}]}
        self.assertEqual(_extract_total_price(entry), 250.0)

    def test_unrecognized_shape_raises_explicitly(self):
        entry = {"roomTypes": [{"rates": [{"retailRate": {"total": "gratis"}}]}]}
        with self.assertRaises(LiteApiError):
            _extract_total_price(entry)

    def test_missing_rates_raises(self):
        entry = {"roomTypes": [{"rates": []}]}
        with self.assertRaises(LiteApiError):
            _extract_total_price(entry)


if __name__ == "__main__":
    unittest.main()
