"""
[AGGIUNTO 2026-07-31 — richiesta di Lorenzo: "manca la parte della stima dei
costi e dettaglio budget"] Copre src/cost_estimator.py.

Tutte funzioni pure e deterministiche: nessun mock, nessuna rete, nessun LLM.
È il punto: il numero su cui il cliente decide quanto contante portare non è
generato, è calcolato — e quindi è verificabile riga per riga anche da qui.
"""
import unittest

from src.cost_estimator import (
    _ACTIVITY_BANDS_EUR, _MEAL_BANDS_EUR, count_nights, estimate_costs,
)
from src.schemas import Hotel, POI, Trip


def _trip(**overrides):
    base = dict(
        email="cliente@example.com", destination="Firenze, Italia",
        date_start="2026-06-20", date_end="2026-06-23", duration_days=3,
        budget_eur=1000.0, budget_mode="LIMITED", objective_function="BALANCED",
    )
    base.update(overrides)
    return Trip(**base)


HOTEL = Hotel(id="H1", name="Hotel Duomo", lat=43.77, lng=11.25, price_night_eur=120.0)
RISTORANTE = POI(id="R1", type="restaurant", name="Trattoria", lat=43.77, lng=11.25,
                 price_level="MODERATE")
RISTORANTE_IGNOTO = POI(id="R2", type="restaurant", name="Osteria", lat=43.77, lng=11.25)
MUSEO = POI(id="M1", type="museum", name="Uffizi", lat=43.76, lng=11.25, price_level="MODERATE")
PIAZZA = POI(id="A1", type="plaza", name="Piazza della Signoria", lat=43.76, lng=11.25)


def _itinerary(*poi_ids_per_day):
    return {"days": [
        {"day": index + 1, "blocks": [
            {"time": "10:00", "activity": f"attività {poi_id}", "poi_id": poi_id}
            for poi_id in day
        ]}
        for index, day in enumerate(poi_ids_per_day)
    ]}


class TestCountNights(unittest.TestCase):
    def test_notti_corrette(self):
        self.assertEqual(count_nights("2026-06-20", "2026-06-23"), 3)

    def test_date_invertite_o_uguali_danno_none(self):
        self.assertIsNone(count_nights("2026-06-23", "2026-06-20"))
        self.assertIsNone(count_nights("2026-06-20", "2026-06-20"))

    def test_date_non_valide_danno_none_non_un_numero_arbitrario(self):
        for bad in (None, "", "domani", 42, "2026-13-01"):
            with self.subTest(bad=bad):
                self.assertIsNone(count_nights(bad, "2026-06-23"))

    def test_timestamp_iso_completo_accettato(self):
        self.assertEqual(count_nights("2026-06-20T14:00:00", "2026-06-22T09:00:00"), 2)


class TestLodging(unittest.TestCase):
    def test_alloggio_e_prezzo_reale_moltiplicato_per_le_notti(self):
        result = estimate_costs(_itinerary([]), _trip(), [HOTEL], [])
        line = result["lines"][0]
        self.assertEqual(line["category"], "lodging")
        self.assertEqual(line["min_eur"], 360.0)
        self.assertEqual(line["max_eur"], 360.0)  # prezzo esatto: min == max
        self.assertTrue(line["known"])

    def test_hotel_senza_prezzo_marcato_da_verificare_e_fuori_totale(self):
        hotel = Hotel(id="H2", name="Hotel X", lat=43.0, lng=11.0)
        result = estimate_costs(_itinerary([]), _trip(), [hotel], [])
        self.assertFalse(result["lines"][0]["known"])
        self.assertIn("[Da Verificare]", result["lines"][0]["detail"])
        self.assertEqual(result["total_max_eur"], 0.0)
        self.assertEqual(result["unknown_count"], 1)

    def test_senza_notti_certe_niente_costo_alloggio_certo(self):
        result = estimate_costs(_itinerary([]), _trip(date_end="2026-06-20"), [HOTEL], [])
        self.assertFalse(result["lines"][0]["known"])

    def test_hotel_dell_itinerario_non_conta_come_attivita(self):
        # il check-in in hotel è un blocco dell'itinerario: non deve generare
        # una seconda riga di costo oltre a quella dell'alloggio.
        itinerary = _itinerary(["H1", "M1"])
        result = estimate_costs(itinerary, _trip(), [HOTEL], [MUSEO])
        self.assertEqual(sum(1 for l in result["lines"] if l["category"] == "lodging"), 1)


class TestMealsAndActivities(unittest.TestCase):
    def test_fascia_di_prezzo_diventa_un_intervallo_non_un_numero(self):
        result = estimate_costs(_itinerary(["R1"]), _trip(), [], [RISTORANTE])
        line = result["lines"][0]
        self.assertEqual((line["min_eur"], line["max_eur"]), _MEAL_BANDS_EUR["MODERATE"])
        self.assertLess(line["min_eur"], line["max_eur"])

    def test_ristorante_ripetuto_conta_due_volte(self):
        result = estimate_costs(_itinerary(["R1"], ["R1"]), _trip(), [], [RISTORANTE])
        line = next(l for l in result["lines"] if l["category"] == "meals")
        self.assertEqual(line["min_eur"], _MEAL_BANDS_EUR["MODERATE"][0] * 2)
        self.assertIn("× 2", line["label"])

    def test_museo_ripetuto_conta_una_volta_sola(self):
        # il biglietto non si ricompra tornando la sera.
        result = estimate_costs(_itinerary(["M1"], ["M1"]), _trip(), [], [MUSEO])
        activities = [l for l in result["lines"] if l["category"] == "activities"]
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0]["min_eur"], float(_ACTIVITY_BANDS_EUR["MODERATE"][0]))

    def test_fascia_assente_esclusa_dal_totale(self):
        result = estimate_costs(_itinerary(["R1", "R2"]), _trip(), [], [RISTORANTE, RISTORANTE_IGNOTO])
        self.assertEqual(result["unknown_count"], 1)
        self.assertEqual(result["total_min_eur"], float(_MEAL_BANDS_EUR["MODERATE"][0]))

    def test_attivita_gratuita_non_gonfia_il_totale(self):
        # una piazza senza price_level NON diventa un costo inventato.
        result = estimate_costs(_itinerary(["A1"]), _trip(), [], [PIAZZA])
        self.assertEqual(result["total_max_eur"], 0.0)
        self.assertFalse(result["lines"][0]["known"])
        self.assertIn("gratuite", result["lines"][0]["detail"])

    def test_price_level_free_vale_zero_ed_e_un_dato_noto(self):
        free = POI(id="F1", type="museum", name="Museo civico", lat=43.0, lng=11.0, price_level="FREE")
        result = estimate_costs(_itinerary(["F1"]), _trip(), [], [free])
        self.assertTrue(result["lines"][0]["known"])
        self.assertEqual(result["lines"][0]["max_eur"], 0.0)

    def test_moltiplicatore_viaggiatori(self):
        one = estimate_costs(_itinerary(["R1"]), _trip(), [], [RISTORANTE])
        two = estimate_costs(_itinerary(["R1"]), _trip(), [], [RISTORANTE], travellers=2)
        self.assertEqual(two["total_max_eur"], one["total_max_eur"] * 2)
        self.assertIn("2 persone", two["lines"][0]["detail"])

    def test_viaggiatori_non_validi_ricadono_su_uno(self):
        for bad in (0, -3, None, True, "due"):
            with self.subTest(bad=bad):
                result = estimate_costs(_itinerary(["R1"]), _trip(), [], [RISTORANTE], travellers=bad)
                self.assertEqual(result["travellers"], 1)

    def test_poi_id_non_presente_nei_dati_viene_ignorato(self):
        result = estimate_costs(_itinerary(["FANTASMA"]), _trip(), [], [RISTORANTE])
        self.assertEqual(result["lines"], [])


class TestTotalsAndBudget(unittest.TestCase):
    def _full(self, **trip_overrides):
        return estimate_costs(
            _itinerary(["M1", "R1"], ["A1", "R1"]), _trip(**trip_overrides),
            [HOTEL], [RISTORANTE, MUSEO, PIAZZA],
        )

    def test_totali_per_categoria_coerenti_col_totale(self):
        result = self._full()
        self.assertAlmostEqual(
            sum(b["min_eur"] for b in result["totals_by_category"].values()),
            result["total_min_eur"],
        )
        self.assertGreater(result["total_max_eur"], result["total_min_eur"])

    def test_verdetto_within_tight_over(self):
        self.assertEqual(self._full(budget_eur=5000.0)["budget_verdict"], "within")
        self.assertEqual(self._full(budget_eur=10.0)["budget_verdict"], "over")
        result = self._full()
        tight = self._full(budget_eur=(result["total_min_eur"] + result["total_max_eur"]) / 2)
        self.assertEqual(tight["budget_verdict"], "tight")

    def test_senza_righe_nessun_verdetto(self):
        result = estimate_costs({"days": []}, _trip(), [], [])
        self.assertIsNone(result["budget_verdict"])

    def test_nota_esclusioni_dichiarata_esplicitamente(self):
        note = self._full()["excluded_note"]
        for atteso in ("trasporti locali", "assicurazione", "imprevisti"):
            self.assertIn(atteso, note)

    def test_notti_riportate(self):
        self.assertEqual(self._full()["nights"], 3)


class TestRobustness(unittest.TestCase):
    def test_input_malformati_non_sollevano_mai(self):
        for itinerary in (None, {}, {"days": None}, {"days": "x"}, {"days": [None, 3]},
                          {"days": [{"blocks": None}]}, {"days": [{"blocks": [None, "x"]}]},
                          {"days": [{"blocks": [{"poi_id": 5}]}]}):
            with self.subTest(itinerary=itinerary):
                result = estimate_costs(itinerary, _trip(), [HOTEL], [RISTORANTE])
                self.assertIn("total_min_eur", result)

    def test_liste_none_accettate(self):
        result = estimate_costs(_itinerary(["R1"]), _trip(), None, None)
        self.assertEqual(result["lines"], [])

    def test_budget_non_numerico_non_produce_verdetto(self):
        trip = _trip()
        trip.budget_eur = "molto"
        result = estimate_costs(_itinerary(["R1"]), trip, [], [RISTORANTE])
        self.assertIsNone(result["budget_eur"])
        self.assertIsNone(result["budget_verdict"])


if __name__ == "__main__":
    unittest.main()
