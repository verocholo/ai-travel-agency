import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.places_client import (
    map_places_response, fetch_nearby_raw, search_nearby, _DEFAULT_INCLUDED_TYPES,
    _normalize_price_level,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "mock_api_responses"


class TestMapPlacesResponse(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((FIXTURES / "places_response.json").read_text())

    def test_maps_all_places(self):
        pois = map_places_response(self.data)
        self.assertEqual(len(pois), 3)
        self.assertEqual({p.id for p in pois}, {"POI1", "POI2", "POI3"})

    def test_energy_tag_lookup(self):
        pois = {p.id: p for p in map_places_response(self.data)}
        self.assertEqual(pois["POI1"].energy_tag, "LOW")  # restaurant -> LOW
        self.assertEqual(pois["POI2"].energy_tag, "LOW")  # spa -> LOW
        self.assertEqual(pois["POI3"].energy_tag, "LOW")  # museum -> LOW

    def test_specific_food_subtype_recognized_not_defaulted(self):
        # [AGGIUNTO 2026-07-10] Caso reale osservato su San Quirico d'Orcia:
        # una pizzeria è tornata con primaryType="pizza_restaurant", non
        # "restaurant" — prima di espandere le tabelle finiva nel default
        # (type=activity, energy_tag=MEDIUM) invece che restaurant/LOW.
        data = {"places": [{
            "id": "PIZZA1", "displayName": {"text": "Pizzeria Bar"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "pizza_restaurant",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.type, "restaurant")
        self.assertEqual(poi.energy_tag, "LOW")

    def test_specific_culture_subtype_recognized_as_museum(self):
        data = {"places": [{
            "id": "CASTLE1", "displayName": {"text": "Castello"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "castle",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.type, "museum")
        self.assertEqual(poi.energy_tag, "LOW")

    def test_specific_shopping_subtype_recognized_as_shopping(self):
        # [AGGIUNTO 2026-07-13 (ter) — categoria shopping, confermata come
        # miglioramento generale di prodotto via AskUserQuestion] Stessa
        # verifica già fatta per food/culture: un tipo specifico della
        # tassonomia ufficiale "Shopping" (vedi
        # places_client.py::_SHOPPING_TYPES) deve normalizzare a
        # type="shopping" con energy_tag="MEDIUM", non cadere nel
        # fallback generico "activity".
        data = {"places": [{
            "id": "SHOP1", "displayName": {"text": "Bottega di souvenir"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "gift_shop",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.type, "shopping")
        self.assertEqual(poi.energy_tag, "MEDIUM")

    def test_shopping_mall_recognized_as_shopping(self):
        data = {"places": [{
            "id": "SHOP2", "displayName": {"text": "Centro commerciale"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "shopping_mall",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.type, "shopping")
        self.assertEqual(poi.energy_tag, "MEDIUM")

    def test_utility_store_deliberately_not_recognized_as_shopping(self):
        # Difesa in profondità del confine deliberatamente curato: un
        # negozio di uso quotidiano/utilitario (vedi la nota di esclusione
        # in places_client.py) NON deve normalizzare a "shopping" — resta
        # nel fallback generico "activity", energy_tag MEDIUM di default.
        data = {"places": [{
            "id": "HW1", "displayName": {"text": "Ferramenta"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "hardware_store",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.type, "activity")

    def test_unknown_primary_type_defaults_medium(self):
        data = {
            "places": [{
                "id": "X1", "displayName": {"text": "Boh"},
                "location": {"latitude": 1.0, "longitude": 2.0},
                "primaryType": "some_unknown_type",
            }]
        }
        pois = map_places_response(data)
        self.assertEqual(pois[0].energy_tag, "MEDIUM")

    def test_deli_recognized_not_defaulted(self):
        # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] "deli" era l'unico
        # sottotipo mancante su ~165 nella tabella ufficiale "Food and
        # Drink" (trovato per confronto diretto con la tassonomia Google) —
        # stesso tipo di gap già chiuso per "pizza_restaurant".
        data = {"places": [{
            "id": "DELI1", "displayName": {"text": "Salumeria"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "deli",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.type, "restaurant")
        self.assertEqual(poi.energy_tag, "LOW")

    def test_malformed_place_missing_id_is_skipped_not_a_crash(self):
        # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Un solo place
        # malformato nella risposta (manca "id" o "location") faceva
        # fallire con un KeyError grezzo l'INTERA chiamata — ora viene
        # scartato singolarmente, il resto del batch resta utilizzabile.
        data = {"places": [
            {"displayName": {"text": "Senza id"}, "location": {"latitude": 1.0, "longitude": 2.0}},
            {"id": "GOOD1", "displayName": {"text": "Ok"}, "location": {"latitude": 1.0, "longitude": 2.0}},
        ]}
        pois = map_places_response(data)
        self.assertEqual(len(pois), 1)
        self.assertEqual(pois[0].id, "GOOD1")

    def test_malformed_place_missing_location_is_skipped_not_a_crash(self):
        data = {"places": [
            {"id": "BAD1", "displayName": {"text": "Senza location"}},
            {"id": "GOOD1", "displayName": {"text": "Ok"}, "location": {"latitude": 1.0, "longitude": 2.0}},
        ]}
        pois = map_places_response(data)
        self.assertEqual(len(pois), 1)
        self.assertEqual(pois[0].id, "GOOD1")

    def test_open_days_mapping_dow(self):
        pois = {p.id: p for p in map_places_response(self.data)}
        # POI1: periods su day 2,3,4,5,6 -> Tue,Wed,Thu,Fri,Sat
        self.assertEqual(pois["POI1"].open_days, ["Fri", "Sat", "Thu", "Tue", "Wed"])

    def test_dietary_tags_vegetarian(self):
        pois = {p.id: p for p in map_places_response(self.data)}
        self.assertIn("vegetarian_verified:true", pois["POI1"].dietary_tags)
        self.assertEqual(pois["POI2"].dietary_tags, [])

    def test_missing_opening_hours_gives_empty_open_days(self):
        data = {"places": [{
            "id": "X2", "displayName": {"text": "Senza orari"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "restaurant",
        }]}
        pois = map_places_response(data)
        self.assertEqual(pois[0].open_days, [])

    def test_water_park_is_energy_high(self):
        # [AGGIUNTO 2026-07-11] Modulo "famiglia_con_bambini" — stesso
        # principio del test tennis_court sopra, ora sulle categorie
        # "Entertainment and Recreation" per famiglie.
        data = {"places": [{
            "id": "WPARK1", "displayName": {"text": "Acquapark"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "water_park",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.energy_tag, "HIGH")

    def test_picnic_ground_is_energy_low(self):
        data = {"places": [{
            "id": "PICNIC1", "displayName": {"text": "Area Picnic"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "picnic_ground",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.energy_tag, "LOW")

    def test_coworking_space_is_energy_low(self):
        # [AGGIUNTO 2026-07-11] Modulo "lavoro_nomadi_digitali".
        data = {"places": [{
            "id": "COWORK1", "displayName": {"text": "Spazio Coworking Centrale"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "coworking_space",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.energy_tag, "LOW")

    def test_tennis_court_is_energy_high(self):
        # [AGGIUNTO 2026-07-11] Prima del modulo "sport_active_travel" questo
        # primaryType non compariva mai nei dati reali (includedTypes non lo
        # richiedeva) — ora che è richiedibile, deve mappare a energy_tag=HIGH,
        # non al default MEDIUM.
        data = {"places": [{
            "id": "COURT1", "displayName": {"text": "Circolo Tennis"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "tennis_court",
        }]}
        poi = map_places_response(data)[0]
        self.assertEqual(poi.energy_tag, "HIGH")

    def test_price_level_mapped_from_fixture(self):
        # [AGGIUNTO 2026-07-12 — richiesta di Lorenzo: "segnare ogni
        # costo"] La fixture reale già include `priceLevel` per ciascun
        # place (mai sfruttato finora) — verifica che ora arrivi
        # correttamente normalizzato su ogni POI mappato.
        pois = {p.id: p for p in map_places_response(self.data)}
        self.assertEqual(pois["POI1"].price_level, "MODERATE")
        self.assertEqual(pois["POI2"].price_level, "MODERATE")
        self.assertEqual(pois["POI3"].price_level, "INEXPENSIVE")


class TestNormalizePriceLevel(unittest.TestCase):
    """[AGGIUNTO 2026-07-12] `_normalize_price_level()` — valori enum
    verificati sulla documentazione ufficiale Places API (New), non
    ipotizzati a mano (stesso rigore delle tabelle primaryType sopra)."""

    def test_strips_prefix_for_all_valid_enum_values(self):
        for suffix in ("FREE", "INEXPENSIVE", "MODERATE", "EXPENSIVE", "VERY_EXPENSIVE"):
            self.assertEqual(_normalize_price_level(f"PRICE_LEVEL_{suffix}"), suffix)

    def test_unspecified_becomes_none(self):
        self.assertIsNone(_normalize_price_level("PRICE_LEVEL_UNSPECIFIED"))

    def test_missing_field_becomes_none(self):
        self.assertIsNone(_normalize_price_level(None))

    def test_empty_string_becomes_none(self):
        self.assertIsNone(_normalize_price_level(""))

    def test_unrecognized_value_becomes_none_not_passed_through(self):
        # Difensivo: se Google introducesse un nuovo valore enum domani, non
        # vogliamo propagare una stringa non riconosciuta al cliente finale
        # senza controllo — meglio "non specificato" che un valore ignoto.
        self.assertIsNone(_normalize_price_level("PRICE_LEVEL_SOMETHING_NEW"))

    def test_map_places_response_defaults_to_none_when_field_absent(self):
        data = {"places": [{
            "id": "NOPRICE1", "displayName": {"text": "Posto Senza Prezzo"},
            "location": {"latitude": 1.0, "longitude": 2.0},
            "primaryType": "park",
        }]}
        poi = map_places_response(data)[0]
        self.assertIsNone(poi.price_level)


class TestFetchNearbyRawIncludedTypes(unittest.TestCase):
    """[AGGIUNTO 2026-07-11] fetch_nearby_raw()/search_nearby() ora accettano
    included_types esplicito (modulo verticale, src/modules.py) invece delle
    4 categorie hardcoded — verifica che il body della richiesta le usi
    davvero, e che l'omissione mantenga il comportamento originale
    (nessuna rottura per i chiamanti esistenti)."""

    @patch("src.places_client.requests.post")
    def test_custom_included_types_used_in_request_body(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"places": []})
        custom_types = ["restaurant", "tennis_court", "gym"]
        fetch_nearby_raw(1.0, 2.0, "fake-key", included_types=custom_types)
        sent_body = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_body["includedTypes"], custom_types)

    @patch("src.places_client.requests.post")
    def test_default_included_types_when_omitted(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"places": []})
        fetch_nearby_raw(1.0, 2.0, "fake-key")
        sent_body = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_body["includedTypes"], _DEFAULT_INCLUDED_TYPES)

    @patch("src.places_client.requests.post")
    def test_search_nearby_passes_through_included_types(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"places": []})
        custom_types = ["tennis_court"]
        search_nearby(1.0, 2.0, "fake-key", included_types=custom_types)
        sent_body = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_body["includedTypes"], custom_types)


if __name__ == "__main__":
    unittest.main()
