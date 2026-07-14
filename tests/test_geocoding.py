import unittest
from unittest.mock import patch
from src.geocoding import (
    parse_geocoding_response,
    parse_geocoding_response_full,
    is_imprecise_match,
    GeocodingError,
    _geocode_params,
    _should_bypass_region_bias,
    geocode,
    geocode_full,
)


class TestParseGeocodingResponse(unittest.TestCase):
    def test_ok(self):
        data = {
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": 43.07, "lng": 11.61}}}],
        }
        lat, lng = parse_geocoding_response(data)
        self.assertAlmostEqual(lat, 43.07)
        self.assertAlmostEqual(lng, 11.61)

    def test_zero_results_raises(self):
        data = {"status": "ZERO_RESULTS", "results": []}
        with self.assertRaises(GeocodingError):
            parse_geocoding_response(data)

    def test_ok_status_but_empty_results_raises(self):
        data = {"status": "OK", "results": []}
        with self.assertRaises(GeocodingError):
            parse_geocoding_response(data)

    def test_ok_status_but_malformed_shape_raises_geocoding_error_not_keyerror(self):
        # [AGGIUNTO 2026-07-11 — audit qualità pre-lancio] Prima, uno
        # status="OK" con un campo "geometry"/"location" mancante (schema
        # inatteso, es. un futuro cambio API) faceva crashare con un
        # KeyError grezzo invece del GeocodingError esplicito usato per
        # tutti gli altri casi di fallimento di questa stessa funzione.
        data = {"status": "OK", "results": [{"geometry": {}}]}
        with self.assertRaises(GeocodingError):
            parse_geocoding_response(data)


class TestParseGeocodingResponseFull(unittest.TestCase):
    """[AGGIUNTO 2026-07-10] Copre il bug reale di Fase 3: un match "OK" ma
    impreciso (nome di valle senza centro univoco) non va propagato in
    silenzio — vedi nota in src/geocoding.py."""

    def test_precise_match_rooftop(self):
        data = {
            "status": "OK",
            "results": [{
                "geometry": {"location": {"lat": 43.07, "lng": 11.61}, "location_type": "ROOFTOP"},
                "formatted_address": "Via Roma 1, San Quirico d'Orcia SI, Italia",
            }],
        }
        result = parse_geocoding_response_full(data)
        self.assertEqual(result["location_type"], "ROOFTOP")
        self.assertFalse(is_imprecise_match(result["location_type"]))

    def test_imprecise_match_geometric_center(self):
        # Caso reale: "Val d'Orcia, Toscana" -> GEOMETRIC_CENTER, geocodificato
        # a 60-70km dal luogo reale nonostante status "OK".
        data = {
            "status": "OK",
            "results": [{
                "geometry": {"location": {"lat": 43.567, "lng": 10.981}, "location_type": "GEOMETRIC_CENTER"},
                "formatted_address": "Valdelsa, Toscana, Italia",
            }],
        }
        result = parse_geocoding_response_full(data)
        self.assertTrue(is_imprecise_match(result["location_type"]))

    def test_imprecise_match_approximate(self):
        self.assertTrue(is_imprecise_match("APPROXIMATE"))

    def test_precise_match_range_interpolated(self):
        self.assertFalse(is_imprecise_match("RANGE_INTERPOLATED"))

    def test_missing_location_type_defaults_unknown_not_precise(self):
        data = {
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": 43.07, "lng": 11.61}}}],
        }
        result = parse_geocoding_response_full(data)
        self.assertEqual(result["location_type"], "UNKNOWN")
        # UNKNOWN non è nella lista "imprecisi" esplicita, ma nemmeno
        # confermato preciso: is_imprecise_match ritorna False qui perché il
        # controllo è positivo/esplicito (whitelist dei valori noti come
        # precisi verrebbe sbagliata se Google aggiunge nuovi valori) — ma
        # va comunque trattato con cautela in produzione (assenza di dato,
        # non conferma di precisione).
        self.assertFalse(is_imprecise_match(result["location_type"]))


class TestRegionBiasBypass(unittest.TestCase):
    """[AGGIUNTO 2026-07-11 — audit di qualità, secondo giro] Fix
    strutturale per il bug reale scoperto nel capstone test famiglia: il
    bias hardcoded region="it" spingeva Google a risolvere "San Marino"
    verso un'omonima località italiana vicino Carpi invece della vera
    Repubblica di San Marino. Per una lista chiusa di enclave/microstati
    noti, il parametro `region` va omesso del tutto (non solo scelto
    diversamente) — vedi la nota estesa in src/geocoding.py."""

    def test_san_marino_bypasses_region_bias(self):
        self.assertTrue(_should_bypass_region_bias("San Marino"))
        self.assertTrue(_should_bypass_region_bias("Repubblica di San Marino"))

    def test_vatican_bypasses_region_bias(self):
        self.assertTrue(_should_bypass_region_bias("Città del Vaticano"))
        self.assertTrue(_should_bypass_region_bias("vaticano"))

    def test_case_and_whitespace_insensitive(self):
        self.assertTrue(_should_bypass_region_bias("  SAN MARINO  "))

    def test_ordinary_italian_destination_does_not_bypass(self):
        self.assertFalse(_should_bypass_region_bias("Firenze, Toscana"))
        self.assertFalse(_should_bypass_region_bias("Forte dei Marmi"))

    def test_substring_containing_bypass_name_does_not_false_positive(self):
        # Un match troppo permissivo (substring) userebbe questa stessa
        # lista per bypassare il bias su un indirizzo italiano reale che
        # contiene "San Marino" come parte del nome — reintroducendo un
        # rischio invece di eliminarlo. Il confronto deve essere esatto.
        self.assertFalse(_should_bypass_region_bias("Via San Marino 4, Roma"))

    def test_geocode_params_omits_region_for_bypass_name(self):
        params = _geocode_params("Repubblica di San Marino", "fake-key")
        self.assertNotIn("region", params)
        self.assertEqual(params["address"], "Repubblica di San Marino")

    def test_geocode_params_keeps_region_it_for_ordinary_destination(self):
        params = _geocode_params("Firenze, Toscana", "fake-key")
        self.assertEqual(params["region"], "it")

    def test_geocode_uses_bypassed_params_for_san_marino(self):
        captured = {}

        def fake_get(url, params, timeout):
            captured.update(params)
            class FakeResp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {"status": "OK", "results": [{"geometry": {"location": {"lat": 43.94, "lng": 12.45}}}]}
            return FakeResp()

        with patch("src.geocoding.requests.get", side_effect=fake_get):
            geocode("Repubblica di San Marino", "fake-key")
        self.assertNotIn("region", captured)

    def test_geocode_full_keeps_region_for_ordinary_destination(self):
        captured = {}

        def fake_get(url, params, timeout):
            captured.update(params)
            class FakeResp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {"status": "OK", "results": [{"geometry": {"location": {"lat": 43.07, "lng": 11.61}}}]}
            return FakeResp()

        with patch("src.geocoding.requests.get", side_effect=fake_get):
            geocode_full("Forte dei Marmi, Toscana", "fake-key")
        self.assertEqual(captured["region"], "it")


if __name__ == "__main__":
    unittest.main()
