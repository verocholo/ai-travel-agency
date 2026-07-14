import json
import unittest
from pathlib import Path
from unittest.mock import patch
import requests
from src.schemas import Hotel, POI
from src.distance_matrix import (
    build_points, map_distance_matrix_response, MAX_POI_POINTS,
    get_distance_matrix, get_distance_matrix_multi_mode, fetch_distance_matrix_raw,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "mock_api_responses"


class TestBuildPoints(unittest.TestCase):
    def test_hard_cap_1_hotel_9_poi(self):
        hotels = [Hotel(id=f"H{i}", name="x", lat=0, lng=0) for i in range(3)]
        pois = [POI(id=f"P{i}", type="restaurant", name="x", lat=0, lng=0) for i in range(15)]
        points = build_points(hotels, pois)
        self.assertEqual(len(points), 1 + MAX_POI_POINTS)
        self.assertEqual(points[0]["id"], "H0")  # solo il primo hotel

    def test_fewer_poi_than_cap(self):
        hotels = [Hotel(id="H1", name="x", lat=0, lng=0)]
        pois = [POI(id="P1", type="restaurant", name="x", lat=0, lng=0)]
        points = build_points(hotels, pois)
        self.assertEqual(len(points), 2)

    def test_no_hotels_no_anchor_point(self):
        points = build_points([], [POI(id="P1", type="restaurant", name="x", lat=0, lng=0)])
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["id"], "P1")


class TestMapDistanceMatrixResponse(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((FIXTURES / "distance_matrix_response.json").read_text())
        self.points = [{"id": "H1", "coord": "0,0"}, {"id": "POI1", "coord": "0,0"},
                       {"id": "POI2", "coord": "0,0"}, {"id": "POI3", "coord": "0,0"}]

    def test_diagonal_discarded(self):
        travel_times = map_distance_matrix_response(self.data, self.points)
        pairs = [(t.origin_id, t.dest_id) for t in travel_times]
        for p in self.points:
            self.assertNotIn((p["id"], p["id"]), pairs)

    def test_count_matches_off_diagonal(self):
        # matrice 4x4 -> 16 elementi - 4 diagonale = 12 off-diagonal, tutti status OK nel mock
        travel_times = map_distance_matrix_response(self.data, self.points)
        self.assertEqual(len(travel_times), 12)

    def test_minutes_rounded_from_seconds(self):
        travel_times = {(t.origin_id, t.dest_id): t.minutes for t in
                         map_distance_matrix_response(self.data, self.points)}
        self.assertEqual(travel_times[("H1", "POI1")], 13)  # 780s / 60 = 13.0

    def test_status_not_ok_discarded(self):
        data = {
            "rows": [
                {"elements": [{"status": "OK", "duration": {"value": 0}},
                               {"status": "ZERO_RESULTS"}]},
                {"elements": [{"status": "OK", "duration": {"value": 300}},
                               {"status": "OK", "duration": {"value": 0}}]},
            ]
        }
        points = [{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}]
        result = map_distance_matrix_response(data, points)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].origin_id, "B")

    def test_duration_in_traffic_preferred_over_duration(self):
        # [AGGIUNTO 2026-07-10] Gap reale: la fixture distance_matrix_response.json
        # non ha mai incluso duration_in_traffic, quindi il ramo che lo preferisce
        # a duration (righe 35-37 di src/distance_matrix.py) non era mai stato
        # esercitato da nessun test — solo dalla prima chiamata live reale su San
        # Quirico d'Orcia (che passa departure_time=now e quindi lo riceve sempre).
        # Verificato lì a mano cifra per cifra prima di aggiungere questo test.
        data = {
            "rows": [
                {"elements": [
                    {"status": "OK", "duration": {"value": 0}},
                    {"status": "OK", "duration": {"value": 600}, "duration_in_traffic": {"value": 900}},
                ]},
                {"elements": [
                    {"status": "OK", "duration": {"value": 600}, "duration_in_traffic": {"value": 900}},
                    {"status": "OK", "duration": {"value": 0}},
                ]},
            ]
        }
        points = [{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}]
        result = {(t.origin_id, t.dest_id): t.minutes for t in map_distance_matrix_response(data, points)}
        self.assertEqual(result[("A", "B")], 15)  # 900s/60=15, non 600s/60=10


class TestMultiModeDistanceMatrix(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-11 — capstone live test] Bug reale scoperto sul primo
    test dal vivo mai eseguito su un centro storico pedonale (Repubblica di
    San Marino, modulo famiglia): interrogando la Distance Matrix in SOLA
    modalità "driving", ogni coppia di punti tornava a 0 minuti — tecnicamente
    corretto per distanze di poche centinaia di metri, ma fuorviante per
    FRICTION_SAFETY (che protegge esplicitamente da salite/camminate lunghe:
    "0 min in auto" nasconde scalini/dislivelli reali). Fix: interrogare
    ANCHE "walking" e lasciare a Claude la scelta di quale tempo comunicare
    (vedi SYSTEM_PROMPT_MASTER.md §[HARD_CONSTRAINTS] punto 2). Questi test
    coprono solo il livello dati (mai stato esercitato prima) — se Claude
    sceglie bene tra i due è verificato a mano sul run reale, stesso
    principio di onestà già dichiarato altrove per i criteri "soft".
    """

    def _ok_response(self, seconds: int) -> dict:
        return {
            "status": "OK",
            "rows": [
                {"elements": [{"status": "OK", "duration": {"value": 0}},
                               {"status": "OK", "duration": {"value": seconds}}]},
                {"elements": [{"status": "OK", "duration": {"value": seconds}},
                               {"status": "OK", "duration": {"value": 0}}]},
            ],
        }

    def test_fetch_distance_matrix_raw_passes_mode_param(self):
        captured = {}

        def fake_get(url, params, timeout):
            captured.update(params)
            class FakeResp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {"status": "OK", "rows": []}
            return FakeResp()

        with patch("src.distance_matrix.requests.get", side_effect=fake_get):
            fetch_distance_matrix_raw([{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}],
                                       "key", mode="walking")
        self.assertEqual(captured["mode"], "walking")
        self.assertNotIn("departure_time", captured)  # solo "driving" lo usa

    def test_fetch_distance_matrix_raw_driving_includes_departure_time(self):
        captured = {}

        def fake_get(url, params, timeout):
            captured.update(params)
            class FakeResp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {"status": "OK", "rows": []}
            return FakeResp()

        with patch("src.distance_matrix.requests.get", side_effect=fake_get):
            fetch_distance_matrix_raw([{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}],
                                       "key", mode="driving")
        self.assertEqual(captured["departure_time"], "now")

    def test_map_distance_matrix_response_tags_entries_with_given_mode(self):
        points = [{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}]
        travel_times = map_distance_matrix_response(self._ok_response(180), points, mode="walking")
        self.assertTrue(all(t.mode == "walking" for t in travel_times))

    def test_get_distance_matrix_multi_mode_combines_both_modes(self):
        points = [{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}]

        def fake_get_distance_matrix(pts, api_key, mode="driving"):
            seconds = 20 if mode == "driving" else 200  # driving arrotonda a 0, walking no
            return map_distance_matrix_response(self._ok_response(seconds), pts, mode=mode)

        with patch("src.distance_matrix.get_distance_matrix", side_effect=fake_get_distance_matrix):
            combined = get_distance_matrix_multi_mode(points, "key")
        modes_present = {t.mode for t in combined}
        self.assertEqual(modes_present, {"driving", "walking"})
        driving_minutes = {t.minutes for t in combined if t.mode == "driving"}
        walking_minutes = {t.minutes for t in combined if t.mode == "walking"}
        self.assertEqual(driving_minutes, {0})  # 20s arrotonda a 0 min — il bug reale
        self.assertEqual(walking_minutes, {3})  # 200s arrotonda a 3 min — dato utile

    def test_get_distance_matrix_multi_mode_tolerates_secondary_mode_failure(self):
        # [AGGIUNTO 2026-07-11] Se "walking" fallisce (es. non disponibile
        # per quella coppia di coordinate), il Nodo 4 non deve fallire per
        # intero: la modalità primaria "driving" resta comunque utilizzabile
        # — stesso principio di resilienza già applicato a un singolo place/
        # hotel malformato altrove nel prototipo (places_client.py,
        # liteapi_client.py).
        points = [{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}]

        def fake_get_distance_matrix(pts, api_key, mode="driving"):
            if mode == "walking":
                raise RuntimeError("Distance Matrix fallita (mode=walking): status=ZERO_RESULTS")
            return map_distance_matrix_response(self._ok_response(300), pts, mode=mode)

        with patch("src.distance_matrix.get_distance_matrix", side_effect=fake_get_distance_matrix):
            combined = get_distance_matrix_multi_mode(points, "key")
        # [CORRETTO 2026-07-13 — audit di revisione completa, gap di
        # mutation-testing trovato dall'agente di audit qualità test]
        # `assertTrue(len(combined) > 0)` è debole: passerebbe anche se
        # una mutazione duplicasse le entry, ne perdesse una, o ne
        # aggiungesse di spurie — non avrebbe rilevato nulla del genere.
        # Con 2 punti (A, B) e "walking" fallito, restano esattamente le 2
        # entry off-diagonale di "driving" (A->B e B->A, vedi
        # `map_distance_matrix_response`, che scarta solo la diagonale).
        self.assertEqual(len(combined), 2)
        self.assertTrue(all(t.mode == "driving" for t in combined))
        pairs = {(t.origin_id, t.dest_id) for t in combined}
        self.assertEqual(pairs, {("A", "B"), ("B", "A")})

    def test_get_distance_matrix_multi_mode_tolerates_secondary_mode_network_failure(self):
        # [AGGIUNTO 2026-07-11 — audit di qualità, secondo giro] Il test
        # gemello sopra (`..._tolerates_secondary_mode_failure`) copre solo
        # il caso "Google risponde ma status != OK" (RuntimeError). Il bug
        # reale appena corretto in get_distance_matrix_multi_mode() era
        # un'altra causa di fallimento della modalità secondaria: un errore
        # HTTP/di rete vero e proprio (timeout, 5xx, connessione caduta),
        # che fetch_distance_matrix_raw() solleva come
        # requests.exceptions.RequestException, NON RuntimeError. Prima del
        # fix, questo tipo di eccezione non veniva catturato qui e faceva
        # fallire l'intero Nodo 4 — buttando via anche i risultati "driving"
        # già ottenuti con successo. Questo test verifica specificamente
        # quel caso, che nessun test precedente esercitava.
        points = [{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}]

        def fake_get_distance_matrix(pts, api_key, mode="driving"):
            if mode == "walking":
                raise requests.exceptions.Timeout("simulato: timeout su mode=walking")
            return map_distance_matrix_response(self._ok_response(300), pts, mode=mode)

        with patch("src.distance_matrix.get_distance_matrix", side_effect=fake_get_distance_matrix):
            combined = get_distance_matrix_multi_mode(points, "key")
        # [CORRETTO 2026-07-13 — audit di revisione completa, stesso gap
        # di mutation-testing del test gemello sopra] Stessa assertion
        # esatta, non solo "non vuoto".
        self.assertEqual(len(combined), 2)
        self.assertTrue(all(t.mode == "driving" for t in combined))
        pairs = {(t.origin_id, t.dest_id) for t in combined}
        self.assertEqual(pairs, {("A", "B"), ("B", "A")})

    def test_get_distance_matrix_multi_mode_primary_mode_failure_propagates(self):
        # Se invece fallisce "driving" (la modalità primaria/storica), il
        # fallimento deve propagare normalmente — run_live() lo intercetta
        # già come data_layer_error, stesso comportamento pre-esistente.
        points = [{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}]

        def fake_get_distance_matrix(pts, api_key, mode="driving"):
            if mode == "driving":
                raise RuntimeError("Distance Matrix fallita (mode=driving): status=INVALID_REQUEST")
            return map_distance_matrix_response(self._ok_response(300), pts, mode=mode)

        with patch("src.distance_matrix.get_distance_matrix", side_effect=fake_get_distance_matrix):
            with self.assertRaises(RuntimeError):
                get_distance_matrix_multi_mode(points, "key")

    def test_get_distance_matrix_multi_mode_fewer_than_2_points_returns_empty(self):
        self.assertEqual(get_distance_matrix_multi_mode([{"id": "A", "coord": "0,0"}], "key"), [])


class TestGetDistanceMatrixSingleMode(unittest.TestCase):
    """
    [AGGIUNTO 2026-07-12 — gap di copertura reale trovato nell'audit di
    potenziamento massimo] `get_distance_matrix()` (modalità singola) era
    esercitata SOLO indirettamente dai test di
    `get_distance_matrix_multi_mode`, che la mockano via
    `patch("src.distance_matrix.get_distance_matrix", ...)` — quindi il suo
    corpo reale (chiamata a `fetch_distance_matrix_raw`, controllo
    `status != OK`, delega a `map_distance_matrix_response`) non era mai
    stato esercitato da un test diretto.
    """

    def _points(self):
        return [{"id": "A", "coord": "0,0"}, {"id": "B", "coord": "0,0"}]

    def test_fewer_than_2_points_returns_empty_without_any_http_call(self):
        with patch("src.distance_matrix.requests.get") as mock_get:
            result = get_distance_matrix([{"id": "A", "coord": "0,0"}], "key")
        self.assertEqual(result, [])
        mock_get.assert_not_called()

    def test_status_ok_delegates_to_mapping(self):
        data = {
            "status": "OK",
            "rows": [
                {"elements": [{"status": "OK", "duration": {"value": 0}},
                               {"status": "OK", "duration": {"value": 300}}]},
                {"elements": [{"status": "OK", "duration": {"value": 300}},
                               {"status": "OK", "duration": {"value": 0}}]},
            ],
        }
        with patch("src.distance_matrix.fetch_distance_matrix_raw", return_value=data) as mock_fetch:
            result = get_distance_matrix(self._points(), "key", mode="driving")
        mock_fetch.assert_called_once_with(self._points(), "key", mode="driving")
        self.assertEqual(len(result), 2)
        self.assertTrue(all(t.mode == "driving" for t in result))

    def test_status_not_ok_raises_runtime_error_with_mode_in_message(self):
        data = {"status": "OVER_QUERY_LIMIT", "rows": []}
        with patch("src.distance_matrix.fetch_distance_matrix_raw", return_value=data):
            with self.assertRaises(RuntimeError) as ctx:
                get_distance_matrix(self._points(), "key", mode="walking")
        self.assertIn("walking", str(ctx.exception))
        self.assertIn("OVER_QUERY_LIMIT", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
