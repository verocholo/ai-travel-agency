"""
[AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "manca anche la parte 'cartina e
come arrivare' in cui spieghi spostamento per spostamento come arrivare"]
Copre src/directions.py.

Nessuna rete: gli URL prodotti sono deep link pubblici documentati (Google
Maps URLs API) e i minuti provengono SOLO da misure reali della Distance
Matrix già in payload — `None` quando non le abbiamo. Il test
`test_minuti_mai_inventati` è il contratto di onestà di questo modulo.
"""
import unittest
from urllib.parse import parse_qs, urlparse

from src.directions import (
    build_directions_by_day, build_directions_url, build_day_legs,
    build_travel_time_lookup, travel_mode_label,
)
from src.maps_static import build_day_map_plans
from src.schemas import POI, Hotel, TravelTime

HOTEL = Hotel(id="H1", name="Hotel Duomo", lat=43.7731, lng=11.2560, price_night_eur=120.0)
MUSEO = POI(id="P1", type="museum", name="Uffizi", lat=43.7678, lng=11.2553)
RISTORANTE = POI(id="P2", type="restaurant", name="Trattoria", lat=43.7700, lng=11.2500)

ITINERARY = {"days": [{"day": 1, "title": "Centro", "blocks": [
    {"time": "09:00", "activity": "Colazione in hotel", "poi_id": "H1"},
    {"time": "10:00", "activity": "Visita agli Uffizi", "location": "Uffizi", "poi_id": "P1"},
    {"time": "13:00", "activity": "Pranzo", "location": "Trattoria", "poi_id": "P2"},
]}]}

TRAVEL_TIMES = [
    TravelTime(origin_id="H1", dest_id="P1", minutes=9, mode="walking"),
    TravelTime(origin_id="H1", dest_id="P1", minutes=4, mode="driving"),
    TravelTime(origin_id="P1", dest_id="P2", minutes=7, mode="walking"),
]


def _plan():
    return build_day_map_plans([HOTEL], [MUSEO, RISTORANTE], ITINERARY)[0]


class TestDirectionsUrl(unittest.TestCase):
    def test_url_ben_formato(self):
        url = build_directions_url((43.77, 11.25), (43.76, 11.26), "walking")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertIn("google.com/maps/dir", url)
        self.assertEqual(query["origin"], ["43.77,11.25"])
        self.assertEqual(query["destination"], ["43.76,11.26"])
        self.assertEqual(query["travelmode"], ["walking"])

    def test_modo_sconosciuto_ricade_su_a_piedi(self):
        url = build_directions_url((43.77, 11.25), (43.76, 11.26), "teletrasporto")
        self.assertIn("travelmode=walking", url)

    def test_coordinate_non_valide_danno_none_non_un_link_rotto(self):
        for origin, dest in (((None, None), (43.0, 11.0)), (("a", "b"), (43.0, 11.0)),
                             (None, (43.0, 11.0)), ((43.0, 11.0), None)):
            with self.subTest(origin=origin):
                self.assertIsNone(build_directions_url(origin, dest, "walking"))

    def test_nessuna_chiave_api_nell_url(self):
        url = build_directions_url((43.77, 11.25), (43.76, 11.26), "walking")
        self.assertNotIn("key=", url)


class TestTravelModeLabel(unittest.TestCase):
    def test_etichette_italiane(self):
        self.assertEqual(travel_mode_label("walking"), "a piedi")
        self.assertEqual(travel_mode_label("driving"), "in auto")

    def test_modo_ignoto_etichettato_comunque(self):
        self.assertTrue(travel_mode_label(None))
        self.assertTrue(travel_mode_label("qualcosa"))


class TestTravelTimeLookup(unittest.TestCase):
    def test_tiene_la_misura_piu_breve(self):
        lookup = build_travel_time_lookup(TRAVEL_TIMES)
        self.assertEqual(lookup[("H1", "P1")]["minutes"], 4)
        self.assertEqual(lookup[("H1", "P1")]["mode"], "driving")

    def test_input_malformati_ignorati_senza_sollevare(self):
        class Bad:
            origin_id, dest_id, minutes, mode = 1, None, "molti", None
        lookup = build_travel_time_lookup([Bad(), None, "x"])
        self.assertEqual(lookup, {})

    def test_none_accettato(self):
        self.assertEqual(build_travel_time_lookup(None), {})


class TestDayLegs(unittest.TestCase):
    def test_catena_hotel_tappe_hotel(self):
        legs = build_day_legs(_plan(), build_travel_time_lookup(TRAVEL_TIMES))
        self.assertEqual(
            [(leg["from_label"], leg["to_label"]) for leg in legs],
            [("H", "1"), ("1", "2"), ("2", "H")],
        )

    def test_etichette_coincidono_con_i_numeri_della_cartina(self):
        plan = _plan()
        legs = build_day_legs(plan, {})
        map_labels = [stop["label"] for stop in plan["stops"]]
        self.assertEqual(map_labels, ["1", "2"])
        self.assertTrue(all(leg["to_label"] in map_labels + ["H"] for leg in legs))

    def test_nomi_leggibili_mai_id_grezzi(self):
        legs = build_day_legs(_plan(), {})
        for leg in legs:
            self.assertNotIn("P1", leg["to_name"])
            self.assertNotIn("H1", leg["from_name"])
        self.assertEqual(legs[0]["from_name"], "Hotel Duomo")

    def test_minuti_mai_inventati(self):
        # senza misure, `minutes` è None — non una stima plausibile.
        legs = build_day_legs(_plan(), {})
        self.assertTrue(all(leg["minutes"] is None for leg in legs))

    def test_misura_reale_usata_quando_ce(self):
        legs = build_day_legs(_plan(), build_travel_time_lookup(TRAVEL_TIMES))
        self.assertEqual(legs[0]["minutes"], 4)
        self.assertEqual(legs[1]["minutes"], 7)

    def test_direzione_inversa_usata_come_ripiego(self):
        lookup = build_travel_time_lookup([
            TravelTime(origin_id="P2", dest_id="H1", minutes=11, mode="walking")
        ])
        legs = build_day_legs(_plan(), lookup)
        self.assertEqual(legs[-1]["minutes"], 11)

    def test_orario_di_arrivo_riportato(self):
        legs = build_day_legs(_plan(), {})
        self.assertEqual(legs[0]["arrival_time"], "10:00")

    def test_ogni_leg_ha_un_link_cliccabile(self):
        for leg in build_day_legs(_plan(), {}):
            self.assertIn("google.com/maps/dir", leg["url"])

    def test_senza_hotel_la_catena_parte_dalla_prima_tappa(self):
        plan = _plan()
        plan["hotel_point"] = None
        legs = build_day_legs(plan, {})
        self.assertEqual([(l["from_label"], l["to_label"]) for l in legs], [("1", "2")])

    def test_plan_vuoto_o_malformato_non_solleva(self):
        for plan in ({}, {"stops": None}, {"stops": [{}]}, {"stops": [{"point": None}]}):
            with self.subTest(plan=plan):
                self.assertIsInstance(build_day_legs(plan, {}), list)


class TestDirectionsByDay(unittest.TestCase):
    def test_una_voce_per_giorno(self):
        plans = build_day_map_plans([HOTEL], [MUSEO, RISTORANTE], ITINERARY)
        result = build_directions_by_day(plans, TRAVEL_TIMES)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["day"], 1)
        self.assertEqual(result[0]["title"], "Centro")
        self.assertEqual(len(result[0]["legs"]), 3)

    def test_input_malformati_non_sollevano(self):
        self.assertEqual(build_directions_by_day(None), [])
        self.assertEqual(build_directions_by_day([None, "x"]), [])


if __name__ == "__main__":
    unittest.main()
