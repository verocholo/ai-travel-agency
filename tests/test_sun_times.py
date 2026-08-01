"""
[AGGIUNTO 2026-07-31 — aggiunta mia ("stupiscimi"), al servizio della
direttrice "meteo, luce e stagione"] Copre src/sun_times.py.

Astronomia deterministica: i valori attesi qui sotto sono confrontati con
fonti astronomiche pubbliche entro una tolleranza di pochi minuti (l'algoritmo
NOAA semplificato non pretende la precisione al secondo, e per decidere se il
belvedere è meglio alle 18 o alle 20 non serve).
"""
import unittest
from datetime import date

from src.sun_times import (
    PolarDayNight, describe_light, estimate_utc_offset_hours, local_times,
    sun_events_utc, _solar_event_julian,
)

FIRENZE = (43.7696, 11.2558)
TROMSO = (69.6492, 18.9553)
QUITO = (-0.1807, -78.4678)


def _minutes(dt):
    return dt.hour * 60 + dt.minute


class TestSunEvents(unittest.TestCase):
    def test_solstizio_estate_firenze(self):
        events = sun_events_utc(date(2026, 6, 21), *FIRENZE)
        # ~03:32 UTC / ~19:00 UTC (05:32 / 21:00 ora legale italiana)
        self.assertAlmostEqual(_minutes(events["sunrise"]), 3 * 60 + 32, delta=5)
        self.assertAlmostEqual(_minutes(events["sunset"]), 19 * 60 + 0, delta=5)
        self.assertGreater(events["daylight_minutes"], 900)

    def test_solstizio_inverno_firenze_ha_molta_meno_luce(self):
        estate = sun_events_utc(date(2026, 6, 21), *FIRENZE)["daylight_minutes"]
        inverno = sun_events_utc(date(2026, 12, 21), *FIRENZE)["daylight_minutes"]
        self.assertLess(inverno, estate)
        self.assertAlmostEqual(inverno, 535, delta=15)

    def test_equinozio_circa_dodici_ore_ovunque(self):
        for lat, lng in (FIRENZE, QUITO):
            with self.subTest(lat=lat):
                minutes = sun_events_utc(date(2026, 3, 20), lat, lng)["daylight_minutes"]
                self.assertAlmostEqual(minutes, 720, delta=20)

    def test_ora_doro_dentro_le_ore_di_luce(self):
        events = sun_events_utc(date(2026, 6, 21), *FIRENZE)
        self.assertGreater(events["golden_morning_end"], events["sunrise"])
        self.assertLess(events["golden_evening_start"], events["sunset"])

    def test_notte_polare_non_solleva_ma_dichiara_none(self):
        events = sun_events_utc(date(2026, 12, 21), *TROMSO)
        self.assertIsNone(events["sunrise"])
        self.assertIsNone(events["sunset"])
        self.assertIsNone(events["daylight_minutes"])

    def test_sole_di_mezzanotte_non_solleva(self):
        events = sun_events_utc(date(2026, 6, 21), *TROMSO)
        self.assertIsNone(events["sunrise"])

    def test_l_equazione_grezza_solleva_invece_di_mentire(self):
        # `sun_events_utc` protegge il chiamante; la primitiva sottostante
        # deve essere esplicita, non restituire un numero inventato.
        with self.assertRaises(PolarDayNight):
            _solar_event_julian(date(2026, 12, 21), TROMSO[0], TROMSO[1], -0.833, True)


class TestLocalTimes(unittest.TestCase):
    def test_offset_applicato(self):
        events = sun_events_utc(date(2026, 6, 21), *FIRENZE)
        times = local_times(events, 2)
        self.assertEqual(times["sunrise"], "05:32")
        self.assertEqual(times["sunset"], "21:00")

    def test_offset_ignoto_non_indovina(self):
        events = sun_events_utc(date(2026, 6, 21), *FIRENZE)
        self.assertEqual(set(local_times(events, None).values()), {""})

    def test_offset_frazionario_supportato(self):
        events = sun_events_utc(date(2026, 6, 21), *FIRENZE)
        self.assertNotEqual(local_times(events, 5.5)["sunrise"], "")

    def test_eventi_none_diventano_stringhe_vuote(self):
        self.assertEqual(local_times({"sunrise": None, "sunset": None}, 2)["sunrise"], "")


class TestEstimateOffset(unittest.TestCase):
    def test_longitudine_italiana_da_uno(self):
        self.assertEqual(estimate_utc_offset_hours(11.25), 1)

    def test_longitudine_negativa_da_offset_negativo(self):
        self.assertEqual(estimate_utc_offset_hours(-78.4), -5)


class TestDescribeLight(unittest.TestCase):
    def test_riga_pronta_per_il_pdf(self):
        light = describe_light(date(2026, 6, 21), *FIRENZE, utc_offset_hours=2)
        self.assertTrue(light["available"])
        self.assertFalse(light["approximate"])
        self.assertEqual(light["sunrise"], "05:32")
        self.assertIn("di luce", light["daylight_label"])

    def test_senza_offset_dichiarato_come_approssimato(self):
        light = describe_light(date(2026, 6, 21), *FIRENZE)
        self.assertTrue(light["approximate"])
        self.assertTrue(light["available"])

    def test_notte_polare_dichiarata_non_disponibile(self):
        self.assertFalse(describe_light(date(2026, 12, 21), *TROMSO)["available"])

    def test_coordinate_non_numeriche_non_sollevano(self):
        self.assertFalse(describe_light(date(2026, 6, 21), None, None)["available"])
        self.assertFalse(describe_light(date(2026, 6, 21), "a", "b")["available"])


if __name__ == "__main__":
    unittest.main()
