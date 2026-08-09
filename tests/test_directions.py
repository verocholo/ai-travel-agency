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
    ALTERNATIVE_MODE_MIN_MINUTES, DEPARTURE_BUFFER_MINUTES,
    build_directions_by_day, build_directions_url, build_day_legs,
    build_travel_time_lookup, compute_departure_time, travel_mode_label,
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

    def test_le_tratte_nominano_i_posti_non_gli_indirizzi(self):
        """[AGGIUNTO 2026-08-02 — difetto visto rigenerando il campione con un
        payload completo] Il nome della tappa veniva letto da `location`, che
        nei blocchi veri è l'indirizzo o — peggio — il nome nudo della città:
        uscivano «1 → 2  Siena → Piazza del Campo 1» e «2 → 3  Piazza del Duomo
        1 → Siena», dove lo stesso posto compare una volta col nome e una volta
        con la via, e la città fa da tappa. Una riga "come arrivare" risponde a
        una domanda sola — da DOVE a DOVE — e servono due nomi propri."""
        itinerary = {"days": [{"day": 1, "title": "Centro", "blocks": [
            {"time": "09:00", "activity": "Colazione in hotel", "poi_id": "H1"},
            {"time": "10:00", "activity": "Visita agli Uffizi",
             "location": "Piazzale degli Uffizi 6", "poi_id": "P1"},
            {"time": "13:00", "activity": "Pranzo", "location": "Firenze", "poi_id": "P2"},
        ]}]}
        plan = build_day_map_plans([HOTEL], [MUSEO, RISTORANTE], itinerary)[0]
        legs = build_day_legs(plan, {})
        coppie = [(leg["from_name"], leg["to_name"]) for leg in legs]
        self.assertEqual(coppie, [
            ("Hotel Duomo", "Uffizi"),
            ("Uffizi", "Trattoria"),
            ("Trattoria", "Hotel Duomo"),
        ])
        # Né l'indirizzo né il nome della città possono comparire come tappa.
        piatto = " ".join(n for coppia in coppie for n in coppia)
        self.assertNotIn("Piazzale degli Uffizi", piatto)
        self.assertNotIn("Firenze", piatto)

    def test_senza_nome_le_tratte_ripiegano_invece_di_restare_mute(self):
        """Il ripiego resta, nell'ordine giusto: meglio una frase di un
        indirizzo, meglio un indirizzo di una freccia senza capo né coda."""
        plan = _plan()
        plan["stops"][0].pop("name")
        self.assertEqual(build_day_legs(plan, {})[0]["to_name"], "Visita agli Uffizi")
        plan["stops"][0]["activity"] = ""
        self.assertEqual(build_day_legs(plan, {})[0]["to_name"], "Uffizi")

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


class TestOraDiPartenza(unittest.TestCase):
    """[AGGIUNTO 2026-08-01 — "semplificargli la vita e togliergli piu' lavoro
    possibile"] Il PDF sapeva gia' che l'attivita' comincia alle 11:00 e che il
    tragitto dura 18 minuti. La sottrazione la faceva il cliente, in strada.
    Ora la facciamo noi: nessun dato nuovo, nessuna chiamata, zero costo."""

    def test_sottrae_durata_e_margine(self):
        self.assertEqual(compute_departure_time("11:00", 18), "10:37")

    def test_il_margine_esiste_e_non_e_zero(self):
        """Senza margine l'ora sarebbe sistematicamente ottimistica: la
        Distance Matrix misura porta-a-porta, non il tempo di finire il caffe'
        e capire da che parte girare."""
        self.assertGreaterEqual(DEPARTURE_BUFFER_MINUTES, 1)
        self.assertEqual(
            compute_departure_time("11:00", 18, buffer_minutes=0), "10:42"
        )

    def test_accetta_un_intervallo_orario_e_usa_linizio(self):
        self.assertEqual(compute_departure_time("11:00-13:00", 10), "10:45")

    def test_senza_misura_reale_nessun_orario_inventato(self):
        self.assertIsNone(compute_departure_time("11:00", None))
        self.assertIsNone(compute_departure_time("11:00", "dieci"))
        self.assertIsNone(compute_departure_time("11:00", True))

    def test_senza_orario_di_arrivo_nessun_orario_inventato(self):
        self.assertIsNone(compute_departure_time("", 10))
        self.assertIsNone(compute_departure_time("mattina", 10))
        self.assertIsNone(compute_departure_time("25:00", 10))

    def test_scavalcare_la_mezzanotte_non_produce_un_orario_confuso(self):
        self.assertIsNone(compute_departure_time("00:10", 30))


class TestAlternativaColMezzo(unittest.TestCase):
    """Sopra la soglia il cliente merita di sapere in un tap se due fermate di
    metro gli risparmiano quaranta minuti a piedi."""

    def test_tragitto_lungo_offre_lalternativa_coi_mezzi(self):
        plan = _plan()
        lungo = [TravelTime(origin_id="H1", dest_id="P1",
                            minutes=ALTERNATIVE_MODE_MIN_MINUTES + 5, mode="walking")]
        leg = build_day_legs(plan, build_travel_time_lookup(lungo))[0]
        self.assertEqual(leg["alt_mode"], "transit")
        self.assertIn("travelmode=transit", leg["alt_url"])
        self.assertIn("mezzi", leg["alt_mode_label"])

    def test_tragitto_breve_non_aggiunge_rumore(self):
        leg = build_day_legs(_plan(), build_travel_time_lookup(TRAVEL_TIMES))[0]
        self.assertIsNone(leg["alt_mode"])
        self.assertIsNone(leg["alt_url"])

    def test_senza_misura_nessuna_alternativa_arbitraria(self):
        leg = build_day_legs(_plan(), {})[0]
        self.assertIsNone(leg["minutes"])
        self.assertIsNone(leg["alt_url"])

    def test_lora_di_partenza_finisce_nel_leg(self):
        legs = build_day_legs(_plan(), build_travel_time_lookup(TRAVEL_TIMES))
        museo = [l for l in legs if l["to_name"] == "Uffizi"][0]
        self.assertEqual(museo["depart_by"], "09:51")


if __name__ == "__main__":
    unittest.main()
